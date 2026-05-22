# COC Simulator Cookbook — 代码导航指南

> 每个模块标注：文件路径 → 核心类/函数 → 功能拆解。供后续 session 快速定位代码。

---

## 1. 游戏循环入口

### `src/game_loop.py` (284 行)

| 函数/类 | 功能 |
|----------|------|
| `init_game(l2_path, l1_path, l3_path, ...)` | 加载 L1/L2/L3 JSON → 构建 DirectedGraph → 加载 EnemyLibrary/WeaponLibrary/BossLibrary → 初始化 BossManager/NPCManager → 创建 ScenarioWorld → 初始化 Keeper/Narrator/Author → 返回 `{keeper, narrator, author}` |
| `run_turn(game, user_input, ...)` | 单回合入口：处理 debug 命令 → 构建 TurnInput → `keeper.process_turn()` → 检测 `combat_init` 调用 `CombatSystem.run_combat()` → `narrator.narrate()` → 返回 `{brief, narrative, full, combat, standoff_prompt}` |
| `continue_standoff(keeper, player_input)` | 对峙阶段处理：`keeper.resolve_standoff()` → 检测结果调用 CombatSystem → 返回 |
| `_handle_spawn_command(...)` | `/spawn enemy <name>` 和 `/spawn weapon <name>` 调试命令处理 |

### `run_game.py` / `notebooks/notebook_simplified.ipynb`
CLI 和 Jupyter 交互入口，调用 `init_game()` + `run_turn()` 循环。

---

## 2. Keeper 回合编配

### `src/game/agents/keeper.py` (1013 行)

| 方法 | 功能 |
|------|------|
| `process_turn(turn_input, author)` | **主流程**：NPC 对话路由 → Step1 parse(LLM) → Step2 judge(确定) + 并行 IntentDetect → Step3 [enrich(LLM) ∥ combat_entry(LLM) ∥ TimeAgent(LLM)] → Step3.5 收集结果 → Step4 对峙/CombatInit → Step5 IntentDetect 决策 → Step6 curate → Step7 memory(后台压缩) → 返回 `{brief, combat_entry, standoff_prompt, combat_init}` |
| `_parse(raw)` | LLM parse：玩家输入 → 匹配 entity (interaction/auto_trigger/event/move/search/other) |
| `_enrich(judged_entities, user_input)` | **LLM enrich**：将本轮所有实体结果（含成功/失败/AT）合并润色为连贯叙事段落。输入包含 `judged_entities`（修复后含失败实体及惩罚叙事）、world snapshot（世界状态/场景现状/时间块）。覆写规则：结果只覆写第一个成功且非 AT 的 outcome.message，保护失败实体的惩罚叙事 |
| `_find_entity_by_id(eid)` | 跨 graph(场景+events) 查找 entity |
| `_apply_side_effects(side_effects)` | 应用 7 种 @markup side effect dataclass 到世界状态（ItemGain/ConsumeItem/StatChange/SpawnEnemy/GrantWeapon/NPCStateChange/NPCFollow） |
| `resolve_standoff(state, player_input)` | 对峙：语义匹配 LLM → D100 检定 → trait enhancement → 成功转 neutral / 失败进战斗 |
| `_build_world_snapshot()` | 给 IntentDetector 构建世界快照 |
| `_build_scene_context_for_author()` | 给 Author 构建场景上下文 |
| `_integrate_patch(patch)` | Author Patch 实体注入到 graph |
| `_integrate_supplement(structural_edit, author)` | Author StructuralEdit → 补充管线 → 合并 graph + L1 + L3 |
| `_run_time_agent(action_summaries, raw)` | TimeAgent：评估本轮行动耗时（与 enrich 并行，不写 Clock 只返回 time_delta） |

---

## 3. 确定性闸门

### `src/game/judge.py` (324 行)

| 方法 | 功能 |
|------|------|
| `_execute_entity(entity, intent)` | **核心判定**：requirement 检查(hard+soft) → D100 技能检定 → trait enhancement(LLM 特质修正) → ##GRADED## 分级 → **失败惩罚系统**(LLM) → side_effects 解析 → 返回 ActionOutcome |
| `_split_requirement(req)` | 拆分 hard(AND/OR) \|\| soft(自然语言) |
| `_are_requirements_met(entity)` | 硬条件检查：`parse_hard_requirement()` + dependency_graph |
| `_set_completion_flag(entity)` | 标记 entity 完成：更新 runtime_state + dependency_graph 入度 |
| `check_auto_triggers()` | 扫描当前场景 + 全局 events 的满足条件 AT |

---

## 3.5. 失败惩罚系统

### `src/game/judge.py:173-225` + `src/llm.py:344-422`

三层递增机制，在 `_execute_entity()` 内触发（仅当 skill_passed = False）：

| 失败次数 | 触发 | 说明 |
|----------|------|------|
| 第 1 次 | `_escalate_difficulty()` | 实体鉴定难度永久提升一级，写入 `NodeRuntimeState.escalated_difficulty` |
| 第 2 次 | `state.retries++` | 仅递增重试计数 |
| 第 3+ 次 | `evaluate_failure_penalty(LLM)` | 生成创意惩罚叙事 + 可选 @markup 副作用（扣HP/SAN、刷怪、NPC变敌对等），经 `parse_markup_all` 解析后由 `Keeper._apply_side_effects()` 应用 |

**状态追踪**：`NodeRuntimeState`（`src/scenario_core.py:201-207`）每实体一份，含 `retries/escalated_difficulty`，持久化存档。CLI `/flags` 可查询。

**2026-05-22 修复**：失败实体此前被排除在 enrich 的 `judged_entities` 且 `all_outcomes[0].message` 被 unconditionally 覆写，导致惩罚叙事丢失。已修复。

**测试**：`tests/test_failure_penalty.py`（2 case，全 mock）

---

## 4. 战斗系统

### `src/game/combat.py` (371 行)

| 类/函数 | 功能 |
|----------|------|
| `CombatAction` (dataclass) | 单次战斗动作记录：actor/action_type/weapon/skill/roll/tier/target/damage/narrative |
| `CombatState` (dataclass) | 可变战斗状态：round/enemies/player_hp/initiative_order/log |
| `CombatSystem(weapon_lib)` | COC 7th 战斗控制器 |
| `.run_combat(combat_init)` → CombatResult | **主入口**：初始化 CombatState → 逐轮循环 → 返回 CombatResult |
| `._init_combat(combat_init)` | 初始化：解析敌人 hp/先攻 → 构建 CombatState |
| `._process_round(state, player, action_id, target)` | 单轮处理：按先攻序 → 玩家动作 → 敌人动作 → 判定存活 |
| `._resolve_player_action(state, player, action_id, target)` | 玩家 D100 格斗/射击/闪避检定 + 伤害掷骰 + 护甲减免 |
| `._resolve_enemy_action(state, enemy, player)` | 敌人攻击选取 + D100 检定 + 伤害 + 护甲 |
| `._get_tier(roll, skill_value)` | COC 7th 四级检定：≤skill/5=extreme, ≤skill/2=hard, ≤skill=regular |
| `_roll_damage(formula, STR, SIZ)` | 伤害公式解析：1D6+DB、2D6 等 |
| `_apply_armor(damage, armor_str)` | 护甲减免：从 "2点厚皮" 提取数字 |

### `src/game/messages.py` (124 行)

| dataclass | 用途 |
|-----------|------|
| `ActionIntent` | Parse 解析出的玩家意图 |
| `ActionOutcome` | 单个 action 的执行结果(含 skill_tier, skill_detail) |
| `NarratorBrief` | Keeper→Narrator 的策展结果 |
| `AuthorRequest` | IntentDetector→Author：玩家叙事意图 |
| `ModulePatch` | Author→Keeper：entity 补丁 |
| `StructuralEdit` | Author→Keeper：结构扩展 |
| `CombatEntryCheck` | LLM 判定：是否进入战斗 |
| `StandoffMatch` | 对峙语义匹配结果 |
| `CombatInit` | →CombatSystem：战斗初始化数据 |
| `CombatResult` | CombatSystem→：战斗结果 |
| `TurnInput` | 回合入口数据 |

---

## 5. 敌人管理

### `src/game/enemy_manager.py` (170 行)

| 类/方法 | 功能 |
|----------|------|
| `EnemyInstance` (dataclass) | 运行时敌人：instance_id/enemy_ref/scene/quantity/status/flags |
| `EnemyManager(enemy_library)` | 敌人追踪层 |
| `.spawn(enemy_ref, scene, quantity)` → EnemyInstance | 从库实例化敌人，拷贝 flags/combat_behavior |
| `.get_active_in_scene(scene)` → list | 场景中 status != dead 的敌人 |
| `.get_active_in_range(scene, graph)` → list | 当前场景 + adjacent_aware 敌人的相邻场景 |
| `.group_by_ref(scene)` → dict | 同场景按 enemy_ref 分组 |
| `.enter_combat(instance_ids)` | 标记 engaged + 激活 combat 状态 |
| `.exit_combat(result_dict)` | defeated→dead, survivors→hostile, 清除 combat 状态 |
| `.get_combat_context(scene, graph)` → str\|None | 构建 LLM 判定用的敌人信息文本 |
| `.to_dict()` / `.from_dict()` | 序列化/反序列化 |

### `src/game/boss_manager.py` (74 行)

| 类/方法 | 功能 |
|----------|------|
| `BossManager(boss_library, boss_encounters)` | Boss 信息管理（不参与 spawn，由模块预设） |
| `.get_boss(name)` → dict | 获取 Boss stat block + boss_mechanics |
| `.build_combat_init(boss_name, player, scene)` → CombatInit | 从 Boss 数据构造 CombatInit |

---

## 6. NPC 管理

### `src/game/npc_manager.py` (152 行)

| 类/方法 | 功能 |
|----------|------|
| `NPC` (dataclass) | NPC 实例：name/scene/attitude/dialogue_state/following |
| `NPCManager()` | NPC 全量管理 |
| `.init_from_profiles(profiles)` | 从 L2 npc_profiles 批量初始化 |
| `.get_in_scene(scene)` → list | 获取场景中所有 NPC |
| `.talk_to(name, user_input, llm_call)` → str | **对话系统**：LLM 生成 NPC 回复，含 attitude/dialogue 上下文 |
| `.set_attitude(name, attitude)` | 修改 NPC 态度 |
| `.set_following(name, bool)` | 同伴跟随切换 |
| `.to_dict()` / `.from_dict()` | 序列化/反序列化 |

---

## 7. 场景世界

### `src/scenario_core.py` (1391 行)

**Side Effects (6 种 @markup)**：

| dataclass | 字段 | 应用路径 |
|-----------|------|----------|
| `SpawnEnemy` | enemy_ref, scene, quantity | → EnemyManager.spawn() |
| `GrantWeapon` | weapon_ref, scene, quantity | → scene_weapons 放置 |
| `StatChange` | stat_name, delta, narrative | → Investigator.modify_stat() + LLM 描述更新 |
| `ItemGain` | item_name, quantity | → ItemManager.add() |
| `ConsumeItem` | item_name, quantity, narrative | → ItemManager.remove() + LLM 模糊匹配保底 |
| `NPCStateChange` | npc_name, new_state | → world.npc_states 更新 |
| `SceneWeapon` | weapon_ref, scene, quantity | 场景武器追踪 |

**核心类**：

| 类 | 功能 |
|----|------|
| `Entity` | 统一 entity：interaction/auto_trigger/event |
| `Node` | 场景节点：description/edges/interactions/auto_triggers/encounters |
| `Edge` | 连接边：target/method/requirement |
| `DirectedGraph` | 有向图：管理 nodes/events，支持 from_dict/to_dict |
| `ScenarioWorld` | 运行时世界状态：graph/player/memory/enemy_manager/scene_weapons/npc_states/runtime_state/dependency_graph |
| `MemoryManager` | 分层记忆：raw_history + summary + key_items/visited |

**关键函数**：

| 函数 | 功能 |
|------|------|
| `parse_markup(text)` → dataclass\|None | 解析单个 @函数(参数) 字符串 |
| `parse_markup_all(text)` → list | 解析多个 @markup |
| `apply_side_effects(world, side_effects)` → list[str] | 将 dataclass 实例应用到世界，返回 log 消息 |
| `resolve_graded_result(entity, tier)` → str | ##GRADED## 分级结果解析 |
| `has_ending(text)` → (name, narrative)\|None | ##END_ 结局检测 |
| `parse_hard_requirement(req)` → (met, reason) | AND/OR 结构化的硬条件解析 |

---

## 8. 调查员系统

### `src/investigator/models.py` (391 行)

| 类 | 功能 |
|----|------|
| `Stats` | 8 项核心属性 + LUCK |
| `DerivedStats` | HP/MP/SAN/MOV/DB/BUILD/DODGE |
| `Skill` | 技能定义：name/base_value/value/category |
| `Occupation` | 职业定义 |
| `Weapon` | 武器：name/skill_name/damage/range/malfunction |
| `InventoryItem` | 背包物品：name/description/quantity/category |
| `ItemManager` | 物品管理器：add/remove/has/get/list_all/describe/序列化 |
| `Investigator` | 调查员主类 |
| `Investigator.check_skill(name, difficulty)` | D100 技能检定 |
| `Investigator.modify_stat(stat_name, delta)` | 修改属性(int/dice formula) + 衍生属性重算 |
| `Investigator.add_weapon(w)` / `remove_weapon(name)` | 武器管理 |

### `src/investigator/rules.py` (304 行)
纯函数规则引擎：`roll_stats()` / `calc_derived_stats()` / `calc_db(STR, SIZ)` / `allocate_skill_points()` / `age_modifiers()`

### `src/investigator/serialization.py` (174 行)
`to_json()` / `from_json()` — 调查员 JSON 序列化

---

## 9. 资源库

### `src/library/enemies.py` (145 行)
`LibraryEnemy` / `EnemyLibrary` — 加载 core/enemies.json + extensions，含 `[flag]` 解析（`adjacent_aware`/`avoidable`）

### `src/library/weapons.py` (97 行)
`LibraryWeapon` / `WeaponLibrary` — 加载 core/weapons.json + extensions

### `src/library/bosses.py` (69 行)
`LibraryBoss` / `BossLibrary` — 加载 core/bosses.json，含 `boss_mechanics` 字段

### `src/library/judgment.py` (121 行)
`JudgmentEngine`：T1 确定性 D100 检定 + 伤害掷骰 + SAN 损失 + T2 LLM 增强上下文

### `src/library/injector.py` (99 行)
`ContentInjector`：离线注入（模组构建时）+ 运行时动态注入（`runtime_spawn_enemy`）

---

## 10. Prompt 构建

### `src/prompts.py` (990 行)

| 函数 | 用途 |
|------|------|
| `build_keeper_parse_prompt(world, raw)` | Parse 阶段：玩家输入 → entity 匹配 |
| `build_keeper_enrich_prompt(world, entities, input)` | Enrich 阶段：检定结果 → 叙事润色 |
| `build_narrator_prompt(brief, l1, inv_info)` | Narrator：L1 + Brief → 沉浸式叙事 |
| `build_author_prompt(request, l3, ...)` | Author：Patch/StructuralEdit 判定 |
| `build_combat_entry_prompt(player_input, outcomes, enemy_ctx, scene)` | Combat entry：LLM 判定是否进入战斗 |
| `build_standoff_match_prompt(player_input)` | 对峙：语义匹配 → 技能名 |
| `build_stat_narrative_prompt(inv_desc, stat_name, delta, narrative)` | StatChange：LLM 更新调查员描述 |
| `build_consume_item_fuzzy_prompt(target, quantity, held_items)` | ConsumeItem：LLM 模糊匹配背包物品 |
| `build_combat_narrative_prompt(round_log, enemies_desc, player_name, scene)` | 战斗逐轮叙事 |
| `_build_investigator_info(world)` | 构建调查员状态摘要（供各 prompt 复用） |
| `_build_l1l3_context(l1, l3, location)` | L1/L3 基调约束 + 场景感知上下文 |
| `log_skill_result(detail)` | 技能检定写入日志 `skill_checks.txt` |
| `set_current_round(n)` | 设置当前回合号（供日志命名） |
| `_show_prompt(label, prompt)` | 调试用 prompt 打印（由环境变量控制） |

---

## 11. LLM 封装

### `src/llm.py` (490 行)

| 函数 | 用途 |
|------|------|
| `call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort, fallback_schema)` | **统一 LLM 调用入口**。DeepSeek API 封装。json_mode=True→temperature=0.2；False→0.7。fallback_schema 用于 JSON 解析失败时的保底输出 |
| `evaluate_trait_enhancement(inv_desc, skill_name, skill_detail, current_tier, entity_name, search_context)` | 特质修正评估 |
| `evaluate_failure_penalty(inv_desc, entity_name, skill_name, skill_detail, failure_tier, scene_context, graded_on_failure, retry_count)` | 失败惩罚生成 |

---

## 12. 离线管线

### `src/module_designer/layered_pipeline.py` (727 行)
`run_pipeline()` — 12 步渐进式解析入口，含 fallback 策略

### `src/module_designer/layered_parser.py` (1187 行)
各步 prompt 构建 + 解析函数。Phase 2 标准化 6 种 `@函数(参数)` 标记

### `src/module_designer/layered_schema.py` (325 行)
JSON Schema 定义 + `validate_all()` 三层验证

### `src/module_designer/supplement_pipeline.py` (280 行)
`run_supplement_pipeline()` — Author StructuralEdit 触发的轻量补充管线

### `src/module_designer/dependency_graph.py` (140 行)
依赖有向图：构建 + 循环检测 + cut edge

### `src/module_designer/l1_player.py` / `l2_keeper.py` / `l3_designer.py`
L1/L2/L3 数据模型定义

---

## 13. 前端

| 文件 | 功能 |
|------|------|
| `frontend/game_server.py` | Web 游戏服务器（localhost:8080） |
| `frontend/game.html` | 游戏循环 Web 界面 |
| `frontend/server.py` | 车卡 Web 服务器 |
| `frontend/character.html` / `.css` / `.js` | 5 步车卡向导（1920s 美学） |

---

## 14. 测试

| 文件 | 覆盖 | 类型 |
|------|------|------|
| `tests/test_enemy_manager.py` (9 case) | spawn/filter/group/combat/range/context | 单元 |
| `tests/test_combat_entry.py` (6 case) | SpawnEnemy→EnemyManager→combat lifecycle | 集成 |
| `tests/test_combat.py` (10 case) | damage/armor/tier/state/CombatSystem | 单元 |
| `tests/test_combat_harness.py` | CombatSystem 完整战斗流程 | 集成 |
| `tests/test_boss_manager.py` | BossManager spawn/combat_init | 单元 |
| `tests/test_boss_library.py` | BossLibrary load/get | 单元 |
| `tests/test_npc_manager.py` | NPCManager talk/attitude/serialize | 单元 |
| `tests/test_library.py` (18 case) | Weapon/EnemyLibrary + flag 解析 | 单元 |
| `tests/test_author_flow.py` (8 case) | Detector→Author→Keeper mock | 单元 |
| `tests/test_intent_detector.py` (3 case) | flavor/有意义/空输入 | 单元 |
| `tests/test_escalation_harness.py` (5 case) | 正常/flavor/Patch/Reject/StructuralEdit | 集成(真实LLM) |
| `tests/test_failure_penalty.py` (2 case) | Judge惩罚生成→Keeper enrich保留→Narrator接收 | 单元(全mock) |
| `tests/game_loop_harness.py` (7 轮) | parse→judge→enrich→narrate | 集成(真实LLM) |
| `tests/test_harness_stability.py` (2 case) | 正常探索 + 混合压力，3轮/每轮3turn | 集成(真实LLM) |
| `tests/test_harness_parallel.py` (16 case) | search/检定/依赖/AT/NPC/武器/move/对峙/战斗/道具/属性/结局 | 集成(真实LLM+mock) |
| 其他 | test_judge/dependency_graph/directed_graph/entity/entity_resolvers/curator/integration/module_designer | 单元+集成 |

---

## 15. 关键数据流速查

```
离线管线: .docx → layered_pipeline(12 LLM calls) → l1/l2/l3.json

运行时加载: l2.json → DirectedGraph → ScenarioWorld(enemy_manager, weapon_library, scene_weapons)
            l1.json → Narrator
            l3.json → Author
            enemies.json → EnemyLibrary → EnemyManager
            weapons.json → WeaponLibrary
            bosses.json → BossLibrary → BossManager

单回合: user_input → Keeper.process_turn()
           ├─ parse(LLM flash) → intent matches
           ├─ judge(deterministic) → D100 check + @markup resolve + [失败≥3次 → 惩罚系统(LLM) → penalty narrative + markup_effects]
           ├─ [enrich(LLM flash) ∥ combat_entry(LLM flash) ∥ TimeAgent(LLM)]
           ├─ [对峙(avoidable敌人): 语义匹配(LLM flash) → D100 → trait_enhancement]
           ├─ curate → NarratorBrief
           ├─ [IntentDetect → Author → Patch/StructuralEdit (按需)]
           └─ narrator(LLM) → immersive narrative
           ╎ 独立管线: skill_detail(骰值/难度递增/惩罚标记) → CLI skill_results + 日志
           ╎          TimeAgent → clock.advance_time() + time_context

战斗: CombatInit → CombatSystem.run_combat()
        ├─ _init_combat → CombatState
        ├─ 逐轮: 玩家动作(D100) + 敌人动作(D100) + 伤害(公式+护甲)
        └─ CombatResult → EnemyManager.exit_combat()
```

---

## 16. 环境约定

- **Python path**：所有命令需要 `PYTHONPATH="src;."`（Windows）或 `PYTHONPATH="src:."`（Unix）
- **测试命令**：`cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/<file> -v --tb=short`
- **LLM 模型**：默认 `deepseek-v4-pro`（重推理），flash 任务用 `deepseek-v4-flash`（轻量）
- **推理强度**：`reasoning_effort`: 重任务 `"high"`，轻任务 `"low"`
- **JSON mode**：结构化判定 `json_mode=True`（temperature=0.2），叙事生成 `json_mode=False`（temperature=0.7）
