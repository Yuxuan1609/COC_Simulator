# Keeper 回合管线阶段化（R1）设计

> 2026-08-28 与用户讨论拍板。来源：roadmap Step2 第 2 项（docs/superpowers/specs/2026-08-26-remaining-issues-roadmap-design.md §2）。
> 2026-05-30 turnrunner-keeper-split spec 的继任：诊断沿用（god function + 三层混叠），方案不照抄——那份 spec 死于顺手重设计回合协议，本设计除 §4 一处外行为逐字节等价。

## 0. 目标 / 非目标

**目标**

- `process_turn`（keeper.py:149–999，~850 行）拆为 5 个宏阶段 + 薄编排器 TurnRunner
- keeper.py 1702 → ~700 行（facade + toolbox）
- 阶段间 typed 契约；早退 / 重入 / 冻结统一为三种去向 + 一个异常
- C 遭遇阶段立 `EncounterProvider` 接口（plugin 形态），为 C 簇 F28 友方 NPC 参战 / F29 死亡连锁铺接入点
- Keeper 跨回合会话态显式收拢为 `session_state` 分组（给 B1 存档设计铺路）

**非目标**

- 不动 game_loop（narrator/snapshot 边界已清晰）、combat.py、scenario_core.py（后两者拆分另行排期）
- 不引入注册表 / 装饰器 / 中间件框架（R2 域）；provider 链就是有序 list
- 不重设计回合协议；TurnMonitor 维持 retry 壳不动

## 1. 契约

每个阶段只可能返回三种去向之一；freeze 是基础设施异常，不建模进返回值：

```python
Continue(payload)   # 正常：带本阶段产出，编排器并入 acc
Early(TurnResult)   # 早退：offer/拾取/消歧/纯对话/冻结，编排器直接返回
Restart             # 重入：Author 接受 → 落账后从 A 重跑（循环，非递归调用）
# TurnFrozenError   # parse/curate 抛出，冒泡到编排器统一转 Early(FROZEN)
```

数据对象（`src/game/turn/context.py`）：

| 类型 | 内容 | 性质 |
|---|---|---|
| `TurnContext` | turn_input / raw（pre_parse 可改写）/ author / depth | 输入侧，只读 |
| `TurnAccumulator` | all_outcomes / enrich_input / pending_side_effects / pending_move / combat_init / standoff / ending / brief / detect_future | 产出侧累积（= 现 process_turn 局部变量显式分组） |

- 跨阶段槽：`detect_future`（A 发射 / B 收割，全程唯一终态槽）；`boss_pending_accounting` 仅存在于 W3–W5 过渡期（记账仍延后时的 C→E 传递），W6 记账提前后删除
- `world` 共享可变，不进契约
- 跨回合会话态不进契约，收拢为 `Keeper.session_state`：weapon_offer / standoff_pending / npc_injected_at_ids / combat_result_pending / last_outcomes / last_player_input / recent_intents

## 2. 五宏阶段 DAG

```
A 理解   守卫(offer是/否→Early · 直接拾取→Early · 深度守卫) → LUCK
         → parse(UseParser短路/move/search/pre_parse消歧→Early(SUSPENDED)/LLM parse)
         → NPC对话(纯对话→Early) → use归一 → intent发射(future挂acc)
B 裁决   judge循环(interaction/event/use/move/search/other) → 依赖图自动触发
         → intent收割 → 作者门(接受─Restart / 拒绝─outcome继续)
C 遭遇   EncounterProvider有序链 [EnemyCombat → SceneBoss]
         → 即时记账(register/add_to_combat/set_active/mark_spawned) → 吞对峙
D 充实   enrich ∥ TA(execute_parallel) → advance_time → ending扫描① → 时压通信
E 收尾   落账(pending side effects + move) → ending扫描② → warnings
         → event型Boss(迟发钩子) → 吞对峙② → curate → assemble → TurnResult
```

编排器示意（`runner.py`，~100 行；真实签名以实施计划为准）：

```python
def execute_turn(self, ctx, tools) -> TurnResult:
    depth = 0
    while True:
        acc = TurnAccumulator()
        for phase in (A, B, C, D, E):
            try:
                r = phase(ctx, acc, tools)
            except TurnFrozenError as e:
                return tools.frozen_response(e, acc)
            if isinstance(r, Early):
                return r.result
            if isinstance(r, Restart):
                tools.apply_pending(acc)   # 保持现语义：重入前落账
                break
        else:
            return acc.result              # E 已完成 assemble
        depth += 1
        if depth >= MAX_ESCALATION_DEPTH:
            return tools.deterministic_only(ctx)
```

## 3. EncounterProvider 接口

```python
class EncounterProvider(Protocol):
    def probe(self, ctx, acc, tools) -> EncounterContribution | None: ...

@dataclass
class EncounterContribution:
    combat_init: CombatInit | None = None     # 多个 provider 可合并
    standoff: dict | None = None
    outcomes: list[ActionOutcome] = field(default_factory=list)
    enrich_entities: list[dict] = field(default_factory=list)
```

- R1 链上两个 provider：`EnemyCombatProvider`（敌人上下文 → LLM 判定 → 对峙/CombatInit）、`SceneBossProvider`（at/interaction 检查 + 即时记账）
- event 型 Boss 保留为 E 的「迟发钩子」：同一接口、不同执行点。原因：它现在跑在 enrich 之后（keeper.py:891），挪进 C 会改变 enrich 输入——属行为变更，留 Step3 C 簇收编（带测试）
- NPC ally provider 随 F28 落地时再新增

## 4. 唯一有意的行为变更（W6 波）

作者门从 enrich 之后（keeper.py:815）迁到 B 尾部。连锁效果：

1. **Boss 记账提前到 C**：现记账延后到返回前（keeper.py:975–983）的唯一理由是防作者门递归吞账；迁移后走到 C 的帧必然发货，延后理由消失，acc 的 boss_pending_accounting 槽删除
2. **修复递归暗伤①**：`advance_time` 双涨（外帧 keeper.py:781 + 内帧重跑，同一玩家动作时间走两格）
3. **修复递归暗伤②**：`enemies.enter_combat`（keeper.py:648）在被弃帧里改了世界态
4. 附带收益：递归路径不再白跑 combat-entry LLM / enrich / TA
5. 已知微小差异：作者拒绝的 outcome 现在会进 combat-entry prompt 的 outcomes_summary 和 enrich 输入（原先 enrich 已消费完，keeper.py:869 的 enrich_input 追加是死写）

普通路径（无 creative other / 无 author / author 拒绝）逐字节等价。

W6 新测试锁定递归语义：

- 递归时时间只走一格
- 被弃帧零世界副作用（enter_combat 未发生、boss 未记账）
- author 拒绝信息出现在 outcomes
- MAX_ESCALATION_DEPTH 守卫不变（超限 → deterministic only）

## 5. 文件排布

```
src/game/turn/
  __init__.py
  context.py       # TurnContext / TurnAccumulator / Continue / Early / Restart / 各阶段产出 ~200 行
  runner.py        # TurnRunner ~100 行
  understand.py    # A
  adjudicate.py    # B
  encounter.py     # C + EncounterProvider
  enrich.py        # D
  finalize.py      # E
```

Keeper（~700 行）= facade + toolbox：

- `process_turn` 签名保留，内部委托 runner；`complete_combat_turn` / `resolve_standoff` 不动——测试与 game_loop 零改动
- toolbox：_parse / _enrich / _run_time_agent / _inject_npc_at / _apply_pending / _grant_scene_weapons / _detect_direct_pickup / _devour_standoff_for_boss / _check_boss_requirements / _evaluate_boss_soft_condition / _integrate_supplement / _integrate_patch / _load_scene_into_graph / _build_world_brief / _build_world_snapshot / _build_scene_context_for_author / _infer_time_category / _process_deterministic_only / _build_frozen_response / _scan_ending
- TurnMonitor 经 tools 暴露给阶段

## 6. 迁移波次

| 波 | 内容 | 性质 | 验收 |
|---|---|---|---|
| W0 | turn/ 骨架 + process_turn 整体委托为单块 | 纯搬运 | `pytest tests/ -q` 全绿 |
| W1 | A 理解 | 纯搬运，Early 契约立住 | 同上 |
| W2 | B 裁决（judge + 依赖触发；作者门暂留原位） | 纯搬运 | 同上 |
| W3 | C 遭遇（provider 化，记账仍延后） | 纯搬运，接口落地 | 同上 |
| W4 | D 充实 | 纯搬运 | 同上 |
| W5 | E 收尾 | 纯搬运 | 同上 |
| W6 | 作者门迁 B 尾 + Boss 记账提前 + Restart 循环化 + 递归语义新测试 | **唯一变更波** | 全绿 + 新测试 |
| W7 | facade 定型 + MAINTENANCE/ISSUES 收口 | 文档 | 全量回归 |

W1–W5 任一波出问题都是纯搬运错误，好定位；行为变更全部隔离在 W6，diff 小、审查集中。

## 7. 风险与对策

- 局部变量归属错（该进 acc 的留成阶段私有）→ 小步波次 + 每波全绿
- W3 provider 化时顺手把 event boss 挪进 C → 纪律：W3 零行为变更
- W6 递归语义改动波及 escalation 测试 → 动手前先盘点 tests 里 recursion/escalation 覆盖
- 契约新增 ~200 行类型，总行数略涨——显式化的代价，非膨胀
