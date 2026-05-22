"""Keeper agent — orchestrates the turn: parse → judge → enrich → intent → curate."""
from __future__ import annotations
from typing import Any
import json
import re
from concurrent.futures import ThreadPoolExecutor

from scenario_core import ScenarioWorld, Entity
from game.side_effects import (
    parse_markup_all,
    ItemGain, ConsumeItem, StatChange, SpawnEnemy, GrantWeapon, SceneWeapon,
    NPCStateChange, NPCFollow,
)
from ..messages import (
    ActionIntent, ActionOutcome, NarratorBrief,
    AuthorRequest, StructuralEdit, ModulePatch, TurnInput,
    CombatEntryCheck, StandoffMatch, CombatInit,
    TimeCommsPacket,
)
from ..judge import Judge
from ..curator import Curator
from ..intent_detector import IntentDetector
from prompts import build_keeper_parse_prompt, build_keeper_enrich_prompt
from llm import call_deepseek


class Keeper:
    """Keeper agent. Owns L2 + ScenarioWorld, coordinates the turn.

    Must never: output directly to player.
    """

    MAX_ESCALATION_DEPTH = 3

    def __init__(
        self,
        world: ScenarioWorld,
        phase1: dict | None = None,
    ):
        self.world = world
        self.phase1 = phase1 or {}
        self._last_comms_time = 0

        self.intent_detector = IntentDetector()

        self.judge = Judge(world)
        self.curator = Curator(world)
        self.turn_number = 0
        self._warnings: list[str] = []  # per-turn LLM error warnings surfaced to player
        self._recent_intents: list[str] = []  # last N intent strings for duplicate suppression
        self._intent_cooldown: int = 3

    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse → judge → enrich → curate."""
        if _depth >= self.MAX_ESCALATION_DEPTH:
            # Guard against infinite recursion — re-execute deterministically
            return self._process_deterministic_only(turn_input)
        self.turn_number += 1
        raw = turn_input.raw_text
        self._warnings.clear()

        # NPC interaction routing: if user input targets a known NPC, route to NPCManager
        if self.world.npcs:
            npcs_present = self.world.npcs.get_in_scene(self.world.current_location)
            for npc in npcs_present:
                # Simple heuristic: NPC name or role keywords in user input
                if npc.name in raw:
                    response = self.world.npcs.talk_to(npc.name, raw, lambda prompt, **kw: call_deepseek(prompt, **kw))
                    return {"brief": response, "narrative": response, "full": response}

        # Step 1: Parse (LLM) — entity matching + NL requirement evaluation
        parse_result = self._parse(raw)

        # Launch IntentDetector early if there are "other" entries
        other_entries = [e for e in parse_result if e.get("type") == "other"]
        detect_future = None
        executor = None
        if other_entries and author:
            other_text = "; ".join(e.get("text", "") for e in other_entries)
            world_snapshot = self._build_world_snapshot()
            executor = ThreadPoolExecutor(max_workers=1)
            detect_future = executor.submit(
                self.intent_detector.detect, other_text, world_snapshot
            )

        # Step 2: Judge (deterministic) — flag check, skill check, ##GRADED##
        all_outcomes = []
        judged_entities = []  # for enrich prompt
        for entry in parse_result:
            entry_type = entry.get("type", "")
            if entry_type in ("auto_trigger", "interaction", "event"):
                eid = entry.get("id", "")
                entity = self._find_entity_by_id(eid)
                if not entity:
                    continue
                intent = ActionIntent(
                    action=entry_type if entry_type != "auto_trigger" else "other",
                    target=entity.name if entry_type == "interaction" else "",
                )
                outcome = self.judge._execute_entity(entity, intent=intent, player_input=raw)
                self._apply_side_effects(outcome.side_effects)
                # Time advancement for entity execution
                if outcome.success:
                    time_delta = self._resolve_time_delta(entity)
                    self.world.clock.advance_time(time_delta)
                all_outcomes.append(outcome)
                if outcome.success:
                    judged_entities.append({
                        "entity_type": entity.entity_type,
                        "id": entity.id,
                        "name": entity.name,
                        "result": outcome.message,
                        "success": True,
                        "skill_tier": outcome.skill_tier,
                    })
            elif entry_type == "move":
                target = entry.get("target", "")
                result = self.world.move(target)
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="move", target=target),
                    success=result.success, message=result.message,
                    side_effects=result.side_effects,
                ))
                self._apply_side_effects(result.side_effects)
                if result.success:
                    self.world.clock.advance_time(3)  # default move: ~3 min
            elif entry_type == "search":
                # Search always performs a 侦查 (Spot Hidden) check.
                # No dependency check, no flag update, no enrich.
                if self.world.player:
                    ok, skill_msg, tier = self.world.player.check_skill("侦查", "regular")
                    skill_detail = (
                        f"[SEARCH] 侦查检定 | 等级={tier} | {'成功' if ok else '失败'}\n"
                        f"  {skill_msg}"
                    )
                    from prompts import log_skill_result
                    log_skill_result(skill_detail)
                    # Trait enhancement for search
                    inv_desc = getattr(self.world.player, 'personal_description', '') or \
                               getattr(self.world.player, 'description', '')
                    if inv_desc:
                        from llm import evaluate_trait_enhancement
                        roll_m = re.search(r'D100=(\d+)/', skill_msg)
                        dice_roll = int(roll_m.group(1)) if roll_m else 0
                        skill_val = self.world.player.get_skill_value("侦查") if self.world.player else 0
                        enh = evaluate_trait_enhancement(
                            inv_desc=inv_desc,                             skill_name="侦查", skill_detail=skill_msg,
                            dice_roll=dice_roll, skill_value=skill_val,
                            entity_name="搜索",
                            search_context=True,
                            player_input=raw,
                        )
                        new_tier = enh.get("tier", tier)
                        if new_tier != tier:
                            skill_detail += f"\n  [特质修正] {tier} → {new_tier}：{enh.get('reason', '')}"
                            log_skill_result(skill_detail)
                            tier = new_tier
                            ok = (tier != "failure")
                    if ok:
                        interactions = self.world.get_available_interactions()
                        done = self.world.completed_interactions.get(self.world.current_location, set())
                        available = [i for i in interactions if i.name not in done]
                        if available:
                            lines = ["（环顾四周，注意到可以做的事：）"]
                            for inter in available:
                                lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
                            msg = "\n".join(lines)
                        else:
                            msg = "（仔细查看四周，没有特别的发现）"
                        # Weapon discovery: check if scene has weapons
                        scene_weps = self.world.scene_weapons.get(
                            self.world.current_location, []
                        )
                        if scene_weps:
                            wep_names = "、".join(
                                f"{f'{sw.quantity}把 ' if sw.quantity > 1 else ''}{sw.weapon_ref}"
                                for sw in scene_weps
                            )
                            msg += f'\n\n（你发现了 {wep_names}。输入“拾取 <武器名>”来获得它）'
                    else:
                        msg = "（你环顾四周，但昏暗的光线让你无法看清任何有用的东西）"
                else:
                    msg = "（仔细查看四周，没有特别的发现）"
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="search"), success=True, message=msg,
                    entity_id="SEARCH", entity_type="search",
                    skill_tier=tier if self.world.player else "",
                    skill_detail=skill_detail if self.world.player else ""))
                # Advance time for search
                self.world.clock.advance_time(10 if (self.world.player and ok) else 5)
            elif entry_type == "other":
                text = entry.get("text", "")
                scene = self.world.current_location
                scene_weps = self.world.scene_weapons.get(scene, [])
                picked_up = False
                for sw in list(scene_weps):  # iterate copy since we mutate
                    if sw.weapon_ref.lower() in text.lower() and \
                       ("拾取" in text or "捡" in text or "拿" in text or "pick" in text.lower()):
                        # Look up weapon stats from library
                        if self.world.weapon_library:
                            lib_wep = self.world.weapon_library.get(sw.weapon_ref)
                            if lib_wep:
                                from investigator.models import Weapon
                                inv_wep = Weapon(
                                    name=lib_wep.name,
                                    skill_name=lib_wep.skill_name,
                                    damage=lib_wep.damage,
                                    range=lib_wep.range,
                                    malfunction=lib_wep.malfunction,
                                )
                                self.world.player.add_weapon(inv_wep)
                        scene_weps.remove(sw)
                        if not scene_weps:
                            del self.world.scene_weapons[scene]
                        all_outcomes.append(ActionOutcome(
                            intent=ActionIntent(action="pickup", target=sw.weapon_ref),
                            success=True,
                            message=f"你拾起了{sw.weapon_ref}。",
                        ))
                        picked_up = True
                        break
                if not picked_up:
                    all_outcomes.append(ActionOutcome(
                        intent=ActionIntent(action="other"), success=True,
                        message=f"（{text}）"))
            else:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=True,
                    message=f"（{entry.get('text', '没有特别的事情发生')}）"))

        # Boss "at" check: after scene change
        if self.world.bosses:
            at_bosses = self.world.bosses.check_by_engage_type("at", scene=self.world.current_location)
            for boss_entity in at_bosses:
                if self._check_boss_requirements(boss_entity):
                    combat_init = self.world.bosses.build_combat_init(boss_entity, self.world.player, self.world.current_location)
                    self.world.bosses.set_active(boss_entity["id"])
                    return {"combat_init": combat_init, "brief": "", "narrative": ""}

        # Step 2.5: Combat entry detection — deterministic gate + LLM (parallel with enrich)
        combat_future = None
        combat_executor = None
        enemy_ctx = None
        if self.world and self.world.enemies and not self.world.enemies._combat_active:
            enemy_ctx = self.world.enemies.get_combat_context(
                self.world.current_location, self.world.graph
            )
        if enemy_ctx:
            outcomes_summary = "\n".join(
                f"[{o.entity_type}] {o.message}" for o in all_outcomes
            )
            from prompts import build_combat_entry_prompt
            combat_prompt = build_combat_entry_prompt(
                player_input=raw,
                outcomes_summary=outcomes_summary,
                enemy_context=enemy_ctx,
                current_scene=self.world.current_location,
            )
            combat_executor = ThreadPoolExecutor(max_workers=1)
            combat_future = combat_executor.submit(
                call_deepseek,
                combat_prompt,
                json_mode=True,
                model="deepseek-v4-flash",
                reasoning_effort="low",
                system="你是 COC 7th KP 助理，负责判断是否进入战斗。",
                fallback_schema={"enter_combat": False, "enemy_instance_ids": [], "reasoning": ""},
            )

        # Step 3: Enrich (LLM) — describe and integrate
        emphasis = ""
        if judged_entities:
            enrichment = self._enrich(judged_entities, raw)
            emphasis = enrichment.get("emphasis_hint", "")
            reasoning = enrichment.get("reasoning", "")
            # Apply enriched results: string = merged narrative for first outcome
            results = enrichment.get("results", "")
            if isinstance(results, str) and results and all_outcomes:
                all_outcomes[0].message = results

        # Step 3.5: Collect combat entry result
        combat_entry = None
        if combat_future:
            try:
                raw_result = combat_future.result()
                result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                combat_entry = CombatEntryCheck(
                    enter_combat=result.get("enter_combat", False),
                    enemy_instance_ids=result.get("enemy_instance_ids", []),
                    reasoning=result.get("reasoning", ""),
                )
            except Exception:
                combat_entry = None
            finally:
                combat_executor.shutdown(wait=False)

        # Step 3.6: Build standoff_prompt or combat_init from combat_entry
        standoff_prompt = None
        combat_init_result = None
        if combat_entry and combat_entry.enter_combat:
            avoidable_by_ref: dict[str, list[str]] = {}
            hostile_iids: list[str] = []
            for iid in combat_entry.enemy_instance_ids:
                inst = self.world.enemies.get_by_id(iid) if self.world.enemies else None
                if inst and "avoidable" in inst.flags:
                    avoidable_by_ref.setdefault(inst.enemy_ref, []).append(iid)
                elif inst:
                    hostile_iids.append(iid)

            if avoidable_by_ref:
                standoff_prompt = {
                    "groups": {ref: iids for ref, iids in avoidable_by_ref.items()},
                    "current_group": next(iter(avoidable_by_ref)),
                    "hostile_iids": hostile_iids,
                    "all_enemy_iids": list(combat_entry.enemy_instance_ids),
                    "reasoning": combat_entry.reasoning,
                }
                first_ref = standoff_prompt["current_group"]
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="standoff"),
                    success=True,
                    message=f"你还有最后一次机会避免与{first_ref}的战斗——你要怎么做？",
                    entity_id="STANDOFF",
                    entity_type="standoff",
                ))
            elif hostile_iids:
                enemies = [self.world.enemies.get_by_id(iid)
                          for iid in hostile_iids
                          if self.world.enemies and self.world.enemies.get_by_id(iid)]
                if enemies and self.world.enemies:
                    self.world.enemies.enter_combat(hostile_iids)
                combat_init_result = CombatInit(
                    enemies=enemies,
                    player=self.world.player,
                    scene=self.world.current_location,
                    initiative_context=combat_entry.reasoning,
                )

        # TimeAgent trigger (after enrich, before curate)
        if self._should_trigger_time_agent():
            try:
                from game.agents.time_agent import TimeAgent
                ta = TimeAgent()
                tc_guideline = ""
                if self.world.time_costs:
                    import json as _json
                    tc_guideline = _json.dumps(self.world.time_costs, ensure_ascii=False)
                recent = self.world.memory.raw_history[-3:] if self.world.memory.raw_history else []
                recent_summary = "; ".join(
                    (r.get("user_input", "") or "")[:80] for r in recent
                )
                result = ta.assess(
                    game_time=self.world.clock.game_time,
                    day=self.world.clock.day,
                    time_of_day=self.world.clock.time_of_day,
                    hour=self.world.clock.hour,
                    recent_actions=recent_summary,
                    current_scene=self.world.current_location,
                    scene_description=self.world.get_current_description(),
                    time_costs_guideline=tc_guideline,
                )
                if result.get("time_delta", 0) > 0:
                    self.world.clock.advance_time(result["time_delta"])
                narrative = (result.get("narrative_hint", "") or "")
                signal = (result.get("signal_hint", "") or "")
                combined = f"{narrative} {signal}".strip()
                if combined:
                    self.world.clock.time_context = combined
                self._last_ta_call = self.world.clock.game_time
            except Exception:
                pass  # TimeAgent is best-effort

        # TimePressure comms dispatch (at most 1 per turn)
        tp = author.time_pressure if author else None
        if tp and self.world.clock.game_time - self._last_comms_time >= self.world.comms_interval:
            self._last_comms_time = self.world.clock.game_time
            try:
                recent = self.world.memory.raw_history[-5:] if self.world.memory.raw_history else []
                packet = TimeCommsPacket(
                    game_time=self.world.clock.game_time,
                    day=self.world.clock.day,
                    time_of_day=self.world.clock.time_of_day,
                    current_scene=self.world.current_location,
                    player_actions="; ".join(
                        (r.get("user_input", "") or "")[:60] for r in recent[-3:]
                    ),
                    world_state=f"场景:{self.world.current_location}, "
                               f"NPC:{self.world.npcs.all_names()[:3]}",
                )
                tp_result = author.assess_time_pressure(packet)
                if tp_result.get("should_press") and tp_result.get("signal"):
                    all_outcomes.append(ActionOutcome(
                        intent=ActionIntent(action="time_pressure"),
                        success=True,
                        message=f"【{tp.get('name', '时间压力')}】{tp_result.get('signal', '')}",
                        entity_id="TIME_PRESS",
                        entity_type="time_pressure",
                    ))
            except Exception:
                pass  # Comms is best-effort

        # Step 4: IntentDetector decision point (was Escalation check)
        if detect_future:
            try:
                intent_result = detect_future.result()
            except Exception:
                intent_result = None
                self._warnings.append("意图检测失败，流程无中断。")
            finally:
                executor.shutdown(wait=False)

            if intent_result and intent_result.needs_author and author:
                # Suppress duplicate intents within cooldown window
                intent_key = intent_result.intent.strip().lower()
                if intent_key not in [i.lower() for i in self._recent_intents[-self._intent_cooldown:]]:
                    self._recent_intents.append(intent_key)
                    self._recent_intents = self._recent_intents[-self._intent_cooldown:]
                    request = AuthorRequest(
                        other_texts=[e.get("text", "") for e in other_entries],
                        intent=intent_result.intent,
                        reasoning=intent_result.reasoning,
                        scene_context=self._build_scene_context_for_author(),
                    )
                    response = author.handle_request(request, self.turn_number)

                    if isinstance(response, StructuralEdit):
                        response = self._integrate_supplement(
                            response, author,
                            intent=request.intent, reasoning=request.reasoning,
                        )
                        if response.supplement_path:
                            return self.process_turn(turn_input, author, _depth + 1)
                    elif isinstance(response, ModulePatch):
                        if response.entities:
                            self._integrate_patch(response)
                            self._warnings.append(
                                f"模组已动态扩展：{response.justification[:60]}")
                            return self.process_turn(turn_input, author, _depth + 1)
                        else:
                            # Author rejected — inject player-visible narrative hint
                            rejection_msg = response.justification
                            if rejection_msg.startswith("REJECTED:"):
                                rejection_msg = rejection_msg[9:].strip()
                            all_outcomes.append(ActionOutcome(
                                intent=ActionIntent(action="other"), success=True,
                                message=f"（你尝试了，但{rejection_msg}）"))

        # Ending detection
        from scenario_core import has_ending as _has_ending
        ending_name = None
        ending_narrative = None
        for o in all_outcomes:
            en, ed = _has_ending(o.message)
            if en:
                ending_name = en
                ending_narrative = ed
                break

        # Inject LLM error warnings as player-visible outcomes
        for w in self._warnings:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"⚠ {w}"))

        # Boss "event" check: after judge completes
        if self.world.bosses:
            event_bosses = self.world.bosses.check_by_engage_type("event")
            for boss_entity in event_bosses:
                if self._check_boss_requirements(boss_entity):
                    combat_init = self.world.bosses.build_combat_init(boss_entity, self.world.player, self.world.current_location)
                    self.world.bosses.set_active(boss_entity["id"])
                    return {"combat_init": combat_init, "brief": "", "narrative": ""}

        # Step 5: Curate
        ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
        brief = self.curator.assemble(all_outcomes, ambient, emphasis)

        # Step 6: Memory (now handled in game_loop after narrator.narrate)
        if self.world.memory.should_compress():
            from threading import Thread
            t = Thread(target=self.world.memory.compress, args=(
                lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash",
                                        system="你是一个擅长总结和提炼信息的助手。请将游戏历史压缩为简洁摘要，"
                                               "保留关键事件、重要细节和当前状态，去除冗余对话。"),
            ), daemon=True)
            t.start()

        return {"brief": brief,
                "ending_name": ending_name, "ending_narrative": ending_narrative,
                "combat_entry": combat_entry,
                "standoff_prompt": standoff_prompt,
                "combat_init": combat_init_result}

    def resolve_standoff(self, standoff_state: dict, player_input: str) -> dict:
        """Resolve a standoff: semantic match -> D100 -> trait enhancement -> result."""
        from prompts import build_standoff_match_prompt
        from llm import evaluate_trait_enhancement

        enemy_ref = standoff_state["current_group"]
        instance_ids = standoff_state["groups"][enemy_ref]
        # Store standoff state for game loop continuation
        self._standoff_pending = standoff_state

        # Step 1: Semantic match (LLM, flash)
        match_prompt = build_standoff_match_prompt(player_input)
        try:
            raw = call_deepseek(match_prompt, json_mode=True, model="deepseek-v4-flash",
                               system="你是 COC 7th KP 助理，将玩家输入匹配到对应技能。",
                               fallback_schema={"matched": False, "skill_name": "", "reason": ""})
            match_data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            match_data = {"matched": False, "skill_name": "", "reason": ""}

        if not match_data.get("matched"):
            for iid in instance_ids:
                inst = self.world.enemies.get_by_id(iid) if self.world.enemies else None
                if inst:
                    inst.status = "hostile"
            self._standoff_pending = None
            return {"standoff_resolved": True, "avoided": False,
                    "message": f"你的尝试无效，{enemy_ref}进入战斗！",
                    "instance_ids": instance_ids}

        # Step 2: D100 skill check
        skill_name = match_data["skill_name"]
        ok, skill_msg, tier = self.world.player.check_skill(skill_name, "regular")
        skill_detail = (
            f"[STANDOFF] {skill_name}检定 | 等级={tier} | {'成功' if ok else '失败'}\n"
            f"  {skill_msg}"
        )

        # Step 3: Trait enhancement
        inv_desc = (getattr(self.world.player, 'personal_description', '') or
                   getattr(self.world.player, 'description', ''))
        if inv_desc:
            roll_m = re.search(r'D100=(\d+)/', skill_msg)
            dice_roll = int(roll_m.group(1)) if roll_m else 0
            skill_val = self.world.player.get_skill_value(skill_name) if self.world.player else 0
            enh = evaluate_trait_enhancement(
                inv_desc=inv_desc,
                skill_name=skill_name,
                skill_detail=skill_msg,
                dice_roll=dice_roll,
                skill_value=skill_val,
                entity_name=f"避免与{enemy_ref}战斗",
                search_context=False,
                player_input=player_input,
            )
            from prompts import log_skill_result
            log_skill_result(f"[STANDOFF特质增强完整响应] {json.dumps(enh, ensure_ascii=False)}")
            new_tier = enh.get("tier", tier)
            if new_tier != tier:
                skill_detail += f"\n  [特质修正] {tier} -> {new_tier}: {enh.get('reason', '')}"
                tier = new_tier
                ok = (tier != "failure")

        # Step 4: Apply result
        if ok:
            if skill_name in ("魅惑", "说服", "话术", "恐吓"):
                for iid in instance_ids:
                    if self.world.enemies:
                        self.world.enemies.set_status(iid, "neutral")
                msg = f"{skill_name}成功——{enemy_ref}被{skill_name}所动，敌意消退。"
            else:
                msg = f"潜行成功——你悄悄绕过了{enemy_ref}。"
            self._standoff_pending = None
            return {"standoff_resolved": True, "avoided": True,
                    "message": msg, "instance_ids": instance_ids,
                    "skill_detail": skill_detail}
        else:
            for iid in instance_ids:
                inst = self.world.enemies.get_by_id(iid) if self.world.enemies else None
                if inst:
                    inst.status = "hostile"
            self._standoff_pending = None
            return {"standoff_resolved": True, "avoided": False,
                    "message": f"{skill_name}失败——{enemy_ref}进入战斗！",
                    "instance_ids": instance_ids,
                    "skill_detail": skill_detail}

    def _check_boss_requirements(self, boss_entity: dict) -> bool:
        """Check boss requirements using the (hard) || soft pattern."""
        req_str = boss_entity.get("requirements", "")
        if not req_str:
            return True
        if "||" in req_str:
            hard_part = req_str.split("||", 1)[0].strip()
            if hard_part:
                from scenario_core import parse_hard_requirement
                return parse_hard_requirement(hard_part, self.world.runtime_state)
        return True

    # ── Internal ──

    def _parse(self, raw: str) -> list[dict]:
        prompt = build_keeper_parse_prompt(self.world, raw)
        try:
            response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                                     reasoning_effort="max",
                                     system="你是一个优秀的跑团KP，擅长理解玩家的意图并将之与游戏实体精准匹配。"
                                            "你可以根据经验和对COC规则的理解，判断玩家输入触发了哪些交互、"
                                            "自动事件或移动行为，并评估软性叙事条件是否满足。",
                                     fallback_schema={"actions": []})
            data = json.loads(response) if isinstance(response, str) else response
        except Exception as e:
            self._warnings.append(f"意图解析失败（{e}），将你的输入作为即兴行为处理。")
            return [{"type": "other", "text": raw}]
        actions = data.get("actions", [])
        if not actions:
            return [{"type": "other", "text": raw}]
        return actions

    def _enrich(self, judged_entities, user_input) -> dict:
        prompt = build_keeper_enrich_prompt(self.world, judged_entities, user_input)
        try:
            response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                                     system="你是一个优秀的跑团KP，擅长叙事整合和氛围营造。"
                                            "你可以根据检定结果和场景上下文，将零散的实体触发结果转化为流畅沉浸的叙事，"
                                            "依据成功或失败调整描述的清晰度和影响力。",
                                     fallback_schema={
                                         "results": {},
                                         "reasoning": "",
                                         "emphasis_hint": "",
                                     })
            return json.loads(response) if isinstance(response, str) else response
        except Exception as e:
            self._warnings.append(f"叙事润色失败（{e}），结果将以原始形式呈现。")
            return {"results": {}, "reasoning": "", "emphasis_hint": ""}

    def _find_entity_by_id(self, entity_id: str):
        """Find entity by ID across graph (scenes + events)."""
        if entity_id in self.world.graph.events:
            return self.world.graph.events[entity_id]
        node = self.world._current_node()
        if node:
            for e in node.interactions + node.auto_triggers:
                if e.id == entity_id:
                    return e
        # Scan all scenes
        for node in self.world.graph.nodes.values():
            for e in node.interactions + node.auto_triggers:
                if e.id == entity_id:
                    return e
        return None

    def _process_deterministic_only(self, turn_input: TurnInput) -> dict:
        """Fallback: deterministic-only pass when escalation recursion exceeds limit."""
        self.turn_number += 1
        raw = turn_input.raw_text

        # Run auto-triggers deterministically
        at_results = self.judge.check_auto_triggers()
        for o in at_results:
            self._apply_side_effects(o.side_effects)

        all_outcomes = list(at_results) + [
            ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message="（周围安静如常，没有什么特别的事情发生）")
        ]

        ambient = [a.message for a in at_results]
        brief = self.curator.assemble(all_outcomes, ambient, "")
        return {"brief": brief,
                "ending_name": None, "ending_narrative": None}

    def _build_world_snapshot(self) -> dict:
        """Lightweight snapshot for IntentDetector. Delegates to World."""
        snap = self.world.build_snapshot()
        l1 = getattr(self, "narrator_l1", {}) or {}
        l1_scene = l1.get(self.world.current_location, {})
        scene_desc = l1_scene.get("description", "") if isinstance(l1_scene, dict) else ""
        return {
            "location": snap["location"],
            "scene_description": scene_desc or snap["description"],
            "npc_states": {n["name"]: n["state"] for n in snap["npcs_in_scene"]},
        }

    def _resolve_time_delta(self, entity) -> int:
        """Resolve time delta based on entity extra.time_range or defaults."""
        if entity.extra and entity.extra.get("time_range"):
            tr = entity.extra["time_range"]
            return (tr.get("min", 3) + tr.get("max", 10)) // 2
        category = self._infer_time_category(entity)
        defaults = self.world.time_costs or {"search": 10, "move": 3, "dialogue": 5, "combat_round": 1, "other": 3}
        return defaults.get(category, 5)

    def _infer_time_category(self, entity) -> str:
        if entity.entity_type in ("auto_trigger", "event"):
            return "other"
        if entity.type and entity.type in ("侦查", "聆听", "图书馆使用"):
            return "search"
        return "other"

    def _should_trigger_time_agent(self) -> bool:
        if not hasattr(self, '_last_ta_call'):
            self._last_ta_call = -1
        if self._last_ta_call < 0:
            return True  # first call
        if self.world.clock.game_time - self._last_ta_call >= 30:
            return True
        return False

    def _build_scene_context_for_author(self) -> dict:
        """Build scene_context for AuthorRequest. Delegates to World snapshot."""
        snap = self.world.build_snapshot()
        return {
            "location": snap["location"],
            "description": snap["description"],
            "available_scenes": list(self.world.graph.nodes.keys()),
            "npc_states": {n["name"]: n["state"] for n in snap["npcs_in_scene"]},
            "runtime_summary": {
                eid: s.result_tier
                for eid, s in self.world.runtime_state.items()
                if s.completed
            },
            "wr0_enabled": self.world.wr0_enabled,
        }

    def _integrate_supplement(self, structural_edit: StructuralEdit, author, intent: str = "", reasoning: str = "") -> StructuralEdit:
        """Run supplement pipeline and integrate results into world graph."""
        try:
            from module_designer.supplement_pipeline import run_supplement_pipeline
            result = run_supplement_pipeline(
                player_intent=intent,
                reasoning=reasoning,
                base_l3=author.l3_data,
                entry_scene=structural_edit.entry_scene,
                exit_scene=structural_edit.exit_scene,
                world_snapshot=self._build_world_snapshot(),
                module_name="",
            )

            l2 = result["l2"]
            graph = self.world.graph

            for scene_name, scene_data in l2.get("scenes", {}).items():
                self._load_scene_into_graph(scene_name, scene_data)

            for ev in l2.get("events", []):
                eid = ev["id"]
                if eid not in graph.events:
                    graph.events[eid] = Entity(
                        id=eid, entity_type="event",
                        name=ev["name"], type=ev.get("type", ""),
                        requirement=ev.get("requirement", ""), trigger=ev.get("trigger", ""),
                        result=ev.get("result", ""), side_effects=ev.get("side_effects", []),
                        graded_result=ev.get("graded_result"), difficulty=ev.get("difficulty", ""),
                    )

            if structural_edit.entry_scene in graph.nodes:
                first_new_scene = next(iter(l2.get("scenes", {}).keys()), None)
                if first_new_scene:
                    entry_node = graph.nodes[structural_edit.entry_scene]
                    already_connected = any(
                        e.target == first_new_scene for e in entry_node.edges
                    )
                    if not already_connected:
                        from scenario_core import Edge
                        entry_node.edges.append(Edge(
                            target=first_new_scene, method="深入探索",
                            requirement="",
                        ))

            if not hasattr(self, '_merged_l1'):
                self._merged_l1 = {}
            self._merged_l1.update(result["l1"])

            supp_dep = l2.get("dependency_graph", {})
            for eid, ndata in supp_dep.get("nodes", {}).items():
                if eid not in self.world.dependency_graph.setdefault("nodes", {}):
                    self.world.dependency_graph["nodes"][eid] = ndata
            existing_edges = {(e.get("source"), e.get("target"))
                            for e in self.world.dependency_graph.get("edges", [])}
            for edge in supp_dep.get("edges", []):
                key = (edge.get("source"), edge.get("target"))
                if key not in existing_edges:
                    self.world.dependency_graph.setdefault("edges", []).append(edge)
                    existing_edges.add(key)

            for eid in supp_dep.get("nodes", {}):
                self.world.get_runtime_state(eid)

            author.update_l3(result["l3"])

            structural_edit.supplement_path = result.get("output_dir", "")
            structural_edit.l3_updates = result["l3"]
        except Exception as e:
            self._warnings.append(f"补充管线失败（{e}），继续正常流程。")
            structural_edit.supplement_path = ""

        return structural_edit

    def _load_scene_into_graph(self, scene_name: str, scene_data: dict):
        """Load a single scene dict into DirectedGraph."""
        from scenario_core import Entity as EntityClass, Edge, Node
        graph = self.world.graph

        interactions = [
            EntityClass(
                id=inter["id"], entity_type=inter.get("entity_type", "interaction"),
                name=inter["name"], scene=inter.get("scene", scene_name),
                type=inter.get("type", ""), requirement=inter.get("requirement", ""),
                trigger=inter.get("trigger", ""), result=inter.get("result", ""),
                side_effects=inter.get("side_effects", []),
                graded_result=inter.get("graded_result"), difficulty=inter.get("difficulty", ""),
            )
            for inter in scene_data.get("interactions", [])
        ]
        auto_triggers = [
            EntityClass(
                id=at["id"], entity_type=at.get("entity_type", "auto_trigger"),
                name=at["name"], scene=at.get("scene", scene_name),
                type=at.get("type", ""), requirement=at.get("requirement", ""),
                trigger=at.get("trigger", ""), result=at.get("result", ""),
                side_effects=at.get("side_effects", []),
                graded_result=at.get("graded_result"), difficulty=at.get("difficulty", ""),
            )
            for at in scene_data.get("auto_triggers", [])
        ]

        from_edges = [
            Edge(target=conn["target"], method=conn.get("method", ""),
                 requirement=conn.get("requirement", ""))
            for conn in scene_data.get("from_here", [])
        ]
        to_edges = [
            Edge(target=conn.get("source", conn.get("target", "")),
                 method=conn.get("method", ""),
                 requirement=conn.get("requirement", ""))
            for conn in scene_data.get("to_here", [])
        ]

        graph.nodes[scene_name] = Node(
            node_id=scene_name,
            description=scene_data.get("description", ""),
            edges=from_edges,
            to_here=to_edges,
            interactions=interactions,
            auto_triggers=auto_triggers,
            encounters=scene_data.get("encounters", []),
            scene_weapons=scene_data.get("scene_weapons", []),
            extra=scene_data.get("extra", {}),
        )

    def _execute_entity_direct(self, entity: Entity) -> ActionOutcome:
        if entity.entity_type == "event":
            self.world.triggered_events[entity.id] = True
        elif entity.entity_type == "interaction":
            loc = self.world.current_location
            if loc not in self.world.completed_interactions:
                self.world.completed_interactions[loc] = set()
            self.world.completed_interactions[loc].add(entity.name)

        side_effects = []
        for se_text in entity.side_effects:
            side_effects.extend(parse_markup_all(se_text))

        return ActionOutcome(
            intent=ActionIntent(action="other"),
            success=True,
            message=entity.result,
            entity_id=entity.id,
            entity_type=entity.entity_type,
            side_effects=side_effects,
        )

    def _apply_side_effects(self, side_effects: list) -> list[str]:
        """Apply side effect dataclasses via respective managers. Returns log messages."""
        msgs = []
        for effect in side_effects:
            if isinstance(effect, ItemGain):
                self.world.memory.note_item(effect.item_name)
                if self.world.player and hasattr(self.world.player, 'item_manager'):
                    self.world.player.item_manager.add(effect.item_name, quantity=effect.quantity)
                    qty_str = f" x{effect.quantity}" if effect.quantity > 1 else ""
                    msgs.append(f"[获得物品] {effect.item_name}{qty_str}（已加入背包）")
                else:
                    msgs.append(f"[获得物品] {effect.item_name}")

            elif isinstance(effect, ConsumeItem):
                consumed = False
                if self.world.player and hasattr(self.world.player, 'item_manager'):
                    im = self.world.player.item_manager
                    if im.has(effect.item_name) and im.get(effect.item_name).quantity >= effect.quantity:
                        im.remove(effect.item_name, effect.quantity)
                        consumed = True
                    else:
                        try:
                            from llm import call_deepseek
                            from prompts import build_consume_item_fuzzy_prompt
                            held = im.describe()
                            if held and held != "（未持有物品）":
                                prompt = build_consume_item_fuzzy_prompt(
                                    target=effect.item_name, quantity=effect.quantity, held_items=held)
                                result = call_deepseek(
                                    prompt, json_mode=True, model="deepseek-v4-flash",
                                    system="你是 COC 7th KP 助理。",
                                    fallback_schema={"matched": False, "item_name": "", "reason": ""})
                                if isinstance(result, str):
                                    import json as _json
                                    result = _json.loads(result)
                                if result.get("matched") and result.get("item_name"):
                                    if im.has(result["item_name"]):
                                        im.remove(result["item_name"], effect.quantity)
                                        consumed = True
                        except Exception:
                            pass
                msgs.append(f"[消耗物品] {effect.item_name} x{effect.quantity}" +
                           ("" if consumed else "（未找到匹配物品）"))

            elif isinstance(effect, SpawnEnemy):
                target_scene = effect.scene or self.world.current_location
                if self.world.enemies:
                    instance = self.world.enemies.spawn(effect.enemy_ref, target_scene, effect.quantity)
                    msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene} ({instance.instance_id})")
                else:
                    msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}")

            elif isinstance(effect, GrantWeapon):
                target_scene = effect.scene or self.world.current_location
                sw = SceneWeapon(weapon_ref=effect.weapon_ref, scene=target_scene, quantity=effect.quantity)
                if target_scene not in self.world.scene_weapons:
                    self.world.scene_weapons[target_scene] = []
                self.world.scene_weapons[target_scene].append(sw)
                self.world.memory.note_item(effect.weapon_ref)
                msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {target_scene}")

            elif isinstance(effect, NPCStateChange):
                self.world.npcs.set_state(effect.npc_name, effect.new_state)
                msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")

            elif isinstance(effect, NPCFollow):
                self.world.npcs.set_following(effect.npc_name, effect.follow)
                status = "开始跟随" if effect.follow else "停止跟随"
                msgs.append(f"[NPC跟随] {effect.npc_name} {status}")

            elif isinstance(effect, StatChange):
                if self.world.player:
                    new_val, detail = self.world.player.modify_stat(effect.stat_name, effect.delta)
                    msgs.append(f"[属性变化] {detail}")
                    if effect.narrative and hasattr(self.world.player, 'personal_description'):
                        try:
                            from llm import call_deepseek
                            from prompts import build_stat_narrative_prompt
                            prompt = build_stat_narrative_prompt(
                                inv_desc=self.world.player.personal_description or self.world.player.appearance or "",
                                stat_name=effect.stat_name, delta=str(effect.delta), narrative=effect.narrative)
                            result = call_deepseek(
                                prompt, json_mode=True, model="deepseek-v4-flash",
                                system="你是 COC 7th KP 助理，负责更新调查员描述。",
                                fallback_schema={"description": self.world.player.personal_description or ""})
                            if isinstance(result, str):
                                import json as _json
                                result = _json.loads(result)
                            new_desc = result.get("description", "")
                            if new_desc and new_desc != (self.world.player.personal_description or ""):
                                self.world.player.personal_description = new_desc
                                msgs.append(f"[描述更新] {effect.stat_name} 变化影响了外貌/心理描述")
                        except Exception:
                            pass
                else:
                    sign = '+' if (isinstance(effect.delta, (int, float)) and effect.delta > 0) else ''
                    msgs.append(f"[属性变化] {effect.stat_name} {sign}{effect.delta}（无调查员，未应用）")

        return msgs

    def _integrate_patch(self, patch):
        """Integrate ModulePatch entities into world graph."""
        from scenario_core import Entity as EntityClass
        for ent_data in patch.entities:
            entity = EntityClass(
                id=ent_data.get("id", f"NEW_{hash(ent_data['name'])%10000}"),
                entity_type=ent_data.get("entity_type", "interaction"),
                name=ent_data.get("name", ""),
                scene=ent_data.get("scene", ""),
                type=ent_data.get("type", ""),
                requirement=ent_data.get("requirement", ""),
                trigger=ent_data.get("trigger", ""),
                result=ent_data.get("result", ""),
                side_effects=ent_data.get("side_effects", []),
                graded_result=ent_data.get("graded_result"),
                difficulty=ent_data.get("difficulty", ""),
            )
            if entity.entity_type == "event":
                self.world.graph.events[entity.id] = entity
            else:
                node = self.world.graph.nodes.get(entity.scene)
                if node:
                    if entity.entity_type == "auto_trigger":
                        node.auto_triggers.append(entity)
                    else:
                        node.interactions.append(entity)
        for scene_name, desc in patch.scene_descriptions.items():
            if scene_name in self.world.graph.nodes:
                self.world.graph.nodes[scene_name].description = desc
