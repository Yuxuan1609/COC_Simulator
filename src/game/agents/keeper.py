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

    MAX_ESCALATION_DEPTH = 3

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

    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse → judge → enrich → curate."""
        if _depth >= self.MAX_ESCALATION_DEPTH:
            # Guard against infinite recursion — re-execute deterministically
            return self._process_deterministic_only(turn_input)
        self.turn_number += 1
        raw = turn_input.raw_text

        # Step 1: Parse (LLM) — entity matching + NL requirement evaluation
        parse_result = self._parse(raw)

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
                outcome = self.judge._execute_entity(entity, intent=intent)
                self._apply_side_effects(outcome.side_effects)
                all_outcomes.append(outcome)
                if outcome.success:
                    judged_entities.append({
                        "entity_type": entity.entity_type,
                        "id": entity.id,
                        "name": entity.name,
                        "result": outcome.message,
                        "success": True,
                    })
            elif entry_type == "move":
                result = self.world.move(entry.get("target", ""))
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="move", target=entry.get("target", "")),
                    success=result.success, message=result.message,
                    side_effects=result.side_effects,
                ))
                self._apply_side_effects(result.side_effects)
            elif entry_type == "search":
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
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="search"), success=True, message=msg))
            else:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=True,
                    message=f"（{entry.get('text', '没有特别的事情发生')}）"))

        # Step 3: Enrich (LLM) — describe and integrate
        emphasis = ""
        if judged_entities:
            enrichment = self._enrich(judged_entities, raw)
            emphasis = enrichment.get("emphasis_hint", "")
            # Apply enriched AT descriptions to outcomes
            at_descs = enrichment.get("at_descriptions", {})
            enriched = enrichment.get("enriched_results", {})
            for o in all_outcomes:
                eid = o.entity_id
                if o.entity_type == "auto_trigger" and eid in at_descs:
                    o.message = at_descs[eid]
                elif eid in enriched:
                    o.message = enriched[eid]

        # Step 4: Escalation check
        escalation_req = self._check_escalation(raw, parse_result, all_outcomes, [])
        if escalation_req and author:
            patch = author.handle_escalation(escalation_req)
            self._integrate_patch(patch)
            return self.process_turn(turn_input, author, _depth + 1)

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

        # Step 5: Curate
        ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
        brief = self.curator.assemble(all_outcomes, ambient, emphasis)

        # Memory
        first_entry = parse_result[0] if parse_result else {"type": "other"}
        brief_text = "\n".join(o.message for o in all_outcomes)
        self.world.memory.add_record(
            raw, first_entry.get("type", "other"), first_entry.get("target", ""),
            brief_text, location=self.world.current_location,
            success=any(o.success for o in all_outcomes)
        )
        if self.world.memory.should_compress():
            self.world.memory.compress(
                lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))

        return {"brief": brief, "escalation": escalation_req,
                "ending_name": ending_name, "ending_narrative": ending_narrative}

    # ── Internal ──

    def _parse(self, raw: str) -> list[dict]:
        prompt = build_keeper_parse_prompt(self.world, raw)
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
        data = json.loads(response) if isinstance(response, str) else response
        actions = data.get("actions", [])
        if not actions:
            return [{"type": "other", "text": raw}]
        return actions

    def _enrich(self, judged_entities, user_input) -> dict:
        prompt = build_keeper_enrich_prompt(self.world, judged_entities, user_input)
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
        return json.loads(response) if isinstance(response, str) else response

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
        return {"brief": brief, "escalation": None,
                "ending_name": None, "ending_narrative": None}

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
        eval_result = call_deepseek(eval_prompt, json_mode=True, reasoning_effort="low", model="deepseek-v4-flash")
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
