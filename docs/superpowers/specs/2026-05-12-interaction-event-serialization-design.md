# 交互结果丰富化 + 事件触发混合模式 + 世界可序列化

**日期**: 2026-05-12
**类型**: 统一设计（三项优化有数据流交叉）
**状态**: 待实现

---

## 一、交互结果模型丰富化

### 动机

当前 `execute_interaction` 和 `trigger_event` 均返回 `(bool, str)`，交互的副作用（设置标记、获得物品、属性变化）需要调用方手动处理。随着谜题复杂度上升，声明式副作用可以消除散落在 game_loop 中的手动状态操作。

### 新数据类

```python
# scenario_core.py

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
    - 扩展点在 apply_side_effects() 内部
    """
    stat_name: str
    delta: int       # 正=回复，负=损失

# SideEffect = FlagSet | ItemGain | StatChange

@dataclass  
class ActionResult:
    """交互/事件执行的统一返回类型"""
    success: bool
    message: str
    side_effects: list = field(default_factory=list)     # 由 JSON 声明
    suggested_flags: list = field(default_factory=list)   # 由 LLM 建议（预留，本轮不实现）
```

### 改造面

| 位置 | 改动 |
|------|------|
| `scenario_core.py` | 新增 `FlagSet` / `ItemGain` / `StatChange` / `ActionResult`；`Interaction` 加 `side_effects: list` |
| `scenario_core.py:execute_interaction` | 返回 `ActionResult`，从 `Interaction.side_effects` 组装 |
| `scenario_core.py:trigger_event` | 返回 `ActionResult`，副作用暂为空 |
| `game_loop.py:_execute_single_action` | 适配 `ActionResult` |
| `game_loop.py:handle_user_input` | 新增 `_apply_side_effects(world, effects)` —— 消费 `FlagSet`（调 `world.set_flag`）和 `ItemGain`（调 `world.memory.note_item`），`StatChange` 仅记录不修改状态 |
| `pipeline.py:resolve_requirements` 等 | `Interaction` 构造时解析 `side_effects` |
| JSON 数据文件 | `interactions[].side_effects` 字段按模板新增，当前值为 `[]` |

### 不变的

- LLM prompt 不动，`suggested_flags` 接口预留但不接入 prompt
- 所有对 `(bool, str)` 的外部引用适配为 `ActionResult.success` / `ActionResult.message`
- `StatChange` 不自动修改 `Investigator` 属性（SAN 检定规则待后续细化）

---

## 二、事件触发混合模式

### 动机

当前事件触发完全依赖 LLM（`build_event_prompt`）。虽然 `_categorize_pending_events` 已做了可触发/不可触发的语言分层（幻觉控制效果满意），但 LLM 返回后缺少确定性的最终校验。

### 方案

对标 action 处理逻辑：**LLM 判断意图 → 引擎二次确认条件**。

```
build_event_prompt (LLM，已区分 triggerable/non-triggerable)
    → LLM 返回 triggered_events + condition_events
    → 对每条 triggered_event，RequirementResolver.check() 确定性二次确认
    → 通过 → 实际 trigger
    → 不通过 → 降级输出到 condition（附原因）
```

### 改造面

| 位置 | 改动 |
|------|------|
| `game_loop.py` 阶段2 | 在 `trigger_event` 调用前加 `RequirementResolver.check()` 二次确认；不通过的移入 condition 分支输出 |
| `scenario_core.py` | 不改（`RequirementResolver`、`trigger_event` 已就绪） |
| `prompts.py` | 不改（`_categorize_pending_events` 已就绪） |

### 不变的

- LLM prompt 结构不动
- 事件判定仍由 LLM 主导；引擎只做底线校验
- `condition_events` 机制保留（LLM 对不可触发事件的指引）

---

## 三、世界状态可序列化

### 动机

存档/读档是玩家刚需，也为调试重现提供基础。`ScenarioWorld` + `DirectedGraph` 当前纯内存，无持久化。

### 两层存储模型

| | 临时存档 | 长期存储 |
|---|---|---|
| **时机** | 游戏中任意时刻 | 一局游戏结束后 |
| **内容** | 全量快照（图 + 世界 + 记忆 + 调查员） | 仅 `Investigator` |
| **格式** | 单 JSON | 已有 `character.json` 格式 |
| **槽位** | 多槽位（`save_01.json` ...） | 一个调查员一个文件 |
| **跨模组** | 否 | 是 |

### 存档结构

```json
{
  "version": 1,
  "scenario": "常暗之厢",
  "timestamp": "2026-05-12T20:00:00",
  "graph": {
    "nodes": { "...": {} },
    "events": [{ "id": "E1", ... }]
  },
  "world": {
    "current_location": "4号车厢",
    "triggered_events": {"E1": true, "E2": false},
    "completed_interactions": {"6号车厢": ["查看便签正面"]},
    "flags": {"found_key": true},
    "background_story": "..."
  },
  "memory": {
    "raw_history": [{"turn": 1, "location": "...", "user_input": "...", "action": "interact", "target": "...", "result": "...", "success": true}],
    "summary": "...",
    "visited": ["6号车厢", "5号车厢", "4号车厢"],
    "key_items": ["手电筒"],
    "turn": 5
  },
  "player_snapshot": {
    "name": "调查员A",
    "stats": {"STR": 60, "CON": 50, "SIZ": 55, "DEX": 70, "APP": 45, "INT": 65, "POW": 55, "EDU": 60},
    "derived_stats": {"SAN": 55, "HP": 11, "MP": 11, "LUCK": 50, "DB": 0, "BUILD": 0, "MOV": 8, "DODGE": 35},
    "skills": [{"name": "侦查", "value": 70, "linked_attribute": "INT"}, ...],
    "occupation": "侦探",
    "inventory": ["手电筒"]
  }
}
```

### API

```python
class ScenarioWorld:
    def save_state(self, path: str):
        """全量快照存档（图 + 世界 + 记忆 + 调查员快照）"""

    @classmethod
    def load_state(cls, path: str) -> "ScenarioWorld":
        """从存档恢复（自包含，不需要外部传 graph）"""

# Investigator（已有，明确为长期存储入口）
class Investigator:
    def save(self, path: str):   # to_dict → write
    @classmethod
    def load(cls, path: str):    # from_dict ← read
```

### 设计决策

- **全量快照**：图也存入（尽管当前是只读的），为将来地图破坏/修改机制预留，存档自包含、不依赖外部 JSON 数据文件
- **调查员内联**：存档内嵌 `player_snapshot`（运行时完整状态），不从 `character.json` 恢复。`character.json` 保持初始状态不动，游戏结束后 `investigator.save()` 覆盖写入做长期存储
- **多槽位**：文件名作为存档槽位（`save_01.json`、`save_02.json`...），不在存档元数据中管理槽位索引

---

## 四、影响范围总览

```
scenario_core.py  ◄── 新增 FlagSet, ItemGain, StatChange, ActionResult
                  ◄── Interaction 加 side_effects 字段
                  ◄── execute_interaction 返回 ActionResult
                  ◄── trigger_event 返回 ActionResult
                  ◄── ScenarioWorld.save_state() / load_state()

game_loop.py      ◄── 适配 ActionResult（_execute_single_action + handle_user_input）
                  ◄── 新增 _apply_side_effects()
                  ◄── 阶段2 引擎二次确认事件条件

prompts.py        ◄── 不改（LLM 能力已就绪）

pipeline.py       ◄── Interaction 构造时解析 side_effects

JSON 数据文件     ◄── interactions[].side_effects: []（预留填充）

notebook          ◄── 适配 ActionResult 调用方式
```

---

## 五、不纳入本轮范围

- `StatChange` 接入 COC SAN 检定规则
- LLM `suggested_flags` 实际接入 prompt 和消费逻辑
- JSON 数据文件 `side_effects` 字段的实际填充
- 战斗系统数据序列化（`combat_check`/`damage_roll` 仍为 stub）
- 存档的加密/校验/版本迁移
- 模组多目录化（单模组够用）
