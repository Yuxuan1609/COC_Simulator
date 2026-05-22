# ScenarioWorld 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ScenarioWorld 从 God object 重构为一级 Facade + 5 个子系统，markup 解析迁出到独立模块，side effect 应用分散到各 Manager。

**Architecture:** ScenarioWorld 保留为核心状态容器（图导航、entity 运行时状态、依赖解析），组合 GameClock/MemoryManager/EnemyManager/NPCManager/BossManager 五个二级类。TimeAgent 保持为轻量 LLM 评估器，读 Clock 不写 Clock。Keeper 通过 World 公开接口编排所有子系统。

**Tech Stack:** Python 3.12+, dataclass, pytest

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `src/game/side_effects.py` | **新建** | 7 种 side effect dataclass + `parse_markup()`/`parse_markup_all()`/`_parse_kwargs()` |
| `src/game/clock.py` | **新建** | `GameClock` — 纯确定性计时器 |
| `tests/test_clock.py` | **新建** | GameClock 单元测试 |
| `src/scenario_core.py` | **修改** | 移除 clock 字段/markup 解析/npc_states；挂载子系统；整合 RuntimeState 方法 |
| `src/game/boss_manager.py` | **修改** | 添加 `to_dict()`/`from_dict()` 序列化 |
| `src/game/agents/keeper.py` | **修改** | 适配 `world.clock.*` 接口；重写 `_apply_side_effects`；迁移 time_costs/comms_interval |
| `src/game/judge.py` | **修改** | 适配 markup import；`world.get_runtime_state()` → 公开方法 |
| `src/game_loop.py` | **修改** | 适配 `world.clock.*`/`world.enemies`/`world.npcs`；time_costs 迁移到 keeper |
| `src/prompts.py` | **修改** | `_build_world_state` 适配 `world.runtime_state` 访问 |
| 测试文件 | **修改** | `test_markup.py`/`test_time_system.py` 适配新 import；`test_judge.py` 等适配 world 接口 |

---

### Task 1: 新建 `src/game/side_effects.py` — side effect dataclass + markup 解析

**Files:**
- Create: `src/game/side_effects.py`
- Modify: `src/scenario_core.py:41-287`（移除对应代码段，re-export 兼容）
- Modify: `tests/test_markup.py:4`（更新 import）

- [ ] **Step 1: 创建 side_effects.py，从 scenario_core.py 搬移 dataclass 和解析函数**

```python
# src/game/side_effects.py
"""Side effect dataclasses and @markup parsing. Pure data + parser, no LLM/app logic."""
from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class ItemGain:
    item_name: str
    quantity: int = 1


@dataclass
class ConsumeItem:
    item_name: str
    quantity: int = 1
    narrative: str = ""


@dataclass
class StatChange:
    stat_name: str
    delta: int | str = 0
    narrative: str = ""


@dataclass
class SpawnEnemy:
    enemy_ref: str
    scene: str
    quantity: int = 1


@dataclass
class GrantWeapon:
    weapon_ref: str
    scene: str = ""
    quantity: int = 1


@dataclass
class SceneWeapon:
    weapon_ref: str
    scene: str
    quantity: int = 1


@dataclass
class NPCStateChange:
    npc_name: str
    new_state: str


@dataclass
class NPCFollow:
    npc_name: str
    follow: bool = True


# ── @markup parsing ──

_MARKUP_PATTERN = re.compile(
    r'@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change|npc_follow)'
    r'\(([^)]*)\)'
)


def _parse_kwargs(kwargs_str: str) -> dict:
    result = {}
    if not kwargs_str.strip():
        return result
    for match in re.findall(r'(\w+)\s*=\s*(?:"""([^"]*)"""|"([^"]*)"|\'([^\']*)\'|([^,)]+))', kwargs_str):
        key = match[0]
        value = match[1] or match[2] or match[3] or match[4]
        value = value.strip().rstrip(',')
        result[key] = value
    return result


def parse_markup(text: str):
    match = _MARKUP_PATTERN.search(text)
    if not match:
        return None
    func_name = match.group(1)
    kwargs_str = match.group(2)
    kwargs = _parse_kwargs(kwargs_str)

    if func_name == "spawn_enemy":
        return SpawnEnemy(
            enemy_ref=kwargs.get("enemy_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "grant_weapon":
        return GrantWeapon(
            weapon_ref=kwargs.get("weapon_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "stat_change":
        delta_str = kwargs.get("delta", "0")
        try:
            delta = int(delta_str)
        except ValueError:
            delta = delta_str
        return StatChange(
            stat_name=kwargs.get("stat_name", ""),
            delta=delta,
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "item_gain":
        return ItemGain(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "consume_item":
        return ConsumeItem(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "npc_state_change":
        return NPCStateChange(
            npc_name=kwargs.get("npc_name", ""),
            new_state=kwargs.get("new_state", ""),
        )
    elif func_name == "npc_follow":
        follow_str = kwargs.get("follow", "true").lower()
        return NPCFollow(
            npc_name=kwargs.get("npc_name", ""),
            follow=follow_str in ("true", "1", "yes"),
        )
    return None


def parse_markup_all(text: str) -> list:
    results = []
    for match in _MARKUP_PATTERN.finditer(text):
        func_name = match.group(1)
        kwargs_str = match.group(2)
        kwargs = _parse_kwargs(kwargs_str)

        if func_name == "spawn_enemy":
            results.append(SpawnEnemy(
                enemy_ref=kwargs.get("enemy_ref", ""),
                scene=kwargs.get("scene", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "grant_weapon":
            results.append(GrantWeapon(
                weapon_ref=kwargs.get("weapon_ref", ""),
                scene=kwargs.get("scene", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "stat_change":
            delta_str = kwargs.get("delta", "0")
            try:
                delta = int(delta_str)
            except ValueError:
                delta = delta_str
            results.append(StatChange(
                stat_name=kwargs.get("stat_name", ""),
                delta=delta,
                narrative=kwargs.get("narrative", ""),
            ))
        elif func_name == "item_gain":
            results.append(ItemGain(
                item_name=kwargs.get("item_name", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "consume_item":
            results.append(ConsumeItem(
                item_name=kwargs.get("item_name", ""),
                quantity=int(kwargs.get("quantity", 1)),
                narrative=kwargs.get("narrative", ""),
            ))
        elif func_name == "npc_state_change":
            results.append(NPCStateChange(
                npc_name=kwargs.get("npc_name", ""),
                new_state=kwargs.get("new_state", ""),
            ))
        elif func_name == "npc_follow":
            follow_str = kwargs.get("follow", "true").lower()
            results.append(NPCFollow(
                npc_name=kwargs.get("npc_name", ""),
                follow=follow_str in ("true", "1", "yes"),
            ))
    return results
```

- [ ] **Step 2: 更新 `scenario_core.py` — 移除 dataclass 和 markup 解析代码，重新 import**

删除 scenario_core.py 的 L41-287（ItemGain 到 parse_markup_all 的完整代码块），在文件顶部添加 re-export：

```python
# scenario_core.py 顶部 import 区域添加
from game.side_effects import (
    ItemGain, ConsumeItem, StatChange, SpawnEnemy, GrantWeapon,
    SceneWeapon, NPCStateChange, NPCFollow,
    parse_markup, parse_markup_all,
)
```

- [ ] **Step 3: 更新 `tests/test_markup.py` 的 import**

```python
# tests/test_markup.py:4 — 改为
from game.side_effects import parse_markup, parse_markup_all, ItemGain, StatChange, SpawnEnemy, GrantWeapon, NPCStateChange
```

- [ ] **Step 4: 运行 markup 测试确认通过**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_markup.py -v
```

Expected: 8 passed

- [ ] **Step 5: 更新所有其他文件的 markup import**

需要更新以下文件中的 `from scenario_core import parse_markup_all` → `from game.side_effects import parse_markup_all`：

- `src/game/judge.py:10` — `from scenario_core import parse_markup_all, resolve_graded_result` → 拆为两行
- `src/game/agents/keeper.py:8` — `from scenario_core import ScenarioWorld, Entity, parse_markup_all` → `parse_markup_all` 改从 `game.side_effects`

- [ ] **Step 6: 运行所有测试确认无 import 错误**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short 2>&1 | head -100
```

Expected: 无 ImportError，已有测试继续 pass。

- [ ] **Step 7: Commit**

```bash
git add src/game/side_effects.py src/scenario_core.py tests/test_markup.py src/game/judge.py src/game/agents/keeper.py
git commit -m "refactor: extract side effect dataclasses and markup parsing to src/game/side_effects.py"
```

---

### Task 2: 新建 `src/game/clock.py` — GameClock 纯计时器

**Files:**
- Create: `src/game/clock.py`
- Create: `tests/test_clock.py`

- [ ] **Step 1: 创建 GameClock 类**

```python
# src/game/clock.py
"""GameClock — deterministic minute-clock. No LLM calls, no narrative logic."""
from __future__ import annotations


class GameClock:
    """Pure time tracker. Author handles narrative time pressure; TimeAgent handles
    per-action time assessment. The clock just counts."""

    def __init__(self, start_time: int = 0):
        self.game_time: int = start_time
        self.time_context: str = ""

    @property
    def day(self) -> int:
        return self.game_time // 1440

    @property
    def hour(self) -> int:
        return (self.game_time % 1440) // 60

    @property
    def time_of_day(self) -> str:
        h = self.hour
        if h < 5:
            return "夜间"
        if h < 8:
            return "早晨"
        if h < 17:
            return "白天"
        if h < 20:
            return "黄昏"
        return "夜间"

    def advance_time(self, minutes: int) -> None:
        self.game_time += minutes

    def get_time_flags(self) -> dict[str, bool]:
        return {
            f"day:{self.day}": True,
            f"time:{self.time_of_day}": True,
        }

    def to_dict(self) -> dict:
        return {
            "game_time": self.game_time,
            "time_context": self.time_context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameClock":
        clock = cls(start_time=data.get("game_time", 0))
        clock.time_context = data.get("time_context", "")
        return clock

    def __repr__(self) -> str:
        return f"GameClock(day={self.day}, {self.time_of_day} {self.hour}:00, total={self.game_time}m)"
```

- [ ] **Step 2: 创建 GameClock 单元测试**

```python
# tests/test_clock.py
"""GameClock unit tests — no LLM dependency."""
import pytest
from game.clock import GameClock


@pytest.fixture
def clock():
    return GameClock()


def test_defaults(clock):
    assert clock.game_time == 0
    assert clock.day == 0
    assert clock.hour == 0
    assert clock.time_of_day == "夜间"


def test_advance_minutes(clock):
    clock.advance_time(300)
    assert clock.game_time == 300
    assert clock.day == 0
    assert clock.hour == 5
    assert clock.time_of_day == "早晨"


def test_advance_cross_day(clock):
    clock.advance_time(1500)
    assert clock.day == 1
    assert clock.hour == 1
    assert clock.time_of_day == "夜间"


def test_time_of_day_transitions(clock):
    assert clock.time_of_day == "夜间"
    clock.advance_time(300)
    assert clock.time_of_day == "早晨"
    clock.advance_time(180)
    assert clock.time_of_day == "白天"
    clock.advance_time(540)
    assert clock.time_of_day == "黄昏"
    clock.advance_time(180)
    assert clock.time_of_day == "夜间"


def test_time_flags(clock):
    flags = clock.get_time_flags()
    assert flags == {"day:0": True, "time:夜间": True}


def test_time_flags_after_advance(clock):
    clock.advance_time(480)
    flags = clock.get_time_flags()
    assert flags == {"day:0": True, "time:白天": True}


def test_advance_zero(clock):
    clock.advance_time(0)
    assert clock.game_time == 0


def test_advance_midnight_boundary(clock):
    clock.advance_time(1440)
    assert clock.day == 1
    assert clock.hour == 0
    assert clock.time_of_day == "夜间"


def test_serialization_roundtrip(clock):
    clock.advance_time(360)
    clock.time_context = "天色渐暗"
    data = clock.to_dict()
    restored = GameClock.from_dict(data)
    assert restored.game_time == 360
    assert restored.time_context == "天色渐暗"
    assert restored.time_of_day == clock.time_of_day


def test_separate_instances(clock):
    """Verify two clocks don't share state."""
    c2 = GameClock(start_time=100)
    clock.advance_time(50)
    assert c2.game_time == 100
```

- [ ] **Step 3: 运行 clock 测试确认通过**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_clock.py -v
```

Expected: 10 passed

- [ ] **Step 4: Commit**

```bash
git add src/game/clock.py tests/test_clock.py
git commit -m "feat: add GameClock — deterministic minute-clock extracted from ScenarioWorld"
```

---

### Task 3: ScenarioWorld 挂载 GameClock + 移除 npc_states

**Files:**
- Modify: `src/scenario_core.py`（ScenarioWorld.__init__ + 相关方法）

- [ ] **Step 1: 修改 `ScenarioWorld.__init__` — 挂载 clock 和 npcs，移除遗留字段**

```python
# scenario_core.py — ScenarioWorld.__init__
def __init__(self, graph: DirectedGraph, start_node: str,
             background_story: str = "",
             wr0_enabled: bool = False,
             enemy_library: Any = None,
             weapon_library: Any = None,
             boss_library: Any = None,
             boss_encounters: list | None = None):
    from game.clock import GameClock
    from game.enemy_manager import EnemyManager
    from game.npc_manager import NPCManager
    from game.boss_manager import BossManager

    self.graph = graph
    self.current_location = start_node
    self.player: 'InvestigatorType | None' = None
    self.background_story = background_story
    self.wr0_enabled = wr0_enabled

    # 子系统
    self.clock = GameClock()
    self.memory = MemoryManager()
    self.enemies = EnemyManager(enemy_library) if enemy_library else None
    self.npcs = NPCManager()
    self.bosses = BossManager(boss_library, boss_encounters or []) if boss_library else None

    # 本体状态
    self.scene_weapons: dict[str, list[SceneWeapon]] = {}
    self.weapon_library = weapon_library

    self.triggered_events: Dict[str, bool] = {
        eid: False for eid in graph.get_all_event_ids()
    }
    self.completed_interactions: Dict[str, Set[str]] = {}

    self._runtime_state: Dict[str, NodeRuntimeState] = {}
    self._dependency_graph: Dict[str, Any] = {}
```

删去旧初始化中的：
- `self.game_time = 0`
- `self._last_comms_time = 0`
- `self.comms_interval = 15`
- `self.time_context = ""`
- `self.npc_states: Dict[str, str] = {}`
- enemy_manager 的惰性 import（`if enemy_library is not None: from game.enemy_manager import EnemyManager; self.enemy_manager = ...`）

- [ ] **Step 2: 添加 clock 属性代理（向后兼容）**

在 ScenarioWorld 类中添加 property 代理，让旧代码 `world.game_time` 等仍可工作：

```python
# 向后兼容属性 — 代理到 clock
@property
def game_time(self) -> int:
    return self.clock.game_time

@property
def day(self) -> int:
    return self.clock.day

@property
def hour(self) -> int:
    return self.clock.hour

@property
def time_of_day(self) -> str:
    return self.clock.time_of_day

@property
def time_context(self) -> str:
    return self.clock.time_context

@time_context.setter
def time_context(self, value: str):
    self.clock.time_context = value

def advance_time(self, minutes: int):
    self.clock.advance_time(minutes)

def get_time_flags(self) -> dict:
    return self.clock.get_time_flags()
```

保留 `enemy_manager` 兼容属性：

```python
@property
def enemy_manager(self):
    """向后兼容 — 代理到 self.enemies。"""
    return self.enemies

@enemy_manager.setter
def enemy_manager(self, value):
    self.enemies = value
```

- [ ] **Step 3: 移除 npc_states 遗留 dict，代理到 NPCManager**

删除 `self.npc_states` 字段和 `set_npc_state()`/`get_npc_state()` 方法（替换为代理）：

```python
def set_npc_state(self, npc_name: str, state: str):
    self.npcs.set_state(npc_name, state)

def get_npc_state(self, npc_name: str) -> str:
    npc = self.npcs.get(npc_name)
    return npc.state if npc else "未知"
```

- [ ] **Step 4: 运行测试确认兼容属性工作**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_time_system.py tests/test_enemy_manager.py tests/test_npc_manager.py -v --tb=short
```

Expected: 全部 pass

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py
git commit -m "refactor: mount GameClock/NPCManager on ScenarioWorld, add backward-compat properties"
```

---

### Task 4: BossManager 序列化

**Files:**
- Modify: `src/game/boss_manager.py`

- [ ] **Step 1: 添加 `to_dict()` / `from_dict()` 到 BossManager**

```python
# 添加到 BossManager 类中

def to_dict(self) -> dict:
    return {
        "active_boss_id": self._active_boss_id,
        "encounters": self._encounters,
    }

@classmethod
def from_dict(cls, data: dict, boss_library: BossLibrary) -> "BossManager":
    mgr = cls(boss_library, data.get("encounters", []))
    mgr._active_boss_id = data.get("active_boss_id")
    return mgr
```

- [ ] **Step 2: 运行 boss 测试确认**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_boss_manager.py tests/test_boss_library.py -v --tb=short
```

Expected: 全部 pass

- [ ] **Step 3: Commit**

```bash
git add src/game/boss_manager.py
git commit -m "feat: add BossManager.to_dict/from_dict serialization"
```

---

### Task 5: RuntimeState 方法整合到 ScenarioWorld

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 统一 `_runtime_state` 访问 — 将 Judge 中直连 dict 的逻辑封装为 World 方法**

`ScenarioWorld` 已经有一些方法，需要确保以下公开方法存在并统一命名：

```python
# —— entity 运行时状态 ——

def mark_completed(self, entity_id: str, tier: str = ""):
    """Mark entity completed in runtime state."""
    state = self.get_runtime_state(entity_id)
    state.completed = True
    if tier:
        state.result_tier = tier

def is_entity_completed(self, entity_id: str) -> bool:
    """Check if entity is completed via runtime_state."""
    state = self._runtime_state.get(entity_id)
    if state:
        return state.completed
    # fallback for events
    return self.triggered_events.get(entity_id, False)

def get_runtime_state(self, entity_id: str) -> NodeRuntimeState:
    if entity_id not in self._runtime_state:
        self._runtime_state[entity_id] = NodeRuntimeState()
    return self._runtime_state[entity_id]

# —— 依赖查询 ——

def are_entity_requirements_met(self, entity) -> bool:
    """Check entity prerequisites via runtime_state."""
    if hasattr(entity, 'requirement'):
        req = entity.requirement
        if not req or not req.strip():
            return True
        hard = req.split("||", 1)[0].strip() if "||" in req else req.strip()
        if not hard:
            return True
        return parse_hard_requirement(hard, self._runtime_state)
    return True

def check_edge_requirements(self, entity_id: str) -> tuple[bool, str]:
    # ... 保留现有实现 ...

def get_incoming_edges(self, entity_id: str) -> list[dict]:
    # ... 保留现有实现 ...

def load_dependency_graph(self, dep_graph: dict):
    # ... 保留现有实现 ...
```

- [ ] **Step 2: 更新 `_are_requirements_met` → `are_entity_requirements_met`**

现有 `_are_requirements_met` 以下划线开头，改为公开方法名。更新 `get_scene_summary:1001` 中的调用。

- [ ] **Step 3: 运行测试确认**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_judge.py tests/test_directed_graph.py tests/test_entity.py tests/test_entity_resolvers.py -v --tb=short
```

Expected: 全部 pass

- [ ] **Step 4: Commit**

```bash
git add src/scenario_core.py src/game/judge.py
git commit -m "refactor: unify ScenarioWorld runtime_state access with public methods"
```

---

### Task 6: Keeper 适配 World 新接口

**Files:**
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: 迁移 `time_costs` 和 `comms_interval` 到 Keeper**

之前 `game_loop.py` 把 `time_costs` 和 `comms_interval` 直接设到 `world` 上。改为 Keeper 持有这些配置：

Keeper.__init__ 新增参数：

```python
def __init__(self, world, *,
             dependency_graph=None, phase1=None, npc_profiles=None,
             boss_manager=None, npc_manager=None,
             time_costs=None, comms_interval=15):
    # ... existing init ...
    self.time_costs = time_costs or {}
    self.comms_interval = comms_interval
```

Keeper 中 `world.time_costs` → `self.time_costs`，`world.comms_interval` → `self.comms_interval`。

- [ ] **Step 2: 适配 clock 属性和 enemy_manager → enemies**

在 `keeper.py` 中：
- `self.world.game_time` → `self.world.clock.game_time`（或使用兼容属性）
- `self.world.enemy_manager` → `self.world.enemies`
- `self.world.time_of_day` → `self.world.clock.time_of_day`
- `self.world.time_context` → `self.world.clock.time_context`
- `self.world.advance_time(delta)` → `self.world.clock.advance_time(delta)`
- `self.world._last_comms_time` → Keeper 内部 `self._last_comms_time`
- `self.world.comms_interval` → `self.comms_interval`

在 `_should_trigger_time_agent` 中（line 702）：
```python
# 之前
if self.world.game_time - self._last_ta_call >= 30:
# 之后
if self.world.clock.game_time - self._last_ta_call >= 30:
```

在 `_resolve_time_delta` 中（line 681-688）：
```python
defaults = self.time_costs  # 而不是 world.time_costs
```

- [ ] **Step 3: 重写 `_apply_side_effects` — 分布到各 Manager**

替换 `process_turn()` 中 `self._apply_side_effects(outcome.side_effects)` 调用的实现。现有的 `apply_side_effects` 模块函数不再调用，改为 Keeper 方法：

```python
def _apply_side_effects(self, side_effects: list) -> list[str]:
    """Apply side effect dataclasses via respective managers. Returns log messages."""
    msgs = []
    for effect in side_effects:
        if isinstance(effect, ItemGain):
            self.world.memory.note_item(effect.item_name)
            if self.world.player and hasattr(self.world.player, 'item_manager'):
                self.world.player.item_manager.add(effect.item_name, quantity=effect.quantity)
                qty_str = f" x{effect.quantity}" if effect.quantity > 1 else ""
                msgs.append(f"[获得物品] {effect.item_name}{qty_str}（已加入背包）")
            else:
                msgs.append(f"[获得物品] {effect.item_name}")

        elif isinstance(effect, ConsumeItem):
            consumed = False
            if self.world.player and hasattr(self.world.player, 'item_manager'):
                im = self.world.player.item_manager
                if im.has(effect.item_name) and im.get(effect.item_name).quantity >= effect.quantity:
                    im.remove(effect.item_name, effect.quantity)
                    consumed = True
                else:
                    # LLM fuzzy match fallback
                    try:
                        from llm import call_deepseek
                        from prompts import build_consume_item_fuzzy_prompt
                        held = im.describe()
                        if held and held != "（未持有物品）":
                            prompt = build_consume_item_fuzzy_prompt(
                                target=effect.item_name, quantity=effect.quantity, held_items=held)
                            result = call_deepseek(
                                prompt, json_mode=True, model="deepseek-v4-flash",
                                system="你是 COC 7th KP 助理。",
                                fallback_schema={"matched": False, "item_name": "", "reason": ""})
                            if isinstance(result, str):
                                import json as _json
                                result = _json.loads(result)
                            if result.get("matched") and result.get("item_name"):
                                if im.has(result["item_name"]):
                                    im.remove(result["item_name"], effect.quantity)
                                    consumed = True
                    except Exception:
                        pass
            msgs.append(f"[消耗物品] {effect.item_name} x{effect.quantity}" +
                       ("" if consumed else "（未找到匹配物品）"))

        elif isinstance(effect, SpawnEnemy):
            target_scene = effect.scene or self.world.current_location
            if self.world.enemies:
                instance = self.world.enemies.spawn(effect.enemy_ref, target_scene, effect.quantity)
                msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene} ({instance.instance_id})")
            else:
                msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}")

        elif isinstance(effect, GrantWeapon):
            target_scene = effect.scene or self.world.current_location
            sw = SceneWeapon(weapon_ref=effect.weapon_ref, scene=target_scene, quantity=effect.quantity)
            if target_scene not in self.world.scene_weapons:
                self.world.scene_weapons[target_scene] = []
            self.world.scene_weapons[target_scene].append(sw)
            self.world.memory.note_item(effect.weapon_ref)
            msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {target_scene}")

        elif isinstance(effect, NPCStateChange):
            self.world.npcs.set_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")

        elif isinstance(effect, NPCFollow):
            self.world.npcs.set_following(effect.npc_name, effect.follow)
            status = "开始跟随" if effect.follow else "停止跟随"
            msgs.append(f"[NPC跟随] {effect.npc_name} {status}")

        elif isinstance(effect, StatChange):
            if self.world.player:
                new_val, detail = self.world.player.modify_stat(effect.stat_name, effect.delta)
                msgs.append(f"[属性变化] {detail}")
                if effect.narrative and hasattr(self.world.player, 'personal_description'):
                    try:
                        from llm import call_deepseek
                        from prompts import build_stat_narrative_prompt
                        prompt = build_stat_narrative_prompt(
                            inv_desc=self.world.player.personal_description or self.world.player.appearance or "",
                            stat_name=effect.stat_name, delta=str(effect.delta), narrative=effect.narrative)
                        result = call_deepseek(
                            prompt, json_mode=True, model="deepseek-v4-flash",
                            system="你是 COC 7th KP 助理，负责更新调查员描述。",
                            fallback_schema={"description": self.world.player.personal_description or ""})
                        if isinstance(result, str):
                            import json as _json
                            result = _json.loads(result)
                        new_desc = result.get("description", "")
                        if new_desc and new_desc != (self.world.player.personal_description or ""):
                            self.world.player.personal_description = new_desc
                            msgs.append(f"[描述更新] {effect.stat_name} 变化影响了外貌/心理描述")
                    except Exception:
                        pass
            else:
                sign = '+' if (isinstance(effect.delta, (int, float)) and effect.delta > 0) else ''
                msgs.append(f"[属性变化] {effect.stat_name} {sign}{effect.delta}（无调查员，未应用）")

    return msgs
```

需要添加 import：
```python
from game.side_effects import (
    ItemGain, ConsumeItem, StatChange, SpawnEnemy, GrantWeapon, SceneWeapon,
    NPCStateChange, NPCFollow,
)
```

- [ ] **Step 4: 运行测试确认 Keeper 适配**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_author_flow.py tests/test_intent_detector.py tests/test_combat_entry.py -v --tb=short
```

Expected: 全部 pass

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "refactor: adapt Keeper to World new interface, migrate time_costs/comms_interval, rewrite _apply_side_effects"
```

---

### Task 7: game_loop.py / judge.py / prompts.py 适配

**Files:**
- Modify: `src/game_loop.py`
- Modify: `src/game/judge.py`
- Modify: `src/prompts.py`

- [ ] **Step 1: game_loop.py 适配**

修改 `init_game()` 函数：

```python
# L175-196 — 修改 world 初始化和 time_costs 传递
world = ScenarioWorld(graph, start_node=start_node,
                      background_story=background,
                      wr0_enabled=wr0_enabled,
                      enemy_library=enemy_library,
                      weapon_library=weapon_library)

# time_costs 不再设到 world，改为传给 keeper
time_costs = {}
tc_path = _os.path.join("data", "library", "core", "time_costs.json")
if _os.path.exists(tc_path):
    with open(tc_path, encoding="utf-8") as f:
        time_costs = _json.load(f)

comms_interval = module_meta.get("comms_interval", 15)

# ... 之后 ...
keeper = Keeper(world, dependency_graph=dep_graph, phase1=phase1,
                npc_profiles=npc_profiles, npc_manager=npc_manager,
                time_costs=time_costs, comms_interval=comms_interval)
```

`world.enemy_manager` → `world.enemies`（所有出现处）：
- L260: `world.enemy_manager.exit_combat(result_dict)` → `world.enemies.exit_combat(result_dict)`
- L341-346: `keeper.world.enemy_manager` → `keeper.world.enemies`
- L354-359: 同上
- L371: `keeper.world.weapon_library` — 保持不变
- L375: `keeper.world.enemy_manager` → `keeper.world.enemies`

处理 npc_manager 的直接传递（L164-173, L206, L216）：
- npc_manager 仍创建但 **也** 传给 `world.npcs`（通过 world 初始化后 `world.npcs = npc_manager` 或改 init_game 中先创建再传入）

```python
# L164 之后：npc_manager 创建后同时设到 world
npc_manager = NPCManager()
npc_manager.init_from_profiles(npc_profiles)
world.npcs = npc_manager  # 替换默认创建的 NPCManager
```

- [ ] **Step 2: judge.py 适配**

```python
# L10 — 拆行
from game.side_effects import parse_markup_all
from scenario_core import resolve_graded_result

# L93 — 世界状态访问统一
# world.runtime_state.get(entity.id) → world.get_runtime_state(entity.id).completed
# 或者直接用 is_entity_completed:
```

更新 `_is_completed` 方法（L90-97）：

```python
def _is_completed(self, entity) -> bool:
    if entity.entity_type == "event":
        return self.world.is_event_triggered(entity.id)
    return self.world.is_entity_completed(entity.id)
```

更新 L313, L320 的 `self.world.runtime_state` 直接访问 → `self.world.get_runtime_state()`。

- [ ] **Step 3: prompts.py 适配**

`_build_world_state` (L138-144) 中 `world.runtime_state` 直接访问保持不变（dict 仍在 world 上，只改名为 `_runtime_state`，这里应该用公开方法）：

```python
def _build_world_state(world: ScenarioWorld) -> str:
    triggered = [eid for eid, t in world.triggered_events.items() if t]
    # Use public method instead of private dict access
    # The _runtime_state dict is still on world; 暂时保持兼容
    completed_entities = [eid for eid, s in world._runtime_state.items() if s.completed]
    flags_str = ", ".join(completed_entities) or "（无）"
    return f"""已触发事件：{triggered or '（无）'}
世界标记：{flags_str}"""
```

- [ ] **Step 4: 运行测试确认**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short -k "not harness and not escalation" 2>&1 | tail -30
```

Expected: 全部 pass（排除真实 LLM 测试）

- [ ] **Step 5: Commit**

```bash
git add src/game_loop.py src/game/judge.py src/prompts.py
git commit -m "refactor: adapt game_loop, judge, prompts to World new interface"
```

---

### Task 8: ScenarioWorld 序列化适配 + 死代码清理

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 更新 `ScenarioWorld.to_dict` — 纳入 clock/npcs/enemies/bosses 序列化**

```python
def to_dict(self) -> dict:
    modified_descriptions = {}
    for nid, node in self.graph.nodes.items():
        modified_descriptions[nid] = node.description

    runtime_state_serialized = {}
    for eid, s in self._runtime_state.items():
        runtime_state_serialized[eid] = {
            "completed": s.completed,
            "result_tier": s.result_tier,
            "retries": s.retries,
            "escalated_difficulty": s.escalated_difficulty,
        }

    return {
        "current_location": self.current_location,
        "triggered_events": dict(self.triggered_events),
        "completed_interactions": {
            k: list(v) for k, v in self.completed_interactions.items()
        },
        "runtime_state": runtime_state_serialized,
        "dependency_graph": self._dependency_graph,
        "background_story": self.background_story,
        "modified_descriptions": modified_descriptions,
        "wr0_enabled": self.wr0_enabled,
        # 新子系统
        "clock": self.clock.to_dict(),
        "npc_states": self.npcs.to_dict(),  # 保持 key 名兼容旧存档
        "enemies": self.enemies.to_dict() if self.enemies else {},
        "bosses": self.bosses.to_dict() if self.bosses else {},
    }
```

- [ ] **Step 2: 更新 `ScenarioWorld.from_dict` — 恢复 clock/npcs/enemies/bosses**

```python
@classmethod
def from_dict(cls, data: dict, graph: "DirectedGraph") -> "ScenarioWorld":
    world = cls(graph, data["current_location"])
    world.triggered_events = data.get("triggered_events", {})
    world.completed_interactions = {
        k: set(v) for k, v in data.get("completed_interactions", {}).items()
    }
    world.background_story = data.get("background_story", "")
    world.wr0_enabled = data.get("wr0_enabled", False)
    world._dependency_graph = data.get("dependency_graph", {})

    # 恢复 runtime_state
    for eid, sdata in data.get("runtime_state", {}).items():
        world._runtime_state[eid] = NodeRuntimeState(
            completed=sdata.get("completed", False),
            result_tier=sdata.get("result_tier", ""),
            retries=sdata.get("retries", 0),
            escalated_difficulty=sdata.get("escalated_difficulty", ""),
        )

    # 恢复 node descriptions
    for nid, desc in data.get("modified_descriptions", {}).items():
        if nid in graph.nodes:
            graph.nodes[nid].description = desc

    # 恢复 clock
    if "clock" in data:
        world.clock = GameClock.from_dict(data["clock"])

    # 恢复 npcs
    if "npc_states" in data:
        # 兼容旧存档 key 名 npc_states
        world.npcs.from_dict(data["npc_states"], {})
    elif "npcs" in data:
        world.npcs.from_dict(data["npcs"], {})

    # 恢复 enemies (需要 enemy_library 引用; 在 game_loop 的 load_state 中提供)
    # 这里做 graceful degradation

    # 恢复 memory
    world.memory = MemoryManager.from_dict(data.get("memory", {}))

    return world
```

- [ ] **Step 3: 更新 `save_state` / `load_state` — 传递 subsystem 序列化**

```python
def save_state(self, path: str):
    from investigator.serialization import to_dict as inv_to_dict
    from datetime import datetime
    import os

    data = {
        "version": 1,
        "timestamp": datetime.now().isoformat(),
        "graph": self.graph.to_dict(),
        "world": self.to_dict(),
        "memory": self.memory.to_dict(),
        "player_snapshot": inv_to_dict(self.player) if self.player else None,
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@classmethod
def load_state(cls, path: str, enemy_library=None) -> "ScenarioWorld":
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if data.get("version") != 1:
        raise ValueError(f"不支持的存档版本: {data.get('version')}")
    graph = DirectedGraph.from_dict(data["graph"])
    world_data = data["world"]
    world_data["memory"] = data.get("memory", {})
    world = cls.from_dict(world_data, graph)
    # 恢复 enemies（需要 library）
    if enemy_library and "enemies" in world_data:
        from game.enemy_manager import EnemyManager
        world.enemies = EnemyManager.from_dict(world_data["enemies"], enemy_library)
    # 恢复调查员
    ps = data.get("player_snapshot")
    if ps is not None:
        from investigator.serialization import from_dict as inv_from_dict
        world.player = inv_from_dict(ps)
    return world
```

- [ ] **Step 4: 清理死代码**

在 `scenario_core.py` 中移除：
- `EncounterAnchor` dataclass（line 101-108，C4）
- 场景移动相关逻辑中未使用的代码
- `apply_side_effects()` 模块函数（逻辑已迁移到 Keeper，保留函数签名但标记 deprecated 或直接删除）

`apply_side_effects` 处理：暂时保留函数体但加 deprecation warning，等确认无外部调用者后删除。

```python
import warnings

def apply_side_effects(world, side_effects) -> list:
    """Deprecated. Use Keeper._apply_side_effects instead."""
    warnings.warn("apply_side_effects is deprecated. Use Keeper._apply_side_effects.",
                  DeprecationWarning, stacklevel=2)
    msgs = []
    # ... keep original logic for now ...
    return msgs
```

- [ ] **Step 5: 运行完整测试套件确认**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short -k "not harness and not escalation_real" 2>&1 | tail -40
```

Expected: 所有非 LLM 测试 pass

- [ ] **Step 6: Commit**

```bash
git add src/scenario_core.py
git commit -m "refactor: update ScenarioWorld serialization for subsystems, deprecate apply_side_effects"
```

---

### Task 9: 最终验证 + 集成测试

**Files:**
- No new files

- [ ] **Step 1: 运行全部测试套件**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short 2>&1 | tail -60
```

检查结果，定位并修复任何回归。

- [ ] **Step 2: 运行真实 LLM 集成测试（可选，需 API key）**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/game_loop_harness.py tests/test_escalation_harness.py -v --tb=long 2>&1 | tail -40
```

- [ ] **Step 3: 更新 `NEXT-SESSION.md` — 标记 A1 已解决，更新架构状态**

更新 A1 行：
```markdown
| A1 | ScenarioWorld 职责边界模糊化（God object 趋势） | FIXED — 拆分为 Facade + GameClock；npc_states 移除；BossManager/EnemyManager/NPCManager 正式挂载 |
```

- [ ] **Step 4: Final commit**

```bash
git add docs/superpowers/specs/NEXT-SESSION.md
git commit -m "docs: mark A1 (ScenarioWorld God object) as resolved"
```
