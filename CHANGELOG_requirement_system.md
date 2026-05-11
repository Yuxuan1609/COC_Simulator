# Requirement & Clue System — Change Log

**Date**: 2026-05-06
**Spec**: `docs/superpowers/specs/2026-05-06-requirement-system-design.md`

## scenario_core.py

### New: `Requirement` dataclass (line ~36)
- `ref_type`: `"interaction"` | `"event"` | `"flag"`
- `ref_scene`: scene ID (or event ID for event-type)
- `ref_name`: prerequisite name

### Changed: `Interaction` dataclass
- `clue`: `str` → `Optional[str]` (default `None`, JSON has nulls)
- Added `requirements: List[Requirement]` (default `[]`)

### Changed: `GameEvent` dataclass
- Added `requirements: List[Requirement]` (default `[]`)

### Changed: `DirectedGraph.load_scenes`
- Parses `requirement` array from interaction JSON → `List[Requirement]`
- Reads `clue` as nullable (`inter.get("clue")` without fallback to `""`)

### Changed: `DirectedGraph.load_events`
- Parses `requirement` array from event JSON → `List[Requirement]`
- Supports both `irreversible_impact` and `impact` keys (backward compat)

### New: `RequirementResolver` class (before `ScenarioWorld`)
- `check(requirements) → (bool, str)` — validates all reqs, returns first missing condition on failure
- `get_unmet(requirements) → List[Requirement]` — returns subset not satisfied
- `resolve_chain(requirements) → List[Requirement]` — stub, delegates to `get_unmet`

### Changed: `ScenarioWorld.__init__`
- Creates `self.requirement_resolver = RequirementResolver(self)`

### Changed: `ScenarioWorld.execute_interaction`
- Calls `requirement_resolver.check()` before executing
- Returns `(False, "需要先完成「X号车厢」的「动作名」")` when prerequisites unmet

### Changed: `ScenarioWorld.trigger_event`
- Calls `requirement_resolver.check()` before triggering
- Same failure format as `execute_interaction`

### Changed: `ScenarioWorld.get_scene_summary`
- Appends `[需要前置]` suffix to gated interactions in output

### Changed: `ScenarioWorld.get_scene_info`
- Interaction dicts now include `clue` and `requirements_met` fields

### New: `ScenarioWorld._are_requirements_met(interaction)`
- Convenience method returning `bool` for a single interaction

## notebook_simplified.ipynb

### Cell `ba337da8dcf55dee` (run_game)
- `scene_output_revised.json` → `scene_output_resolved_revised.json`
- `res_event_revised.json` → `res_event_resolved_revised.json`

### Cell `97f37a6dac767b62` (prompt builders)
- `_build_scene_context`: appends `[需要前置]` hint to gated interaction names
- `build_event_prompt`: appends `[条件未满足]` hint to events with unmet requirements
