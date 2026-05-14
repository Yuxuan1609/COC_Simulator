# Parser System Overhaul — Changelog

**Date**: 2026-05-13
**Design Specs**: `docs/superpowers/specs/2026-05-13-parser-system-overhaul-design.md`, `docs/superpowers/specs/2026-05-13-three-layer-schema-overview.md`
**Plan**: `docs/superpowers/plans/2026-05-13-parser-system-overhaul-plan.md`

## Overview

Comprehensive parser upgrade: three-layer information model (L1 player / L2 KP / L3 designer), independent weapon/enemy library with two-tier judgment, content injection engine, game loop adaptation, and LLM-driven one-shot module parser with post-processing pipeline. 13 tasks, 34 tests, 12 commits.

---

## New Packages

### `src/library/` — Weapon/Enemy Resource Library

Independent package with zero external dependencies.

| File | Contents |
|------|----------|
| `weapons.py` | `LibraryWeapon` dataclass + `WeaponLibrary` (load/search/get) |
| `enemies.py` | `LibraryEnemy`, `EnemyAttack`, `SpecialAbility` dataclasses + `EnemyLibrary` |
| `judgment.py` | `JudgmentEngine` — T1 deterministic (D100 skill check, damage roll, SAN check) + T2 LLM context builder |
| `injector.py` | `ContentInjector` — offline pre-fill (scene-based enemy/weapon suggestions) + runtime dynamic injection (`runtime_spawn_enemy`, `runtime_grant_weapon`) |

**Data**: `data/library/core/weapons.json` (10 weapons), `data/library/core/enemies.json` (5 enemies), `data/library/extensions/` (user extension packs)

### `src/module_designer/` — Three-Layer Information Engine

| File | Contents |
|------|----------|
| `l1_player.py` | `SceneL1`, `Perceptible`, `NPCAppearance` — player-visible perception layer |
| `l2_keeper.py` | `SceneL2`, `Encounter`, `SceneWeapon`, `HiddenInfo`, `NPCProfile` — KP keeper layer |
| `l3_designer.py` | `L3Designer`, `ModuleMeta`, `WorldRule`, `LogicChain`, `Branch`, `SceneIntent`, `EndingCondition`, `ToneConstraints` — immutable designer intent layer |
| `layered_schema.py` | JSON Schema definitions for all three layers + `validate_l1/l2/l3/all()` with `SchemaReport` (errors vs warnings) |
| `layered_parser.py` | LLM one-shot parser: `parse_module()` converts source.txt → L1+L2+L3 JSON via structured prompts with template-driven format references |
| `layered_pipeline.py` | Post-processing pipeline: `run_pipeline()` chains schema validation → offline injection → cross-layer reference validation; `cross_validate_layers()` checks L1→L2, L2→library, L3→L1/L2 consistency |

All models have `to_dict()`/`from_dict()` roundtrip serialization and `load_*`/`save_*` JSON I/O functions. All substructures have optional `extra: dict` for future extensibility.

**Templates**: `data/templates/l1_template.json`, `data/templates/l2_template.json`, `data/templates/l3_template.json`

---

## Modified Files

### `src/scenario_core.py`

- **New dataclasses**: `SpawnEnemy`, `GrantItem`, `EncounterAnchor`, `NPCStateChange`
- **Extended**: `_parse_side_effect()` and `_side_effect_to_dict()` with cases for all four new types
- **New**: `ScenarioWorld.npc_states: Dict[str, str]` with `set_npc_state()` / `get_npc_state()` methods
- **Updated**: `to_dict()` and `from_dict()` include `npc_states` in serialization

### `src/prompts.py`

- **New**: `_build_l1l3_context()` — constructs L1 (atmosphere/mood/hints) + L3 (tone constraints, driving force, scene intent) context for narrative prompts
- **Updated**: `build_narrative_prompt()` — accepts optional `l1_scene` and `l3_data` parameters, injects tonal/sensory context
- **Updated**: `build_improvise_prompt()` — same L1/L3 enhancements

### `src/game_loop.py`

- **Extended**: `_apply_side_effects()` — handles `SpawnEnemy` (log to runtime encounter table), `GrantItem` (record to memory), `NPCStateChange` (update npc_states)
- **New**: `_handle_spawn_command()` — `/spawn enemy <name>`, `/spawn weapon <name>`, `/inject [toggle|status]` debug commands
- **New**: `_check_deviation()` — Phase 3.5 deviation detection stub (returns 0.0, full LLM-based implementation deferred)
- **Updated**: `handle_user_input()` — accepts `weapon_lib`, `enemy_lib`, `injector`, `l1_data`, `l3_data` parameters; checks for `/` commands before LLM call; passes L1/L3 context to narrative prompts

### `notebooks/notebook_simplified.ipynb`

- Added library imports (`WeaponLibrary`, `EnemyLibrary`, `ContentInjector`)
- Added library initialization cell (loads core weapons/enemies, creates injector)
- Updated `/help` with `/spawn` and `/inject` commands
- Updated `handle_user_input()` call to pass library/injector references

### `notebooks/parser.ipynb`

- Updated imports from `parsers`/`pipeline` → `archive.parsers`/`archive.pipeline`
- Added deprecation notice pointing to `module_designer/layered_parser`

---

## Deprecated

| File | Status |
|------|--------|
| `src/parsers.py` | Moved to `src/archive/parsers.py` |
| `src/pipeline.py` | Moved to `src/archive/pipeline.py` |

To be replaced by `module_designer/layered_parser.py` + `module_designer/layered_pipeline.py` (planned, not in this round).

---

## Design Decisions

1. **Three-layer model**: L1 (player-visible, overridable by LLM at runtime), L2 (KP info, existing Interaction/GameEvent aligned at schema level), L3 (designer intent, immutable at runtime)
2. **Library scope**: Core only — ~10 weapons + ~5 enemies. User extensions via JSON files in `data/library/extensions/`
3. **Two-tier judgment**: T1 (deterministic dice math, always on) + T2 (LLM interprets special rules/abilities, toggleable via `tier2_enabled`)
4. **Content injection**: Dual mode — offline (module build time, deterministic rules) + runtime (deviation-triggered, LLM-driven, toggleable)
5. **NPC runtime state**: Managed by `ScenarioWorld.npc_states` (mutable dict), not static JSON. Updated via `NPCStateChange` side effect or LLM improvise
6. **Scene weapons only**: Only weapons get structured `SceneWeapon` entries. Regular items (flashlight, rope) handled by LLM narrative
7. **HiddenInfo**: Passive "hidden roll" mechanic — system checks conditions automatically, distinct from active `Interaction` choice
8. **Five toggleable control points**: `runtime_injection`, `tier2_llm_judgment`, `offline_injection`, `l3_guardrails`, `deviation_threshold`

---

## Test Results

```
tests/test_library.py ............. 17 passed
tests/test_module_designer.py ..... 17 passed
Total: 34 passed
```

---

## Deferred to Future Rounds

- Deviation score actual implementation (currently stub at 0.0)
- Combat round pipeline
- SAN/HP auto-application
- Save encryption/version migration
- Multi-module management UI
- Runtime auto_trigger condition evaluation
- Testing strategy checklist

---

# Progressive Parser Rewrite — Changelog

**Date**: 2026-05-14
**Design Spec**: `docs/superpowers/specs/2026-05-14-progressive-parser-design.md`
**Plan**: `docs/superpowers/plans/2026-05-14-progressive-parser-plan.md`

## Overview

Replaced the one-shot `parse_module()` (3 LLM calls) with a **4-step progressive pipeline** (10 LLM calls, 6 serial steps). Key improvements: name anchoring in Step 1 eliminates cross-layer scene name drift; interactions generated first to anchor flag names; LLM-driven dependency resolution replaces fragile regex-based requirement parsing; library matching with LLM selection from weapon/enemy lists (no more invented names). Every LLM call wrapped with retry+fallback (`_with_fallback`). 10 commits, 44 tests.

## Data Model Changes

### `l2_keeper.py` — HiddenInfo → AutoTrigger

| Old | New |
|-----|-----|
| `HiddenInfo(info, trigger_condition, reveal_narrative, linked_skill, extra)` | `AutoTrigger(id, name, scene, trigger_condition, effect_type, effect_ref, reveal_narrative, extra)` |
| `SceneL2.hidden_info` | `SceneL2.auto_triggers` |

AutoTrigger unifies the old `hidden_info` (passive reveal) and spawn/grant mechanics into a single event type. `effect_type`: `reveal_info` / `spawn_enemy` / `grant_weapon` / `npc_state_change`. `effect_ref` is filled by Step 4 library matching.

### `l3_designer.py` — Sync to new template

| Field | Old → New |
|-------|----------|
| `EndingCondition.narrative_theme` | → `narrative` |
| `ToneConstraints.required` | → `recommended` |
| `SceneIntent` | Removed `emotion`, `danger_level`, `key_info`, `exit_leads_to` |
| `LogicChain`, `Branch` | Removed entirely |
| `L3Designer.logic_chains` | Removed |

### `layered_schema.py` — Schema sync

- Removed: `L2_HIDDEN_INFO_SCHEMA`, `L3_BRANCH_SCHEMA`, `L3_LOGIC_CHAIN_SCHEMA`, `L3_DANGER_LEVELS`, `L3_ENDING_TYPES`
- Added: `L2_AUTO_TRIGGER_SCHEMA`
- Updated: `L2_SCENE_SCHEMA` (`hidden_info` → `auto_triggers`), `L3_SCENE_INTENT_SCHEMA`, `L3_ENDING_CONDITION_SCHEMA`, `L3_TONE_CONSTRAINTS_SCHEMA`

### `l2_template.json` — Updated

- Removed `hidden_info` section
- Added `auto_triggers` section with `id`, `name`, `scene`, `trigger_condition`, `effect_type`, `effect_ref`, `reveal_narrative`

## Core Rewrites

### `layered_parser.py` — Complete rewrite (~730 lines)

Old: `parse_l1()` / `parse_l2()` / `parse_l3()` / `parse_module()` — 3 serial LLM calls, one-shot generation.

New: 4-step progressive pipeline:

```
Step 1a: structured_extraction  →  meta + scenes[{name,id}] + characters[{name,id}]
Step 1b: condensed_module       →  condensed_text (semi-structured markdown)
         (1a+1b run in parallel)

Step 2a: interactions           →  all interactions with IDs + flag names
Step 2b: events + auto_triggers  →  global events + passive triggers (parallel, injects 2a output)
Step 2c: L1 + L3                →  player-visible + designer layers (parallel, independent)

Step 3a: dependency_resolution  →  flag unification, requirement completion, cross-reference
Step 3b: L1-L2_cross_check      →  linked_interaction verification, scene name alignment

Step 4: library_matching        →  fill enemy_ref/weapon_ref/effect_ref from weapon/enemy libraries
```

10 prompt builders + 10 parse functions. Each prompt builder takes structured context (scene lists, interaction lists) rather than just raw text. `_with_fallback` wraps every LLM call: retry up to N times, then return degraded output with `_fallback: True` marker.

### `layered_pipeline.py` — Rewrite (~540 lines)

Old: `run_pipeline(l1_data, l2_data, l3_data, injector=, ...)` — serial schema validation + offline injection + cross-reference.

New: `run_pipeline(content, llm_json, llm_text=, ...)` — full orchestration:
- Step 1a+1b: `ThreadPoolExecutor(max_workers=2)` parallel
- Step 2a: serial (needed for interaction IDs)
- Step 2b+2c: `ThreadPoolExecutor(max_workers=4)` parallel
- Step 3a → 3b: serial (3b needs 3a's resolved names)
- Step 4: serial, conditional on library availability
- Final: schema validation + deterministic cross-reference on grouped L2 data

Every LLM call gate through `_with_fallback`. `PipelineResult.fallbacks` tracks which steps degraded. `save_pipeline_result()` groups interactions/auto_triggers by scene ID for L2 output.

`CrossRefReport` and `cross_validate_layers()` preserved unchanged.

## Test Results

```
tests/test_library.py ............. 17 passed
tests/test_module_designer.py ..... 27 passed
Total: 44 passed (+10 from previous round)
```

New tests: `test_auto_trigger_roundtrip`, 9 prompt builder structure tests (Steps 1a-4), `test_pipeline_result_summary_with_fallbacks`, `test_fallback_utility`.

## Design Decisions (this round)

1. **Progressive over one-shot**: LLM calls increase (3→10) but each prompt is shorter and more focused, producing more consistent output.
2. **Interactions first**: Interactions are the largest content block and define flag names — running them before events/auto-triggers ensures downstream steps reference consistent identifiers.
3. **LLM-driven cross-validate**: Deterministic code does structural checks (zero token); LLM does semantic correction (flag unification, name alignment).
4. **Natural language conditions**: Auto-trigger `trigger_condition` uses free-form natural language, not a DSL — LLM generates and runtime LLM interprets.
5. **Retry + fallback**: Every LLM call gets up to N retries on format/content failure, then degraded output — pipeline never crashes on a single step failure.
6. **condensed_text as canonical source**: Step 1b produces a complete, fluent narrative text (not an abstract) that all subsequent steps consume — removes original document noise while preserving all information.
