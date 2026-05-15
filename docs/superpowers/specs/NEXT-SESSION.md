# Next Session — Step 4 详解 + 最终输出格式

**日期**: 2026-05-15
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
Step 2b: Events + Auto-triggers (并行, 分类并标注 based_on → interaction)
Step 2c: L1 + L3 (并行, L1 用 characters 指导 NPC, L3 含 characters 行为设计)
    ↓
Step 3a: 去重 + 冲突 + 结局验证 (轻量 LLM)
    ↓
Step 3b: L1 ↔ L2 ↔ L3 交叉核对
    ↓
Step 3.5 + Step 4: 并行
    ├─ 3.5: 依赖图 (requirement 标准化 → 有向图 → 循环检测)
    └─ 4:   标准化 (技能/属性/side_effect 结构化)
    ↓
最终验证 + 保存 L1/L2/L3 JSON
```

## Step 4 详解：标准化收口

**职责**：管线最后一步，将所有半结构化信息统一为标准格式。与 Step 3.5 并行执行。

### 输入

| 参数 | 来源 |
|------|------|
| `interactions` | Step 3a → 3b 修正后 |
| `auto_triggers` | Step 3a → 3b 修正后 |
| `l2_descriptions` | 从 L1 提取（entry_narrative 或 atmosphere） |
| `scene_intents` | L3 设计意图 |
| `chapters` | Step 1b 章节化文本 |
| `skill_names` | data/skill_checks.json 45 项 COC 标准技能 |
| `stat_names` | STR, CON, SIZ, DEX, APP, INT, POW, EDU, SAN, HP, LUCK, MP |

### 五个标准化任务

| # | 任务 | 说明 |
|---|------|------|
| 1 | `enemy_ref` 匹配 | 为 side_effects 中的 spawn_enemy 匹配敌人库 |
| 2 | `weapon_ref` 匹配 | 为 side_effects 中的 grant_item 匹配武器库 |
| 3 | `type` 技能标准化 | "侦查"→"侦察"，与 skill_checks.json 对齐 |
| 4 | `side_effect` 结构化 | 自然语言 → 结构化对象（见下方） |
| 5 | `stat_name` 标准化 | stat_change 的属性名对齐标准属性集 |

### side_effect 结构化类型

| 类型 | 格式 | 说明 |
|------|------|------|
| `item_gain` | `{"type":"item_gain", "item_name":"..."}` | 获得物品 |
| `stat_change` | `{"type":"stat_change", "stat_name":"SAN", "delta":-1, "narrative":"..."}` | 属性/状态变化，narrative 可选 |
| `spawn_enemy` | `{"type":"spawn_enemy", "enemy_ref":"深潜者", "scene":"7号车厢", "quantity":1}` | 敌人出现 |
| `grant_item` | `{"type":"grant_item", "item_ref":"手电筒", "scene":"6号车厢"}` | 授予武器/物品 |
| `npc_state_change` | `{"type":"npc_state_change", "npc_name":"京山人吉", "new_state":"死亡"}` | NPC 状态变化 |
| (string) | 保留原始字符串 | 无法归入以上类型的副作用 |

## 最终输出格式

管线产出 3 个 JSON 文件，写入 `data/modules/<模组名>/`。

### l1_player.json — 玩家可见层

```json
{
  "6号车厢": {
    "entry_narrative": "调查员们在此处醒来...",
    "atmosphere": "昏暗封闭的车厢，空气中弥漫着不自然的死寂",
    "mood": "uneasy",
    "perceptible": [
      {"type": "object", "name": "便签", "brief": "一张贴在门上的泛黄纸条",
       "linked_interaction": "阅读便签正面"}
    ],
    "ambient_hints": ["后方传来若有若无的震动"],
    "npc_appearances": [
      {"name": "京山人吉", "brief": "穿着制服的乘务员，面色苍白",
       "demeanor": "昏迷不醒"}
    ]
  }
}
```

**字段含义**：
- `entry_narrative`: KP 可直接朗读的场景入场文本
- `atmosphere`: 场景氛围一句话
- `mood`: 情绪基调 (confused/uneasy/tense/terrified/hopeful/desperate)
- `perceptible`: 无需检定即可感知的元素。`linked_interaction` 指向 L2 的 interaction name
- `ambient_hints`: 微妙的环境线索
- `npc_appearances`: 当前场景 NPC 外貌

### l2_keeper.json — KP 守秘人层

```json
{
  "scenes": {
    "6号车厢": {
      "description": "调查员们从沉睡中惊醒的初始地点...",
      "from_here": [{"target": "7号车厢", "method": "步行通过车门", "requirement": ""}],
      "to_here": [{"source": "5号车厢", "method": "步行通过车门", "requirement": ""}],
      "interactions": [
        {
          "id": "I1", "type": "侦察", "name": "阅读便签正面",
          "requirement": "", "trigger": "调查员注意到门上的便签",
          "result": "上面写着「只管前进吧 已经没有退路了」",
          "side_effects": ["发现关键提示信息"],
          "graded_result": {
            "on_failure": "字迹模糊无法辨认",
            "on_regular": "看清了便签内容",
            "on_hard": "看清便签内容且注意到纸张质地异常",
            "on_extreme": "完全理解便签含义，感知到警告"
          },
          "difficulty": "regular", "based_on": null
        }
      ],
      "auto_triggers": [
        {
          "id": "AT1", "type": "灵感", "name": "察觉后方异常",
          "scene": "6号车厢", "requirement": "",
          "trigger": "调查员在车厢内停留超过5分钟",
          "result": "##GRADED##",
          "side_effects": [],
          "graded_result": {
            "on_failure": "你隐约感到不安",
            "on_regular": "你察觉到后方传来的震动在缓慢靠近",
            "on_hard": "你意识到有东西正在从后方车厢吞噬一切",
            "on_extreme": "你清晰地感知到一张巨口正从后方逼近"
          },
          "difficulty": "regular", "based_on": "I1"
        }
      ],
      "encounters": [],
      "scene_weapons": [],
      "extra": {}
    }
  },
  "events": [
    {
      "id": "E1", "type": "无", "name": "巨口吞噬电车",
      "requirement": "interaction:I6", "trigger": "调查员触发7号车厢的后方观察",
      "result": "##END_坏结局:电车被吞噬## 不可逆：后方车厢被巨口完全吞没...",
      "side_effects": ["所有在后方车厢的调查员立即死亡"],
      "difficulty": "None", "based_on": "I6",
      "extra": {}
    }
  ],
  "npc_profiles": {
    "京山人吉": {
      "name": "京山人吉", "role": "关键情报源",
      "motivation": "保护乘客安全",
      "knowledge": ["怪物对声音敏感", "驾驶室钥匙在3号车厢"],
      "personality": "冷静但内心焦虑",
      "voice_notes": "声音微微颤抖",
      "notes": "在4号车厢被发现时处于昏迷状态",
      "extra": {}
    }
  }
}
```

**统一实体字段含义**（interaction / auto_trigger / event 共享）：

| 字段 | 含义 | 特殊值 |
|------|------|--------|
| `id` | 全局唯一标识 | I1.. / AT1.. / E1.. |
| `scene` | 所属场景中文名 | event 无此字段 |
| `type` | 关联技能名 | "侦察"、"急救"、"无" |
| `name` | 实体名称 | |
| `requirement` | 硬性前置条件（必须已完成的 ID 或持有的物品） | 无条件为空字符串 |
| `trigger` | 触发场景描述（什么情况下触发） | 与 requirement 不可混淆 |
| `result` | 直接结果 | `##GRADED##` 表示结果在 graded_result 中；`##END_名称:简述##` 表示结局 |
| `side_effects` | 间接后果（与 result 不重合） | 自然语言字符串列表，Step 4 后部分结构化 |
| `graded_result` | 分级检定后果 | type != "无" 时填写；四等级 on_failure/on_regular/on_hard/on_extreme |
| `difficulty` | 检定难度 | None / regular / hard / extreme |
| `based_on` | 派生来源 interaction ID | interaction 为 null；AT/event 指向派生的 interaction |

### l3_designer.json — 设计者层

```json
{
  "module_meta": {
    "title": "常暗之厢", "author": "", "era": "1920s",
    "theme": "封闭空间中的绝望逃亡", "expected_duration": "2-3小时", "player_count": "3-5"
  },
  "world_rules": [
    {
      "id": "WR0", "name": "创作者豁免",
      "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
      "scope": ["meta"], "is_absolute": true
    },
    {
      "id": "WR1", "name": "无路可退",
      "rule": "后方车厢被巨口吞噬，调查员只能向前探索",
      "scope": ["movement"], "is_absolute": true
    }
  ],
  "scene_intents": {
    "6号车厢": {"purpose": "苏醒点——建立基础恐慌和前进动机", "notes": "便签是关键线索引导"},
    "7号车厢": {"purpose": "恐怖展场——展示巨口的威胁", "key_threat": "巨口吞噬"}
  },
  "ending_conditions": [
    {"id": "END1", "condition": "加速逃脱", "narrative": "真结局——调查员冲破噩梦醒来"},
    {"id": "END2", "condition": "减速停车", "narrative": "坏结局——永远困在噩梦中"},
    {"id": "END3", "condition": "SAN归零", "narrative": "疯狂结局——调查员精神崩溃"}
  ],
  "tone_constraints": {
    "genre": "克苏鲁恐怖",
    "forbidden": ["喜剧化", "轻松氛围", "超现实解围"],
    "recommended": ["压迫感", "时间紧迫", "声音恐惧"],
    "narrative_style": "以调查员的感官体验为中心，强调狭窄空间的压迫感和不可名状的恐怖"
  },
  "characters": [
    {
      "id": "NPC_1", "name": "京山人吉",
      "behavior": "乘务员，在4号车厢昏迷。苏醒后会提供驾驶室位置和怪物情报。若调查员触发巨口吞噬，乘务员会为保护调查员而牺牲。叙事作用：情报传递 + 牺牲制造情感冲击"
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

### dependency_graph（Step 3.5 产物，嵌入 L2 数据）

```json
{
  "nodes": {
    "I1": {"entity_id": "I1", "entity_type": "interaction", "name": "阅读便签正面"},
    "I3": {"entity_id": "I3", "entity_type": "interaction", "name": "撕下便签查看背面"},
    "E1": {"entity_id": "E1", "entity_type": "event", "name": "巨口吞噬电车"}
  },
  "edges": [
    {"source": "I3", "target": "I1", "dep_type": "interaction", "condition": "completed"},
    {"source": "E1", "target": "I6", "dep_type": "interaction", "condition": "completed"}
  ],
  "_circular_cut": false, "_cut_info": null
}
```

**有向边含义**：source 依赖 target。如 I3→I1 表示"执行 I3 需要先完成 I1"。

## 特殊标记约定

| 标记 | 位置 | 含义 |
|------|------|------|
| `##GRADED##` | `result` 字段 | 实际结果在 `graded_result` 中，side_effects 为空 |
| `##END_名称:简述##` | `result` 字段开头 | 此实体会触发游戏结局 |

## 已知预留位

`encounters` 和 `scene_weapons` 在 L2 模板中保留空数组占位。当前 pipeline 不填充这两个字段——敌人/武器信息通过 `side_effects` 中的结构化对象（spawn_enemy / grant_item）承载，无需单独字段。
