# Triggerable / Non-Triggerable Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `prompts.py` to clearly separate triggerable and non-triggerable interactions/events in prompts, with unmet conditions explicitly listed and a toggleable constant.

**Architecture:** Deterministic categorization helpers split items based on existing `ScenarioWorld` requirement checks. Four pure formatting helpers produce prompt sections. A module-level `_SHOW_NON_TRIGGERABLE` constant (with per-call override parameter) controls whether non-triggerable sections appear in prompts.

**Tech Stack:** Pure Python — no new dependencies. All required checks exist in `scenario_core.py`.

---

## File Structure

- **Modify:** `src/prompts.py` — all changes in this single file
- **No changes:** `src/scenario_core.py`, data files, notebook

Internal decomposition within `prompts.py`:

| Function | Role |
|---|---|
| `_categorize_interactions(world)` | Split scene interactions by requirement status |
| `_categorize_pending_events(world)` | Split pending events by requirement status |
| `_format_triggerable_interactions(items)` | Prompt text for triggerable interactions |
| `_format_non_triggerable_interactions(items)` | Prompt text for non-triggerable interactions |
| `_format_triggerable_events(items)` | Prompt text for triggerable events |
| `_format_non_triggerable_events(items)` | Prompt text for non-triggerable events |
| `_build_scene_context(world)` | Refactored to use categorize+format |
| `_build_scene_context_event(world)` | Refactored to use categorize+format |
| `build_action_prompt(world, input, show_non_triggerable=None)` | Updated signature |
| `build_event_prompt(world, input, show_non_triggerable=None)` | Updated signature |

---

### Task 1: Add module constant and categorization helpers

**Files:**
- Modify: `src/prompts.py` — insert after `_show_prompt`, before `_build_scene_context`

- [ ] **Step 1: Add the toggle constant after existing imports and log config**

Insert after line 35 (`_show_prompt` function end):

```python
# ── 触发状态分离（确定性，不依赖 LLM）──

_SHOW_NON_TRIGGERABLE = True  # 设为 False 则不展示不可触发项
```

- [ ] **Step 2: Add `_categorize_interactions(world)` helper**

```python
def _categorize_interactions(world: ScenarioWorld) -> dict:
    """Split available (incomplete) interactions into triggerable / non-triggerable."""
    interactions = world.get_available_interactions()
    done = world.completed_interactions.get(world.current_location, set())
    available = [i for i in interactions if i.name not in done]

    triggerable = []
    non_triggerable = []

    for i in available:
        entry = {
            "name": i.name,
            "type": i.type,
            "trigger": i.trigger,
            "result": i.result[:120],
        }
        if world._are_requirements_met(i):
            triggerable.append(entry)
        else:
            unmet = world.requirement_resolver.get_unmet(i.requirements)
            reasons = []
            for req in unmet:
                if req.ref_type == "interaction":
                    reasons.append(f"需要先完成「{req.ref_scene}」的「{req.ref_name}」")
                elif req.ref_type == "event":
                    event = world.graph.get_event(req.ref_scene)
                    event_name = event.name if event else req.ref_scene
                    reasons.append(f"需要先触发事件「{event_name}」")
                elif req.ref_type == "flag":
                    reasons.append(f"需要世界标记「{req.ref_name}」")
            entry["unmet_reasons"] = reasons
            non_triggerable.append(entry)

    return {"triggerable": triggerable, "non_triggerable": non_triggerable}
```

- [ ] **Step 3: Add `_categorize_pending_events(world)` helper**

```python
def _categorize_pending_events(world: ScenarioWorld) -> dict:
    """Split pending (not yet triggered) events into triggerable / non-triggerable."""
    pending = [e for e in world.graph.events.values()
               if not world.is_event_triggered(e.event_id)]

    triggerable = []
    non_triggerable = []

    for ev in pending:
        entry = {
            "event_id": ev.event_id,
            "name": ev.name,
            "trigger": ev.trigger,
            "impact": ev.impact[:150],
        }
        if ev.requirements:
            met, _ = world.requirement_resolver.check(ev.requirements)
            if met:
                triggerable.append(entry)
            else:
                unmet = world.requirement_resolver.get_unmet(ev.requirements)
                reasons = []
                for req in unmet:
                    if req.ref_type == "interaction":
                        reasons.append(f"需要先完成「{req.ref_scene}」的「{req.ref_name}」")
                    elif req.ref_type == "event":
                        event = world.graph.get_event(req.ref_scene)
                        event_name = event.name if event else req.ref_scene
                        reasons.append(f"需要先触发事件「{event_name}」")
                    elif req.ref_type == "flag":
                        reasons.append(f"需要世界标记「{req.ref_name}」")
                entry["unmet_reasons"] = reasons
                non_triggerable.append(entry)
        else:
            triggerable.append(entry)

    return {"triggerable": triggerable, "non_triggerable": non_triggerable}
```

- [ ] **Step 4: Verification — import test**

Run: `cd /c/Users/micha/PyCharmMiscProject && python -c "from src.prompts import _categorize_interactions, _categorize_pending_events; print('OK')"`

Expected: `OK` (no import errors)

---

### Task 2: Add formatting helpers

**Files:**
- Modify: `src/prompts.py` — insert after Task 1 helpers, before `_build_scene_context`

- [ ] **Step 1: Add `_format_triggerable_interactions`**

```python
def _format_triggerable_interactions(interactions: list) -> str:
    """Format triggerable interactions for prompt display."""
    if not interactions:
        return ""
    lines_list = []
    for i in interactions:
        lines_list.append(
            f"  名称（请原样复制）：「{i['name']}」\n"
            f"  类型：{i['type']}\n"
            f"  触发条件：{i['trigger']}\n"
            f"  结果：{i['result']}"
        )
    text = "\n\n".join(lines_list)
    return f"【可执行动作】\n{text}"
```

- [ ] **Step 2: Add `_format_non_triggerable_interactions`**

```python
def _format_non_triggerable_interactions(interactions: list) -> str:
    """Format non-triggerable interactions with unmet reasons."""
    if not interactions:
        return ""
    lines_list = []
    for i in interactions:
        reasons = "\n".join(f"    - {r}" for r in i["unmet_reasons"])
        lines_list.append(
            f"  名称：「{i['name']}」\n"
            f"  类型：{i['type']}\n"
            f"  触发条件：{i['trigger']}\n"
            f"  缺少前置：\n{reasons}"
        )
    text = "\n\n".join(lines_list)
    return f"【暂不可执行动作】（需满足前置条件）\n{text}"
```

- [ ] **Step 3: Add `_format_triggerable_events`**

```python
def _format_triggerable_events(events: list) -> str:
    """Format triggerable events for prompt display."""
    if not events:
        return ""
    lines_list = []
    for ev in events:
        lines_list.append(
            f"  ◇ [{ev['event_id']}] {ev['name']}\n"
            f"    触发条件：{ev['trigger']}\n"
            f"    预期影响：{ev['impact']}"
        )
    text = "\n\n".join(lines_list)
    return f"【可触发事件】\n{text}"
```

- [ ] **Step 4: Add `_format_non_triggerable_events`**

```python
def _format_non_triggerable_events(events: list) -> str:
    """Format non-triggerable events with unmet reasons."""
    if not events:
        return ""
    lines_list = []
    for ev in events:
        reasons = "\n".join(f"    - {r}" for r in ev["unmet_reasons"])
        lines_list.append(
            f"  ◇ [{ev['event_id']}] {ev['name']}\n"
            f"    触发条件：{ev['trigger']}\n"
            f"    预期影响：{ev['impact']}\n"
            f"    缺少前置：\n{reasons}"
        )
    text = "\n\n".join(lines_list)
    return f"【暂不可触发事件】（需满足前置条件）\n{text}"
```

- [ ] **Step 5: Verification — import test**

Run: `cd /c/Users/micha/PyCharmMiscProject && python -c "from src.prompts import _format_triggerable_interactions, _format_non_triggerable_interactions, _format_triggerable_events, _format_non_triggerable_events; print('OK')"`

Expected: `OK`

---

### Task 3: Refactor `_build_scene_context` and `_build_scene_context_event`

**Files:**
- Modify: `src/prompts.py` — replace existing `_build_scene_context` (lines 39-72) and `_build_scene_context_event` (lines 74-81)

- [ ] **Step 1: Replace `_build_scene_context`**

```python
def _build_scene_context(world: ScenarioWorld, show_non_triggerable: bool = True) -> str:
    """从 graph 获取当前场景的稳定上下文（不含世界状态）"""
    node = world._current_node()
    if not node:
        return "未知地点"

    exits = world.get_possible_exits()
    exit_list = "\n".join([
        f"  → {e.target}：{e.method}" for e in exits
    ]) or "（无）"

    categorized = _categorize_interactions(world)

    interaction_parts = []
    triggerable_text = _format_triggerable_interactions(categorized["triggerable"])
    if triggerable_text:
        interaction_parts.append(triggerable_text)

    if show_non_triggerable:
        non_trig_text = _format_non_triggerable_interactions(categorized["non_triggerable"])
        if non_trig_text:
            interaction_parts.append(non_trig_text)

    interaction_text = "\n\n".join(interaction_parts) if interaction_parts else "（当前场景无可执行动作）"

    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}

【可移动方向】
{exit_list}

{interaction_text}"""
```

- [ ] **Step 2: Replace `_build_scene_context_event`**

```python
def _build_scene_context_event(world: ScenarioWorld) -> str:
    """从 graph 获取当前场景的稳定上下文（不含世界状态）—— 供事件判定使用"""
    node = world._current_node()
    if not node:
        return "未知地点"
    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}
"""
```

`_build_scene_context_event` stays the same — it doesn't need interaction data, only scene identity for event prompts.

- [ ] **Step 3: Update `_build_scene_context` call in `build_action_prompt` (line 128)**

Replace:
```python
    scene_ctx = _build_scene_context(world)
```
With:
```python
    scene_ctx = _build_scene_context(world, show_non_triggerable=show_non_triggerable)
```

- [ ] **Step 4: Verification**

Run: `cd /c/Users/micha/PyCharmMiscProject && python -c "from src.prompts import _build_scene_context, _build_scene_context_event; print('OK')"`

Expected: `OK`

---

### Task 4: Update `build_action_prompt` and `build_event_prompt` signatures

**Files:**
- Modify: `src/prompts.py` — update function signatures and add `show_non_triggerable` parameter

- [ ] **Step 1: Replace `build_action_prompt` signature and body**

Replace lines 126-173 with:

```python
def build_action_prompt(world: ScenarioWorld, user_input: str,
                        show_non_triggerable: bool | None = None) -> str:
    """基于当前场景 JSON 信息，让 LLM 判断玩家意图，支持多动作识别"""
    if show_non_triggerable is None:
        show_non_triggerable = _SHOW_NON_TRIGGERABLE

    scene_ctx = _build_scene_context(world, show_non_triggerable=show_non_triggerable)
    state = _build_world_state(world)
    context = world.memory.get_context()
    skills = _build_player_skills(world)

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

【玩家技能】
{skills}

{scene_ctx}

【玩家输入】
{user_input}

请判断玩家意图。玩家输入可能包含单个或多个连续意图（如"先检查桌子然后去7号车厢"），请按先后顺序拆分为多个动作。返回 JSON：
{{
  "actions": [
    {{
      "action": "move" | "interact" | "search" | "other",
      "target": "目标地点（仅 move 时填写）",
      "interaction": "动作名称（仅 interact 时填写，务必从上述「名称（请原样复制）」中精确复制）",
      "skill_checks": ["技能名"],
      "reasoning": "简要推理"
    }}
  ]
}}

规则：
- move：玩家明确想前往某方向/地点 → target 填「可移动方向」中列出的目标 注意 查看/聆听/询问/非直接前往的方式 了解另外一个场景不适用move
- interact：玩家意图匹配某个可执行动作 → interaction 务必精确复制名称
- search：玩家想探索但无法精确匹配任何动作
- other：其他动作类型（不产生实际影响）
- skill_checks：根据动作的触发条件，列出需要鉴定的技能名称（如 侦查、灵感、急救 等），
  技能必须是玩家拥有的。无需鉴定时返回空数组 []，仅对 move 和 interact 生效
- 如果玩家输入只有单一意图，actions 数组仍包含 1 个元素
- actions 按玩家输入中的先后顺序排列

直接输出 JSON，不要额外文字。
"""
    _show_prompt("Step 1/3 — 动作解析", prompt)
    return prompt
```

- [ ] **Step 2: Replace `build_event_prompt` signature and body**

Replace lines 178-231 with:

```python
def build_event_prompt(world: ScenarioWorld, user_input: str,
                       show_non_triggerable: bool | None = None) -> str:
    """基于 user_input + 全部未触发事件，让 LLM 独立判断哪些事件应在此刻触发"""
    if show_non_triggerable is None:
        show_non_triggerable = _SHOW_NON_TRIGGERABLE

    context = world.memory.get_context()
    state = _build_world_state(world)
    scene_ctx = _build_scene_context_event(world)
    categorized = _categorize_pending_events(world)

    event_parts = []
    triggerable_text = _format_triggerable_events(categorized["triggerable"])
    if triggerable_text:
        event_parts.append(triggerable_text)

    if show_non_triggerable:
        non_trig_text = _format_non_triggerable_events(categorized["non_triggerable"])
        if non_trig_text:
            event_parts.append(non_trig_text)

    event_text = "\n\n".join(event_parts) if event_parts else "（所有事件均已触发）"

    prompt = f"""【玩家历史行动】
{context or '（无）'}

{scene_ctx}
【世界状态】
{state}

【玩家输入】
{user_input}

【待检查事件（仅以下未触发事件需判断）】
{event_text}

请逐一判断上述「待检查事件」的触发条件是否被玩家当前输入所描述的行动满足。返回 JSON：
{{
  "triggered_events": ["E1"],
  "new_flags": {{"flag_name": true}},
  "reasoning": "逐事件推理"
}}

规则：
- 仅当玩家输入中描述的行动确实满足事件的触发条件时才列入
- 已触发的事件不要重复触发
- new_flags 可选，用于设置新的世界标记
- 不满足任何条件时 triggered_events 返回 []
- 严格比对触发条件，不要过度联想

直接输出 JSON，不要额外文字。
"""
    _show_prompt("Step 2/3 — 事件触发判定", prompt)
    return prompt
```

- [ ] **Step 3: Verification — full import and smoke test**

Run:
```bash
cd /c/Users/micha/PyCharmMiscProject && python -c "
from src.prompts import build_action_prompt, build_event_prompt, _SHOW_NON_TRIGGERABLE
print(f'SHOW_NON_TRIGGERABLE = {_SHOW_NON_TRIGGERABLE}')
print('All imports OK')
"
```

Expected:
```
SHOW_NON_TRIGGERABLE = True
All imports OK
```

---

### Task 5: Run the notebook to verify end-to-end

- [ ] **Step 1: Start the notebook and verify prompts render correctly**

Run the notebook up to the game loop start. Check the log file for prompt output and confirm:
- `【可执行动作】` and/or `【暂不可执行动作】` sections appear correctly
- `【可触发事件】` and/or `【暂不可触发事件】` sections appear correctly
- Non-triggerable items show `缺少前置：` with specific reasons
- Setting `_SHOW_NON_TRIGGERABLE = False` hides the non-triggerable sections

- [ ] **Step 2: Test Option 2 (hide non-triggerable)**

In the notebook, before starting the game loop:
```python
import src.prompts as prompts
prompts._SHOW_NON_TRIGGERABLE = False
```
Verify only triggerable sections appear in the logged prompts.

- [ ] **Step 3: Test Option 3 (access categorized data directly)**

```python
# Access non-triggerable data separately for debug commands
categorized = prompts._categorize_pending_events(world)
print("Non-triggerable events:", categorized["non_triggerable"])
print("Non-triggerable interactions:", prompts._categorize_interactions(world)["non_triggerable"])
```
