# Next Session — 管线总览 + 最终输出格式

**日期**: 2026-05-16
**分支**: main
**状态**: 管线全部就绪

---

## Pipeline 总览

```
模组文档 (.docx)
    ↓
Step 1a: 结构化提取 (meta + scenes + characters)
Step 1b: 精修模组 → condensed_text → chapters dict (按 ## 标题拆分)
    ↓
Step 2a: Interactions + scene_movements (统一实体格式, based_on 留空)
    ↓
Step 2b: Events + Auto-triggers (并行, based_on 指向派生的 interaction，非派生则留空)
Step 2c: L1 + L3 (并行, L1 用 characters 指导 NPC, L3 含 characters 行为设计)
    ↓
Step 3a: 去重 + 冲突 + 结局验证 (轻量 LLM)
Step 2.5: NPC 行为描述 (与 Step 3a 并行, 轻量 LLM)
    ↓
组装 L2 结构 (_assemble_l2)
    ↓
Step 3b: L1 ↔ L2 ↔ L3 交叉核对
    ↓
Step 3.5 + Phase 1: 并行
    ├─ 3.5: 依赖图 (requirement 标准化 → 有向图 → 循环检测)
    └─ Phase 1: 风格预判 (enemy/weapon 类型 + 数量范围)
    ↓
Phase 2: 精简标准化 (技能/属性/side_effect @标记化 + Phase 1 约束)
    ↓
最终验证 + 保存 L1/L2/L3 JSON
```

总 LLM 调用: **13 次** (Step 1:2 + Step 2:5 + Step 2.5:1 + Step 3:2 + 3.5+Phase 1:2 + Phase 2:1)

---

## Phase 1：风格预判

**职责**：与 Step 3.5 并行执行。根据完整模组文本，确定武器/敌人的风格方向和数量范围。约束宽松，只需符合背景设定，允许随机性。不做场景绑定。

**输出**：写入 L2 的 `_phase1` 字段，同时作为 Phase 2 的约束输入。

```json
{
  "_phase1": {
    "enemies": [
      {"enemy_ref": "Clicker", "min_count": 1, "max_count": 3}
    ],
    "weapons": [
      {"weapon_ref": "手电筒", "min_count": 0, "max_count": 3}
    ]
  }
}
```

## Phase 2：精简标准化

**职责**：替代原 Step 4。只传 entity 的 6 个相关字段（name, scene, type, result, graded_result, side_effects），去掉 id/requirement/trigger/difficulty/based_on。将 side_effects/result/graded_result 中的自然语言转化为 `@函数(参数=值)` 标记。

### @标记语法

五种标准函数，可嵌入 result / graded_result 各等级 / side_effects 等任何文本字段：

| 函数 | 参数 | 说明 |
|------|------|------|
| `@spawn_enemy` | enemy_ref, scene, quantity=1 | 生成敌人遭遇 |
| `@grant_weapon` | weapon_ref, scene="", quantity=1 | 授予标准化武器 |
| `@stat_change` | stat_name, delta=0, narrative="" | 属性/状态变化 |
| `@item_gain` | item_name | 获得物品（纯文本） |
| `@npc_state_change` | npc_name, new_state | NPC 状态变化 |

数量约束：spawn_enemy / grant_weapon 的 enemy_ref / weapon_ref 必须在 Phase 1 约束列表内，总调用次数不超过 max_count。

---

## Step 2.5：NPC 行为描述

**职责**：与 Step 3a 并行执行。基于 L3 characters（设计意图）、L1 npc_appearances（外貌/神态）和 L2 entity（NPC 参与的互动），为每个 NPC 生成行为描述档案。用于叙事增强。

**输出**：写入 L2 的 `npc_profiles` 字段。

```json
{
  "npc_profiles": {
    "京山人吉": {
      "name": "京山人吉",
      "role": "关键情报源 — 昏迷的乘务员",
      "what_they_can_do": "苏醒后提供驾驶室位置和Clicker弱点情报；若被巨口吞噬则触发乘务员牺牲事件",
      "interaction_triggers": ["调查员急救成功时苏醒", "调查员询问电车情况时提供情报"],
      "personality_notes": "冷静尽责但内心恐惧，声音微微颤抖",
      "appearance": "穿着制服的乘务员，面色苍白，昏迷不醒"
    }
  }
}
```

核心字段 `what_they_can_do` 回答"这个 NPC 能/会干什么"，让 KP 在运行时快速了解 NPC 的行为模式和触发条件。

---

## 最终输出格式

管线产出 3 个 JSON 文件，写入 `data/modules/<模组名>/`。

### l1_player.json — 玩家可见层

```json
{
  "6号车厢": {
    "description": "叙事文本，KP 可直接朗读（30-200字）",
    "atmosphere": "场景氛围一句话总结",
    "mood": "uneasy",
    "perceptible": [
      {
        "type": "object",
        "name": "便签",
        "brief": "贴在车门上的醒目便签",
        "linked_interaction": "阅读车门便签"
      }
    ],
    "ambient_hints": ["微妙的环境线索"],
    "npc_appearances": [
      {
        "name": "京山人吉",
        "brief": "穿着制服的乘务员，面色苍白",
        "demeanor": "昏迷不醒"
      }
    ]
  }
}
```

**字段含义**：
- `description`: 场景基本信息的叙事文本（KP 可直接朗读）
- `atmosphere`: 场景氛围一句话
- `mood`: 情绪基调 (confused/uneasy/tense/terrified/hopeful/desperate)
- `perceptible`: 无需检定即可感知的元素，`linked_interaction` 指向 L2 的 interaction name
- `ambient_hints`: 微妙的环境线索列表
- `npc_appearances`: 当前场景 NPC 外貌描述（仅可见信息，不含隐藏动机）

### l2_keeper.json — KP 守秘人层

```json
{
  "scenes": {
    "6号车厢": {
      "description": "场景描述（来自 L1 atmosphere）",
      "from_here": [{"target": "7号车厢", "method": "步行通过车门", "requirement": ""}],
      "to_here": [{"source": "5号车厢", "method": "步行通过车门", "requirement": ""}],
      "interactions": [
        {
          "name": "阅读车门便签",
          "scene": "6号车厢",
          "type": "无",
          "result": "便签上写着「只管前进吧 已经没有退路了」",
          "side_effects": ["意识到无路可退的氛围"],
          "graded_result": {
            "on_failure": "@stat_change(stat_name=\"SAN\", delta=-1)",
            "on_regular": "看清了便签内容",
            "on_hard": "看清便签内容且注意到纸张质地异常",
            "on_extreme": "完全理解便签含义"
          }
        }
      ],
      "auto_triggers": [
        {
          "name": "靠近后门闻到血腥味",
          "scene": "6号车厢",
          "type": "无",
          "result": "一股浓烈的血腥臭味从7号车厢飘来，令人作呕",
          "side_effects": []
        }
      ],
      "encounters": [],
      "scene_weapons": [],
      "from_here": [],
      "to_here": [],
      "extra": {}
    }
  },
  "events": [
    {
      "id": "E1",
      "type": "无",
      "name": "退路断绝",
      "result": "##END_坏结局:电车被吞噬##",
      "side_effects": []
    }
  ],
  "npc_profiles": {
    "京山人吉": {
      "name": "京山人吉",
      "role": "关键情报源",
      "what_they_can_do": "苏醒后提供情报",
      "interaction_triggers": ["急救成功时苏醒"],
      "personality_notes": "冷静尽责",
      "appearance": "穿着制服的乘务员，面色苍白"
    }
  },
  "dependency_graph": {
    "nodes": {"I1": {"entity_id": "I1", "entity_type": "interaction", "name": "阅读车门便签"}},
    "edges": [{"source": "I3", "target": "I1", "dep_type": "interaction", "condition": "completed"}],
    "_circular_cut": false, "_cut_info": null
  },
  "_phase1": {
    "enemies": [{"enemy_ref": "Clicker", "min_count": 1, "max_count": 3}],
    "weapons": [{"weapon_ref": "手电筒", "min_count": 0, "max_count": 3}]
  }
}
```

**术语约定**：interaction、auto_trigger、event 三者统称为 **entity（实体）**。

**Entity 字段含义**（最终输出中保留的完整字段）：

| 字段 | 含义 | 特殊值 |
|------|------|--------|
| `name` | 实体名称 | |
| `scene` | 所属场景中文名 | event 无此字段 |
| `type` | 关联技能名（标准 COC 45 项，Phase 2 标准化） | "无" 表示不涉及检定 |
| `result` | 直接结果（Phase 2 可含 @标记） | `##GRADED##` 表示在 graded_result 中；`##END_名称:简述##` 表示结局 |
| `side_effects` | 间接后果（Phase 2 @标记化） | `@函数(参数)` 标记字符串或自然语言 |
| `graded_result` | 分级检定后果（Phase 2 可含 @标记） | type != "无" 时填写 |
| `id` | 全局唯一标识 | I1../AT1../E1.. |
| `requirement` | 硬性前置条件 | |
| `trigger` | 触发场景描述 | |
| `difficulty` | 检定难度 | None/regular/hard/extreme |

**Phase 2 处理方式**：prompt 仅传前 6 个字段（name/scene/type/result/graded_result/side_effects）给 LLM 做标准化以节省 token。标准化结果通过 `_merge_phase2_fields` 合并回原始完整 entity（保留 id/requirement/trigger/difficulty 不变）。

**已从最终输出中移除的字段**：`based_on`、`enemy_ref`、`weapon_ref`。`based_on` 仅在 Step 2b/3a/3.5 内部做依赖推导，不进入最终 JSON。

**L2 顶层字段**：
- `scenes`: 按场景中文名分组的 entity + 通行路径 + 描述
- `events`: 全局不可逆事件列表（不绑定特定场景）
- `npc_profiles`: Step 2.5 生成的 NPC 行为描述档案（用于叙事增强）
- `dependency_graph`: Step 3.5 生成的依赖有向图（nodes + edges + 循环标记）
- `_phase1`: Phase 1 产出的武器/敌人约束

### l3_designer.json — 设计者层

```json
{
  "module_meta": {
    "title": "逃出无限电车", "author": "", "era": "2010s",
    "theme": "梦境逃脱与克苏鲁恐怖", "expected_duration": "单次团（3-4小时）", "player_count": "3-5人"
  },
  "world_rules": [
    {
      "id": "WR0", "name": "创作者豁免",
      "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
      "scope": ["meta"], "is_absolute": true
    }
  ],
  "scene_intents": {
    "6号车厢": {"purpose": "初始化场景", "key_threat": "未知与逐渐逼近的威胁感", "notes": ""}
  },
  "ending_conditions": [
    {"id": "END1", "condition": "加速逃脱", "narrative": "真结局——调查员冲破噩梦醒来"}
  ],
  "tone_constraints": {
    "genre": "克苏鲁恐怖",
    "forbidden": ["喜剧化", "轻松氛围"],
    "recommended": ["压迫感", "时间紧迫", "声音恐惧"],
    "narrative_style": "以调查员的感官体验为中心"
  },
  "characters": [
    {
      "id": "NPC_1", "name": "京山人吉",
      "behavior": "乘务员，在4号车厢昏迷。苏醒后提供驾驶室位置和怪物情报。叙事作用：情报传递"
    }
  ],
  "driving_force": "奈亚拉托提普的化身出于对电子游戏的热衷，将调查员拉入这场噩梦试炼"
}
```

**L3 字段含义**：
- `module_meta`: 模组元信息
- `world_rules`: 世界运行规则，WR0 由管线自动注入（创作者豁免）
- `scene_intents`: 每个场景的设计目的（key 为场景中文名）
- `ending_conditions`: 结局条件列表
- `tone_constraints`: 全局叙事护栏
- `characters`: NPC 的行为逻辑和叙事作用（设计意图层）
- `driving_force`: 一切事件的根本驱动力

---

## 特殊标记约定

| 标记 | 位置 | 含义 |
|------|------|------|
| `##GRADED##` | `result` 字段 | 实际结果在 `graded_result` 中 |
| `##END_名称:简述##` | `result` 字段开头 | 此实体会触发游戏结局 |
| `@函数名(参数=值)` | side_effects / result / graded_result | 运行时解析为 side_effect 类实例 |

## 已知预留位

`encounters` 和 `scene_weapons` 在 L2 场景中保留空数组占位。当前 pipeline 不填充这两个字段——敌人/武器信息通过 side_effects 中的 `@spawn_enemy` / `@grant_weapon` 标记承载，Phase 1 约束记录在 `_phase1` 中。
