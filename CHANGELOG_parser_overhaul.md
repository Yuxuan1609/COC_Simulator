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
- Fallback strategy for LLM output violating L3 guardrails
- Testing strategy checklist
