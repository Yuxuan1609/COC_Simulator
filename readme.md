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
│   ├── server.py                              # FastAPI 统一入口（v2，替换旧的 server.py + game_server.py）
│   ├── routers/
│   │   ├── launcher.py                        #   启动页 + 模组生成 API + 参数配置 API
│   │   ├── character.py                       #   车卡创建 API（3 步向导 + LLM 描述生成）
│   │   ├── game.py                            #   游戏循环 API + WebSocket 步骤进度推送
│   │   ├── editor.py                          #   JSON 轻量编辑器 API
│   │   └── files.py                           #   文件浏览 API（共享组件）
│   ├── templates/
│   │   ├── base.html                          #   根布局（Tailwind CDN + HTMX + Jinja2 block）
│   │   ├── launcher.html                      #   启动页（模组生成 + 参数配置 + 导航）
│   │   ├── character.html                     #   车卡 3 步向导
│   │   ├── game.html                          #   游戏主界面（视觉小说布局 + 展开式会话）
│   │   ├── editor.html                        #   JSON 轻量编辑器（3 栏布局）
│   │   └── partials/
│   │       ├── file-browser.html              #   可复用文件/目录选择器
│   │       ├── step-indicator.html            #   WebSocket 驱动的处理步骤指示器
│   │       └── help-*.html                    #   上下文相关用户指南
│   └── static/
│       └── fonts/                             #   捆绑的 Noto Serif SC 字体（生产环境用）
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
- **BossManager**（`boss_manager.py`）：Boss 信息管理 — 不参与 spawn，从 L2 预设 `boss_encounters` + `BossLibrary` 构造 CombatInit。Boss 作为独立子系统，与 Enemy 并行但不注册到 EnemyManager。Boss 战斗复用 CombatSystem（`_resolve_boss_action_stub` 为未来 LLM 增强预留），接入点纯确定性（`engage_type: "at"/"event"` 自动触发），接出后标记 `runtime_state` completed。Boss ID 自动注册到 `dependency_graph` 和 `runtime_state`，支持其他 entity 通过依赖边引用 Boss 击败状态。序列化完整支持 `to_dict()/from_dict()`（含 `library` 属性代理 `_library`）
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
- **TODO**: 战斗 LLM 增强（`COMBAT_LLM_ENHANCEMENT` 开关在 `src/config.py`，# 174 `_generate_combat_narrative()` 为占位；`_resolve_boss_action_stub` 当前镜像常规敌人逻辑，未来接入 `boss_mechanics` 做 LLM 行为决策）

**Boss 战斗系统**：

Boss 与普通敌人（Enemy）并行管理，但设计上独立：

| 维度 | Enemy | Boss |
|------|-------|------|
| 管理器 | `EnemyManager` | `BossManager` |
| 生成 | `spawn()` / `@spawn_enemy` | 无 spawn，纯自动触发 |
| 触发 | LLM 判定 → 对峙 | 确定性 `at`/`event` 触发 |
| 实例 | 持久化 `EnemyInstance`（注册到 EnemyManager） | 瞬态 `EnemyInstance`（战斗后丢弃） |
| 击败状态 | `EnemyManager._dead` | `runtime_state[boss_id].completed` |
| 战斗 | `CombatSystem.run_combat()` | 复用 `CombatSystem.run_combat()` |
| 特殊机制 | `combat_behavior` 字段 | `boss_mechanics` 字段（**TODO: LLM 增强暂未实现**） |

**Boss 事件流**：`keeper.process_turn()` 内
1. **`at` 触发**（场景进入后）→ 依赖图事件触发后立即检查
2. **`event` 触发**（回合处理末尾）→ Judge / Enrich / Author 之后检查
3. 触发条件满足 → `BossManager.build_combat_init()` 创建瞬态 `EnemyInstance` → `set_active()` → 返回 `CombatInit`
4. `game_loop.run_turn()` 检测到 `combat_init` → 运行 `CombatSystem.run_combat()`
5. 战斗结果 → `win` 则 `world.mark_completed(boss_id)` → `set_active(None)`

**Boss 依赖图集成**：`ScenarioWorld._register_boss_nodes()` 在 `load_dependency_graph()` 后自动将 `boss_encounters` 中的每个 Boss ID 注册到 `dependency_graph.nodes` 和 `runtime_state`。其他 entity 可通过依赖边引用 Boss 击败状态（`{source: "I_SOMETHING", target: "BOSS_ID", dep_type: "boss"}`）

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
| **1** | O6 | Harness 整合 + LLM 模拟真人测试 | ♻ 部分完成。旧 `game_loop_harness.py` 已由 `test_harness_parallel.py`（17 case，并行）和 `test_harness_stability.py`（2 case，串行多轮）替代。Parallel harness 已稳定通过。Stability harness 仍需调整 LLM 输入输出响应质量。Escalation harness 触发条件苛刻，暂不整合。远期：LLM-as-player 模式自动驱动多轮探索 |
| **2** | O4 | 基于 Escalation 修改轻量级管线 | ✅ 已实现 — Author Patch/StructuralEdit 管线完整可运行（`author.py:handle_request()` → `build_author_prompt()` → `supplement_pipeline.run_supplement_pipeline()` 4 步 LLM）。Keeper 集成完整（`process_turn` → Author → 递归）。待优化：LLM prompt 模板精修提升 Patch 命中率 |
| **3** | O5 | 时间系统 | ✅ 已修复 — `_resolve_time_delta` 移除，改为每轮单次 TimeAgent 调用（与 enrich 并行）。TA 接收本轮所有 action 摘要 + time_range + 玩家输入，统一评估总耗时。日志写入 `logs/<ts>/TimeAgent.txt` |
| 4 | O7 | 世界状态类 & 调查员类序列化 | ✅ 已修复（G9/G10 于 2026-05-23 修复）— 所有子系统（GameClock/EnemyManager/NPCManager/BossManager/MemoryManager/ItemManager）均实现 `to_dict()`/`from_dict()`，`test_save_load_roundtrip.py` 覆盖全量往返测试 |
| 5 | O8 | parse → enrich → curate 链路缺少明确中间结构 | ✅ 已修复 — 引入 `EnrichInput` dataclass（`messages.py`），封装 `entities: list[dict]` + `actions: list[dict]`，替代 `process_turn` 中的裸 `list[dict]` 局部变量。`keeper.py` 全部引用已迁移 |
| 6 | O9 | 战斗叙事缺失 — `CombatResult.narrative` 始终为空 | ♻ 接口已就绪 — `CombatSystem.__init__` 接收 `llm_enhancement` 参数（默认读取 `config.py:COMBAT_LLM_ENHANCEMENT=False`），`_generate_combat_narrative()` 占位。开启后调用 `build_combat_narrative_prompt()` → LLM 填充 `CombatResult.narrative`。当前输出确定性 per-action 文本 |
| 7 | O10 | Standoff 流程未接入 Harness | ✅ 已修复 — `_run_turns()` 检测 `standoff_prompt` 后自动消耗下一个玩家输入调用 `continue_standoff()`，记录对峙结果。详见 `tests/test_harness_parallel.py:289` |
| 8 | O11 | System Prompt 过于简略 — 稳定规则应从 User Prompt 迁移 | ✅ 已修复 — Keeper Parse/Enrich、Narrator、CombatEntry、TimeAgent 的 system prompt 已扩充，包含角色定义 + 任务描述 + 输出规则 + 输出格式。User prompt 中移除了冗余规则，仅保留动态数据和 JSON 格式示例 |
| 9 | O12 | 条件="" 字段造成 Token 噪声 | ✅ 已修复 — `_build_entity_lines()` 中 `_fmt_inter`、`_fmt_at` 和事件格式化均改为仅当条件非空时才渲染 `条件="..."` 字段 |
| 10 | O13 | @grant_weapon 副效果未接入游戏循环 | ✅ 已修复（2026-05-23）。两处 fix：(1) `ScenarioWorld.__init__()` 从 graph nodes 加载 L2 `scene_weapons` → `world.scene_weapons`。(2) `Keeper._load_scene_into_graph()` 动态场景时同步武器。(3) Search handler 中武器发现移出 `if ok` 分支——即使侦查失败也能看到场景武器。(4) Search handler 新增拾取意图检测，LLM 误分类为 search 时仍能触发 `add_weapon()` |
| 11 | O14 | 结局事件系统未实施 | ✅ 已修复 — `keeper.py` 中 Judge 完成后通过 dependency_graph 自动检测并触发依赖事件的结局（如 IT3 完成 → E_TEST_END 自动触发）。`##END_` 标记检测后从 L3 `ending_conditions` 查找完整叙事。`game_loop.py` 返回 `game_over=True`，前端可据此显示结局并退出。**TODO**：跨模组时结局需合并多 L3 或全局结局表 |
| 14 | O15 | NPC 态度层级复杂影响 | hostile/wary/neutral/friendly/trusting 五级态度 -> 信息透露量 / 检定难度 / 战斗触发。当前仅注入 prompt 供 LLM 自行解读 |
| 15 | O16 | 世界状态更新纳入 NPC 关键事件 | NPC 跟随/死亡/态度转变等事件纳入 dependency graph 和 world.runtime_state 追踪 |
| 16 | O17 | 半主动 NPC ambient triggers | NPCManager 预留 get_ambient_triggers() hook，未来对接 AutoTrigger 系统实现 NPC 主动行为 |
| 17 | O18 | requirement 确定性 NPC 状态语法 | 如 NPC:name.attitude=friendly 形式的硬性条件解析 |
| 18 | O19 | NPC bound entity 跨场景激活 | 当前 source_scene 精确匹配过于粗糙——NPC 移动后原场景 entity 仍应可选，部分 AT 应跨场景生效。需细化绑定实体的可用性规则 |


### 待升级（不优先）

| # | 问题 | 说明 |
|----|------|------|
| U1 | Author 的 "other 行为" 缺乏意图消歧 | 玩家输入 "我想试试能不能跳过去" 可能意味（a）真正做动作需检定（b）仅 RP 描述。当前 IntentDetector 只判断"是否有意图"但不评分"意图对应哪个实体/是否需要检定"，导致 detect 的 false positive 触发不必要的 Author 调用。建议引入二次确认（如 Keeper 反问玩家"你要实际尝试吗？"）或实体匹配置信度阈值 |
| U2 | 缺少技能协同检定 | COC 7th 规则中的合作检定（多人共同尝试）和互补检定（用相关技能辅助）未实现。单调查员模组下无大碍，但限制未来多人扩展 |
| U3 | 战斗系统 LLM 增强 | `config.py` 中 `COMBAT_LLM_ENHANCEMENT=False`。开启后：每轮战斗由 `build_combat_narrative_prompt()` 生成 LLM 叙事，战斗结束生成 LLM 战斗总结填入 `CombatResult.narrative`。`CombatSystem.__init__` 已接收 `llm_enhancement` 参数并预留 `_generate_combat_narrative()` 方法。当前仅输出确定性 per-action 文本 |
| U4 | LLM Provider 抽象 | `config_llm.template.py` 已预留 `LLM_PROVIDER` 字段。远期支持 OpenAI/Anthropic 等多 provider 切换，改写 `llm.py` 的 API 调用方式 |
| ~~U5~~ | ~~管线运行时监控 (PipelineMonitor)~~ | ✅ 已实现 (2026-05-25)。两层架构：LLMSensor 嵌入 call_deepseek 零侵入记录 + AgentMonitor 每 Agent 降级决策 + DegradationPolicy 集中化配置 (`config.py:DEGRADE_POLICY`)。降级策略：超时重试/连续失败切 flash/Keeper 跳过 enrich。CLI `/health` 查询。`src/monitor/` |
| U6 | 基于 Logger 内容实现世界状态解读 | `TurnLogger`（`src/game/turn_logger.py`）已记录每轮玩家输入 + Enrich 输出 + Narrator 输出到 `data/debug/turn_logs/`。后续基于此数据训练/评估世界状态解读模型，或生成更准确的场景摘要 |

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
- **战斗系统详解**: `docs/combat-system.md` — CombatSystem 回合制逻辑、回避/逃跑/攻击的动作互作用、伤害计算链、LLM 增强预留接口

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
| `tests/test_harness_parallel.py` | **NEW** — 17 case 并行，覆盖 search/检定/依赖链/AT/NPC/武器/move/对峙/战斗/道具/属性/结局/重复失败惩罚，含 `--mock` 模式 | 集成（真实 LLM） |
| `tests/test_harness_stability.py` | **NEW** — 2 case 串行稳定性测试（正常探索 + 混合压力），3 轮/每轮 3 turn，含完整 LLM 日志 | 集成（真实 LLM） |
| `tests/test_failure_penalty.py` | **NEW** — 2 case 失败惩罚链路：Judge 生成→Keeper 保留→Narrator 接收，全 mock | 单元 |
| `tests/test_save_load_roundtrip.py` | **NEW** — 存档/读档全量 roundtrip：ItemManager/GameClock/EnemyManager/NPCManager/Memory | 集成 |
| `tests/game_loop_harness.py` | ⚠ 已弃用 — 7 轮旧 pipeline（绕过 Keeper.process_turn，使用废弃的 `apply_side_effects`），待迁移到新 harness | 集成（真实 LLM） |
| 其他 | test_judge, test_dependency_graph, test_directed_graph, test_entity, test_entity_resolvers, test_curator, test_integration, test_module_designer, test_markup | 单元 + 集成 |

**测试说明**：
- 测试数据：`data/modules/test/l*_test.json` 及 `data/modules/常暗之厢/l*_test.json`
- **Parallel Harness**：`python tests/test_harness_parallel.py`（17 case 并行），`--mock` 快速验证，`--cases search,npc_dialogue` 选择 case
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

### 前端车卡（调查员创建） + 游戏 + 编辑器

```bash
uvicorn frontend.server:app --reload             # 开发模式 → localhost:8080
python run_game.py                               # 生产模式（含自动打开浏览器）
```

浏览器打开 `http://localhost:8080` 进入启动页面，可选择车卡（`/character`）、游戏（`/game`）、编辑器（`/editor`）。

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

## 公开发行打包

PyInstaller 方案：

```bash
pip install pyinstaller

pyinstaller -F --noconsole --name "TRPG助手" \
  --add-data "frontend/templates;frontend/templates" \
  --add-data "frontend/static;frontend/static" \
  --add-data "data;data" \
  --add-data "src;src" \
  --add-data "investigator;investigator" \
  --add-data "logs;logs" \
  --hidden-import fastapi \
  --hidden-import uvicorn \
  --hidden-import jinja2 \
  --hidden-import openai \
  run_game.py
```

- API Key：`.env` 不打包，首次启动引导用户在 Web 界面配置（Launcher → 参数配置）
- 杀软误报：`--onedir`（文件夹分发）误报率低于 `--onefile`
- 跨平台：Windows/macOS/Linux 分别需在对应系统打包

## Frontend v2 重构 (2026-05-25)

> ✅ 已完成。vanilla HTML/CSS/JS + `http.server` 原型已替换为 FastAPI + HTMX + Tailwind CSS。

### 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 服务器 | **FastAPI** | async 路由 + WebSocket + Jinja2 模板，统一替换两个旧的 http.server |
| 前端交互 | **HTMX** (~14KB) | 声明式 AJAX，服务端渲染 HTML 片段，最小化手写 JS |
| 样式 | **Tailwind CSS v4** | CDN 开发 → 独立构建生产部署 |
| 实时推送 | **WebSocket** | 游戏回合处理步骤进度 + 模组生成管线进度 |
| 打包 | **PyInstaller** | `--add-data` 模板 + 静态文件 + `--hidden-import` fastapi/uvicorn |

### 页面架构

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | **Launcher 启动页** | 模组生成向导（上传 docx → 管线进度 → 下载 JSON）+ 参数配置（API Key、模型、阈值、开关）+ 子页面导航 |
| `/character` | **车卡创建** | 3 步向导（基本信息+属性掷骰 → 职业+技能分配 → 预览+导出 JSON），LLM 辅助描述生成 |
| `/game` | **游戏循环** | 视觉小说风格沉浸式布局：全屏氛围图 + HUD 叠加 + 底部紧凑叙事栏 + 点击展开完整会话面板 + WebSocket 步骤指示器 |
| `/editor` | **JSON 编辑器** | 轻量 3 栏布局（文件浏览 + JSON 树形展开 + 校验状态），非完整 IDE |

### 设计文档

- 设计规格：`docs/superpowers/specs/2026-05-25-frontend-redesign-design.md`
- 实现计划：`docs/superpowers/plans/2026-05-25-frontend-redesign-plan.md`

### 代码分离

```
frontend/          ← 表示层（导入 src/）
src/               ← 游戏引擎（不导入 frontend/）
```

## NPC-Entity 分离 (2026-05-25)

- **NPC 场景分配**：Step 1a `characters` 输出 `scenes`（首次出现的主要场景）、`can_follow`（bool）、`follow_condition`（文本描述）。管线后处理注入到 `npc_profiles[].scene` / `.can_follow` / `.follow_requirements`。
- **NPC 实体绑定**：新增 Step 2.5b（LLM，与 Step 3a ∥ 2.5 并行），用 LLM 判定每个 entity 归属哪个 NPC，替代原确定性子串匹配。Binding 结果传入 `_bind_npc_entities()` 优先使用，fallback 到确定性匹配。
- **模组生成 prompt**：Step 2a/2b prompt 排除纯 NPC 对话和跟随事件。Step 2.5b prompt 传入完整 entity 列表 + characters 用于归属判定。
- **运行时**：NPC 对话走独立 turn — talk_to(状态门+交互触发条件) → NPC parse(bound entities) → judge → enrich → curate，game_loop 统一 narrate。flash LLM 判定对话意图防止误触发。NPC AT 条件满足时动态注入主 parse，注入的 AT 标记为 `[NPC_AT]` 并在 parse prompt 中显示为独立 `【NPC 专属实体】` 区块。
- **独立输出**：`run_turn()` 返回 `npcs_visible` (in_scene/following) 和 `npc_events` (固定预料通知)。
- **NPC 跟随（简化）**：两种触发源（@npc_follow markup + 玩家请求），统一检查 `can_follow` + 存活状态。`follow_requirements` 保留为 Step 1a 生成的文本描述供将来 LLM 评估（TODO），当前运行时不做确定性求值。
- **NPC 跟随 entity 生成**：`_apply_pending()` 中检测 `npc.following=True` 后注入 `EVT_NPC_FOLLOW` entity 的逻辑当前是死代码——必须先有 entity 触发 `@npc_follow` side effect 调用 `set_following()`，NPC 才会开始跟随。Step 2a/2b prompt 已允许生成跟随 entity（`@npc_follow`），但已生成的模组（如 `常暗更新`）不含此 entity。
  - **TODO**：重新生成模组或运行时加兜底逻辑。
  - **注意**：跟随事件应在**单一环节**中确定性注入（如 Step 1a 直接写死 `@npc_follow` 字段，或在 `_assemble_l2` 中自动化补全），不要在多个步骤中各自解析跟随，避免重复和冲突。不要依赖 LLM 自己"理解"是否要生成跟随实体。
- **run_pipeline.py CLI**：LLM call 日志目录使用语义化步骤名（如 `step1a_structured_extract`）替代编号。Step 3a+2.5+2.5b 三路并行。
- **设计文档**：`docs/superpowers/specs/2026-05-25-npc-entity-separation-design.md`
- **实现计划**：`docs/superpowers/plans/2026-05-25-npc-entity-separation-plan.md`

## 管线提示词重构 (2026-05-25)

- **主管线 + 补充管线**：全部 18 个步骤的 system prompt 重构——角色定义、规则、输出格式、字段约束从 user prompt 移入 system prompt。User prompt 仅保留动态数据（章节文本、entity 列表、场景/角色名、库引用）。
- **补充管线 Step 1 结构化**：`story` 输出从自由文本改为半结构化——综述（200字）、每场景可用互动、叙事线、driving force、涉及敌人（仅普通敌人库）。`enemy_names` 参数传入确保敌人名从库中选择。Step 2 消费的 story 自动组装为 markdown 格式。
