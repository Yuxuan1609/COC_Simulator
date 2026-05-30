# UPDATES — 待修改内容细节

> 本文档记录需要修改但暂未实施的内容，作为 TODO 的详细补充。完成一项删一项。

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
