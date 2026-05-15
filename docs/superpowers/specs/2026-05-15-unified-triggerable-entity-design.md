# 统一可触发实体格式设计

**日期**: 2026-05-15
**状态**: 设计中
**范围**: `src/module_designer/` — 解析管线；不影响 `game_loop.py`

---

## 1. 目标

将 interaction / auto_trigger / event 统一为共享字段的可触发实体模型，简化解析管线的生成、消费和验证。

## 2. 核心理念

Step 2a 产出统一实体列表（全部归入 interactions 格式）。Step 2b 将其分为三类角色，用 `based_on` 标注派生关系：

```
Step 2a: 统一实体列表（interactions 格式）
    ↓
Step 2b: 分类 + 补充派生实体（并行）
    ├─ interaction:  玩家主动触发，有 scene，无 based_on
    ├─ auto_trigger: 系统被动触发，有 scene，based_on → interaction
    └─ event:        全局不可逆，无 scene，based_on → interaction
    ↓
Step 3a: 依赖解析 + 冲突兜底
Step 4:  Library 匹配 + 技能标准化
```

## 3. 统一字段模型

每个可触发实体：

| 字段 | 必需 | 说明 |
|------|------|------|
| `id` | ✓ | I1.. / AT1.. / E1.. 全局唯一 |
| `scene` | 条件 | interaction/auto_trigger 必需；event 为空 |
| `type` | ✓ | 关联技能名，不涉及填"无" |
| `name` | ✓ | 实体名称 |
| `requirement` | | 前置条件（自然语言，引用 interaction ID） |
| `trigger` | | 触发条件描述 |
| `result` | ✓ | 触发后结果描述（含线索信息、不可逆性等） |
| `side_effects` | | 自然语言字符串列表 |
| `enemy_ref` | | Step 4 填入，event 留空 |
| `weapon_ref` | | Step 4 填入，event 留空 |
| `difficulty` | | None / regular / hard / extreme |
| `based_on` | | 派生来源（只能指向 interaction ID） |

### 按实体类型的字段约束

| 实体 | scene | difficulty | enemy/weapon_ref | based_on |
|------|-------|-----------|-------------------|----------|
| interaction | ✓ | ✓ | ✓ | 空 |
| auto_trigger | ✓ | ✓ | ✓ | → interaction |
| event | ✗ | ✓ | ✗ | → interaction |

### 关键约束

- `based_on` 只能指向 interaction（Step 2a 的产物）。Step 2b 并行运行，event 和 auto_trigger 无法互引
- 两个 entity 冲突时，Step 3a 兜底解决
- event 的 `irreversible_impact`（旧字段）并入 `result`，prompt 需明确要求标注不可逆性

## 4. 旧→新字段映射

| 旧字段 | 新位置 | 说明 |
|--------|--------|------|
| `interaction.clue` | → `result` | 合并 |
| `auto_trigger.effect_type` | 删除 | 信息由 `result` + `side_effects` 覆盖 |
| `auto_trigger.effect_ref` | → `enemy_ref` / `weapon_ref` | 对齐 interaction |
| `auto_trigger.reveal_narrative` | → `result` | 合并 |
| `auto_trigger.trigger_condition` | → `trigger` | 重命名对齐 |
| `event.irreversible_impact` | → `result` | 合并，需标注不可逆性 |
| (新增) `based_on` | `based_on` | 派生来源 |

## 5. 影响范围

### 5.1 模板

- `data/templates/l2_template.json` — interactions/auto_triggers/events 改为统一格式，新增 `based_on`

### 5.2 数据模型

- `l2_keeper.py` — `AutoTrigger` 重构，新增 `based_on`，删除 `effect_type`/`effect_ref`/`reveal_narrative`
- `l3_designer.py` — 无影响（已在前序修改中完成）

### 5.3 Schema

- `layered_schema.py` — `L2_INTERACTION_SCHEMA` 新增 `based_on`；`L2_AUTO_TRIGGER_SCHEMA` 重构；`L2_EVENT_SCHEMA` 新增 `type`/`difficulty`/`based_on`，删除 `irreversible_impact`

### 5.4 解析器

- `layered_parser.py`:
  - Step 2a prompt: 补充 `based_on` 字段说明（始终为空）
  - Step 2b events prompt: 重写，输入 interactions 列表，输出 events 列表（含 `based_on`、`type`、`difficulty`）
  - Step 2b AT prompt: 重写，输入 interactions 列表，输出 auto_triggers 列表（含 `based_on`）
  - Step 3a prompt: 利用 `based_on` 整理依赖关系
  - Step 3b prompt: 无影响
  - Step 4 prompt: 扩展到 auto_triggers，加入 type 技能标准化

### 5.5 管线

- `layered_pipeline.py`:
  - Step 4: 对 auto_triggers 做 `enemy_ref`/`weapon_ref` 匹配（当前只对 interactions 做）
  - Step 4: 加入技能名标准化（用 skill_checks.json 的 45 项技能）
  - `_with_fallback` required_keys 保持 `["interactions"]`

### 5.6 不影响的文件

- `scenario_core.py` — `Edge`、`Interaction` 数据类不在本次范围
- `game_loop.py` — 不在范围
- `prompts.py` — 不在范围

## 6. Step 4 技能标准化

利用 `data/skill_checks.json` 中 45 项 COC 标准技能名，在 Step 4 prompt 中提供技能列表，让 LLM 将 `type` 中的技能名统一到标准名称（如 "侦查"→"侦察"）。逻辑与 enemy_ref/weapon_ref 库匹配一致。

## 7. 与之前修改的关系

本次修改和之前所有修改叠加后的完整管线：

```
Step 1a: meta + scenes + characters
Step 1b: condensed_text (含 enemies, locations_and_map 等新章节)
    ↓
Step 2a: 统一实体列表 (含 scene_movements, based_on 留空)
    ↓
Step 2b: events + auto_triggers (并行，分类并标注 based_on)
Step 2c: L1 + L3 (并行，L1 用 characters 指导 NPC 命名，L3 含 characters 字段)
    ↓
Step 3a: side_effects 结构化 + 依赖解析 (利用 based_on)
Step 3b: L1 ↔ L2 交叉核对
    ↓
Step 4: Library 匹配 + 技能标准化
    ↓
最终验证 + 保存
```

### 变更历史

- 2026-05-15: 初始版本 — Edge.requirement, Interaction.clue 移除, side_effects 自然语言化, scene_movements, L1/L3 characters
- 2026-05-15: 本次扩展 — 统一实体格式, based_on, auto_trigger/event 对齐, Step 4 技能标准化
