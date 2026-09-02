"""Keeper agent — orchestrates the turn: parse → judge → enrich → intent → curate."""
from __future__ import annotations
from typing import Any
import json
import re

from scenario_core import ScenarioWorld, Entity
from game.side_effects import (
    parse_markup_all,
    ItemGain, ConsumeItem, StatChange, SpawnEnemy, GrantWeapon, SceneWeapon,
    NPCStateChange, NPCFollow,
)
from ..messages import (
    ActionIntent, ActionOutcome,
    StructuralEdit, ModulePatch, TurnInput,
    TurnStatus, TurnResult, TurnDiagnostics,
)
from ..judge import Judge
from ..curator import Curator
from ..intent_detector import IntentDetector
from ..pre_parse import PreParseDisambiguator
from prompts import build_keeper_parse_prompt, build_keeper_enrich_prompt, KEEPER_PARSE_MADNESS_RULE
from llm import call_deepseek
from config import INTENT_COOLDOWN_WINDOW
from config_llm import LLM_FLASH_MODEL, RE_KEEPER_PARSE
from monitor.turn_monitor import TurnFrozenError, TurnMonitor


def _describe_time_condition(tc: str) -> str:
    """Parse time_condition JSON into a human-readable hint for the player.
    Returns empty string if unparseable or no constraint."""
    if not tc or tc == "[]":
        return ""
    import json as _json
    try:
        entries = _json.loads(tc)
    except (_json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(entries, list) or not entries:
        return ""
    parts = []
    for entry in entries:
        day_str = entry.get("day", "ALL") if isinstance(entry, dict) else "ALL"
        times = entry.get("times", ["ALL"]) if isinstance(entry, dict) else ["ALL"]
        day_text = ""
        if day_str != "ALL":
            if day_str.startswith(">="):
                day_text = f"第{day_str[2:]}天起"
            elif day_str.startswith("<="):
                day_text = f"第{day_str[2:]}天前"
            else:
                day_text = f"第{day_str}天"
        time_set = set(times)
        time_text = ""
        if "ALL" not in time_set and time_set:
            time_text = "、".join(sorted(time_set))
        if day_text and time_text:
            parts.append(f"{day_text}{time_text}")
        elif day_text:
            parts.append(day_text)
        elif time_text:
            parts.append(f"需要{time_text}")
    if not parts:
        return "时间条件未满足"
    return "需要" + " 或 ".join(parts) + "时触发"


def _build_investigator_weapon(lib_wep, name_override: str = "") -> 'Weapon':
    """Build an Investigator Weapon from a LibraryWeapon dataclass.

    LibraryWeapon.damage is always a structured dict ({\"dice_n\": N, \"dice_d\": N,
    \"bonus\": N, \"use_db\": bool}), which _roll_damage() in combat.py handles
    natively — so we pass it through unchanged.
    """
    from investigator.models import Weapon as InvWeapon
    return InvWeapon(
        name=name_override or getattr(lib_wep, 'name', ''),
        skill_name=getattr(lib_wep, 'skill_name', '') or '格斗',
        damage=getattr(lib_wep, 'damage', {"dice_n": 0, "dice_d": 0, "bonus": 0, "use_db": False}),
        range=getattr(lib_wep, 'range', ''),
        malfunction=int(getattr(lib_wep, 'malfunction', 100)),
        damage_type=getattr(lib_wep, 'damage_type', '物理'),
        armor_piercing=int(getattr(lib_wep, 'armor_piercing', 0)),
        attack_bonus=int(getattr(lib_wep, 'attack_bonus', 0)),
        multi_attack=int(getattr(lib_wep, 'multi_attack', 1)),
        special_rules=getattr(lib_wep, 'special_rules', ''),
    )


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
        from monitor.agent_monitor import AgentMonitor
        from monitor.policies import KeeperPolicy
        from llm import _init_sensor
        self._sensor = _init_sensor()
        self.monitor = AgentMonitor("Keeper", self._sensor, KeeperPolicy())
        self._intent_cooldown: int = INTENT_COOLDOWN_WINDOW
        self._npc_events: list[str] = []  # NPC follow/state events collected this turn
        self._pending_side_effects: list = []  # deferred side effects (apply after Author check)
        self._pending_move: str | None = None  # deferred move target
        # ── session_state（跨回合；B1 存档设计将以此分组为入档单元）──
        self._standoff_pending: dict | None = None
        self._combat_result_pending: dict | None = None  # {outcome, narrative, is_boss} from last combat
        self._last_outcomes: list = []  # stored outcomes for combat completion replay
        self._last_player_input: str = ""  # original input that triggered combat
        self._npc_injected_at_ids: set[str] = set()  # track ATs injected from NPC bound_auto_triggers
        self._recent_intents: list[str] = []  # last N intent strings for duplicate suppression
        self.turn_monitor = TurnMonitor(self._sensor, self.world, keeper=self)
        from game.use_parser import UseParser
        self.use_parser = UseParser(
            llm_call=lambda prompt, **kw: call_deepseek(prompt, **kw))

    def set_world(self, new_world: ScenarioWorld) -> None:
        """B1②：读档重绑——所有持 world 引用的内部组件统一切换。"""
        self.world = new_world
        self.judge.world = new_world
        self.curator.world = new_world
        self.turn_monitor._world = new_world

    def dump_session_state(self) -> dict:
        return {
            "npc_injected_at_ids": sorted(self._npc_injected_at_ids),
            "recent_intents": list(self._recent_intents),
            "last_comms_time": self._last_comms_time,
        }

    def load_session_state(self, data: dict) -> None:
        self._npc_injected_at_ids = set(data.get("npc_injected_at_ids", []))
        self._recent_intents = list(data.get("recent_intents", []))
        self._last_comms_time = data.get("last_comms_time", 0)

    def _material_catalogs(self):
        """统一资源层：从世界与玩家构建 use 可解析目录（持有物 + 已知法术）。"""
        from game.use_parser import ItemCatalog, SpellCatalog
        cats = []
        p = self.world.player
        if p is not None:
            if getattr(self.world, "item_library", None):
                cats.append(ItemCatalog(self.world.item_library, p.item_manager))
            if getattr(self.world, "spell_library", None) and getattr(p, "known_spells", None):
                cats.append(SpellCatalog(self.world.spell_library, p.known_spells))
        return cats

    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> TurnResult:
        """Facade：委托 TurnRunner（_depth 参数保留兼容，不再使用）。"""
        if not hasattr(self, "_runner"):
            from ..turn.runner import TurnRunner
            self._runner = TurnRunner(self)
        return self._runner.execute(turn_input, author)

    def _build_frozen_response(self, exc: TurnFrozenError) -> TurnResult:
        return TurnResult(
            status=TurnStatus.FROZEN,
            text=str(exc) or "（回合已冻结）",
            frozen_message=str(exc) or "（回合已冻结）",
            npc_events=list(self._npc_events),
        )

    def _scan_ending(self, outcomes, author) -> dict | None:
        """Scan outcomes for ##END_ markers; enrich narrative from L3 ending_conditions."""
        from scenario_core import has_ending
        for o in outcomes:
            en, ed = has_ending(o.message)
            if not en:
                continue
            full_narrative = ed or ""
            if author and hasattr(author, 'l3_data') and author.l3_data:
                for ec_item in author.l3_data.get("ending_conditions", []):
                    eid = ec_item.get("id", "")
                    if eid == en or ec_item.get("name", eid) == en:
                        full_narrative = ec_item.get("narrative", ed)
                        break
            return {"name": en, "narrative": full_narrative, "game_over": True}
        return None

    def complete_combat_turn(self, original_input: str, combat_result: dict) -> TurnResult | None:
        """After combat resolves, replay enrich→curate with combat result injected.
        Uses stored outcomes from the original process_turn that triggered combat.
        Returns TurnResult whose brief the caller passes to narrator."""
        chronicle = getattr(self.world, "chronicle", None)
        if chronicle is not None:
            chronicle.record_combat_end(combat_result.get("outcome", ""), self.world)
        if not self._last_outcomes:
            return None
        outcomes = list(self._last_outcomes)
        self._last_outcomes = []

        # Inject combat result
        cr_outcome = combat_result.get("outcome", "")
        cr_label = {"win": "胜利", "loss": "败北", "flee": "逃脱", "draw": "平局"}.get(cr_outcome, cr_outcome)
        outcomes.append(ActionOutcome(
            intent=ActionIntent(action="combat"), success=(cr_outcome == "win"),
            message=f"战斗{cr_label}。{combat_result.get('narrative', '')}"[:200],
            entity_id="COMBAT_RESULT", entity_type="combat_result",
        ))

        # Build enrich_input from all outcomes
        enrichment = None
        enrich_entities = [
            {"entity_type": "combat_result", "id": "COMBAT_RESULT",
             "name": f"战斗{cr_label}", "result": combat_result.get("narrative", "")[:200],
             "success": cr_outcome == "win", "skill_tier": ""}
        ]
        if enrich_entities:
            enrichment = self._enrich(enrich_entities, original_input)

        emphasis = enrichment.get("emphasis_hint", "") if enrichment else ""
        result_text = enrichment.get("results", "") if enrichment else ""
        enriched_summary = result_text if isinstance(result_text, str) else ""

        ambient = [o.message for o in outcomes if o.entity_type == "auto_trigger"]
        brief = self.curator.assemble(outcomes, ambient, emphasis, enriched_summary)
        return TurnResult(
            status=TurnStatus.COMPLETED,
            brief=brief,
            diagnostics=TurnDiagnostics(enrich_raw=enrichment),
        )

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
        from prompts import log_skill_result, apply_trait_enhancement
        new_tier, _ = apply_trait_enhancement(
            self.world.player, skill_name, skill_msg,
            entity_name=f"避免与{enemy_ref}战斗",
            player_input=player_input,
        )
        if new_tier and new_tier != tier:
            skill_detail += f"\n  [特质修正] {tier} -> {new_tier}"
            tier = new_tier
            ok = (tier != "failure")

        # Step 4: Apply result
        if ok:
            from utils import normalize_skill_name as _nsn
            if _nsn(skill_name)[1] in ("魅惑", "说服"):
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
            hard_part, _, soft_part = (p.strip() for p in req_str.partition("||"))
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
        # Pure hard requirement (no || separator)
        from scenario_core import parse_hard_requirement
        return parse_hard_requirement(req_str.strip(), self.world.runtime_state)

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
        """Inject current-scene NPC bound entities into the scene node so parse sees them."""
        if not self.world.npcs:
            return
        node = self.world._current_node()
        if not node:
            return
        from scenario_core import Entity
        injected = self._npc_injected_at_ids
        for npc_name, npc in self.world.npcs._npcs.items():
            if npc.scene != self.world.current_location:
                continue
            if npc.state in ("dead", "left"):
                continue
            for ent in npc.bound_interactions:
                eid = ent.get("id", "")
                if not eid or eid in injected:
                    continue
                if self.world.is_entity_completed(eid) and not (
                    ent.get("repeatable") or (ent.get("extra") or {}).get("repeatable")
                ):
                    continue
                node.interactions.append(Entity.from_dict(ent, overrides={
                    "entity_type": "interaction",
                    "scene": npc.scene or self.world.current_location,
                }))
                injected.add(eid)
            for at in npc.bound_auto_triggers:
                eid = at.get("id", "")
                if not eid or eid in injected:
                    continue
                if self.world.is_entity_completed(eid) and not (
                    at.get("repeatable") or (at.get("extra") or {}).get("repeatable")
                ):
                    continue
                node.auto_triggers.append(Entity.from_dict(at, overrides={
                    "entity_type": "auto_trigger",
                    "scene": npc.scene or self.world.current_location,
                }))
                injected.add(eid)

    # ── Internal ──

    def _apply_pending(self):
        """Apply all deferred side effects and move collected during this turn."""
        if self._pending_move:
            result = self.world.move(self._pending_move)
            self._pending_move = None
        if self._pending_side_effects:
            from scenario_core import apply_side_effects
            def _direct_weapon(wref):
                lib = self.world.weapon_library
                lib_wep = lib.get(wref) if lib else None
                if lib_wep and self.world.player:
                    self.world.player.add_weapon(
                        _build_investigator_weapon(lib_wep, name_override=wref))
            effect_msgs = apply_side_effects(
                self.world, list(self._pending_side_effects),
                npc_events=self._npc_events,
                direct_weapon_callback=_direct_weapon,
            )
            for m in effect_msgs or []:
                if "失败" in m:
                    self._warnings.append(m)
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
                node.interactions.append(Entity.from_dict({
                    "id": follow_eid, "entity_type": "interaction",
                    "name": f"{npc.name}开始跟随你",
                    "scene": self.world.current_location, "type": "无",
                    "requirement": req_text,
                    "trigger": f"你请求{npc.name}跟随你一起行动",
                    "result": f"{npc.name}加入了你的队伍，你可以随时与其交谈",
                    "difficulty": "None",
                }))

    _PICKUP_RE = re.compile(r"(捡|拾|拿起|拿上|拿走|取|拔|抓|收)")
    _NEGATIVE_RE = re.compile(r"(不|别|勿|甭)")

    def _detect_direct_pickup(self, raw: str) -> tuple[str, str, bool] | None:
        """直接拾取意图（R1）：拾取动词 + 场景物品名；仅一件暴露且未持有时可不点名。
        含否定词（不/别/勿）时不触发。返回 (kind, ref, hidden) 或 None。"""
        if not self._PICKUP_RE.search(raw) or self._NEGATIVE_RE.search(raw):
            return None
        if not self.world.player:
            return None
        self.world._hydrate_scene_items_from_weapons()
        scene = self.world.current_location
        items = list(self.world.scene_items.get(scene, []))
        named = [it for it in items if it.ref and it.ref in raw]
        if named:
            it = max(named, key=lambda x: len(x.ref))
            return (it.kind, it.ref, it.hidden)
        owned_w = {w.name for w in self.world.player.weapons}
        def _owned(it) -> bool:
            if it.kind == "weapon":
                return it.ref in owned_w
            return self.world.player.item_manager.has(it.ref)
        pool = [it for it in items if not it.hidden and not _owned(it)]
        if len(pool) == 1:
            it = pool[0]
            return (it.kind, it.ref, False)
        return None

    def _grant_scene_item(self, kind: str, ref: str) -> str:
        """发放一件场景物品入包并从场景移除（quantity>1 则减一）。"""
        scene = self.world.current_location
        items = self.world.scene_items.get(scene, [])
        target = next((i for i in items if i.kind == kind and i.ref == ref), None)
        if target is None:
            return ref
        if kind == "weapon":
            lib = self.world.weapon_library
            lib_wep = lib.get(ref) if lib else None
            if not (lib_wep and self.world.player):
                return ref
            self.world.player.add_weapon(
                _build_investigator_weapon(lib_wep, name_override=ref))
        elif self.world.player:
            self.world.player.item_manager.add(ref)
        if target.quantity > 1:
            target.quantity -= 1
        else:
            items.remove(target)
        if not items:
            self.world.scene_items.pop(scene, None)
        self.world._sync_scene_weapons_from_items()
        return ref

    def _devour_standoff_for_boss(self, standoff_prompt, combat_init_result,
                                  all_outcomes, enrich_input):
        """F3：Boss 强制战吞掉对峙——撤回 standoff 播种/话术，
        avoidable 敌人一并卷入 Boss 战。返回 None（清空 standoff_prompt）。"""
        self._standoff_pending = None
        all_outcomes[:] = [o for o in all_outcomes
                           if o.entity_id != "STANDOFF"]
        if enrich_input is not None:
            enrich_input.entities[:] = [e for e in enrich_input.entities
                                        if e.get("id") != "STANDOFF"]
        if self.world.enemies and combat_init_result is not None:
            in_combat = {e.instance_id for e in combat_init_result.enemies}
            dragged = [
                inst for inst in self.world.enemies.get_active_in_scene(
                    self.world.current_location)
                if inst.status not in ("dead", "defeated")
                and "avoidable" in inst.flags
                and inst.instance_id not in in_combat
            ]
            if dragged:
                self.world.enemies.enter_combat(
                    [i.instance_id for i in dragged])
                combat_init_result.enemies.extend(dragged)
        return None

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
                       "\n" + KEEPER_PARSE_MADNESS_RULE +
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
        """Find entity by ID across graph + NPCs + boss encounters."""
        from scenario_core import find_entity_by_id
        found = find_entity_by_id(self.world, entity_id)
        if found:
            return found
        # NPC bound entities — dynamically resolved, follow the NPC's current location
        if self.world.npcs:
            from scenario_core import Entity
            for npc in self.world.npcs._npcs.values():
                if npc.scene != self.world.current_location:
                    continue
                for ent in npc.bound_interactions + npc.bound_auto_triggers:
                    eid = ent.get("id", "")
                    if eid != entity_id:
                        continue
                    if self.world.is_entity_completed(eid) and not (
                        ent.get("repeatable") or (ent.get("extra") or {}).get("repeatable")
                    ):
                        continue
                    return Entity.from_dict(ent, overrides={
                        "scene": ent.get("source_scene", ""),
                    })
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

    def _process_deterministic_only(self, turn_input: TurnInput) -> TurnResult:
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
        return TurnResult(status=TurnStatus.COMPLETED, brief=brief)

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
            parts.append(f"NPC: {', '.join(npc_names[:5])}")
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
            "chronicle": self.world.chronicle.render_for_author(self.world),
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
                    graph.events[eid] = Entity.from_dict(ev, overrides={
                        "entity_type": "event",
                    })

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

            entity_ids = [ev.get("id", "") for ev in l2.get("events", [])]
            for scene_data in l2.get("scenes", {}).values():
                entity_ids.extend(e.get("id", "") for e in scene_data.get("interactions", []))
                entity_ids.extend(e.get("id", "") for e in scene_data.get("auto_triggers", []))
            self.world.chronicle.record_patch(
                turn=self.turn_number,
                level="structural",
                entity_ids=entity_ids,
                new_scenes=list(l2.get("scenes", {}).keys()),
                justification=structural_edit.justification,
            )
        except Exception as e:
            self._warnings.append(f"补充管线失败（{e}），继续正常流程。")
            structural_edit.supplement_path = ""

        return structural_edit

    def _load_scene_into_graph(self, scene_name: str, scene_data: dict):
        """Load a single scene dict into DirectedGraph."""
        from scenario_core import Entity as EntityClass, Edge, Node
        graph = self.world.graph

        interactions = [
            EntityClass.from_dict(inter, overrides={
                "entity_type": inter.get("entity_type", "interaction"),
                "scene": inter.get("scene", scene_name),
            })
            for inter in scene_data.get("interactions", [])
        ]
        auto_triggers = [
            EntityClass.from_dict(at, overrides={
                "entity_type": at.get("entity_type", "auto_trigger"),
                "scene": at.get("scene", scene_name),
            })
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

    def _integrate_patch(self, patch):
        """Integrate ModulePatch entities into world graph."""
        from scenario_core import Entity as EntityClass
        integrated_ids = []
        for ent_data in patch.entities:
            entity = EntityClass.from_dict(ent_data, overrides={
                "id": ent_data.get("id", f"NEW_{hash(ent_data['name'])%10000}"),
            })
            integrated_ids.append(entity.id)
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
        self.world.chronicle.record_patch(
            turn=self.turn_number,
            level="patch",
            entity_ids=integrated_ids,
            new_scenes=[],
            justification=patch.justification,
        )
