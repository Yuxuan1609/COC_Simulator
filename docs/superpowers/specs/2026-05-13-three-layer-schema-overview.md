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

L1 是玩家在场景中的**默认初始感知**——一个正常调查员第一次进入场景时无需任何检定即可感知的一切。由 layered_parser 离线生成充分内容，LLM 在运行时可以基于 L2 信息（检定结果、事件触发、NPC状态变化）动态覆盖或增强。

**L1 只描述无条件可见的内容**。条件感知（检定后可见、特定背景可见）归属 L2 的 Interaction/AutoTrigger。

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
| **环境暗示** | `ambient_hints` | list[string] | 微妙的环境线索（无条件的"直觉"类感知） |
| **NPC外貌** | `npc_appearances` | list[NPCAppearance] | 当前场景NPC的外貌描述（不含KP才知道的隐藏信息） |

### Perceptible 子结构

纯基础描述。深入调查由 L2 Interaction 接管，L1 不重复 Interaction 的 trigger 逻辑。

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | enum | object / sound / smell / sight / touch / intuition |
| `name` | string | 元素名称（如"门扉上的便签"） |
| `brief` | string | 一句话描述（玩家不深入调查时看到的内容） |
| `linked_interaction` | string? | 关联的 L2 interaction.name（可选，"调查此物→建议执行哪个互动"） |

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
  "events": [ EventL2 ],
  "npc_profiles": { "<npc_name>": NPCProfile }
}

// NPC 运行时状态不存储在 L2 JSON 中，
// 而是由 ScenarioWorld 管理：world.npc_states[npc_name] = state_string
// 通过 side_effect 类型 NPCStateChange 或 LLM 即兴生成来更新
```

### SceneL2 字段分类

| 类别 | 字段 | 类型 | 说明 |
|------|------|------|------|
| **基础** | `description` | string | 场景功能性描述（KP用） |
| **移动** | `from_here` | list[Edge] | 出边（同现有） |
| | `to_here` | list[Edge] | 入边（同现有） |
| **互动** | `interactions` | list[Interaction] | 可执行动作（扩展现有） |
| **遭遇** | `encounters` | list[Encounter] | 场景中预设的敌人遭遇 |
| **武器** | `scene_weapons` | list[SceneWeapon] | 场景中可获取的武器（常规物品由LLM自由处理） |
| **自动触发** | `auto_triggers` | list[AutoTrigger] | 被动触发事件（替代原 hidden_info） |
| **扩展** | `extra` | dict? | 预留扩展字段 |

### EventL2 子结构

沿用现有 `GameEvent` 数据类结构，预留扩展。

| 字段 | 类型 | 说明 | 状态 |
|------|------|------|------|
| `id` | string | 事件ID（如"E1"） | 已有 |
| `name` | string | 事件名称 | 已有 |
| `trigger` | string | 触发条件描述 | 已有 |
| `irreversible_impact` | string | 不可逆影响 | 已有 |
| `requirement` | list[Requirement] | 前置条件 | 已有 |
| `extra` | dict? | 预留扩展字段 | **新增** |

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
| `extra` | dict? | 预留扩展字段 |

### SceneWeapon 子结构

场景中可获取的**武器**。常规物品（手电筒、绳索等）由 LLM 在叙事中自由处理，不需要结构化数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `weapon_ref` | string | 引用 library/weapons 中的武器名 |
| `location` | string | 在场景中的位置描述 |
| `discovery_method` | string | 发现方式（如"侦查检定"、"乘务员告知"） |
| `extra` | dict? | 预留扩展字段 |

### AutoTrigger 子结构（替代原 HiddenInfo）

**定位**：被动触发事件。与 Interaction 的核心区别：

| | Interaction | AutoTrigger |
|---|---|---|
| 触发方式 | 玩家**主动选择**执行 | 系统**被动检测**条件 |
| 玩家感知 | 玩家知道自己做了这个动作 | 类似"暗骰"——玩家不知道有信息被揭示 |
| 触发条件 | 玩家输入匹配 trigger | 角色背景、属性值、flags 等自动满足 |
| 典型场景 | "我要搜查桌面" | 进入场景且持有钥匙时自动触发怪物遭遇 |

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 唯一标识 (AT1, AT2...) |
| `name` | string | 名称 |
| `scene` | string | 生效场景 ID (S1, S2...) |
| `trigger_condition` | string | 触发条件（自然语言，如"调查员进入7号车厢且持有钥匙"） |
| `effect_type` | string | 效果类型：reveal_info / spawn_enemy / grant_weapon / npc_state_change |
| `effect_ref` | string | 引用目标（enemy 名/weapon 名/NPC 名，Step 4 填入） |
| `reveal_narrative` | string | 揭示时的叙事文本（仅 reveal_info 类型） |
| `extra` | dict? | 预留扩展字段 |

> **2026-05-14 更新**: HiddenInfo 已废弃，替换为 AutoTrigger。AutoTrigger 统一了原 hidden_info（被动揭示）和 spawn/grant 机制为单一事件类型。

### NPCProfile 子结构

NPC 的完整 KP 侧信息。与 L1 的 `NPCAppearance`（玩家看到的）互补。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | NPC名称 |
| `role` | string | 在故事中的角色（如"关键情报源"、"潜在威胁"） |
| `motivation` | string | 核心动机/欲望（此人想要什么、怕什么） |
| `knowledge` | list[string] | NPC知道的关键信息 |
| `personality` | string | 性格简述（供 LLM 维持角色一致性） |
| `voice_notes` | string? | 说话风格备注（可选，供 LLM 模仿口吻） |
| `notes` | string? | 额外KP备注 |
| `extra` | dict? | 预留扩展字段 |

NPC 的运行时状态（如"昏迷"、"死亡"、"已对话"）不存储在静态 JSON 中，而是由 `ScenarioWorld.npc_states` 管理，通过新的 side_effect 类型 `NPCStateChange` 或 LLM 即兴生成来更新。NPC 与场景的关联通过 `interactions` 中的 NPC 名称引用来实现。

---

## 三、L3 设计者层

### 定位

描述模组的**设计意图和世界规则**。运行时不可变。是 LLM 动态生成 L2/L1 时的"宪法"。

### 顶层结构

```
l3_designer.json = {
  "module_meta": ModuleMeta,
  "world_rules": list[WorldRule],
  "scene_intents": { "<scene_name>": SceneIntent },
  "ending_conditions": list[EndingCondition],
  "tone_constraints": ToneConstraints,
  "driving_force": string    ← 一切事件的根本驱动力（"为什么这一切在发生"）
}
```

> **2026-05-14 更新**: `logic_chains` 已移除。逻辑链信息由 Step 3a 的 LLM 依赖解析从 events/interactions 中推断。

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

### SceneIntent 子结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `purpose` | string | 此场景在模组中的作用 |
| `key_threat` | string? | 核心威胁/敌人（如有） |
| `notes` | string? | 设计备注 |

> **2026-05-14 更新**: 移除了 `emotion`、`danger_level`、`key_info`、`exit_leads_to`。这些信息由 LLM 从 context 中动态推断，不需要离线固化。

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
| `recommended` | list[string] | 建议包含的元素/主题 |
| `narrative_style` | string | 叙事风格指引（如"第二人称、现在时、感官描写丰富"） |

---

## 四、层间引用关系

```
L1.perceptible[N].linked_interaction  ──引用──→  L2.interactions[N].name
L2.encounters[N].enemy_ref            ──引用──→  library/enemies.json items[N].name
L2.scene_weapons[N].weapon_ref        ──引用──→  library/weapons.json items[N].name
L2.auto_triggers[N].effect_ref        ──引用──→  library/enemies[N].name / library/weapons[N].name
L2.interactions[N].requirement        ──引用──→  L2.events[N].id / L2.interactions[N].name / flags
```

> **2026-05-14 更新**: 移除了 HiddenInfo 和 LogicChain 引用。AutoTrigger 的 effect_ref 由 Step 4 library 匹配填入。

---

## 五、当前状态

1. **L3 字段**: ✓ 已精简（logic_chains 移除，scene_intents 精简，narrative_theme→narrative，required→recommended）
2. **L2 字段**: ✓ HiddenInfo → AutoTrigger
3. **解析器**: ✓ 四步渐进式流程已实施
4. 编写 JSON Schema 验证规则
5. 创建对应的 Python 数据类
6. 设计兜底策略：LLM生成违反L3护栏的内容时的处理方案（拒绝重试/静默删除/警告）
7. 设计测试策略：每模块的验证场景和检查清单
