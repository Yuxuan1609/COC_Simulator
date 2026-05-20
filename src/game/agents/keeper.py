"""Keeper agent — orchestrates the turn: parse → judge → enrich → intent → curate."""
from __future__ import annotations
from typing import Any
import json
from concurrent.futures import ThreadPoolExecutor

from scenario_core import ScenarioWorld, Entity, parse_markup_all
from ..messages import (
    ActionIntent, ActionOutcome, NarratorBrief,
    AuthorRequest, StructuralEdit, ModulePatch, TurnInput,
    CombatEntryCheck,
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
        dependency_graph: dict | None = None,
        phase1: dict | None = None,
        npc_profiles: dict[str, Any] | None = None,
    ):
        self.world = world
        # dependency_graph is now owned by world; keep reference here for backward compat
        self.dependency_graph = dependency_graph or {}
        self.phase1 = phase1 or {}
        self.npc_profiles = npc_profiles or {}

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
                        "skill_tier": outcome.skill_tier,
                    })
            elif entry_type == "move":
                # TODO: Move restriction check — from_here edges may carry requirement
                # conditions (e.g. "6号车厢未被完全吞噬"). Currently only checks if
                # target is in possible_exits. Future: evaluate edge.requirement via
                # the same parse_hard_requirement + edge gating pipeline.
                target = entry.get("target", "")
                # --- future restriction check point ---
                result = self.world.move(target)
                # --- future restriction check point ---
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="move", target=target),
                    success=result.success, message=result.message,
                    side_effects=result.side_effects,
                ))
                self._apply_side_effects(result.side_effects)
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
                        enh = evaluate_trait_enhancement(
                            inv_desc=inv_desc,                             skill_name="侦查", skill_detail=skill_msg,
                            current_tier=tier, entity_name="搜索",
                            search_context=True,
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
                    else:
                        msg = "（你环顾四周，但昏暗的光线让你无法看清任何有用的东西）"
                else:
                    msg = "（仔细查看四周，没有特别的发现）"
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="search"), success=True, message=msg,
                    entity_id="SEARCH", entity_type="search",
                    skill_tier=tier if self.world.player else "",
                    skill_detail=skill_detail if self.world.player else ""))
            else:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=True,
                    message=f"（{entry.get('text', '没有特别的事情发生')}）"))

        # Step 2.5: Combat entry detection — deterministic gate + LLM (parallel with enrich)
        combat_future = None
        combat_executor = None
        enemy_ctx = None
        if self.world and self.world.enemy_manager and not self.world.enemy_manager._combat_active:
            enemy_ctx = self.world.enemy_manager.get_combat_context(
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
            # Apply enriched results to outcomes (unified results field)
            results = enrichment.get("results", {})
            for o in all_outcomes:
                eid = o.entity_id
                if eid in results:
                    o.message = results[eid]

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

        # Step 5: Curate
        ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
        brief = self.curator.assemble(all_outcomes, ambient, emphasis)

        # Step 6: Memory
        # TODO(optimize): Memory compression currently uses LLM summarization via
        # call_deepseek when the context buffer exceeds threshold. This is a blocking
        # LLM call during turn processing. Planned optimizations:
        #   - Async/background: fire compression in a separate thread, use stale
        #     summary until ready
        #   - Rule-based truncation: drop oldest entries before calling LLM
        #   - Token-count trigger: use actual token count instead of record count
        # See readme.md §待优化 for details.
        first_entry = parse_result[0] if parse_result else {"type": "other"}
        brief_text = "\n".join(o.message for o in all_outcomes)
        self.world.memory.add_record(
            raw, first_entry.get("type", "other"), first_entry.get("target", ""),
            brief_text, location=self.world.current_location,
            success=any(o.success for o in all_outcomes)
        )
        if self.world.memory.should_compress():
            self.world.memory.compress(
                lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash",
                                        system="你是一个擅长总结和提炼信息的助手。请将游戏历史压缩为简洁摘要，"
                                               "保留关键事件、重要细节和当前状态，去除冗余对话。"))

        return {"brief": brief,
                "ending_name": ending_name, "ending_narrative": ending_narrative,
                "combat_entry": combat_entry}

    # ── Internal ──

    def _parse(self, raw: str) -> list[dict]:
        prompt = build_keeper_parse_prompt(self.world, raw)
        try:
            response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
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
        """Lightweight snapshot for IntentDetector."""
        return {
            "location": self.world.current_location,
            "npc_states": dict(self.world.npc_states),
        }

    def _build_scene_context_for_author(self) -> dict:
        """Build scene_context for AuthorRequest."""
        node = self.world._current_node()
        return {
            "location": self.world.current_location,
            "description": node.description if node else "",
            "available_scenes": list(self.world.graph.nodes.keys()),
            "npc_states": dict(self.world.npc_states),
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
