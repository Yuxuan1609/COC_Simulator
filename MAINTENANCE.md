# MAINTENANCE.md — 维护文档（函数级）

> 记录所有模块的函数/类级信息：功能、签名、关键行号、上下游调用关系。
> **规则：每次修改代码文件后，必须同步更新本文档对应条目（行号/签名/功能）。** 另见 `agents.md`。

---

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-08-10 | 全量重写：覆盖 src/ + frontend/ + run_*.py + scripts/ + tools/（不含 tests/、notebooks/）。补齐 monitor、module_designer 子模块、llm_player、utils 等此前缺失部分，行号按 2026-08-10 代码快照更新 |

---

## 总体架构

```
run_game.py / run_pipeline.py / run_step0.py (入口)
  └─ src/game_loop.py       游戏主循环 (init_game / run_turn)
  └─ src/module_designer/   模组解析管线 (layered_parser / layered_pipeline / supplement_pipeline)
       └─ src/llm.py        统一 LLM 入口 (call_deepseek) + 传感器埋点
       └─ src/prompts.py    全部 prompt 构建
       └─ src/config.py / src/config_llm.py  配置
       └─ src/utils.py      文件解析 / token 估算 / 掷骰
  ├─ src/game/              Keeper 回合系统 (agents/ + combat + judge + npc/enemy/boss manager + clock)
  ├─ src/scenario_core.py   数据模型 + 世界状态 (DirectedGraph / ScenarioWorld / MemoryManager / WorldChronicle)
  ├─ src/investigator/      调查员系统 (COC 7th 车卡/检定)
  ├─ src/library/           武器/敌人/Boss 资源库 + 注入器 + 判定引擎
  ├─ src/monitor/           LLM 传感器 + 降级策略 + 回合监控 (管线健康)
  ├─ src/llm_player.py      LLM 自动玩家（测试用）
  ├─ frontend/              FastAPI 服务 + 6 个路由 (launcher/game/character/editor/files/assets)
  ├─ scripts/               库提取等辅助脚本
  └─ tools/                 解析器调试工具
```

---

## 入口脚本

### run_game.py (595 行) — CLI 文字跑团主入口

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_game` | `(character_path=None)` | 主循环：init_game → 加载调查员 → 开场回合 → 命令分发（/scene /info /events /flags /char /save /load /help /spawn）→ 普通回合 → 战斗交互子循环 → 结局判定 | 44 |
| `_build_scene_snapshot` | `(world) -> dict\|None` | 从 world 构建 PlayerFacingSnapshot 格式 dict（场景/出口/时间/NPC/敌人） | 210 |
| `_scene_text` | `(world)` | `/scene` 命令：快照 → Markdown 场景文本 | 227 |
| `_g` | `(obj, key, default=None)` | dict 与 dataclass 通用安全取值 | 234 |
| `_format_snapshot_chapters` | `(snap) -> str` | 快照格式化为半结构化 Markdown（场景/角色/时间/技能） | 241 |
| `_print_turn_output` | `(snap, brief, narrative)` | 打印回合输出 | 340 |
| `_run_interactive_combat` | `(game, combat_init)` | CLI 回合制战斗子循环（调用 CombatSystem） | 355 |

### run_pipeline.py (1459 行) — 模组解析管线 CLI

| 函数/类 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_load_document` | `(path) -> str` | 按扩展名加载 .docx/.txt/.pdf | 38 |
| `_pick_file_gui` | `() -> str` | tkinter 文件对话框选文档 | 66 |
| `_pick_file_scan` | `() -> str` | 扫描当前目录列文档供选择 | 90 |
| `PipelineConfig` | dataclass | 管线配置（路径/模型/温度/执行/注入开关），to_dict/to_json/from_dict/from_json/from_wizard | 176 |
| `LLMLogger` | `(output_dir)` | 包装 llm_json/llm_text，每次调用保存 prompt+response 到 `_llm_calls/<n>/`；wrap_json @371 / wrap_text @423 / call_log @467 | 352 |
| `PipelineAborted` | exception | 用户中止管线 | 475 |
| `InteractiveRunner` | `(config)` | 运行器：`_step_dir`@529 `_save_summary`@534 `_prompt_user`@538 `_handle_retry`@552 `_handle_edit`@573 `_handle_config_change`@600 `_interact`@658 | 480 |
| `_RetryStep` | exception | 重试当前步骤 | 676 |
| `_do_step1` | `(runner, verbose)` | Step1a 结构化提取 + 1b 精修（并行） | 685 |
| `_do_step2a` | `(runner, verbose)` | Step2a interactions 提取 | 737 |
| `_do_step2bc` | `(runner, verbose)` | Step2b+2c: events+AT + L1 + L3（并行） | 773 |
| `_do_step3a_25` | `(runner, verbose)` | Step3a 去重冲突 + 2.5 NPC 档案（并行）→ 绑定 → Boss 遭遇 → 组装 L2 | 827 |
| `_do_step3b` | `(runner, verbose)` | L1↔L2 交叉核对 + WR0 注入 | 918 |
| `_do_step35_phase1` | `(runner, verbose)` | Step3.5 依赖图（含循环重试）+ Phase1 约束 | 952 |
| `_do_phase2_finalize` | `(runner, verbose)` | Phase2 精简标准化 → 重组装 → Schema/交叉引用验证 → 保存 l1/l2/l3 最终产物 | 1019 |
| `run_interactive` | `(config)` | 手动步进模式（每步 [c]继续 [r]重试 [e]编辑 [m]改配置 [q]退出），支持 start_from 断点续跑 | 1158 |
| `run_auto` | `(config)` | 自动模式：复用同一组 `_do_step*` 全程无交互 | 1235 |
| `main` | `()` | argparse CLI：--auto/--config/--docx/--module/--start-from/--model/--thinking-off/--weapon-lib 等 | 1329 |

### run_step0.py (184 行) — 小说 → 模组文本转写

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `STEP0_SYSTEM` | str 常量 | 两阶段系统提示（先以作者理解故事、再以设计师改写为模组格式） | 13 |
| `run_step0` | `(input_path, output_path=None)` | 读取小说 → 构建 prompt → LLM 长文本转写 → 保存 `module_step0.txt` + system/user prompt 副本 | 127 |

### run_step1b_test.py (48 行)

单步测试脚本：直接对源文档执行 Step 1b（精修浓缩），输出 condensed 文本，用于快速验证 1b 质量。

### imp.py / test.py

`imp.py` — 两行快速 import 冒烟；`test.py` — 简单调用测试。均无函数定义。

---

## src/game/messages.py (302 行) — 消息类型 / 契约

| 类 | 字段/说明 | 作用 | 行号 |
|----|-----------|------|------|
| `IntentResult` | `needs_author, intent, reasoning` | IntentDetector 输出 | 12 |
| `AuthorRequest` | `other_texts, intent, reasoning, scene_context` | Detector→Author 请求 | 20 |
| `ActionIntent` | `action, target, skill_checks` | Parse 解析出的玩家意图 | 29 |
| `ActionOutcome` | `intent, success, message, entity_id, entity_type, side_effects, skill_tier, skill_detail, enhancement` | 单个 entity 执行结果 | 39 |
| `SceneSnapshot` | `location, description, exits, perceptible_interactions, visible_npcs` | 场景信息快照 | 53 |
| `NarratorBrief` | `action_outcomes, ambient_changes, scene_snapshot, suggested_emphasis, enriched_summary` | KP→Narrator 策展结果 | 63 |
| `ModulePatch` | `entities, scene_descriptions, justification` | Author→Keeper 实体补丁 | 73 |
| `StructuralEdit` | `supplement_path, l3_updates, entry_scene, exit_scene, justification` | Author→Keeper 结构扩展 | 81 |
| `TurnInput` | `raw_text, player, action_type, action_target` | 回合入口数据；action_type 非空 → 跳过 LLM parse | 91 |
| `CombatEntryCheck` | `enter_combat, enemy_instance_ids, reasoning` | LLM 判定是否进入战斗 | 100 |
| `StandoffMatch` | `matched, skill_name, reason` | 对峙语义匹配 | 108 |
| `CombatInit` | `enemies, player, scene, initiative_context, environment_actions, player_action, player_targets, player_extra` | →CombatSystem 初始化 | 116 |
| `CombatResult` | `outcome, defeated_instance_ids, narrative, player_hp, player_san, rounds, round_log` | 战斗结果 | 135 |
| `SkillCheckResult` | `entity_id, entity_type, skill_name, raw_roll, target, tier, success, enhancement` | 单次技能检定记录 | 147 |
| `PlayerFacingSnapshot` | `scene_name, scene_description, exits, time, npcs, enemies, combat, skill_checks, investigator` | 面向前端/CLI 的回合快照 | 160 |
| `RoundResult` | `round, player_action, player_target, player_roll, player_tier, player_damage, player_damage_type, player_effects, enemy_actions, status_changes, narrative` | 单回合战斗结果 | 178 |
| `Phase` | `trigger, name, overrides, description` | Boss 阶段定义 | 194 |
| `TimeCommsPacket` | `game_time, day, time_of_day, current_scene, player_actions, world_state` | Keeper→Author 时间通信包 | 203 |
| `PreParseResult` | `clarity, interpretation, question, resolved_text` | Pre-parse 消歧输出 | 214 |
| `EnrichInput` | `entities, actions` | parse→enrich 中间体 | 223 |
| `TurnStatus` | Enum: COMPLETED / SUSPENDED / FROZEN | 回合终局状态 | 232 |
| `PendingInteraction` | `kind, question, interaction_id` | 挂起待答问题（weapon_offer/standoff/clarify） | 240 |
| `EndingInfo` | `name, narrative, game_over` | 结局信息 | 248 |
| `TurnDiagnostics` | `combat_entry, time_agent, enrich_raw, pre_parse` | 低频/调试数据入口 | 256 |
| `TurnResult` | `status, brief, text, pending_interaction, combat_init, ending, npc_events, warnings, frozen_message, diagnostics` | **Keeper.process_turn 内部契约返回**；`__post_init__` 校验 SUSPENDED 必须带 pending_interaction | 265 |
| `PlayerTurnResult` | `status, brief, narrative, pending_interaction, player_snapshot, skill_results, combat, combat_init, ending, game_over, timestamp, diagnostics` | **run_turn 玩家面契约返回** | 289 |

---

## src/game/agents/keeper.py (1633 行) — Keeper 回合编配

### 模块级函数

| 函数 | 作用 | 行号 |
|------|------|------|
| `_describe_time_condition` | 时间条件 → 自然语言 | 32 |
| `_build_investigator_weapon` | 库武器 → 调查员 Weapon 实例 | 71 |

### Keeper 类（@93）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(world, phase1=None)` | 初始化 Judge/Curator/IntentDetector/PreParse/AgentMonitor/TurnMonitor | 99 |
| `process_turn` | `(turn_input, author=None, _depth=0) -> TurnResult` | **主流程**：weapon_offer 应答（严格只认「是/否」，其他输入作废 offer 走正常回合）→ 直接拾取通路（捡/拾/拿+武器名直接入包）→ 深度保护 → NPC AT 注入 → pre-parse 消歧/动作捷径 → LLM parse → NPC 对话分流 → 后续 parse/judge/enrich/combat/TimeAgent/Author → curate → memory | 134 |
| `_detect_direct_pickup` | `(raw) -> str \| None` | 直接拾取意图：拾取动词+场景武器名（场景仅一件可不点名），含否定词/已持有时不触发 | 1212 |
| `_devour_standoff_for_boss` | `(standoff_prompt, combat_init_result, all_outcomes, enrich_input) -> None` | F3：Boss 强制战吞掉对峙——撤回 standoff 播种/话术，avoidable 敌人并入 Boss 战（at 与 event 两条 engage 通路共用） | 1249 |
| `_grant_scene_weapons` | `(offer_list) -> str` | 发放武器入包并从场景移除，返回「、」连接名串（offer 应答与直接拾取共用） | 1219 |
| `_build_frozen_response` | `(exc)` | TurnFrozenError → FROZEN TurnResult | 911 |
| `_scan_ending` | `(outcomes, author)` | 检查 ##END_*## 结局标记并触发 | 919 |
| `complete_combat_turn` | `(original_input, combat_result)` | 战斗后回放 enrich→curate | 936 |
| `resolve_standoff` | `(standoff_state, player_input)` | 对峙：LLM 匹配技能 → D100 → 特质修正 | 976 |
| `_check_boss_requirements` | `(boss_entity, player_action)` | Boss 遭遇触发条件检查 | 1052 |
| `_evaluate_boss_soft_condition` | `(soft_condition, player_action, boss_name)` | Boss 软条件 LLM 评估 | 1077 |
| `_inject_npc_at` | `()` | 当前场景 NPC bound entity → 注入 node | 1104 |
| `_apply_pending` | `()` | 应用延迟副作用 + 移动 + NPC 跟随实体注入 | 1143 |
| `_parse` | `(raw) -> list[dict]` | LLM parse：玩家输入 → action 列表 | 1179 |
| `_enrich` | `(judged_entities, user_input) -> dict` | LLM enrich：合并判定结果 | 1212 |
| `_log_agent_response` | `(filename, data)` | 记录 agent 响应日志 | 1242 |
| `_find_entity_by_id` | `(entity_id)` | graph+NPC+boss 按 ID 查找 | 1255 |
| `_process_deterministic_only` | `(turn_input)` | 深度超限/降级时纯确定性执行 | 1290 |
| `_build_world_brief` | `()` | 构建 pre-parse 用世界简报 | 1311 |
| `_build_world_snapshot` | `()` | 构建世界快照 dict | 1327 |
| `_infer_time_category` | `(entity)` | 实体时间类别推断 | 1339 |
| `_run_time_agent` | `(action_summaries, raw)` | 调用 TimeAgent 评估时间 | 1346 |
| `_build_scene_context_for_author` | `()` | 构建 Author 场景上下文（含 chronicle 渲染） | 1448 |
| `_integrate_supplement` | `(structural_edit, author, intent, reasoning)` | 补充管线 → 集成到 graph；成功后 record_patch(level="structural") | 1465 |
| `_load_scene_into_graph` | `(scene_name, scene_data)` | 新场景注入 graph（补充管线产物） | 1554 |
| `_integrate_patch` | `(patch)` | ModulePatch 实体集成 + record_patch(level="patch") | 1608 |

## src/game/agents/narrator.py (57 行) — 叙事者

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(l1_data)` | 持有 L1 数据 | 17 |
| `narrate` | `(brief, snap=None, user_input="") -> (brief, narrative, scene_update)` | KP 简报 → 沉浸式叙事 | 24 |
| `_build_prompt` | `(brief, l1_scene, snap, user_input)` | 构建叙事 prompt | 54 |

## src/game/agents/author.py (136 行) — 作者（创作者层）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(l3_data, persona="")` | 持有 L3 数据 | 29 |
| `handle_request` | `(request, turn_number=0) -> ModulePatch\|StructuralEdit` | 两级响应：Patch / StructuralEdit | 43 |
| `update_l3` | `(l3_updates)` | 增量更新 L3 | 94 |
| `assess_time_pressure` | `(comms_packet)` | 评估时间压力 | 99 |

## src/game/agents/time_agent.py (88 行) — 时间评估

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `build_prompt` | `(actions, current_input, time_costs=None)` | 构建时间评估 prompt | 29 |
| `assess` | `(actions=None, current_input="", time_costs=None, **kwargs) -> {time_delta, narrative_hint}` | LLM 评估本轮时间消耗 | 64 |

## src/game/combat.py (1242 行) — 战斗系统 v2

### 模块级函数

| 函数 | 作用 | 行号 |
|------|------|------|
| `_roll_damage` | 从 dict/legacy 公式掷伤害骰 | 15 |
| `_parse_legacy_damage` | 旧式伤害公式解析 | 65 |
| `_apply_armor` | 护甲减免 | 92 |
| `_apply_damage_multiplier` | 伤害类型倍率 | 99 |

### CombatSystem（@150）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_combat` | `(combat_init, player_action="", max_rounds=20) -> CombatResult` | **主入口**：完整战斗循环（确定性 → LLM 修正 → 结算 → Boss 阶段） | 168 |
| `run_single_round` | `(combat_init, state, action_id, target_ids, player_extra="") -> dict` | 交互式单回合（前端回合制） | 362 |
| `_build_single_round_result` | `(state, combat_init) -> dict` | 单回合结果 dict（胜负判定/回合叙事） | 525 |
| `_generate_combat_narrative` | `(state, player, scene, log_dir)` | 战斗叙事生成 | 576 |
| `_init_combat` | `(combat_init) -> CombatState` | 初始化：展开 quantity 群组，按 DEX 排先攻 | 657 |
| `_match_action` | `(raw_input, available)` | 文本 → 动作 ID 匹配 | 705 |
| `_get_player_actions` | `(player, environment_actions)` | 固定动作列表（拳/踢/回避/逃跑/武器/环境） | 737 |
| `_skill_value` | `(player, skill_name)` | 技能值查询 | 777 |
| `_resolve_player_action` | `(state, player, action_id, target_iid, environment_actions)` | 执行玩家动作 | 788 |
| `_get_tier` | `(roll, skill_value)` | COC 四级检定 | 907 |
| `_select_enemy_attack` | `(enemy)` | 按权重随机选攻击 | 919 |
| `_select_enemy_target` | `(state, enemy)` | 敌人选目标 | 927 |
| `_resolve_enemy_action` | `(state, enemy, player)` | 执行敌人动作 | 931 |
| `_check_phase` / `_apply_phase` | — | Boss 阶段切换 | 978 / 1002 |
| `_any_special_rules` | `(combat_init, enemies)` | 是否有 special_rules 需要 LLM | 1023 |
| `_build_battle_snapshot` | `(state, player, boss_phase)` | LLM 用战斗快照 | 1033 |
| `_build_round_result` | `(state, player_actions, enemy_actions, round_num)` | RoundResult 构建 | 1052 |
| `_llm_correct_round` | `(round_result, combat_init, enemies, player_extra, battle_snapshot, boss_phase, player_actions)` | LLM 修正玩家回合伤害 | 1080 |
| `_llm_correct_enemy_round` | `(enemy, action_data, player, player_extra, investigator_context)` | LLM 修正敌人攻击 | 1187 |

## src/game/judge.py (368 行) — 确定性闸门（无 LLM 依赖）

| 函数/方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_escalate_difficulty` | `(difficulty)` | 难度递增 regular→hard→extreme | 25 |
| `Judge.check_auto_triggers` | `()` | 触发当前场景满足简单条件的全部 AT | 47 |
| `Judge.execute_interaction` | `(intent, player_input="")` | 执行解析出的互动意图 | 63 |
| `Judge._execute_entity` | `(entity, intent=None, player_input="")` | **核心**：重复执行拦截 → NPC 特殊实体(follow/interact unlock) → 硬 requirement → 技能检定+特质增强 → ##GRADED## 解析 → @markup 剥离 → 失败惩罚/难度递增 → 完成标记 | 93 |
| `_split_requirement` | `(req) -> (hard, soft)` | `\|\|` 拆分硬/软条件 | 301 |
| `_is_simple_requirement` / `_check_simple_requirement` | — | AT 简单条件判定 | 312 / 323 |
| `_evaluate_requirement` | `(req) -> (bool, msg)` | flag: → AND/OR 解析 → 边依赖检查 | 334 |

## src/game/curator.py (68 行) — 策展器

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `assemble` | `(outcomes, ambient_changes, emphasis="", enriched_summary="") -> NarratorBrief` | 判定结果 + 场景快照 → NarratorBrief | 17 |
| `_build_snapshot` | `() -> SceneSnapshot` | 收集当前场景元数据 | 32 |

## src/game/side_effects.py (150 行) — @markup 副作用

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `ItemGain` / `ConsumeItem` / `StatChange` / `SpawnEnemy` / `GrantWeapon` / `SceneWeapon` / `NPCStateChange` / `NPCFollow` | @标记 dataclass | 8–55 |
| `_parse_kwargs` | `@标记(...)` 参数解析 | 68 |
| `_build_side_effect` | 函数名+kwargs → dataclass | 81 |
| `parse_markup` | 解析单个文本中的 @标记 | 131 |
| `parse_markup_all` | `(text) -> list` 解析全部 @标记 | 141 |

## src/game/npc_manager.py (411 行) — NPC 管理

### NPC dataclass（@10）字段：`name, role, personality_notes, appearance, what_they_can_do, interaction_triggers, can_follow, follow_requirements, can_interact, interact_requirements, bound_interactions, bound_auto_triggers, scene, attitude, following, memory, state, extra`

### NPCManager（@85）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_check_follow_conditions` | `(npc, world)` | 跟随条件检查 | 94 |
| `init_from_profiles` | `(profiles)` | 从 L2 npc_profiles 批量初始化 | 131 |
| `get` | `(name)` | 按名查询 | 155 |
| `get_in_scene` / `get_in_scene_snapshot` | — | 场景内 NPC（排除 dead/left）/ 轻量快照 | 158 / 162 |
| `talk_to` | `(npc_name, player_input, llm_call, world=None)` | state→can_interact→interact_requirements 门禁 → LLM 对话 | 175 |
| `set_attitude` / `set_following` / `get_following` / `set_state` / `set_scene` | — | 状态操作 | 244–259 |
| `sync_followers` | `(scene)` | 跟随 NPC 同步到新场景 | 265 |
| `to_dict` / `from_dict` | — | 序列化 | 273 / 289 |
| `process_npc_turn` | `(npc_name, user_input, world, llm_json, llm_text, judge, curator)` | 独立 API：talk_to→parse→judge→enrich→curate（主循环不调用） | 315 |

## src/game/enemy_manager.py (275 行) — 敌人管理

### EnemyInstance 字段：`instance_id, enemy_ref, scene, quantity, status, flags, combat_behavior, description, attributes, armor, attacks, special_abilities, san_loss, hp, boss_mechanics, multi_attack, damage_multipliers, dodge_bonus, special_rules, phases, _current_phase`

### EnemyManager（@40）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `spawn` | `(enemy_ref, scene, quantity=1)` | 从库实例化（同场景同类合并） | 47 |
| `remove` / `set_status` / `register` | — | 状态操作 | 89 / 139 / 143 |
| `get_active_in_scene` / `get_active_in_range` / `get_active_in_scene_snapshot` / `group_by_ref` / `get_by_id` | — | 查询族 | 94–160 |
| `add_to_combat` / `mark_defeated` / `mark_dead` | — | 战斗标记 | 147–157 |
| `enter_combat` / `exit_combat` | — | 批量 engaged / win→defeated、非 win→hostile | 163 / 170 |
| `get_combat_context` | `(scene, graph=None)` | 战斗判定用文本 | 185 |
| `to_dict` / `from_dict` | — | 序列化 | 201 / 227 |

## src/game/boss_manager.py (140 行) — Boss 管理

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `has_spawned` / `mark_spawned` | — | 防重复开战 | 14 / 17 |
| `check_by_engage_type` | `(engage_type, *, scene=None)` | 按 at/interaction/event 过滤遭遇 | 20 |
| `_create_instance` | `(boss_entity, scene)` | Boss 库 → EnemyInstance（CON+SIZ→HP） | 31 |
| `spawn_instance` | `(boss_entity)` | init 时预生成实例 | 69 |
| `build_combat_init` | `(boss_entity, player, scene, enemy_manager=None)` | 复用预生成实例或新建 → CombatInit | 73 |
| `active_boss_id` / `set_active` | property / setter | 活跃 Boss | 92 / 103 |
| `resolve_outcome` | `(combat_result)` | 战斗结果透出 | 106 |
| `active_snapshot` | `()` | 快照中的活跃 Boss 信息 | 111 |
| `to_dict` / `from_dict` | — | 序列化 | 126 / 135 |

## src/game/clock.py (60 行) — 游戏时钟

| 成员 | 说明 | 行号 |
|------|------|------|
| `day` / `hour` / `time_of_day` | property：分钟 → 天/小时/5 时段（夜间/早晨/白天/黄昏） | 14 / 18 / 22 |
| `advance_time` | `(minutes)` 推进时钟 | 34 |
| `get_time_flags` | `{day:N:True, time:period:True}` | 37 |
| `to_dict` / `from_dict` | 序列化 | 43 / 54 |

## src/game/pre_parse.py (89 行) — 消歧网关

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `disambiguate` | `(player_text, world_brief="") -> PreParseResult` | 判断输入清晰/模糊，跨 turn 整合，模糊 → 提问（SUSPENDED） | 32 |

## src/game/intent_detector.py (65 行) — 叙事意图检测

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `detect` | `(other_text, world_snapshot) -> IntentResult` | Flash 模型判断 'other' 输入是否有真实叙事意图（与 Enrich 并行）；降级时默认触发 Author | 23 |
| `_build_prompt` | `(other_text, world_snapshot)` | 构建检测 prompt | 47 |

## src/game/turn_logger.py (47 行) — 回合日志

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `log` | `(player_input, enrich_result, narrator_brief, narrator_narrative)` | 回合写为 `turn_NN.json` + `turn_log.jsonl` | 23 |

---

## src/game_loop.py (902 行) — 游戏主循环

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `set_turn_logger` | `(logger)` | 设置全局回合日志器（harness/入口调用） | 21 |
| `setup_logging` | `() -> str` | 统一初始化日志目录 + TurnLogger + prompt/llm 日志 | 27 |
| `_handle_spawn_command` | `(user_input, world, weapon_lib=None, enemy_lib=None, injector=None, keeper=None)` | 调试命令：/spawn enemy\|weapon、/inject [toggle\|status]、/health（TurnMonitor/PipelineHealth 快照） | 46 |
| `init_game` | `(l2_path, l1_path, l3_path, start_node="6号车厢", wr0_enabled=False) -> dict` | 从 JSON 初始化：_scene_names 重映射 → 库加载 → ScenarioWorld → world 节点 AT 执行（延后 item_gain）→ at 型 Boss 预生成 → time_costs → Narrator/Keeper/Author | 154 |
| `run_turn` | `(game, user_input, weapon_lib=None, enemy_lib=None, injector=None, action_type="", action_target="") -> PlayerTurnResult` | **一回合**：自动存档检查 → 调试命令 → 对峙挂起分发 → keeper.process_turn → 回合末写编年史（chronicle.record_turn + 移动轨迹，FROZEN 不计，SUSPENDED 也入史）→ SUSPENDED/FROZEN 短路 → Narrator 叙事 → 场景更新 → 技能检定提取 → PlayerFacingSnapshot 组装（L1 描述/NPC 富化/技能 D100 解析） | 321 |
| `save_game` | `(game, path)` | 存档 + `_meta.turn_number` 写入 | 624 |
| `load_game` | `(game, path)` | 读档并回填世界属性 + turn_number | 640 |
| `_autosave_callback` / `start_autosave` / `_check_autosave` | — | 定时自动存档（AUTOSAVE_INTERVAL_SEC，最多 AUTOSAVE_MAX_COPIES 份轮换） | 666 / 675 / 686 |
| `continue_standoff` | `(keeper, player_input) -> TurnResult` | 对峙回避尝试：成功→下一组/进入战斗；失败→战斗；战斗内联跑（自动胜利短接）→ complete_combat_turn | 703 |
| `format_turn_dynamic` | `(player_snapshot, brief, narrative) -> str` | 快照动态信息（时间/战斗/技能检定）+ 叙事 → 纯文本（CLI/LLM 玩家复用） | 820 |

---

## src/scenario_core.py (1643 行) — 数据模型 + 世界状态

### 数据类 / 基础模型

| 类 | 字段/说明 | 行号 |
|----|-----------|------|
| `Edge` | `target, method, requirement` — 场景通行边 | 39 |
| `Requirement` | `raw, entity_id, negated, flags` — 条件解析结果 | 49 |
| `Interaction` | 互动摘要模型 | 57 |
| `ActionResult` | `success, message, ...` | 71 |
| `Entity` | `id, entity_type, name, scene, type, requirement, trigger, result, side_effects, graded_result, difficulty, extra, time_condition` — 统一实体；`from_dict` 工厂 @109 | 89 |
| `Node` | `node_id, description, edges, to_here, interactions, auto_triggers, encounters, scene_weapons, extra`；`get_interaction`@264 `get_auto_trigger`@270 | 253 |
| `NodeRuntimeState` | `completed, result_tier, retries, escalated_difficulty` | 278 |

### 顶层函数

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `read_json_file` | `(file_path)` | 读 JSON | 29 |
| `find_entity_by_id` | `(world, entity_id)` | 场景+事件+NPC 联合查找 | 77 |
| `resolve_graded_result` | `(entity, tier) -> str` | 解析 `##GRADED##` 四档结果 | 138 |
| `has_ending` | `(text) -> (name, narrative)` | 检测 `##END_*:desc##` | 162 |
| `check_time_condition` | `(time_condition, day, time_of_day)` | 时间条件检查 | 173 |
| `_normalize_requirement` / `_side_effect_to_dict` | — | 内部工具 | 213 / 228 |
| `parse_hard_requirement` | `(hard, runtime_state)` | AND/OR/括号/flag 条件解析 | 563 |
| `apply_side_effects` | `(world, side_effects, npc_events=None, direct_weapon_callback=None)` | 副作用应用到世界（spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change/npc_follow） | 1212 |

### DirectedGraph（@290）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `load_scenes` / `load_events` | — | 从 dict/list 加载 | 307 / 347 |
| `get_edges_from` / `get_interactions` | — | 查询出边/互动 | 356 / 361 |
| `get_event` / `get_all_event_ids` | — | 事件查询 | 366 / 369 |
| `remove_node` / `remove_edge` | — | 图修改（补充管线用） | 374 / 382 |
| `to_dict` / `from_dict` | — | 序列化 | 399 / 450 |

### RequirementResolver（@504）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `check` / `get_unmet` / `resolve_chain` | — | 条件解析（check @510 / get_unmet @528 / resolve_chain @545） | 504 |

### ScenarioWorld（@650）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(graph, start_node, background_story, wr0_enabled, enemy_library, weapon_library, boss_library, boss_encounters, npc_profiles)` | 初始化世界 + Clock/EnemyManager/NPCManager/BossManager/MemoryManager/WorldChronicle（`self.chronicle` @685） | 663 |
| `game_time` / `day` / `hour` / `time_of_day` / `time_context` | property | 时钟透出 | 722–742 |
| `advance_time` | `(minutes)` | 推进时间 + 注入时间标记 | 745 |
| `load_dependency_graph` | `(dep_graph)` | 加载 L2 依赖图 → 注册 Boss 节点 | 766 |
| `get_runtime_state` / `get_incoming_edges` / `check_edge_requirements` | — | 运行时状态/依赖检查 | 795 / 801 / 806 |
| `mark_completed` / `is_entity_completed` | — | 完成标记 | 826 / 833 |
| `set_background` / `set_player` / `load_player` | — | 状态设置 | 842–852 |
| `get_current_description` / `get_possible_exits` / `get_available_interactions` | — | 场景查询 | 862–869 |
| `is_interaction_completed` / `are_entity_requirements_met` | — | 完成/条件判断 | 879 / 883 |
| `get_scene_summary` / `get_scene_info` | — | 场景汇总（前端/NPC 用） | 898 / 947 |
| `move` | `(target) -> ActionResult` | 移动 + NPC 跟随同步 | 970 |
| `is_event_triggered` / `get_active_event_effects` | — | 事件状态 | 995 / 998 |
| `build_snapshot` | `() -> dict` | **单源快照**供所有 prompt builder/前端 | 1007 |
| `set_npc_state` / `get_npc_state` | — | NPC 状态快捷 | 1040 / 1043 |
| `apply_world_update` / `apply_scene_update` | — | 叙事回写 | 1047 / 1051 |
| `to_dict` / `from_dict` | — | 序列化（含 `chronicle` 键） | 1056 / 1097 |
| `save_state` / `load_state` | — | 全量存档/恢复 | 1129 / 1148 |

### MemoryManager（@1366）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `add_record` / `note_item` / `should_compress` / `compress` / `get_context` | — | 交互记录 / 物品记忆 / LLM 压缩 / 上下文构建 | 1381–1441 |
| `to_dict` / `from_dict` | — | 序列化 | 1463 / 1473 |

### WorldChronicle（@1490）— 世界状态摘要层（LLM 饲料，本期消费者=Author；挂载于 ScenarioWorld.chronicle）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `record_turn` | `(turn_number, raw_input, result, world)` | 每回合末记录事件（窗口15）+ entity_results（截断100） | 1507 |
| `record_patch` | `(turn, level, entity_ids, new_scenes, justification)` | 补丁清单（append-only，justification 截断100） | 1539 |
| `compress_events` | `(llm_call)` | LLM 蒸馏预留接口，本期不接线（NotImplementedError） | 1549 |
| `render_for_author` | `(world) -> str` | 渲染【世界真值】+【已注入内容】+【编年史】 | 1555 |
| `_render_event` | `(e) -> str` | 单条事件紧凑渲染 | 1610 |
| `to_dict` / `from_dict` | — | 序列化（events 转 list） | 1628 / 1637 |

---

## src/investigator/ — 调查员系统（COC 7th）

### models.py (413 行)

| 类/方法 | 说明 | 行号 |
|---------|------|------|
| `Stats` / `DerivedStats` / `Skill` / `Occupation` / `Weapon` / `InventoryItem` | 数据类 | 14–83 |
| `ItemManager` | 背包：add/remove/has/get/list_all/describe/to_dict/from_dict | 91–141 |
| `Investigator.__init__` | 构造调查员 | 154 |
| `skills_dict` / `get_skill` / `get_skill_value` | 技能查询 | 193 / 199 / 205 |
| `check_skill` | `(skill_name, difficulty="regular")` COC D100 检定 | 211 |
| `check_skills` | `(skill_names)` 批量检定 | 256 |
| `build_snapshot` | 玩家状态快照 | 274 |
| `_recalc_derived` | 重算衍生属性 | 292 |
| `modify_stat` | `(stat_name, delta)` 支持骰子公式 | 298 |
| `modify_skill` / `has_item` / `list_items` | — | 375–386 |
| `add_weapon` / `remove_weapon` | 武器管理 | 390 / 393 |
| `save` / `load` | JSON 存档 | 400 / 406 |

### rules.py (304 行) — 纯函数规则引擎

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `roll_stats` | `() -> Stats` | COC 7th 掷骰生成属性 | 17 |
| `_calc_db_build` | `(str_siz)` | DB/BUILD 计算 | 36 |
| `calc_derived` | `(stats, age=20, cthulhu_mythos=0)` | 衍生属性 | 52 |
| `resolve_base_value` | `(base, stats)` | 基础值解析 | 113 |
| `create_skill_list` | `() -> list[Skill]` | 完整技能列表 | 118 |
| `allocate_skill_points` | `(skills, occupation_skills, occupation_points, interest_points)` | 技能点分配 | 132 |
| `calc_occupation_points` | `(formula, stats)` | 职业点公式 | 162 |
| `apply_age_modifiers` | `(stats, age)` | 年龄修正 | 189 |
| `get_credit_level` | `(value)` | 信用等级 | 237 |
| `create_default_unarmed` / `create_default_dodge_skill` | — | 默认技能 | 250 / 260 |
| `load_occupations` | `(path)` | 职业 JSON 加载 | 275 |
| `calc_db` | `(STR, SIZ)` | DB 字符串 | 293 |

### serialization.py (184 行)

| 函数 | 说明 | 行号 |
|------|------|------|
| `_occupation_dict_to_obj` | 职业 dict→对象 | 15 |
| `to_dict` / `to_json` / `from_dict` / `from_json` | Investigator ↔ dict/JSON | 27–180 |

---

## src/library/ — 资源库

### enemies.py (180 行) — EnemyLibrary（@137）

| 方法 | 作用 | 行号 |
|------|------|------|
| `load_core` / `load_extension` / `_load_file` | 加载 core + 扩展 | 143 / 150 / 153 |
| `get` / `list_all` / `search` / `__len__` | 查询族 | 160–176 |

数据类：`EnemyAttack`@11 `SpecialAbility`@46 `LibraryEnemy`@59（`from_dict` 解析 [flag] 标记）。

### weapons.py (136 行) — WeaponLibrary（@91）

| 函数/方法 | 作用 | 行号 |
|-----------|------|------|
| `_damage_str_to_dict` | 伤害字符串 → dict | 10 |
| `load_core` / `load_extension` / `_load_file` | 加载 | 97 / 104 / 107 |
| `get` / `list_all` / `search` / `__len__` | 查询族 | 114–132 |

### bosses.py (79 行) — BossLibrary（@48）

| 方法 | 作用 | 行号 |
|------|------|------|
| `_load` / `_load_extensions` | 加载 bosses.json + 扩展目录 | 57 / 66 |
| `get` / `list_names` / `__len__` | 查询族 | 72–78 |

### injector.py (101 行) — ContentInjector

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `offline_inject_scene` | `(scene_data, l3_scene_intent=None)` | 离线按 danger_level 预填 encounter/weapon | 34 |
| `offline_inject_module` | `(l2_data, l3_data)` | 全场景离线注入 | 52 |
| `runtime_spawn_enemy` | `(enemy_name, scene_name, world=None)` | 运行时敌人遭遇 dict | 64 |
| `runtime_grant_weapon` | `(weapon_name)` | 运行时武器 dict | 81 |
| `status` | property | 注入状态 | 95 |

### judgment.py (123 行) — JudgmentEngine（Tier2 桩）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `tier1_skill_check` | `(skill_value, difficulty="regular") -> Tier1Result` | D100 检定（桩） | 40 |
| `tier1_damage_roll` | `(damage_formula, db=0)` | 伤害掷骰 | 56 |
| `tier1_san_check` | `(san_loss)` | SAN 检定 | 86 |
| `build_tier2_context` | `(tier1, enemy, weapon, world)` | Tier2 上下文 | 106 |

---

## src/monitor/ — 管线监控（LLM 埋点 + 降级 + 回合冻结）

### sensor.py (95 行) — LLMSensor 零侵入埋点

| 类 | 说明 | 行号 |
|----|------|------|
| `LLMCallRecord` | dataclass：一次 LLM 调用记录（label/model/耗时/状态/长度/tokens） | 9 |
| `AgentStats` | 聚合统计；`update(records, slow_threshold_ms)` 计算失败率/慢调用率（最近 20 条） | 23 |
| `LLMSensor` | `record()`@51 记录；`get_records/get_stats`@65/70；`history`@77；`consecutive_failures`@81；`recent_slow_rate`@91 | 44 |

### agent_monitor.py (86 行) — AgentMonitor 每 agent 监控

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `DegradationPolicy` | Protocol：on_timeout / on_consecutive_failures / on_degrade | 13 |
| `AgentMonitor.call` | `(llm_fn, prompt, **kwargs)` 包装 LLM 调用：降级时跳过/换模型/调 thinking；记录成功失败；恢复计数 | 29 |
| `_maybe_trigger` | 连续失败 ≥ LLM_MAX_CONSECUTIVE_FAILURES 或慢调用率超阈值 → 置 degraded | 72 |
| `degraded` / `stats` | property | 81 / 85 |

### policies.py (42 行) — 各 Agent 降级策略

`_BasePolicy`（@5）从 `config.DEGRADE_POLICY[agent_key]` 读取配置；`KeeperPolicy`@20 / `NarratorPolicy`@25 / `AuthorPolicy`@30 / `TimeAgentPolicy`@35 / `IntentDetectorPolicy`@40。

### turn_monitor.py (141 行) — 回合状态机

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `StepResult` | dataclass：步骤状态/重试次数/耗时/错误 | 11 |
| `TurnFrozenError` | 关键段耗尽重试 → 回合冻结异常 | 19 |
| `TurnMonitor.begin_turn` | 开始回合，清空步骤 | 33 |
| `execute_step` | `(step, fn, *, is_critical=False, max_retries)` 执行单步；重试循环；关键步失败 → 冻结消息 + TurnFrozenError；非关键失败 → 返回 None | 38 |
| `execute_parallel` | `(steps)` 线程池并行执行，冻结异常优先抛出 | 82 |
| `snapshot` | `() -> dict` 汇总 LLM 调用统计（按 agent）+ 回合步骤状态 + 冻结信息（前端 /health 用） | 109 |

### health.py (36 行) — PipelineHealth（已弃用）

`snapshot()` 逻辑已并入 TurnMonitor.snapshot()；保留兼容旧 /health 调用（构造时 DeprecationWarning）。

---

## src/module_designer/ — 三层信息引擎（管线）

### __init__.py (33 行)

re-export：`SceneL1/SceneL2/L3Designer` 及 load/save、`validate_l1/l2/l3/validate_all/is_valid`、全部 `parse_step*`/`build_step*`、`DependencyGraph`、`run_pipeline/cross_validate_layers/PipelineResult/save_pipeline_result`。

### layered_schema.py (361 行) — Schema 定义 + 验证

| 项 | 说明 | 行号 |
|----|------|------|
| `L1_*` / `L2_*` / `L3_*` | 三层字段 schema 常量（required/values/list_of） | 10–182 |
| `SchemaViolation` / `SchemaReport` | 违规/报告（add/errors/warnings/is_valid/summary） | 183 / 194 |
| `_validate_value` / `_validate_object` | 递归校验 | 226 / 258 |
| `validate_l1` / `validate_l2` / `validate_l3` / `validate_all` / `is_valid` | 各层验证入口 | 267–358 |

### dependency_graph.py (138 行) — 依赖图

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `DependencyNode` / `DependencyEdge` | dataclass + 序列化 | 9 / 24 |
| `DependencyGraph.build` | `(dependencies)` 建图（ID 前缀 I/AT/E 推断类型） | 46 |
| `detect_cycles` | DFS 检测所有循环 | 70 |
| `cut_edge` / `cut_random_edge_in_cycles` | 切断循环边 | 102 / 108 |
| `to_dict` / `from_dict` | 序列化 | 123 / 132 |

### l1_player.py (98 行) — L1 玩家层模型

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `Perceptible`（可感知元素）/ `NPCAppearance` / `SceneL1` | dataclass + to_dict/from_dict | 8–51 |
| `load_l1` / `save_l1` | L1 JSON 读写 | 84 / 92 |

### l2_keeper.py (220 行) — L2 KP 层模型

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `Encounter` / `SceneWeapon` / `AutoTrigger` / `SceneL2` | dataclass + 序列化 | 12–121 |
| `_normalize_npc_profile` | NPC profile 字段归一化 | 162 |
| `load_l2` / `save_l2` | L2 JSON 读写 | 184 / 198 |

### l3_designer.py (245 行) — L3 设计层模型

`ModuleMeta`@8 `WorldRule`@32 `SceneIntent`@54 `EndingCondition`@77 `ToneConstraints`@95 `NarrativeLine`@118 `TimePressureConfig`@144 `CharacterDesign`@173 `L3Designer`@192（to_dict/from_dict）；`load_l3`@232 `save_l3`@240。

### layered_parser.py (1483 行) — 管线 LLM 解析（每步含 build_*_prompt + parse_*）

| 函数 | 作用 | 行号 |
|------|------|------|
| `load_json` / `_clean_json` / `_safe_parse_json` / `_is_valid_json_output` | JSON 工具 | 32–66 |
| `_join_chapters` / `_parse_condensed_chapters` | 章节合并/浓缩文本解析 | 77 / 87 |
| `_slim_entity` / `_merge_phase2_fields` | 实体精简 / Phase2 字段合并 | 105 / 117 |
| `_with_fallback` | `(parse_fn, required_keys, fallback_data, max_retries, verbose, step_name)` 带重试与保底 | 152 |
| `parse_step1a` | 模块元信息+场景+角色+Boss+敌人/武器约束 | 278 |
| `parse_step1b` | 精修浓缩模组文本 | 350 |
| `parse_step2a` | interactions + scene_movements | 471 |
| `parse_step2b_combined` | events + auto_triggers（合并） | 563 |
| `parse_step2c_l1` | L1 场景感知 | 631 |
| `parse_step2c_l3` | L3 设计层 | 696 |
| `parse_step25_combined` | NPC 档案 + entity 归属 + follow/interact 解锁（合并） | 834 |
| `parse_step2_boss` | Boss 遭遇实体 | 932 |
| `parse_step3a` | 去重 + 冲突解决 + 结局标记 | 1016 |
| `_step3b_deterministic` / `parse_step3b` | L1↔L2 交叉核对（确定性修复 + LLM 补 linked_interaction） | 1032 / 1150 |
| `parse_step35` | 依赖图提取 | 1269 |
| `parse_step4` | Phase2：@markup 标准化 | 1465 |

### layered_pipeline.py (924 行) — 管线编排

| 函数/类 | 作用 | 行号 |
|---------|------|------|
| `CrossRefIssue` / `CrossRefReport` | 交叉引用问题/报告 | 33 / 45 |
| `cross_validate_layers` | `(l1, l2, l3, weapon_lib, enemy_lib)` 跨层引用验证 | 96 |
| `_bind_npc_entities` | 扫描 entity NPC 归属 → 剥离+绑定 | 227 |
| `_extract_entity_bindings` | 从 npc_profiles 提取绑定 | 289 |
| `_inject_step1a_meta` | Step1a 角色 → NPC scene 注入 | 298 |
| `_inject_npc_special_entities` | 注入 follow_unlock + interact_unlock entity | 317 |
| `_assemble_l2` | 所有 entity 组装为 L2 JSON | 367 |
| `PipelineResult` | 结果容器（all_valid/summary） | 407 |
| `run_pipeline` | `(content, llm_json, llm_text=None, *, weapon_lib, enemy_lib, boss_lib, max_retries, verbose, inject_l3_wr0) -> PipelineResult` **4 步渐进管线主入口**：Step1→2a→2b+2c→3a∥2.5→3b→3.5/Phase1→Phase2→验证 | 439 |
| `save_pipeline_result` | `(result, module_dir)` 写 l1/l2/l3 JSON（l3 自动补 start_scene） | 890 |

### supplement_pipeline.py (515 行) — Author 触发的轻量补充管线

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_supplement_pipeline` | `(player_intent, reasoning, base_l3, entry_scene, exit_scene="", world_snapshot, output_dir, module_name, enemy_names)` | Step1 叙事规划（1 次 LLM）→ Step2 并行（2a entities / 2b L1 / 2c L3）→ 组装 L2 → 校验 → 写 `supplements/<ts>/l1/l2/l3_supp.json` | 155 |
| `_build_l3_context` | `(l3, current_scene)` | L3 → 自然语言摘要 | 250 |
| `_step_1_narrative` | `(player_intent, reasoning, base_l3, entry_scene, exit_scene, world_snapshot, enemy_names)` | 场景规划（SS1_/SS2_ 命名） | 300 |
| `_step_2a_entities` / `_step_2b_l1` / `_step_2c_l3` | — | 并行生成 | 375 / 404 / 419 |
| `_assemble_l2` | `(entities_data, scene_names)` | 补充 L2 组装 | 438 |
| `_validate_supplement` | `(l2, l1, scene_names)` | 补充内容校验 | 458 |

系统提示常量：`SUPP_STEP1_SYSTEM`@27 / `SUPP_STEP2A_SYSTEM`@55 / `SUPP_STEP2B_SYSTEM`@110 / `SUPP_STEP2C_SYSTEM`@134。

---

## src/llm.py (514 行) — LLM 封装

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_init_sensor` | `()` | 延迟初始化 LLMSensor（避免 config 循环 import） | 48 |
| `set_llm_log_dir` / `set_log_label` | — | 响应日志目录/当前 label | 62 / 70 |
| `_log_response` | `(content, label=None)` | 响应写入 `<label>.txt` | 76 |
| `_extract_json` | `(content) -> str` | markdown 块/花括号定位提取 JSON | 93 |
| `call_deepseek` | `(prompt, *, json_mode=True, system=None, model=None, thinking=None, reasoning_effort=None, temperature=None, max_tokens=None, max_retries=3, fallback_schema=None, timeout=300.0, _label=None) -> dict\|str` | **统一 LLM 入口**：JSON 模式（重试+温度递减+fallback 兜底）/文本模式；内嵌传感器埋点；`_label` 规避并行日志竞态 | 123 |
| `get_sensor` | `()` | 获取传感器 | 268 |
| `evaluate_trait_enhancement` | `(inv_desc, skill_name, skill_detail, dice_roll, skill_value, entity_name, graded_tiers, search_context, player_input) -> dict` | 特质修正 sub-agent（虚拟骰子 ±20 逻辑；大成功/大失败保护；最多 1 级偏移校验） | 272 |
| `evaluate_failure_penalty` | `(inv_desc, entity_name, skill_name, skill_detail, failure_tier, scene_context, graded_on_failure, retry_count) -> dict` | 失败惩罚 sub-agent（重试越多后果越重，可带 @markup_effects） | 421 |
| `evaluate_combat_round_narrative` | `(round_log, enemies_desc, player_name, scene)` | 战斗叙事（走 build_combat_narrative_prompt） | 502 |

## src/prompts.py (1137 行) — Prompt 构建（所有 build_* 只构建不调用）

| 函数 | 签名/作用 | 行号 |
|------|-----------|------|
| `set_current_round` / `set_prompt_log_dir` / `_sanitize_label` / `_show_prompt` / `log_skill_result` | 日志设施 | 29–69 |
| `apply_trait_enhancement` | `(player, skill_name, skill_detail, entity_name, search_context, player_input, graded_tiers) -> (new_tier, enhancement)` judge/search/standoff 三处复用 | 90 |
| `_build_scene_context` / `_build_investigator_info` / `_build_player_state` / `_build_scene_state` / `_build_time_block` / `_build_world_state` / `_build_l1l3_context` | 确定性场景上下文构建 | 127–205 |
| `parse_narrative_output` | Narrator 输出解析 | 263 |
| `_build_entity_lines` | 场景实体 → prompt 行（`_split_req`@312 / `_fmt_inter`@332 / `_fmt_at`@341 / `_parse_req`@376 / `_split_req_str`@390 辅助） | 297 |
| `build_keeper_parse_prompt` | `(world, user_input)` Keeper Step1 实体匹配 | 465 |
| `build_keeper_enrich_prompt` | `(world, judged_entities, user_input)` Step3 叙事整合 | 552 |
| `build_narrator_prompt` | `(brief, l1_scene, snap, user_input)` 沉浸式叙事 | 601 |
| `build_pre_parse_prompt` | `(player_text, ambiguity_context, world_brief)` 消歧 | 661 |
| `build_author_prompt` | `(request, l3_data, persona)` patch/structural 判定（prompt 含【世界编年史】块） | 741 |
| `build_combat_entry_prompt` | 战斗入口判定 | 919 |
| `build_standoff_match_prompt` | 对峙技能匹配 | 944 |
| `build_combat_narrative_prompt` | 战斗叙事 | 967 |
| `build_stat_narrative_prompt` | 属性变化 → 个人描述增量更新 | 993 |
| `build_consume_item_fuzzy_prompt` | 物品名模糊匹配 | 1012 |
| `build_time_pressure_assess_prompt` | 时间压力介入判定 | 1036 |
| `build_npc_intent_detect_prompt` | 是否在和 NPC 对话 | 1078 |
| `build_npc_parse_prompt` | NPC 互动解析 | 1099 |

## src/llm_player.py (382 行) — LLM 自动玩家（模组自动化测试）

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `load_profile` | `(path) -> dict` | 加载测试 profile JSON | 26 |
| `build_player_prompt` | `(world, narrative_result, short_history, long_memory, profile, player_snapshot) -> (system, user)` | 构建玩家 prompt（快照/时间/背包/NPC/出口/敌人 + 4 种测试模式段落） | 31 |
| `compress_memory` | `(short_history) -> str` | LLM 压缩短期记忆 | 101 |
| `_eval_success_checks` | `(names, entries) -> bool` | 按 tests/e2e/scenario_predicates.py 谓词注册表评估是否全部满足 | 115 |
| `run_llm_player` | `(profile_path, module_name, max_turns, max_duration_s, post_init_hook, log_dir) -> {log_dir, summary, goal_achieved}` | **主循环**：init_game → 玩家 prompt → call_deepseek → run_turn → 摘要日志 `_summary.json` → 结局/目标提前终止 → 定期记忆压缩 | 135 |
| `_log_player_call` | `(turn, system_prompt, user_prompt, response)` | 玩家 LLM 交互全文写入 `player_llm.txt` | 206 |

## src/llm_player_prompts.py (81 行)

prompt 常量：`PLAYER_SYSTEM`@3 / `TEST_MODE_STRESS`@13 / `TEST_MODE_EXPLORATION`@23 / `TEST_MODE_ROLEPLAY`@31 / `TEST_MODE_GOAL`@40 / `MEMORY_COMPRESS_SYSTEM`+`MEMORY_COMPRESS_TEMPLATE` / `TEST_MODE_CUSTOM` 等。

## src/config.py (154 行) — 配置常量

| 常量 | 说明 |
|------|------|
| `WR0_ENABLED` / `SHOW_NON_TRIGGERABLE` / `SHOW_COMPLETED` | 创作者豁免 / Parse 展示控制 |
| `COMBAT_LLM_ENHANCEMENT` | 战斗 LLM 增强开关 |
| `LLM_TIMEOUT_MS` / `LLM_SLOW_THRESHOLD_MS` / `LLM_SLOW_RATE_THRESHOLD` / `LLM_MAX_CONSECUTIVE_FAILURES` / `LLM_DEGRADE_RECOVERY_COUNT` | 监控/降级参数 |
| `MONITOR_ENABLED` / `MONITOR_HISTORY_SIZE` | 传感器开关 |
| `MAX_ESCALATION_DEPTH` / `INTENT_COOLDOWN_WINDOW` / `COMMS_INTERVAL_MINUTES` / `NPC_MEMORY_CAP` | 回合控制 |
| `PIPELINE_MAX_RETRIES` / `INJECT_L3_WR0` / `TURN_STEP_MAX_RETRIES` | 管线/回合监控 |
| `DEGRADE_POLICY` | 各 Agent 降级策略 dict（keeper/narrator/author/time_agent/intent_detector） |
| `AGENT_SYSTEM_PROMPTS` | 12 个 Agent system prompt 覆盖 |
| `AUTOSAVE_ENABLED` / `AUTOSAVE_INTERVAL_SEC` / `AUTOSAVE_MAX_COPIES` / `AUTOSAVE_DIR` | 自动存档 |
| `OFFLINE_INJECTION_ENABLED` / `RUNTIME_INJECTION_ENABLED` | 注入开关 |

## src/config_llm.py (76 行) — LLM 后端配置（git 忽略；模板见 config_llm.template.py）

| 常量 | 说明 |
|------|------|
| `LLM_BASE_URL` / `LLM_API_KEY_ENV` | API 端点 / Key 环境变量名 |
| `LLM_DEFAULT_MODEL` / `LLM_FLASH_MODEL` | 主模型 / 轻量模型 |
| `LLM_THINKING_ENABLED` / `LLM_REASONING_EFFORT` / `LLM_TEMPERATURE_JSON` / `LLM_TEMPERATURE_TEXT` / `LLM_MAX_TOKENS_JSON` / `LLM_MAX_TOKENS_TEXT` | 默认生成参数 |
| `RE_*` | 各调用点 reasoning_effort 覆盖（RE_KEEPER_PARSE="max" 等） |

## src/utils.py (161 行) — 通用工具

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `parser` | `(file_path) -> str` | .docx/.pdf 解析入口（.doc 报错引导另存） | 11 |
| `_parse_docx` / `_parse_pdf` | — | python-docx / PyPDF2 解析 | 30 / 41 |
| `estimate_tokens` | `(text) -> int` | 中文≈1.5 token/字，英文≈0.25/字符 | 68 |
| `estimate_and_truncate_context` | `(content, extra_prompt_chars, max_tokens, safety_margin) -> str` | 超限截断（找段落/句号断点） | 78 |
| `roll_dice` / `roll_d6` | — | 掷骰 | 125 / 135 |
| `load_skill_checks` | `(path=None)` | data/skill_checks.json | 142 |
| `get_coc_skill_names` | `() -> list[str]` | COC 7th 技能名（缓存） | 156 |

## src/audit_player_log.py (411 行) — LLM 玩家日志审计

| 函数 | 作用 | 行号 |
|------|------|------|
| `load_summary` | 读 `_summary.json` | 12 |
| `_llm_audit` | LLM 分析玩家日志（叙事质量/检定/NPC/时间/连贯性）→ findings 表 | 18 |
| `audit` | `(log_dir) -> str` 主入口：确定性异常统计 + LLM 审计 + Markdown 报告 | 145 |
| `_audit_npc` / `_audit_enemy` / `_audit_combat` / `_audit_boss` / `_audit_time` / `_audit_author` / `_audit_side_effects` / `_audit_memory` | 各维度确定性异常扫描 | 304–396 |

---

## frontend/ — FastAPI 前端

### server.py (133 行) — 服务入口

| 项 | 说明 | 行号 |
|----|------|------|
| `app` | FastAPI("TRPG Assistant") + CORS + `/static` 挂载 + Jinja2 templates | 37–53 |
| 6 个 router include | files/launcher/character/game/editor/assets | 56–67 |
| `health` | `GET /health` | 70 |
| `_open_app_window` | pywebview 或 Edge/Chrome app 模式打开窗口 | 75 |
| `start_server`（main） | uvicorn 线程 + 自动开窗 | 125 |

启动时若 `src/config_llm.py` 缺失则自动从模板复制（@29）。

### _paths.py (19 行)

集中路径解析：`IS_FROZEN`（PyInstaller `sys._MEIPASS` / Nuitka `.dist` 后缀检测）、`PROJECT_ROOT`、`FRONTEND_DIR`。

### routers/launcher.py (238 行) — 启动页 API

| 端点 | 路由 | 行号 |
|------|------|------|
| `launcher_page` / `launcher_tab` | `GET /` / `GET /launcher/tabs/{tab}` | 46 / 54 |
| `save_config` / `load_config` | `POST/GET /api/config/save\|load`（模型/温度/超时/战斗增强等） | 70 / 95 |
| `start_step0` | `POST /api/step0/start` → run_step0 子进程 | 100 |
| `start_pipeline` | `POST /api/pipeline/start` → run_pipeline 子进程 | 140 |
| `validate_pipeline` | `POST /api/pipeline/validate` | 188 |

### routers/game.py (1139 行) — 游戏 API（核心）

| 端点 | 路由 | 作用 | 行号 |
|------|------|------|------|
| `game_page` | `GET /game` | 游戏页 | 168 |
| `_handle_slash_command` | — | 斜杠命令短路 | 172 |
| `process_turn` | `POST /api/game/turn` | 回合入口（线程池，防止阻塞事件循环） | 253 |
| `character_card` | `GET /api/game/character-card` | 角色卡 HTML | 504 |
| `player_status` | `GET /api/game/player-status?format=` | HP/SAN 状态 | 648 |
| `game_command` | `POST /api/game/command` | 命令 | 676 |
| `scene_info` | `GET /api/game/scene` | 场景 HTML | 681 |
| `game_progress` | `WS /api/game/progress` | 管线进度推送 | 698 |
| `init_game_api` | `POST /api/game/init` | 初始化 + 首回合 | 730 |
| `game_state` | `GET /api/game/state` | 游戏状态 JSON | 818 |
| `set_auto_win` | `POST /api/game/auto-win` | 战斗自动胜利开关 | 832 |
| `combat_start` | `POST /api/combat/start` | 初始化战斗会话 | 843 |
| `combat_round` | `POST /api/combat/round` | 执行一轮 | 952 |

序列化辅助：`_serialize_enemies_for_frontend`@34 / `_serialize_combat_state_for_frontend`@57 / `_deserialize_enemies_for_combat`@70 / `_init_libraries`@104 / `_resolve_start_scene`@1086 / `_make_default_inv`@1132。

### routers/character.py (335 行) — 车卡 API

`character_page`@68 / `upload_avatar`@78 / `step_partial`@91 / `roll_stats`@106 / `skills_list`@144 / `generate_description`@212（LLM 外貌）/ `_build_export`@229 / `export_character_get`@300 / `export_character`@319（ZIP 导出）；辅助 `_load_occupations`@56 / `_roll_stat`@63。

### routers/editor.py (116 行) — JSON 编辑器

`editor_page`@21 / `load_json`@26 / `_render_tree`@37 / `save_json`@71 / `validate_json`@88 / `_type_label`@105。

### routers/files.py (60 行) — 文件浏览

`_safe_dir`@20（目录穿越防护）/ `list_files`@30（html/json 两种格式）。

### routers/assets.py (79 行) — 素材

`list_assets`@27 / `random_asset`@52。

---

## scripts/ 与 tools/

### scripts/extract_library.py (247 行) — 从文本提取敌人/Boss/武器入库

`_load_templates`@27 / `_template_to_example`@32 / `_load_existing`@38（去重）/ `_extract_via_llm`@64 / `_dedup`@113 / `_show_item`@125 / `_write_enemies/_write_bosses/_write_weapons`@147–166 / `main`@175（LLM 提取 → 去重 → 确认 → 写 JSON）。

### scripts/probe_nuitka.py (18 行)

Nuitka 打包环境探测（无函数定义）。

### tools/run_layered_parser.py (88 行)

对「常暗之厢」文档跑 parse_module + save_module + validate_all + run_pipeline 的调试脚本；`llm_parse`@31。

### tools/create_layered_notebook.py (198 行)

生成分层解析器 Jupyter notebook（无函数定义，顶层脚本）。
