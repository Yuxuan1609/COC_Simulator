# Parser 系统全面升级设计

**日期**: 2026-05-13
**状态**: 设计完成，待 spec → plan → execute
**基于**: `2026-05-12-parser-modification-briefing.md` + `2026-05-11-optimization-analysis.md`

---

## 一、动机与目标

### 当前局限

1. **信息扁平化**：所有模组信息（场景描述、NPC对话、线索、游戏机制）混在一起，LLM无法区分哪些是玩家可见的、哪些是KP才知道的、哪些是模组设计者的世界逻辑
2. **内容静态化**：模组JSON是parser的最终产物，游戏中无法动态生成新敌人、新物品、新线索
3. **无资源库**：武器和敌人数据仅存在于 investigator 端的 Weapon 数据类（玩家装备），没有KP端的怪物/武器资源库
4. **偏离轨道无响应**：当玩家行为超出模组JSON声明的交互范围时，只有简单的即兴叙事，无法动态生成游戏内容

### 核心目标

- **一键式模组导入**：LLM自动从模组文档解析三层信息，人工审核可选
- **运行时动态生成**：LLM根据L3（设计者意图）在游戏中自主生成L2（KP信息）和L1（玩家叙事）
- **结构化资源库**：独立的武器/敌人库，支持核心库+用户扩展包
- **高自由度**：KP/LLM可随时刷怪或发物资，受L3设计约束护栏

---

## 二、架构总览

### 新增包

```
src/
├── module_designer/            # 三层信息引擎
│   ├── __init__.py
│   ├── l1_player.py            # L1 玩家可见层数据模型
│   ├── l2_keeper.py            # L2 KP层（现有Interaction/Event对齐）
│   ├── l3_designer.py          # L3 设计者层数据模型 + 约束规则
│   ├── layered_parser.py       # LLM一键解析 → 三层JSON
│   ├── layered_pipeline.py     # 三层后处理管线
│   └── layered_schema.py       # JSON Schema定义 + 验证
│
├── library/                    # 武器/敌人资源库
│   ├── __init__.py
│   ├── weapons.py              # 武器数据类 + JSON加载器
│   ├── enemies.py              # 敌人数据类 + JSON加载器
│   ├── injector.py             # 离线预填充 + 运行时注入引擎
│   └── judgment.py             # 双层判定：T1确定性 + T2 LLM增强
```

### 重构文件

| 文件 | 改动性质 |
|------|----------|
| `src/scenario_core.py` | 新增 `SpawnEnemy` / `GrantItem` / `EncounterAnchor` 数据类，扩展现有 `Interaction.side_effects` |
| `src/parsers.py` | **废弃** — 由 `layered_parser.py` 直接输出三层JSON |
| `src/pipeline.py` | **废弃** — 由 `layered_parser.py` 直接输出三层JSON |
| `src/prompts.py` | 扩展：L1/L3感知的prompt构建，增强 `build_improvise_prompt` |
| `src/game_loop.py` | 适配：三层数据消费、偏离检测、双层判定调用、即兴注入 |

### 数据目录重组

```
data/
├── modules/                    # 按模组组织的三层数据
│   └── 常暗之厢/
│       ├── source.txt
│       ├── l1_player.json
│       ├── l2_keeper.json      # 现有 scene/event 数据对齐
│       ├── l3_designer.json
│       └── meta.json
├── library/
│   ├── core/
│   │   ├── weapons.json        # ~20核心武器
│   │   └── enemies.json        # ~30核心神话生物
│   └── extensions/             # 用户自定义扩展包
├── templates/                  # 三层JSON模板
│   ├── l1_template.json
│   ├── l2_template.json
│   └── l3_template.json
└── saves/                      # 存档（已有）
```

---

## 三、三层信息模型

### 数据流

```
离线（模组导入）：
  source.txt → layered_parser (LLM) → L1 + L2 + L3
                → injector.offline() → 填充武器/敌人引用到 L2
                → 人工审核（可选）

在线（游戏进行中）：
  L3 (🔒不可变) → LLM 基于 L3 生成动态 L2 → LLM 基于 L2 生成动态 L1
备注：只在特定场景下调用动态生成流程
```

### L1 — 玩家可见层

完全结构化。描述玩家在场景中的直接感知：氛围、可感知物品、NPC外貌、环境线索。

**职责**：
- 提供 entry_narrative（场景入场叙事）
- 提供 perceptible 列表（类型化感知元素：object/sound/smell/sight/touch）
- 提供 ambient_hints（环境暗示）
- 提供 mood 标签（LLM叙事生成的基调输入）

**生成方式**：
- 离线：layered_parser 从 source.txt 推断
- 在线：LLM 基于 L2.VisibleSet + L3.tone_constraints 动态生成/更新

### L2 — KP层

现有 `Interaction` / `GameEvent` / `Node` 结构对齐（**字段/schema对齐即可，内容不需匹配现有JSON数据文件**，后续跑通逻辑再调整内容）。包含所有游戏机制信息。

**扩展字段**（在现有基础上）：
- `interactions[].side_effects` — 已有，扩展 `SpawnEnemy` / `GrantItem` 类型
- `interactions[].skill_name` — 新增，关联技能名
- `interactions[].difficulty` — 新增，检定难度
- `encounters` — 新增，场景级敌人遭遇声明
- `scene_weapons` — 新增，场景中可获取的武器（常规物品由LLM自由处理）

**生成方式**：
- 离线：layered_parser 从 source.txt 解析（同现有 parsers.py 逻辑但对齐新字段）
- 在线：LLM 基于 L3 约束 + library 动态生成新 encounter/item

### L3 — 设计者层

完全结构化。描述模组设计者的世界观、逻辑链、设计意图。**运行时不可变**。

**核心字段**：
- `world_rules`：世界观规则（如"后方车厢被吞噬，只能前进"）
- `logic_chains`：逻辑链（如"获取钥匙 → 到达驾驶室 → 选择加速/减速"），含 branch_conditions
- `scene_intents`：每个场景的设计意图（purpose、emotion、danger_level、key_info）
- `ending_conditions`：结局条件及对应的叙事主题
- `tone_constraints`：基调约束（genre、forbidden主题、required元素）

**职责**：
- 约束L2的生成（不能生成违反世界规则的敌人/物品）
- 约束L1的生成（叙事必须符合基调和设计情绪）
- 偏离检测：评估玩家行为是否符合预期路径

---

## 四、三层约束接口

### L3 → L2 约束

```
L3.get_applicable_rules(scene, flags) → List[WorldRule]
L3.validate_spawn(enemy_type, scene) → bool
L3.evaluate_branch(chain_id, flags) → BranchState
L3.get_tone_context() → ToneConstraints
```

L2在生成任何新内容（spawn enemy, grant item）前必须通过L3验证。

### L2 → L1 约束

```
L2.get_visible(scene, perception_result) → VisibleSet
L2.filter_perceptible(scene, skill_level) → List[Perceptible]
L2.get_available_actions(scene, flags) → List[Interaction]
```

L1只能描述L2.VisibleSet范围内的感知元素。

### L3 → L1 直接约束

```
L3.get_mood_palette(scene) → MoodDirective
L3.sanitize_narrative(l1_text) → str
```

### 生成护栏（可开关）

- L2只能spawn **library中存在** 且 **L3允许** 的敌人
- L2只能grant **library中存在** 且 **L3逻辑链包含** 的物品
- L1只能描述 **L2.VisibleSet范围内** 的感知元素

---

## 五、武器/敌人库

### 武器数据模型

```python
@dataclass
class LibraryWeapon:
    name: str
    skill_name: str          # 关联技能
    damage: str              # 伤害公式
    range: str               # 射程
    shots: int               # 弹药/装填
    malfunction: int         # 故障值
    era: str                 # 年代（1920s/Modern/etc）
    rarity: str              # common/uncommon/rare
    special_rules: str       # 特殊规则（自然语言，供T2 LLM判断）
```

### 敌人数据模型

```python
@dataclass
class LibraryEnemy:
    name: str
    type: str                # 神话生物/丧尸/人类/etc
    attributes: dict         # STR, CON, SIZ, DEX, POW
    armor: str               # 护甲描述
    attacks: list[dict]      # [{name, damage, notes}]
    special_abilities: list[dict]  # [{name, desc}] 自然语言，供T2 LLM判断
    san_loss: str            # SAN损失公式
    combat_behavior: str     # 战斗行为描述（自然语言）
```

### 库结构

- **core/**：项目发布的精简核心库（~20武器 + ~30敌人），随版本更新
- **extensions/**：用户自定义JSON扩展包，KP可手动编辑添加

---

## 六、双层判定系统

### Tier 1 — 确定性引擎（始终启用）

- D100检定（已有 `roll_dice` / `check_skill`）
- 伤害公式计算（解析 "1D10+DB" 等）
- 装甲值比对
- SAN损失计算
- JSON数值 + 随机骰子，零token成本

### Tier 2 — LLM增强（可手动开关）

- 输入：T1结果 + 规则描述（special_rules / special_abilities / combat_behavior）+ 玩家意图 + 上下文
- LLM判定：战术动作修饰、怪物特殊能力效果、环境因素影响、叙事修饰
- 输出：修正后的判定结果 + 叙事描述

### 调用时机

- 战斗遭遇中使用 `library.judgment.resolve_combat(T1_result, enemy, weapon, context)`
- 特殊能力触发时使用 `library.judgment.resolve_ability(T1_result, ability, context)`

---

## 七、内容注入模块

### 离线注入（模组构建时）

- LLM 扫描 L3.scene_intents + L2 场景结构
- 识别需要敌人/物品的场景（danger_level 高 → 需要敌人声明）
- 从 library 中匹配（场景情绪/危险等级 → 合适的敌人类型/武器类型）
- 写入 L2 JSON 的 encounters/items 字段
- 可开关：`offline_injection` 配置项 默认开启

### 在线注入（游戏进行中）

- 触发条件：玩家行为偏离 L3 预期路径（deviation_score > threshold）
- LLM 判断需要增加/调整内容
- 查询 L3 约束 + library 库
- 动态 spawn enemy 或 grant item 到当前场景
- 可开关：`runtime_injection` 配置项
- 在运行时可通过特点代码调出方便调试

### 注入锚点类型

| 锚点类型 | 含义 | 触发方式 |
|----------|------|----------|
| `enemy_spawn` | 生成敌人遭遇 | 离线：L2声明 · 在线：LLM判断 |
| `item_grant` | 分发武器/物品 | 离线：L2声明 · 在线：LLM判断 |
| `encounter_zone` | 随机遭遇区域 | L3声明可刷怪 · LLM决定时机 |
| `loot_table` | 掉落表 | 场景/敌人关联可掉落物品列表 |

---

## 八、Game Loop 适配

### 阶段变化

| 阶段 | 现状 | 改动 |
|------|------|------|
| Phase 1 · 动作解析 | LLM解析意图 | 不改 |
| Phase 2 · 事件判定 | LLM判定 + 引擎确认 | 不改 |
| Phase 3 · 动作执行 | 执行 + side_effects | 扩展：SpawnEnemy / GrantItem |
| **Phase 3.5 · 偏离注入** | 不存在 | **新增** |
| Phase 4 · 事件执行 | 确定性触发 | 不改 |
| Phase 5 · 叙事生成 | LLM叙事 | 增强：L3约束 + L1结构化输出 |

### Phase 3.5 — 偏离检测 + 即兴注入

依赖现有的 `build_improvise_prompt` 路径（当 `all_other == True` 且 `!triggered_events` 时触发）：

1. `L3.evaluate_deviation(context)` → deviation_score
2. 如果 deviation_score > threshold **且** `runtime_injection` 开启：
   - `library.injector.runtime()` → 从库中spawn/grant
   - 调用增强的 `build_improvise_prompt()`（含L3约束 + 库上下文）
3. 否则：走现有 improvise 路径（不注入）

### Phase 5 — 叙事增强

`build_narrative_prompt()` 额外接收：
- `L1.atmosphere` + `L1.perceptible`（结构化感知信息）
- `L3.tone_constraints`（基调约束）
- `L3.scene_intents[scene].emotion`（设计情绪）
- 输出拆解为 L1 结构化更新 + 沉浸式叙事文本

---

## 九、动态生成触发路径

| 路径 | 触发者 | 时机 | 控制 |
|------|--------|------|------|
| A · 声明式 | JSON锚点 | 进入场景/完成前置 | 无LLM参与，确定性 |
| B · LLM自主 | 偏离检测 | deviation > threshold | `runtime_injection` 开关 |
| C · 手动命令 | /spawn命令 | KP/测试任意时刻 | 仅限调试 |

### 手动命令（预留）

| 命令 | 作用 |
|------|------|
| `/spawn enemy <name>` | 从库中生成指定敌人 |
| `/spawn weapon <name>` | 从库中生成指定武器 |
| `/spawn random` | 从L3允许的库中随机生成 |
| `/inject toggle` | 开关运行时注入 |
| `/inject status` | 查看注入状态 |

---

## 十、可开关控制点

| 开关 | 作用 | 默认 |
|------|------|------|
| `runtime_injection` | 在线注入总开关 | true |
| `tier2_llm_judgment` | 双层判定T2 | true |
| `offline_injection` | 离线注入开关 | true |
| `l3_guardrails` | L3护栏（关闭后LLM无约束） | true |
| `deviation_threshold` | 偏离触发敏感度（0.0-1.0） | 0.5 |

---

## 十一、实施顺序

1. **library 包** — 武器/敌人数据类 + core JSON + 加载器（无依赖，可独立开发测试）
2. **scenario_core 扩展** — SpawnEnemy / GrantItem / EncounterAnchor，对接 library（可独立开发测试）
3. **module_designer 包** — L1/L2/L3 数据类 + schema + 约束接口（依赖 scenario_core）
4. **layered_parser + layered_pipeline** — 一键解析 + 离线注入（依赖 library + module_designer）
5. **验证里程碑** — 完整跑通现阶段流程，确保l2层数据可被现有系统消费
6. **prompts 扩展** — L1/L3 感知 + improvise 增强
7. **game_loop 适配** — Phase 3.5 + Phase 5 增强 + /spawn 命令
8. **验证里程碑** — 完整跑通现阶段流程，确保所有数据可被现有系统消费
9. **parsers.py / pipeline.py 废弃** — 直接由 layered_parser 输出三层JSON，旧文件删除或归档
10. **notebooks 适配** — 新导入流程

---

## 十二、不纳入本轮范围

- COC SAN检定规则完整实现（StatChange仍仅记录）
- 战斗回合管线（Phase 3 → CombatRound → Phase 4）
- 存档的加密/校验/版本迁移
- 多模组管理界面
- 扩展包的社区分发机制
- 字段级详细设计（L1/L3的具体字段列表待后续spec细化）
