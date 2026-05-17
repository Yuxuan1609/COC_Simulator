# Parse / Enrich Responsibility Split — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the game loop so Parse (LLM) handles entity matching + NL requirement evaluation, Judge (deterministic) handles flag checks + skill checks + ##GRADED## resolution + flag updates, and Enrich (LLM) is pure description/integration.

**Architecture:** Single-pass Parse→Judge→Enrich pipeline. Parse receives ALL entities (scene interactions, ATs, ALL events) and returns matched entity IDs in a unified list. Judge gates deterministically and sets completion flags. Enrich describes and provides emphasis — no decisions.

**Tech Stack:** Python 3.13, DeepSeek API (via `src/llm.py`)

---

### Task 1: Rewrite Parse Prompt — Unified Entity List + New Output Format

**Files:**
- Modify: `src/prompts.py:635-663` (`build_keeper_parse_prompt`)
- Modify: `src/prompts.py:91-126` (remove `_categorize_pending_events`)
- Modify: `src/prompts.py:163-192` (remove `_format_triggerable_events`, `_format_non_triggerable_events`)
- Modify: `src/prompts.py:257-277` (remove or inline `_build_triggerable_events`)

- [ ] **Step 1: Write new `build_keeper_parse_prompt`**

Replace the existing function (lines 628-663) with a version that:
1. Lists ALL scene entities (interactions + ATs) with id, name, type, trigger, requirement
2. Lists ALL events with id, name, trigger, requirement, current triggered status
3. Uses the new output format: `[{type, id, target, text}]`
4. Instructs LLM to evaluate NL requirements and exclude unmet entities
5. Instructs LLM to sort ATs first

```python
def build_keeper_parse_prompt(world, user_input: str) -> str:
    """Keeper step 1: match player input against ALL entities, evaluate NL requirements."""
    node = world._current_node()
    scene_ctx = _build_scene_context(world)
    state = _build_world_state(world)
    context = world.memory.get_context()

    # Build all-entities list for the current scene
    entities_lines = []
    if node:
        for at in node.auto_triggers:
            attrs = []
            if at.requirement:
                attrs.append(f"需要：{at.requirement}")
            entities_lines.append(
                f"  [AT] id={at.id} name=\"{at.name}\" type={at.type} "
                f"trigger=\"{at.trigger}\" {' '.join(attrs)}"
            )
        for inter in node.interactions:
            done = world.completed_interactions.get(world.current_location, set())
            status = "（已完成）" if inter.name in done else ""
            attrs = []
            if inter.requirement:
                attrs.append(f"需要：{inter.requirement}")
            entities_lines.append(
                f"  [INTER] id={inter.id} name=\"{inter.name}\" type={inter.type} "
                f"trigger=\"{inter.trigger}\" {status} {' '.join(attrs)}"
            )

    # Build all-events list
    events_lines = []
    for ev in world.graph.events.values():
        triggered = world.is_event_triggered(ev.id)
        status = "（已触发）" if triggered else ""
        attrs = []
        if ev.requirement:
            met = world._are_requirements_met(ev)
            attrs.append(f"硬性条件：{'满足' if met else '未满足'}")
        events_lines.append(
            f"  [EVENT] id={ev.id} name=\"{ev.name}\" "
            f"trigger=\"{ev.trigger}\" {status} {' '.join(attrs)}"
        )

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

{scene_ctx}

【所有可触发事件】
{chr(10).join(events_lines) if events_lines else '（无）'}

【玩家输入】
{user_input}

请同时做两件事：
1. 判断玩家意图匹配了哪些实体（交互/自动触发/事件）。检查每个匹配实体的非结构化前置条件（自然语言描述的），不满足的排除。
2. 对于不匹配任何实体的输入，归类为 move/search/other。

返回 JSON：
{{
  "actions": [
    {{"type": "auto_trigger", "id": "AT1"}},
    {{"type": "interaction", "id": "I3"}},
    {{"type": "event", "id": "E22"}},
    {{"type": "move", "target": "7号车厢"}},
    {{"type": "search"}},
    {{"type": "other", "text": "唱了一首歌"}}
  ]
}}

规则：
- auto_trigger 必须排在列表最前面
- id 必须从上述实体列表中精确复制
- move：target 填可移动方向中列出的目标
- other：text 用自然语言简述玩家意图
- 排除已完成的交互和已触发的事件
- 如果实体的非结构化前置条件不满足，不要放入列表
- 直接输出 JSON，不要额外文字
"""
    _show_prompt("Keeper Parse", prompt)
    return prompt
```

- [ ] **Step 2: Remove `_categorize_pending_events` and related formatters**

Delete the following functions from `src/prompts.py`:
- `_categorize_pending_events` (lines 91-126)
- `_format_triggerable_events` (lines 163-174)
- `_format_non_triggerable_events` (lines 178-192)
- `_build_triggerable_events` (lines 257-277)

- [ ] **Step 3: Run test harness to verify parse prompt compiles**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 -c "
import sys
sys.path.insert(0, 'src')
from game_loop import init_game
from prompts import build_keeper_parse_prompt
from pathlib import Path
base = Path('data/modules/常暗之厢')
game = init_game(
    l2_path=str(base/'l2_keeper.json'), l1_path=str(base/'l1_player.json'),
    l3_path=str(base/'l3_designer.json'),
    escalation_config_path=str(base/'escalation_config.json'), start_node='6号车厢',
)
p = build_keeper_parse_prompt(game['keeper'].world, '环顾四周')
print(f'Prompt length: {len(p)} chars')
print('Has events:', 'EVENT' in p)
print('Has AT:', '[AT]' in p)
print('Has INTER:', '[INTER]' in p)
"
```

Expected: prompt > 2000 chars, all entity types present.

- [ ] **Step 4: Commit**

```bash
git add src/prompts.py
git commit -m "feat: rewrite parse prompt with unified entity list + all events"
```

---

### Task 2: Rewrite Enrich Prompt — Pure Description, No Trigger Evaluation

**Files:**
- Modify: `src/prompts.py:666-727` (`build_keeper_enrich_prompt`)

- [ ] **Step 1: Rewrite `build_keeper_enrich_prompt`**

Replace the function with one that receives already-gated entities and only describes/enriches:

```python
def build_keeper_enrich_prompt(world, judged_entities, user_input) -> str:
    """Keeper step 3: describe and enrich entity results. No trigger evaluation."""
    state = _build_world_state(world)

    entities_text = ""
    for e in judged_entities:
        entities_text += (
            f"  [{e['entity_type']}] id={e['id']} name=\"{e['name']}\" "
            f"result=\"{e['result']}\" success={e['success']}"
        )
        if e.get('skill_tier'):
            entities_text += f" skill_tier={e['skill_tier']}"
        entities_text += "\n"

    prompt = f"""【世界状态】
{state}

【当前场景】{world.current_location}
{world.get_current_description()}

【玩家输入】{user_input}

【本轮已触发实体】
{entities_text or '（无）'}

请为以上已触发实体做叙事整合：
1. 为 auto_trigger 实体生成简短描述（它们是无条件触发的环境变化）
2. 为 interaction/event 实体的结果文本润色，增加氛围和细节
3. 提供 emphasis_hint：本轮叙事的强调方向

返回 JSON：
{{
  "at_descriptions": {{"AT1": "环境变化描述"}},
  "enriched_results": {{"I3": "润色后的结果"}},
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt)
    return prompt
```

- [ ] **Step 2: Verify enrich prompt compiles**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 -c "
import sys
sys.path.insert(0, 'src')
from prompts import build_keeper_enrich_prompt
# Stub world
from unittest.mock import MagicMock
w = MagicMock()
w.current_location = 'test'
w.get_current_description.return_value = 'desc'
w.triggered_events = {}
w.flags = {}
p = build_keeper_enrich_prompt(w, [{'entity_type':'interaction','id':'I1','name':'test','result':'ok','success':True}], 'input')
print(f'Prompt: {len(p)} chars')
print(p[:500])
"
```

Expected: no errors, prompt contains entity info and no trigger-evaluation instructions.

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "feat: rewrite enrich prompt for pure description/integration"
```

---

### Task 3: Update Judge — ##GRADED## Resolution + Flag Setting

**Files:**
- Modify: `src/game/judge.py:86-144` (`_execute_entity`)
- Modify: `src/game/judge.py:43-85` (simplify `check_auto_triggers`, remove `filter_pending_events`, remove `get_deferred_auto_triggers`)

- [ ] **Step 1: Add `_set_completion_flag` helper and update `_execute_entity` to resolve ##GRADED##**

Add a new method and modify `_execute_entity` to call `resolve_graded_result` after skill check and set flags after execution:

```python
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
                # Check margin of success for tier
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
```

- [ ] **Step 2: Remove `filter_pending_events` and `get_deferred_auto_triggers`**

Delete these two methods from `Judge` class (lines 43-52 and 73-86).

Update `check_auto_triggers`:

Remove the method since Parse now handles AT matching. Keep a simplified version for the test harness if needed, or inline the logic.

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 -m pytest tests/ -v --ignore=tests/test_module_designer.py -x 2>&1 | tail -30
```

Expected: same pass count as before (63 passed), no new failures.

- [ ] **Step 5: Commit**

```bash
git add src/game/judge.py
git commit -m "feat: add ##GRADED## resolution and flag setting to Judge"
```

---

### Task 4: Update Keeper `process_turn` — New Parse→Judge→Enrich Flow

**Files:**
- Modify: `src/game/agents/keeper.py:55-165` (`process_turn`)
- Modify: `src/game/agents/keeper.py:174-181` (`_enrich` signature)

- [ ] **Step 1: Rewrite `process_turn`**

Replace the dispatcher with the new single-pass flow:

```python
def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
    """Execute full turn: parse → judge → enrich → curate."""
    if _depth >= self.MAX_ESCALATION_DEPTH:
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
```

- [ ] **Step 2: Update `_parse` to return new format**

```python
def _parse(self, raw: str) -> list[dict]:
    prompt = build_keeper_parse_prompt(self.world, raw)
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
    data = json.loads(response) if isinstance(response, str) else response
    actions = data.get("actions", [])
    if not actions:
        return [{"type": "other", "text": raw}]
    return actions
```

- [ ] **Step 3: Update `_enrich` signature**

```python
def _enrich(self, judged_entities, user_input) -> dict:
    prompt = build_keeper_enrich_prompt(self.world, judged_entities, user_input)
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
    return json.loads(response) if isinstance(response, str) else response
```

- [ ] **Step 4: Add `_find_entity_by_id` helper**

```python
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
```

- [ ] **Step 5: Verify compilation**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 -c "import sys; sys.path.insert(0,'src'); from game.agents.keeper import Keeper; print('OK')"
```

- [ ] **Step 6: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: refactor process_turn for parse→judge→enrich single pass"
```

---

### Task 5: Update Test Harness

**Files:**
- Modify: `tests/game_loop_harness.py:75-254` (`run_turn_with_log`)

- [ ] **Step 1: Update `run_turn_with_log` to match new flow**

Replace the manual parse/judge/enrich steps with the keeper's `process_turn` call, but keep per-step logging by intercepting the stages. Since the test harness needs per-step logs, we keep the explicit logging while using the new parse format.

```python
def run_turn_with_log(game, user_input: str, case_dir: str, turn_num: int) -> dict:
    """Run one turn, capturing all intermediates to case_dir/turn_NN/."""
    turn_dir = os.path.join(case_dir, f"turn_{turn_num:02d}")
    os.makedirs(turn_dir, exist_ok=True)

    keeper = game["keeper"]
    narrator = game["narrator"]
    world = keeper.world

    from prompts import (
        build_keeper_parse_prompt, build_keeper_enrich_prompt,
        build_narrator_prompt, parse_narrative_output,
    )
    from game.messages import ActionIntent, ActionOutcome
    from scenario_core import (
        parse_markup_all, apply_side_effects as apply_se, has_ending,
    )
    from llm import call_deepseek

    raw = user_input

    # ── Pre-parse: /trigger debug command ──
    direct_trigger_event = None
    if raw.strip().startswith("/trigger "):
        eid = raw.strip().split()[1] if len(raw.strip().split()) > 1 else ""
        ev = world.graph.events.get(eid)
        if ev:
            world.triggered_events[ev.id] = True
            direct_trigger_event = ev
            raw = f"（KP命令：手动触发事件 {eid}）"

    # ── Step 1: Parse (new unified format) ──
    parse_prompt = build_keeper_parse_prompt(world, raw)
    parse_response = call_deepseek(parse_prompt, json_mode=True, model="deepseek-v4-flash")
    parse_data = json.loads(parse_response) if isinstance(parse_response, str) else parse_response
    parse_actions = parse_data.get("actions", [])
    if not parse_actions:
        parse_actions = [{"type": "other", "text": raw}]

    with open(os.path.join(turn_dir, "01_parse_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(parse_prompt)
    with open(os.path.join(turn_dir, "01_parse_response.json"), "w", encoding="utf-8") as f:
        json.dump(parse_data, f, ensure_ascii=False, indent=2)

    # ── Step 2: Judge (deterministic) ──
    from game.judge import Judge
    judge = Judge(world)
    all_outcomes = []
    judged_entities = []
    for entry in parse_actions:
        entry_type = entry.get("type", "")
        if entry_type in ("auto_trigger", "interaction", "event"):
            eid = entry.get("id", "")
            entity = keeper._find_entity_by_id(eid)
            if not entity:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=False,
                    message=f"未找到实体「{eid}」"))
                continue
            intent = ActionIntent(
                action=entry_type if entry_type != "auto_trigger" else "other",
                target=entity.name if entry_type == "interaction" else "",
            )
            outcome = judge._execute_entity(entity, intent=intent)
            apply_se(world, outcome.side_effects)
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
            result = world.move(entry.get("target", ""))
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="move", target=entry.get("target", "")),
                success=result.success, message=result.message,
                side_effects=result.side_effects,
            ))
            apply_se(world, result.side_effects)
        elif entry_type == "search":
            interactions = world.get_available_interactions()
            done = world.completed_interactions.get(world.current_location, set())
            available = [i for i in interactions if i.name not in done]
            if available:
                lines = ["（环顾四周，注意到可以做的事：）"]
                for inter in available:
                    lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
                msg = "\n".join(lines)
            else:
                msg = "（仔细查看四周，没有特别的发现）"
            all_outcomes.append(ActionOutcome(intent=ActionIntent(action="search"), success=True, message=msg))
        else:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{entry.get('text', '没有特别的事情发生')}）"))

    # Inject direct trigger event if /trigger was used
    if direct_trigger_event:
        se = []
        for se_text in direct_trigger_event.side_effects:
            se.extend(parse_markup_all(se_text))
        apply_se(world, se)
        all_outcomes.append(ActionOutcome(
            intent=ActionIntent(action="other"), success=True,
            message=direct_trigger_event.result,
            entity_id=direct_trigger_event.id, entity_type="event",
            side_effects=se,
        ))
        judged_entities.append({
            "entity_type": "event", "id": direct_trigger_event.id,
            "name": direct_trigger_event.name,
            "result": direct_trigger_event.result, "success": True,
        })

    with open(os.path.join(turn_dir, "02_judge.json"), "w", encoding="utf-8") as f:
        json.dump({
            "action_outcomes": [{"entity_id": o.entity_id, "entity_type": o.entity_type,
                                  "success": o.success, "message": o.message,
                                  "side_effects": str(o.side_effects)} for o in all_outcomes],
        }, f, ensure_ascii=False, indent=2)

    # ── Step 3: Enrich ──
    emphasis = ""
    if judged_entities:
        enrich_prompt = build_keeper_enrich_prompt(world, judged_entities, raw)
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash")
        enrichment = json.loads(enrich_response) if isinstance(enrich_response, str) else enrich_response

        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(enrich_prompt)
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)

        emphasis = enrichment.get("emphasis_hint", "")
        at_descs = enrichment.get("at_descriptions", {})
        enriched = enrichment.get("enriched_results", {})
        for o in all_outcomes:
            eid = o.entity_id
            if o.entity_type == "auto_trigger" and eid in at_descs:
                o.message = at_descs[eid]
            elif eid in enriched:
                o.message = enriched[eid]
    else:
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write("(no judged entities — enrich skipped)\n")
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump({"skipped": True}, f)

    # ── Ending detection ──
    ending_name = None; ending_narrative = None
    for o in all_outcomes:
        en, ed = has_ending(o.message)
        if en:
            ending_name = en; ending_narrative = ed; break
    if not ending_name and direct_trigger_event:
        en, ed = has_ending(direct_trigger_event.result)
        if en:
            ending_name = en; ending_narrative = ed
    with open(os.path.join(turn_dir, "05_ending.json"), "w", encoding="utf-8") as f:
        json.dump({"ending_triggered": ending_name is not None,
                    "ending_name": ending_name, "ending_narrative": ending_narrative}, f, ensure_ascii=False, indent=2)

    # ── Step 4: Narrate ──
    from game.curator import Curator
    curator = Curator(world)
    ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
    brief = curator.assemble(all_outcomes, ambient, emphasis)

    l1_scene = narrator.l1_data.get(world.current_location) if narrator.l1_data else None
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene)
    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=False, model="deepseek-v4-flash")
    narrative_brief, narrative = parse_narrative_output(narrative_response)
    with open(os.path.join(turn_dir, "04_narrative.txt"), "w", encoding="utf-8") as f:
        f.write(f"=== PLAYER INPUT ===\n{raw}\n\n=== BRIEF ===\n{narrative_brief}\n\n=== NARRATIVE ===\n{narrative}\n")

    # ── Memory ──
    first_entry = parse_actions[0] if parse_actions else {"type": "other"}
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_entry.get("type", "other"), first_entry.get("target", ""),
        brief_text, location=world.current_location,
        success=any(o.success for o in all_outcomes))
    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))

    return {"brief": narrative_brief, "narrative": narrative,
            "ending_name": ending_name, "ending_narrative": ending_narrative}
```

- [ ] **Step 2: Run test harness to verify**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 tests/game_loop_harness.py 2>&1 | head -80
```

Expected: all 15 cases run, no AttributeErrors, case_15 shows ENDING.

- [ ] **Step 3: Commit**

```bash
git add tests/game_loop_harness.py
git commit -m "feat: update test harness for parse→judge→enrich single pass"
```

---

### Task 6: Remove Dead Code + Cleanup

**Files:**
- Modify: `src/prompts.py` (remove `build_action_prompt`, `build_event_prompt`, `_build_scene_context_event`, `_build_triggerable_events` if unused)
- Modify: `src/game/judge.py` (remove `execute_interaction`, `check_auto_triggers` if no longer called by keeper)
- Modify: `src/scenario_core.py` (remove `GameEvent` class if no longer referenced)

- [ ] **Step 1: Find dead references**

```bash
cd C:/Users/micha/PyCharmMiscProject && grep -rn "build_action_prompt\|build_event_prompt\|_build_scene_context_event\|_build_triggerable_events\|GameEvent\|execute_interaction\|check_auto_triggers" src/ tests/ --include="*.py" | grep -v __pycache__ | grep -v ".pyc"
```

- [ ] **Step 2: Remove truly dead code**

Delete any functions/classes only referenced by the old flow. Keep anything still used.

- [ ] **Step 3: Run full test suite**

```bash
cd C:/Users/micha/PyCharmMiscProject && python3 -m pytest tests/ -v --ignore=tests/test_module_designer.py 2>&1 | tail -30
```

Expected: at least 63 passed, no regressions.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove dead code from old parse/enrich flow"
```
