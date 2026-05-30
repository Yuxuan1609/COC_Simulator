# UPDATES — 待修改内容细节

> 本文档记录需要修改但暂未实施的内容，作为 TODO 的详细补充。完成一项删一项。

---

## Boss/Enemy 管理统一化

- **现状**：EnemyInstance 有两个创建入口——`EnemyManager.spawn()`（普通敌人）和 `BossManager.build_combat_init()`（Boss）。两条路径各自维护字段完整性，已导致 flags 字段在 spawn 路径丢失。
- **目标**：两者共享 `EnemyManager.create_instance(lib_data, scene, quantity)` 唯一入口，Boss 特殊性通过 `flags=["boss"]` 标记表达而非分离 API。
- **涉及文件**：`src/game/enemy_manager.py`、`src/game/boss_manager.py`、`src/game/agents/keeper.py`（Boss trigger 代码路径）
- **约束**：Boss 不应走 `spawn()` 方法（不可通过 `/spawn enemy` 命令批量生成），需通过属性标记区分。
- **参考**：DEBUG_JOURNAL.md #64, LEARNING_JOURNAL "同类子系统的双轨制是 Bug 温床"

## EnemyManager.spawn() flags 字段补传

- **现状**：`LibraryEnemy.from_dict()` 正确从 `combat_behavior` 文本解析 `[avoidable]`/`[adjacent_aware]` 等 tag 到 `flags` 列表，但 `EnemyManager.spawn()` 构造 `EnemyInstance` 时未拷贝 `flags`。
- **影响**：`avoidable` 不触发对峙，`adjacent_aware` 不跨场景感知。
- **修复**：`spawn()` 中 `hp=base_hp` 后加 `inst.flags = list(getattr(lib_enemy, 'flags', []))`
- **涉及文件**：`src/game/enemy_manager.py:78`
- **注意**：此项与上方"管理统一化"关联——统一入口后自然修复。
- **参考**：DEBUG_JOURNAL.md #64

## 输出流信息规范化

- **现状**：当前数据流分两路——raw ActionOutcome 进 Curator → Narrator，enrich_input 进 Enrich LLM → Narrator。Narrator 同时接触 raw outcomes 和 enriched text。
- **目标**：所有结果先过 Enrich，Narrator 只读 Enrich 产出 + 场景信息，不接触原始 ActionOutcome。
- **涉及文件**：`src/game/agents/keeper.py`（enrich 覆盖）、`src/game/curator.py`（移除 raw outcomes 依赖）、`src/prompts.py`（Narrator prompt 调整）

## 战斗总结生成（前端交互路径）

- **现状**：前端交互战斗走 `run_single_round()` 逐轮执行，不调用 `run_combat()`，导致 `_generate_combat_narrative()`（LLM 战斗总结）永不执行。仅 `continue_standoff` 路径生成战斗总结。
- **目标**：前端 combat 结束（`result.finished=True`）时调用 LLM 生成战斗总结，并回传给 enrich/narrator 管线。
- **涉及文件**：`frontend/routers/game.py`（combat_round 结束处理）、`src/game/combat.py`

## flags 标签系统审计（已审计，待修复）

| 标签 | 定义源 | 消费者 | 状态 |
|------|--------|--------|------|
| `avoidable` | enemies.json (深潜者) | keeper.py 对峙流程 | **失效**（spawn 未传 flags） |
| `adjacent_aware` | enemies.json (Clicker) | enemy_manager.py 跨场景感知 | **失效**（spawn 未传 flags） |
| `guardian` | enemies.json (石卫) | 无消费代码 | 死数据 |
| `boss` | bosses.json (全部 Boss) | combat.py Boss 战斗路由 | **正常** |
