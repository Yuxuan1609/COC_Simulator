# Step 3 重构 + Step 3.5 依赖图 + Step 4 扩展 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆分臃肿的 Step 3a 为 Step 3a(轻量去重+冲突) + Step 3.5(依赖图+循环检测) + Step 4(统一标准化+side_effect 结构化)

**Architecture:** Step 3a 精简为 5 个任务；新增 Step 3.5（LLM 解析 requirement → 有向图 → 循环检测 + fallback）；Step 4 扩展（加 stat 标准化 + side_effect 结构化）。Step 3.5 和 Step 4 并行。

**Tech Stack:** Python 3.12+, dataclasses, DFS cycle detection, ThreadPoolExecutor

---

### Task 1: Create dependency_graph.py — DependencyGraph + DependencyEdge + DependencyNode

**Files:**
- Create: `src/module_designer/dependency_graph.py`
- Create: `src/module_designer/__init__.py` (update imports)
- Test: `tests/test_dependency_graph.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dependency_graph.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from module_designer.dependency_graph import DependencyGraph, DependencyEdge, DependencyNode


def test_build_graph_from_dependencies():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
        {"entity_id": "E1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    assert "I1" in graph.nodes
    assert "I3" in graph.nodes
    assert "E1" in graph.nodes
    assert len(graph.edges) == 2  # I3→I1, E1→I3


def test_no_cycle():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) == 0


def test_detect_simple_cycle():
    deps = [
        {"entity_id": "I1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) > 0


def test_cut_edge_breaks_cycle():
    deps = [
        {"entity_id": "I1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) > 0
    # Cut one edge
    cut_edge = graph.edges[0]
    graph.cut_edge(cut_edge)
    cycles_after = graph.detect_cycles()
    assert len(cycles_after) == 0
    assert graph._circular_cut is True


def test_to_dict_and_from_dict():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    d = graph.to_dict()
    restored = DependencyGraph.from_dict(d)
    assert set(restored.nodes.keys()) == set(graph.nodes.keys())
    assert len(restored.edges) == len(graph.edges)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dependency_graph.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write dependency_graph.py**

```python
"""依赖图 —— 管理 interaction/event/auto_trigger 之间的 requirement 依赖关系."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import random


@dataclass
class DependencyNode:
    entity_id: str
    entity_type: str = ""  # interaction / event / auto_trigger
    name: str = ""

    def to_dict(self) -> dict:
        return {"entity_id": self.entity_id, "entity_type": self.entity_type, "name": self.name}

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyNode":
        return cls(entity_id=data["entity_id"], entity_type=data.get("entity_type", ""),
                   name=data.get("name", ""))


@dataclass
class DependencyEdge:
    source: str     # 依赖方（需要满足条件才能触发）
    target: str     # 被依赖方
    dep_type: str = ""       # interaction / event / auto_trigger / item
    condition: str = ""      # completed / triggered / possess / not_*

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "dep_type": self.dep_type, "condition": self.condition}

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyEdge":
        return cls(source=data["source"], target=data["target"],
                   dep_type=data.get("dep_type", ""), condition=data.get("condition", ""))


class DependencyGraph:
    def __init__(self):
        self.nodes: dict[str, DependencyNode] = {}
        self.edges: List[DependencyEdge] = []
        self._circular_cut: bool = False
        self._cut_info: Optional[dict] = None

    def build(self, dependencies: list[dict]) -> None:
        for dep in dependencies:
            eid = dep["entity_id"]
            # Determine type from ID prefix
            etype = ""
            if eid.startswith("I"):
                etype = "interaction"
            elif eid.startswith("AT"):
                etype = "auto_trigger"
            elif eid.startswith("E"):
                etype = "event"
            self.nodes[eid] = DependencyNode(entity_id=eid, entity_type=etype)

            for req in dep.get("requires", []):
                edge = DependencyEdge(
                    source=eid,
                    target=req.get("id", req.get("name", "")),
                    dep_type=req.get("type", ""),
                    condition=req.get("condition", ""),
                )
                self.edges.append(edge)
                # Ensure target node exists
                target_id = edge.target
                if target_id not in self.nodes:
                    self.nodes[target_id] = DependencyNode(entity_id=target_id,
                        entity_type="item" if edge.dep_type == "item" else "")

    def detect_cycles(self) -> list[list[str]]:
        """DFS 检测所有循环。返回循环路径列表，每条路径是 entity_id 列表."""
        cycles = []
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {nid: WHITE for nid in self.nodes}
        parent = {}

        def dfs(u):
            color[u] = GRAY
            for edge in self.edges:
                if edge.source == u:
                    v = edge.target
                    if v not in color:
                        color[v] = WHITE
                    if color.get(v) == GRAY:
                        # Found cycle — reconstruct path
                        path = [v, u]
                        cur = u
                        while cur in parent and parent[cur] != v:
                            cur = parent[cur]
                            path.append(cur)
                        path.append(v)
                        cycles.append(list(reversed(path)))
                    elif color.get(v) == WHITE:
                        parent[v] = u
                        dfs(v)
            color[u] = BLACK

        for nid in list(self.nodes.keys()):
            if color.get(nid) == WHITE:
                dfs(nid)
        return cycles

    def cut_edge(self, edge: DependencyEdge) -> None:
        """随机切断一条参与循环的边."""
        self.edges = [e for e in self.edges if e is not edge]
        self._circular_cut = True
        self._cut_info = {"source": edge.source, "target": edge.target,
                          "dep_type": edge.dep_type, "condition": edge.condition}

    def cut_random_edge_in_cycles(self) -> bool:
        """检测循环，随机切断一条参与循环的边。返回是否切断了边."""
        cycles = self.detect_cycles()
        if not cycles:
            return False
        # Collect all edges involved in cycles
        cycle_edges = set()
        for path in cycles:
            for i in range(len(path) - 1):
                for e in self.edges:
                    if e.source == path[i + 1] and e.target == path[i]:
                        cycle_edges.add(e)
        if cycle_edges:
            self.cut_edge(random.choice(list(cycle_edges)))
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "_circular_cut": self._circular_cut,
            "_cut_info": self._cut_info,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyGraph":
        g = cls()
        g.nodes = {nid: DependencyNode.from_dict(nd) for nid, nd in data.get("nodes", {}).items()}
        g.edges = [DependencyEdge.from_dict(ed) for ed in data.get("edges", [])]
        g._circular_cut = data.get("_circular_cut", False)
        g._cut_info = data.get("_cut_info")
        return g
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dependency_graph.py -v`
Expected: 5 passed

- [ ] **Step 5: Update __init__.py exports**

Add to `src/module_designer/__init__.py`:
```python
from module_designer.dependency_graph import (
    DependencyGraph, DependencyNode, DependencyEdge,
)
```

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/dependency_graph.py src/module_designer/__init__.py tests/test_dependency_graph.py
git commit -m "feat: add DependencyGraph for cycle detection and requirement management"
```

---

### Task 2: Rewrite Step 3a prompt — slim to 5 tasks

**Files:**
- Modify: `src/module_designer/layered_parser.py:618-694`

- [ ] **Step 1: Replace STEP3A_SYSTEM**

```python
STEP3A_SYSTEM = """你是一个 TRPG 逻辑验证助手，专门做模组信息的去重和冲突解决。
你的任务是：检查所有 interaction/event/auto_trigger，基于 based_on 去重，验证 graded_result，修剪 result/side_effects 重合，解决冲突，验证结局标记。

重要原则：
- based_on 已标注派生关系。若两个 entity 的 based_on 指向同一 interaction 且语义重复（name/result 高度相似），合并为一个
- graded_result 在 type != "无" 时建议填写但不强制；type == "无" 时删除空 graded_result
- result 和 side_effects 信息重合时修剪一方。result 为 "##GRADED##" 时跳过此检查
- requirement/trigger 冲突以 condensed_text 为准修正
- ##END_## 标记与 L3 ending_conditions 相互补齐
- 不删改实质信息，只修正名称和引用
- 互动完成即代表状态变更，不需要单独的 flag
- 仅输出 JSON，不要任何解释性文字"""

def build_step3a_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
) -> str:
    return f"""对以下模组中的所有 L2 内容做去重、冲突解决和结局验证。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## L3 结局条件（用于验证 ##END_## 标记）
{json.dumps(ending_conditions, ensure_ascii=False, indent=2)}

## Interactions
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Events（based_on 指向派生的 interaction，无 scene）
{json.dumps(events, ensure_ascii=False, indent=2)}

## Auto-triggers（based_on 指向派生的 interaction，有 scene）
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. **Based_on 去重**: 若两个 entity 的 based_on 指向同一 interaction 且 name/result 语义高度相似，合并为一个（保留较完整的版本，删除重复的）。
2. **Graded_result 检查**: type != "无" 时建议填写 graded_result 但不强制；type == "无" 时删除空 graded_result。
3. **Result / Side_effects 去重**: 若 result 为 "##GRADED##" 跳过此检查。否则若 side_effects 中的某条内容已在 result 中体现，移除该条。
4. **冲突解决**: requirement/trigger 矛盾以 condensed_text 为准修正。
5. **结局标记验证**: 扫描 ##END_## 标记与 L3 ending_conditions 做语义匹配。标记缺失则相互补齐。

输出格式:
{{
  "interactions": [{{ ...原字段... }}],
  "events": [{{ ...原字段... }}],
  "auto_triggers": [{{ ...原字段... }}]
}}

仅输出 JSON。"""
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: 49 passed (44 old + 5 new from Task 1)

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "refactor: slim Step 3a to 5 tasks — dedup, graded_result, result/side_effects, conflict, endings"
```

---

### Task 3: Add Step 3.5 prompt + parser — requirement standardization

**Files:**
- Modify: `src/module_designer/layered_parser.py` (add after Step 3b section)

- [ ] **Step 1: Add STEP35_SYSTEM, build_step35_prompt, parse_step35**

Insert after the Step 3b section (before Step 4):

```python
# ═══════════════════════════════════════════════════════════════
#  Step 3.5: 依赖图构建
# ═══════════════════════════════════════════════════════════════

STEP35_SYSTEM = """你是一个 TRPG 依赖关系解析助手。
你的任务是：检查所有 interaction/event/auto_trigger 的 requirement 和 trigger 字段，将其中描述的依赖关系标准化为结构化 JSON。

重要原则：
- 从 requirement 和 trigger 的自然语言中提取依赖关系
- requirement 中的 "interaction:I3 已完成" → {{"type": "interaction", "id": "I3", "condition": "completed"}}
- requirement 中的 "持有手电筒" → {{"type": "item", "name": "手电筒", "condition": "possess"}}
- trigger 中的 "E1 已触发" → {{"type": "event", "id": "E1", "condition": "triggered"}}
- 每条 entity 的 requires 列出所有提取到的依赖（可为空列表）
- 仅输出 JSON，不要任何解释性文字"""


def build_step35_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
) -> str:
    interaction_list = json.dumps(interactions, ensure_ascii=False, indent=2)
    events_list = json.dumps(events, ensure_ascii=False, indent=2)
    at_list = json.dumps(auto_triggers, ensure_ascii=False, indent=2)
    return f"""从以下 L2 实体的 requirement 和 trigger 字段中提取并标准化所有依赖关系。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions
{interaction_list}

## Events
{events_list}

## Auto-triggers
{at_list}

任务:
1. 扫描每个 entity 的 requirement 和 trigger 字段
2. 提取其中描述的依赖关系，标准化为:
   - interaction 依赖: {{"type": "interaction", "id": "I3", "condition": "completed"}} 或 "not_completed"
   - event 依赖: {{"type": "event", "id": "E1", "condition": "triggered"}} 或 "not_triggered"
   - auto_trigger 依赖: {{"type": "auto_trigger", "id": "AT1", "condition": "triggered"}}
   - item 依赖: {{"type": "item", "name": "手电筒", "condition": "possess"}} 或 "not_possess"
3. 每条 entity 必须在输出中列出，requires 为空列表表示无依赖
4. 实体 ID 必须精确匹配（如 I3 不能写成 I03）

输出格式:
{{
  "dependencies": [
    {{
      "entity_id": "I1",
      "requires": []
    }},
    {{
      "entity_id": "I3",
      "requires": [
        {{"type": "interaction", "id": "I1", "condition": "completed"}}
      ]
    }}
  ]
}}

仅输出 JSON。"""


def parse_step35(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    llm_call,
) -> dict:
    prompt = build_step35_prompt(condensed_text, interactions, events, auto_triggers)
    return llm_call(prompt, system=STEP35_SYSTEM)
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: 49 passed

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: add Step 3.5 prompt — requirement standardization for DependencyGraph"
```

---

### Task 4: Update Step 4 prompt — add stat standardization + side_effect structuring

**Files:**
- Modify: `src/module_designer/layered_parser.py:773-856`

- [ ] **Step 1: Replace STEP4_SYSTEM and build_step4_prompt**

```python
STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：根据模组内容和场景需求，统一做所有标准化处理：enemy_ref/weapon_ref 匹配、技能名/属性名标准化、side_effect 结构化。

重要原则：
- 必须从提供的库列表中选择，不允许自创名称
- 若无合适的库条目，填 "none"
- 技能名必须从标准技能列表中选择
- 属性名必须从标准属性列表中选择
- side_effect 从自然语言解析为结构化对象
- 仅输出 JSON，不要任何解释性文字"""


def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
    stat_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    stats_list = "\n".join(f"- {s}" for s in stat_names)
    desc_list = "\n".join(f"- {sid}: {desc}" for sid, desc in l2_descriptions.items())
    return f"""标准化 enemy_ref/weapon_ref/type/stat_name，并结构化 side_effects。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

## 标准属性列表（stat_change 的 stat_name 必须从此列表中选择）
{stats_list}

## 场景描述
{desc_list}

## L3 Scene Intents
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions (含空占位符)
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Auto-triggers (含空占位符)
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. 为每个 enemy_ref 从可用敌人库中选择匹配项。无匹配填 "none"。event 跳过。
2. 为每个 weapon_ref 从可用武器库中选择匹配项。无匹配填 "none"。event 跳过。
3. 为每个 type 从标准技能列表中选择最匹配的技能名。不涉及检定的 type 保持"无"。
4. **Side_effect 结构化**: 将 side_effects 从自然语言字符串解析为结构化对象:
   - item_gain: {{"type": "item_gain", "item_name": "物品名"}}
   - stat_change: {{"type": "stat_change", "stat_name": "属性名", "delta": -1, "narrative": "角色经历（可选）"}}
   - spawn_enemy: {{"type": "spawn_enemy", "enemy_ref": "敌人名", "scene": "场景ID", "trigger_condition": "...", "quantity": 1}}
   - grant_item: {{"type": "grant_item", "item_ref": "武器/物品名", "scene": "场景ID"}}
   - npc_state_change: {{"type": "npc_state_change", "npc_name": "NPC名", "new_state": "新状态"}}
   无法归入以上类型的保留字符串。
5. stat_change 的 stat_name 必须从标准属性列表中选择。narrative 字段可选。
6. 不允许自创名称。

输出格式:
{{
  "interactions": [{{ ...原字段..., "enemy_ref": "...", "weapon_ref": "...", "type": "标准技能名", "side_effects": [结构化对象或字符串] }}],
  "auto_triggers": [{{ ...原字段..., "enemy_ref": "...", "weapon_ref": "...", "type": "标准技能名", "side_effects": [结构化对象或字符串] }}]
}}

仅输出 JSON。"""


def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
    stat_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, condensed_text,
        weapon_library_names, enemy_library_names, skill_names, stat_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: some tests may fail due to signature change — will fix in Task 6

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: extend Step 4 — add stat standardization + side_effect structuring"
```

---

### Task 5: Update layered_pipeline.py — wire Step 3a/3.5/4

**Files:**
- Modify: `src/module_designer/layered_pipeline.py:386-500`

- [ ] **Step 1: Replace Step 3a section — slim call**

Update the Step 3a call to match the new simplified version. The actual call is already correct (same parameters), just the log message changes:

```python
    if verbose:
        print(f"  Step 3a 完成: 去重 + 冲突解决 + 结局验证")
```

- [ ] **Step 2: Add Step 3.5 + Step 4 parallel block**

Replace the Step 4 section (from `# ── Step 4 ──` onward) with the parallel Step 3.5 + Step 4:

```python
    # ── Step 3.5 + Step 4 (并行) ──────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3.5 + Step 4] 依赖图构建 + Library 匹配 (并行)...")

    # 加载 stat_names
    stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    # Build name→id map for scene descriptions
    name_to_id = {s["name"]: s["id"] for s in scenes if s.get("name") and s.get("id")}
    l2_descriptions = {}
    for name, sdata in l1_data.items():
        sid = name_to_id.get(name, name)
        desc = sdata.get("description", "") or sdata.get("atmosphere", "") or sdata.get("entry_narrative", "")
        if desc:
            l2_descriptions[sid] = desc

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

    scene_intents_for_step4 = l3_data.get("scene_intents", {})

    from module_designer.dependency_graph import DependencyGraph

    def _do_step35():
        """Step 3.5: LLM 解析 → 有向图 → 循环检测."""
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            step35_result = parse_step35(condensed_text, interactions, events, auto_triggers, llm_json)
            deps = step35_result.get("dependencies", [])
            if not deps:
                if attempt < max_tries:
                    if verbose:
                        print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
                    continue
                return {"graph": None, "dependencies": deps, "_fallback_reason": "LLM 解析为空"}

            graph = DependencyGraph()
            graph.build(deps)
            cycles = graph.detect_cycles()
            if not cycles:
                if verbose:
                    print(f"  [Step 3.5] 依赖图构建完成: {len(graph.nodes)} 节点, {len(graph.edges)} 边, 无循环")
                return {"graph": graph, "dependencies": deps}

            if attempt < max_tries:
                if verbose:
                    cycle_ids = [p[0] for p in cycles[:3]]
                    print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环 ({cycle_ids}...)，重调 LLM...")
                continue

        # Fallback: cut random edge
        if verbose:
            print(f"  [Step 3.5] 重调用尽，切断一条循环边")
        graph.cut_random_edge_in_cycles()
        return {"graph": graph, "dependencies": deps, "_circular_cut": True}

    def _do_step4():
        return parse_step4(
            interactions, auto_triggers, l2_descriptions,
            scene_intents_for_step4, condensed_text,
            weapon_names, enemy_names, skill_names, stat_names, llm_json,
        )

    with ThreadPoolExecutor(max_workers=2) as ex:
        f35 = ex.submit(_do_step35)
        f4 = ex.submit(lambda: _with_fallback(
            _do_step4, ["interactions"],
            {"interactions": interactions, "auto_triggers": auto_triggers},
            max_retries, verbose, "Step 4",
        ) if (weapon_names or enemy_names or skill_names) else ex.submit(lambda: {"interactions": interactions, "auto_triggers": auto_triggers}))
        step35_result = f35.result()
        step4 = f4.result()

    interactions = step4.get("interactions", interactions)
    auto_triggers = step4.get("auto_triggers", auto_triggers)
    if step4.get("_fallback"):
        result.fallbacks.append("Step 4")

    # Store dependency graph
    dep_graph = step35_result.get("graph")
    result.l2_data["dependency_graph"] = dep_graph.to_dict() if dep_graph else None
    if step35_result.get("_circular_cut"):
        result.fallbacks.append("Step 3.5 (circular cut)")

    if verbose:
        nodes = len(dep_graph.nodes) if dep_graph else 0
        edges = len(dep_graph.edges) if dep_graph else 0
        print(f"  Step 3.5 完成: {nodes} 节点, {edges} 边")
        print(f"  Step 4 完成: enemy/weapon/skill/stat 标准化 + side_effect 结构化")
```

Note: The parallel block with `ThreadPoolExecutor` requires careful handling of the Step 4 skip condition. The above uses a conditional submit — when no libraries are available, Step 4 returns the input unchanged.

Actually, let me simplify: use `if weapon_names or enemy_names or skill_names:` check before the parallel block, with a fallback identity function for Step 4:

```python
    # Actually simpler — just always run Step 4, it can handle empty lists
    with ThreadPoolExecutor(max_workers=2) as ex:
        f35 = ex.submit(_do_step35)
        f4 = ex.submit(lambda: _with_fallback(
            _do_step4, ["interactions"],
            {"interactions": interactions, "auto_triggers": auto_triggers},
            max_retries, verbose, "Step 4",
        ))
        step35_result = f35.result()
        step4 = f4.result()
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: 49 passed (may fail due to signature changes — fix in Task 6)

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_pipeline.py
git commit -m "feat: wire Step 3.5 + Step 4 parallel in pipeline, add dependency graph construction"
```

---

### Task 6: Fix tests for new signatures

**Files:**
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Update test_build_step3a_prompt_structure**

```python
def test_build_step3a_prompt_structure():
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "requirement": "需要先找到线索", "side_effects": [], "result": "找到线索", "type": "无"}]
    events = [{"id": "E1", "name": "事件", "requirement": "interaction I1 完成后", "type": "无", "difficulty": "None", "based_on": "I1", "side_effects": [], "result": "..."}]
    auto_triggers = [{"id": "AT1", "name": "触发", "scene": "S1", "trigger": "玩家进入场景", "type": "无", "based_on": "I1", "side_effects": [], "result": "..."}]
    ending_conditions = [{"id": "END1", "condition": "...", "narrative": "真结局"}]
    prompt = build_step3a_prompt("精修模组", interactions, events, auto_triggers, ending_conditions)
    assert "I1" in prompt
    assert "E1" in prompt
    assert "AT1" in prompt
    assert "based_on" in prompt
    assert "去重" in prompt
    assert "graded_result" in prompt
```

- [ ] **Step 2: Add test_build_step35_prompt_structure**

```python
def test_build_step35_prompt_structure():
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "requirement": "需要先完成I3", "trigger": "", "result": "找到钥匙", "side_effects": []}]
    events = [{"id": "E1", "name": "事件", "requirement": "interaction I1 完成后", "trigger": ""}]
    auto_triggers = []
    prompt = build_step35_prompt("精修模组", interactions, events, auto_triggers)
    assert "精修模组" in prompt
    assert "dependencies" in prompt
    assert "entity_id" in prompt
    assert "requires" in prompt
    assert "I1" in prompt
    assert "E1" in prompt
```

- [ ] **Step 3: Update test_build_step4_prompt_structure — add stat_names**

Find the existing `test_build_step4_prompt_structure` and update to pass `stat_names`:

```python
def test_build_step4_prompt_structure():
    interactions = [{"id": "I1", "name": "测试", "scene": "S1", "enemy_ref": None, "weapon_ref": None, "type": "侦察", "result": "", "side_effects": ["获得手枪"], "requirement": "", "trigger": "", "difficulty": "regular", "based_on": ""}]
    auto_triggers = [{"id": "AT1", "name": "测试", "scene": "S1", "enemy_ref": None, "weapon_ref": None, "type": "无", "result": "", "side_effects": [], "requirement": "", "trigger": "", "difficulty": "regular", "based_on": "I1"}]
    prompt = build_step4_prompt(
        interactions, auto_triggers,
        {"S1": "测试描述"}, {}, "精修内容",
        ["sword"], ["ghost"], ["侦察", "急救"],
        ["STR", "SAN", "HP"],
    )
    assert "sword" in prompt
    assert "ghost" in prompt
    assert "侦察" in prompt
    assert "STR" in prompt
    assert "side_effect" in prompt.lower() or "结构化" in prompt
```

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -x -q`
Expected: 51 passed (44 old + 5 dependency_graph + 2 new step35)

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: update tests for Step 3a/3.5/4 new signatures and behavior"
```

---

### Task 7: Update notebooks — parser_test.ipynb + _parser_layered_export.py

**Files:**
- Modify: `notebooks/parser_test.ipynb`
- Modify: `notebooks/_parser_layered_export.py`

- [ ] **Step 1: Update parser_test.ipynb Step 3a cell**

NotebookEdit cell `16a85bc89692e7fb`:

```python
# ═══ Step 3a: L2 去重 + 冲突解决 + 结局验证 ═══
ending_conditions = l3_data.get("ending_conditions", [])
step3a = do_json_call(
    "step_3", "3a_dedup_conflict",
    build_step3a_prompt,
    condensed_text, interactions, events, auto_triggers, ending_conditions,
    system_prompt=STEP3A_SYSTEM
)
interactions = step3a.get("interactions", interactions)
events = step3a.get("events", events)
auto_triggers = step3a.get("auto_triggers", auto_triggers)
print(f"Step 3a 完成: 去重 + 冲突 + 结局")
print(f"  Interactions: {len(interactions)}, Events: {len(events)}, Auto-triggers: {len(auto_triggers)}")
```

- [ ] **Step 2: Update Step 4 cell to run Step 3.5 + Step 4 in parallel**

Replace the existing Step 4 cell (`3e36fe38dd5e9a4a`) — Step 3.5 runs in the same cell in parallel with Step 4:

```python
# ═══ Step 3.5 + Step 4: 依赖图 + Library 匹配 (并行) ═══
weapon_names = [w.name for w in wl.list_all()]
enemy_names = [e.name for e in el.list_all()]

# 标准属性
stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

# 加载标准技能名
import json as _json
import os as _os
try:
    skill_path = _os.path.join("..", "data", "skill_checks.json")
    with open(skill_path, "r", encoding="utf-8") as _f:
        skill_checks = _json.load(_f)
        skill_names = sorted(set(s["name"] for s in skill_checks))
except Exception:
    skill_names = []

# 构建场景描述
name_to_id = {s["name"]: s["id"] for s in scenes if s.get("name") and s.get("id")}
l2_descriptions = {}
for name, sdata in l1_data.items():
    sid = name_to_id.get(name, name)
    desc = sdata.get("description", "") or sdata.get("atmosphere", "")
    if desc:
        l2_descriptions[sid] = desc

scene_intents_for_s4 = l3_data.get("scene_intents", {})

from module_designer.dependency_graph import DependencyGraph

# ── Step 3.5: 依赖图 ──
MAX_TRIES = 3
dep_graph = None
for attempt in range(1, MAX_TRIES + 1):
    step35 = do_json_call(
        "step_35", "35_dependency_graph",
        build_step35_prompt,
        condensed_text, interactions, events, auto_triggers,
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
        print(f"  [Step 3.5] 重调用尽，随机切断循环边 (cut_info={dep_graph._cut_info})")

# ── Step 4: Library 匹配 + 标准化 ──
step4 = do_json_call(
    "step_4", "4_library_matching",
    build_step4_prompt,
    interactions, auto_triggers, l2_descriptions,
    scene_intents_for_s4, condensed_text,
    weapon_names, enemy_names, skill_names, stat_names,
    system_prompt=STEP4_SYSTEM
)
interactions = step4.get("interactions", interactions)
auto_triggers = step4.get("auto_triggers", auto_triggers)
print(f"Step 4 完成: enemy/weapon/skill/stat 标准化 + side_effect 结构化")
```

- [ ] **Step 3: Same changes for _parser_layered_export.py**

Update the Step 3a section (line ~326) and Step 4 section (line ~375) with the same changes.

- [ ] **Step 4: Run all tests**

Run: `python -m pytest tests/ -x -q`
Expected: 51 passed

- [ ] **Step 5: Commit**

```bash
git add notebooks/parser_test.ipynb notebooks/_parser_layered_export.py
git commit -m "feat: update notebooks for Step 3a/3.5/4 refactor"
```

---

### Task 8: Final verification

**Files:**
- Verify: all modified files

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Verify imports**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from module_designer.dependency_graph import DependencyGraph, DependencyNode, DependencyEdge
from module_designer.layered_parser import (
    build_step3a_prompt, build_step35_prompt, build_step4_prompt,
    STEP3A_SYSTEM, STEP35_SYSTEM, STEP4_SYSTEM,
    parse_step35, parse_step4,
)

# Step 3a: dedup tasks, no side_effect structuring
prompt = build_step3a_prompt('ctx', [], [], [], [])
assert '去重' in prompt
assert '结构化' not in prompt  # side_effect structuring removed
print('Step 3a OK')

# Step 3.5: dependency extraction
prompt = build_step35_prompt('ctx', [], [], [])
assert 'dependencies' in prompt
assert 'require' in prompt.lower()
print('Step 3.5 OK')

# Step 4: stat standardization + side_effect structuring
prompt = build_step4_prompt([], [], {}, {}, '', [], [], [], ['STR', 'SAN'])
assert 'STR' in prompt
assert '结构化' in prompt or 'side_effect' in prompt.lower()
print('Step 4 OK')

# DependencyGraph
g = DependencyGraph()
g.build([{'entity_id': 'I1', 'requires': []}])
assert len(g.nodes) == 1
assert g.detect_cycles() == []
print('DependencyGraph OK')

print('ALL INTEGRATION CHECKS PASSED')
"
```

- [ ] **Step 3: Commit if any fixes needed**

- [ ] **Step 4: Final commit (if no changes, skip)**

```bash
git add -A
git commit -m "chore: final verification — all tests pass, integration checks green"
```
