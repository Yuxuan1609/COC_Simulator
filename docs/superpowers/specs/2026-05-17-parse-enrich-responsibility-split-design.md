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
| **Parse** | LLM | Match player input against ALL scene entities (interactions + ATs) + ALL events. Evaluate non-structured (natural language) requirements. Return only entities whose NL conditions are met. ATs sorted first. |
| **Judge** | Deterministic | Structured gate: world flag checks + dependency graph consultation + skill checks + `##GRADED##` resolution. Update world flags on entity completion. |
| **Enrich** | LLM | Pure integration + description. Describe AT results, enrich interaction/event result text, provide `emphasis_hint`. No requirement checking. No flag updates. |
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
Parse (LLM): evaluate input against ALL entities + ALL events
  → NL requirement evaluation — exclude unmet entities
  → Return matched entity IDs + generic actions (ATs first)

For each entry in parse_result.actions:

  ┌─ ANY entity (AT / interaction / event) ──┐
  │ → Judge: check structured requirement    │
  │   (world flags are canonical;             │
  │    dependency graph consulted for         │
  │    guidance message on failure)           │
  │ → Judge: skill check + ##GRADED## resolve │
  │ → Execute if gates pass                  │
  │ → Apply side effects                     │
  │ → Judge: set completion flag for entity  │
  │ → Mark for enrich: describe/enrich result │
  └──────────────────────────────────────────┘

  ┌─ move / search / other ──────────────────┐
  │ → Judge: deterministic handling          │
  │ → Enrich: no-op                          │
  └──────────────────────────────────────────┘
```

All entity types (AT, interaction, event) go through the same gate. NL requirements handled by Parse (LLM), structured requirements and flag updates by Judge (deterministic).

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

### Parse Prompt Changes

Parse prompt now includes:
- All scene entities (interactions + ATs) with their non-structured requirement strings
- All events with their trigger descriptions and requirement strings
- Current world state so the LLM can evaluate NL conditions

Parse evaluates non-structured (natural language) requirements itself — entities whose NL conditions are not met are excluded from the returned list. Only entities that pass NL evaluation reach Judge.

### Judge Responsibilities

Judge handles all deterministic and structured work:
1. World flag checks (canonical requirement check)
2. Dependency graph consultation for error messages on flag failure
3. Skill checks (COC 7th D100)
4. `##GRADED##` resolution after skill check
5. **Update world flags** on entity completion (e.g., `flag:I1_done=true`)

Flags are set immediately after entity execution, not deferred to Enrich.

### Enrich Prompt Changes

Old prompt asked LLM to evaluate which ATs/events should fire AND set flags. New prompt:

- **Input**: list of entities that passed Judge (id, type, name, resolved result text, skill check tier)
- **LLM tasks**:
  1. Describe triggered AT results in narrative form
  2. Enrich interaction/event result text (tone, atmosphere, detail)
  3. Provide `emphasis_hint` for narrator

No requirement checking. No flag updates. No trigger evaluation — Parse already decided which entities fire, Judge already gated and flagged them. Enrich is pure narrative integration.

### Parse Prompt Expansion

Current parse prompt shows only current-scene context. New prompt adds:
- All events (with id, name, trigger description, current status)
- Scoped to flag-satisfied and all events, so LLM can match player intent

### Removed / Changed

| Item | Old | New |
|------|-----|-----|
| `judge.filter_pending_events()` | Scans graph for deterministically-qualified events | Removed — Parse feeds entities |
| `judge.get_deferred_auto_triggers()` | Returns ATs with NL requirements | Removed — NL requirements evaluated in Parse |
| `_categorize_pending_events` | Separates events by requirement status | Removed |
| Enrich trigger evaluation | LLM decides which events fire | Removed — Parse decided |
| Enrich world flag updates | LLM sets `new_flags` | Moved to Judge — flags set on entity completion |
| `##GRADED##` resolution | LLM in Enrich (unused) | Deterministic in Judge |
| NL requirement checking | Deferred to Enrich LLM | Moved to Parse LLM |
| Dependency graph check | Separate step | Absorbed into requirement check as guidance |

### Files Affected

| File | Change |
|------|--------|
| `src/prompts.py` | `build_keeper_parse_prompt` expanded with all events; `build_keeper_enrich_prompt` rewritten for describe-only; `_categorize_pending_events` removed |
| `src/game/judge.py` | `resolve_graded_result` called after skill check; `filter_pending_events` removed; `get_deferred_auto_triggers` removed; dependency graph consulted for error messages |
| `src/game/agents/keeper.py` | `process_turn` simplified: parse feeds entities, judge gates, enrich describes |
| `tests/game_loop_harness.py` | `run_turn_with_log` updated to match new flow |
