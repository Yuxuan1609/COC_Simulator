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
    TimeCommsPacket, EnrichInput,
)
from ..judge import Judge
from ..curator import Curator
from ..intent_detector import IntentDetector
from ..pre_parse import PreParseDisambiguator
from prompts import build_keeper_parse_prompt, build_keeper_enrich_prompt
from llm import call_deepseek
from config import MAX_ESCALATION_DEPTH, INTENT_COOLDOWN_WINDOW
from config_llm import LLM_FLASH_MODEL, RE_COMBAT_ENTRY, RE_KEEPER_PARSE
from monitor.turn_monitor import TurnFrozenError, TurnMonitor


def _wattr(lib_wep, key, default):
    """Safe attribute access for both dict and dataclass weapon/attack entries."""
    if isinstance(lib_wep, dict):
        return lib_wep.get(key, default)
    return getattr(lib_wep, key, default)


class Keeper:
    """Keeper agent. Owns L2 + ScenarioWorld, coordinates the turn.

    Must never: output directly to player.
    """

    def __init__(
        self,
        world: ScenarioWorld,
        phase1: dict | None = None,
    ):
        self.world = world
        self.phase1 = phase1 or {}
        self._last_comms_time = 0

        self.intent_detector = IntentDetector()
        self.pre_parse = PreParseDisambiguator()

        self.judge = Judge(world)
        self.curator = Curator(world)
        self.turn_number = 0
        self._warnings: list[str] = []  # per-turn LLM error warnings surfaced to player
        self._recent_intents: list[str] = []  # last N intent strings for duplicate suppression
        from monitor.agent_monitor import AgentMonitor
        from monitor.policies import KeeperPolicy
        from llm import _init_sensor
        self._sensor = _init_sensor()
        self.monitor = AgentMonitor("Keeper", self._sensor, KeeperPolicy())
        self._intent_cooldown: int = INTENT_COOLDOWN_WINDOW
        self._standoff_pending: dict | None = None
        self._weapon_offer: list | None = None  # pending weapon pickup offers [{weapon_ref, scene}, ...]
        self._weapon_offer_msg: str = ""  # offer prompt message for current turn's output
        self._npc_events: list[str] = []  # NPC follow/state events collected this turn
        self._pending_side_effects: list = []  # deferred side effects (apply after Author check)
        self._pending_move: str | None = None  # deferred move target
        self.turn_monitor = TurnMonitor(self._sensor, self.world, keeper=self)

    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse → judge → enrich → curate."""
        raw = turn_input.raw_text

        # Pending weapon offer check: yes/no, does NOT consume a turn
        if self._weapon_offer:
            answer = raw.strip().lower()
            pickup = any(kw in answer for kw in ("是", "yes", "y", "拾取", "捡", "拿"))
            offer_list = self._weapon_offer
            self._weapon_offer = None
            if pickup and self.world.weapon_library:
                for wo in offer_list:
                    lib_wep = self.world.weapon_library.get(wo["weapon_ref"])
                    if lib_wep:
                        from investigator.models import Weapon
                        skill = lib_wep.get("skill_name", "") if isinstance(lib_wep, dict) else getattr(lib_wep, "skill_name", "")
                        dmg_raw = lib_wep.get("damage", "") if isinstance(lib_wep, dict) else getattr(lib_wep, "damage", "")
                        dmg_str = dmg_raw if isinstance(dmg_raw, str) else (str(dmg_raw) if dmg_raw else "1D6+DB")
                        inv_wep = Weapon(
                            name=wo["weapon_ref"], skill_name=skill or "格斗",
                            damage=dmg_str,
                            damage_type=_wattr(lib_wep, 'damage_type', '物理'),
                            armor_piercing=int(_wattr(lib_wep, 'armor_piercing', 0)),
                            attack_bonus=int(_wattr(lib_wep, 'attack_bonus', 0)),
                            multi_attack=int(_wattr(lib_wep, 'multi_attack', 1)),
                            special_rules=_wattr(lib_wep, 'special_rules', ''),
                        )
                        self.world.player.add_weapon(inv_wep)
                        scene = wo.get("scene", "")
                        if scene:
                            scene_weps = self.world.scene_weapons.get(scene, [])
                            for sw in list(scene_weps):
                                if sw.weapon_ref == wo["weapon_ref"]:
                                    scene_weps.remove(sw)
                                    break
                            if not scene_weps:
                                del self.world.scene_weapons[scene]
                names = "、".join(w["weapon_ref"] for w in offer_list)
                return {"brief": f"你拾起了{names}。", "weapon_pickup": True}
            names = "、".join(w["weapon_ref"] for w in offer_list)
            return {"brief": f"你忽略了{names}。", "weapon_pickup": False}

        if _depth >= MAX_ESCALATION_DEPTH:
            # Guard against infinite recursion — re-execute deterministically
            return self._process_deterministic_only(turn_input)
        self.turn_number += 1
        self._warnings.clear()
        self._npc_events.clear()
        self._pending_side_effects.clear()
        self._pending_move = None

        # Inject NPC ATs + interactions before normal parse
        self._inject_npc_at()

        # Step 0: Pre-parse — disambiguation gate
        pre_result = self.pre_parse.disambiguate(raw, self._build_world_brief())
        if pre_result.clarity == "ambiguous":
            return {
                "brief": pre_result.question,
                "narrative": pre_result.question,
                "pre_parse_ambiguous": True,
            }
        # Use resolved_text as effective input when cross-turn integration happened
        if pre_result.resolved_text:
            raw = pre_result.resolved_text

        # Step 1: Parse (LLM) — entity matching + NL requirement evaluation
        try:
            parse_result = self.turn_monitor.execute_step(
                "parse", lambda: self._parse(raw), is_critical=True)
        except TurnFrozenError as e:
            return self._build_frozen_response(e)

        # Handle npc_interact — general conversation (no matching entity).
        # NPC-bound entities ([NPC_INTERACT]/[NPC_AT]) are matched as normal
        # interaction/auto_trigger by parse — they follow the main pipeline.
        # npc_interact here means "talk to NPC about something no entity covers."
        npc_interact_entries = [e for e in parse_result if e.get("type") == "npc_interact"]
        non_npc_entries = [e for e in parse_result if e.get("type") != "npc_interact"]
        _FOLLOW_KEYWORDS = ("跟我", "跟着", "跟随", "一起走", "加入我", "跟我来", "跟我走",
                           "一起行动", "陪同", "随行", "随我")
        _has_follow_request = lambda txt: any(kw in txt for kw in _FOLLOW_KEYWORDS)
        if npc_interact_entries:
            for entry in npc_interact_entries:
                npc_name = entry.get("npc_name", "")
                npc = self.world.npcs.get(npc_name) if npc_name and self.world.npcs else None
                if not npc:
                    self._npc_events.append(f"（没有叫「{npc_name}」的 NPC）")
                    continue
                if npc.scene != self.world.current_location:
                    self._npc_events.append(f"（{npc_name} 不在当前场景）")
                    continue
                dialogue = self.world.npcs.talk_to(
                    npc_name, raw,
                    lambda prompt, **kw: call_deepseek(prompt, json_mode=False, **kw),
                    world=self.world,
                )
                self._npc_events.append(f"{npc_name}：{dialogue}")
                # Detect follow request via keyword match
                if _has_follow_request(raw):
                    ok, reason = self.world.npcs._check_follow_conditions(npc, self.world)
                    if ok:
                        self.world.npcs.set_following(npc_name, True)
                        self._npc_events.append(f"{npc_name} 开始跟随你")
                    else:
                        self._npc_events.append(reason)
            # If ONLY npc_interact, short-circuit — dialogue is the narrative.
            if not non_npc_entries:
                dialogue_text = self._npc_events[-1] if self._npc_events else ""
                return {"brief": dialogue_text, "narrative": dialogue_text,
                        "npc_events": list(self._npc_events)}
            parse_result = non_npc_entries

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
        enrich_input = EnrichInput()
        for entry in parse_result:
            entry_type = entry.get("type", "")
            if entry_type in ("auto_trigger", "interaction", "event"):
                eid = entry.get("id", "")
                entity = self._find_entity_by_id(eid)
                if not entity:
                    continue
                # Time condition check — independent of requirement/dependency_graph
                if self.world and self.world.clock:
                    from scenario_core import check_time_condition as _check_tc
                    tc = entity.get("time_condition", "") if isinstance(entity, dict) else getattr(entity, "time_condition", "")
                    if not _check_tc(tc, self.world.clock.day, self.world.clock.time_of_day):
                        continue
                intent = ActionIntent(
                    action=entry_type,
                    target=entity.name if entry_type == "interaction" else "",
                )
                outcome = self.judge._execute_entity(entity, intent=intent, player_input=raw)
                self._pending_side_effects.extend(outcome.side_effects)
                if outcome.success:
                    tr = entity.extra.get("time_range") if entity.extra else None
                    enrich_input.actions.append({
                        "type": entity.entity_type,
                        "name": entity.name,
                        "success": True,
                        "time_range": tr,
                        "time_category": self._infer_time_category(entity),
                    })
                all_outcomes.append(outcome)
                enrich_input.entities.append({
                    "entity_type": entity.entity_type,
                    "id": entity.id,
                    "name": entity.name,
                    "result": outcome.message,
                    "success": outcome.success,
                    "skill_tier": outcome.skill_tier,
                })
            elif entry_type == "move":
                target = entry.get("target", "")
                origin = self.world.current_location
                self._pending_move = target  # defer move until Author check passes
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="move", target=target),
                    success=True, message=f"从{origin}前往{target}...",
                ))
                enrich_input.actions.append({
                    "type": "move",
                    "name": f"移动到{target}",
                    "success": True,
                    "time_range": None,
                    "time_category": "move",
                })
            elif entry_type == "search":
                # Search always performs a 侦查 (Spot Hidden) check.
                # No dependency check, no flag update, no enrich.
                trait_enh = None
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
                        trait_enh = enh
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
                    else:
                        msg = "（你环顾四周，但昏暗的光线让你无法看清任何有用的东西）"
                    # Weapon discovery: always check scene weapons (visible even on failed search)
                    scene_weps = self.world.scene_weapons.get(
                        self.world.current_location, []
                    )
                    if scene_weps:
                        wep_names = "、".join(
                            f"{f'{sw.quantity}把 ' if sw.quantity > 1 else ''}{sw.weapon_ref}"
                            for sw in scene_weps
                        )
                        # Handle pickup intent embedded in search input
                        picked_up = False
                        for sw in list(scene_weps):
                            if sw.weapon_ref.lower() in raw.lower() and \
                               ("拾取" in raw or "捡" in raw or "拿" in raw):
                                if self.world.weapon_library:
                                    lib_wep = self.world.weapon_library.get(sw.weapon_ref)
                                    if lib_wep:
                                        from investigator.models import Weapon
                                        skill = _wattr(lib_wep, "skill_name", "")
                                        dmg_raw = _wattr(lib_wep, "damage", "")
                                        dmg_str = dmg_raw if isinstance(dmg_raw, str) else (str(dmg_raw) if dmg_raw else "1D6+DB")
                                        inv_wep = Weapon(
                                            name=sw.weapon_ref, skill_name=skill or "格斗",
                                            damage=dmg_str,
                                            damage_type=_wattr(lib_wep, 'damage_type', '物理'),
                                            armor_piercing=int(_wattr(lib_wep, 'armor_piercing', 0)),
                                            attack_bonus=int(_wattr(lib_wep, 'attack_bonus', 0)),
                                            multi_attack=int(_wattr(lib_wep, 'multi_attack', 1)),
                                            special_rules=_wattr(lib_wep, 'special_rules', ''),
                                        )
                                        self.world.player.add_weapon(inv_wep)
                                        picked_up = True
                                        scene_weps.remove(sw)
                                if not scene_weps:
                                    del self.world.scene_weapons[self.world.current_location]
                                msg = f"你拾起了{sw.weapon_ref}。"
                                all_outcomes.append(ActionOutcome(
                                    intent=ActionIntent(action="pickup", target=sw.weapon_ref),
                                    success=True,
                                    message=f"你拾起了{sw.weapon_ref}。",
                                    entity_id="WEAPON_PICKUP",
                                    entity_type="interaction",
                                ))
                                break
                        if not picked_up:
                            msg += f'\n\n（你发现了 {wep_names}。是否拾取？（是/否））'
                            self._weapon_offer = [{"weapon_ref": sw.weapon_ref, "scene": self.world.current_location} for sw in scene_weps]
                else:
                    msg = "（仔细查看四周，没有特别的发现）"
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="search"), success=True, message=msg,
                    entity_id="SEARCH", entity_type="search",
                    skill_tier=tier if self.world.player else "",
                    skill_detail=skill_detail if self.world.player else "",
                    enhancement=trait_enh))
                enrich_input.actions.append({
                    "type": "search",
                    "name": "搜索",
                    "success": True,
                    "time_range": None,
                    "time_category": "search",
                })
            elif entry_type == "other":
                text = entry.get("text", "")
                scene = self.world.current_location
                scene_weps = self.world.scene_weapons.get(scene, [])
                picked_up = False
                for sw in list(scene_weps):
                    if sw.weapon_ref.lower() in text.lower() and \
                       ("拾取" in text or "捡" in text or "拿" in text or "pick" in text.lower()):
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
                                    damage_type=_wattr(lib_wep, 'damage_type', '物理'),
                                    armor_piercing=int(_wattr(lib_wep, 'armor_piercing', 0)),
                                    attack_bonus=int(_wattr(lib_wep, 'attack_bonus', 0)),
                                    multi_attack=int(_wattr(lib_wep, 'multi_attack', 1)),
                                    special_rules=_wattr(lib_wep, 'special_rules', ''),
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
                        enrich_input.actions.append({
                            "type": "other",
                            "name": f"拾取{sw.weapon_ref}",
                            "success": True,
                            "time_range": None,
                            "time_category": "other",
                        })
                        break
                if not picked_up:
                    all_outcomes.append(ActionOutcome(
                        intent=ActionIntent(action="other"), success=True,
                        message=f"（{text}）"))
                    enrich_input.actions.append({
                        "type": "other",
                        "name": text,
                        "success": True,
                        "time_range": None,
                        "time_category": "other",
                    })
            else:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=True,
                    message=f"（{entry.get('text', '没有特别的事情发生')}）"))
                enrich_input.actions.append({
                    "type": "other",
                    "name": entry.get("text", ""),
                    "success": True,
                    "time_range": None,
                    "time_category": "other",
                })

        # Deterministic event auto-trigger: after judge, fire events whose dependencies just satisfied
        dep_graph = self.world.dependency_graph if hasattr(self.world, 'dependency_graph') else {}
        for edge in dep_graph.get("edges", dep_graph.get("dependency_edges", [])):
            if edge.get("dep_type") == "interaction":
                source_id = edge.get("source", "")
                target_id = edge.get("target", "")
                if self.world.is_entity_completed(target_id):
                    # Source is an event that should auto-fire when target completes
                    source_entity = self.world.graph.events.get(source_id)
                    if source_entity and not self.world.is_event_triggered(source_id):
                        outcome = self.judge._execute_entity(source_entity, intent=ActionIntent(action="event"), player_input=raw)
                        self._pending_side_effects.extend(outcome.side_effects)
                        all_outcomes.append(outcome)
                        enrich_input.entities.append({
                            "entity_type": "event",
                            "id": source_entity.id,
                            "name": source_entity.name,
                            "result": outcome.message,
                            "success": outcome.success,
                            "skill_tier": outcome.skill_tier,
                        })

        # Step 2.5: Combat entry detection — run BEFORE enrich so combat info flows into enrichment
        combat_entry = None
        enemy_ctx = None
        if self.world and self.world.enemies and not self.world.enemies._combat_active:
            enemy_ctx = self.world.enemies.get_combat_context(
                self.world.current_location, self.world.graph
            )
            n_instances = len(self.world.enemies._instances)
            print(f"[Combat Entry] scene={self.world.current_location} total_instances={n_instances} has_context={bool(enemy_ctx)}")
            if enemy_ctx:
                print(f"  {enemy_ctx[:200]}")
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
            try:
                raw_result = call_deepseek(
                    combat_prompt,
                    json_mode=True,
                    model=LLM_FLASH_MODEL,
                    reasoning_effort=RE_COMBAT_ENTRY,
                    _label="combat_entry",
                    system="你是 COC 7th KP 助理，负责根据玩家行为和场景内敌人习性判断是否进入回合制战斗。"
                           "\n\n输出 JSON：{\"enter_combat\": true/false, \"enemy_instance_ids\": [...], \"reasoning\": \"简述理由\"}。直接输出 JSON。",
                    fallback_schema={"enter_combat": False, "enemy_instance_ids": [], "reasoning": ""},
                )
                result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                combat_entry = CombatEntryCheck(
                    enter_combat=result.get("enter_combat", False),
                    enemy_instance_ids=result.get("enemy_instance_ids", []),
                    reasoning=result.get("reasoning", ""),
                )
                print(f"[Combat Entry] LLM decided: enter={combat_entry.enter_combat} ids={combat_entry.enemy_instance_ids} reason={combat_entry.reasoning[:80]}")
            except Exception:
                combat_entry = None

        # Step 2.6: Resolve combat trigger & inject combat narrative into enrich_input
        standoff_prompt = None
        combat_init_result = None
        if combat_entry and combat_entry.enter_combat:
            # 直接从场景收集所有敌对敌人，不依赖 LLM 返回的 ID 列表
            scene_enemies = self.world.enemies.get_active_in_scene(
                self.world.current_location
            ) if self.world.enemies else []
            # 过滤出 hostile 或可战斗状态的敌人
            combat_candidates = [
                inst for inst in scene_enemies
                if inst.status not in ("dead", "defeated")
            ]
            if combat_candidates:
                avoidable_by_ref: dict[str, list[str]] = {}
                hostile_iids: list[str] = []
                for inst in combat_candidates:
                    if "avoidable" in inst.flags:
                        avoidable_by_ref.setdefault(inst.enemy_ref, []).append(inst.instance_id)
                    else:
                        hostile_iids.append(inst.instance_id)

            if avoidable_by_ref:
                first_ref = next(iter(avoidable_by_ref))
                standoff_prompt = {
                    "groups": {ref: iids for ref, iids in avoidable_by_ref.items()},
                    "current_group": first_ref,
                    "hostile_iids": hostile_iids,
                    "all_enemy_iids": [inst.instance_id for inst in combat_candidates],
                    "reasoning": combat_entry.reasoning,
                }
                standoff_msg = f"你还有最后一次机会避免与{first_ref}的战斗——你要怎么做？"
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="standoff"),
                    success=True,
                    message=standoff_msg,
                    entity_id="STANDOFF",
                    entity_type="standoff",
                ))
                enrich_input.entities.append({
                    "entity_type": "standoff",
                    "id": "STANDOFF",
                    "name": f"对峙：{first_ref}",
                    "result": standoff_msg,
                    "success": True,
                    "skill_tier": "",
                })
            elif hostile_iids:
                enemies = [self.world.enemies.get_by_id(iid)
                          for iid in hostile_iids
                          if self.world.enemies and self.world.enemies.get_by_id(iid)]
                if enemies and self.world.enemies:
                    self.world.enemies.enter_combat(hostile_iids)
                enemy_names = ", ".join(
                    getattr(e, 'enemy_ref', getattr(e, 'name', '未知')) for e in enemies
                )
                combat_msg = f"⚔ 你与{enemy_names}进入了战斗！"
                enrich_input.entities.append({
                    "entity_type": "combat",
                    "id": "COMBAT",
                    "name": f"战斗：{enemy_names}",
                    "result": combat_msg,
                    "success": True,
                    "skill_tier": "",
                })
                combat_init_result = CombatInit(
                    enemies=enemies,
                    player=self.world.player,
                    scene=self.world.current_location,
                    initiative_context=combat_entry.reasoning,
                    player_action="",
                    player_targets=[],
                    player_extra="",
                )

        # Step 3: [Enrich(LLM) ∥ TimeAgent(LLM)] — combat info already injected into enrich_input
        emphasis = ""
        enrichment = None
        ta_result = None
        if enrich_input.entities or enrich_input.actions:
            have_enrich = bool(enrich_input.entities)
            have_ta = bool(enrich_input.actions)
            steps = []
            if have_enrich:
                steps.append(("enrich",
                    lambda: self._enrich(enrich_input.entities, raw),
                    False, 2))
            else:
                steps.append(("enrich",
                    lambda: {"results": {}, "reasoning": "", "emphasis_hint": ""},
                    False, 0))
            if have_ta:
                steps.append(("time_agent",
                    lambda: self._run_time_agent(enrich_input.actions, raw),
                    False, 2))
            else:
                steps.append(("time_agent",
                    lambda: {"time_delta": 0, "narrative_hint": ""},
                    False, 0))
            parallel_results = self.turn_monitor.execute_parallel(steps)
            enrichment = parallel_results.get("enrich")
            ta_result = parallel_results.get("time_agent")

        # Step 3.5: Collect enrich + TA results
        if enrichment:
            emphasis = enrichment.get("emphasis_hint", "")
            results = enrichment.get("results", "")
            if isinstance(results, str) and results and all_outcomes:
                updated = False
                for o in all_outcomes:
                    if o.success and o.entity_type != "auto_trigger":
                        o.message = results
                        updated = True
                        break
                if not updated:
                    all_outcomes[0].message = results
        if ta_result:
            if ta_result.get("time_delta", 0) > 0:
                self.world.clock.advance_time(ta_result["time_delta"])
            narrative = (ta_result.get("narrative_hint", "") or "")
            if narrative:
                self.world.clock.time_context = narrative

        # Boss "at" / "interaction" check: scene-bound bosses
        boss_combat_init = None
        if self.world.bosses:
            for engage in ("at", "interaction"):
                candidates = self.world.bosses.check_by_engage_type(engage, scene=self.world.current_location)
                for boss_entity in candidates:
                    boss_id = boss_entity.get("id", boss_entity.get("boss_ref", "unknown"))
                    if self.world.is_entity_completed(boss_id):
                        continue
                    if self._check_boss_requirements(boss_entity, turn_input.raw_text):
                        boss_combat_init = self.world.bosses.build_combat_init(boss_entity, self.world.player, self.world.current_location)
                        self.world.bosses.set_active(boss_id)
                        boss_name = boss_entity.get("name", boss_entity.get("boss_ref", boss_id))
                        boss_msg = f"⚠ {boss_name}发现了你！退路已断，战斗一触即发——"
                        enrich_input.entities.append({
                            "entity_type": "boss_encounter",
                            "id": f"BOSS_{boss_id}",
                            "name": f"Boss遭遇：{boss_name}",
                            "result": boss_msg,
                            "success": True,
                            "skill_tier": "",
                        })
                        break
                if boss_combat_init:
                    break
        if boss_combat_init:
            boss_enemy = boss_combat_init.enemies[0] if boss_combat_init.enemies else None
            if boss_enemy:
                if combat_init_result and combat_init_result.enemies:
                    # 合并：Boss 加入当前场景的已有战斗
                    combat_init_result.enemies.append(boss_enemy)
                    self.world.enemies.register(boss_enemy)
                    self.world.enemies.add_to_combat(boss_enemy.instance_id)
                else:
                    combat_init_result = boss_combat_init
                    self.world.enemies.register(boss_enemy)
                    self.world.enemies.add_to_combat(boss_enemy.instance_id)

        # Step 3: [Enrich(LLM) ∥ TimeAgent(LLM)] — combat info already injected into enrich_input

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
                intent_result = self.turn_monitor.execute_step(
                    "intent_detect",
                    lambda: detect_future.result(),
                    is_critical=False,
                )
            except TurnFrozenError:
                intent_result = None
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

        # ── Apply all deferred side effects + move (Author check passed) ──
        self._apply_pending()

        # Ending detection — scan outcomes for ##END_ markers + L3 ending_conditions lookup
        # TODO: 跨模组结局 — 当支持多模组串联时，结局可能需要在模组间传递状态或触发不同后续。
        # 当前实现仅查询当前 L3 的 ending_conditions。跨模组时需要合并多个 L3 或增加全局结局表。
        from scenario_core import has_ending as _has_ending
        ending_result = None
        for o in all_outcomes:
            en, ed = _has_ending(o.message)
            if en:
                # Look up L3 ending_conditions for rich narrative (match by id or name)
                full_narrative = ed or ""
                if author and hasattr(author, 'l3_data') and author.l3_data:
                    ec = author.l3_data.get("ending_conditions", [])
                    for ec_item in ec:
                        eid = ec_item.get("id", "")
                        ename = ec_item.get("name", eid)
                        if eid == en or ename == en:
                            full_narrative = ec_item.get("narrative", ed)
                            break
                ending_result = {
                    "name": en,
                    "narrative": full_narrative,
                    "game_over": True,
                }
                break

        # Inject LLM error warnings as player-visible outcomes
        for w in self._warnings:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"⚠ {w}"))

        # Boss "event" check: after judge completes
        # Don't return early — let curate run so enrich/narrator output is preserved
        if self.world.bosses:
            event_bosses = self.world.bosses.check_by_engage_type("event")
            for boss_entity in event_bosses:
                boss_id = boss_entity.get("id", boss_entity.get("boss_ref", "unknown"))
                if self.world.is_entity_completed(boss_id):
                    continue
                if self._check_boss_requirements(boss_entity, turn_input.raw_text):
                    combat_init_result = self.world.bosses.build_combat_init(boss_entity, self.world.player, self.world.current_location)
                    self.world.bosses.set_active(boss_id)
                    break  # only handle one boss per turn; curate + return below

        # Step 5: Curate
        ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
        try:
            brief = self.turn_monitor.execute_step(
                "curate",
                lambda: self.curator.assemble(all_outcomes, ambient, emphasis),
                is_critical=True,
            )
        except TurnFrozenError as e:
            return self._build_frozen_response(e)

        # Step 6: Memory (now handled in game_loop after narrator.narrate)
        if self.world.memory.should_compress():
            from threading import Thread
            t = Thread(target=self.world.memory.compress, args=(
                lambda p: call_deepseek(p, json_mode=False, model=LLM_FLASH_MODEL,
                                        system="你是一个擅长总结和提炼信息的助手。请将游戏历史压缩为简洁摘要，"
                                               "保留关键事件、重要细节和当前状态，去除冗余对话。"),
            ), daemon=True)
            t.start()

        # Inject weapon offer prompt if direct grant is pending
        if self._weapon_offer_msg:
            brief.action_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=self._weapon_offer_msg,
                entity_id="WEAPON_OFFER", entity_type="information",
            ))
            self._weapon_offer_msg = ""

        return {"brief": brief,
                "ending": ending_result,
                "combat_entry": combat_entry,
                "standoff_prompt": standoff_prompt,
                "combat_init": combat_init_result,
                "time_agent": ta_result,
                "enrich": enrichment,
                "npc_events": list(self._npc_events)}

    def _build_frozen_response(self, exc: TurnFrozenError) -> dict:
        return {
            "brief": "",
            "narrative": "",
            "ending": None,
            "combat_entry": None,
            "standoff_prompt": None,
            "combat_init": None,
            "time_agent": None,
            "enrich": None,
            "npc_events": list(self._npc_events),
            "game_frozen": True,
            "frozen_message": str(exc),
        }

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
            raw = self.monitor.call(
                lambda p, **kw: call_deepseek(p, _label="standoff_match", **kw),
                match_prompt, json_mode=True, model=LLM_FLASH_MODEL,
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

    def _check_boss_requirements(self, boss_entity: dict, player_action: str = "") -> bool:
        """Check boss requirements using the (hard) || soft pattern.
        || is an AND separator — both hard and soft conditions must be met.
        Soft condition is evaluated by LLM when player_action is provided.
        """
        req_str = boss_entity.get("requirements", "")
        if not req_str:
            return True
        if "||" in req_str:
            hard_part = req_str.split("||", 1)[0].strip()
            soft_part = req_str.split("||", 1)[1].strip() if len(req_str.split("||", 1)) > 1 else ""
            # Check hard condition first
            if hard_part:
                from scenario_core import parse_hard_requirement
                if not parse_hard_requirement(hard_part, self.world.runtime_state):
                    return False  # hard condition failed → AND fails
            # Hard passed (or empty). Now check soft condition via LLM.
            if soft_part and player_action:
                return self._evaluate_boss_soft_condition(
                    soft_part, player_action, boss_entity.get("name", boss_entity.get("boss_ref", "unknown")))
            # No soft condition, or no player action to evaluate against → pass
            return True
        return True

    def _evaluate_boss_soft_condition(self, soft_condition: str, player_action: str, boss_name: str) -> bool:
        """Use LLM to evaluate whether the soft trigger condition is currently met."""
        try:
            from llm import call_deepseek
            from config_llm import LLM_FLASH_MODEL
            import json as _json

            scene = self.world.current_location
            prompt = (
                f"当前场景：{scene}\n"
                f"Boss名称：{boss_name}\n"
                f"玩家最近的行动：{player_action}\n"
                f"\nBoss触发条件（软条件）：{soft_condition}\n"
                f"\n请判断：玩家最近的行动是否满足上述触发条件？\n"
                f"返回 JSON：{{\"triggered\": true/false, \"reason\": \"<简要理由 20字以内>\"}}\n"
                f"直接输出 JSON。"
            )
            response = call_deepseek(
                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system="你是 TRPG Boss 触发裁判。根据玩家行动判断是否满足 Boss 的触发条件。",
                fallback_schema={"triggered": True, "reason": ""},
            )
            data = _json.loads(response) if isinstance(response, str) else response
            return data.get("triggered", True)
        except Exception:
            return True  # LLM unavailable → optimistic pass

    def _inject_npc_at(self):
        """Inject condition-satisfied NPC bound entities (interactions + ATs) into current node."""
        if not self.world.npcs:
            return
        self.world._npc_injected_at_ids.clear()
        node = self.world._current_node()
        if not node:
            return
        existing_interact_ids = {e.id for e in node.interactions}
        existing_at_ids = {e.id for e in node.auto_triggers}
        for npc in self.world.npcs._npcs.values():
            if npc.scene != self.world.current_location:
                continue
            # Inject bound interactions
            for ent in npc.bound_interactions:
                eid = ent.get("id", "")
                if self.world.is_entity_completed(eid) or eid in existing_interact_ids:
                    continue
                req = ent.get("requirement", "")
                if req:
                    from scenario_core import parse_hard_requirement
                    if not parse_hard_requirement(req, self.world.runtime_state):
                        continue
                from scenario_core import Entity
                node.interactions.append(Entity(
                    id=eid, entity_type="interaction",
                    name=ent.get("name", ""), scene=ent.get("source_scene", ""),
                    type=ent.get("type", ""), requirement=req,
                    trigger=ent.get("trigger", ""), result=ent.get("result", ""),
                    side_effects=ent.get("side_effects", []),
                    graded_result=ent.get("graded_result"),
                    difficulty=ent.get("difficulty", ""),
                    extra=ent.get("extra"),
                    time_condition=ent.get("time_condition", ""),
                ))
                self.world._npc_injected_at_ids.add(eid)
            # Inject bound auto_triggers
            for at in npc.bound_auto_triggers:
                at_scene = at.get("source_scene", "")
                if at_scene != self.world.current_location and at_scene:
                    continue
                eid = at.get("id", "")
                if self.world.is_entity_completed(eid) or eid in existing_at_ids:
                    continue
                req = at.get("requirement", "")
                if req:
                    from scenario_core import parse_hard_requirement
                    if not parse_hard_requirement(req, self.world.runtime_state):
                        continue
                from scenario_core import Entity
                node.auto_triggers.append(Entity(
                    id=eid, entity_type="auto_trigger",
                    name=at.get("name", ""), scene=at_scene,
                    type=at.get("type", ""), requirement=req,
                    trigger=at.get("trigger", ""), result=at.get("result", ""),
                    side_effects=at.get("side_effects", []),
                    graded_result=at.get("graded_result"),
                    difficulty=at.get("difficulty", ""),
                    extra=at.get("extra"),
                    time_condition=at.get("time_condition", ""),
                ))
                self.world._npc_injected_at_ids.add(eid)

    # ── Internal ──

    def _apply_pending(self):
        """Apply all deferred side effects and move collected during this turn."""
        if self._pending_move:
            result = self.world.move(self._pending_move)
            self._pending_move = None
        if self._pending_side_effects:
            self._apply_side_effects(list(self._pending_side_effects))
        # ── Inject NPC follow entity for NPCs that just started following ──
        for npc in self.world.npcs._npcs.values():
            if not npc.following or npc.scene != self.world.current_location:
                continue
            if not npc.can_follow:
                continue
            follow_eid = f"EVT_NPC_FOLLOW_{npc.name}"
            node = self.world._current_node()
            if node and follow_eid not in {e.id for e in node.interactions}:
                from scenario_core import Entity
                req_text = npc.follow_requirements if npc.follow_requirements else "NPC愿意跟随"
                node.interactions.append(Entity(
                    id=follow_eid, entity_type="interaction",
                    name=f"{npc.name}开始跟随你",
                    scene=self.world.current_location, type="无",
                    requirement=req_text,
                    trigger=f"你请求{npc.name}跟随你一起行动",
                    result=f"{npc.name}加入了你的队伍，你可以随时与其交谈",
                    side_effects=[], difficulty="None",
                    time_condition="",
                ))

    def _parse(self, raw: str) -> list[dict]:
        prompt = build_keeper_parse_prompt(self.world, raw)
        try:
            response = self.monitor.call(
                lambda p, **kw: call_deepseek(p, _label="keeper_parse", **kw),
                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                reasoning_effort=RE_KEEPER_PARSE,
                system="你是一个优秀的跑团KP，擅长理解玩家的意图并将之与游戏实体精准匹配。"
                       "\n\n你的任务是为玩家输入匹配结构化的游戏内容。"
                       "\n实体分为四类：[INTERACT]（场景交互）、[AUTO_TRIGGER]（自动触发）、[NPC_INTERACT]/[NPC_AT]（NPC 专属实体）、[EVENT]（全局事件）。"
                       "\n硬性条件已由系统判定，你只需判断意图匹配了哪个可触发实体或行为(move/search/other/npc_interact)。"
                       "\n只考虑可触发的entity，包括场景实体、NPC 专属实体和全局事件。"
                       "\n如有「条件=」字段则需评估是否满足；无「条件=」字段则默认条件已满足。"
                       "\n\n行为优先级："
                       "\n- 有明确对应实体时优先返回实体（[NPC_INTERACT]/[NPC_AT] 标记的 NPC 专属实体也按 interaction/auto_trigger 类型匹配）"
                       "\n- 玩家行为泛指搜索整个场景时返回 search，玩家想要明确移动到另一个场景时返回 move"
                       "\n- npc_interact 仅用于与【场景 NPC】中列出的 NPC 进行一般性对话/闲聊（玩家输入不涉及任何实体时），npc_name 必须从【场景 NPC】列表中精确复制"
                       "\n- 其他情况下返回 other"
                       "\n- 一般一个动作只匹配一个结果，特殊情况下允许多个。玩家一轮输入可能不只有一个动作，动作应该按照常识理解"
                       "\n- [AUTO_TRIGGER]/[NPC_AT] 为自动触发事件：条件满足即自动触发，不依赖玩家主动匹配。无「条件=」的 AT 进入场景时自动触发，必须包含在匹配结果中"
                       "\n\n输出规则：id 必须从实体列表中精确复制；move.target 填可移动方向中列出的目标；只考虑可触发的entity。"
                       "\n直接输出 JSON，不要额外文字。"
                       "\n\n输出格式：{\"actions\": [{\"type\": \"auto_trigger\", \"id\": \"...\"}, ..., {\"type\": \"npc_interact\", \"npc_name\": \"NPC名称\"}]}",
                fallback_schema={"actions": []},
            )
            data = json.loads(response) if isinstance(response, str) else response
        except Exception as e:
            raise  # let TurnMonitor handle retries
        actions = data.get("actions", [])
        if not actions:
            return [{"type": "other", "text": raw}]
        return actions

    def _enrich(self, judged_entities, user_input) -> dict:
        if self.monitor.degraded:
            from monitor.policies import KeeperPolicy
            policy = KeeperPolicy()
            if policy.on_degrade().get("skip_enrich"):
                return {"results": "（enrich 降级跳过）", "reasoning": "", "emphasis_hint": ""}
        prompt = build_keeper_enrich_prompt(self.world, judged_entities, user_input)
        try:
            response = self.monitor.call(
                lambda p, **kw: call_deepseek(p, **kw),
                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system="你是一个优秀的跑团KP，擅长叙事整合和氛围营造。"
                       "\n\n你的任务是整合本轮所有已触发实体的结果，合并润色为统一连贯的叙事。"
                       "\n\n叙事规则："
                       "\n- success=true → 结果清晰明确地整合，玩家能感知发生了什么"
                       "\n- success=false → 若 result 已含明确失败后果（扣血/惩罚/敌人出现），直接保留原文整合，不得改为晦涩模糊；仅当 result 为简单「检定失败」类通用文字时才描述为晦涩、模糊、似错觉或微不足道的细节"
                       "\n- 提供 reasoning 简短说明整合逻辑"
                       "\n\n输出格式：{\"results\": \"合并叙事\", \"reasoning\": \"整合逻辑\", \"emphasis_hint\": \"叙事方向\"}。直接输出 JSON。",
                fallback_schema={
                    "results": {},
                    "reasoning": "",
                    "emphasis_hint": "",
                })
            result = json.loads(response) if isinstance(response, str) else response
            self._log_agent_response("keeper_enrich", result)
            return result
        except Exception as e:
            self._warnings.append(f"叙事润色失败（{e}），结果将以原始形式呈现。")
            return {"results": {}, "reasoning": "", "emphasis_hint": ""}

    def _log_agent_response(self, filename: str, data: dict):
        """Write agent response directly to log file, bypassing global label."""
        import os as _os
        from prompts import _log_dir as _prompt_log_dir
        d = _prompt_log_dir
        if not d:
            return
        _os.makedirs(d, exist_ok=True)
        with open(_os.path.join(d, f"{filename}.txt"), "a", encoding="utf-8") as f:
            f.write("\n--- Response ---\n")
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n\n")

    def _find_entity_by_id(self, entity_id: str):
        """Find entity by ID across graph (scenes + events + boss encounters)."""
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
        # Boss encounters
        if self.world.bosses:
            for enc in self.world.bosses._encounters:
                if enc.get("id") == entity_id:
                    library_boss = self.world.bosses.library.get(enc.get("boss_ref", ""))
                    return {
                        "id": enc.get("id"),
                        "entity_type": "boss",
                        "name": enc.get("description", "")[:40],
                        "data": enc,
                        "library": library_boss,
                    }
        return None

    def _process_deterministic_only(self, turn_input: TurnInput) -> dict:
        """Fallback: deterministic-only pass when escalation recursion exceeds limit."""
        self.turn_number += 1
        raw = turn_input.raw_text

        # Run auto-triggers deterministically
        at_results = self.judge.check_auto_triggers()
        for o in at_results:
            self._pending_side_effects.extend(o.side_effects)

        all_outcomes = list(at_results) + [
            ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message="（周围安静如常，没有什么特别的事情发生）")
        ]

        ambient = [a.message for a in at_results]
        self._apply_pending()
        brief = self.curator.assemble(all_outcomes, ambient, "")
        return {"brief": brief,
                "ending": None}

    def _build_world_brief(self) -> str:
        """Ultra-light scene overview for pre-parse disambiguator (≤200 tokens)."""
        loc = self.world.current_location
        interactions = self.world.get_available_interactions()
        int_names = [i.name for i in interactions] if interactions else []
        npc_names = list(self.world.npcs._npcs.keys()) if self.world.npcs else []
        exits = [e.target for e in self.world.get_possible_exits()]
        parts = [f"当前位置: {loc}"]
        if int_names:
            parts.append(f"可用互动: {', '.join(int_names[:8])}")
        if npc_names:
            parts.append(f"N PC: {', '.join(npc_names[:5])}")
        if exits:
            parts.append(f"出口: {', '.join(exits[:5])}")
        return "; ".join(parts)

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

    def _infer_time_category(self, entity) -> str:
        if entity.entity_type in ("auto_trigger", "event"):
            return "other"
        if entity.type and entity.type in ("侦查", "聆听", "图书馆使用"):
            return "search"
        return "other"

    def _run_time_agent(self, action_summaries: list[dict], raw: str) -> dict:
        """Call TimeAgent with collected action summaries. Runs in parallel with enrich."""
        from game.agents.time_agent import TimeAgent
        ta = TimeAgent()
        return ta.assess(actions=action_summaries, current_input=raw,
                         time_costs=self.world.time_costs)

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
            enemy_names = []
            if self.world.enemies:
                try:
                    enemy_names = [e.name for e in self.world.enemies._library.list_all()]
                except Exception:
                    pass
            result = run_supplement_pipeline(
                player_intent=intent,
                reasoning=reasoning,
                base_l3=author.l3_data,
                entry_scene=structural_edit.entry_scene,
                exit_scene=structural_edit.exit_scene,
                world_snapshot=self._build_world_snapshot(),
                module_name="",
                enemy_names=enemy_names,
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
                time_condition=inter.get("time_condition", ""),
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
                time_condition=at.get("time_condition", ""),
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

        # Sync scene_weapons from graph node → world.scene_weapons
        raw_weapons = scene_data.get("scene_weapons", [])
        if raw_weapons:
            from game.side_effects import SceneWeapon as SW
            self.world.scene_weapons[scene_name] = [
                SW(weapon_ref=sw["weapon_ref"], scene=scene_name,
                   quantity=sw.get("quantity", 1))
                for sw in raw_weapons
            ]

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
                                    prompt, json_mode=True, model=LLM_FLASH_MODEL,
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
                scene = effect.scene.strip() if effect.scene else ""
                if scene:
                    # 有场景名：武器放置到场景中，玩家通过搜索发现
                    sw = SceneWeapon(weapon_ref=effect.weapon_ref, scene=scene, quantity=effect.quantity)
                    if scene not in self.world.scene_weapons:
                        self.world.scene_weapons[scene] = []
                    self.world.scene_weapons[scene].append(sw)
                    self.world.memory.note_item(effect.weapon_ref)
                    msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {scene}")
                else:
                    # scene 为空：直接授予调查员，通过 _weapon_offer 走确认流程
                    self._weapon_offer = [{"weapon_ref": effect.weapon_ref, "scene": ""}]
                    self._weapon_offer_msg = f"（获得了{effect.weapon_ref}，是否接受？（是/否））"
                    msgs.append(f"[武器授予] {effect.weapon_ref} x{effect.quantity} 直接授予调查员（待确认）")

            elif isinstance(effect, NPCStateChange):
                self.world.npcs.set_state(effect.npc_name, effect.new_state)
                msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")

            elif isinstance(effect, NPCFollow):
                self.world.npcs.set_following(effect.npc_name, effect.follow)
                status = "开始跟随" if effect.follow else "停止跟随"
                msgs.append(f"[NPC跟随] {effect.npc_name} {status}")
                self._npc_events.append(f"{effect.npc_name} {status}你")

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
                                prompt, json_mode=True, model=LLM_FLASH_MODEL,
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
                time_condition=ent_data.get("time_condition", ""),
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
