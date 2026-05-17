"""Deterministic gate — requirement check, skill check, @markup resolution."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld, Entity, ActionResult

from scenario_core import parse_markup_all, resolve_graded_result
from .messages import ActionIntent, ActionOutcome
from prompts import log_skill_result


class Judge:
    """Deterministic gate for entity execution.

    No LLM dependencies. Handles:
    - Auto-trigger condition checking
    - Flag-based requirement gating
    - Skill check gating
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

    def execute_interaction(self, intent: ActionIntent) -> ActionOutcome:
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

        return self._execute_entity(entity, intent=intent)

    # ── Internal ──

    def _set_completion_flag(self, entity: Entity):
        """Set world flag when entity completes."""
        flag_key = f"{entity.id}_done"
        self.world.set_flag(flag_key, True)

    def _execute_entity(self, entity: Entity, intent: ActionIntent | None = None) -> ActionOutcome:
        """Run entity through gate and execute."""
        # Check structured requirements (world flags)
        if entity.requirement and self._is_simple_requirement(entity.requirement):
            met, msg = self._evaluate_simple_requirement(entity.requirement)
            if not met:
                return ActionOutcome(
                    intent=intent or ActionIntent(action="other"),
                    success=False, message=msg,
                    entity_id=entity.id, entity_type=entity.entity_type
                )

        # Skill check + ##GRADED## resolution
        skill_tier = None
        skill_passed = True
        skill_message = ""
        if entity.type and entity.type not in ("无", "None", ""):
            if self.world.player and intent and intent.skill_checks:
                all_pass, skill_result = self.world.player.check_skills(intent.skill_checks)
                log_skill_result(skill_result)
                skill_passed = all_pass
                skill_message = skill_result
                # Determine tier for ##GRADED##
                if all_pass:
                    result_text = str(skill_result)
                    if "极限" in result_text:
                        skill_tier = "extreme"
                    elif "困难" in result_text or "极难" in result_text:
                        skill_tier = "hard"
                    else:
                        skill_tier = "regular"
                else:
                    skill_tier = "failure"
            elif self.world.player is not None:
                skill_passed = False
                skill_message = f"需要进行{entity.type}检定但无可用技能数据"
                skill_tier = "failure"

        # Resolve result text (handle ##GRADED##)
        result_text = entity.result
        if skill_tier:
            result_text = resolve_graded_result(entity, skill_tier)

        if not skill_passed:
            return ActionOutcome(
                intent=intent or ActionIntent(action="other"),
                success=False, message=skill_message,
                entity_id=entity.id, entity_type=entity.entity_type
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
        self._set_completion_flag(entity)

        # Resolve side effects
        side_effects = []
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
        )

    def _is_simple_requirement(self, req: str) -> bool:
        """Check if requirement can be resolved deterministically."""
        if not req or not req.strip():
            return True
        return req.startswith("flag:") or "需要先完成" in req

    def _check_simple_requirement(self, entity: Entity) -> bool:
        """Check if entity's requirement is met deterministically."""
        if not entity.requirement or not entity.requirement.strip():
            return True
        if self._is_simple_requirement(entity.requirement):
            met, _ = self._evaluate_simple_requirement(entity.requirement)
            return met
        return False

    def _evaluate_simple_requirement(self, req: str) -> tuple[bool, str]:
        """Evaluate a simple (deterministic) requirement string."""
        if req.startswith("flag:"):
            flag_name = req[5:]
            if self.world.flags.get(flag_name, False):
                return True, ""
            return False, f"行动失败！需要满足条件「{flag_name}」"
        return True, ""
