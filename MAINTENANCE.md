# Architecture Maintenance Doc — COC Simulator

> 记录所有模块的函数级信息：函数作用、参数签名、上下游调用关系。
> 每次较大修改后即时更新。替代旧 cookbook.md。

---

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-06-10 | 初稿：全量 scan 项目代码，函数级归档。新增 parse shortcut dispatch。 |

---

## src/game/messages.py (>220 行) — 消息类型

| 类 | 签名/字段 | 作用 | 上游调用者 | 下游调用 | 行号 |
|----|-----------|------|-----------|---------|------|
| `IntentResult` | `needs_author: bool`, `intent: str=""`, `reasoning: str=""` | Detector 输出：other 输入是否有叙事意图 | `IntentDetector.detect()` | `Keeper._maybe_escalate_to_author()` | 8 |
| `AuthorRequest` | `other_texts: list=[], intent: str="", reasoning: str="", scene_context: dict={}` | Detector→Author 请求 | `Keeper.process_turn()` | `Author.handle_request()` | 12 |
| `ActionIntent` | `action: str`, `target: str=""` | Parse 解析出的玩家意图 | `keeper.py` 多处构造 | `Judge._execute_entity()` | 25 |
| `ActionOutcome` | `intent: ActionIntent`, `success: bool`, `message: str`, `entity_id: str=""`, `entity_type: str=""`, `side_effects: list=[], skill_tier: str="", skill_detail: str="", enhancement: dict\|None=None` | 单个 entity 执行结果 | `Judge._execute_entity()` | `Curator.assemble()` | 30 |
| `SceneSnapshot` | `location: str`, `description: str`, `exits: list[dict]`, `perceptible_interactions: list[str]`, `visible_npcs: list[dict]` | 场景信息快照 | `Curator._build_snapshot()` | `NarratorBrief` | 46 |
| `NarratorBrief` | `action_outcomes: list[ActionOutcome]`, `ambient_changes: list[str]`, `scene_snapshot: SceneSnapshot`, `suggested_emphasis: str` | KP→Narrator 策展结果 | `Curator.assemble()` | `Narrator.narrate()` | 55 |
| `ModulePatch` | `entities: list[dict]`, `scene_descriptions: dict`, `justification: str=""` | Author→Keeper entity 补丁 | `Author.handle_request()` | `Keeper._integrate_patch()` | 64 |
| `StructuralEdit` | `supplement_path: str=""`, `l3_updates: dict={}`, `entry_scene: str=""`, `exit_scene: str=""`, `justification: str=""` | Author→Keeper 结构扩展 | `Author.handle_request()` | `Keeper._integrate_supplement()` | 72 |
| `@dataclass TurnInput` | `raw_text: str=""`, `player: Any\|None=None`, `action_type: str=""`, `action_target: str=""` | 回合入口数据。`action_type` 非空 → 跳过 LLM parse | `game_loop.py:run_turn()` | `Keeper.process_turn()` | 89 |
| `CombatEntryCheck` | `enter_combat: bool`, `enemy_instance_ids: list=[], reasoning: str=""` | LLM 判定是否进入战斗 | `keeper.py` 构造 | `process_turn` 分流 | 95 |
| `StandoffMatch` | `matched: bool`, `skill_name: str=""`, `reason: str=""` | 对峙语义匹配结果 | `keeper.py` 内部 | — | 101 |
| `CombatInit` | `enemies: list=[], player: Any=None, scene: str="", initiative_context: str="", environment_actions: list=[], player_action: str="", player_targets: list=[], player_extra: str=""` | →CombatSystem 初始化数据 | `keeper.py`, `game_loop.py`, `frontend` | `CombatSystem.run_combat()` | 107 |
| `CombatResult` | `outcome: str="", defeated_instance_ids: list=[], narrative: str="", player_hp: int=0, player_san: int=0, rounds: int=0, round_log: list=[]` | CombatSystem→外部 战斗结果 | `CombatSystem.run_combat()` | `game_loop.py`, `frontend` | 120 |
| `SkillCheckResult` | `entity_id: str="", entity_type: str="", skill_name: str="", raw_roll: int=0, target: int=0, tier: str="", success: bool=False, enhancement: dict\|None=None` | 单次技能检定记录 | `game_loop.py` 构造 | `PlayerFacingSnapshot` | 132 |
| `PlayerFacingSnapshot` | `scene_name: str="", scene_description: str="", exits: list=[], time: dict={}, npcs: list=[], enemies: list=[], combat: dict\|None=None, skill_checks: list=[], investigator: Any=None` | 面向前端/CLI 的回合快照 | `game_loop.py:run_turn()` L493 | `frontend/routers/game.py`, `format_turn_dynamic()` | 143 |
| `RoundResult` | `round: int=0`, `player_action: str=""`, `player_target: str=""`, `player_roll: int=0`, `player_tier: str=""`, `player_damage: int=0`, `player_damage_type: str="物理"`, `player_effects: list=[], enemy_actions: list=[], status_changes: list=[], narrative: str=""` | 单回合战斗结果 | CombatSystem 内部 | `CombatResult.round_log` | 157 |
| `Phase` | `trigger: str=""`, `name: str=""`, `overrides: dict={}`, `description: str=""` | Boss 阶段定义 | Boss 战斗系统 | — | 169 |
| `TimeCommsPacket` | `game_time: int=0`, `day: int=0`, `time_of_day: str=""`, `current_scene: str=""`, `player_actions: str=""`, `world_state: str=""` | Keeper→Author 时间通信包 | `keeper.py` L729 构造 | `Author.assess_time_pressure()` | 177 |
| `PreParseResult` | `clarity: str=""`, `interpretation: str=""`, `question: str=""`, `resolved_text: str=""` | Pre-parse 消歧输出 | `PreParseDisambiguator.disambiguate()` | `Keeper.process_turn()` | 185 |
| `EnrichInput` | `entities: list[dict]=[]`, `actions: list[dict]=[]` | parse→enrich 中间体 | `keeper.py` 构造 | enrich step, TimeAgent | 192 |

---

## src/scenario_core.py (>1470 行) — 数据模型 + 世界状态

### 数据类

| 类 | 字段 | 作用 | 行号 |
|----|------|------|------|
| `Entity` | `id, entity_type, name, scene, type, requirement, trigger, result, side_effects, graded_result, difficulty, extra, time_condition` | 统一实体（interaction/auto_trigger/event） | 89 |
| `Entity.from_dict` | `(cls, data: dict, overrides=None) -> Entity` | 统一工厂，从 dict 构造 Entity | 109 |
| `Node` | `node_id, description, edges, to_here, interactions, auto_triggers, encounters, scene_weapons, extra` | 场景节点 | 253 |
| `Edge` | `target, method, requirement` | 场景通行边 | 39 |
| `NodeRuntimeState` | `completed: bool=False, result_tier: str="", retries: int=0, escalated_difficulty: str=""` | 实体运行时状态 | 278 |

### DirectedGraph

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, scenes=None, events=None)` | 初始化图 | 293 |
| `load_scenes` | `(self, data: dict)` | 从 dict 加载场景节点 | 307 |
| `load_events` | `(self, data: list)` | 从 list 加载全局事件 | 347 |
| `get_edges_from` | `(self, node_id: str) -> List[Edge]` | 查询出边 | 356 |
| `get_event` | `(self, event_id: str) -> Optional[Entity]` | 按 ID 查事件 | 366 |
| `to_dict` / `from_dict` | — | 序列化 | 399/450 |

### ScenarioWorld

| 方法 | 签名 | 作用 | 上游 | 下游 | 行号 |
|------|------|------|------|------|------|
| `__init__` | `(self, graph, start_node, ...)` | 初始化世界 + 所有子系统 (Clock/EnemyManager/NPCManager/BossManager/MemoryManager) | `init_game()` | 所有子系统 init | 663 |
| `advance_time` | `(self, minutes: int)` | 推进时间并注入时间标记 | Keeper | `clock.advance_time`, `get_time_flags` | 744 |
| `load_dependency_graph` | `(self, dep_graph: dict)` | 加载 L2 依赖图 | `init_game()` | `_register_boss_nodes` | 765 |
| `get_runtime_state` | `(self, entity_id: str) -> NodeRuntimeState` | 获取/创建实体运行时状态 | 多处 | — | 794 |
| `is_entity_completed` | `(self, entity_id: str) -> bool` | 检查实体是否已完成 | `_build_entity_lines`, `_inject_npc_at` | `runtime_state` | 832 |
| `mark_completed` | `(self, entity_id, tier="")` | 标记实体已完成 | Keeper | `get_runtime_state` | 825 |
| `get_possible_exits` | `(self) -> List[Edge]` | 获取当前节点出边 | `Keeper dispatcher`, `move`, `run_turn` | `graph.get_edges_from` | 865 |
| `move` | `(self, target: str) -> ActionResult` | 移动到目标场景 | Keeper | `npcs.sync_followers` | 969 |
| `build_snapshot` | `(self) -> dict` | 构建单源快照供所有 prompt builder | Keeper, `run_turn`, prompts | `player.build_snapshot`, `npcs.get_in_scene_snapshot` 等 | 1006 |
| `to_dict` / `from_dict` | — | 序列化世界状态 | `save_state` / `load_state` | 子系统序列化 | 1055/1095 |
| `save_state` | `(self, path: str)` | 全量快照存档 | `save_game` | `graph.to_dict`, `to_dict` | 1126 |
| `load_state` | `(cls, path: str) -> ScenarioWorld` | 从存档恢复 | `load_game` | `DirectedGraph.from_dict`, 各子系统 `from_dict` | 1145 |

### 顶层函数

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `find_entity_by_id` | `(world: ScenarioWorld, entity_id: str)` | 在场景+事件+NPC 中联合查找实体 | 77 |
| `resolve_graded_result` | `(entity: Entity, tier: str) -> str` | 解析 `##GRADED##` 结果 | 138 |
| `has_ending` | `(text: str) -> tuple[str\|None, str\|None]` | 检测 `##END_*:desc##` 结局标记 | 162 |
| `check_time_condition` | `(time_condition: str, day: int, time_of_day: str) -> bool` | 检查时间条件 | 173 |
| `parse_hard_requirement` | `(hard: str, runtime_state: dict) -> bool` | 解析 AND/OR 条件表达式 | 563 |
| `apply_side_effects` | `(world, side_effects: list, **kwargs) -> list` | 应用副作用实例到世界 | 1212 |

### MemoryManager

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `add_record` | `(self, user_input, action, target, result, location, success)` | 添加交互记录 | 1373 |
| `compress` | `(self, llm_call)` | LLM 压缩旧记录为摘要 | 1399 |
| `get_context` | `(self) -> str` | 构建完整上下文 | 1433 |

---

## src/game_loop.py (768 行) — 游戏主循环

| 函数 | 签名 | 作用 | 上游 | 下游 | 行号 |
|------|------|------|------|------|------|
| `init_game` | `(l2_path, l1_path, l3_path, start_node="6号车厢", wr0_enabled=WR0_ENABLED) -> dict` | 从 JSON 初始化所有 agent + world + 库 | main entry, frontend | `DirectedGraph`, `ScenarioWorld`, `EnemyLibrary`, `WeaponLibrary`, `BossLibrary`, `Narrator`, `Keeper`, `Author` | 148 |
| `run_turn` | `(game, user_input, weapon_lib=None, enemy_lib=None, injector=None, action_type="", action_target="") -> dict` | 执行一回合：debug 命令 → Keeper.process_turn → Narrator.narrate | main loop, frontend | `Keeper.process_turn`, `Narrator.narrate`, `TurnLogger.log` | 297 |
| `continue_standoff` | `(keeper, player_input) -> dict` | 处理对峙回避尝试 | main loop | `Keeper.resolve_standoff`, `CombatSystem.run_combat` | 614 |
| `save_game` | `(game, path)` | 保存游戏 | autosave, CLI | `world.save_state` | 535 |
| `load_game` | `(game, path)` | 加载存档 | CLI | `ScenarioWorld.load_state` | 551 |
| `format_turn_dynamic` | `(player_snapshot, brief, narrative) -> str` | 快照+叙事 → 纯文本（时间/战斗/技能检定） | CLI, frontend | — | 692 |

---

## src/game/agents/keeper.py (>1470 行) — Keeper 回合编配

### 公共方法

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `process_turn` | `(self, turn_input: TurnInput, author: Any=None, _depth: int=0) -> dict` | **主流程**：pre-parse shortcut dispatch → parse → judge → enrich/combat/TimeAgent → Author → curate → memory | 133 |
| `complete_combat_turn` | `(self, original_input, combat_result: dict) -> dict` | 战斗后回放 enrich→curate | 916 |
| `resolve_standoff` | `(self, standoff_state: dict, player_input: str) -> dict` | 对峙：LLM 匹配技能 → D100 → 特质修正 | 956 |

### 关键内部方法

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_parse` | `(self, raw: str) -> list[dict]` | LLM parse：玩家输入 → action 列表 | 1158 |
| `_enrich` | `(self, judged_entities, user_input) -> dict` | LLM enrich：合并判定结果 | 1191 |
| `_inject_npc_at` | `(self)` | 当前场景 NPC bound entity → 注入 node | 1083 |
| `_apply_pending` | `(self)` | 应用延迟副作用 + 移动 + NPC 跟随实体 | 1122 |
| `_find_entity_by_id` | `(self, entity_id)` | graph+NPC+boss 按 ID 查找实体 | 1234 |
| `_run_time_agent` | `(self, action_summaries, raw) -> dict` | 调用 TimeAgent 评估时间 | 1326 |
| `_integrate_supplement` | `(self, structural_edit, author)` | 补充管线 → 集成到 graph | 1349 |
| `_integrate_patch` | `(self, patch)` | ModulePatch 实体集成 | 1480 |

---

## src/game/agents/narrator.py (~90 行)

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, l1_data: dict)` | 初始化（持有 L1 数据） | 17 |
| `narrate` | `(self, brief: NarratorBrief, snap=None, user_input="") -> tuple[str, str, str]` | KP 简报 → 沉浸式叙事，返回 (brief, narrative, scene_update) | 24 |

---

## src/game/agents/author.py (~140 行)

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, l3_data, persona="")` | 初始化（持有 L3 数据） | 29 |
| `handle_request` | `(self, request: AuthorRequest, turn_number=0) -> ModulePatch\|StructuralEdit` | 两级响应：Patch / StructuralEdit | 43 |
| `assess_time_pressure` | `(self, comms_packet) -> dict` | 评估时间压力 | 99 |

---

## src/game/agents/time_agent.py (~75 行)

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `assess` | `(self, actions=None, current_input="", time_costs=None) -> dict{time_delta, narrative_hint}` | LLM 评估本轮时间消耗 | 64 |
| `build_prompt` | `(self, actions, current_input, time_costs=None) -> str` | 构建时间评估 prompt | 29 |

---

## src/game/clock.py (~60 行) — 游戏时钟

| 方法/属性 | 签名 | 作用 | 行号 |
|-----------|------|------|------|
| `game_time` | `int` (属性) | 累计游戏分钟数 | — |
| `day` | `property -> int` | `game_time // 1440` | — |
| `time_of_day` | `property -> str` | 5 段（夜间/早晨/白天/黄昏/夜间） | — |
| `advance_time` | `(minutes: int)` | 推进时钟 | — |
| `get_time_flags` | `() -> dict` | `{day:N: True, time:period: True}` | — |
| `to_dict` | `() -> dict` | `{game_time, time_context}` | — |

---

## src/game/judge.py (~360 行) — 确定性闸门

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, world: ScenarioWorld)` | 初始化 | 30 |
| `check_auto_triggers` | `(self) -> list[ActionOutcome]` | 触发当前场景所有满足条件的 AT | — |
| `_execute_entity` | `(self, entity, intent, player_input="") -> ActionOutcome` | **核心**：requirement → D100 → trait enhancement → graded → failure penalty → side effects | — |

---

## src/game/curator.py (~66 行) — 策展器

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `assemble` | `(self, outcomes, ambient_changes, emphasis="") -> NarratorBrief` | outcomes + 场景快照 → NarratorBrief | — |
| `_build_snapshot` | `(self) -> SceneSnapshot` | 收集当前场景元数据 | — |

---

## src/game/side_effects.py (~150 行) — @markup 解析

| 函数/dataclass | 作用 |
|----------------|------|
| `SpawnEnemy` | `@spawn_enemy(enemy_ref, scene, quantity)` → `EnemyManager.spawn()` |
| `GrantWeapon` | `@grant_weapon(weapon_ref, scene, quantity)` → 场景武器放置 |
| `StatChange` | `@stat_change(stat_name, delta)` → `Investigator.modify_stat()` |
| `ItemGain` | `@item_gain(item_name, quantity)` → `ItemManager.add()` |
| `ConsumeItem` | `@consume_item(item_name, quantity)` → `ItemManager.remove()` |
| `NPCStateChange` | `@npc_state_change(npc_name, new_state)` → `NPCManager.set_state()` |
| `NPCFollow` | `@npc_follow(npc_name, follow)` → `NPCManager.set_following()` |
| `SceneWeapon` | 场景武器追踪 dataclass |
| `parse_markup_all` | `(text: str) -> list` | 解析所有 @markup → dataclass 列表 |

---

## src/game/combat.py (>1250 行) — 战斗系统 v2

### CombinatSystem 公共方法

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, weapon_lib=None, llm_enhancement=COMBAT_LLM_ENHANCEMENT)` | 初始化 | 162 |
| `run_combat` | `(self, combat_init: CombatInit, player_action="", max_rounds=20) -> CombatResult` | **主入口**：完整战斗循环。≤5 enemies，确定性→LLM 修正→结算 | 168 |
| `run_single_round` | `(self, combat_init, state, action_id, target_ids, player_extra="") -> dict` | 交互式单回合（前端回合制） | 362 |

### 关键内部方法

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_init_combat` | `(self, combat_init) -> CombatState` | 初始化：展开 quantity 群组，按 DEX 排先攻 | 657 |
| `_get_player_actions` | `(self, player, environment_actions=None) -> list[dict]` | 构建固定动作列表（拳/踢/回避/逃跑/武器/环境） | 737 |
| `_get_tier` | `(self, roll, skill_value) -> str` | COC 四级检定（extreme/hard/regular/failure） | 907 |
| `_roll_damage` | `(damage_spec, STR=50, SIZ=50) -> int` | 从 dict/legacy 公式掷伤害骰 | 15 (模块函数) |
| `_resolve_player_action` | `(self, state, player, action_id, target_iid, ...) -> CombatAction` | 执行玩家动作 | 788 |
| `_resolve_enemy_action` | `(self, state, enemy, player) -> CombatAction` | 执行敌人动作 | 931 |
| `_select_enemy_attack` | `(self, enemy) -> dict` | 按权重随机选攻击 | 919 |
| `_llm_correct_round` | `(self, round_result, ...) -> dict` | LLM 修正玩家回合伤害 | 1080 |
| `_llm_correct_enemy_round` | `(self, enemy, action_data, ...) -> dict` | LLM 修正敌人攻击伤害 | 1187 |
| `_check_phase` / `_apply_phase` | — | Boss 阶段切换 | 978/1002 |

---

## src/game/npc_manager.py (~411 行) — NPC 管理

### NPC dataclass 字段

`name, role, personality_notes, appearance, what_they_can_do, interaction_triggers, can_follow, follow_requirements, can_interact, interact_requirements, bound_interactions, bound_auto_triggers, scene, attitude, following, memory, state, extra`

### NPCManager

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `init_from_profiles` | `(self, profiles: dict)` | 从 L2 npc_profiles 批量初始化 | 131 |
| `get` | `(self, name: str) -> NPC\|None` | 按名查询 | 155 |
| `get_in_scene` | `(self, scene: str) -> list[NPC]` | 场景内 NPC（排除 dead/left） | 158 |
| `get_in_scene_snapshot` | `(self, scene: str) -> list[dict]` | 场景 NPC 轻量快照 | 162 |
| `talk_to` | `(self, npc_name, player_input, llm_call, world=None) -> str` | state gate → can_interact gate → interact_requirements gate → LLM 对话 | 175 |
| `_check_follow_conditions` | `(self, npc, world) -> tuple[bool, str]` | 跟随条件检查（can_follow → state → follow_requirements） | 94 |
| `set_following` | `(self, name, following: bool)` | 跟随切换 | 248 |
| `sync_followers` | `(self, scene: str)` | 跟随 NPC 同步到新场景 | 265 |
| `process_npc_turn` | `(self, npc_name, user_input, world, llm_json, llm_text, judge, curator) -> dict` | **独立 API**：自含 talk_to→parse→judge→enrich→curate。主循环不调用 | 315 |
| `to_dict` / `from_dict` | — | 序列化 | 273/289 |

---

## src/game/enemy_manager.py (~270 行) — 敌人管理

### EnemyInstance 字段

`instance_id, enemy_ref, scene, quantity, status, flags, combat_behavior, description, attributes, armor, attacks, special_abilities, san_loss, hp, boss_mechanics, multi_attack, damage_multipliers, dodge_bonus, special_rules, phases, _current_phase`

### EnemyManager

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `spawn` | `(self, enemy_ref, scene, quantity=1) -> EnemyInstance` | 从库实例化（同场景同类合并） | 47 |
| `get_active_in_scene` | `(self, scene) -> list[EnemyInstance]` | 场景内存活敌人 | 93 |
| `get_active_in_range` | `(self, scene, graph) -> list[EnemyInstance]` | 当前+相邻场景（adjacent_aware） | 99 |
| `get_active_in_scene_snapshot` | `(self, scene) -> list[dict]` | 轻量快照 | 117 |
| `group_by_ref` | `(self, scene) -> dict` | 同场景按 enemy_ref 分组 | 130 |
| `get_by_id` | `(self, instance_id) -> EnemyInstance\|None` | 按 ID 查找 | 157 |
| `enter_combat` | `(self, instance_ids: list)` | 批量标记 engaged | 160 |
| `exit_combat` | `(self, result: dict)` | win→defeated, 非 win→hostile | 167 |
| `get_combat_context` | `(self, scene, graph=None) -> str\|None` | 构建战斗判定用文本 | 182 |
| `to_dict` / `from_dict` | — | 序列化 | 198/223 |

---

## src/game/boss_manager.py (~125 行) — Boss 管理

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `has_spawned` / `mark_spawned` | `(self, boss_id) -> bool / None` | 防重复生成 | 13/16 |
| `check_by_engage_type` | `(self, engage_type, *, scene=None) -> list[dict]` | 按 at/interaction/event 过滤 | 19 |
| `build_combat_init` | `(self, boss_entity, player, scene) -> CombatInit` | Boss 库 → CombatInit | 30 |
| `set_active` | `(self, boss_id)` | 设置活跃 boss | 84 |
| `to_dict` / `from_dict` | — | 序列化 | 107/114 |

---

## src/game/pre_parse.py (~90 行) — 消歧网关

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `disambiguate` | `(self, player_text, world_brief="") -> PreParseResult` | 判断输入清晰/模糊，跨 turn 整合 | — |

---

## src/game/turn_logger.py (~50 行) — 回合日志

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `log` | `(self, player_input, enrich_result, narrator_brief, narrator_narrative)` | 回合写为 `turn_NN.json` + `turn_log.jsonl` | — |

---

## src/investigator/ (>900 行 总计) — 调查员系统

### models.py — `Investigator`

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(self, name, age, gender, occupation, stats, derived, skills, weapons, ...)` | 构造调查员 | 154 |
| `get_skill` | `(self, name) -> Optional[Skill]` | 按名查技能 | 199 |
| `check_skill` | `(self, skill_name, difficulty="regular") -> tuple[bool, str, str]` | COC 7th D100 技能检定 | 211 |
| `build_snapshot` | `(self) -> dict` | 玩家状态快照 | 274 |
| `modify_stat` | `(self, stat_name, delta: int\|str) -> tuple[int, str]` | 修改核心属性（支持骰子公式） | 298 |
| `add_weapon` | `(self, w: Weapon)` | 添加武器 | 390 |
| `save` / `load` | — | JSON 存档 | 400/405 |

### rules.py — 纯函数规则引擎

| 函数 | 签名 | 作用 |
|------|------|------|
| `roll_stats` | `() -> Stats` | 按 COC 7th 骰子生成属性 |
| `calc_derived` | `(stats, age=20, cthulhu_mythos=0) -> DerivedStats` | 计算衍生属性 |
| `create_skill_list` | `() -> List[Skill]` | 基础值表 → 完整技能列表 |
| `calc_db` | `(STR, SIZ) -> str` | STR+SIZ → DB 字符串 |
| `load_occupations` | `(path) -> List[Occupation]` | 加载职业 JSON |

### serialization.py — 序列化

| 函数 | 签名 | 作用 |
|------|------|------|
| `to_dict` | `(inv: Investigator) -> dict` | Investigator → dict |
| `to_json` | `(inv, path)` | 导出 JSON |
| `from_dict` | `(data: dict) -> Investigator` | dict → Investigator |
| `from_json` | `(path) -> Investigator` | 从 JSON 加载 |

---

## src/library/ — 资源库

### enemies.py — EnemyLibrary

| 方法 | 签名 | 作用 |
|------|------|------|
| `load_core` | `(self, core_path=None)` | 加载 core/enemies.json |
| `get` | `(self, name) -> Optional[LibraryEnemy]` | 按名查询 |
| `list_all` | `(self) -> list[LibraryEnemy]` | 全部敌人 |
| `LibraryEnemy.from_dict` | `(cls, data) -> LibraryEnemy` | 解析 [flag] 标记 |

### weapons.py — WeaponLibrary

| 方法 | 签名 | 作用 |
|------|------|------|
| `load_core` | `(self, core_path=None)` | 加载 core/weapons.json |
| `get` | `(self, name) -> Optional[LibraryWeapon]` | 按名查询 |
| `list_all` | `(self) -> list[LibraryWeapon]` | 全部武器 |

### bosses.py — BossLibrary

| 方法 | 签名 | 作用 |
|------|------|------|
| `__init__` | `(self, core_path, extensions_dir=None)` | 加载 bosses.json |
| `get` | `(self, boss_ref) -> LibraryBoss\|None` | 按名查询 |
| `list_names` | `(self) -> list[str]` | 全部名称 |

### injector.py — ContentInjector

| 方法 | 签名 | 作用 |
|------|------|------|
| `offline_inject_module` | `(self, l2_data, l3_data) -> dict` | 管线离线注入武器/敌人 |
| `runtime_spawn_enemy` | `(self, enemy_name, scene_name, world=None) -> dict\|None` | 运行时 /spawn |

### judgment.py — JudgmentEngine

| 方法 | 签名 | 作用 |
|------|------|------|
| `tier1_skill_check` | `(self, skill_value, difficulty="regular") -> Tier1Result` | D100 检定（桩） |
| `tier1_damage_roll` | `(self, damage_formula, db=0) -> tuple[int, str]` | 伤害掷骰 |

---

## src/prompts.py (>1120 行) — Prompt 构建

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `build_keeper_parse_prompt` | `(world, user_input) -> str` | Keeper Step 1：匹配玩家输入到实体 | 465 |
| `build_keeper_enrich_prompt` | `(world, judged_entities, user_input) -> str` | Keeper Step 3：叙事整合 | 552 |
| `build_narrator_prompt` | `(brief, l1_scene=None, snap=None, user_input="") -> str` | Narrator：沉浸式叙事 | 601 |
| `build_author_prompt` | `(request, l3_data, persona="") -> str` | Author：patch/structural 判定 | 737 |
| `build_combat_entry_prompt` | `(player_input, outcomes_summary, enemy_context, current_scene) -> str` | 战斗入口判定 | 915 |
| `build_standoff_match_prompt` | `(player_input) -> str` | 对峙技能匹配 | 936 |
| `build_combat_narrative_prompt` | `(round_log, enemies_desc, player_name, scene) -> str` | 战斗叙事 | 959 |
| `build_npc_parse_prompt` | `(npc_name, user_input, bound_interactions, bound_auto_triggers, current_scene) -> str` | NPC 互动解析 | 1091 |
| `apply_trait_enhancement` | `(player, skill_name, skill_detail, entity_name, search_context, player_input, graded_tiers) -> tuple[str, dict\|None]` | 共享特质增强逻辑 | 90 |

---

## src/llm.py (~510 行) — LLM 封装

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `call_deepseek` | `(prompt, *, json_mode=True, system=None, model=None, thinking=None, reasoning_effort=None, temperature=None, max_tokens=None, max_retries=3, fallback_schema=None, timeout=300.0, _label=None) -> dict\|str` | **统一 LLM 入口**。JSON mode→temperature=0.2；text mode→0.7 | 123 |
| `evaluate_trait_enhancement` | `(inv_desc, skill_name, skill_detail, dice_roll, skill_value, entity_name, graded_tiers, search_context, player_input) -> dict` | 特质修正评估 | 272 |
| `evaluate_failure_penalty` | `(inv_desc, entity_name, skill_name, skill_detail, failure_tier, scene_context, graded_on_failure, retry_count) -> dict` | 失败惩罚生成 | 421 |

---

## src/config.py (~155 行) — 配置常量

| 常量 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `WR0_ENABLED` | `bool` | `False` | 创作者豁免 |
| `SHOW_NON_TRIGGERABLE` | `bool` | `True` | Parse prompt 展示不可触发实体 |
| `SHOW_COMPLETED` | `bool` | `False` | Parse prompt 展示已完成实体 |
| `COMBAT_LLM_ENHANCEMENT` | `bool` | `False` | 战斗 LLM 增强 |
| `LLM_TIMEOUT_MS` | `int` | `45000` | LLM 超时 (ms) |
| `LLM_SLOW_THRESHOLD_MS` | `int` | `8000` | 慢调用阈值 (ms) |
| `LLM_MAX_CONSECUTIVE_FAILURES` | `int` | `3` | 触发降级的连续失败数 |
| `MAX_ESCALATION_DEPTH` | `int` | `3` | Author 递归深度上限 |
| `INTENT_COOLDOWN_WINDOW` | `int` | `3` | Intent 去重窗口 |
| `COMMS_INTERVAL_MINUTES` | `int` | `15` | TimePressure 通信间隔 |
| `NPC_MEMORY_CAP` | `int` | `20` | NPC 对话记忆上限 |
| `PIPELINE_MAX_RETRIES` | `int` | `3` | 管线 LLM 重试上限 |
| `DEGRADE_POLICY` | `dict[str, dict]` | 各 Agent 降级策略 | keeper/narrator/author/time_agent/intent_detector |
| `AGENT_SYSTEM_PROMPTS` | `dict[str, str]` | 12 个 Agent system prompt 覆盖 | 空=用内置默认 |
| `AUTOSAVE_ENABLED` | `bool` | `True` | 自动存档开关 |
| `AUTOSAVE_INTERVAL_SEC` | `int` | `600` | 存档间隔 (s) |
| `AUTOSAVE_MAX_COPIES` | `int` | `5` | 最大存档份数 |

---

## frontend/server.py (~96 行) — FastAPI 入口

| 端点 | 路由 | 作用 |
|------|------|------|
| `health` | `GET /health` | 健康检查 |
| StaticFiles | `/static` | 静态资源 (CSS/JS/assets) |
| 6 个子路由 | launcher, game, character, editor, files, assets | — |

---

## frontend/routers/game.py (>1010 行) — 游戏 API

| 端点 | 方法/路由 | 参数 | 作用 | 行号 |
|------|-----------|------|------|------|
| `game_page` | `GET /game` | — | game.html 页面 | 159 |
| `process_turn` | `POST /api/game/turn` | `user_input`, `action_type`, `action_target` | 回合入口：斜杠命令短路 / `run_turn` 线程池 | 238 |
| `init_game_api` | `POST /api/game/init` | `l1/l2/l3/char_path`, weapon/enemy/boss path | 初始化游戏 + 首回合 | 634 |
| `character_card` | `GET /api/game/character-card` | — | 角色卡 HTML | 408 |
| `player_status` | `GET /api/game/player-status` | `?format=json` | HP/SAN 状态 | 552 |
| `scene_info` | `GET /api/game/scene` | — | 场景信息 HTML | 585 |
| `game_state` | `GET /api/game/state` | — | 游戏状态 JSON | 722 |
| `npcs` | `GET /api/game/npcs` | — | 场景 NPC HTML | 940 |
| `command` | `POST /api/game/command` | `cmd` | 斜杠命令 | 580 |
| `combat_start` | `POST /api/combat/start` | JSON body | 初始化战斗会话 | 736 |
| `combat_round` | `POST /api/combat/round` | JSON body | 执行一轮战斗 | 794 |
| `game_progress` | `WS /api/game/progress` | — | 管线进度推送 | 602 |

---

## frontend/routers/launcher.py (~240 行) — 启动页 API

| 端点 | 方法/路由 | 作用 |
|------|-----------|------|
| `launcher_page` | `GET /` | 启动页 |
| `launcher_tab` | `GET /launcher/tabs/{tab}` | 动态加载 tab partial |
| `save_config` | `POST /api/config/save` | 保存配置 |
| `load_config` | `GET /api/config/load` | 读取配置 |
| `start_step0` | `POST /api/step0/start` | 启动 Step 0 子进程 |
| `start_pipeline` | `POST /api/pipeline/start` | 启动管线子进程 |
| `validate_pipeline` | `POST /api/pipeline/validate` | 校验中间文件 |

---

## frontend/routers/character.py (~340 行) — 车卡 API

| 端点 | 方法/路由 | 作用 |
|------|-----------|------|
| `character_page` | `GET /character` | 车卡页 |
| `step_partial` | `GET /character/step/{n}` | 步骤 partial |
| `roll_stats` | `POST /character/roll` | 掷骰属性 |
| `skills_list` | `GET /character/skills-list` | 职业技能列表 |
| `generate_description` | `POST /character/generate-description` | LLM 生成外貌 |
| `export_character` | `POST /character/export` | 导出 ZIP |

---

## frontend/routers/editor.py (~120 行) — JSON 编辑器

| 端点 | 方法/路由 | 作用 |
|------|-----------|------|
| `editor_page` | `GET /editor` | 编辑器页 |
| `load_json` | `GET /editor/load` | 加载 JSON 树 |
| `save_json` | `POST /editor/save` | 保存 JSON |
| `validate_json` | `POST /editor/validate` | 校验 JSON |

---

## frontend/routers/files.py (~60 行) — 文件浏览

| 端点 | 方法/路由 | 作用 |
|------|-----------|------|
| `list_files` | `GET /api/files` | 目录浏览（html/json） |

---

## frontend/routers/assets.py (~80 行) — 素材

| 端点 | 方法/路由 | 作用 |
|------|-----------|------|
| `list_assets` | `GET /api/assets/list` | 素材列表 |
| `random_asset` | `GET /api/assets/random` | 随机素材 |

---

## src/module_designer/layered_pipeline.py (~920 行) — 管线编排

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_pipeline` | `(content, llm_json, llm_text=None, ...) -> PipelineResult` | 执行 4 步渐进式管线：Step1→2a→2b+2c→3a∥2.5→3b→3.5/Phase1→Phase2 | 439 |
| `run_supplement_pipeline` | — | Author StructuralEdit 触发的轻量补充管线 | — |
| `_bind_npc_entities` | `(interactions, auto_triggers, npc_profiles, entity_bindings=None) -> tuple` | 扫描 entity NPC 归属 → 剥离+绑定 | 227 |
| `_inject_step1a_meta` | `(npc_profiles, step1a_characters, verbose=False)` | Step 1a → NPC scene 注入 | 298 |
| `_inject_npc_special_entities` | `(interactions, npc_profiles, verbose=False)` | 注入 follow_unlock + interact_unlock entity | 317 |
| `_assemble_l2` | `(interactions, events, auto_triggers, scene_movements, l1_data, npc_profiles, boss_encounters) -> dict` | 所有 entity 组装为 L2 JSON | 367 |
| `save_pipeline_result` | `(result, module_dir)` | 写入 l1/l2/l3 JSON | 889 |
| `cross_validate_layers` | `(l1, l2, l3, weapon_lib, enemy_lib) -> CrossRefReport` | 跨层引用验证 | 96 |

---

## src/module_designer/layered_parser.py (>1470 行) — 管线解析

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `parse_step1a` | `(content, llm_call, weapon_lib, enemy_lib, boss_lib) -> dict` | 模块元信息+场景+角色+Boss+敌人/武器约束 | 278 |
| `parse_step1b` | `(content, llm_call) -> dict` | 精修模组文本 | 350 |
| `parse_step2a` | `(chapters, scenes, llm_call, characters, skill_names) -> dict` | interactions + scene_movements | 471 |
| `parse_step2b_combined` | `(chapters, scenes, interactions, llm_call, ...) -> dict` | events + auto_triggers（合并） | 563 |
| `parse_step2c_l1` | `(chapters, scenes, characters, llm_call) -> dict` | L1 场景感知信息 | 631 |
| `parse_step2c_l3` | `(chapters, scenes, characters, llm_call, step1_meta) -> dict` | L3 设计者层 | 696 |
| `parse_step25_combined` | `(l3_characters, l1_data, interactions, auto_triggers, llm_call, step1a_characters) -> dict` | NPC 档案+entity 归属+follow/interact 解锁（合并） | 834 |
| `parse_step2_boss` | `(boss_hints, boss_lib_names, interactions, auto_triggers, scenes, chapters, llm_call) -> dict` | Boss 遭遇实体生成 | 932 |
| `parse_step3a` | `(chapters, interactions, events, auto_triggers, ending_conditions, llm_call) -> dict` | 去重+冲突解决+结局标记 | 1016 |
| `parse_step3b` | `(chapters, l1, l2, l3, step1_scenes, llm_call) -> dict` | 确定性修复+LLM 补 linked_interaction | 1150 |
| `parse_step35` | `(chapters, interactions, events, auto_triggers, llm_call) -> dict` | 依赖图提取 | 1269 |
| `parse_step4` | (Phase 2) | 标准化 @markup | 1459 |
