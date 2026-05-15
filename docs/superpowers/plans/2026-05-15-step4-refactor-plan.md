# Step 4 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Step 4 into Phase 1 (style preview, parallel with 3.5) + Phase 2 (streamlined standardization with @ dispatch syntax), strip based_on from final output.

**Architecture:** Phase 1 is a new lightweight LLM call that reads chapters to determine enemy/weapon style and quantity bounds. Phase 1 output feeds into Phase 2 as a constraint, and also populates L2 encounters/scene_weapons arrays. Phase 2 replaces the current Step 4 with a slimmed prompt — entities only pass 6 fields, side_effects use `@function(param=value)` syntax instead of structured JSON dicts.

**Tech Stack:** Python 3.x, layered_parser.py (prompt builders), layered_pipeline.py (orchestration), Jupyter notebook (test driver)

---

### Task 1: Phase 1 — SYSTEM prompt + prompt builder

**Files:**
- Modify: `src/module_designer/layered_parser.py` (insert before Step 4 section, ~line 867)

- [ ] **Step 1: Add PHASE1_SYSTEM and helper function**

After the Step 3b section and before the Step 4 section, insert:

```python
# ═══════════════════════════════════════════════════════════════
#  Phase 1: 风格预判
# ═══════════════════════════════════════════════════════════════

PHASE1_SYSTEM = """你是一个 TRPG 模组风格分析助手。
你的任务是：根据模组精修文本，判断敌人和武器的风格方向和数量范围，用于后续约束生成。

重要原则：
- enemy_ref / weapon_ref 必须从提供的库列表中选择，不允许自创名称
- 约束宽松，只需符合模组背景设定，允许随机性
- 不做场景绑定——跑团中任何场景都可能出现
- min_count 可为 0（表示可能不出现），max_count 为最多出现次数
- 仅输出 JSON，不要任何解释性文字"""


def build_phase1_prompt(
    chapters: dict[str, str],
    scene_intents: dict,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    return f"""根据模组背景确定敌人和武器的风格方向与数量范围。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## L3 Scene Intents（设计意图参考）
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组
\"\"\"
{chapters.get('enemies','')}

{chapters.get('module_overview','')}
\"\"\"

输出格式:
{{
  "enemies": [
    {{"enemy_ref": "敌人名", "min_count": 0, "max_count": 2}}
  ],
  "weapons": [
    {{"weapon_ref": "武器名", "min_count": 1, "max_count": 1}}
  ]
}}

要求：
1. enemy_ref 和 weapon_ref 必须从可用库中选择，不允许自创
2. 数量约束宽松，只需符合背景；若模组未提及敌人/武器，返回空列表
3. 仅输出 JSON"""


def parse_phase1(
    chapters: dict[str, str],
    scene_intents: dict,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    llm_call,
) -> dict:
    prompt = build_phase1_prompt(chapters, scene_intents, weapon_library_names, enemy_library_names)
    return llm_call(prompt, system=PHASE1_SYSTEM)
```

- [ ] **Step 2: Verify Phase 1 code parses**

Run: `python -c "from module_designer.layered_parser import PHASE1_SYSTEM, build_phase1_prompt, parse_phase1; print('Phase 1 imports OK')"`
Expected: `Phase 1 imports OK`

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: add Phase 1 style preview SYSTEM + prompt builder"
```

---

### Task 2: Phase 2 — SYSTEM prompt + prompt builder rewrite

**Files:**
- Modify: `src/module_designer/layered_parser.py` (replace STEP4_SYSTEM, build_step4_prompt, parse_step4)

- [ ] **Step 1: Add entity field sliming helper**

After the `_parse_condensed_chapters` helper, add:

```python
def _slim_entity(entity: dict) -> dict:
    """从 entity dict 中提取 Phase 2 需要的 6 个字段."""
    slimmed = {k: entity.get(k, "") for k in ("name", "scene", "type")}
    slimmed["result"] = entity.get("result", "")
    if entity.get("graded_result"):
        slimmed["graded_result"] = entity["graded_result"]
    slimmed["side_effects"] = entity.get("side_effects", [])
    return slimmed
```

- [ ] **Step 2: Rewrite STEP4_SYSTEM**

Replace the existing `STEP4_SYSTEM` (~line 868) with:

```python
STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：将 entity 中的 type 标准化为技能名，并将 side_effects / result / graded_result 中的自然语言转化为 @函数(参数) 标记。

术语：interaction、auto_trigger、event 三者统称为 entity（实体）。

重要原则：
- type 必须从标准技能列表中选择，不涉及检定保持"无"
- side_effects / result / graded_result 中的关键信息用 @函数(参数=值) 标记替代自然语言描述
- @标记可嵌入任何文本字段中，与普通文本混合
- spawn_enemy 和 grant_weapon 的 enemy_ref/weapon_ref 必须来自 Phase 1 约束列表，且总调用次数不超过对应 max_count
- stat_change 的 stat_name 必须来自标准属性列表
- @item_gain 用于纯文本物品，不做库匹配
- 无法归入 @函数的自然语言保留原样
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 3: Rewrite build_step4_prompt**

Replace the existing `build_step4_prompt` (~line 885) with:

```python
def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    chapters: dict[str, str],
    phase1_constraints: dict,
    skill_names: list[str],
    stat_names: list[str],
) -> str:
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    stats_list = "\n".join(f"- {s}" for s in stat_names)
    desc_list = "\n".join(f"- {name}: {desc}" for name, desc in l2_descriptions.items())

    # Slim entities to 6 fields only
    slim_interactions = json.dumps(
        [_slim_entity(i) for i in interactions], ensure_ascii=False, indent=2
    )
    slim_at = json.dumps(
        [_slim_entity(a) for a in auto_triggers], ensure_ascii=False, indent=2
    )

    return f"""标准化 type，将 side_effects/result/graded_result 转为 @函数(参数) 标记。

## Phase 1 约束（spawn_enemy / grant_weapon 必须在约束范围内）
{json.dumps(phase1_constraints, ensure_ascii=False, indent=2)}

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

## 标准属性列表（stat_change 的 stat_name 必须从此列表中选择）
{stats_list}

## 场景描述（参考上下文）
{desc_list}

## L3 Scene Intents
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组（参考上下文）
\"\"\"
{"\n\n".join(chapters.values())}
\"\"\"

## Interactions (仅含需标准化的字段，side_effects 待结构化)
{slim_interactions}

## Auto-triggers (仅含需标准化的字段，side_effects 待结构化)
{slim_at}

任务:
1. **type 标准化**: 从标准技能列表中选择最匹配的技能名。不涉及检定的保持"无"。
2. **@标记转化**: 将 side_effects / result / graded_result 中的自然语言转化为 @函数(参数=值) 标记:

   @spawn_enemy(enemy_ref="敌人名", scene="场景名", quantity=1)
   @grant_weapon(weapon_ref="武器名", scene="场景名", quantity=1)
   @stat_change(stat_name="属性名", delta=-1, narrative="角色经历（可选）")
   @item_gain(item_name="物品名")
   @npc_state_change(npc_name="NPC名", new_state="新状态")

   无法归入以上类型的保留原自然语言。

3. **数量约束**: spawn_enemy / grant_weapon 的总调用次数不得超过 Phase 1 约束中对应条目的 max_count。
4. **结果嵌入**: @标记可嵌入 result / graded_result 各等级 / side_effects 等任何字段。graded_result 各等级为独立字符串，可独立含 @标记。
5. 不允许自创 enemy_ref / weapon_ref / stat_name。
6. type 为"无"的 entity 若无实质 side_effects 则保持原样。

输出格式:
{{
  "interactions": [{{ ...entity 字段..., "type": "标准技能名" }}],
  "auto_triggers": [{{ ...entity 字段..., "type": "标准技能名" }}]
}}

仅输出 JSON。"""
```

- [ ] **Step 4: Rewrite parse_step4**

Replace the existing `parse_step4` with updated signature (remove weapon/enemy_library_names, add phase1_constraints):

```python
def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    chapters: dict[str, str],
    phase1_constraints: dict,
    skill_names: list[str],
    stat_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, chapters,
        phase1_constraints, skill_names, stat_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
```

- [ ] **Step 5: Verify imports**

Run: `python -c "from module_designer.layered_parser import STEP4_SYSTEM, build_step4_prompt, parse_step4, _slim_entity, PHASE1_SYSTEM, build_phase1_prompt, parse_phase1; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: rewrite Step 4 → Phase 2 with slimmed entities, @dispatch syntax, Phase 1 constraint injection"
```

---

### Task 3: Pipeline — Phase 1 parallel, Phase 2 integration, based_on strip

**Files:**
- Modify: `src/module_designer/layered_pipeline.py`

- [ ] **Step 1: Update imports**

In the `run_pipeline` function's local import block (~line 278), add Phase 1 to the import:

```python
from module_designer.layered_parser import (
    _is_valid_json_output, _with_fallback,
    parse_step1a, parse_step1b,
    parse_step2a, parse_step2b_events, parse_step2b_at,
    parse_step2c_l1, parse_step2c_l3,
    parse_step3a, parse_step3b, parse_step4,
    parse_step35, parse_phase1,
)
```

- [ ] **Step 2: Replace Step 3.5 + Step 4 parallel block**

Replace the entire Step 3.5 + Step 4 section (~lines 488-588) with:

```python
    # ── Step 3.5 + Phase 1 (并行) ──────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3.5 + Phase 1] 依赖图构建 + 风格预判 (并行)...")

    # 标准属性集
    stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    l2_descriptions = {}
    for name, sdata in l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "") or sdata.get("entry_narrative", "")
        if desc:
            l2_descriptions[name] = desc

    weapon_names = []
    enemy_names = []
    try:
        if weapon_lib:
            weapon_names = [w.name for w in weapon_lib.list_all()]
    except Exception:
        pass
    try:
        if enemy_lib:
            enemy_names = [e.name for e in enemy_lib.list_all()]
    except Exception:
        pass

    skill_names = []
    try:
        import os as _os
        skill_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "skill_checks.json")
        with open(skill_path, "r", encoding="utf-8") as _f:
            skill_checks = json.load(_f)
            skill_names = sorted(set(s["name"] for s in skill_checks))
    except Exception:
        pass

    from module_designer.dependency_graph import DependencyGraph

    def _do_step35():
        """Step 3.5: LLM 解析 → 有向图 → 循环检测."""
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            step35_result = parse_step35(chapters, step35_interactions, step35_events, step35_at, llm_json)
            deps = step35_result.get("dependencies", [])
            if not deps:
                if attempt < max_tries:
                    if verbose:
                        print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
                    continue
                return {"graph": None, "dependencies": []}

            graph = DependencyGraph()
            graph.build(deps)
            cycles = graph.detect_cycles()
            if not cycles:
                if verbose:
                    print(f"  [Step 3.5] 依赖图: {len(graph.nodes)} 节点, {len(graph.edges)} 边, 无循环")
                return {"graph": graph, "dependencies": deps}

            if attempt < max_tries:
                if verbose:
                    cycle_ids = [str(p[0]) for p in cycles[:3]]
                    print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环 ({cycle_ids}...)，重调 LLM...")
                continue

        # Fallback: cut random edge
        if verbose:
            print(f"  [Step 3.5] 重调用尽，随机切断一条循环边")
        graph.cut_random_edge_in_cycles()
        return {"graph": graph, "dependencies": deps, "_circular_cut": True}

    def _do_phase1():
        """Phase 1: 风格预判."""
        return parse_phase1(
            chapters, l3_data.get("scene_intents", {}),
            weapon_names, enemy_names, llm_json,
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        f35 = ex.submit(_do_step35)
        f_p1 = ex.submit(lambda: _with_fallback(
            _do_phase1, ["enemies"],
            {"enemies": [], "weapons": []},
            max_retries, verbose, "Phase 1",
        ))
        step35_result = f35.result()
        phase1_result = f_p1.result()

    dep_graph = step35_result.get("graph")
    if dep_graph:
        result.l2_data["dependency_graph"] = dep_graph.to_dict()
    if step35_result.get("_circular_cut"):
        result.fallbacks.append("Step 3.5 (circular cut)")
    if phase1_result.get("_fallback"):
        result.fallbacks.append("Phase 1")

    # Inject Phase 1 output into L2 encounters/scene_weapons
    l2_assembled["encounters"] = phase1_result.get("enemies", [])
    l2_assembled["scene_weapons"] = phase1_result.get("weapons", [])
    if verbose:
        print(f"  Phase 1 完成: {len(phase1_result.get('enemies',[]))} 敌人类型, {len(phase1_result.get('weapons',[]))} 武器类型")

    # ── Phase 2 (串行，依赖 Phase 1) ──────────────────────────
    if verbose:
        print("[Phase 2] 精简标准化...")

    def _do_phase2():
        return parse_step4(
            step35_interactions, step35_at, l2_descriptions,
            l3_data.get("scene_intents", {}), chapters,
            phase1_result, skill_names, stat_names, llm_json,
        )

    phase2_result = _with_fallback(
        _do_phase2, ["interactions"],
        {"interactions": step35_interactions, "auto_triggers": step35_at},
        max_retries, verbose, "Phase 2",
    )

    interactions = phase2_result.get("interactions", step35_interactions)
    auto_triggers = phase2_result.get("auto_triggers", step35_at)
    if phase2_result.get("_fallback"):
        result.fallbacks.append("Phase 2")

    # Strip based_on from all entities in final output
    for e in interactions:
        e.pop("based_on", None)
    for e in auto_triggers:
        e.pop("based_on", None)
    for e in l2_assembled.get("events", []):
        e.pop("based_on", None)

    # Re-assemble L2 with Phase 2 standardized entities
    l2_assembled.clear()
    l2_assembled.update(_assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data))
    if dep_graph:
        l2_assembled["dependency_graph"] = dep_graph.to_dict()
```

Wait — `l2_assembled` is the dict returned by `_assemble_l2`, which has `scenes`, `events`, `npc_profiles`. Let me fix this — the encounters/scene_weapons injection needs to go into the scenes dict or be a top-level key. Let me look at the L2 template...

Actually, `encounters` and `scene_weapons` are per-scene arrays in the template. But per the spec, Phase 1 output is global (not per-scene). Let me store them at the top level of `l2_assembled` for now — they're constraints, not per-scene data.

Let me rewrite Step 2 more carefully.

- [ ] **Step 2 (rewritten): Replace Step 3.5 + Step 4 parallel block**

The Phase 1 constraint output is stored at `l2_assembled["_phase1"]` rather than polluting the scene structure. Replace the section from `# ── Step 3.5 + Step 4 (并行)` through the `step4 = f4.result()` block with:

```python
    # ── Step 3.5 + Phase 1 (并行) ──────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3.5 + Phase 1] 依赖图构建 + 风格预判 (并行)...")

    stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    l2_descriptions = {}
    for name, sdata in l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "") or sdata.get("entry_narrative", "")
        if desc:
            l2_descriptions[name] = desc

    weapon_names = []
    enemy_names = []
    try:
        if weapon_lib:
            weapon_names = [w.name for w in weapon_lib.list_all()]
    except Exception:
        pass
    try:
        if enemy_lib:
            enemy_names = [e.name for e in enemy_lib.list_all()]
    except Exception:
        pass

    skill_names = []
    try:
        import os as _os
        skill_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "skill_checks.json")
        with open(skill_path, "r", encoding="utf-8") as _f:
            skill_checks = json.load(_f)
            skill_names = sorted(set(s["name"] for s in skill_checks))
    except Exception:
        pass

    from module_designer.dependency_graph import DependencyGraph

    def _do_step35():
        """Step 3.5: LLM 解析 → 有向图 → 循环检测."""
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            step35_result = parse_step35(chapters, step35_interactions, step35_events, step35_at, llm_json)
            deps = step35_result.get("dependencies", [])
            if not deps:
                if attempt < max_tries:
                    if verbose:
                        print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
                    continue
                return {"graph": None, "dependencies": []}

            graph = DependencyGraph()
            graph.build(deps)
            cycles = graph.detect_cycles()
            if not cycles:
                if verbose:
                    print(f"  [Step 3.5] 依赖图: {len(graph.nodes)} 节点, {len(graph.edges)} 边, 无循环")
                return {"graph": graph, "dependencies": deps}

            if attempt < max_tries:
                if verbose:
                    cycle_ids = [str(p[0]) for p in cycles[:3]]
                    print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环 ({cycle_ids}...)，重调 LLM...")
                continue

        if verbose:
            print(f"  [Step 3.5] 重调用尽，随机切断一条循环边")
        graph.cut_random_edge_in_cycles()
        return {"graph": graph, "dependencies": deps, "_circular_cut": True}

    def _do_phase1():
        return parse_phase1(
            chapters, l3_data.get("scene_intents", {}),
            weapon_names, enemy_names, llm_json,
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        f35 = ex.submit(_do_step35)
        f_p1 = ex.submit(lambda: _with_fallback(
            _do_phase1, ["enemies"],
            {"enemies": [], "weapons": []},
            max_retries, verbose, "Phase 1",
        ))
        step35_result = f35.result()
        phase1_result = f_p1.result()

    dep_graph = step35_result.get("graph")
    if dep_graph:
        result.l2_data["dependency_graph"] = dep_graph.to_dict()
    if step35_result.get("_circular_cut"):
        result.fallbacks.append("Step 3.5 (circular cut)")
    if phase1_result.get("_fallback"):
        result.fallbacks.append("Phase 1")

    if verbose:
        print(f"  Phase 1 完成: {len(phase1_result.get('enemies',[]))} 敌人类型, {len(phase1_result.get('weapons',[]))} 武器类型")

    # ── Phase 2 (串行，依赖 Phase 1 约束) ─────────────────────
    if verbose:
        print("[Phase 2] 精简标准化...")

    def _do_phase2():
        return parse_step4(
            step35_interactions, step35_at, l2_descriptions,
            l3_data.get("scene_intents", {}), chapters,
            phase1_result, skill_names, stat_names, llm_json,
        )

    phase2_result = _with_fallback(
        _do_phase2, ["interactions"],
        {"interactions": step35_interactions, "auto_triggers": step35_at},
        max_retries, verbose, "Phase 2",
    )

    interactions = phase2_result.get("interactions", step35_interactions)
    auto_triggers = phase2_result.get("auto_triggers", step35_at)
    if phase2_result.get("_fallback"):
        result.fallbacks.append("Phase 2")
```

- [ ] **Step 3: Add based_on strip + re-assemble after Phase 2**

After the Phase 2 block and before `# ── 最终: Schema 验证`, insert:

```python
    # Strip based_on from all entities
    for e in interactions:
        e.pop("based_on", None)
    for e in auto_triggers:
        e.pop("based_on", None)
    for e in step35_events:
        e.pop("based_on", None)

    # Re-assemble L2 with Phase 2 standardized entities
    l2_assembled.clear()
    l2_assembled.update(_assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data))
    if dep_graph:
        l2_assembled["dependency_graph"] = dep_graph.to_dict()
    l2_assembled["_phase1"] = {"enemies": phase1_result.get("enemies", []),
                                "weapons": phase1_result.get("weapons", [])}
```

- [ ] **Step 4: Verify pipeline imports**

Run: `python -c "from module_designer.layered_pipeline import run_pipeline; print('pipeline import OK')"`
Expected: `pipeline import OK`

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/layered_pipeline.py
git commit -m "feat: wire Phase 1 parallel with 3.5, Phase 2 after, strip based_on from final output"
```

---

### Task 4: Notebook sync

**Files:**
- Modify: `notebooks/parser_test.ipynb`
- Modify: `notebooks/_parser_layered_export.py`

- [ ] **Step 1: Update Step 3.5+4 cell in parser_test.ipynb**

Current cell `3e36fe38dd5e9a4a` merges Step 3.5 + Step 4 into one cell. Replace with two cells:

**Cell A** (replaces `3e36fe38dd5e9a4a`) — Step 3.5 + Phase 1 parallel:

```python
# ═══ Step 3.5 + Phase 1: 依赖图 + 风格预判 (并行) ═══
weapon_names = [w.name for w in wl.list_all()]
enemy_names = [e.name for e in el.list_all()]
stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

import json as _json
import os as _os
try:
    skill_path = _os.path.join("..", "data", "skill_checks.json")
    with open(skill_path, "r", encoding="utf-8") as _f:
        skill_checks = _json.load(_f)
        skill_names = sorted(set(s["name"] for s in skill_checks))
except Exception:
    skill_names = []

l2_descriptions = {}
for name, sdata in l1_data.items():
    desc = sdata.get("description", "") or sdata.get("atmosphere", "")
    if desc:
        l2_descriptions[name] = desc

from module_designer.dependency_graph import DependencyGraph
from module_designer.layered_parser import build_phase1_prompt, PHASE1_SYSTEM

# ── Step 3.5: 依赖图 ──
MAX_TRIES = 3
dep_graph = None
for attempt in range(1, MAX_TRIES + 1):
    step35 = do_json_call(
        "step_35", "35_dependency_graph",
        build_step35_prompt,
        chapters, step35_interactions, step35_events, step35_at,
        system_prompt=STEP35_SYSTEM
    )
    deps = step35.get("dependencies", [])
    if not deps:
        print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
        continue
    dep_graph = DependencyGraph()
    dep_graph.build(deps)
    cycles = dep_graph.detect_cycles()
    if not cycles:
        print(f"  [Step 3.5] 依赖图: {len(dep_graph.nodes)} 节点, {len(dep_graph.edges)} 边, 无循环")
        break
    if attempt < MAX_TRIES:
        print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环，重试...")
    else:
        dep_graph.cut_random_edge_in_cycles()
        print(f"  [Step 3.5] 重调用尽，随机切断循环边")

# ── Phase 1: 风格预判 ──
scene_intents_for_p1 = l3_data.get("scene_intents", {})
phase1 = do_json_call(
    "phase_1", "phase1_style_preview",
    build_phase1_prompt,
    chapters, scene_intents_for_p1, weapon_names, enemy_names,
    system_prompt=PHASE1_SYSTEM
)
print(f"Phase 1 完成: {len(phase1.get('enemies',[]))} 敌人类型, {len(phase1.get('weapons',[]))} 武器类型")
```

**Cell B** (new cell `phase2_standardization`, insert after Cell A) — Phase 2:

```python
# ═══ Phase 2: 精简标准化 ═══
step4 = do_json_call(
    "phase_2", "phase2_standardization",
    build_step4_prompt,
    step35_interactions, step35_at, l2_descriptions,
    l3_data.get("scene_intents", {}), chapters,
    phase1, skill_names, stat_names,
    system_prompt=STEP4_SYSTEM
)
interactions = step4.get("interactions", step35_interactions)
auto_triggers = step4.get("auto_triggers", step35_at)
print(f"Phase 2 完成: skill/stat 标准化 + @标记转化")

# Strip based_on
for e in interactions:
    e.pop("based_on", None)
for e in auto_triggers:
    e.pop("based_on", None)
for e in events:
    e.pop("based_on", None)

# Re-assemble L2
l2_assembled = _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data)
if dep_graph:
    l2_assembled["dependency_graph"] = dep_graph.to_dict()
l2_assembled["_phase1"] = {"enemies": phase1.get("enemies", []),
                            "weapons": phase1.get("weapons", [])}
print(f"L2 重新组装完成: {len(l2_assembled.get('scenes',{}))} 场景")
```

- [ ] **Step 2: Update summary cell printout**

In the final summary cell (`3d914ea22f50a1b2`), update the Step 4 line:

```python
print(f"Step 4: Phase 1 风格预判 + Phase 2 标准化{'完成' if weapon_names or enemy_names or skill_names else '跳过'}")
print(f"")
print(f"总 LLM 调用: 12 (Step 1:2 + Step 2:5 + Step 3:2 + 3.5+Phase 1:2 + Phase 2:1)")
print(f"调试产物: {DEBUG_ROOT}/")
print(f"├── step_1/   (1a_structured_extraction, 1b_condensed_text)")
print(f"├── step_2/   (2a_interactions, 2b_events, 2b_auto_triggers, 2c_l1, 2c_l3)")
print(f"├── step_3/   (3a_dedup_conflict, 3b_cross_check)")
print(f"├── step_35/  (35_dependency_graph)")
print(f"├── phase_1/  (phase1_style_preview)")
print(f"└── phase_2/  (phase2_standardization)")
```

- [ ] **Step 3: Sync _parser_layered_export.py**

Apply the same changes to `notebooks/_parser_layered_export.py`:
- Replace the Step 3.5+4 section (~lines 374-445) with Step 3.5 + Phase 1 (parallel) + Phase 2 (serial)
- Update the summary printout
- Add `build_phase1_prompt` and `PHASE1_SYSTEM` to imports if not already present
- Use `l2_assembled` for validation and save (already done from earlier work)

- [ ] **Step 4: Commit**

```bash
git add notebooks/parser_test.ipynb notebooks/_parser_layered_export.py
git commit -m "feat: sync notebook with Phase 1 + Phase 2 pipeline, strip based_on"
```

---

### Task 5: Final verification

- [ ] **Step 1: Verify all imports resolve**

```bash
python -c "
from module_designer.layered_parser import (
    PHASE1_SYSTEM, build_phase1_prompt, parse_phase1,
    STEP4_SYSTEM, build_step4_prompt, parse_step4,
    _slim_entity,
)
from module_designer.layered_pipeline import run_pipeline, _assemble_l2
print('All imports OK')
"
```

- [ ] **Step 2: Verify prompt builders produce strings**

```python
from module_designer.layered_parser import build_phase1_prompt, build_step4_prompt, _slim_entity

# Phase 1
p1 = build_phase1_prompt(
    {"enemies": "深潜者", "module_overview": "test"},
    {"6号车厢": {"purpose": "test"}},
    ["手电筒"], ["深潜者"]
)
assert isinstance(p1, str) and len(p1) > 0
print(f"Phase 1 prompt: {len(p1)} chars OK")

# _slim_entity
entity = {"id": "I1", "name": "test", "scene": "X", "type": "侦察",
          "result": "ok", "side_effects": [], "requirement": "", "trigger": "",
          "difficulty": "regular", "based_on": "I0",
          "graded_result": {"on_failure": "fail"}}
slim = _slim_entity(entity)
assert "id" not in slim
assert "requirement" not in slim
assert "based_on" not in slim
assert slim["name"] == "test"
assert slim["graded_result"] == {"on_failure": "fail"}
print("_slim_entity OK")

# Phase 2
p2 = build_step4_prompt(
    [slim], [], {"X": "desc"}, {"X": {"purpose": "test"}},
    {"scenes": "test"}, {"enemies": [], "weapons": []},
    ["侦察"], ["SAN"]
)
assert isinstance(p2, str) and len(p2) > 0
print(f"Phase 2 prompt: {len(p2)} chars OK")
```

- [ ] **Step 3: Commit if any fixes needed, otherwise done**

```bash
echo "Verification complete"
```
