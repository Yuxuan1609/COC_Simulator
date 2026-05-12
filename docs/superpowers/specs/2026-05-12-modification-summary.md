# 修改说明：交互结果丰富化 + 事件触发混合模式 + 世界可序列化

**日期**: 2026-05-12
**基于**: `docs/superpowers/specs/2026-05-12-interaction-event-serialization-design.md`

---

## 改动文件一览

| 文件 | 行变化 | 性质 |
|------|--------|------|
| `src/scenario_core.py` | +279/-33 | 新增数据类、返回类型重构、序列化 |
| `src/game_loop.py` | +77/-12 | ActionResult 消费、副作用引擎、事件门 |
| `src/investigator/models.py` | +11 | save/load 便捷方法 |
| `data/templates/scene.json` | +5 | side_effects 模板 |
| `.gitignore` | +1 | 存档文件忽略规则 |
| `data/saves/.gitkeep` | 0 | 存档目录占位 |

---

## 一、交互结果模型丰富化

### 新增数据类

- **`FlagSet(key, value=True)`** — 设置世界标记
- **`ItemGain(item_name)`** — 获得关键物品
- **`StatChange(stat_name, delta)`** — 属性变化（预留，不自动修改 Investigator）
- **`ActionResult(success, message, side_effects=[], suggested_flags=[])`** — 统一的交互/事件返回类型

### `Interaction` 新增字段

```python
side_effects: list = field(default_factory=list)  # FlagSet | ItemGain | StatChange
```

JSON 模板已更新，示例：
```json
"side_effects": [
  {"type": "flag_set", "key": "示例标记", "value": true},
  {"type": "item_gain", "item_name": "示例物品"},
  {"type": "stat_change", "stat_name": "SAN", "delta": -1}
]
```

### 返回类型变更

三个 `ScenarioWorld` 方法的返回值从 `Tuple[bool, str]` 改为 `ActionResult`：

| 方法 | 旧 | 新 |
|------|-----|-----|
| `move(target)` | `(bool, str)` | `ActionResult` |
| `execute_interaction(name)` | `(bool, str)` | `ActionResult`（成功时携带 `side_effects`） |
| `trigger_event(event_id)` | `(bool, str)` | `ActionResult` |

### 副作用消费

`game_loop.py` 新增 `_apply_side_effects(world, side_effects) -> list[str]`，在三个路径统一调用：
- Phase 1a：场景交互执行后
- Phase 1b：移动执行后
- Phase 2：事件触发后

### 工具函数

- `_parse_side_effect(data: dict)` — dict → 数据类实例
- `_parse_side_effects(data: list) -> list` — 批量解析
- `_side_effect_to_dict(effect) -> dict` — 数据类实例 → dict（序列化用）

### 预留项（本轮未实现）

| 项目 | 状态 |
|------|------|
| `StatChange` 自动修改 Investigator 属性 | COC SAN 规则待细化 |
| `suggested_flags` LLM 接入 | 接口预留 |
| JSON 数据文件 `side_effects` 字段实际填充 | 字段已预留 `[]` |

---

## 二、事件触发混合模式

### 改动

在 `game_loop.py` 阶段2（事件执行）中，对 LLM 返回的每条 `triggered_event` 增加确定性二次确认：

```
LLM 判定意图 → 返回 triggered_events
    → 引擎 RequirementResolver.check() 二次确认
    → 满足 → 实际触发
    → 不满足 → 降级为条件不满足输出
```

### 涉及的 Prompt

未改动。`_categorize_pending_events` 已对 LLM 做了可触发/不可触发事件的语言分层。

---

## 三、世界状态可序列化

### API

```python
# 临时存档（全量快照）
world.save_state("data/saves/save_01.json")
world = ScenarioWorld.load_state("data/saves/save_01.json")

# 长期存储（仅调查员）
investigator.save("character_final.json")
inv = Investigator.load("character_final.json")
```

### 存档结构

```json
{
  "version": 1,
  "timestamp": "...",
  "graph": { "nodes": {...}, "events": [...] },
  "world": {
    "current_location": "...",
    "triggered_events": {...},
    "completed_interactions": {...},
    "flags": {...},
    "background_story": "...",
    "modified_descriptions": {...}
  },
  "memory": { "raw_history": [...], "summary": "...", "visited": [...], "key_items": [...], "turn": N },
  "player_snapshot": { ... }  // null 当无调查员
}
```

### 序列化覆盖

| 类 | `to_dict()` | `from_dict()` |
|----|-------------|---------------|
| `DirectedGraph` | nodes + events（含 interactions.side_effects） | 完整重建 |
| `ScenarioWorld` | 运行时状态 + modified_descriptions | dict + graph 恢复 |
| `MemoryManager` | raw_history, summary, visited, key_items, turn | 含 max_raw 参数 |
| `Investigator` | 已有（`investigator.serialization.to_dict`） | 已有（`investigator.serialization.from_dict`） |

### 安全措施

- 版本号校验：`version != 1` 时拒绝加载
- `player_snapshot` 为 `null`（而非 `{}`），避免误判
- `save_state` 自动创建父目录

---

## 调用方适配说明

`notebooks/notebook_simplified.ipynb` 中如有对 `world.move()`、`world.execute_interaction()`、`world.trigger_event()` 的调用，需从元组解包改为属性访问：

```python
# 旧
ok, msg = world.move("5号车厢")

# 新
result = world.move("5号车厢")
# result.success, result.message, result.side_effects
```

`handle_user_input` 返回值保持 `dict`（`{"brief", "narrative", "full"}`），消费端无需改动。
