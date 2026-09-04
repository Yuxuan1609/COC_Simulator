# 生成端回填专项设计（2026-09-04）

> 来源：2026-09-04 session 拍板。前置：簇评估 §10 缺口核对（schema 已加 vs prompt 未教 / 枚举漂移 / 样例模组脱节）。
> **核心原则（用户拍板）：以 schema 正确为核心。Prompt 修改从简——当前不做真实端到端生成验证，模组生成管线将来需要系统性升级，本次只保证「生成器有能力产出 schema 正确的数据」。**
> 修订：2026-09-04 plan review（`--strict` 只升 schema；中值进 game_config；environment 词表 quiet/noisy；`_assemble_l2` 透传 scene 级字段；F33 只收口 CLI）。

## 0. 范围与原则

- **做**：schema 修补、测试样例模组补全、prompt 最小回填、`_assemble_l2` 透传 scene_items/environment（让 STEP2A 产出能进 L2）、lint `--strict` 接 schema（F33 CLI 形态）、依赖图 mermaid 导出（F35 CLI）、`scheduled_events` 加载桥、消费端测试盘点补缺。
- **不做（明确缺口，需标注）**：真实端到端模组生成验证（费 API 且管线本身待系统升级）；STEP1A/1B/2B/2C/3A/3B/35 无缺口不动；F33 前端手写编辑器；F35 前端渲染（备注进 ISSUES §4，随前端专项）。
- **Prompt 从简约定**：每个 prompt 只加「字段存在 + 格式 + 何时用」的最小说明，不写长篇教学。等管线系统升级时再重写。
- 组织：方案 A 三阶段递进，TDD 逐阶段；commit 按 P1/P2/P3 各一，文档收口可另一次。
- 测试约定：生成端 = 契约 + 确定性（零 API）；改 prompt 后跑 `pytest -m real_llm_smoke`（该标记打的是对局主路径，**覆盖不到** `layered_parser`；仪式性收口，402 不阻塞）；默认收口 `pytest tests/ -q`。

## 1. P1 — Schema 修补 + 样例模组补全

### 1.1 Schema 修补（`src/module_designer/layered_schema.py`）

1. `L2_NPC_PROFILE_SCHEMA` 加 `attitude_value`（optional，int，-100~100）。
2. NPC 态度档位枚举统一为运行时五档 `hostile/wary/neutral/friendly/devoted`（修 STEP25 `allied` 漂移）；schema `values` 从 `game_config.npc_attitude_tiers[].key` 派生，禁止复制字面量。
3. 五档 ↔ 中值映射抽到 `game_config.npc_attitude_tiers[].mid`（hostile -75 / wary -30 / neutral 0 / friendly 30 / devoted 75），与现有 `max`/`key`/`label` 同行。`npc_manager._attitude_value_from_key` 读同一处，删除 `_ATTITUDE_MIDPOINTS`。
4. 核对 NPC profile 落盘字段：补 `scene` / `all_scenes` / `bound_interactions` / `bound_auto_triggers`（STEP25 中间名 `bound_entities` 由管线 pop 转换，schema 跟落盘）。
5. 嵌套校验：`scene_items`（kind∈item|weapon、ref、quantity、hidden）；`environment`（lighting∈dark|dim|normal，noise∈quiet|noisy）；顶层 `scheduled_events` 纳入 `validate_l2`。`_validate_value` 支持 min/max（warning 级）。未知字段仍静默（既有引擎行为，本期不改）。

### 1.2 测试样例模组补全（`data/modules/e2e_testbed/`）

现状：8 个新设计元素（scene_items / environment / attitude_min / attitude_value / scheduled_events / repeatable / player_goal / npc_dead）在样例模组中**全部缺失**，运行时测试靠内联构造。

补全清单（模组数据层可表达的全量设计元素）：
- L2 scene：`scene_items`（hidden + exposed 各一）、`environment`（两轴；可分场景各填一轴）
- NPC：`attitude_value`；interaction 挂 `attitude_min`
- 实体：`repeatable: true` 一例；AT 挂 `npc_dead:` requirement 一例
- 时间：`scheduled_events` 一例
- L3：`player_goal`；多结局 ending refs（≥2）
- 存量元素（防漂移必须锁）：boss_encounters / time_condition / scene_weapons / graded_result / 多场景移动

**不进 fixture**：`timed_effects` 是 markup 驱动的运行时玩家状态，模组 JSON 无对应字段，由既有 `tests/test_periodic_effects.py` 覆盖。

**样例约束**：
- `IT_END.difficulty` 改为 `"None"`（空串是现存 schema warning，会挡住 `--strict`）。
- 新增实体默认 **不进** `dependency_graph`（可选行动；实体可达只扫图内节点）。
- 技能名用「侦查」不是「侦察」。hidden 物品不要和第二把钥匙叙事撞车。
- `init_game` 当前不读 l2 `scheduled_events`（断链）——本期补加载桥。

**防漂移测试**：`tests/test_fixture_completeness.py` —— 维护「已设计元素清单」单一事实源，断言 e2e_testbed 每项有实例承载；将来新机制落地强制同步样例。

### 1.3 P1 测试

- 新 `tests/test_generation_schema.py`（确定性）：attitude_value 边界、非法档位、五档中值单一事实源、validate_l2 对新字段通过、environment 非法轴值、scene_items kind。
- `test_fixture_completeness.py` 见 1.2。
- `test_scheduled_events.py`：`init_game` 从 l2 顶层键加载到 `keeper.world.scheduled_events`。

## 2. P2 — Prompt 最小回填

| Prompt | 最小改动 |
|---|---|
| STEP2A | `scene_items`/`environment` 字段说明 + **写在每个 scene 的 `scene_movements` 对象内**；difficulty 语义一句（hard=半数/extreme=1/5）；repeatable 何时标 true 一句。词表：lighting∈dark\|dim\|normal，noise∈quiet\|noisy（**不是** normal） |
| STEP4 | markup 词表加 `@attitude_change(npc_name, delta)` / `@env_change(axis, value)`（轴值枚举同上）各一条；`npc_dead:` requirement 语法一句；F8 模式一句（读典籍/目击神话挂 `@stat_change(克苏鲁神话,+N)`） |
| STEP25 | 输出格式加 `attitude_value`；枚举 allied→devoted；档位中值从 `game_config.npc_attitude_tiers[].mid` 派生写入 prompt，禁止第三份字面量 |

**组装透传**（P2 附带，非管线系统升级）：`_assemble_l2` 把 `scene_movements[scene].scene_items` / `.environment` 拷到 L2 scene。缺省行为不变。

**测试**（确定性，零 API）：
- 每个被改 prompt 断言「必含新字段关键词」（防回退）。
- `_assemble_l2` 透传锁测。
- 收口跑 `pytest -m real_llm_smoke`（对局主路径仪式性；402 不阻塞）。

**明确缺口标注**：本次不做真实端到端生成验证（prompt 效果未实测），写入 ISSUES §4。

## 3. P3 — 工具

### 3.1 F33 lint 接 schema 校验（CLI 形态）

`run_lint` 已调用 `validate_all`。schema 问题默认 warning 不挡 exit。`--strict` **只把 `validate_all` 的 schema warning 升为 error**（计入 n_error、影响退出码）。可达性 / 孤立场景 / 实体不可达等 lint warning **保持 warning**，strict 下也不挡。

测试：错枚举默认 exit 0；`--strict` exit 1；e2e_testbed `--strict` exit 0（允许图 warning，不允许 schema error）。

ISSUES：只收口「CLI 接 schema」；§2 F33 手写模组/前端编辑器仍在。

### 3.2 F35 依赖图 mermaid 导出

`DependencyGraph.to_mermaid()`；CLI 走 `python -m module_designer.lint <dir> --graph`（`module_designer/__main__.py` 同步）。结局节点 `classDef`/`class` 高亮；环用已有 `detect_cycles()` 以 `%% 环:` 注释标注。不另写 DFS。

测试：小图 → 节点/边/`classDef`；环图含「环」。前端渲染留 ISSUES §4。

## 4. 贯穿：消费端测试盘点补缺

对照近期落地清单逐一核 tests/ 覆盖：F5/F8/F10/F14/F17/F18/F19/F23/F25/F27/F29/F31/F32、B20/B21、N1/N3/N4、LLM fallback。

初查：大部分已有专测文件。疑似缺口（盘点时确认）：
- **存档 round-trip 覆盖新字段**：scene_items / environment / attitude_value / insanity / scheduled_events / repeatable completed 集（只补实际缺的）。
- **run_game.py 交互路径**（非 game_loop harness）覆盖薄弱处。
- 盘点产出缺口清单，顺手补；补完可加载 e2e_testbed 样例（含 scheduled_events 桥）。

## 5. 收尾

- 簇评估 §10 回写：schema 已修 / prompt 最小回填 / 样例模组补全 / **真实生成验证未做（管线待系统升级）**；措辞修正（N1 schema 拆分、F19 锚 L2、P0-1/F8 由「应」改实态）；中值单一事实源；scheduled_events 加载桥。
- ISSUES：F33 **仅 CLI schema** 备注进 §5（§2 手写/前端编辑器保留）；F35 CLI mermaid 进 §5，前端留 §4；§4 追加 prompt 未实测缺口。
- MAINTENANCE.md 同步。
- commit 分 P1 / P2 / P3；文档收口可 P4。

## 6. 验收标准

1. `pytest tests/ -q` 全绿（含新增 schema/fixture/lint/graph 测试）。
2. P2 后 `pytest -m real_llm_smoke` 跑过或记录 402（不阻塞）。
3. e2e_testbed 通过 `run_lint --strict` **零 schema error**（图 warning 允许）。
4. `test_fixture_completeness` 覆盖清单 = 本 spec §1.2（不含 timed_effects；含存量元素）。
5. ISSUES/§10/MAINTENANCE 三处文档回写一致；F33 未把前端手写路径整项关掉。
