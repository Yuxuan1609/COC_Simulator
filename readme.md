# TRPG 调查员助手

基于 LLM 的 TRPG（桌上角色扮演游戏）KP 助手，以《常暗之厢》模组为测试用例，实现从玩家输入到沉浸式叙事生成的完整调用链。COC 7th 规则。

## 项目结构

```
.
├── data/
│   ├── abstract.txt                         # 模组背景设定（供叙事参考）
│   ├── occupations.json                     # COC 7th 标准职业数据
│   ├── skill_checks.json                    # COC 7th 45 项技能定义（名称、关联属性、基础值、分类）
│   ├── library/
│   │   ├── core/
│   │   │   ├── weapons.json                 # 核心武器库（10 件）
│   │   │   ├── enemies.json                 # 核心敌人库（4 种神话生物/人类，含 [flag] 标记）
│   │   │   └── bosses.json                  # 核心 Boss 库（3 种剧情敌人，含 boss_mechanics）
│   │   └── extensions/                      # 用户自定义武器/敌人扩展包
│   ├── templates/
│   │   ├── l1_template.json                 # L1 玩家可见层模板
│   │   ├── l2_template.json                 # L2 KP 守秘人层模板
│   │   ├── l3_template.json                 # L3 设计者层模板
│   │   ├── scene.json                       # 场景模板
│   │   └── event.json                       # 事件模板
│   ├── modules/
│   │   ├── 常暗之厢/                           # 主测试模组
│   │   ├── 深渊之口/                           # 新模组
│   │   ├── test/                              # 单元测试用模组
│   │   └── supplements/                       # 补充管线输出（Author StructuralEdit）
├── src/
│   ├── scenario_core.py                     # 数据类、有向图、世界状态 Facade、记忆管理、Entity/##GRADED##/##END_
│   ├── llm.py                               # DeepSeek API 封装（可配置模型、思考模式）
│   ├── trpg_display.py                      # Notebook UI 显示组件
│   ├── utils.py                             # 文件解析、Token 估算、掷骰、技能定义加载
│   ├── prompts.py                           # LLM Prompt 构建器（Keeper/Narrator/Author/CombatEntry/Standoff/StatNarrative/ConsumeFuzzy）
│   ├── game_loop.py                         # 多 Agent 入口：init_game() + run_turn() + continue_standoff()
│   ├── game/                                # Multi-Agent 游戏循环
│   │   ├── messages.py                      #   消息 dataclass（NarratorBrief, CombatEntryCheck, CombatInit, CombatResult 等）
│   │   ├── side_effects.py                  #   Side effect dataclass（7 种）+ @markup 解析器（纯函数）
│   │   ├── clock.py                         #   GameClock — 确定性分钟计时器（day/hour/time_of_day）
│   │   ├── judge.py                         #   确定性闸门（需求 + 技能检定 + @markup + ##GRADED##）
│   │   ├── curator.py                       #   策展器：outcomes → NarratorBrief
│   │   ├── combat.py                        #   CombatSystem：COC 7th 回合制战斗（独立于 Keeper 管线）
│   │   ├── enemy_manager.py                 #   EnemyInstance + EnemyManager：敌人追踪层
│   │   ├── boss_manager.py                  #   BossManager：Boss 信息挂钩 + CombatInit 构造（不参与 spawn）
│   │   ├── npc_manager.py                   #   NPC + NPCManager：NPC 全量管理（对话/态度/跟随/序列化）
│   │   ├── intent_detector.py               #   意图检测器（Parse other → Author trigger）
│   │   └── agents/
│   │       ├── keeper.py                    #   KP 守秘人（回合编配：parse→judge→enrich∥combat_entry→standoff→curate）
│   │       ├── narrator.py                  #   叙事者（唯一面向玩家，L1 + NarratorBrief → 叙事）
│   │       ├── author.py                    #   作者（L3 + AuthorRequest → ModulePatch/StructuralEdit）
│   │       └── time_agent.py               #   TimeAgent — 轻量 LLM 时间评估器（读 Clock，不写 Clock）
│   ├── library/                             # 武器/敌人资源库
│   │   ├── weapons.py                       #   LibraryWeapon + WeaponLibrary
│   │   ├── enemies.py                       #   LibraryEnemy（含 [flag] 解析）+ EnemyLibrary
│   │   ├── bosses.py                       #   LibraryBoss + BossLibrary
│   │   ├── judgment.py                      #   双层判定引擎（T1 确定性 + T2 LLM 增强）
│   │   └── injector.py                      #   内容注入（离线预填充 + 运行时动态注入）
│   ├── module_designer/                     # 三层信息引擎
│   │   ├── l1_player.py                     #   L1 玩家可见层数据模型
│   │   ├── l2_keeper.py                     #   L2 KP 守秘人层数据模型 (含 AutoTrigger)
│   │   ├── l3_designer.py                   #   L3 设计者层数据模型
│   │   ├── layered_schema.py                #   JSON Schema 定义 + 三层验证
│   │   ├── layered_parser.py                #   渐进式解析 (prompt builders + system prompts，含 Phase 2 7 种 @markup)
│   │   ├── layered_pipeline.py              #   管线编排 (并行 + retry/fallback + 最终验证)
│   │   ├── supplement_pipeline.py           #   补充管线（Author StructuralEdit 触发）
│   │   └── dependency_graph.py              #   依赖有向图 (构建 + 循环检测)
│   └── investigator/                        # COC 7th 调查员车卡系统
│       ├── __init__.py                      # 公开 API
│       ├── models.py                        # 数据类 + 技能检定 + 战斗预留 + ItemManager + modify_stat
│       ├── rules.py                         # COC 7th 规则引擎（纯函数）
│       └── serialization.py                 # JSON 序列化 / 反序列化
├── frontend/
│   ├── server.py                            # 车卡服务器 + LLM 描述生成 API
│   ├── character.html                       # 5 步车卡向导
│   ├── character.css                        # COC 1920s 美学风格
│   ├── character.js                         # 车卡交互逻辑（含 /llm 触发）
│   ├── game_server.py                       # 游戏循环 Web 服务器
│   └── game.html                            # 游戏循环 Web 前端
├── run_pipeline.py                          # 管线 CLI 入口（配置向导 + 手动/自动模式）
├── notebooks/
│   ├── notebook_simplified.ipynb            # 主游戏循环（导入 src/ 模块）
│   ├── parser_test.ipynb                    # 管线驱动与测试（交互式）
│   └── _parser_layered_export.py            # 管线一键运行脚本（命令行可执行）
├── docs/
│   └── superpowers/
│       ├── specs/                           # 设计文档（含 combat-entry-detection-design）
│       └── plans/                           # 实现计划（含 combat-entry-detection-plan）
├── logs/                                    # Prompt 日志（每次运行生成，含技能检定记录）
└── .env                                     # DeepSeek API Key（不纳入版本控制）
```

## 核心模块

### `scenario_core.py`

纯 Python 数据模块，不依赖 LLM 或 UI。一级 Facade 组合 5 个子系统。

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Entity`（统一 entity）、`Requirement`（前置条件）、`ActionResult`（统一返回类型）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态 Facade —— 当前位置、已触发事件、已完成交互、runtime_state/dependency_graph。挂载子系统：
  - `clock: GameClock` — 确定性分钟计时器（`game_time`/`day`/`hour`/`time_of_day`/`advance_time()`）
  - `memory: MemoryManager` — 分层记忆（近期原始记录 + 远期压缩摘要 + 关键发现追踪）
  - `enemies: EnemyManager` — 敌人实例追踪层
  - `npcs: NPCManager` — NPC 全量管理
  - `bosses: BossManager` — Boss 遭遇管理
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪
- **##GRADED## / ##END_**：分级检定结果 + 结局嵌入

> Side effect dataclass（7 种）和 @markup 解析器已迁至 `src/game/side_effects.py`。

### `src/game/` — Multi-Agent 游戏循环

2026-05-16 重构。4-Agent 架构替代单体 `handle_user_input()`：

| Agent | 层 | 职责 | 文件 |
|-------|----|------|------|
| Keeper | L2 | 回合编配：parse→judge→enrich∥combat_entry→standoff→curate | `src/game/agents/keeper.py` |
| Narrator | L1 | 唯一面向玩家，生成沉浸式叙事 | `src/game/agents/narrator.py` |
| Author | L3 | 两级响应：Patch（填缺口）/ StructuralEdit（触发补充管线），WR0 独立可配 | `src/game/agents/author.py` |
| IntentDetector | — | Parse 命中 other 时并行检测是否存在实际叙事意图 | `src/game/intent_detector.py` |

**支持系统**：
- **Side Effects**（`side_effects.py`）：7 种 dataclass（ItemGain/ConsumeItem/StatChange/SpawnEnemy/GrantWeapon/NPCStateChange/NPCFollow）+ `parse_markup()`/`parse_markup_all()` 纯函数解析器
- **GameClock**（`clock.py`）：确定性分钟计时器 — `game_time`/`day`/`hour`/`time_of_day`/`advance_time()`/`get_time_flags()`。不做 LLM 调用
- **TimeAgent**（`agents/time_agent.py`）：轻量 LLM 时间评估器 — 读 Clock 状态，评估额外时间消耗，不写 Clock。Author 管理叙事时间压力
- **Judge**（`judge.py`）：确定性闸门 — requirement 检查 + COC 7th D100 检定 + ##GRADED## 分级 + LLM 失败惩罚 + trait enhancement
- **Curator**（`curator.py`）：策展器 — outcomes + ambient → NarratorBrief
- **CombatSystem**（`combat.py`）：COC 7th 回合制战斗，独立于 Keeper 管线。接收 CombatInit，返回 CombatResult
- **EnemyManager**（`enemy_manager.py`）：纯追踪层 — 敌人实例管理、位置/状态/flag 查询、combat entry 上下文
- **BossManager**（`boss_manager.py`）：Boss 信息管理 — 不参与 spawn，从 L2 预设 `boss_encounters` + `BossLibrary` 构造 CombatInit，特殊机制走自然语言 `boss_mechanics`
- **NPCManager**（`npc_manager.py`）：NPC 全量管理 — LLM 对话（态度/记忆上下文注入）、5 级态度状态机、被动跟随（`@npc_follow` markup）、初始化从 L2 `npc_profiles`
- **Combat Entry Detection**（keeper.py 内）：确定性闸门（active enemy in range）→ LLM 判定（flash，与 enrich 并行）→ CombatEntryCheck
- **对峙阶段**（keeper.py 内）：avoidable 敌人 → 语义匹配 LLM → D100 检定 → trait enhancement

**数据流**：

```
玩家输入 → parse(LLM) → judge(确定) → [enrich(LLM) ∥ combat_entry(LLM)] → [对峙(可选)] → curate → narrator(LLM) → 输出
                                           ↓ other+有意义                                         ↓ enter_combat
                                      Author(LLM)                                          CombatSystem
                                      ├─ Patch → integrate → 递归                          ├─ 战斗回合循环
                                      ├─ Structural → supplement pipeline                  └─ CombatResult → EnemyManager.exit_combat
                                      └─ Reject → 注入提示
```

入口：`init_game()` 加载所有 JSON + EnemyLibrary + WeaponLibrary + 初始化三 Agent，`run_turn()` 驱动每回合。
仅 `keeper.world` 暴露 ScenarioWorld，L3 数据内聚在 Author。

**Enricher（`src/game/agents/keeper.py:642-657` + `src/prompts.py:495-544`）**：

parse → judge 之后、curate → narrator 之前的软缓冲层。职责是**合并润色**——将分散的实体触发结果（含成功和失败）转化为连贯的叙事段落，但不做任何裁决或状态变更。

- **输入**：`judged_entities`（修复后包含失败实体，含失败惩罚叙事）、`user_input`、`world.build_snapshot()`（世界状态/场景现状/时间块）
- **输出**：`{"results": "合并叙事", "reasoning": "整合逻辑", "emphasis_hint": "叙事方向"}`
- **覆写规则**（2026-05-22 修复）：enrich 结果只覆写第一个**成功且非 AT** 的 outcome.message，失败实体的惩罚叙事不受影响。失败实体的 result 如含明确后果（扣血/刷怪等）则保留原文入叙事，仅当 result 为简单"检定失败"时才改为晦涩模糊。
- **并行**：与 `combat_entry(LLM)` 和 `TimeAgent(LLM)` 在同一线程池中并行执行
- **提示词**见上方 `丰富后的enrich提示词` 章节详细展示

**输出管线分离**：`skill_detail`（检定骰值、难度递增标记、失败惩罚标记）和 `TimeAgent` 的时间信息走独立输出管线（CLI `skill_results` + 日志 `skill_checks.txt`），不经过 Narrator。Narrator 仅接收已完成的叙事文本（`ActionOutcome.message`），保持"叙事者只叙事"的职责边界。

**CombatSystem（`src/game/combat.py`）**：
- 独立于 Keeper 管线，接收 `CombatInit`，返回 `CombatResult`
- 伤害掷骰（1D6+DB 等公式）、护甲减免、D100 技能检定（格斗/射击/闪避）
- 先攻排序、逐轮处理、玩家/敌人动作编排
- 10 个单元测试（`tests/test_combat.py`），combat harness 集成测试（`tests/test_combat_harness.py`）

### `src/library/` — 武器/敌人资源库

独立包，零外部依赖。提供结构化武器和敌人数据、双层判定引擎和内容注入。

- **WeaponLibrary / EnemyLibrary**：加载核心库 + 用户扩展 JSON，支持按年代/稀有度/类型/关键词搜索
- **EnemyLibrary**：`LibraryEnemy.from_dict()` 从 `combat_behavior` 前缀提取 `[flag]`（`adjacent_aware` / `avoidable`）
- **JudgmentEngine**：T1 确定性检定（D100 技能检定、伤害公式掷骰、SAN 损失计算）+ T2 LLM 增强上下文构建（可开关）
- **ContentInjector**：离线注入（模组构建时根据 L3 危险等级自动填充 encounter/weapon 槽位）+ 运行时动态注入

### `src/investigator/` — COC 7th 调查员车卡系统

- **`models.py`**：`Stats`（8 项核心属性 + LUCK）、`DerivedStats`、`Skill`（45 项 COC 标准技能）、`Occupation`、`Weapon`、`InventoryItem`、`ItemManager`、`Investigator`（主类，含 `check_skill()` / `modify_stat()` / `add_weapon()` / `item_manager`）
- **`rules.py`**：纯函数规则引擎 —— 掷骰生成、衍生属性计算、技能点分配、年龄修正、信用评级、DB 计算
- **`serialization.py`**：JSON 序列化/反序列化
- `combat_check()` / `damage_roll()` 已由 `src/game/combat.py` 的 CombatSystem 接管，旧 stub 已移除
- **默认测试角色卡**：`investigator/Sothoth_character` — 测试时使用的预设调查员，可针对性利用其角色特性（属性、技能、物品等）进行测试

### `src/module_designer/` — 三层信息引擎

渐进式解析流程（13 次 LLM 调用）：

1. Step 1a/1b — 结构化提取 + 精修模组 (2 并行)。Step 1a 同时输出敌人/武器/Boss 约束
2. Step 2a — Interactions + scene_movements
3. Step 2b/2c — Events + AT + L1 + L3 (4 并行)。AT 自动生成 AT_WORLD 世界初始化实体
4. Step 3a ∥ Step 2.5 ∥ Step_boss — 去重/冲突/结局验证 ∥ NPC 行为档案 ∥ Boss 遭遇实体 (3 并行)
5. 组装 L2 → Step 3b: L1↔L2↔L3 交叉核对
6. Step 3.5 — 依赖图构建 + 循环检测
7. Phase 2 — type 标准化 + side_effects → `@函数(参数)` (7 种：spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change/npc_follow)

每步含 `_with_fallback` 保底策略。详细过程见 `docs/superpowers/specs/NEXT-SESSION.md`。

### `prompts.py`

LLM Prompt 构建器。覆盖 Keeper parse/enrich、Narrator、Author、combat entry detection、standoff match、stat narrative、consume item fuzzy match、combat narrative。

### `game_loop.py` — 入口

- `init_game()`：加载 L1/L2/L3 JSON + EnemyLibrary/WeaponLibrary/BossLibrary → 构建 DirectedGraph → ScenarioWorld（初始化 GameClock/EnemyManager/NPCManager/BossManager）→ Keeper/Narrator/Author
- `run_turn()`：驱动回合，处理 debug 命令 → `keeper.process_turn()` → 检测 `combat_init` → `CombatSystem.run_combat()` → `narrator.narrate()` → 返回 `{brief, narrative, full, combat, standoff_prompt}`
- `continue_standoff()`：处理对峙阶段的玩家回避尝试 → 检测结果调用 CombatSystem → 返回 `{avoided, combat_init, message, combat_narrative}`

### 已知缺口

> G9/G10 已于 2026-05-23 修复。移入测试表。

### 待优化（按优先级）

| P | # | 问题 | 说明 |
|---|----|------|------|
| **1** | O6 | Harness 整合 — 集成测试 + LLM 模拟真人测试 | 整合现有 harness（parallel 16 case / stability 2 case / escalation 5 case）为统一测试入口。加入 LLM-as-player 模式：模拟真人的探索/对话/战斗行为，自动驱动多轮回合，检测异常路径（卡关、死循环、叙事断裂）。旧 `game_loop_harness.py` 待迁移 |
| **2** | O4 | 基于 Escalation 修改轻量级管线 | Author Patch/StructuralEdit 轻量级 LLM 提示词质量不稳定。需结合 escalation 的 real-LLM 测试结果精修 prompt 模板，提升 Patch 命中率和 StructuralEdit 生成质量 |
| 3 | O5 | 时间系统 | ✅ 已修复 — `_resolve_time_delta` 移除，改为每轮单次 TimeAgent 调用（与 enrich 并行）。TA 接收本轮所有 action 摘要 + time_range + 玩家输入，统一评估总耗时。日志写入 `logs/<ts>/TimeAgent.txt` |
| 4 | O7 | 世界状态类 & 调查员类序列化 | 详见 `docs/superpowers/specs/2026-05-22-world-refactor-design.md`。子系统序列化 (G9/G10) 待修复 |
| 5 | O8 | parse → enrich → curate 链路缺少明确中间结构 | `judged_entities` / `action_summaries` 在 `process_turn` 中为局部裸 list[dict] 自由漂浮，无类型约束。建议引入 `EnrichInput` dataclass 封装传给 enrich 的完整上下文，降低未来管线修改引入 bug 的风险 |

### 待升级（不优先）

| # | 问题 | 说明 |
|----|------|------|
| U1 | Author 的 "other 行为" 缺乏意图消歧 | 玩家输入 "我想试试能不能跳过去" 可能意味（a）真正做动作需检定（b）仅 RP 描述。当前 IntentDetector 只判断"是否有意图"但不评分"意图对应哪个实体/是否需要检定"，导致 detect 的 false positive 触发不必要的 Author 调用。建议引入二次确认（如 Keeper 反问玩家"你要实际尝试吗？"）或实体匹配置信度阈值 |
| U2 | 缺少技能协同检定 | COC 7th 规则中的合作检定（多人共同尝试）和互补检定（用相关技能辅助）未实现。单调查员模组下无大碍，但限制未来多人扩展 |

## 设计文档

- Multi-Agent: `docs/superpowers/specs/2026-05-16-game-loop-multi-agent-design.md`
- Escalation 重设计: `docs/superpowers/specs/2026-05-19-escalation-redesign.md`
- 战斗进入/脱出判定: `docs/superpowers/specs/2026-05-19-combat-entry-detection-design.md`
- 时间系统: `docs/superpowers/specs/2026-05-19-time-system-design.md`
- 测试体系: `docs/superpowers/specs/2026-05-20-test-suites.md`
- Boss/剧情敌人 & NPC: `docs/superpowers/specs/2026-05-20-boss-npc-design.md`
- Implementation Plan: `docs/superpowers/plans/2026-05-20-boss-npc-plan.md`
- ScenarioWorld 重构: `docs/superpowers/specs/2026-05-22-world-refactor-design.md`
- **Cookbook 代码导航**: `docs/superpowers/guides/cookbook.md` — 每个模块标注文件-类/函数-功能拆解，供快速定位代码
- **模组创作指南**: `docs/superpowers/guides/module-authoring-guide.md` — 三层架构说明、源文档写法、@markup 系统、敌人/Boss/NPC 设计、叙事线/时间压力配置、写作检查清单

## 测试

| 文件 | 覆盖范围 | 类型 |
|------|----------|------|
| `tests/test_clock.py` | 10 case — GameClock 默认值/推进/跨天/时段转换/时间标记/序列化/隔离 | 单元（确定） |
| `tests/test_time_system.py` | 8 case — GameClock 集成 world + time_costs 文件完整性 | 单元（确定） |
| `tests/test_enemy_manager.py` | 9 case — spawn/filter/group/combat lifecycle/range/context | 单元（确定） |
| `tests/test_combat_entry.py` | 6 case — SpawnEnemy→EnemyManager→combat lifecycle | 集成（确定） |
| `tests/test_combat.py` | 10 case — damage roll/armor/tier/combat state | 单元（确定） |
| `tests/test_combat_harness.py` | CombatSystem 完整战斗流程 | 集成（确定） |
| `tests/test_boss_library.py` | 3 case — BossLibrary 加载/查询/字段完整性 | 单元（确定） |
| `tests/test_boss_manager.py` | 6 case — engage_type 过滤/CombatInit 构造/active/set/resolve | 单元（确定） |
| `tests/test_npc_manager.py` | 6 case — 创建/对话/跟随同步/场景查询/状态变更/序列化 | 单元（确定） |
| `tests/test_library.py` | 18 case — WeaponLibrary/EnemyLibrary + flag 解析 | 单元（确定） |
| `tests/test_author_flow.py` + `tests/test_intent_detector.py` | 11 case — Detector→Author→Keeper 全链路（全 mock） | 单元 |
| `tests/test_escalation_harness.py` | 5 case — 正常/flavor/Patch/Reject/StructuralEdit | 集成（真实 LLM） |
| `tests/test_escalation_real.py` | 5 case — 真实 LLM 升级流测试，含完整 prompt/response 日志 | 集成（真实 LLM） |
| `tests/test_harness_parallel.py` | **NEW** — 16 case 并行，覆盖 search/检定/依赖链/AT/NPC/武器/move/对峙/战斗/道具/属性/结局，含 `--mock` 模式 | 集成（真实 LLM） |
| `tests/test_harness_stability.py` | **NEW** — 2 case 串行稳定性测试（正常探索 + 混合压力），3 轮/每轮 3 turn，含完整 LLM 日志 | 集成（真实 LLM） |
| `tests/test_failure_penalty.py` | **NEW** — 2 case 失败惩罚链路：Judge 生成→Keeper 保留→Narrator 接收，全 mock | 单元 |
| `tests/test_save_load_roundtrip.py` | **NEW** — 存档/读档全量 roundtrip：ItemManager/GameClock/EnemyManager/NPCManager/Memory | 集成 |
| `tests/game_loop_harness.py` | ⚠ 已弃用 — 7 轮旧 pipeline（绕过 Keeper.process_turn，使用废弃的 `apply_side_effects`），待迁移到新 harness | 集成（真实 LLM） |
| 其他 | test_judge, test_dependency_graph, test_directed_graph, test_entity, test_entity_resolvers, test_curator, test_integration, test_module_designer, test_markup | 单元 + 集成 |

**测试说明**：
- 测试数据：`data/modules/test/l*_test.json` 及 `data/modules/常暗之厢/l*_test.json`
- **Parallel Harness**：`python tests/test_harness_parallel.py`（16 case 并行），`--mock` 快速验证，`--cases search,npc_dialogue` 选择 case
- **Stability Harness**：`python tests/test_harness_stability.py`（2 case 串行），日志 → `data/debug/test_stability/<ts>/`
- Game Loop Harness（旧）：`cd tests && python game_loop_harness.py`（需 API Key），日志 → `data/debug/test_harness/<ts>/`

## @markup 副效果系统（7 种）

| 标记 | 效果 | 应用路径 |
|------|------|----------|
| `@spawn_enemy(enemy_ref="", scene="", quantity=1)` | 生成敌人实例 | EnemyManager.spawn() → combat entry detection |
| `@grant_weapon(weapon_ref="", scene="", quantity=1)` | 武器放置到场景 | SceneWeapon → search 发现 → 确认拾取 → Investigator.add_weapon |
| `@stat_change(stat_name="", delta=-1, narrative="")` | 修改属性 + 更新描述 | Investigator.modify_stat() + LLM narrative 描述更新 |
| `@item_gain(item_name="", quantity=1)` | 获得物品 | ItemManager.add(name, quantity) |
| `@consume_item(item_name="", quantity=1)` | 消耗物品 | ItemManager.remove() + LLM 模糊匹配保底 |
| `@npc_state_change(npc_name="", new_state="")` | NPC 状态变化 | NPCManager.set_state() |
| `@npc_follow(npc_name="", follow=true/false)` | 设置 NPC 跟随状态 | NPCManager.set_following() |

## 失败惩罚系统

多次鉴定同一实体失败时触发三层递增惩罚（`src/game/judge.py:173-225`）：

| 失败次数 | 惩罚 | 说明 |
|----------|------|------|
| **第 1 次** | 难度递增 | 该实体鉴定难度永久提升一级（`regular`→`hard`→`extreme`），记录在 `NodeRuntimeState.escalated_difficulty` |
| **第 2 次** | 无额外惩罚 | 仅递增 `retries` 计数 |
| **第 3 次及以后** | LLM 创意惩罚 | 调用 `evaluate_failure_penalty()`（`src/llm.py:344-422`），生成失败叙事 + 可选 @markup 副作用（扣HP/SAN、刷怪、NPC变敌对等） |

**惩罚数据流**：

```
Judge._execute_entity()
  ├── 失败 → escalate_difficulty（首次）/ retries++
  ├── retries>=2 → evaluate_failure_penalty(LLM) → {narrative, markup_effects}
  │                  ├── narrative → ActionOutcome.message
  │                  └── markup_effects → parse_markup_all() → ActionOutcome.side_effects
  ├── Keeper._apply_side_effects() → 世界状态变更（扣血/刷敌/物品等）
  └── Keeper._enrich() → 合并叙事（含惩罚叙事）→ Curator → Narrator → 玩家
```

**状态追踪**（`src/scenario_core.py:201-207`）：
```python
@dataclass
class NodeRuntimeState:
    completed: bool
    result_tier: str       # fumble|failure|regular|hard|extreme
    retries: int           # 失败重试次数
    escalated_difficulty: str  # 持久化的难度提升
```
每个实体一份状态，持久化存档。CLI 下 `/flags` 命令可查看。

**2026-05-22 修复**：失败实体的惩罚叙事曾因 enrich 步骤的两个 bug 丢失：
- `judged_entities` 只收集成功实体 → enrich LLM 看不到惩罚内容
- `all_outcomes[0].message` 无条件被 enrich 结果覆盖 → 惩罚叙事可能被擦除  
详见 `tests/test_failure_penalty.py`（2 case，全部 mock）。

## 特殊标记

| 标记 | 含义 |
|------|------|
| `##GRADED##` | 实际结果在 graded_result 中（failure/regular/hard/extreme 四级） |
| `##END_名称:简述##` | 触发游戏结局 |
| `[adjacent_aware]` | Enemy flag：跨场景可感知（确定性闸门扩展到相邻场景） |
| `[avoidable]` | Enemy flag：存在非战斗绕过途径，触发对峙阶段（语义匹配→D100 检定） |

## 环境配置

```bash
pip install openai python-docx PyPDF2 ipython
```

在项目根目录创建 `.env` 文件（已纳入 .gitignore）：

```
DEEPSEEK_API_KEY=your-key
```

`src/llm.py` 启动时自动加载 `.env`，无需手动 export。

## 核心 LLM 调用

`call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort)`

- `model`: 模型名称（默认 `deepseek-v4-pro`）
- `thinking`: 思考模式开关（默认 True）
- `reasoning_effort`: 推理强度 `"low"/"medium"/"high"/"max"`（默认 `"high"`）
- `json_mode=True`：结构化判定（temperature=0.2）；`json_mode=False`：叙事生成（temperature=0.7）

## 运行

### 管线 CLI（模组解析）

```bash
python run_pipeline.py                          # 交互式向导
python run_pipeline.py --auto --docx "常暗之厢.docx" --module 常暗之厢  # 自动
python run_pipeline.py --config config.json     # 从配置文件
python run_pipeline.py --config config.json --start-from step_3a  # 断点续跑
```

### 前端车卡（调查员创建）

```bash
python frontend/server.py                        # localhost:8080/character.html
```

### 游戏循环

```bash
python frontend/game_server.py                   # Web 模式 → localhost:8080/game.html
python run_game.py                               # CLI 模式（需要 IPython）
```

Jupyter 交互：`notebooks/notebook_simplified.ipynb`

### 调试命令（Web/CLI 通用）

| 命令 | 作用 |
|------|------|
| `/scene` | 查看当前场景完整信息 |
| `/char` | 查看当前调查员角色卡（含武器、物品） |
| `/do <动作名>` | 直接执行交互（跳过 LLM） |
| `/trigger <E1>` | 手动触发事件 |
| `/spawn enemy <名称>` | 从敌人库生成敌人 |
| `/spawn weapon <名称>` | 从武器库分发武器 |
| `/save <槽位>` / `/load <槽位>` | 存档/读档 |
| `/charsave` / `/charload` | 调查员长期存档 |
| `/inject [toggle\|status]` | 运行时注入状态 |
| `/help` | 帮助 |

### Web 前端

```bash
python frontend/game_server.py                    # 默认 :8080
python frontend/game_server.py --port 9000        # 自定义端口
```

浏览器打开 `http://localhost:8080/game.html`。

## 公开发行打包

PyInstaller 方案：

```bash
pip install pyinstaller

pyinstaller -F --noconsole --name "TRPG助手" \
  --add-data "frontend;frontend" \
  --add-data "data;data" \
  --add-data "src;src" \
  --add-data "investigator;investigator" \
  --add-data "logs;logs" \
  --hidden-import openai \
  --hidden-import IPython \
  run_game.py
```

- API Key：`.env` 不打包，首次启动引导用户在 Web 界面配置
- 杀软误报：`--onedir`（文件夹分发）误报率低于 `--onefile`
- 跨平台：Windows/macOS/Linux 分别需在对应系统打包
