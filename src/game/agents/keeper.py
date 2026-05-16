"""Keeper agent — orchestrates the turn: parse → judge → enrich → curate → escalate."""
from __future__ import annotations
from typing import Any
import json

from scenario_core import ScenarioWorld, Entity, parse_markup_all
from ..messages import (
    ActionIntent, ActionOutcome, NarratorBrief,
    EscalationRequest, TurnInput,
)
from ..judge import Judge
from ..curator import Curator
from ..escalation import EscalationPolicy, EscalationContext
from prompts import build_keeper_parse_prompt, build_keeper_enrich_prompt
from llm import call_deepseek


class Keeper:
    """Keeper agent. Owns L2 + ScenarioWorld, coordinates the turn.

    Must never: output directly to player.
    """

    def __init__(
        self,
        world: ScenarioWorld,
        dependency_graph: dict | None = None,
        phase1: dict | None = None,
        escalation_policy: EscalationPolicy | None = None,
        npc_profiles: dict[str, Any] | None = None,
    ):
        self.world = world
        self.dependency_graph = dependency_graph or {}
        self.phase1 = phase1 or {}
        self.escalation_policy = escalation_policy or EscalationPolicy()
        self.npc_profiles = npc_profiles or {}

        self.judge = Judge(world)
        self.curator = Curator(world)
        self.turn_number = 0
        self.escalation_history: list[str] = []  # recent escalation dimension names

    def process_turn(self, turn_input: TurnInput, author: Any = None) -> dict:
        """Execute full turn: parse → judge → enrich → escalate → curate.

        Returns dict with keys: brief, narrative (None until narrate), escalation (EscalationRequest | None)
        """
        self.turn_number += 1
        raw = turn_input.raw_text

        # Step 1: Parse
        parsed = self._parse(raw)

        # Step 2: Deterministic judge
        at_results = self.judge.check_auto_triggers()
        action_outcomes = []
        for intent in parsed:
            if intent.action == "interact":
                outcome = self.judge.execute_interaction(intent)
                self._apply_side_effects(outcome.side_effects)
                action_outcomes.append(outcome)
            elif intent.action == "move":
                result = self.world.move(intent.target)
                action_outcomes.append(ActionOutcome(
                    intent=intent, success=result.success,
                    message=result.message,
                    side_effects=result.side_effects,
                ))
                self._apply_side_effects(result.side_effects)
            elif intent.action == "search":
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
                action_outcomes.append(ActionOutcome(
                    intent=intent, success=True, message=msg))
            else:
                action_outcomes.append(ActionOutcome(
                    intent=intent, success=True,
                    message="（没有特别的事情发生）"))

        # Step 3: LLM Enrich
        deferred_ats = self.judge.get_deferred_auto_triggers()
        pending_events = self.judge.filter_pending_events()

        enriched_ats = []
        enriched_events = []
        emphasis = ""
        if deferred_ats or pending_events or any(
            "##GRADED##" in o.message for o in action_outcomes
        ):
            enrichment = self._enrich(
                action_outcomes, list(at_results),
                deferred_ats, pending_events, raw
            )
            emphasis = enrichment.get("emphasis_hint", "")
            # Fire enriched ATs
            for at_id in enrichment.get("triggered_ats", []):
                node = self.world._current_node()
                if node:
                    for at in node.auto_triggers:
                        if at.id == at_id:
                            outcome = self._execute_entity_direct(at)
                            enriched_ats.append(outcome)
                            self._apply_side_effects(outcome.side_effects)
                            break
            # Fire enriched events
            for ev_id in enrichment.get("triggered_events", []):
                ev = self.world.graph.events.get(ev_id)
                if ev:
                    outcome = self._execute_entity_direct(ev)
                    enriched_events.append(outcome)
                    self._apply_side_effects(outcome.side_effects)
            # Apply new flags
            for flag_key, flag_val in enrichment.get("new_flags", {}).items():
                self.world.set_flag(flag_key, flag_val)

        all_outcomes = action_outcomes + list(at_results) + enriched_ats + enriched_events

        # Step 4: Escalation check
        escalation_req = self._check_escalation(raw, parsed, all_outcomes, at_results)

        if escalation_req and author:
            patch = author.handle_escalation(escalation_req)
            self._integrate_patch(patch)
            # Re-execute from step 2 with new entities
            return self.process_turn(turn_input, author)

        # Step 5: Curate
        ambient = [a.message for a in list(at_results) + enriched_ats]
        brief = self.curator.assemble(all_outcomes, ambient, emphasis)

        # Record to memory
        first_intent = parsed[0] if parsed else ActionIntent(action="other")
        brief_text = "\n".join(o.message for o in all_outcomes)
        self.world.memory.add_record(
            raw, first_intent.action, first_intent.target,
            brief_text, location=self.world.current_location,
            success=any(o.success for o in action_outcomes)
        )

        # Memory compression check
        if self.world.memory.should_compress():
            self.world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

        return {"brief": brief, "escalation": escalation_req}

    # ── Internal ──

    def _parse(self, raw: str) -> list[ActionIntent]:
        prompt = build_keeper_parse_prompt(self.world, raw)
        response = call_deepseek(prompt, json_mode=True)
        data = json.loads(response) if isinstance(response, str) else response
        actions = data.get("actions", [])
        if not actions:
            return [ActionIntent(action="other")]
        return [
            ActionIntent(
                action=a.get("action", "other"),
                target=a.get("target", ""),
                skill_checks=a.get("skill_checks", []),
                reasoning=a.get("reasoning", ""),
                condition=a.get("condition", ""),
            )
            for a in actions
        ]

    def _enrich(self, action_outcomes, at_results, deferred_ats,
                pending_events, user_input) -> dict:
        prompt = build_keeper_enrich_prompt(
            self.world, action_outcomes, at_results,
            pending_events, deferred_ats, user_input
        )
        response = call_deepseek(prompt, json_mode=True)
        return json.loads(response) if isinstance(response, str) else response

    def _check_escalation(self, raw, parsed, outcomes, at_results) -> EscalationRequest | None:
        ctx = EscalationContext(
            severities={},
            player_input=raw,
            parsed_intents=parsed,
            action_outcomes=outcomes,
            at_results=list(at_results),
            world_snapshot={
                "location": self.world.current_location,
                "flags": dict(self.world.flags),
                "triggered_events": [
                    eid for eid, t in self.world.triggered_events.items() if t
                ],
                "npc_states": dict(self.world.npc_states),
            },
            dimension_configs=self.escalation_policy.dimensions,
            recent_escalations=self.escalation_history[-5:],
            turn_number=self.turn_number,
        )
        # Build LLM eval prompt and call
        eval_prompt = self.escalation_policy._build_eval_prompt(ctx)
        eval_result = call_deepseek(eval_prompt, json_mode=True, reasoning_effort="low")
        eval_data = json.loads(eval_result) if isinstance(eval_result, str) else eval_result

        severities = eval_data.get("severities", {})
        rules_triggered = eval_data.get("rules_triggered", [])

        # Check thresholds + rules
        for dim_name, sev in severities.items():
            if self.escalation_policy._check_dimension(dim_name, sev):
                cfg = self.escalation_policy.dimensions.get(dim_name)
                if cfg and cfg.can_trigger(self.turn_number):
                    cfg.last_triggered_turn = self.turn_number
                    cfg.trigger_count += 1
                    self.escalation_history.append(dim_name)
                    return EscalationRequest(
                        trigger=dim_name, severity=sev,
                        player_input=raw,
                        world_context=ctx.world_snapshot,
                        reason=f"Severity {sev:.2f} >= threshold {cfg.threshold}"
                    )

        if rules_triggered:
            dim_name = rules_triggered[0]
            self.escalation_history.append(dim_name)
            return EscalationRequest(
                trigger=f"rule:{dim_name}", severity=1.0,
                player_input=raw, world_context=ctx.world_snapshot,
                reason=f"Rule triggered: {dim_name}"
            )

        return None

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

    def _apply_side_effects(self, side_effects: list):
        from scenario_core import apply_side_effects as _apply
        _apply(self.world, side_effects)

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
