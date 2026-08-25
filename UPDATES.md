# UPDATES — 待修改内容细节

> 本文档记录需要修改但暂未实施的内容，作为 TODO 的详细补充。完成一项删一项。

---

## PyInstaller 封包后调查员头像路径解析（2026-05-31）

**现状**：`_build_export()` 中通过 `PROJECT_ROOT / 'frontend' / 'static' / 'uploads' / 'avatars' / ...` 查找头像。打包后 `PROJECT_ROOT` 由 `character.py` 的 `Path(__file__).resolve().parent.parent.parent` 计算得出，在 PyInstaller 模块中可能指向异常路径。

**影响**：导出角色卡时头像文件可能无法正确包含到 zip 中（但角色 json 本身不受影响，功能不阻塞）。

**后续**：如需修复，应将 avatar 路径改为使用 `FRONTEND_DIR`（已在 `server.py` 正确定义）或 `character.py` 自身的 `UPLOADS_DIR`，而非重新拼接 `PROJECT_ROOT`。

---

## 代码库结构审计（2026-05-31）

**Top 3 高影响优化**：

| # | 事项 | 影响面 | 预期减量 |
|---|------|--------|----------|
| 1 | `Entity.from_dict()` 统一工厂 | 8+ 处重复构造，散落在 3 个文件 | ~100 行 |
| 2 | 合并双份 `apply_side_effects`（keeper vs scenario_core） | 两份 ~100 行处理同一套 7 种效果，维护不同步风险 | ~100 行 |
| 3 | 提取 trait enhancement 为独立函数 | judge / keeper(search) / keeper(standoff) 三处完全相同的 20 行 block | ~40 行 |

**重复代码全貌**：12 处重复（HIGH×4 / MEDIUM×7 / LOW×1），6 个结构问题，8 个合并机会。

**结构性**: `process_turn()` 743 行需拆解，`world.enemy_manager` vs `world.enemies` 命名不一致，dead code 若干。

---

---

## @consume_item 在 requirement 中作为前置门禁（2026-05-31）

**现状**：Phase 2 管线将 requirement 中的自然语言（如"需要消耗1个急救包"）标准化为 `@consume_item` 写入 `side_effects`。运行时 `parse_markup_all` 解析后，物品在 entity 执行后删除（后置副作用），不在执行前作为前置门禁。

**问题**：
- 玩家没有物品时无法拒绝（"你没有这个物品"）
- 技能检定失败时物品照样被消耗

**修改方式**：在 requirement 解析中加入物品消耗检查，或额外增设一个字段。本质上仍须通过自然语言处理——`@consume_item` 本身可嵌入 requirement 文本中，由 `parse_markup_all` 提取后作为前置门禁判断。

**涉及文件**：`src/game/judge.py:_execute_entity()`、`src/game/agents/keeper.py`、`src/module_designer/layered_parser.py`（Phase 2 prompt）

---

## [P0] 模组打包：深渊第七城 + 常暗之厢_0531（2026-05-31）

待打包模组：

| 模组 | L2 路径 | 初始场景 | 测试武器 | 状态 |
|------|---------|---------|----------|------|
| 深渊第七城 | `data/modules/深渊第七城/l2_keeper.json` | 波士顿阿什克罗夫特办公室 | ✅ 已添加（试作型裁决者/湮灭者） | 待打包测试 |
| 常暗之厢_0531 | `data/modules/常暗之厢_0531/l2_keeper.json` | 6号车厢 | ✅ 已添加（试作型裁决者/湮灭者） | 待打包测试 |

打包步骤：
1. 运行 `python run_pipeline.py --auto --module 常暗之厢_0531` 生成三层 JSON
2. 按相同方式处理深渊第七城（已有 l2_keeper.json，as L2 入口）
3. 用 CLI 或前端启动验证战斗系统是否正常触发

---

## 战斗伤害结算重检（2026-05-31）✅ 已确认无阻塞问题

**重检结果**：

```
玩家伤害链：_roll_damage → -armor(+AP) → ×damage_multiplier → ×1.5(charge) → action.damage → LLM修正 → enemy.hp -= action.damage
敌人伤害链：_roll_damage → action.damage → state.player_hp -= action.damage → LLM修正(回退旧+应用新) → state.player_hp
```

- **交互式路径**（run_game.py）：LLM 修正通过修改 `state.log` 中的 `a.damage` 实现，最终 `enemy.hp -= act.damage` 读取的是修正后值。对象共享引用，`state.full_log` 自动反映修正。✅
- **自动战斗路径**（combat.py run_combat）：玩家伤害读取 `rresult["player_damage"]`（LLM 返回），敌人伤害通过回退旧值 + 应用新值修正。✅
- **群组展开**：`_init_combat` 拆分后的独立实体各有独立 hp，damage 独立结算。✅
- **hp_before/hp_after**：`_resolve_enemy_action` 中设置后在 LLM 修正时未同步更新，仅影响日志展示不影响游戏。⚠️ 低优先级。

结论：两部分损伤结算路径逻辑正确，暂无明显 Bug。

---

## [P0] 架构审计：子回合模式统一化（2026-05-30）

**设计模式**：主回合 parse → judge → enrich → curate。7 个独立子系统以子回合形式接入——在 parse 同期或之后启动，结果在主回合外处理，再接回。

**审计结果**：

| 子系统 | 并行? | 接回方式 | 问题 |
|--------|-------|----------|------|
| IntentDetector/Author | 是（ThreadPoolExecutor 早启动） | 晚收集 → 递归 escalation | 最干净的子回合实现 |
| Combat（战斗） | 否 | `complete_combat_turn()` 重放 enrich→curate | 仅重放叙事层，不重跑完整 pipeline。可接受但不够彻底 |
| Weapon Offer（武器拾取） | 否 | 跨两回合：turn N 设 offer → turn N+1 消费 | 应改为同回合可中断子回合 |
| Pre-parse（消歧网关） | docstring 声称并行，实际串行 | Step 0 gate | 应与 parse 真正并行以降低延迟 |
| NPC 纯对话 | 否 | 短接整个 pipeline，不经过 narrator | 设计正确但缺乏 L1 沉浸 |
| Standoff（对峙） | 否 | 每个 group 消费一个回合输入 | 应改为同回合可中断子回合 |
| TimeAgent | 是（enrich 内并行） | enrich 结果同时收集 | 不是独立子回合，是 enrich 内的并行 LLM 调用 |

**致命 Bug**：`resolve_standoff` 方法缺失 `def` 声明行（被 `complete_combat_turn` 覆盖），运行时 `continue_standoff` 会 `AttributeError`。修复：补 `def resolve_standoff(self, standoff_state: dict, player_input: str) -> dict:`。

**涉及文件**：`src/game/agents/keeper.py`（子回合入口 + resolve_standoff 修复）、`src/game_loop.py`（continue_standoff）、`src/game/pre_parse.py`（并行化）

**参考**：DEBUG_JOURNAL.md #65, #66

---

## Boss/Enemy 管理统一化

- **现状**：EnemyInstance 有两个创建入口——`EnemyManager.spawn()`（普通敌人）和 `BossManager.build_combat_init()`（Boss）。两条路径各自维护字段完整性，已导致 flags 字段在 spawn 路径丢失。
- **目标**：两者共享 `EnemyManager.create_instance(lib_data, scene, quantity)` 唯一入口，Boss 特殊性通过 `flags=["boss"]` 标记表达而非分离 API。
- **涉及文件**：`src/game/enemy_manager.py`、`src/game/boss_manager.py`、`src/game/agents/keeper.py`
- **参考**：DEBUG_JOURNAL.md #64, LEARNING_JOURNAL "同类子系统的双轨制是 Bug 温床"

---

## EnemyManager.spawn() flags 字段补传

- **修复**：`spawn()` 中 `hp=base_hp` 后加 `inst.flags = list(getattr(lib_enemy, 'flags', []))`
- **涉及文件**：`src/game/enemy_manager.py:78`
- **注意**：此项与上方"管理统一化"关联——统一入口后自然修复。

---

## 输出流信息规范化

- **目标**：所有结果先过 Enrich，Narrator 只读 Enrich 产出 + 场景信息。
- **涉及文件**：`src/game/agents/keeper.py`、`src/game/curator.py`、`src/prompts.py`

---

## flags 标签系统

| 标签 | 定义源 | 消费者 | 状态 |
|------|--------|--------|------|
| `avoidable` | enemies.json (深潜者) | keeper.py 对峙流程 | **失效**（spawn 未传 flags） |
| `adjacent_aware` | enemies.json (Clicker) | enemy_manager.py 跨场景感知 | **失效**（spawn 未传 flags） |
| `guardian` | enemies.json (石卫) | 无消费代码 | 死数据 |
| `boss` | bosses.json (全部 Boss) | combat.py Boss 战斗路由 | **正常** |

---

## 武器拾取逻辑三处重复（2026-05-30）

- **现状**：`keeper.py` 中有三处几乎相同的"库武器 → Investigator Weapon"构造逻辑：
  - L83-118：武器拾取确认流程（`_weapon_offer` 消费）
  - L330-375：搜索中的武器拾取
  - L399-448：other 路径中的武器拾取
- **风险**：三处独立维护，已有一处代码路径使用了不同的属性访问模式（`lib_wep.name` vs `lib_wep["weapon_ref"]` vs `_wattr(lib_wep, key, default)`）。修复一处 bug 另两处可能遗留。
- **方案**：抽 `_build_investigator_weapon(lib_weapon)` 工厂方法，统一构造 `investigator.models.Weapon` 实例
- **涉及文件**：`src/game/agents/keeper.py`

---

## process_turn() 过长（2026-05-30）

- **现状**：单一 `process_turn()` 方法 920 行，承载 parse → judge → enrich → combat → boss → time → author → curate 全流程。出问题时 920 行中定位根因困难。
- **方案**：拆为 5 个阶段方法：`_step_parse()` / `_step_judge_combat()` / `_step_enrich_time()` / `_step_author()` / `_step_curate()`。每个方法职责单一，返回下一阶段的输入。
- **涉及文件**：`src/game/agents/keeper.py`

---

## Combat Entry LLM 异常静默吞掉（2026-05-30）

- **決議**：当前行为（LLM 失败 → 默认不进入战斗）是合理设计。战斗入口判定是 LLM 增强功能，失败时退避为"不战斗"比"无条件进入战斗"更安全。保留现状。

---

## Memory 压缩线程无错误反馈（2026-05-30）【低优先级】

- **决议**：daemon 线程静默失败可接受。压缩是 best-effort 功能，失败不影响游戏。延后处理。
- **涉及文件**：`src/game/agents/keeper.py:890-897`

---

## PreParse 消歧计数器跨回合不累积（2026-05-30）【低优先级】

- **决议**：当前行为（仅单回合内 2 次兜底）可接受。跨回合追踪可能引入更复杂的状态管理。延后处理。
- **涉及文件**：`src/game/pre_parse.py`

---

## Enemy/Boss 特殊字段统一化（2026-05-30）

- **现状**：`flags` 标签（`avoidable` / `adjacent_aware` / `guardian` / `boss`）定义散落在 `enemies.json` 和 `bosses.json`，消费者各自解析，部分标签无消费代码（`guardian` 是死数据）。
- **目标**：
  1. 统一定义：所有特殊行为标记收敛到一个枚举或常量集，消除僵尸标签
  2. 统一消费：`avoidable` → 对峙流程、`adjacent_aware` → 跨场景感知、`boss` → Boss 战斗路由，三者走同一个 flag 解析入口
  3. 字段完整性：`EnemyManager.spawn()` 和 `BossManager.build_combat_init()` 共享唯一的 `create_instance()` 入口，消除 flags 字段丢失的 Bug
- **涉及文件**：`src/game/enemy_manager.py`、`src/game/boss_manager.py`、`src/game/agents/keeper.py`、`src/library/enemies.py`、`data/library/core/enemies.json`

---

## NPC 注入实体无限增长（2026-05-30）

- **现状**：`_inject_npc_at()`（keeper.py:1114-1175）每回合将 NPC 的 bound_interactions 和 bound_auto_triggers 追加到当前场景 node 的列表中。去重仅检查 `(id, not completed)`，但 NPC 离场/死亡后已注入的 entity 永远不会被清理。
- **风险**：多回合游戏（尤其是 NPC 频繁进出场景时）node 列表线性增长，Parse prompt 越来越长，LLM 延迟逐步增加，最终 token 超限。
- **方案**：在 NPC 离场/状态变更时清理其注入的 entity（从 node 中移除 `id in _npc_injected_at_ids` 的 entity），或改为不注入到 node 本体而是动态生成 entity 列表供 Parse 使用。
- **涉及文件**：`src/game/agents/keeper.py:1114-1175`、`src/scenario_core.py:721`

---

## TurnMonitor 每回合全量序列化（2026-05-30）

- **现状**：`TurnMonitor.begin_turn()` 调用 `inv_to_dict(player)` + `graph.to_dict()` + `world.to_dict()`——相当于每次行动前做一次完整存档。每回合耗时 ~50-200ms 纯 Python 序列化。
- **方案**：改为 lazy snapshot——仅在步骤失败时才触发回退序列化。正常流程不执行。
- **涉及文件**：`src/monitor/turn_monitor.py:34-46`

---

## 时间条件不满足时无玩家反馈（2026-05-30）

- **现状**：Judge 在 `keeper.py:222-226` 仅 `continue`，不做叙事提示。玩家输入匹配 entity 但 `time_condition` 不满足时静默跳过，Parse 可能将输入误匹配到 other。
- **方案**：生成 `ActionOutcome` 提示"现在不是合适的时机"，让玩家感知到条件限制的存在。
- **涉及文件**：`src/game/agents/keeper.py:222-226`

---

## _weapon_offer 在递归时状态可能冲突（2026-05-30）

- **现状**：`_weapon_offer` 是 Keeper 实例属性。Author 触发 `process_turn()` 递归时，内层递归可能覆盖外层的 `_weapon_offer`。
- **方案**：递归前保存，递归后恢复；或将 offer 改为局部变量通过回调传递。
- **涉及文件**：`src/game/agents/keeper.py:68, 83-118, 375, 900`

---

## Author 降级时持续注入拒绝叙事（2026-05-30）

- **现状**：Author 降级后 `reject_all_structural=True`，Keeper 的 Step 4 每次 Reject 都向玩家注入"你尝试了，但..."叙事。连续多回合降级会让玩家感觉"作者一直在拒绝我"。
- **方案**：降级时直接跳过 Author 整个 Step 4，不注入拒绝叙事，让游戏退化为纯 Closed-World 模式。
- **涉及文件**：`src/game/agents/keeper.py:784-826`、`src/monitor/policies.py`

---

## 技能检定返回裸 tuple（2026-05-30）

- **现状**：`Investigator.check_skill()` 返回 `(ok: bool, msg: str, tier: str)`，调用方用位置解包——参数顺序易错。且已经定义了 `SkillCheckResult` dataclass 但未在此处使用。
- **方案**：`check_skill()` 返回 `SkillCheckResult` dataclass。
- **涉及文件**：`src/investigator/models.py`、所有 `check_skill()` 调用方

---

## 工作方向约定与后续队列（2026-07-31）

**方向约定**：当前只关注 CLI client（`run_game.py` 交互式命令行入口）；前端（`frontend/` FastAPI + game.html）暂时不管——前端相关 bug/重构不排期，除非阻塞 CLI。

**队列顺序约定**：修复类任务优先；**重构排倒数第二**；存读档 🔴 bug 排最后。
> 活跃队列与全部已知问题已集中于 `docs/ISSUES.md`;本节为历史记录。

1. ~~run_game.py 预存 import 缺失~~ ✅（1872419 已修，CLI 冒烟通过）
2. ~~test_escalation_real 从未真实调 LLM~~ ✅（d2e4fdd 已修：load_dotenv + wrapper 兼容 `_label` kwarg。真相：原"基线 4 失败"是 wrapper TypeError 被 keeper 吞掉导致全程降级；修复后脚本模式 5/5 通过。case C/E 依赖 Author 升级决策，存在真实 LLM 波动性）
3. ~~test_turn_monitor 基线失败~~ ✅（1e6edfd 已修：断言更新为 freeze 不再调 save_state 的现行行为）
4. ~~SUSPENDED/FROZEN 回合不进 TurnLogger~~ ✅（ecba8aa 已修）
5. **重构（倒数第二）**：中断机制（resolver 注册表）、战斗完成契约统一（B5）、process_turn 拆分（C1）。~~keeper 发 weapon_offer PendingInteraction~~ ✅（de8fefd 已修）
6. **存读档 3 个 🔴 bug（最后）**：EnemyManager.from_dict 无 library 静默吞异常致 enemies 变 None；两条读档路径不一致（run_game 替换 world 但 judge/curator 持旧引用）；`_npc_injected_at_ids` 不入档致重复注入。

---

## 工作汇总（2026-08-04）

### 已完成

**① TurnResult 契约迁移**（a2e503b→baeb786，13 commits，详见 `docs/superpowers/specs/2026-07-31-turnresult-contract-design.md`）
- process_turn（7 种 dict）/run_turn（14 键 dict）→ 双层 dataclass 契约（TurnResult/PlayerTurnResult + TurnStatus 枚举 + PendingInteraction）
- SUSPENDED 仅用于 clarify（回合阻塞）；offer/standoff = COMPLETED + pending_interaction
- enrich 合并叙事与 outcome 事实分离（NarratorBrief.enriched_summary）
- 顺带修复：`_standoff_pending` 从未播种（standoff 曾生产不可达）、standoff 战斗叙事丢失、/api/game/init 吞异常致开场白为空、前端死代码隐藏 exit_combat 双重调用

**② 修复批**（1872419/de8fefd/1e6edfd/ecba8aa/d2e4fdd）
- run_game.py import 恢复（CLI 可运行）、weapon_offer 契约对称、turn_monitor 断言、SUSPENDED/FROZEN 记 TurnLogger、escalation 基建修复（见上队列 2）

**③ 分层 E2E 测试体系**（spec：`docs/superpowers/specs/2026-07-31-e2e-test-system-design.md`）
- 步骤 1（2bb6c20）：确定性 E2E 7 场景（offer/clarify/战斗/移动/结局/NPC/多回合序列），`tests/e2e/`，零 API，默认套件一部分
- 步骤 2（af3048c）：真实 LLM 固定输入 S1-S9，combat_entry/standoff_match 单点 stub + 其余真实，`real_llm` marker 默认排除，实测 9/9（172s）
- 步骤 3（9ccb274/8bff62c）：testbed 专用测试模块 + 场景化 llm_player 机制（goal 注入/播种 hook/谓词判定/runner + LLM judge 三层判定）+ pilot 场景 standoff_avoid（实跑 8 回合 standoff 有机触发，judge PASS 带证据）
- 顺带修复 2 个真缺陷：combat_entry prompt 语义被 LLM 反向理解致 standoff 触发不可达（prompts.py:931）；llm_player 硬编码 start_node 改为读 l3 start_scene

**测试现状**：默认套件 68 passed / 14 deselected（real_llm）；real_llm 套件 = escalation 5 + scenarios 9（on-demand，`pytest -m real_llm`）；场景 runner 独立 CLI（`tests/e2e/run_scenario.py`）

---

## 工作汇总（2026-08-14）

### 已完成

**④ 场景层完备化 + 谓词分层 + R1/R2 拾取修复**
- Phase 0-4 落地：审计手册（f002c4c）→ 机制时间线+三档输出（c030a25）→ 骨架层 D8-D12（4919380）→ 实连层试点 S10/S11（b188834）→ 全量实连 14/16 + prompt 缺 json 字样 400 静默降级修复（4f36cda）→ Author 升级硬性门控防递归丢帧（dcce6e8/2a225b6）
- 谓词分层：`predicates`（engine 事实硬卡 verdict）/ `outcome_goals`（玩家侧目标只报告）；full_clear 的 game_over 归入 outcome_goals
- **R2 修复**：weapon_offer 门严格只认「是/否」本身（标点容忍），其他输入作废 offer 走正常回合——修复"别怕，我是来帮你的"含"是"被当拾取确认
- **R1 修复**：直接拾取通路——明说「捡/拾/拿+武器名」（场景仅一件可不点名）直接入包；含否定词/已持有时不触发；offer 应答与直接拾取共用 `_grant_scene_weapons`
- `weapon_picked_up` 谓词修复：双通道（系统输出"你拾起了" OR 数量增长），消除首回合拾取盲区
- **F3 修复**：standoff×boss 同回合互斥（方案 B）——Boss 强制战命中时撤回 standoff 播种/话术，avoidable 敌人并入 Boss 战；at 与 event 两条 engage 通路共用 `_devour_standoff_for_boss`；审计手册补互斥条目防 judge 误报
- **S-D full_clear 全绿**：14 回合，搜索→直接拾取→NPC→绕开巡游者→Boss(AUTO)→低语结局，三层判定全 PASS
- 确定性套件新增 TestWeaponPickupRules 7 测试 + TestStandoffBossMutex 2 测试；审计手册补武器拾取双路径条目；rubric 承认直接拾取/绕行合法路径

**测试现状**：默认套件 86 passed / 16 deselected（real_llm：S1-S11 + escalation 5）；场景层 S-A/S-B/S-C/S-D 全 PASS

**⑤ U2 WorldChronicle 世界状态摘要层**（eb28df9→4d46768，spec：`docs/superpowers/specs/2026-08-14-world-chronicle-design.md`，plan：`docs/superpowers/plans/2026-08-14-world-chronicle.md`）
- WorldChronicle 挂 ScenarioWorld：facts 实时采集/events 窗口 15 带玩家原话/entity_results 截断 100/patches 清单/序列化入档
- game_loop 每回合 record_turn（含移动轨迹，FROZEN 不记）；Author prompt 注入【世界编年史】块（scene_ctx 后 intent_ctx 前）
- patch/supplement 成功集成后 record_patch（reject 不记）；LLM 蒸馏仅留 compress_events 接口（本期不接线）
- keeper parse/enrich/narrator 明确不接 Chronicle（控制范围，本期唯一消费者 Author）

---

## 工作汇总（2026-08-15）

### 已完成

**⑥ U9 技能系统重修**（b599f9f→31c7058，spec：`docs/superpowers/specs/2026-06-10-skill-system-redesign.md`（2026-08-14 修订版），plan：`docs/superpowers/plans/2026-08-14-skill-system-redesign.md`）
- 45 技能/9 属性 → **20 技能/8 属性**配置化体系：`data/skill_config.json` 单一事实源（技能/属性乘数/legacy_map/attr_aliases/pseudo_skills），`normalize_skill_name()` 五路归一（skill/attr/pseudo/ignore/unknown）单点下沉 `get_skill`/`check_skill`
- Stats 删 SIZ（并入 CON）、DerivedStats 删 MOV；新衍生公式 HP=CON//3、DB/BUILD 查表键=STR+CON//2；属性池分配（属性值×乘数均分归属技能）；职业标签制（occupation_labels.json）
- LUCK 声明式消耗：keeper 识别「烧/用 N 点幸运」→ spend_luck + pending_luck_bonus（当回合检定一次性消费）
- 序列化 v2.0：旧卡（含 SIZ）拒绝加载提示重建；combat_test_character.json 按新体系重建（**武器仅留徒手**——预装小刀会让 full_clear 的 weapon_picked_up 谓词基线失效，偏离 plan Task 8 的「徒手+小刀」）
- 管线/前端适配：layered_pipeline + run_pipeline 技能名改从 config 拉取、stat_names 删 SIZ、parser 落库归一；前端车卡 STATS/SKILLS/STAT_ROLLS 从 config 读（模板按属性分块 UI 后置）
- 数据清理：删 skill_checks.json/occupations.json，load_skill_checks 数据源切 config
- 敌人/Boss 侧 SIZ 与 calc_db(STR,SIZ) **保留不动**（神话生物有体型）

**测试现状**：默认套件 127 passed；场景层 S-D full_clear VERDICT PASS（三层）；实连层 real_llm 11 passed

**⑦ 编年史收尾 + 车卡向导 U9 适配**（70459b6/6a210bd，spec：`docs/superpowers/specs/2026-08-15-chronicle-charwizard-design.md`）
- `_integrate_patch` 的 entity_ids 改记集成后真实 id（含 NEW_xxx 回退），修原始 dict id 空串不一致
- 编年史补三通道投影：spawn（SpawnEnemy 副作用）/ combat=end（挂在 complete_combat_turn 统一入口，CLI/前端/auto 全覆盖）/ boss=engage·defeated（Chronicle 内置 diff，基准集入档防读档重报）；`_collect_mech_line` **不切源**（它还采 move/tier 箭头等编年史没有的字段）
- facts 渲染补 Boss 块（已开战状态+阶段 / 未遭遇清单）与玩家关键物品（memory.key_items）
- 车卡向导：技能按归属属性分 8 块（双属性技能首块可编辑、其余只读；块标题乘数+池参考实时算）；职业标签下拉读 occupation_labels.json（专精 +10 封顶 99、换标签整表重渲染）；导出写 personal.label、v2.0；模板 SIZ 残留清零
- 新增 tests/test_frontend_character.py 5 例（TestClient 冒烟）+ test_chronicle.py 6 例

**测试现状**：默认套件 139 passed

### 待办（按优先级）

0. **前端**：现栈优化（抽 JS 出 game.html/htmx 面板/Alpine 局部交互），等用户手动测试反馈后排期
1. **R4 parse 稀疏实体过度匹配**：IT_END 误触发隐患（S-D 首跑曾现，近两轮未复现）——**暂缓**（2026-08-15 用户拍板，保持观察不处理）
2. ~~巡检层 verdict 化~~（用户拍板暂缓）
3. **重构（倒数第二）**：resolver 注册表 / B5 战斗完成契约 / C1 process_turn 拆分——现有 E2E 三层即其回归网
4. **存读档 3 个 🔴 bug（最后）**：见上队列 6

### 已知观察（非阻塞）

> **已迁移**:全部活跃问题集中于 `docs/ISSUES.md`(单一事实来源),本节不再更新。历史各期"已知观察(本期新增)"为当时快照,保留原文备查。
---

## 工作汇总（2026-08-18）

### 已完成

**real_llm 复测 + 文档巡检（session 死机后核对）**
- 测试：默认套件 139 passed；real_llm 14/16--escalation C/E 挂，同 08-14 已知门控机制（见已知观察末条），带日志复跑 2 次均稳定复现；S1-S11 全过（S5 首跑失败 retry_once 内消化）
- 测试基建缺口（未修）：escalation_real 在 pytest 下 `log_dir=""` 全部诊断日志 no-op（`tests/e2e/test_escalation_real.py:184`），失败无现场，需 `python tests/e2e/test_escalation_real.py C E` 手跑
- MAINTENANCE.md 行号巡检刷新：keeper（+17，中段漂移 +38~+110）/combat（+6）/models（+3）/layered_parser（+14）/layered_pipeline（-7）/scenario_core（尾部 +6，文件头 1643->1712）/run_pipeline（尾部 -4）对齐实际快照；逐函数核对**内容条目无缺漏**；**llm_player.py 有内容缺漏**：`_collect_mech_line`（@138，场景 runner 机制时间线，08-10 c030a25 引入）未入档、`_log_player_call` 移为嵌套函数未标注、文件头 382->482；prompts.py 尾部 +6 / game_loop init_game +1 一并修正；character.py/rules.py/serialization.py/utils.py/game.py 原本全准

---

## 工作汇总（2026-08-19）

### 已完成

**统一资源层落地（U6 法术 + U8 物品 + parse 规范化）**--spec/plan 见 docs/superpowers/{specs,plans}/2026-08-18-unified-resource-impact*，14 任务全 TDD，16 个提交：

- **前置修复**：DerivedStats 拆 MP_MAX；`_recalc_derived`/`modify_stat` 经 `_carry_current` 保留 HP/MP 当前值（涨上限携带差值、降上限 clamp），SAN 永不重置；序列化 v2.1（known_spells + MP_MAX，v2.0 兼容加载）
- **素材库**：`src/library/items.py`/`spells.py` + `data/library/core/{items,spells}.json`（12 物品/8 法术，impact L0/L1/L2 库预标注 + use_semantic + check + on_use @markup + result_slots）；ScenarioWorld 挂 item_library/spell_library，init_game 自动接线（core + extensions）
- **@grant_spell**：第 8 种 markup（GrantSpell -> spell_library 校验 -> known_spells，不重复授予）；全库枚举同步（side_effects/prompts/judge 三处 strip 正则 + Author 文档）
- **UseParser 子系统**：`src/game/use_parser.py` 独立小 parse 系统（MaterialCatalog 协议可注入素材源）；确定性层（否定排除 -> USE_VERBS 谓词 -> 精确/包含/difflib 三级匹配）+ LLM 兜底（build_material_fuzzy_prompt 通用化，旧 consume_item 包装兼容）；keeper pre-parse 短路 + parse use 条目归一（未命中转 creative 升 Author）
- **Judge.execute_material**：L1 执行通道（硬门[已知/持有/MP/材料] -> 扣减[refund_on_fail 回滚] -> 可选检定[下沉复用 check_skill/opposed_check] -> 结果槽 tier 选档 -> on_use @markup 走 apply_side_effects）
- **门控 flavor 豁免**：parse other 拆 flavor/creative 子类；other_flavor 永不触发 detector；other_creative 仅帧内无实质性动作（interaction/event/move/search/use/NPC）时升级，氛围 AT 捎带不算实质覆盖
- **战斗施法**：cast_<SPELL_ID> 动作（known_spells∩combat）+ MP/SAN 扣减 + opposed/常规检定 + effect damage 结算（4 处 CombatSystem 构造点接 spell_lib）
- **requirement `item:` 条件**：持有硬条件先行短路（judge._evaluate_requirement）
- **管线感知**：Step1a prompt 物品/法术库摘要；STEP4/Step2A @grant_spell 语法；cross_validate_layers spell_ref 校验（未知引用记 warning）；run_pipeline 双库加载
- **编年史/快照**：render_for_author 玩家行含 MP_MAX + 已知法术；build_snapshot 增 mp_max/known_spells
- **文档**：MAINTENANCE.md 全面同步（新增 items/spells/use_parser 三节 + 全部行号刷新）；readme U6/U8 标 ✅

### 测试现状

- 默认套件：181 passed（基线 139 + 新增 42：test_use_system.py 33 + deterministic +5 + scenarios S12-S14 结构）
- real_llm：S1-S14 全过（14/14，含新 S12 感知法术/S13 急救包/S14 库外素材升 Author）
- escalation C/E：**双双 PASS（手跑 + pytest）**--门控 flavor 豁免修复了 2026-08-14/08-18 已知阻塞（见已知观察末条，已收口）；case E 在 pytest 首跑偶现"Author patch 未产新场景"（LLM 行为波动，复跑即过，与门控无关）

### 已知观察（本期新增）

- 测试期间产生 data/modules/supplements/20260819_* 目录（S14 场景 Author 真实调用副产物），未入库

---

## 工作汇总（2026-08-24）

### 已完成

**effect 表达力 + MP 恢复 + 库注入通路**（2026-08-21 spec：`docs/superpowers/specs/2026-08-21-effect-expression-design.md`，plan 14 任务 T1-T14 全部完成，commit 10cf782→本次收口）：

- **effect 原子数组**（8 种类型）：库条目 `effect` 字段单 dict 升维为原子数组（旧格式自动包装兼容），damage/heal/mp_change/markup/buff/control/timed/narrative 战斗（cast 分支）/探索（execute_material）双侧结算；未知 type `[unknown:x]` 标识符降级永不空转、永不阻断；旧单 dict 数据零修改兼容
- **timed 软状态**：挂 `player.timed_effects`（`{id, description, expire_at}`），序列化 v2.2（旧档缺省 [] + 坏元素过滤），`advance_time` 推满时长自动清除（同 id 重复施放刷新不叠条），编年史 facts 玩家行渲染「生效中」块 Author/enrich 可见
- **MP 恢复**：每小时 1 点（分钟余数累计器攒满 60 回点，clamp MP_MAX），`mp_recovery_per_hour` 在 `data/game_config.json` 可配（0 关闭）；game_config 参数中心（get_game_config 缺省兜底+类型校验+缓存）
- **战斗 buff / control**：buff 挂 temporary_effects 受击减免（下限 `buff_damage_floor` 可配）+ 轮末 rounds 递减归零移除（3 处轮末 tick 调用点含 run_game CLI 路径）；control 写敌方 controlled_rounds 行动阶段跳过（轮末递减）
- **library/loader 统一加载**：`load_item_library/load_spell_library` core + extensions 目录扫描，game_loop 与 run_pipeline 双侧接入，修复管线 extensions 不可见断点（用户放 `data/library/extensions/{items,spells}/*.json` 即生效，游戏+模组管线双侧可见）
- **核心库升维示范**（纯 JSON）：石肤 buff+timed 双原子 / 支配 control / 帷幕 timed / 死灵书残页 @grant_spell / 盐袋 timed；UseParser/Catalog effect 元素级浅拷贝透传（防库单例别名污染）
- **文档**：readme 增「effect 原子系统」节（8 原子双侧语义表 + MP 恢复 + timed + 扩展库约定）+ spec 索引；MAINTENANCE 全程同步（含 T3 changelog 补录）

### 测试现状

- 默认套件：268 passed（基线 181（2026-08-19 统一资源层收口后）→ 268，计划期净增 87：test_use_system effect/timed/config 系 + test_combat_smoke buff/control/cast 系 + test_library_loader + test_game_config 防御 + e2e 确定性三场景等）
- e2e 确定性三场景（T13）：帷幕 timed 入档+过期 / 石肤战斗减伤 / 支配控制轮次，零 API 调用
- real_llm：S15 扩展法术游戏内施放（tmp extensions 注入 → UseParser 短路 → 扣 MP + timed 挂载 + 叙事宽断言）通过；S1-S15 15/15 首跑全过（含 S5/S9 等历史波动场景，本轮无 retry 消化）

### 已知观察（本期新增，非阻塞）

- loader 损坏扩展 JSON 报错缺文件名（Minor，T2 review 记录：`json.load` 异常不带来源路径，排障需逐文件试）；默认路径 cwd 独立性无回归测试
- frontend character.py 导出 version 覆写 "2.0" 与核心序列化 v2.2 漂移（pre-existing，前端按约定不排期）
- day:N time flag 随天数累积进 prompt/存档（T7 激活既有死代码暴露：advance_time 每次注入 runtime_state，无清理点，长期局 prompt 膨胀）
- timed 只进 Author prompt（编年史 facts），enrich/narrator 经 Author 产出间接感知（架构特性，同 known_spells 通路）
- 战斗轮叙事对被支配跳过渲染「未命中」不准（叙事层措辞问题，机制正确）；control 对快于玩家的敌人 rounds 有 off-by-one（spec 未规定先手，文档已注明）
- run_step1b_test.py 收集错误：用户删除 data/modules/深渊第七城/module_raw.txt 所致（pre-existing，非代码问题）
