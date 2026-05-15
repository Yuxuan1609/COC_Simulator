# Step 3 重构 + Step 3.5 依赖图设计

**日期**: 2026-05-15
**状态**: 设计中
**范围**: `src/module_designer/` — 解析管线；不影响 `game_loop.py`（序列化图为可选）

---

## 1. 目标

将当前过于臃肿的 Step 3a 拆分为三个职责清晰的步骤：
- **Step 3a**: 去重 + 冲突解决 + 结局验证（轻量 LLM）
- **Step 3.5**: 依赖图构建 + 循环检测（LLM + 代码）
- **Step 4**: 所有标准化统一处理（enemy/weapon/skill/stat + side_effect 结构化）

## 2. 新管线流程

```
Step 3a: 去重 + 冲突解决 + 结局验证（1 call）
    ↓
Step 3b: L1 ↔ L2 交叉核对（1 call）—— 不变
    ↓
Step 3.5 + Step 4: 并行（2 calls）
    ├─ Step 3.5: requirement 标准化 → 有向图 → 循环检测
    └─ Step 4: enemy/weapon/skill/stat 标准化 + side_effect 结构化
    ↓
最终验证 + 保存
```

## 3. Step 3a（精简后）

### 3.1 SYSTEM 原则

- based_on 已标注派生关系。若两个 entity 的 based_on 指向同一 interaction 且语义重复 → 合并
- graded_result 在 type != "无" 时建议填写但不强制；type == "无" 时删除空 graded_result
- result 和 side_effects 信息重合时修剪。result 为 "##GRADED##" 时跳过此检查
- 冲突以 condensed_text 为准修正
- ##END_## 标记与 L3 ending_conditions 相互补齐

### 3.2 任务

| # | 任务 | 说明 |
|---|------|------|
| 1 | Based_on 去重 | 同一 interaction 派生的多个 entity 语义重复时合并 |
| 2 | Graded_result 检查 | 建议填写，不强制；清理 type="无" 的空字段 |
| 3 | Result/Side_effects 去重 | 信息重合修剪；##GRADED## 跳过 |
| 4 | 冲突解决 | requirement/trigger 矛盾以 condensed_text 为准 |
| 5 | 结局标记验证 | ##END_## ↔ L3 ending_conditions |

### 3.3 移除的任务

- ~~Side_effect 结构化~~ → Step 4
- ~~Requirement 补全~~ → Step 3.5
- ~~Trigger 补全~~ → Step 3.5

## 4. Step 3.5：依赖图

### 4.1 阶段一：LLM 解析

输入：Step 3b 修正后的 interactions + events + auto_triggers

任务：将所有 entity 的 `requirement` 和 `trigger` 标准化为结构化 JSON：

```json
{
  "dependencies": [
    {
      "entity_id": "I3",
      "requires": [
        {"type": "interaction", "id": "I1", "condition": "completed"},
        {"type": "event", "id": "E2", "condition": "triggered"},
        {"type": "item", "name": "手电筒", "condition": "possess"}
      ]
    }
  ]
}
```

允许的 `type`：
- `interaction` — 依赖另一个互动完成
- `event` — 依赖事件已/未触发
- `auto_trigger` — 依赖自动触发已/未触发
- `item` — 依赖持有特定物品

`condition` 可选值：`completed`, `not_completed`, `triggered`, `not_triggered`, `possess`, `not_possess`

### 4.2 阶段二：有向图构建（代码）

```python
class DependencyGraph:
    nodes: dict[str, DependencyNode]  # entity_id → node
    edges: list[DependencyEdge]       # source → target (source depends on target)

    def build(self, dependencies: list[dict]) -> None
    def detect_cycles(self) -> list[list[str]]  # 返回所有循环路径
    def cut_edge(self, edge: DependencyEdge) -> None  # 切断一条依赖
    def to_dict(self) -> dict  # 序列化供 game_loop 消费
    @classmethod
    def from_dict(cls, data: dict) -> "DependencyGraph"
```

### 4.3 循环检测 + Fallback

1. 构建有向图
2. 检测循环依赖（DFS）
3. 无循环 → 通过
4. 有循环 → 重调 LLM（最多 N 次）
5. N 次仍不解决 → 随机切断一条参与循环的边，记录 `_circular_cut: true`

### 4.4 依赖关系规则

- **三者可互相依赖**：interaction 可以依赖 event/auto_trigger，event 可以依赖 interaction/auto_trigger，auto_trigger 可以依赖 interaction/event
- `based_on` 仍然只指向 interaction（Step 2b 约束），`requires` 无此限制

## 5. Step 4（扩展后）

### 5.1 标准化对象

| # | 字段 | 库来源 |
|---|------|--------|
| 1 | enemy_ref | enemy library |
| 2 | weapon_ref | weapon library |
| 3 | type（技能名） | skill_checks.json |
| 4 | **stat_change.stat_name（属性名）** | **COC 标准属性集** |
| 5 | **side_effect 结构化** | **自然语言 → 结构化对象** |

### 5.2 COC 标准属性集

```
STR, CON, SIZ, DEX, APP, INT, POW, EDU, SAN, HP, LUCK, MP
```

来源：从 `skill_checks.json` 的 `linked_attribute` 字段提取，加上 COC 7th 核心衍生属性。

### 5.3 Side_effect 结构化

从 Step 3a 移入。类型：
- `item_gain`: `{"type": "item_gain", "item_name": "物品名"}`
- `stat_change`: `{"type": "stat_change", "stat_name": "属性名", "delta": -1, "narrative": "角色经历描述（可选）"}`。narrative 字段描述角色在 fiction 层面的经历，如"目睹不可名状之物后陷入短暂疯狂"，使 stat_change 可承载非数值化的角色状态变化（如恐惧、失忆、幻觉等），不必局限于数值增减
- `spawn_enemy`: `{"type": "spawn_enemy", "enemy_ref": "敌人名", "scene": "...", "trigger_condition": "...", "quantity": 1}`
- `grant_item`: `{"type": "grant_item", "item_ref": "武器/物品名", "scene": "..."}`
- `npc_state_change`: `{"type": "npc_state_change", "npc_name": "NPC名", "new_state": "新状态"}`
- 无法归入以上类型的直接保留字符串

### 5.4 SYNCHRONIZATION 提示词原则

- 标准化后的字段必须与库中名称完全一致
- stat_change 的属性名必须来自标准属性集；narrative 字段可选，描述角色经历
- side_effect 的结构化优先识别上述 5 种类型，其余保留字符串

## 6. 影响范围

### 6.1 layered_parser.py

| 函数 | 改动 |
|------|------|
| STEP3A_SYSTEM | 重写：去重 + 冲突 + 结局，去掉 side_effect/requirement 补全 |
| build_step3a_prompt | 重写：5 个任务，精简 prompt |
| STEP35_SYSTEM | **新增**：LLM 依赖解析 |
| build_step35_prompt | **新增**：输入所有 entity，输出标准化 dependencies |
| STEP4_SYSTEM | 更新：加 stat 标准化 + side_effect 结构化 |
| build_step4_prompt | 更新：加 stat_names 参数 + side_effect 任务 |

### 6.2 layered_pipeline.py

| 位置 | 改动 |
|------|------|
| Step 3a | 精简调用 |
| Step 3.5 | **新增**: LLM 解析 → 有向图构建 → 循环检测 → fallback |
| Step 4 | 扩展：side_effect 结构化 + stat 标准化 |

Step 3.5 和 Step 4 使用 `ThreadPoolExecutor` 并行。

### 6.3 新增文件

- `src/module_designer/dependency_graph.py` — `DependencyGraph` + `DependencyNode` + `DependencyEdge` 数据类

### 6.4 不影响的文件

- `l2_keeper.py`, `l2_template.json`, `l3_designer.py`, `l3_template.json`
- `scenario_core.py`（后续可选：game_loop 消费序列化图）
- `layered_schema.py`

### 6.5 Notebook

- Step 3a cell：更新
- Step 3.5 cell：**新增**（LLM 解析 + 图构建 + 循环检测）
- Step 4 cell：更新（side_effect 结构化 + stat 标准化）

## 7. 变更历史

- 2026-05-15: 初始版本 — 之前历次修改（统一实体格式, based_on, graded_result, ##END_##, WR0 等）
- 2026-05-15: 本次 — Step 3 重构 + Step 3.5 依赖图 + Step 4 扩展
