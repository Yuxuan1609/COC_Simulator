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
│   │   │   └── bosses.json                  # 核心 Boss 库（1 种剧情敌人，含 boss_mechanics）
│   │   └── extensions/                      # 用户自定义武器/敌人扩展包
│   ├── templates/
│   │   ├── l1_template.json                 # L1 玩家可见层模板
│   │   ├── l2_template.json                 # L2 KP 守秘人层模板
│   │   └── l3_template.json                 # L3 设计者层模板
│   ├── modules/
│   │   └── 常暗之厢/
│   │       ├── l1_player.json               # L1 玩家可见层（LLM 生成）
│   │       ├── l2_keeper.json               # L2 KP 守秘人层（LLM 生成，游戏循环直接消费）
│   │       └── l3_designer.json             # L3 设计者层（LLM 生成）
│   └── output/
│       └── archive/                         # 旧 pipeline 输出存档
├── src/
│   ├── scenario_core.py                     # 数据类、有向图、世界状态、记忆管理、Entity/@markup（7 种）
│   ├── llm.py                               # DeepSeek API 封装（可配置模型、思考模式）
│   ├── trpg_display.py                      # Notebook UI 显示组件
│   ├── utils.py                             # 文件解析、Token 估算、掷骰、技能定义加载
│   ├── prompts.py                           # LLM Prompt 构建器（Keeper/Narrator/Author/CombatEntry/Standoff/StatNarrative/ConsumeFuzzy）
│   ├── game_loop.py                         # 多 Agent 入口：init_game() + run_turn() + continue_standoff()
│   ├── game/                                # Multi-Agent 游戏循环
│   │   ├── messages.py                      #   消息 dataclass（NarratorBrief, CombatEntryCheck, CombatInit, CombatResult 等）
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
│   │       └── author.py                    #   作者（L3 + AuthorRequest → ModulePatch/StructuralEdit）
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
├── frontend/                                # 车卡前端页面
│   ├── server.py                            # 本地服务器 + LLM 描述生成 API
│   ├── character.html                       # 5 步车卡向导
│   ├── character.css                        # COC 1920s 美学风格
│   └── character.js                         # 车卡交互逻辑（含 /llm 触发）
├── run_pipeline.py                          # 管线 CLI 入口（配置向导 + 手动/自动模式）
├── notebooks/
│   ├── notebook_simplified.ipynb            # 主游戏循环（导入 src/ 模块）
│   └── parser_test.ipynb                    # 管线驱动与测试
├── docs/
│   └── superpowers/
│       ├── specs/                           # 设计文档（含 combat-entry-detection-design）
│       └── plans/                           # 实现计划（含 combat-entry-detection-plan）
├── logs/                                    # Prompt 日志（每次运行生成，含技能检定记录）
└── .env                                     # DeepSeek API Key（不纳入版本控制）
```

## 核心模块

### `scenario_core.py`

纯 Python 数据模块，不依赖 LLM 或 UI。

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Entity`（统一 entity）、`Requirement`（前置条件）、`ActionResult`（统一返回类型）
- **Side Effects (8 种)**：`ItemGain`（获得物品）、`ConsumeItem`（消耗物品）、`StatChange`（属性变化）、`SpawnEnemy`（生成敌人）、`GrantWeapon`（授予武器）、`NPCStateChange`（NPC 状态）、`NPCFollow`（NPC 跟随）、`SceneWeapon`（场景武器）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态管理器 —— 当前位置、已触发事件、已完成交互、runtime_state/dependency_graph、NPC 运行时状态、记忆管理、EnemyManager、scene_weapons、weapon_library
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪
- **@markup 解析器**：`parse_markup` / `parse_markup_all` 将 @函数(参数) 标记文本解析为 dataclass 实例
- **##GRADED## / ##END_**：分级检定结果 + 结局嵌入

### `src/game/` — Multi-Agent 游戏循环

2026-05-16 重构。4-Agent 架构替代单体 `handle_user_input()`：

| Agent | 层 | 职责 | 文件 |
|-------|----|------|------|
| Keeper | L2 | 回合编配：parse→judge→enrich∥combat_entry→standoff→curate | `src/game/agents/keeper.py` |
| Narrator | L1 | 唯一面向玩家，生成沉浸式叙事 | `src/game/agents/narrator.py` |
| Author | L3 | 两级响应：Patch（填缺口）/ StructuralEdit（触发补充管线），WR0 独立可配 | `src/game/agents/author.py` |
| IntentDetector | — | Parse 命中 other 时并行检测是否存在实际叙事意图 | `src/game/intent_detector.py` |

**支持系统**：
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
- `combat_check()` / `damage_roll()` 已由 `src/game/combat.py` 的 CombatSystem 接管，旧方法待清理

### `src/module_designer/` — 三层信息引擎

渐进式解析流程（12 次 LLM 调用）：

1. Step 1a/1b — 结构化提取 + 精修模组 (2 并行)
2. Step 2a — Interactions + scene_movements
3. Step 2b/2c — Events + AT + L1 + L3 (4 并行)
4. Step 3a — 去重 + 冲突 + 结局验证
5. 组装 L2 → Step 3b: L1↔L2↔L3 交叉核对
6. Step 3.5 ∥ Phase 1 — 依赖图 + 风格预判 (2 并行)
7. Phase 2 — type 标准化 + side_effects → `@函数(参数)` (7 种：spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change/npc_follow)

每步含 `_with_fallback` 保底策略。详细过程见 `docs/superpowers/specs/NEXT-SESSION.md`。

### `prompts.py`

LLM Prompt 构建器。覆盖 Keeper parse/enrich、Narrator、Author、combat entry detection、standoff match、stat narrative、consume item fuzzy match、combat narrative。

### `game_loop.py` — 入口

- `init_game()`：加载 L1/L2/L3 JSON + EnemyLibrary/WeaponLibrary/BossLibrary + BossManager/NPCManager → 构建 DirectedGraph → ScenarioWorld → 初始化 Keeper/Narrator/Author
- `run_turn()`：驱动回合，处理 debug 命令 → `keeper.process_turn()` → 检测 `combat_init` → `CombatSystem.run_combat()` → `narrator.narrate()` → 返回 `{brief, narrative, full, combat, standoff_prompt}`
- `continue_standoff()`：处理对峙阶段的玩家回避尝试 → 检测结果调用 CombatSystem → 返回 `{avoided, combat_init, message, combat_narrative}`

## 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 作者介入机制 (Escalation) | ⚠ 已实现，提示词待精修 | Parse other → IntentDetect(并行) → Author (Patch/StructuralEdit/Reject) → 补充管线。Patch 和 StructuralEdit 的轻量级 LLM 提示词需精修。`scene_context` 字段随 NPC/时间/Boss 系统上线待补全。Author 人设（`DEFAULT_AUTHOR_PERSONA`）可手动修改，位于 `src/game/agents/author.py`。详见 `docs/superpowers/specs/2026-05-19-escalation-redesign.md` |
| 战斗系统 — 进入/脱出 | ✅ 已实现 | SpawnEnemy→EnemyManager→LLM 检测+对峙→CombatInit。详见 `docs/superpowers/specs/2026-05-19-combat-entry-detection-design.md` |
| 战斗系统 — 回合制核心 | ✅ 已接入 | `src/game/combat.py`：CombatSystem 已实现伤害掷骰/D100 检定/先攻/逐轮处理，`run_turn()` 和 `continue_standoff()` 中自动调用 |
| 武器获取系统 | ✅ 已实现 | grant_weapon → SceneWeapon 场景放置 → search 发现 → 确认拾取 → Investigator.add_weapon |
| 物品管理 | ✅ 已实现 | ItemManager（Investigator），item_gain(quantity) / consume_item（严格+LLM 模糊匹配） |
| 属性变化 | ✅ 已实现 | StatChange → Investigator.modify_stat(int/dice formula) + LLM narrative 描述更新 |
| NPC / 同伴系统 | ✅ 已实现 | NPCManager 全量管理：LLM 对话（态度/记忆上下文注入）、被动跟随（@npc_follow markup）、5级态度状态机。架构预留半主动 hook。详见 `docs/superpowers/specs/2026-05-20-boss-npc-design.md` |
| Boss/剧情敌人 | ✅ 已实现 | 独立 bosses.json 库，`type="boss_encounter"` Entity（engage_type 硬性过滤），BossManager 信息挂钩+CombatSystem LLM 路径。特殊机制走自然语言 `boss_mechanics` 字段。详见 `docs/superpowers/specs/2026-05-20-boss-npc-design.md` |
| 前端 UI + 随材 | TODO | **升级功能点**：游戏循环 Web 前端的视觉升级（场景插图、角色立绘、战斗动画）、音效/BGM 随材集成、移动端适配。当前 `frontend/game.html` 为纯功能界面 |
| 时间系统 | ⚠ 已实现，有已知问题 | 两层架构：确定性时间（`world.game_time` + `advance_time()`）+ TimeAgent (LLM sub-agent) 叙事引导。每 30 分钟调用一次。设计文档：`docs/superpowers/specs/2026-05-22-time-system-redesign.md` **已知问题：1) TimeAgent prompt 未传入玩家本轮输入，导致叙事引导与玩家行为脱节 2) other 行为（即兴/搜索/非常规互动）未接入 TimeAgent，应在每轮判定中主动触发时间感知** |

### 已知缺口

| # | 问题 | 状态 |
|---|------|------|
| G1 | Judge 需求检查仅 `flag:` 前缀 | ✅ FIXED — dependency_graph + runtime_state + parse_hard_requirement |
| G2 | `from_dict` 未更新 Entity 格式 | ✅ FIXED |
| G3 | Escalation 递归无深度保护 | ✅ FIXED — MAX_ESCALATION_DEPTH=3 |
| G4 | `run_turn` 输出格式 | ✅ FIXED |
| G5 | 结局检测未接入 | ✅ FIXED |
| G6 | Keeper 无单元测试 | ✅ DONE |
| G7 | CombatSystem 未接入 game_loop | ✅ FIXED — `run_turn()` 和 `continue_standoff()` 中检测 `CombatInit` → `CombatSystem.run_combat()` → `EnemyManager.exit_combat()` |
| G8 | `Investigator.combat_check/damage_roll` 仍 raise NotImplementedError | ✅ FIXED — 旧 stub 已移除，战斗逻辑已由 `CombatSystem` 完全接管 |

### 待优化

| # | 问题 | 说明 |
|---|------|------|
| O1 | Escalation 每回合 LLM 调用 | ✅ 已解决 — 改为 Parse other → IntentDetect 按需触发 |
| O2 | Memory 压缩阻塞 LLM 调用 | ✅ FIXED — 改为 daemon Thread 后台执行，不阻塞 turn 返回 |
| O3 | Move 限制条件未强制执行 | ✅ FIXED — `ScenarioWorld.move()` 检查 edge.requirement（hard: entity IDs + AND/OR，soft: LLM parse 评估），不满足返回阻塞消息。⚠ 模组生成管线需微调：L2 edge requirement 格式需要与 entity requirement 对齐 |
| O4 | Author Patch/StructuralEdit 提示词 | 轻量级生成质量不稳定，需精修 prompt 模板 |
| O5 | 时间系统 | ⚠ 部分实现 — TimeAgent prompt 未传入玩家输入，other 行为未接入。需修复 |
| O6 | Harness 整合 | `game_loop_harness` / `escalation_harness` / `combat_harness` 三个集成测试文件合并为统一的 mock-LLM 端到端测试 |

## 设计文档

- Multi-Agent: `docs/superpowers/specs/2026-05-16-game-loop-multi-agent-design.md`
- Escalation 重设计: `docs/superpowers/specs/2026-05-19-escalation-redesign.md`
- 战斗进入/脱出判定: `docs/superpowers/specs/2026-05-19-combat-entry-detection-design.md`
- 时间系统: `docs/superpowers/specs/2026-05-19-time-system-design.md`
- 测试体系: `docs/superpowers/specs/2026-05-20-test-suites.md`
- Boss/剧情敌人 & NPC: `docs/superpowers/specs/2026-05-20-boss-npc-design.md`
- Implementation Plan: `docs/superpowers/plans/2026-05-20-boss-npc-plan.md`
- **Cookbook 代码导航**: `docs/superpowers/guides/cookbook.md` — 每个模块标注文件-类/函数-功能拆解，供快速定位代码
- **模组创作指南**: `docs/superpowers/guides/module-authoring-guide.md` — 三层架构说明、源文档写法、@markup 系统、敌人/Boss/NPC 设计、叙事线/时间压力配置、写作检查清单

## 测试

| 文件 | 覆盖范围 | 类型 |
|------|----------|------|
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
| `tests/game_loop_harness.py` | 7 轮 parse→judge→enrich→narrate | 集成（真实 LLM） |
| 其他 | test_judge, test_dependency_graph, test_directed_graph, test_entity, test_entity_resolvers, test_curator, test_integration, test_module_designer | 单元 + 集成 |

**测试说明**：
- 测试数据：`data/modules/常暗之厢/l*_test.json`（测试房间 + 原模组内容），`start_node` 已切到「测试房间」。正式需切回正式 JSON。
- Game Loop Harness：`cd tests && python game_loop_harness.py`（需 API Key），日志 → `data/debug/test_harness/<ts>/`
- **测试模组**：`test_story.txt` — 极小模组「林中小屋」(~180 字，2 场景 / 1 NPC / 1 Boss / 1 普通敌人)，用于快速验证管线。在 `notebooks/parser_layered.ipynb` Cell 2 中切 `SOURCE_FILE` 即可使用，2-3 分钟跑完全管线。

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
启动角色卡.bat                                   # Windows 一键启动
python frontend/server.py                        # 手动启动 → localhost:8080/character.html
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
  frontend/launcher.py
```

- API Key：`.env` 不打包，首次启动引导用户在 Web 界面配置
- 杀软误报：`--onedir`（文件夹分发）误报率低于 `--onefile`
- 跨平台：Windows/macOS/Linux 分别需在对应系统打包
