# UPDATES — 待修改内容细节

> 本文档记录需要修改但暂未实施的内容，作为 TODO 的详细补充。完成一项删一项。

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
