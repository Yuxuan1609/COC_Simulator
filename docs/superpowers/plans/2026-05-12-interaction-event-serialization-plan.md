# 交互结果丰富化 + 事件触发混合模式 + 世界可序列化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `ActionResult` 统一交互和事件的返回类型，增加声明式副作用消费；为事件触发增加引擎二次确认；实现全量存档/读档。

**Architecture:** 新数据类 `ActionResult` / `FlagSet` / `ItemGain` / `StatChange` 放在 `scenario_core.py`，由 `execute_interaction` 和 `trigger_event` 返回。`game_loop.py` 新增 `_apply_side_effects()` 消费副作用，事件阶段增加 `RequirementResolver` 二次确认。`ScenarioWorld` / `DirectedGraph` / `MemoryManager` 各加 `to_dict()` / `from_dict()`，`save_state()` / `load_state()` 做全量快照。

**Tech Stack:** Python dataclasses, JSON, 纯模块无外部依赖

---

### Task 1: 新增数据类 `ActionResult` 及其关联类型

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 在 `Interaction` dataclass 后添加新数据类**

在 `Interaction` 类定义之后（约第 58 行）、`GameEvent` 之前，插入以下代码：

```python
@dataclass
class FlagSet:
    """设置世界标记"""
    key: str
    value: bool = True


@dataclass
class ItemGain:
    """获得关键物品"""
    item_name: str


@dataclass
class StatChange:
    """
    属性变化（预留）
    - COC 规则下的 SAN/HP 变化涉及检定与鉴定大成功/失败规则
    - 当前仅做结构化记录，不自动修改 Investigator 状态
    """
    stat_name: str
    delta: int       # 正=回复，负=损失


@dataclass
class ActionResult:
    """交互/事件执行的统一返回类型"""
    success: bool
    message: str
    side_effects: list = field(default_factory=list)     # JSON 声明的确定性副作用
    suggested_flags: list = field(default_factory=list)   # LLM 建议（预留，本轮不实现）
```

- [ ] **Step 2: 在 `Interaction` 类添加 `side_effects` 字段**

修改 `Interaction` 类（第 47-57 行），在 `requirements` 行之后、`clue` 行之后加 `side_effects`：

```python
@dataclass
class Interaction:
    """场景中可执行的动作（调查、鉴定、对话、决策等）"""
    type: str
    name: str
    trigger: str
    result: str
    clue: Optional[str] = None
    requirements: List[Requirement] = field(default_factory=list)
    side_effects: list = field(default_factory=list)   # FlagSet | ItemGain | StatChange

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"
```

- [ ] **Step 3: 添加 side_effect 解析/序列化工具函数**

在 `ActionResult` 类之后，添加两个模块级工具函数：

```python
def _parse_side_effect(data: dict):
    """从 dict 解析单个 side effect"""
    type_ = data.get("type", "")
    if type_ == "flag_set":
        return FlagSet(key=data["key"], value=data.get("value", True))
    elif type_ == "item_gain":
        return ItemGain(item_name=data["item_name"])
    elif type_ == "stat_change":
        return StatChange(stat_name=data["stat_name"], delta=data.get("delta", 0))
    return None


def _parse_side_effects(data: list) -> list:
    """从 list[dict] 解析 side effects"""
    result = []
    for d in data:
        parsed = _parse_side_effect(d)
        if parsed is not None:
            result.append(parsed)
    return result


def _side_effect_to_dict(effect) -> dict:
    """将 side effect 实例序列化为 dict"""
    if isinstance(effect, FlagSet):
        return {"type": "flag_set", "key": effect.key, "value": effect.value}
    elif isinstance(effect, ItemGain):
        return {"type": "item_gain", "item_name": effect.item_name}
    elif isinstance(effect, StatChange):
        return {"type": "stat_change", "stat_name": effect.stat_name, "delta": effect.delta}
    return {}
```

- [ ] **Step 4: 验证导入**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "from src.scenario_core import FlagSet, ItemGain, StatChange, ActionResult; a = ActionResult(True, 'test'); print(a)"
```

Expected: `ActionResult(success=True, message='test', side_effects=[], suggested_flags=[])`

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add ActionResult, FlagSet, ItemGain, StatChange data classes"
```

---

### Task 2: 适配 `execute_interaction` 和 `trigger_event` 返回 `ActionResult`

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 修改 `execute_interaction` 返回类型**

修改 `execute_interaction` 方法（第 438-461 行），将 `Tuple[bool, str]` 改为 `ActionResult`：

```python
def execute_interaction(self, name: str) -> ActionResult:
    """
    执行当前场景的指定动作。检查前置条件，标记完成并返回结果文本。
    不检查事件 —— 事件触发由外部 LLM 调用链独立处理。
    """
    node = self._current_node()
    if not node:
        return ActionResult(False, "当前场景不存在。")
    interaction = node.get_interaction(name)
    if not interaction:
        available = ', '.join(i.name for i in node.interactions)
        return ActionResult(False, f"当前场景没有动作「{name}」。可用动作：{available or '无'}")

    # 检查前置条件
    if interaction.requirements:
        ok, msg = self.requirement_resolver.check(interaction.requirements)
        if not ok:
            return ActionResult(False, msg)

    loc = self.current_location
    if loc not in self.completed_interactions:
        self.completed_interactions[loc] = set()
    self.completed_interactions[loc].add(name)
    return ActionResult(
        True,
        f"【{interaction.type}】{interaction.name}：{interaction.result}",
        side_effects=list(interaction.side_effects),
    )
```

- [ ] **Step 2: 修改 `trigger_event` 返回类型**

修改 `trigger_event` 方法（第 465-479 行），将 `Tuple[bool, str]` 改为 `ActionResult`：

```python
def trigger_event(self, event_id: str) -> ActionResult:
    event = self.graph.get_event(event_id)
    if not event:
        return ActionResult(False, f"未知事件：{event_id}")
    if self.triggered_events.get(event_id, False):
        return ActionResult(False, f"事件「{event.name}」已经触发过。")

    # 检查前置条件
    if event.requirements:
        ok, msg = self.requirement_resolver.check(event.requirements)
        if not ok:
            return ActionResult(False, msg)

    self.triggered_events[event_id] = True
    return ActionResult(True, f"【事件触发】{event.name}\n{event.impact}")
```

- [ ] **Step 3: 修改 `move` 方法返回类型**

`move` 也返回 `Tuple[bool, str]`，为保持统一，改为 `ActionResult`（第 426-434 行）：

```python
def move(self, target: str) -> ActionResult:
    if self.player is None:
        return ActionResult(False, "尚未设置角色")
    possible = {e.target: e for e in self.get_possible_exits()}
    if target not in possible:
        available = ', '.join(e.target for e in self.get_possible_exits())
        return ActionResult(False, f"无法从{self.current_location}前往{target}。可前往：{available or '无'}")
    self.current_location = target
    return ActionResult(True, f"你来到了{target}。{self.get_current_description()}")
```

- [ ] **Step 4: 验证 - 测试新返回类型**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
from src.scenario_core import ActionResult, FlagSet, ItemGain, read_json_file, DirectedGraph, ScenarioWorld
# 快速集成测试
graph = DirectedGraph()
world = ScenarioWorld(graph, 'test')
# move 返回 ActionResult
r = world.move('anywhere')
print(f'move: success={r.success}, msg={r.message}')
# execute_interaction 返回 ActionResult
r = world.execute_interaction('nonexistent')
print(f'interact: success={r.success}, msg={r.message}')
"
```

Expected: 两行输出都是 `success=False`

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py
git commit -m "refactor: return ActionResult from execute_interaction, trigger_event, and move"
```

---

### Task 3: 适配 `game_loop.py` — `_apply_side_effects` + 事件引擎二次确认

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: 更新 import**

修改 `src/game_loop.py` 顶部 import（第 8-10 行），增加新类型引用：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld
from llm import call_deepseek
from prompts import (
    build_action_prompt,
    build_event_prompt,
    build_action_world_update,
    build_event_world_update,
    build_narrative_prompt,
    build_improvise_prompt,
    log_skill_result,
    parse_narrative_output,
)
from scenario_core import FlagSet, ItemGain, StatChange  # 新增
```

- [ ] **Step 2: 新增 `_apply_side_effects` 函数**

在 `_execute_single_action` 函数之前（约第 24 行前）插入：

```python
def _apply_side_effects(world: ScenarioWorld, side_effects: list) -> list:
    """
    消费 side effects。当前实现：
    - FlagSet → world.set_flag
    - ItemGain → world.memory.note_item
    - StatChange → 仅记录不修改状态（COC SAN 规则待后续细化）
    
    返回人类可读的副作用摘要列表。
    """
    msgs = []
    for effect in side_effects:
        if isinstance(effect, FlagSet):
            world.set_flag(effect.key, effect.value)
            msgs.append(f"[标记] {effect.key} = {effect.value}")
        elif isinstance(effect, ItemGain):
            world.memory.note_item(effect.item_name)
            msgs.append(f"[获得物品] {effect.item_name}")
        elif isinstance(effect, StatChange):
            msgs.append(f"[属性变化] {effect.stat_name} {'+' if effect.delta > 0 else ''}{effect.delta}（未自动应用）")
    return msgs
```

- [ ] **Step 3: 适配 `_execute_single_action` 返回类型**

修改 `_execute_single_action`（第 25-55 行），将返回值从 `tuple` 改为 `tuple[ActionResult, bool]`：

```python
def _execute_single_action(act: dict, world: ScenarioWorld, location: str) -> tuple:
    """执行单个动作，返回 (ActionResult, any_executed: bool)"""
    action = act.get("action", "other")

    if action == "move":
        target = act.get("target", "")
        if not target:
            return ActionResult(False, "（试图移动但未指定目标）"), False
        result = world.move(target)
        return result, result.success

    elif action == "interact":
        name = act.get("interaction", "")
        if not name:
            return ActionResult(False, "（试图执行动作但未指定名称）"), False
        result = world.execute_interaction(name)
        return result, result.success

    elif action == "search":
        interactions = world.get_available_interactions()
        done = world.completed_interactions.get(location, set())
        available = [i for i in interactions if i.name not in done]
        if available:
            lines = ["（环顾四周，注意到可以做的事：）"]
            for inter in available:
                lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
            return ActionResult(True, "\n".join(lines)), True
        else:
            return ActionResult(True, "（仔细查看四周，没有特别的发现）"), True
    else:
        return ActionResult(True, "（什么也没做）"), True
```

需要添加 import `ActionResult`：

在 `from scenario_core import FlagSet, ItemGain, StatChange` 行中加入 `ActionResult`：

```python
from scenario_core import FlagSet, ItemGain, StatChange, ActionResult
```

- [ ] **Step 4: 适配 `handle_user_input` 消费逻辑**

修改 `handle_user_input` 中阶段1a（原第 103-121 行），适配 `ActionResult` 并消费 `side_effects`：

```python
    action_results = []
    any_scene_executed = False

    for act in scene_actions:
        condition = act.get("condition", "")
        if condition:
            action_results.append(f"（无法执行：{condition}）")
            continue

        skill_checks = act.get("skill_checks", [])
        if skill_checks and world.player:
            all_pass, skill_result = world.player.check_skills(skill_checks)
            log_skill_result(skill_result)
            if not all_pass:
                action_results.append(skill_result)
                continue

        # 闸门通过，执行动作
        result, executed = _execute_single_action(act, world, location)
        action_results.append(result.message)
        if executed:
            any_scene_executed = True
            # 消费声明式副作用
            side_msgs = _apply_side_effects(world, result.side_effects)
            action_results.extend(side_msgs)
```

修改阶段1b（原第 136-138 行）：

```python
    # ═══ 阶段1b：执行 move 动作 ═══
    for act in move_actions:
        result, _ = _execute_single_action(act, world, location)
        action_results.append(result.message)
```

- [ ] **Step 5: 事件阶段增加引擎二次确认**

修改阶段2（原第 142-156 行），对 LLM 返回的每条 `triggered_event` 做 `RequirementResolver` 二次确认：

```python
    # ═══ 阶段2：执行事件 ═══
    events_result = ""
    any_event_triggered = False
    for eid in event_data.get("triggered_events", []):
        # 引擎二次确认：条件是否真的满足
        event = world.graph.get_event(eid)
        if event and event.requirements:
            met, reason = world.requirement_resolver.check(event.requirements)
            if not met:
                events_result += f"（事件「{eid}」条件不满足：{reason}）\n"
                continue
        result = world.trigger_event(eid)
        if result.success:
            events_result += result.message + "\n"
            any_event_triggered = True
            side_msgs = _apply_side_effects(world, result.side_effects)
            events_result += "\n".join(side_msgs)
        else:
            events_result += f"（事件「{eid}」触发失败：{result.message}）\n"
    for eid, condition_text in event_data.get("condition_events", {}).items():
        events_result += f"（无法触发事件「{eid}」：{condition_text}）\n"
    for flag_key, flag_val in event_data.get("new_flags", {}).items():
        world.set_flag(flag_key, flag_val)
        events_result += f"[标记更新] {flag_key} = {flag_val}\n"
```

- [ ] **Step 6: 验证 — import + 基本逻辑检查**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "from src.game_loop import _apply_side_effects; from src.scenario_core import FlagSet, ItemGain; print('imports OK')"
```

- [ ] **Step 7: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: add _apply_side_effects, adapt to ActionResult, add event gate confirmation"
```

---

### Task 4: 适配 `pipeline.py` — 解析 `side_effects` 字段

**Files:**
- Modify: `src/pipeline.py`

- [ ] **Step 1: 在 `DirectedGraph.load_scenes` 中解析 `side_effects`**

修改 `load_scenes` 方法（`scenario_core.py` 第 106-143 行），在 `Interaction` 构造中加入 `side_effects` 解析：

```python
    def load_scenes(self, data: dict):
        """从 scene_output_resolved_revised.json 格式的字典加载场景"""
        for node_id, node_info in data.items():
            interactions = [
                Interaction(
                    type=inter["type"],
                    name=inter["name"],
                    trigger=inter.get("trigger", ""),
                    result=inter.get("result", ""),
                    clue=inter.get("clue"),
                    requirements=[
                        Requirement(
                            ref_type=req.get("ref_type", ""),
                            ref_scene=req.get("ref_scene", ""),
                            ref_name=req.get("ref_name", ""),
                        )
                        for req in inter.get("requirement", [])
                    ],
                    side_effects=_parse_side_effects(inter.get("side_effects", [])),
                )
                for inter in node_info.get("interactions", [])
            ]
            # ... remainder unchanged
```

- [ ] **Step 2: 验证 — 确认空 side_effects 解析不报错**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
from src.scenario_core import DirectedGraph, read_json_file
data = read_json_file('data/output/scene_output_resolved_revised.json')
graph = DirectedGraph(data)
node = graph.nodes.get('6号车厢')
if node:
    for i in node.interactions:
        print(f'{i.name}: side_effects={len(i.side_effects)}')
print('OK')
"
```

Expected: 所有 interaction 的 `side_effects=0`

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: parse side_effects field in Interaction construction"
```

---

### Task 5: 世界状态序列化 — `to_dict` / `from_dict` / `save_state` / `load_state`

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: `MemoryManager.to_dict()` 和 `MemoryManager.from_dict()`**

在 `MemoryManager` 类中（`scenario_core.py`），添加两个方法。在 `get_context` 方法之后（第 624 行附近）：

```python
    def to_dict(self) -> dict:
        return {
            "raw_history": self.raw_history,
            "summary": self.summary,
            "visited": self.visited,
            "key_items": self.key_items,
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryManager":
        mm = cls(max_raw=data.get("max_raw", 5))
        mm.raw_history = data.get("raw_history", [])
        mm.summary = data.get("summary", "")
        mm.visited = data.get("visited", [])
        mm.key_items = data.get("key_items", [])
        mm.turn = data.get("turn", 0)
        return mm
```

- [ ] **Step 2: `DirectedGraph.to_dict()` 和 `DirectedGraph.from_dict()`**

在 `DirectedGraph` 类中（`scenario_core.py`），在 `__repr__` 方法之后添加：

```python
    def to_dict(self) -> dict:
        """序列化为 dict（含 nodes 和 events）"""
        nodes_dict = {}
        for nid, node in self.nodes.items():
            nodes_dict[nid] = {
                "node_id": node.node_id,
                "description": node.description,
                "edges": [{"target": e.target, "method": e.method} for e in node.edges],
                "to_here": [{"target": e.target, "method": e.method} for e in node.to_here],
                "interactions": [
                    {
                        "type": i.type,
                        "name": i.name,
                        "trigger": i.trigger,
                        "result": i.result,
                        "clue": i.clue,
                        "requirements": [
                            {"ref_type": r.ref_type, "ref_scene": r.ref_scene, "ref_name": r.ref_name}
                            for r in i.requirements
                        ],
                        "side_effects": [_side_effect_to_dict(se) for se in i.side_effects],
                    }
                    for i in node.interactions
                ],
            }
        events_list = [
            {
                "event_id": e.event_id,
                "name": e.name,
                "trigger": e.trigger,
                "impact": e.impact,
                "requirements": [
                    {"ref_type": r.ref_type, "ref_scene": r.ref_scene, "ref_name": r.ref_name}
                    for r in e.requirements
                ],
            }
            for e in self.events.values()
        ]
        return {"nodes": nodes_dict, "events": events_list}

    @classmethod
    def from_dict(cls, data: dict) -> "DirectedGraph":
        """从 dict 重建 DirectedGraph（含 nodes 和 events）"""
        graph = cls()
        nodes_data = data.get("nodes", {})
        for nid, node_data in nodes_data.items():
            interactions = [
                Interaction(
                    type=inter["type"],
                    name=inter["name"],
                    trigger=inter.get("trigger", ""),
                    result=inter.get("result", ""),
                    clue=inter.get("clue"),
                    requirements=[
                        Requirement(
                            ref_type=req.get("ref_type", ""),
                            ref_scene=req.get("ref_scene", ""),
                            ref_name=req.get("ref_name", ""),
                        )
                        for req in inter.get("requirements", [])
                    ],
                    side_effects=_parse_side_effects(inter.get("side_effects", [])),
                )
                for inter in node_data.get("interactions", [])
            ]
            graph.nodes[nid] = Node(
                node_id=node_data["node_id"],
                description=node_data.get("description", ""),
                edges=[Edge(target=e["target"], method=e["method"]) for e in node_data.get("edges", [])],
                to_here=[Edge(target=e["target"], method=e["method"]) for e in node_data.get("to_here", [])],
                interactions=interactions,
            )
        events_data = data.get("events", [])
        for ev_data in events_data:
            graph.events[ev_data["event_id"]] = GameEvent(
                event_id=ev_data["event_id"],
                name=ev_data["name"],
                trigger=ev_data.get("trigger", ""),
                impact=ev_data.get("impact", ""),
                requirements=[
                    Requirement(
                        ref_type=req.get("ref_type", ""),
                        ref_scene=req.get("ref_scene", ""),
                        ref_name=req.get("ref_name", ""),
                    )
                    for req in ev_data.get("requirements", [])
                ],
            )
        return graph
```

- [ ] **Step 3: `ScenarioWorld.to_dict()`**

在 `ScenarioWorld` 类的 `apply_scene_update` 之后、`__repr__` 之前添加：

```python
    def to_dict(self) -> dict:
        """序列化运行时世界状态（含被修改的 node descriptions）"""
        modified_descriptions = {}
        for nid, node in self.graph.nodes.items():
            modified_descriptions[nid] = node.description

        return {
            "current_location": self.current_location,
            "triggered_events": dict(self.triggered_events),
            "completed_interactions": {
                k: list(v) for k, v in self.completed_interactions.items()
            },
            "flags": dict(self.flags),
            "background_story": self.background_story,
            "modified_descriptions": modified_descriptions,
        }

    @classmethod
    def from_dict(cls, data: dict, graph: "DirectedGraph") -> "ScenarioWorld":
        """从 dict + graph 恢复运行时世界状态"""
        world = cls(graph, data["current_location"])
        world.triggered_events = data.get("triggered_events", {})
        world.completed_interactions = {
            k: set(v) for k, v in data.get("completed_interactions", {}).items()
        }
        world.flags = data.get("flags", {})
        world.background_story = data.get("background_story", "")
        # 恢复被修改的 node descriptions
        for nid, desc in data.get("modified_descriptions", {}).items():
            if nid in graph.nodes:
                graph.nodes[nid].description = desc
        world.memory = MemoryManager.from_dict(data.get("memory", {}))
        return world
```

- [ ] **Step 4: `ScenarioWorld.save_state()` 和 `ScenarioWorld.load_state()`**

在 `from_dict` 类方法之后添加：

```python
    def save_state(self, path: str):
        """全量快照存档（图 + 世界 + 记忆 + 调查员快照）"""
        from investigator.serialization import to_dict as inv_to_dict
        from datetime import datetime

        data = {
            "version": 1,
            "scenario": "常暗之厢",
            "timestamp": datetime.now().isoformat(),
            "graph": self.graph.to_dict(),
            "world": self.to_dict(),
            "memory": self.memory.to_dict(),
            "player_snapshot": inv_to_dict(self.player) if self.player else {},
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_state(cls, path: str) -> "ScenarioWorld":
        """从存档恢复（自包含，不需要外部传 graph）"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        graph = DirectedGraph.from_dict(data["graph"])
        world_data = data["world"]
        world_data["memory"] = data.get("memory", {})
        world = cls.from_dict(world_data, graph)
        # 恢复调查员
        ps = data.get("player_snapshot")
        if ps:
            from investigator.serialization import from_dict as inv_from_dict
            world.player = inv_from_dict(ps)
        return world
```

需要在文件顶部添加 `import json`（检查是否已存在——第 9 行已有 `import json`）。

- [ ] **Step 5: 添加 `Investigator.save()` 便捷方法**

在 `src/investigator/models.py` 的 `Investigator` 类末尾添加（`damage_roll` stub 之后）：

```python
    def save(self, path: str):
        """长期存储：导出为 JSON 文件"""
        from investigator.serialization import to_json
        to_json(self, path)

    @classmethod
    def load(cls, path: str) -> "Investigator":
        """长期存储：从 JSON 文件加载"""
        from investigator.serialization import from_json
        return from_json(path)
```

- [ ] **Step 6: 验证 — 完整存档/读档循环**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
from src.scenario_core import DirectedGraph, ScenarioWorld, read_json_file
# 加载正常数据
scenes = read_json_file('data/output/scene_output_resolved_revised.json')
events = read_json_file('data/output/res_event_resolved_revised.json')
graph = DirectedGraph(scenes, events)
world = ScenarioWorld(graph, '6号车厢')
# 执行一些操作
world.move('5号车厢')
world.set_flag('test_flag', True)
world.memory.add_record('测试输入', 'move', '5号车厢', '你来到了5号车厢', location='5号车厢')
# 存档
world.save_state('data/saves/test_save.json')
print(f'Saved. Location: {world.current_location}, Flags: {dict(world.flags)}')
# 读档
restored = ScenarioWorld.load_state('data/saves/test_save.json')
print(f'Restored. Location: {restored.current_location}, Flags: {dict(restored.flags)}')
print(f'Events: {dict(restored.triggered_events)}')
print(f'Memory turn: {restored.memory.turn}')
print('Save/load cycle OK')
"
```

Expected: `Restored. Location: 5号车厢, Flags: {'test_flag': True}`, Memory turn=1

- [ ] **Step 7: Commit**

```bash
git add src/scenario_core.py src/investigator/models.py
git commit -m "feat: add to_dict/from_dict/save_state/load_state for full snapshot serialization"
```

---

### Task 6: JSON 数据模板更新 + 存档目录

**Files:**
- Modify: `data/templates/scene.json`
- Create: `data/saves/.gitkeep`

- [ ] **Step 1: 更新场景 JSON 模板**

修改 `data/templates/scene.json`，在 `interactions[].requirement` 之后、`clue` 之前加 `side_effects`：

将模板中的 interaction 对象从：

```json
      {
        "type": "搜索/对话/鉴定/战斗/调查/使用物品",
        "name": "互动名称",
        "requirement": [
          {"ref_type": "event", "ref_id": "E1", "ref_name": "事件名称"},
          {"ref_type": "interaction", "ref_scene": "场景名", "ref_name": "互动名称"}
        ],
        "trigger": "触发条件（技能鉴定名/玩家行为等）",
        "result": "成功/失败的后果描述",
        "clue": "该互动可能揭示的线索"
      }
```

改为：

```json
      {
        "type": "搜索/对话/鉴定/战斗/调查/使用物品",
        "name": "互动名称",
        "requirement": [
          {"ref_type": "event", "ref_id": "E1", "ref_name": "事件名称"},
          {"ref_type": "interaction", "ref_scene": "场景名", "ref_name": "互动名称"}
        ],
        "side_effects": [
          {"type": "flag_set", "key": "示例标记", "value": true},
          {"type": "item_gain", "item_name": "示例物品"},
          {"type": "stat_change", "stat_name": "SAN", "delta": -1}
        ],
        "trigger": "触发条件（技能鉴定名/玩家行为等）",
        "result": "成功/失败的后果描述",
        "clue": "该互动可能揭示的线索"
      }
```

- [ ] **Step 2: 创建存档目录**

```bash
mkdir -p data/saves && touch data/saves/.gitkeep
```

在 `.gitignore` 中确认 `data/saves/*.json` 被忽略（存档不应提交）。

- [ ] **Step 3: Commit**

```bash
git add data/templates/scene.json data/saves/.gitkeep
git commit -m "feat: add side_effects to scene template, create saves directory"
```

---

### Task 7: 清理验证

- [ ] **Step 1: 全量导入检查**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
from src.scenario_core import (
    Edge, Requirement, Interaction, GameEvent, Node,
    DirectedGraph, RequirementResolver, ScenarioWorld, MemoryManager,
    FlagSet, ItemGain, StatChange, ActionResult, read_json_file
)
from src.game_loop import handle_user_input, _apply_side_effects
from src.prompts import (
    build_action_prompt, build_event_prompt, build_narrative_prompt,
    build_improvise_prompt, parse_narrative_output, log_skill_result
)
from src.investigator.models import Investigator, Stats, Skill
print('All imports OK')
"
```

- [ ] **Step 2: 保存/加载完整循环测试（含调查员）**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
from src.scenario_core import DirectedGraph, ScenarioWorld, read_json_file
from src.investigator.models import Investigator, Stats, DerivedStats, Skill
# 创建最小调查员
stats = Stats(STR=50, CON=50, SIZ=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
derived = DerivedStats(HP=10, MP=10, SAN=50, SAN_MAX=99, MOV=8, DB='0', BUILD=0, DODGE=25)
inv = Investigator(name='测试调查员', age=30, gender='男', stats=stats, derived=derived, skills=[Skill(name='侦查', base_value=25, value=50)])
# 加载场景
scenes = read_json_file('data/output/scene_output_resolved_revised.json')
events = read_json_file('data/output/res_event_resolved_revised.json')
graph = DirectedGraph(scenes, events)
world = ScenarioWorld(graph, '6号车厢')
world.set_player(inv)
# 存档
world.save_state('data/saves/full_test.json')
# 读档
restored = ScenarioWorld.load_state('data/saves/full_test.json')
print(f'Location: {restored.current_location}')
print(f'Player: {restored.player.name if restored.player else None}')
print(f'Player skills: {[s.name for s in restored.player.skills] if restored.player else []}')
print('Full cycle OK')
"
```

Expected: Location=6号车厢, Player=测试调查员, skills=["侦查"]

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: add import and serialization round-trip verification"
```
