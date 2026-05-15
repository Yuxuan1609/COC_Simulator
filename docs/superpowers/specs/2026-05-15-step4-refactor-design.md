# Step 4 重构设计

**日期**: 2026-05-15
**状态**: 设计中
**范围**: `src/module_designer/` 解析管线 Step 4；不影响 `scenario_core.py` / `game_loop.py`

---

## 1. 目标

将当前单一臃肿的 Step 4 LLM 调用拆分为 Phase 1（风格预判）+ Phase 2（精简标准化），引入 `@函数(参数)` 标记语法替代结构化 JSON side_effect，清理 `based_on` 等冗余字段。

## 2. 新管线流程

```
Step 3a → _assemble_l2 → Step 3b → Step 3.5 + Phase 1 + Phase 2
                                        ├─ 3.5: 依赖图 (不变)
                                        ├─ Phase 1: 风格预判 (新增, 并行)
                                        └─ Phase 2: 精简标准化 (替代原 Step 4)
```

Phase 1 和 Step 3.5 并行执行，Phase 2 串行在 Phase 1 之后（需要 Phase 1 的约束输出）。

## 3. Phase 1：风格预判

### 3.1 输入

| 参数 | 来源 |
|------|------|
| chapters（尤其 `enemies` 章节） | Step 1b |
| L3 scene_intents | Step 2c |
| weapon_library_names | 武器库 |
| enemy_library_names | 敌人库 |

### 3.2 LLM 任务

根据模组背景，确定武器/敌人的风格方向和数量范围。约束宽松，只需符合背景设定，允许随机性。不做场景绑定——跑团中任何场景都可能触发。

### 3.3 输出格式

```json
{
  "enemies": [
    {"enemy_ref": "深潜者", "min_count": 0, "max_count": 2}
  ],
  "weapons": [
    {"weapon_ref": "手电筒", "min_count": 1, "max_count": 1}
  ]
}
```

字段：`enemy_ref` / `weapon_ref` 必须来自库列表，不可自创。`min_count` 为最小出现次数（可为 0），`max_count` 为最大出现次数。

### 3.4 消费方式

- 写入 L2 的 `encounters` / `scene_weapons` 数组（直接替换原有空占位）
- 作为 Phase 2 prompt 的约束输入，限制 side_effect 中的 spawn_enemy / grant_weapon 数量和类型

## 4. Phase 2：精简标准化

### 4.1 输入

每个 entity 只传 6 个字段：

| 保留字段 | 原因 |
|----------|------|
| `name` | 实体识别，知道在处理什么 |
| `scene` | 场景上下文，辅助位置判断 |
| `type` | 标准化目标 |
| `result` | 区分直接结果 vs 间接后果 |
| `graded_result` | `##GRADED##` 时的真实结果 |
| `side_effects` | 结构化目标 |

去掉：`id`、`requirement`、`trigger`、`difficulty`、`based_on`

附加上下文：Phase 1 约束 + 场景描述 + 库名列表 + 标准技能列表 + 标准属性列表

### 4.2 LLM 任务

1. **type 标准化**：从标准技能列表中选最匹配的技能名。不涉及检定的保持"无"。
2. **side_effect 结构化**：自然语言 → `@函数(参数=值)` 标记字符串
3. **stat_name 标准化**：对齐标准属性集（STR/CON/SIZ/DEX/APP/INT/POW/EDU/SAN/HP/LUCK/MP）

### 4.3 输出格式

输出完整的 entity dict（仅含上述 6 个字段），side_effects 为标记字符串数组。Phase 2 的输出直接替换 assembled L2 中对应 entity 的 dict（保持 scene 分组结构不变）：

```json
{
  "interactions": [
    {
      "name": "观察后方",
      "scene": "7号车厢",
      "type": "侦察",
      "result": "##GRADED##",
      "graded_result": {
        "on_failure": "@stat_change(stat_name=\"SAN\", delta=-1, narrative=\"看到不可名状之物的一角\")",
        "on_regular": "@spawn_enemy(enemy_ref=\"大嘴吞噬者\", scene=\"7号车厢\", quantity=1)",
        "on_hard": "你看到了后方的巨口但保持了冷静",
        "on_extreme": "你完全理解了后方的威胁并找到了最佳逃生路线"
      },
      "side_effects": ["@stat_change(stat_name=\"SAN\", delta=-1)"]
    }
  ],
  "auto_triggers": [...]
}
```

## 5. @标记语法

### 5.1 规范

```
@函数名(参数名=值, ...)
```

- 参数值可用双引号包裹（含空格或特殊字符时）
- 多个参数用 `, ` 分隔
- 可嵌入 `result`、`side_effects`、`graded_result` 各等级、`scene` 描述等任何文本字段

### 5.2 五种标准函数

| 函数 | 参数 | 说明 |
|------|------|------|
| `@spawn_enemy` | enemy_ref, scene, quantity=1 | 生成敌人遭遇。enemy_ref 必须来自 Phase 1 约束列表 |
| `@grant_weapon` | weapon_ref, scene="", quantity=1 | 授予武器。weapon_ref 必须来自 Phase 1 约束列表 |
| `@stat_change` | stat_name, delta=0, narrative="" | 属性/状态变化。stat_name 必须是标准属性名 |
| `@item_gain` | item_name | 获得物品，纯文本描述 |
| `@npc_state_change` | npc_name, new_state | NPC 状态变化 |

### 5.3 数量约束

spawn_enemy 和 grant_weapon 的总调用次数不得超过 Phase 1 中对应条目的 `max_count`。

### 5.4 Runtime 解析（后续实现）

字符串以 `@` 开头 → 正则提取函数名和参数 → 路由到 `scenario_core.py` 中的对应 dataclass。当前暂不修改 `scenario_core.py` / `game_loop.py`。

## 6. based_on 清理

- Step 4 prompt 不传 `based_on`，LLM 输出不含 `based_on`
- 最终保存的 L2 JSON 不含 `based_on`
- `based_on` 仍在 Step 2b/3a/3.5 内部用于依赖推导，仅不进入最终产物

## 7. 影响范围

### 7.1 layered_parser.py

| 函数 | 改动 |
|------|------|
| PHASE1_SYSTEM | **新增**：风格预判系统提示 |
| build_phase1_prompt | **新增**：Phase 1 prompt builder |
| STEP4_SYSTEM | 重写：去掉 enemy_ref/weapon_ref 匹配，加 @语法 + Phase 1 约束 |
| build_step4_prompt | 重写：精简 entity 字段，加 Phase 1 约束，@语法模板 |

### 7.2 layered_pipeline.py

| 位置 | 改动 |
|------|------|
| Step 3.5 + Phase 1 + Phase 2 | 调整并行策略：3.5 ∥ Phase 1，然后 Phase 2 |
| `_assemble_l2` | 注入 Phase 1 产出的 encounters/scene_weapons |
| `based_on` | 最终保存时 strip |

### 7.3 不变

- `l1_player.py`、`l3_designer.py`、`dependency_graph.py`
- `scenario_core.py`、`game_loop.py`（@解析延后）
- `l2_template.json`（encounters/scene_weapons 已有结构可用）
- `layered_schema.py`

### 7.4 Notebook

- Phase 1 cell：新增（与 Step 3.5 并行后）
- Step 4 cell：更新为 Phase 2（精简 prompt，@语法）

## 8. 变更历史

- 2026-05-15: 初始版本
