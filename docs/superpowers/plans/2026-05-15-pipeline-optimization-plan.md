# 解析管线优化四则 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove enemy_ref/weapon_ref fields, split condensed_text into chapters, switch scene IDs to Chinese names, assemble L2 structure after Step 3a

**Architecture:** Sequential edits: remove fields → add chapter parsing → switch to Chinese scene names → assemble L2 early → final schema cleanup

**Tech Stack:** Python 3.12+, dataclasses, json

---

### Task 1: Remove enemy_ref/weapon_ref from data model + template + schema

**Files:**
- Modify: `src/module_designer/l2_keeper.py:66-115` (AutoTrigger)
- Modify: `src/module_designer/layered_schema.py:44-52,70-72` (L2_INTERACTION_SCHEMA, L2_AUTO_TRIGGER_SCHEMA)
- Modify: `data/templates/l2_template.json`

- [ ] **Step 1: Update l2_keeper.py — AutoTrigger**

Remove `enemy_ref` and `weapon_ref` from the AutoTrigger dataclass, `to_dict`, and `from_dict`.

In AutoTrigger (around line 67), delete these lines:
```python
    enemy_ref: str = ""          # Step 4 填入
    weapon_ref: str = ""         # Step 4 填入
```

In to_dict, remove:
```python
            "enemy_ref": self.enemy_ref,
            "weapon_ref": self.weapon_ref,
```

In from_dict, remove:
```python
            enemy_ref=data.get("enemy_ref", ""),
            weapon_ref=data.get("weapon_ref", ""),
```

- [ ] **Step 2: Update layered_schema.py**

Remove `enemy_ref` and `weapon_ref` from `L2_INTERACTION_SCHEMA` (lines 44-52). The schema dict should not have these two keys.

- [ ] **Step 3: Update l2_template.json**

Remove `"enemy_ref": null,` and `"weapon_ref": null,` from interactions and auto_triggers sections.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: some test failures (tests reference old fields) — will fix in Task 5

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/l2_keeper.py src/module_designer/layered_schema.py data/templates/l2_template.json
git commit -m "refactor: remove enemy_ref and weapon_ref fields — info now in side_effects/result/scene descriptions"
```

---

### Task 2: Add _parse_condensed_chapters + convert all prompts from condensed_text to chapters

**Files:**
- Modify: `src/module_designer/layered_parser.py` (add utility + change all build_step* and parse_step* signatures)
- Modify: `src/module_designer/layered_pipeline.py` (add chapter parsing call, pass chapters dict)

- [ ] **Step 1: Add _parse_condensed_chapters utility**

In `layered_parser.py` utility section, add:

```python
def _parse_condensed_chapters(markdown_text: str) -> dict[str, str]:
    """按 ## 标题拆分为章节 dict。key 为标题名（去掉 ## 前缀和空格）."""
    chapters = {}
    current_title = "_header"
    current_lines = []
    for line in markdown_text.split("\n"):
        if line.startswith("## "):
            if current_lines:
                chapters[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chapters[current_title] = "\n".join(current_lines).strip()
    return chapters
```

- [ ] **Step 2: Change all build_step* prompt builders**

Every `build_step*_prompt` function currently takes `condensed_text: str`. Change all to `chapters: dict[str, str]`. Inside each prompt, replace `{condensed_text}` with `{chapters.get('module_overview', '')}` or the relevant chapter(s).

Full reference sections to use:

| Function | Chapter(s) |
|----------|------------|
| `build_step2a_prompt` | `chapters.get('scenes','')` + `chapters.get('locations_and_map','')` |
| `build_step2b_events_prompt` | `chapters.get('scenes','')` + `chapters.get('events_summary','')` |
| `build_step2b_at_prompt` | `chapters.get('scenes','')` |
| `build_step2c_l1_prompt` | `chapters.get('scenes','')` + `chapters.get('npcs','')` |
| `build_step2c_l3_prompt` | `chapters.get('module_overview','')` + `chapters.get('events_summary','')` |
| `build_step3a_prompt` | all chapters (combined) |
| `build_step3b_prompt` | all chapters |
| `build_step35_prompt` | all chapters |
| `build_step4_prompt` | all chapters |

Context reference format: replace `{condensed_text}` with `{chapters.get('section_name', '')}`. For functions needing all chapters, join them: `"\n\n".join(chapters.values())`.

- [ ] **Step 3: Change all parse_step* signatures**

Update each `parse_step*` function signature from `condensed_text: str` to `chapters: dict[str, str]`. Pass through to the corresponding `build_step*`.

- [ ] **Step 4: Update layered_pipeline.py**

In `run_pipeline()`, after Step 1b gets `condensed_text`, add:
```python
    from module_designer.layered_parser import _parse_condensed_chapters
    chapters = _parse_condensed_chapters(condensed_text) if condensed_text else {}
```

Then replace all `parse_step*(condensed_text, ...)` calls with `parse_step*(chapters, ...)`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: failures due to signature changes — Task 5 fixes

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py
git commit -m "feat: add _parse_condensed_chapters, convert all prompts from condensed_text to chapters dict"
```

---

### Task 3: Switch scene IDs to Chinese names

**Files:**
- Modify: `src/module_designer/layered_parser.py` (Step 1a prompt + all scene-related format references)
- Modify: `src/module_designer/layered_pipeline.py` (remove name_to_id maps)

- [ ] **Step 1: Update build_step1a_prompt**

In `build_step1a_prompt`, change the scenes output format from:
```
"scenes": [{"name": "场景中文名", "id": "S1"}, ...]
```
to:
```
"scenes": ["场景中文名", ...]
```

Remove "id" from scenes entirely.

- [ ] **Step 2: Update all prompts to use Chinese names in scene field**

In every `build_step*_prompt`, change the example `scene` field values from `"S1"` to `"6号车厢"`:
- Step 2a: `"scene": "6号车厢"` in interaction example
- Step 2b events: (no scene field — events are global)
- Step 2b AT: `"scene": "6号车厢"` in AT example
- `scene_movements` key: `"6号车厢"` instead of `"S1"`
- `scene_list` formatting: just list the names `"\n".join(f"- {s}" for s in scene_names)`
- `from_here[].target` / `to_here[].source`: Chinese names

Update all scene-related requirements text: "使用场景中文名" instead of "使用给定列表中的 ID (S1, S2...)"

- [ ] **Step 3: Update layered_pipeline.py**

Remove name_to_id mapping (around line 450):
```python
    name_to_id = {s["name"]: s["id"] for s in scenes if s.get("name") and s.get("id")}
    l2_descriptions = {}
    for name, sdata in l1_data.items():
        sid = name_to_id.get(name, name)
        desc = sdata.get("description", "") or ...
```

Becomes:
```python
    l2_descriptions = {}
    for name, sdata in l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "") or sdata.get("entry_narrative", "")
        if desc:
            l2_descriptions[name] = desc
```

Step 1a result extraction: `scenes = step1a.get("scenes", [])` — scenes is now a list of strings, not dicts. Update any iteration over scenes list.

Update `_assemble_l2` (Task 4 will add this) to use scene names as dict keys directly.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: failures from scene ID references — Task 5 fixes

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py
git commit -m "refactor: switch scene references from IDs (S1) to Chinese names (6号车厢)"
```

---

### Task 4: Add _assemble_l2 + move L2 assembly to after Step 3a

**Files:**
- Modify: `src/module_designer/layered_pipeline.py`

- [ ] **Step 1: Add _assemble_l2 function**

```python
def _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data) -> dict:
    """将 Step 3a 后的实体按场景分组组装为 L2 结构."""
    scenes: dict[str, dict] = {}
    for inter in interactions:
        sname = inter.get("scene", "")
        if sname:
            scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                       "encounters": [], "scene_weapons": [],
                                       "from_here": [], "to_here": [], "extra": {}})
            scenes[sname]["interactions"].append(inter)
    for at in auto_triggers:
        sname = at.get("scene", "")
        if sname:
            scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                       "encounters": [], "scene_weapons": [],
                                       "from_here": [], "to_here": [], "extra": {}})
            scenes[sname]["auto_triggers"].append(at)
    for sname, movement in scene_movements.items():
        scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                   "encounters": [], "scene_weapons": [],
                                   "from_here": [], "to_here": [], "extra": {}})
        scenes[sname]["from_here"] = movement.get("from_here", [])
        scenes[sname]["to_here"] = movement.get("to_here", [])
    for sname in scenes:
        l1_scene = l1_data.get(sname, {})
        scenes[sname]["description"] = l1_scene.get("entry_narrative", "") or l1_scene.get("atmosphere", "")
    return {
        "scenes": scenes,
        "events": events,
        "npc_profiles": {},
    }
```

- [ ] **Step 2: Wire _assemble_l2 after Step 3a**

In `run_pipeline()`, after Step 3a completes and before Step 3b, add:
```python
    # ── 组装 L2 结构 ──
    l2_assembled = _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data)
```

Change Step 3b call to use `l2_assembled` instead of hand-building `l2_completed`:
```python
    def _do_step3b():
        return parse_step3b(chapters, l1_data, l2_assembled, l3_data, scene_names, llm_json)
```

Change Step 3.5 call to use `l2_assembled["events"]` and extract entities from `l2_assembled["scenes"]`:
```python
    # Extract entities from assembled L2 for Step 3.5/4
    assembled_interactions = []
    assembled_at = []
    for sname, sdata in l2_assembled.get("scenes", {}).items():
        assembled_interactions.extend(sdata.get("interactions", []))
        assembled_at.extend(sdata.get("auto_triggers", []))
```

- [ ] **Step 3: Simplify save_pipeline_result**

Remove the scenes_by_id grouping logic from `save_pipeline_result`. Now just serializes `result.l2_data` directly:
```python
    path = os.path.join(module_dir, "l2_keeper.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l2_data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Update final validation section**

Remove the scenes_by_sid grouping code in the validation block. Use `l2_assembled` directly for `validate_all` and `cross_validate_layers`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: failures from structural changes — Task 5 fixes

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_pipeline.py
git commit -m "refactor: assemble L2 structure after Step 3a, simplify save and validation"
```

---

### Task 5: Fix all tests and update notebooks

**Files:**
- Modify: `tests/test_module_designer.py`
- Modify: `tests/test_dependency_graph.py` (if needed)
- Modify: `notebooks/parser_test.ipynb`
- Modify: `notebooks/_parser_layered_export.py`

- [ ] **Step 1: Fix test data — remove enemy_ref/weapon_ref**

In all test fixtures that create AutoTrigger or pass entity dicts, remove `enemy_ref`/`weapon_ref` fields.

- [ ] **Step 2: Fix test data — condensed_text → chapters**

Update test functions that call `build_step*_prompt` to pass `chapters: dict[str, str]` instead of `condensed_text: str`. Example:
```python
chapters = {"scenes": "...", "events_summary": "...", "module_overview": "..."}
prompt = build_step2a_prompt(chapters, scenes)
```

- [ ] **Step 3: Fix test data — scene names from dict to string**

Update scenes from `[{"id": "S1", "name": "6号车厢"}]` to `["6号车厢"]`.

- [ ] **Step 4: Fix test data — entity scene field to Chinese names**

Update entity fixtures: `"scene": "S1"` → `"scene": "6号车厢"`.

- [ ] **Step 5: Update notebooks**

Both notebooks need the same changes:
- Import `_parse_condensed_chapters`, call it after Step 1b
- Pass `chapters` to all `build_step*` calls
- Remove `enemy_ref`/`weapon_ref`
- Scene names as Chinese strings
- Add `_assemble_l2` call after Step 3a (manual inline version)
- `scenes_by_sid` → `scenes_by_name`

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -x -q`
Expected: 50 passed

- [ ] **Step 7: Commit**

```bash
git add tests/ notebooks/
git commit -m "test: update tests and notebooks for 4 pipeline optimizations"
```

---

### Task 6: Final schema cleanup — remove old validations

**Files:**
- Modify: `src/module_designer/layered_schema.py`

- [ ] **Step 1: Clean schema to match new format**

Remove any remaining old field references from schemas. Specific checks:
- No `enemy_ref`, `weapon_ref` in any schema
- No `irreversible_impact` in event schema
- No `effect_type`, `effect_ref`, `reveal_narrative`, `trigger_condition` in auto_trigger schema
- No `clue` in interaction schema
- No `scene` in event schema requirement (event has no scene)
- All `id` requirements on schema fields reflect current state

- [ ] **Step 2: Clean up unused schemas**

If any schema dicts are dead (no longer referenced), remove them. Keep only: L1 schemas, L2 schemas (interaction/encounter/scene_weapon/auto_trigger/event/npc_profile/scene), L3 schemas.

- [ ] **Step 3: Clean _validate_object**

Ensure `_validate_object` still works correctly with the cleaned schemas. No changes needed to the validation engine itself — just the schema dicts.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -x -q`
Expected: 50 passed

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/layered_schema.py
git commit -m "refactor: final schema cleanup — remove all old field validations, align with new format"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: all 50 pass

- [ ] **Step 2: Integration check**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from module_designer.l2_keeper import AutoTrigger
from module_designer.layered_parser import _parse_condensed_chapters, load_json

# 1. AutoTrigger has no enemy_ref/weapon_ref
d = AutoTrigger(id='AT1', name='test', scene='6号车厢').to_dict()
assert 'enemy_ref' not in d
assert 'weapon_ref' not in d
print('1. AutoTrigger clean')

# 2. Chapter parsing
text = '## module_overview\nhello\n## scenes\nworld\n'
ch = _parse_condensed_chapters(text)
assert ch['module_overview'] == 'hello'
assert ch['scenes'] == 'world'
print('2. Chapters OK')

# 3. Template valid
import json
tmpl = json.load(open('data/templates/l2_template.json'))
at = tmpl['scenes']['6号车厢']['auto_triggers'][0]
assert 'enemy_ref' not in at
assert 'weapon_ref' not in at
assert 'scene' in at
print('3. Template OK')

print('ALL CHECKS PASSED')
"
```
Expected: `ALL CHECKS PASSED`

- [ ] **Step 3: Commit if any fixes needed**
