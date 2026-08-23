"""Deterministic gate — requirement check, skill check, @markup resolution."""
from __future__ import annotations
from typing import TYPE_CHECKING
import re as _re
import json

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld, Entity, ActionResult

from game.side_effects import parse_markup_all
from scenario_core import resolve_graded_result

_MARKUP_STRIP_RE = _re.compile(
    r'\s*@(spawn_enemy|grant_weapon|grant_spell|stat_change|item_gain|consume_item|npc_state_change|npc_follow)'
    r'\([^)]*\)'
)
from .messages import ActionIntent, ActionOutcome
from prompts import log_skill_result, _build_scene_context

_ENTITY_ID_RE = _re.compile(r'^([IEA]+\d+)$')  # e.g. I1, AT2, E3

_DIFFICULTY_ORDER = {"regular": "hard", "hard": "extreme"}


def _escalate_difficulty(difficulty: str) -> str:
    """Escalate difficulty by one level: regular→hard→extreme. Already extreme stays."""
    return _DIFFICULTY_ORDER.get(difficulty, difficulty)


class Judge:
    """Deterministic gate for entity execution.

    No LLM dependencies. Handles:
    - Auto-trigger condition checking
    - Flag-based + entity-ID-based requirement gating
    - Skill check gating + tier determination
    - ##GRADED## result resolution (inline, after skill check)
    - Completion flag setting
    - @markup side effect resolution
    """

    def __init__(self, world: ScenarioWorld):
        self.world = world

    # ── Auto-triggers ──

    def check_auto_triggers(self) -> list[ActionOutcome]:
        """Check all ATs in current scene. Fire those with simple requirements met."""
        results = []
        node = self.world._current_node()
        if not node:
            return results

        for at in node.auto_triggers:
            if not self._check_simple_requirement(at):
                continue
            outcome = self._execute_entity(at)
            results.append(outcome)
        return results

    # ── Interactions ──

    def execute_interaction(self, intent: ActionIntent, player_input: str = "") -> ActionOutcome:
        """Execute a parsed interaction intent through the gate."""
        node = self.world._current_node()
        if not node:
            return ActionOutcome(intent=intent, success=False,
                                message="当前场景不存在。")

        entity = node.get_interaction(intent.target)
        if not entity:
            available = ', '.join(e.name for e in node.interactions)
            return ActionOutcome(intent=intent, success=False,
                                message=f"没有动作「{intent.target}」。可用：{available or '无'}")

        return self._execute_entity(entity, intent=intent, player_input=player_input)

    def execute_material(self, material, player_input: str = "") -> ActionOutcome:
        """L1 执行通道：use 动作确定性结算。
        硬门（已知/持有/MP/材料）-> 扣减（refund_on_fail 回滚）-> 可选检定
        -> 结果槽 -> on_use @markup 副作用。L0 无消耗无检定时纯叙事。"""
        player = self.world.player
        intent = ActionIntent(action="use", target=material.name)

        def _fail(msg: str) -> ActionOutcome:
            return ActionOutcome(intent=intent, success=False, message=msg,
                                 entity_id=material.material_id,
                                 entity_type="material")

        if player is None:
            return _fail("（无调查员，无法使用素材。）")
        if material.catalog_kind == "spell" and material.material_id not in player.known_spells:
            return _fail(f"你尚未习得「{material.name}」。")

        cost = material.cost or {}
        need_mp = int(cost.get("mp", 0) or 0)
        need_san = int(cost.get("san", 0) or 0)
        if need_mp and player.derived.MP < need_mp:
            return _fail(f"MP不足：需要 {need_mp}，当前 {player.derived.MP}。")
        for mat in (material.constraints or {}).get("materials", []):
            if not player.item_manager.has(mat):
                return _fail(f"缺少材料：{mat}。")

        # L0 且零消耗无检定且无副作用（on_use/effect 对称）：纯叙事
        if (material.impact == "L0" and not need_mp and not need_san
                and not material.check and not material.on_use
                and not getattr(material, "effect", None)):
            text = (material.result_slots or {}).get("on_success") or material.description
            return ActionOutcome(intent=intent, success=True, message=text,
                                 entity_id=material.material_id,
                                 entity_type="material")

        # 扣减（原子）
        if need_mp:
            player.derived.MP -= need_mp
        if need_san:
            player.derived.SAN = max(0, player.derived.SAN - need_san)
        consumed_item = None
        if (material.catalog_kind == "item"
                and material.use_semantic == "consume"):
            if not player.item_manager.has(material.name):
                if need_mp:
                    player.derived.MP += need_mp
                return _fail(f"你没有「{material.name}」。")
            player.item_manager.remove(material.name, 1)
            consumed_item = material.name

        # 可选检定（检定能力下沉：复用 check_skill 全套）
        skill_tier = ""
        skill_detail = ""
        success = True
        if material.check:
            cskill = material.check.get("skill", "")
            ctype = material.check.get("type", "regular")
            if ctype == "opposed":
                from investigator.rules import opposed_check
                def_val = int((material.constraints or {}).get("opposed_value", 50))
                att_val = player.get_skill_value(cskill) or getattr(
                    player.stats, cskill, 50)
                outcome, detail = opposed_check(att_val, def_val)
                skill_detail = f"[use] {material.name} | 对抗 {cskill}={att_val} vs {def_val} | {detail}"
                success = outcome == "win"
                skill_tier = "regular" if success else "failure"
            else:
                ok, msg, skill_tier = player.check_skill(
                    cskill, "hard" if ctype == "hard" else "regular")
                skill_detail = f"[use] {material.name} | {cskill} | {msg}"
                success = ok
            log_skill_result(skill_detail)

        if not success and material.refund_on_fail:
            if need_mp:
                player.derived.MP += need_mp
            if need_san:
                player.derived.SAN += need_san
            if consumed_item:
                player.item_manager.add(consumed_item, quantity=1)

        # 结果槽（tier 选用）
        slots = material.result_slots or {}
        if success:
            text = ((slots.get("on_extreme") if skill_tier == "extreme" else "")
                    or (slots.get("on_hard") if skill_tier == "hard" else "")
                    or slots.get("on_success")
                    or f"你使用了{material.name}。")
        else:
            text = slots.get("on_failure") or f"{material.name}没有产生效果。"

        # on_use @markup -> 统一副作用底座
        side_effects = parse_markup_all(" ".join(material.on_use)) if material.on_use else []
        side_msgs = []
        if side_effects:
            from scenario_core import apply_side_effects
            side_msgs = apply_side_effects(self.world, side_effects)

        # effect 原子数组(2026-08-21 spec §1.2 探索侧;检定失败不结算,防退款后免费获益)
        eff_msgs = (self._execute_effect_atoms(getattr(material, "effect", None) or [], player)
                    if success else [])

        message = text + ("".join(f"\n{m}" for m in side_msgs + eff_msgs))
        return ActionOutcome(
            intent=intent, success=success, message=message,
            entity_id=material.material_id, entity_type="material",
            side_effects=side_effects, skill_tier=skill_tier,
            skill_detail=skill_detail,
        )

    def _execute_effect_atoms(self, effects: list, player) -> list[str]:
        """探索侧 effect 原子结算(spec §1.2 探索列)。返回追加进 message 的行。"""
        import re
        import logging
        import random
        from investigator.rules import get_game_config
        cfg = get_game_config()
        logger = logging.getLogger("game.judge")
        msgs: list[str] = []

        def _roll(formula: str) -> int:
            m = re.match(r"^(\d*)D(\d+)([+-]\d+)?$", str(formula).strip().upper())
            if not m:
                return 0
            n = int(m.group(1) or 1)
            d = int(m.group(2))
            bonus = int(m.group(3) or 0)
            return sum(random.randint(1, d) for _ in range(n)) + bonus

        for atom in effects or []:
            t = atom.get("type", "")
            if t == "heal":
                delta = max(0, int(atom.get("delta", 0) or 0))
                if "formula" in atom:
                    delta = _roll(str(atom["formula"]))
                if delta:
                    before = player.derived.HP
                    player.derived.HP = min(player.derived.HP_MAX,
                                            player.derived.HP + delta)
                    msgs.append(f"（恢复 {player.derived.HP - before} 点 HP。）")
            elif t == "mp_change":
                delta = int(atom.get("delta", 0) or 0)
                if delta:
                    before = player.derived.MP
                    player.derived.MP = max(0, min(player.derived.MP_MAX,
                                                   player.derived.MP + delta))
                    msgs.append(f"（MP {player.derived.MP - before:+d}。）")
            elif t == "markup":
                from scenario_core import apply_side_effects
                effs = parse_markup_all(str(atom.get("text", "")))
                if effs:
                    msgs.extend(apply_side_effects(self.world, effs))
            elif t == "timed":
                minutes = int(atom.get("minutes", 0)
                              or cfg["timed_default_minutes"])
                # 同 id refresh:替换旧条目刷新时效,不叠条
                player.timed_effects = [te for te in player.timed_effects
                                        if te.get("id") != str(atom.get("id", "TIMED"))]
                player.timed_effects.append({
                    "id": str(atom.get("id", "TIMED")),
                    "description": str(atom.get("description", "")),
                    "expire_at": self.world.clock.game_time + minutes,
                })
            elif t == "damage":
                # 探索侧无伤害目标:跳过 + 日志,不硬造(spec §1.2)
                logger.warning("[effect] damage 原子在探索侧跳过: %s", atom)
            elif t in ("buff", "control"):
                logger.warning("[effect] %s 原子探索侧降级为文本: %s", t, atom)
                desc = str(atom.get("description", "") or f"（{t} 效果仅在战斗中生效。）")
                msgs.append(desc)
            elif t == "narrative":
                msgs.append(str(atom.get("text", "") or ""))
            else:
                # 未知 type:标识符前缀降级(spec §1.3)
                if t:
                    logger.warning("[effect] 未知 type 原子降级进结果: %s", atom)
                text = str(atom.get("text") or atom.get("description") or "")
                msgs.append(f"[unknown:{t}] {text}" if t else text)
        return msgs

    # ── Internal ──

    def _set_completion_flag(self, entity: Entity, tier: str = ""):
        """Mark entity completed in runtime_state with optional result tier."""
        self.world.mark_completed(entity.id, tier)

    def _find_entity_by_id(self, entity_id: str):
        """Find an entity by ID across graph. Delegates to shared lookup."""
        from scenario_core import find_entity_by_id
        return find_entity_by_id(self.world, entity_id)

    def _is_entity_completed(self, entity) -> bool:
        """Check if an entity has been completed/triggered via runtime_state."""
        return self.world.is_entity_completed(entity.id)

    def _execute_entity(self, entity: Entity, intent: ActionIntent | None = None, player_input: str = "") -> ActionOutcome:
        """Run entity through gate and execute."""
        if self._is_entity_completed(entity):
            return ActionOutcome(
                intent=intent or ActionIntent(action="other"),
                success=False, message="（该实体已触发过，无法重复执行）",
                entity_id=entity.id, entity_type=entity.entity_type,
            )

        # ── NPC Special entities: follow_unlock / interact_unlock ──
        # Hard requirements already evaluated by _build_entity_lines before parse;
        # soft requirements evaluated by Parse (LLM). Here we just execute state change.
        extra = entity.extra or {}
        npc_special = extra.get("npc_special", "")
        if npc_special in ("follow_unlock", "interact_unlock"):
            npc_name = extra.get("npc_name", "")
            if not npc_name or not self.world.npcs:
                return ActionOutcome(
                    intent=intent or ActionIntent(action="other"),
                    success=False, message="（NPC 配置异常）",
                    entity_id=entity.id, entity_type=entity.entity_type,
                )
            npc = self.world.npcs.get(npc_name)
            if not npc:
                return ActionOutcome(
                    intent=intent or ActionIntent(action="other"),
                    success=False, message=f"（{npc_name} 不在此处）",
                    entity_id=entity.id, entity_type=entity.entity_type,
                )

            if npc_special == "follow_unlock":
                self.world.npcs.set_following(npc_name, True)
                self._set_completion_flag(entity, "")
                return ActionOutcome(
                    intent=intent or ActionIntent(action="other"),
                    success=True,
                    message=entity.result or f"{npc_name}开始跟随你",
                    entity_id=entity.id, entity_type=entity.entity_type,
                )

            if npc_special == "interact_unlock":
                npc.can_interact = True
                self._set_completion_flag(entity, "")
                return ActionOutcome(
                    intent=intent or ActionIntent(action="other"),
                    success=True,
                    message=entity.result or f"{npc_name}愿意与你交谈了",
                    entity_id=entity.id, entity_type=entity.entity_type,
                )
        # ── End NPC special ──

        # Check structured requirements (world flags + entity IDs) — hard part only
        if entity.requirement and entity.requirement.strip():
            self._current_entity_id = entity.id
            hard, _ = self._split_requirement(entity.requirement)
            if hard:
                met, msg = self._evaluate_requirement(hard)
                if not met:
                    return ActionOutcome(
                        intent=intent or ActionIntent(action="other"),
                        success=False, message=msg,
                        entity_id=entity.id, entity_type=entity.entity_type
                    )

        # Note: soft requirements (after ||) are evaluated by Parse (LLM) step,
        # not duplicated here. See build_keeper_parse_prompt for soft condition handling.

        # Skill check + ##GRADED## resolution
        skill_tier = ""
        skill_passed = True
        skill_message = ""
        skill_detail = ""
        enh = None

        if self.world.player and entity.type and entity.type not in ("无", "None", ""):
            skill_name = entity.type
            intent_skill = intent.skill_checks[0] if (intent and intent.skill_checks) else skill_name
            difficulty = entity.difficulty if entity.difficulty not in ("None", "", None) else "regular"
            state = self.world.get_runtime_state(entity.id)
            if state.escalated_difficulty:
                difficulty = state.escalated_difficulty
            all_pass, skill_result, skill_tier = self.world.player.check_skill(intent_skill, difficulty)

            skill_passed = all_pass
            skill_message = skill_result
            skill_detail = (
                f"[{entity.id}] {entity.name} | 技能={skill_name} | "
                f"难度={difficulty} | 骰子等级={skill_tier} | {'成功' if all_pass else '失败'}\n"
                f"  {skill_result}"
            )
            log_skill_result(skill_detail)

            # Rule enhancement: trait-based tier correction via LLM sub-agent
            from prompts import apply_trait_enhancement
            new_tier, enh = apply_trait_enhancement(
                self.world.player, skill_name, skill_result,
                entity_name=entity.name,
                graded_tiers=entity.graded_result,
                player_input=player_input,
            )
            if new_tier and new_tier != skill_tier:
                enh = enh or {}
                enh["original_tier"] = skill_tier
                skill_tier = new_tier
                skill_passed = (skill_tier != "failure")

        # Resolve result text (handle ##GRADED##)
        result_text = entity.result
        has_graded = "##GRADED##" in result_text
        if skill_tier:
            result_text = resolve_graded_result(entity, skill_tier)

        # Extract @markup from result text before stripping
        result_markup_effects = parse_markup_all(result_text)

        # Strip @markup from result text — deterministic side effects, LLM doesn't need them
        result_text = _MARKUP_STRIP_RE.sub("", result_text).strip()

        # Use resolved graded text as the primary message (not raw D100 string)
        if has_graded:
            skill_message = result_text

        if not skill_passed:
            # Failure penalty: retry tracking + difficulty escalation via runtime_state
            state = self.world.get_runtime_state(entity.id)
            retries = state.retries

            # First failure: escalate difficulty by one level
            if retries == 0:
                new_diff = _escalate_difficulty(difficulty)
                if new_diff != difficulty:
                    state.escalated_difficulty = new_diff
                    skill_detail += f"\n  [难度递增] {difficulty} → {new_diff}"
                    log_skill_result(skill_detail)

            state.retries = retries + 1

            # After difficulty locked (2nd+ failure): LLM creative consequence
            penalty_side_effects = []
            if retries >= 2:
                inv_desc = getattr(self.world.player, 'personal_description', '') or \
                           getattr(self.world.player, 'description', '')
                scene_ctx = _build_scene_context(self.world.build_snapshot())
                graded_on_failure = ""
                if entity.graded_result and isinstance(entity.graded_result, dict):
                    graded_on_failure = entity.graded_result.get("on_failure", "")

                if inv_desc:
                    from llm import evaluate_failure_penalty
                    penalty = evaluate_failure_penalty(
                        inv_desc=inv_desc,
                        entity_name=entity.name,
                        skill_name=skill_name,
                        skill_detail=skill_result,
                        failure_tier=skill_tier,
                        scene_context=scene_ctx,
                        graded_on_failure=graded_on_failure,
                        retry_count=retries,
                    )
                    if penalty.get("narrative"):
                        skill_message = penalty["narrative"]
                    for markup in penalty.get("markup_effects", []):
                        parsed = parse_markup_all(markup)
                        penalty_side_effects.extend(parsed)
                    skill_detail += f"\n  [失败惩罚] {skill_message}"
                    log_skill_result(skill_detail)

            return ActionOutcome(
                intent=intent or ActionIntent(action="other"),
                success=False, message=skill_message,
                entity_id=entity.id, entity_type=entity.entity_type,
                skill_tier=skill_tier,
                skill_detail=skill_detail,
                enhancement=enh,
                side_effects=penalty_side_effects + list(result_markup_effects),
            )

        # Execute — mark completion
        if entity.entity_type == "interaction":
            loc = self.world.current_location
            if loc not in self.world.completed_interactions:
                self.world.completed_interactions[loc] = set()
            self.world.completed_interactions[loc].add(entity.name)
        elif entity.entity_type == "event":
            self.world.triggered_events[entity.id] = True

        # Set completion flag
        self._set_completion_flag(entity, skill_tier)

        # Resolve side effects — from entity.side_effects field + @markup in result_text
        side_effects = list(result_markup_effects)
        for se_text in entity.side_effects:
            parsed = parse_markup_all(se_text)
            side_effects.extend(parsed)

        return ActionOutcome(
            intent=intent or ActionIntent(action="other"),
            success=True,
            message=result_text,
            entity_id=entity.id,
            entity_type=entity.entity_type,
            side_effects=side_effects,
            skill_tier=skill_tier,
            skill_detail=skill_detail,
            enhancement=enh,
        )

    @staticmethod
    def _split_requirement(req: str) -> tuple[str, str]:
        """Split requirement by '||': hard (before) | soft (after)."""
        if not req:
            return "", ""
        parts = req.split("||", 1)
        hard = parts[0].strip() if parts[0] else ""
        soft = parts[1].strip() if len(parts) > 1 else ""
        return hard, soft

    # ── Requirement checking ──

    def _is_simple_requirement(self, req: str) -> bool:
        hard, _ = self._split_requirement(req)
        if not hard:
            return True
        # Any hard string with recognizable IDs or logical operators can be parsed
        if "OR" in hard or "AND" in hard:
            return True
        if _ENTITY_ID_RE.match(hard.strip().strip("()（）")):
            return True
        return False

    def _check_simple_requirement(self, entity: Entity) -> bool:
        if not entity.requirement or not entity.requirement.strip():
            return True
        hard, _ = self._split_requirement(entity.requirement)
        if not hard:
            return True
        if self._is_simple_requirement(hard):
            met, _ = self._evaluate_requirement(hard)
            return met
        return False

    def _evaluate_requirement(self, req: str) -> tuple[bool, str]:
        """Evaluate hard requirement string using flag check + AND/OR parser + edge graph.

        Order:
        0. Flag-based requirement check FIRST (flag:xxx)
        1. String-based AND/OR parsing (handles OR semantics)
        2. Edge-based dependency check SECOND (structural AND, secondary)
        3. No ID found → pass (graceful degradation for LLM-generated text)
        """
        req = req.strip()
        if not req:
            return True, ""

        # 统一资源层：item:物品名 硬条件（持有检查）先行短路
        _item_toks = _re.findall(r"item[:：]([^&|（）()\s]+)", req)
        if _item_toks:
            p = self.world.player
            for tok in _item_toks:
                tok = tok.strip()
                if not (p and getattr(p, 'item_manager', None) and p.item_manager.has(tok)):
                    return False, f"需要物品：{tok}"
            req = _re.sub(r"item[:：][^&|（）()\s]+", "", req).strip(" &|ANDORandor")
            if not req:
                return True, ""

        # Step 0: check for flag-based requirements (flag:xxx)
        if req.startswith("flag:"):
            flag_name = req[5:].strip()
            state = self.world.runtime_state.get(flag_name)
            if not state or not state.completed:
                return False, f"需要满足条件「{flag_name}」"
            return True, ""

        # Step 1: string-based AND/OR parsing FIRST (handles OR semantics)
        from scenario_core import parse_hard_requirement
        met = parse_hard_requirement(req, self.world.runtime_state)
        if met:
            return True, ""

        # Step 2: edge-based dependency check (structural AND, secondary)
        entity_id = getattr(self, '_current_entity_id', '')
        if entity_id:
            met, msg = self.world.check_edge_requirements(entity_id)
            if not met:
                return False, msg

        return True, ""
