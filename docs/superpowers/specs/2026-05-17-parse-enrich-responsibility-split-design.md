# Parse / Enrich Responsibility Split

**Date**: 2026-05-17
**Status**: Design approved, pending plan
**Context**: Multi-agent game loop (3-Agent: Keeper/Narrator/Author)

---

## Problem

The current parse/enrich split blurs responsibilities:

1. Parse only sees current-scene interactions and exits — events and ATs with natural-language conditions are deferred to enrich
2. Enrich does double duty: evaluates "which ATs/events should fire" AND enriches `##GRADED##` results
3. `judge.filter_pending_events()` scans all events deterministically, missing entities whose hard conditions are met but need soft (NL) trigger evaluation
4. `##GRADED##` resolution is never applied — Enrich LLM returns `enriched_results` dict that goes unused
5. No clear boundary between "deterministic" and "LLM-evaluated" trigger conditions

## Design

### Step Responsibilities

| Step | Who | What |
|------|-----|------|
| **Parse** | LLM | Match player input against ALL scene entities (interactions + ATs) + ALL events. Return matched entity IDs + generic actions (move/search/other). ATs sorted first in the output list. |
| **Judge** | Deterministic | Hard gate: world flag checks + dependency graph consultation + skill checks + `##GRADED##` resolution. |
| **Enrich** | LLM | For entities that passed Judge: describe AT results, enrich interaction/event result text, set new world flags, provide `emphasis_hint`. No trigger-condition evaluation. |
| **Curate** | Deterministic | Assemble NarratorBrief. |
| **Narrate** | LLM | Generate immersive narrative. |

### Parse Output Format

Single ordered list. ATs first. Entity references use `id`, generic actions use `text`:

```json
{
  "actions": [
    {"type": "auto_trigger", "id": "AT1"},
    {"type": "interaction", "id": "I3"},
    {"type": "event", "id": "E22"},
    {"type": "move", "target": "7号车厢"},
    {"type": "search"},
    {"type": "other", "text": "唱了一首歌"}
  ]
}
```

Rules:
- `id` must match entity IDs from the prompt exactly
- Multiple entities can fire in one turn
- `other` carries raw text for unmatched input

### Execution Order (per turn)

Keeper processes parse results sequentially:

```
For each entry in parse_result.actions (ATs already first):

  ┌─ ANY entity (AT / interaction / event) ──┐
  │ → Judge: check requirement string        │
  │   (world flags are canonical;             │
  │    dependency graph consulted for         │
  │    guidance message on failure)           │
  │ → Judge: skill check + ##GRADED## resolve │
  │ → Execute if all gates pass              │
  │ → Apply side effects                     │
  │ → Mark for enrich: describe/enrich result │
  └──────────────────────────────────────────┘

  ┌─ move / search / other ──────────────────┐
  │ → Judge: deterministic handling          │
  │ → Enrich: no-op                          │
  └──────────────────────────────────────────┘
```

All entity types (AT, interaction, event) go through the same Judge gate: requirement check → skill check → execute.

### World Flags & Dependency Graph

Two representations of the same thing:

| Representation | Purpose | Example |
|---------------|---------|---------|
| World flag `flag:I1_done` | Deterministic check at Judge | `flags.get("I1_done")` |
| Dependency graph edge `I3→I1` | Guidance message on failure | "需要先完成「阅读便签正面」" |

When entity `I1` completes, `flag:I1_done` is set. When entity `I3` requires `I1`, the flag is checked first. If missing, the dependency graph edge provides the human-readable name for the error message. No separate step — the graph is a messaging layer on top of flag checks.

### `##GRADED##` Resolution

Happens deterministically in Judge after skill check:

1. Entity has `##GRADED##` in its result → skill check runs
2. Judge determines tier: failure / regular / hard / extreme
3. `resolve_graded_result(entity, tier)` picks the tier-appropriate text
4. Clean result text flows into Enrich (for polish) and Curate (for assembly)

### Enrich Prompt Changes

Old prompt asked LLM to evaluate which ATs/events should fire. New prompt:

- **Input**: list of entities that passed Judge (id, type, name, resolved result text, skill check tier)
- **LLM tasks**:
  1. Describe triggered AT results in narrative form
  2. Enrich interaction/event result text (tone, atmosphere, detail)
  3. Set new world flags where appropriate
  4. Provide `emphasis_hint` for narrator

No trigger-condition evaluation — Parse already decided which entities fire.

### Parse Prompt Expansion

Current parse prompt shows only current-scene context. New prompt adds:
- All events (with id, name, trigger description, current status)
- Scoped to flag-satisfied and all events, so LLM can match player intent

### Removed / Changed

| Item | Old | New |
|------|-----|-----|
| `judge.filter_pending_events()` | Scans graph for deterministically-qualified events | Removed — Parse feeds entities |
| `judge.get_deferred_auto_triggers()` | Returns ATs with NL requirements | Removed — all ATs go through Parse |
| `_categorize_pending_events` | Separates events by requirement status | Removed |
| Enrich trigger evaluation | LLM decides which events fire | Removed — Parse decided |
| `##GRADED##` resolution | LLM in Enrich (unused) | Deterministic in Judge |
| Dependency graph check | Separate step | Absorbed into requirement check as guidance |

### Files Affected

| File | Change |
|------|--------|
| `src/prompts.py` | `build_keeper_parse_prompt` expanded with all events; `build_keeper_enrich_prompt` rewritten for describe-only; `_categorize_pending_events` removed |
| `src/game/judge.py` | `resolve_graded_result` called after skill check; `filter_pending_events` removed; `get_deferred_auto_triggers` removed; dependency graph consulted for error messages |
| `src/game/agents/keeper.py` | `process_turn` simplified: parse feeds entities, judge gates, enrich describes |
| `tests/game_loop_harness.py` | `run_turn_with_log` updated to match new flow |
