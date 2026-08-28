# R1 Keeper 回合管线阶段化 — 执行记录

**日期**: 2026-08-28
**分支**: `feat/keeper-turn-pipeline` → 已合入 `main`（fast-forward `e536bfd..d708f91`）
**Spec**: `docs/superpowers/specs/2026-08-28-keeper-turn-pipeline-design.md`
**Plan**: `docs/superpowers/plans/2026-08-28-keeper-turn-pipeline.md`

对照 spec 各节落地情况。W0–W5 纯搬运；W6 唯一行为变更；W7 收口。

---

## §0 目标 / 非目标

| Spec 目标 | 结果 |
|---|---|
| `process_turn` ~850 行拆为 5 宏阶段 + TurnRunner | 做到。`Keeper.process_turn` 薄 facade → `TurnRunner.execute` → A–E |
| keeper.py 1702 → ~700 | **855**（facade + toolbox 仍驻本文件；未靠删 toolbox 压行） |
| 早退 / 重入 / 冻结三种去向 + 异常 | `Early` / `Restart` / 正常 `None`；`TurnFrozenError` 冒泡到 runner 转 FROZEN |
| C 立 `EncounterProvider` 有序链 | `EnemyCombatProvider` → `SceneBossProvider`；无注册表/装饰器 |
| 跨回合态收拢为 session_state 分组 | `__init__` 注释组 8 字段；**不是** `Keeper.session_state` 容器（计划：只加注释、不改字段名） |

非目标均守住：未动 `game_loop` / `combat.py` / `scenario_core.py`；未重设计回合协议；TurnMonitor retry 壳不动。

---

## §1 契约

落地类型在 `src/game/turn/context.py`：

- `TurnContext`：turn_input / raw（pre_parse 可改写）/ author / depth
- `TurnAccumulator`：parse/outcomes/enrich/combat/standoff/`boss_accounting`/`detect_future` 等
- `Early(TurnResult)`、`Restart`

相对 spec 草图的取舍（以计划为准）：

- 未实现 `Continue(payload)`；阶段返回 `Early | Restart | None`，产出直接写 `acc`
- pending_side_effects / pending_move **不进 acc**，仍在 Keeper 会话/回合态，阶段经 `tools.` 访问
- `boss_accounting` 由 C 记载荷、E 在 curate 成功后消费（freeze 安全，§4.1）

---

## §2 五宏阶段 DAG

| 阶段 | 文件 | 行数 | 内容 |
|---|---|---|---|
| A 理解 | `understand.py` `phase_a_understand` | 207 | 守卫 → LUCK → parse → NPC → use 归一 → intent 预发射；早退 `Early` |
| B 裁决 | `adjudicate.py` `phase_b_adjudicate` | 293 | judge 循环 + 依赖自动触发 + **作者门**（W6 迁入） |
| C 遭遇 | `encounter.py` `phase_c_encounter` | 230 | provider 链 + 吞对峙① |
| D 充实 | `enrich.py` `phase_d_enrich` | 98 | enrich∥TA → advance_time → ending① → 时压 |
| E 收尾 | `finalize.py` `phase_e_finalize` | 131 | 落账 → ending② → event Boss → 吞对峙② → curate → Boss 记账 → assemble |

编排器 `runner.py` 41 行（spec 估 ~100），循环结构与 spec 草图同构：`Early` 直接返回；`Restart` 先 `_apply_pending` 再 `depth+=1` 重入；`depth>=MAX` → `_process_deterministic_only`；`TurnFrozenError` 统一 `_build_frozen_response`。

`process_turn` 签名保留；`complete_combat_turn` / `resolve_standoff` 未改。

---

## §3 EncounterProvider

- Protocol + `EncounterContribution`；链上两个 provider，event 型 Boss **仍在 E**（迟发钩子，未挪进 C）
- NPC ally 未加（等 F28）

实现差：`SceneBossProvider.probe` 会就地写 `acc.combat_init_result` / `acc.boss_accounting`，再填 contribution；`phase_c` 再合并一次。两 provider 时语义等价，插件单出口略漏。

---

## §4 唯一有意变更（W6）

作者门从 enrich 之后迁到 B 尾部；递归 `process_turn(_depth+1)` 改为 Restart 循环。

| Spec 锁定 | 测试 |
|---|---|
| 递归时时间只走一格 | `TestAuthorRecursion.test_recursion_advances_time_once` |
| 被弃帧零世界副作用（enter_combat / boss 记账） | **未单测**；由「enrich 只跑一次」代理（Restart 在 B 尾、C 之前，结构上 C 不跑被弃帧） |
| 作者拒绝信息进 outcomes | `test_author_rejection_outcome_present` |
| MAX 守卫 → deterministic-only | `test_escalation_depth_guard` |

已知微差按 spec 保留：拒绝 outcome 现会进 combat-entry prompt 与 enrich 输入。

TDD 红绿（生产改动前）：时间双涨 120 vs 60、enrich 2 vs 1 两条红；拒绝 / 深度守卫两条绿。改后 4 绿。

---

## §5 文件排布

```
src/game/turn/
  __init__.py
  context.py       # 49
  runner.py        # 41
  understand.py    # A 207
  adjudicate.py    # B 293
  encounter.py     # C 230
  enrich.py        # D 98
  finalize.py      # E 131
src/game/agents/keeper.py   # 855，facade + toolbox
```

---

## §6 波次

| 波 | Commit | 验收 |
|---|---|---|
| W0 | `f3b71f8` 骨架 + 委托壳 | 341 passed |
| W1 | `df02882` A 理解 | 341 |
| W2 | `61301b3` B 裁决 | 341 |
| W3 | `7fc9804` C 遭遇 + provider | 341 |
| W4 | `48cbd5b` D 充实 | 341 |
| W5 | `a44fefc` E 收尾 | 341 |
| W6 | `edf7253` 作者门 + Restart | 345（+4）+ P0 6 |
| W7 | `d708f91` session_state + ISSUES R1 收口 | 345 |

ISSUES：R1 从 §3 移入 §5；combat.py / scenario_core.py 拆分另排；R2/R3 仍开。

---

## §7 风险（实际）

- 局部变量归属：每波 `pytest tests/ -q` 全绿，未发现错槽
- event Boss 未进 C（W3 纪律守住）
- W6 递归：新增 4 测 + 既有 `TestAuthorRecursionPreservesPending`（该测因 `has_substantive` 现打不到 Restart，完成帧 E 落账仍绿）

已知不修：`test_unresolved_use_becomes_creative` / `test_combat_phase_trigger` 偶发 flaky，复跑即过。

---

## 测试

- 默认套件：`345 passed, 20 deselected`
- 已知 flaky 按项目约定不修

## 后续（非 R1）

- B1 存档：以 session_state 注释组 8 字段为入档单元；另评估 `_last_comms_time`
- 补一条被弃帧 `enter_combat` / boss 未记账的直接断言（spec §4 原文比 enrich 次数代理更硬）
- combat.py / scenario_core.py 拆分另排
