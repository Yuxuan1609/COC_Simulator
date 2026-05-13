# 三层 JSON Schema 字段设计概述

**日期**: 2026-05-13
**状态**: 概述草稿，待逐层细化字段
**基于**: `2026-05-13-parser-system-overhaul-design.md`

---

## 设计原则

1. **每层只存本层信息** — L1 不包含游戏机制，L3 不包含具体叙事
2. **层间通过 ID 引用** — L1 引用 L2 的 interaction_id，L2 引用 L3 的 rule_id / chain_id
3. **LLM 可读可写** — 所有字段值都是自然语言或简单枚举，LLM 能理解、能生成
4. **确定性引擎可消费** — 关键数值字段（difficulty、damage、attributes）是结构化类型，不需要 LLM 解析
5. **可扩展** — 每个对象都有可选的 `notes` / `extra` 字段，用户可附加自定义数据

---

## 一、L1 玩家可见层

### 定位

描述玩家在场景中**直接感知**的一切。是 L2 信息的"视觉滤镜"——同一个 interaction 可能因检定结果不同而产生完全不同的 L1 输出。

### 顶层结构（按场景）

```
l1_player.json = {
  "<scene_name>": SceneL1
}
```

### SceneL1 字段分类

| 类别 | 字段 | 类型 | 说明 |
|------|------|------|------|
| **入场叙事** | `entry_narrative` | string | 玩家进入时的开场叙事（KP可直接朗读） |
| **氛围** | `atmosphere` | string | 场景的氛围一句话总结（如"昏暗封闭、空气中弥漫霉味"） |
| **情绪** | `mood` | enum | confused / uneasy / tense / terrified / hopeful / desperate |
| **可感知元素** | `perceptible` | list[Perceptible] | 玩家无需检定即可感知的物体/声音/气味等 |
| **环境暗示** | `ambient_hints` | list[string] | 不明显的环境线索（对应L2中 passive_perception 类的信息） |
| **NPC外貌** | `npc_appearances` | list[NPCAppearance] | 当前场景NPC的外貌描述（不含KP才知道的隐藏信息） |

### Perceptible 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | enum | object / sound / smell / sight / touch / intuition |
| `name` | string | 元素名称（如"门扉上的便签"） |
| `brief` | string | 一句话描述（玩家不深入调查时看到的内容） |
| `detail_trigger` | string | 触发深入描述的玩家行为（如"走近查看"、"仔细聆听"） |
| `linked_interaction` | string | 关联的 L2 interaction.name（可选，用于"调查此物→触发互动"的关联） |

### NPCAppearance 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | NPC名称 |
| `brief` | string | 外貌一句话描述 |
| `demeanor` | string | 神态/举止描述 |

---

## 二、L2 KP 守秘人层

### 定位

包含游戏机制的**完整真相**。KP 用这一层来裁决玩家行动。现有 `Interaction`/`GameEvent`/`Node` 结构属于这一层。

### 顶层结构

```
l2_keeper.json = {
  "scenes": { "<scene_name>": SceneL2 },
  "events": [ EventL2 ]
}
```

### SceneL2 字段分类

| 类别 | 字段 | 类型 | 说明 |
|------|------|------|------|
| **基础** | `description` | string | 场景功能性描述（KP用） |
| **移动** | `from_here` | list[Edge] | 出边（同现有） |
| | `to_here` | list[Edge] | 入边（同现有） |
| **互动** | `interactions` | list[Interaction] | 可执行动作（扩展现有） |
| **遭遇** | `encounters` | list[Encounter] | 场景中预设的敌人遭遇 |
| **物品** | `scene_items` | list[SceneItem] | 场景中可获取的物品 |
| **隐藏信息** | `hidden_info` | list[HiddenInfo] | 需要特定检定才能发现的信息 |

### Interaction 扩展字段（在现有基础上）

| 字段 | 类型 | 说明 | 状态 |
|------|------|------|------|
| `type` | string | 互动类型 | 已有 |
| `name` | string | 互动名称 | 已有 |
| `requirement` | list[Requirement] | 前置条件 | 已有 |
| `trigger` | string | 触发描述 | 已有 |
| `result` | string | 结果描述 | 已有 |
| `clue` | string? | 线索 | 已有 |
| `side_effects` | list[SideEffect] | 副作用 | 已有，需扩展 |
| `skill_name` | string? | 关联技能名 | **新增** |
| `difficulty` | string | 检定难度 regular/hard/extreme | **新增** |

### Encounter 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `enemy_ref` | string | 引用 library/enemies 中的敌人名 |
| `trigger_condition` | string | 触发条件描述 |
| `initial_behavior` | string | 初始行为描述 |
| `quantity` | int | 数量（默认1） |
| `notes` | string? | 额外备注 |

### SceneItem 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_ref` | string | 引用 library/weapons 中的物品名或自定义物品名 |
| `location` | string | 在场景中的位置描述 |
| `discovery_method` | string | 发现方式（如"侦查检定"、"乘务员告知"） |

### HiddenInfo 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `info` | string | 隐藏信息内容 |
| `reveal_condition` | string | 揭示条件描述 |
| `linked_skill` | string? | 关联技能 |

---

## 三、L3 设计者层

### 定位

描述模组的**设计意图、世界规则、逻辑链**。运行时不可变。是 LLM 动态生成 L2/L1 时的"宪法"。

### 顶层结构

```
l3_designer.json = {
  "module_meta": ModuleMeta,
  "world_rules": list[WorldRule],
  "logic_chains": list[LogicChain],
  "scene_intents": { "<scene_name>": SceneIntent },
  "ending_conditions": list[EndingCondition],
  "tone_constraints": ToneConstraints
}
```

### ModuleMeta 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | string | 模组标题 |
| `author` | string | 作者 |
| `era` | string | 年代设定（1920s/Modern/etc） |
| `theme` | string | 核心主题（如"无路可退的恐怖箱庭"） |
| `expected_duration` | string | 预计游戏时长 |
| `player_count` | string | 建议玩家人数 |

### WorldRule 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 规则ID（如"WR1"） |
| `name` | string | 规则名称 |
| `rule` | string | 规则描述（自然语言，供LLM理解和遵循） |
| `scope` | list[string] | 影响范围（movement/combat/stealth/investigation/dialogue） |
| `is_absolute` | bool | 是否为绝对规则（true=不可违反，false=可被LLM在极端情况下打破） |

### LogicChain 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 逻辑链ID（如"LC1"） |
| `name` | string | 逻辑链名称 |
| `description` | string | 一句话描述 |
| `nodes` | list[string] | 逻辑节点（按顺序的里程碑） |
| `branches` | list[Branch] | 分支条件 |
| `is_critical` | bool | 是否为主线（true=必须推进，false=可选支线） |

### Branch 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `condition` | string | 触发条件表达式（如"flag:has_crew"、"!flag:has_key"） |
| `effect` | string | 条件满足时的效果描述 |
| `next_node` | string? | 跳转到哪个节点 |

### SceneIntent 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `purpose` | string | 此场景在模组中的作用 |
| `emotion` | string | 目标情绪 |
| `danger_level` | enum | safe / low / medium / high / extreme |
| `key_info` | list[string] | 此场景必须传达的关键信息 |
| `key_threat` | string? | 核心威胁/敌人（如有） |
| `exit_leads_to` | list[string] | 离开后可能前往的场景 |
| `notes` | string? | 设计备注 |

### EndingCondition 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 结局ID（如"END1"） |
| `type` | enum | escape / trapped / madness / sacrifice / revelation |
| `condition` | string | 触发条件表达式 |
| `narrative_theme` | string | 结局叙事主题 |

### ToneConstraints 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `genre` | string | 类型标签（如"克苏鲁恐怖箱庭"） |
| `forbidden` | list[string] | 禁止出现的元素/主题 |
| `required` | list[string] | 必须包含的元素/主题 |
| `narrative_style` | string | 叙事风格指引（如"第二人称、现在时、感官描写丰富"） |

---

## 四、层间引用关系

```
L1.perceptible[N].linked_interaction  ──引用──→  L2.scenes[S].interactions[N].name
L2.encounters[N].enemy_ref            ──引用──→  library/enemies.json items[N].name
L2.scene_items[N].item_ref            ──引用──→  library/weapons.json items[N].name
L2.hidden_info[N].reveal_condition    ──引用──→  L3.world_rules[N].id
L2.interactions[N].requirement[M]     ──引用──→  L2.events[N].id / L2.interactions[N].name
L3.logic_chains[N].branches[M].condition ──引用→  world.flags / L2.events[N].id
```

---

## 五、下一步

1. 逐层确认字段：L1 → L2 → L3，每次只讨论一层
2. 确定每个字段的"可空性"（optional vs required）
3. 确定枚举值的完整列表
4. 编写 JSON Schema 验证规则
5. 创建对应的 Python 数据类
