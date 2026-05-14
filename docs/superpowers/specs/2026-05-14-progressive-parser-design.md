# 四步渐进式解析流程设计

**日期**: 2026-05-14
**来源**: 2026-05-13 NEXT-SESSION Q1-Q5 确认 + brainstorming
**状态**: 设计完成，待实施

---

## 一、设计目标

替代当前 `layered_parser.py` 的一次性三层生成模式，改为四步渐进解析。核心改进：

- **名称固化**：Step 1 统一场景/NPC 命名，彻底解决当前 L1/L2/L3 独立调用导致场景名不一致的问题
- **依赖分级**：先产出基础内容（有 ID），再补全引用关系，降低单次 LLM prompt 复杂度
- **Library 匹配**：注入武器/敌人库列表，LLM 从库中选择，不再自创不存在的名称
- **保底策略**：每步产出一旦格式/内容不合格，重调（可配次数）→ 仍失败则基于可解析内容写 JSON 并标记缺失

---

## 二、全景数据流

```
source.txt / .docx
    │
    ├── Step 1a (1 call) ──────────────┐
    │   结构化提取:                      │
    │   module_meta + scenes[{name,id}]  │
    │   + characters[{name,id}]          │
    │                                    │  并行
    ├── Step 1b (1 call) ──────────────┘
    │   精修模组:
    │   condensed_text (半结构化 markdown)
    │   去噪 + 理顺 + 可扩写，不压缩信息
    │
    ▼  Step 2a (1 call, 先跑)
    interactions: 全部互动列表
    产出 interaction IDs + flag 名称 + requirement 声明
    enemy_ref/weapon_ref 留空占位
    │
    ├── Step 2b (2 calls, 并行)
    │   events: 全局不可逆事件
    │   auto_triggers: 替代原 hidden_info
    │   均注入 Step 2a 的 interaction IDs + flag 名称
    │
    ├── Step 2c (2 calls, 并行)
    │   L1: 玩家可见层
    │   L3: 设计者层 (基于新 l3_template.json)
    │   独立提取，不依赖其他 Step 2 产物
    │
    ▼  Step 3a (1 call)
    L2 依赖解析:
    interaction/event/auto_trigger 的 requirement 补全
    flag 名称统一，依赖链补全
    │
    ▼  Step 3b (1 call) — 依赖 3a 输出，串行
    L1 ↔ L2 交叉核对:
    linked_interaction 名称校对
    场景名一致性，L3 scene_intents 覆盖检查
    │
    ▼  Step 4 (1 call)
    Library 匹配:
    注入武器/敌人库列表 + L2 scene descriptions + condensed_text
    从库中选择填入 interactions 和 auto_triggers 的占位符
    不允许自创名称
    │
    ▼
data/modules/<模组>/
├── l1_player.json
├── l2_keeper.json  (完整，含 interactions + events + auto_triggers + scene_weapons + encounters)
└── l3_designer.json
```

**总计**: 10 LLM calls / 6 串行步。

---

## 三、Step 1 — 元信息提取 + 名称固化 + 精修模组

### 输入
- 原始模组文档

### 调用方案
- 2 次 LLM 调用，**并行**

### Step 1a: 结构化提取

**输出**:
```json
{
  "module_meta": {"title": "...", "era": "1920s", "theme": "..."},
  "characters": [
    {"name": "京山人吉", "id": "NPC_1"},
    {"name": "乘务员", "id": "NPC_2"}
  ],
  "scenes": [
    {"name": "6号车厢", "id": "S1"},
    {"name": "7号车厢", "id": "S2"}
  ]
}
```

### Step 1b: 精修模组

**输出**:
```json
{
  "condensed_text": "## module_overview\n...\n\n## scenes\n- S1: 6号车厢 ...\n- S2: 7号车厢 ...\n\n## npcs\n- NPC_1: 京山人吉 ...\n\n## clues_and_items\n- 钥匙在3号车厢第三个箱子里\n\n## events_summary\n- ..."
}
```

**condensed_text 格式**: 半结构化 markdown，固定章节标题：
- `## module_overview` — 模组全局概述
- `## scenes` — 每场景关键信息（以 S1/S2 等 ID 标识）
- `## npcs` — NPC 信息（以 NPC_1/NPC_2 等 ID 标识）
- `## clues_and_items` — 关键线索和物品清单
- `## events_summary` — 事件概要

每节内自由文本，以完整、流畅的叙事行文呈现。不压缩信息量，保留所有关键实体的叙事性描述（而非仅列表化提取）。去除原作者备注等非模组本体内容；原文模糊、不连贯或不合理处可基于上下文扩写和衔接，确保产出是一篇可直接阅读的完整模组文本，而非摘要碎片。

### 内容校验
- 格式：合法 JSON、`scenes` 非空数组、`condensed_text` 非空字符串
- 内容：每个 scene 有 `id` 和 `name`、每个 character 有 `id` 和 `name`、`condensed_text` 含上述章节标题

---

## 四、Step 2 — 内容生成

### 共同输入
- Step 1 的 `condensed_text` + `scenes` 名称/ID 列表

### Step 2a: Interactions（先跑）

**1 LLM call**

**输出**: 按场景组织的 interactions 列表：
| 字段 | 说明 |
|------|------|
| `id` | 唯一标识 (I1, I2...) |
| `scene` | 所属场景 ID (S1, S2...) |
| `type` | 互动类型 |
| `name` | 互动名称 |
| `requirement` | 前置条件**声明**（自然语言，Step 3 补全引用） |
| `trigger` | 触发描述 |
| `result` | 结果描述 |
| `clue` | 线索 (可选) |
| `side_effects` | 副作用列表，flag 首次命名即固化 |
| `enemy_ref` | **留空占位**（Step 4 填） |
| `weapon_ref` | **留空占位**（Step 4 填） |
| `skill_name` | 关联技能 (可选) |
| `difficulty` | 检定难度 (regular/hard/extreme) |

### Step 2b: Events + Auto-triggers（并行）

**2 LLM calls，并行**

**输入**: condensed_text + scenes 列表 + **Step 2a 产出的全部 interactions（含 ID + name + flag 名称）**

**Events 输出**:
| 字段 | 说明 |
|------|------|
| `id` | E1, E2... |
| `name` | 事件名称 |
| `trigger` | 触发条件描述（自然语言） |
| `irreversible_impact` | 不可逆影响 |
| `requirement` | 声明式（自然语言引用已知 interaction/flag/event，Step 3 补全） |

**Auto-triggers 输出** (替代原 hidden_info):
| 字段 | 说明 |
|------|------|
| `id` | AT1, AT2... |
| `name` | 名称 |
| `scene` | 生效场景 ID |
| `trigger_condition` | 触发条件（自然语言） |
| `effect_type` | reveal_info / spawn_enemy / grant_weapon / npc_state_change |
| `effect_ref` | 引用目标（**占位符，Step 4 填**） |
| `reveal_narrative` | 揭示叙事（仅 reveal_info） |

### Step 2c: L1 + L3（并行）

**2 LLM calls，并行**

L1: 从 condensed_text 提取玩家可见层，逻辑与现有 `parse_l1` 相同

L3: 从 condensed_text 提取设计者层，基于已更新的 l3_template.json：
- `module_meta`、`world_rules`、`scene_intents`、`ending_conditions`、`tone_constraints`、`driving_force`
- `tone_constraints` 字段：`genre` / `forbidden` / `recommended`（非 `required`） / `narrative_style`
- `ending_conditions` 字段：`id` / `condition` / `narrative`（非 `narrative_theme`）
- `scene_intents` 每场景：`purpose` / `key_threat` (可选) / `notes` (可选) — 去掉 `emotion`/`danger_level`/`key_info`/`exit_leads_to`

---

## 五、Step 3 — Cross-validate + 依赖补全

**2 次 LLM 串行调用**（3b 依赖 3a 修正后的 L2 名称）

### Step 3a: L2 依赖解析

**输入**: condensed_text + Step 2a(interactions) + Step 2b(events + auto_triggers)

| 任务 | 说明 |
|------|------|
| Flag 名称统一 | 合并语义相同的 flag（如 `flag:has_key` vs `flag:found_key`） |
| Interaction requirement 补全 | 自然语言声明 → 引用具体 interaction/event/flag |
| Event requirement 补全 | 同上 |
| Auto-trigger condition 补全 | 同上 |
| Interaction ↔ Event 依赖 | 互动的前置事件条件 |
| Interaction ↔ Auto-trigger 依赖 | 被动触发对互动的引用 |
| Interaction ↔ Interaction 依赖 | 同场景内互动执行顺序关系 |
| Event ↔ Event 依赖 | 事件链顺序 |

### Step 3b: L1 ↔ L2 交叉核对

**输入**: condensed_text + L1(原始) + Step 3a 输出(L2 已补全)

| 任务 | 说明 |
|------|------|
| L1 linked_interaction 校对 | 修正到 Step 3a 后的正确 interaction 名称 |
| 场景名一致性 | 检查 L1/L2/L3 场景名与 Step 1 的 scenes 列表一致 |
| L1 perceptible 关联 | 是否有感知元素应关联 L2 互动但未关联 |
| L3 scene_intents 覆盖 | 检查 L3 的 scene_intents key 是否覆盖所有场景 |
| 场景名不一致修正 | 三层的场景名与 Step 1 统一名称对齐 |

---

## 六、Step 4 — Library 匹配

**1 LLM call**

### 输入
- Step 3 输出的完整 L2（interactions + auto_triggers，含空占位符）
- L3 的 scene_intents
- L2 的 scene descriptions
- condensed_text (精修后原文，可选参考)
- Library 简要列表（prompt 注入）：

```
可用敌人: Clicker (盲感怪物, 2点装甲), 深潜者 (两栖, 1点鳞片), 食尸鬼 (食腐),
          修格斯 (变形吞噬生物), 狂信徒 (人类, 可理智沟通)
可用武器: .45自动手枪 (1D10+2, 1920s), 手电筒 (钝器1D3), 消防斧 (1D8+2), ...
```

### 任务
从库中选择合适的敌人/武器填入所有占位符。不允许自创名称。若原文主题无匹配，显式标记"无可匹配"而非编造。

### 输出
- interactions: `enemy_ref` / `weapon_ref` 已填值或标记
- auto_triggers: `effect_ref` 已填值或标记

---

## 七、保底策略

### 整体原则

```
每一步产出
  → [格式关]: 合法 JSON, 顶层结构符合预期
  → [内容关]: 必需字段不空, ID 唯一性
  → 通过 → 进入下一步
  ↓ 失败
  重调 LLM (最多 N 次, N 可配置)
  → 通过 → 进入下一步
  ↓ 用尽
  保底提取: 基于可解析内容写 JSON
  - 能解析的部分原样写入
  - 无法解析的字段放空值 ("", [], {})
  - 标记缺失 (后续 Step 可尝试补全)
  → 进入下一步
```

### 各步骤内容关

| Step | 必需断言 |
|------|---------|
| 1a | scenes 非空数组, 每个 scene 有 id+name, characters 每个有 id+name |
| 1b | condensed_text 非空, 含 `## scenes` 章节标题 |
| 2a | interaction 列表非空, 每个有 id+name+scene |
| 2b | events 列表 (可为空), auto_triggers 列表 (可为空), 每个有 id+name |
| 2c | L1: 每个场景有 entry_narrative; L3: module_meta + world_rules 不为空 |
| 3a/3b | 合法 JSON 输出 (语义修正失败不视为内容失败 — 保留原始引用) |
| 4 | 合法 JSON 输出 |

### 重试次数
- N 可配置，默认 3
- 重试时 model/temperature 不变

---

## 八、文件变更清单

| 文件 | 变更 | 破坏性 |
|------|------|--------|
| `src/module_designer/layered_parser.py` | **核心重写** — 旧 `parse_module()` 替换为 4 步入口 + 各步 prompt builder | 高 |
| `src/module_designer/layered_pipeline.py` | **重写** — 交叉引用确定性验证保留，对接 Step 3b 后验证；管线改为 step-by-step 编排 | 中 |
| `src/module_designer/layered_schema.py` | 同步 L3 模板变更；新增 auto_trigger 结构 schema；`hidden_info` schema 移除 | 中 |
| `src/module_designer/l3_designer.py` | 字段同步：`narrative_theme→narrative`、`required→recommended`；移除 `logic_chains`、`SceneIntent.emotion`/`danger_level`/`key_info`/`exit_leads_to` | 中 |
| `src/module_designer/l2_keeper.py` | 移除 `HiddenInfo`；`SceneL2` 新增 `auto_triggers` 字段 | 中 |
| `data/templates/l2_template.json` | 移除 `hidden_info`；新增 `auto_triggers`；events 新增字段 | 低 |
| `data/templates/l3_template.json` | 已由用户修改 ✓ | — |
| `tests/test_module_designer.py` | 新增各 Step prompt 构建测试、保底策略测试 | 低 |

---

## 九、待定项（不在本 session 范围）

| 项 | 说明 |
|----|------|
| Step 1 内容关细化 | "每个 scene 有 name/id" 以外，是否需要更细的 condensed_text 质量检查 |
| auto_trigger condition 运行时解析 | 自然语言 condition 在 game_loop 中如何评估（runtime 端的事） |
| 重试次数 N 调整 | 默认 3，运行后根据实际 LLM 表现调整 |
| 串行/并行调优 | 当前 6 串行步，Step 4 是否可与 Step 3b 尾段并行可后续微调 |
