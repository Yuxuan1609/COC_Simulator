# Triggerable / Non-Triggerable Separation in Prompts

## Goal

Refactor `prompts.py` so that `build_action_prompt` and `build_event_prompt` clearly separate triggerable items (requirements met) from non-triggerable items (requirements unmet), with unmet conditions explicitly listed. Toggleable via a constant to support testing all three display options.

## Motivation

Currently both prompts lump triggerable and non-triggerable items together, distinguished only by small inline hints (`[需要前置]`, `[条件未满足]`). The LLM can easily miss these distinctions. Separating them into explicit sections with clear unmet-condition descriptions improves prompt clarity and makes it easy to test whether including/excluding non-triggerable items changes LLM behavior.

## Design

### New helper functions (deterministic, no LLM)

**`_categorize_interactions(world)`**

Split available (not yet completed) interactions at current scene into triggerable and non-triggerable. Uses existing `world._are_requirements_met()`.

Returns:
```python
{
    "triggerable": [
        {"name": str, "type": str, "trigger": str, "result": str},
        ...
    ],
    "non_triggerable": [
        {"name": str, "type": str, "trigger": str, "result": str, "unmet_reasons": [str]},
        ...
    ]
}
```

**`_categorize_pending_events(world)`**

Same for pending (not yet triggered) events. Uses existing `world.requirement_resolver.check()` / `get_unmet()`.

Returns:
```python
{
    "triggerable": [
        {"event_id": str, "name": str, "trigger": str, "impact": str},
        ...
    ],
    "non_triggerable": [
        {"event_id": str, "name": str, "trigger": str, "impact": str, "unmet_reasons": [str]},
        ...
    ]
}
```

### Formatting helpers

Four pure formatting functions that take the categorized lists and produce prompt text:

- `_format_triggerable_interactions(interactions)` — section: `【可执行动作】`
- `_format_non_triggerable_interactions(interactions)` — section: `【暂不可执行动作】（需满足前置条件）` with `缺少前置：` lines
- `_format_triggerable_events(events)` — section: `【可触发事件】`
- `_format_non_triggerable_events(events)` — section: `【暂不可触发事件】（需满足前置条件）` with `缺少前置：` lines

### Refactored build functions

`_build_scene_context()` and `_build_scene_context_event()` are refactored to call categorize → format → compose.

### Control mechanism

```python
# Module-level default
_SHOW_NON_TRIGGERABLE = True

def build_action_prompt(world, user_input, show_non_triggerable=None): ...
def build_event_prompt(world, user_input, show_non_triggerable=None): ...
```

| `show_non_triggerable` | Behavior |
|---|---|
| `None` (default) | Uses `_SHOW_NON_TRIGGERABLE` constant |
| `True` | Both triggerable + non-triggerable sections in prompt |
| `False` | Only triggerable section in prompt |

When `False`, non-triggerable data is still computed and accessible via the categorize helpers for use in debug commands (`/info`, `/events`).

### Implementation note

`requirement_resolver.check()` returns strings like `"行动失败！！！需要先完成「4号车厢」的「急救乘务员」"`. The categorization helpers strip the `"行动失败！！！"` prefix before storing in `unmet_reasons`, since it's meant for the game engine's action-failure message, not prompt display.

### Files changed

- `src/prompts.py` — all changes contained here

### No changes to

- `scenario_core.py` — all required checks already exist (`_are_requirements_met`, `requirement_resolver.check`, `get_unmet`)
- `notebooks/` — callers pass through without changes (the new param is optional)
- Data files

### Testing the three options

- **Option 1 (both sections)**: `_SHOW_NON_TRIGGERABLE = True` (default)
- **Option 2 (only triggerable)**: `_SHOW_NON_TRIGGERABLE = False`
- **Option 3 (separate variable)**: Call `_categorize_pending_events(world)` or `_categorize_interactions(world)` directly from debug commands, independent of prompt construction
