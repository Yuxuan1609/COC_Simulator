# 生成端回填专项设计（2026-09-04）

> 来源：2026-09-04 session 拍板。前置：簇评估 §10 缺口核对（schema 已加 vs prompt 未教 / 枚举漂移 / 样例模组脱节）。
> **核心原则（用户拍板）：以 schema 正确为核心。Prompt 修改从简——当前不做真实端到端生成验证，模组生成管线将来需要系统性升级，本次只保证「生成器有能力产出 schema 正确的数据」。**

## 0. 范围与原则

- **做**：schema 修补、测试样例模组补全、prompt 最小回填、lint 接 schema 校验（F33）、依赖图 mermaid 导出（F35）、消费端测试盘点补缺。
- **不做（明确缺口，需标注）**：真实端到端模组生成验证（费 API 且管线本身待系统升级）；STEP1A/1B/2B/2C/3A/3B/35 无缺口不动；前端渲染（F35 前端化备注进 ISSUES §4，随前端专项）。
- **Prompt 从简约定**：每个 prompt 只加「字段存在 + 格式 + 何时用」的最小说明，不写长篇教学。等管线系统升级时再重写。
- 组织：方案 A 三阶段递进，TDD 逐阶段；commit 按 P1/P2/P3 各一。
- 测试约定：生成端 = 契约 + 确定性（零 API）；改 prompt 主路径后跑 `pytest -m real_llm_smoke`；默认收口 `pytest tests/ -q`。

## 1. P1 — Schema 修补 + 样例模组补全

### 1.1 Schema 修补（`src/module_designer/layered_schema.py`）

1. `L2_NPC_PROFILE_SCHEMA` 加 `attitude_value`（optional，int，-100~100）。
2. NPC 态度档位枚举统一为运行时五档 `hostile/wary/neutral/friendly/devoted`（修 STEP25 `allied` 漂移）；schema 加 values 约束。
3. 五档 ↔ 中值映射（hostile -75 / wary -30 / neutral 0 / friendly 30 / devoted 75）抽为单一事实源常量，运行时 npc_manager 引用同一处（消灭双定义）。
4. 核对 NPC profile 是否缺运行时已有字段（如 `bound_entities`），缺则补。

### 1.2 测试样例模组补全（`data/modules/e2e_testbed/`）

现状：8 个新设计元素（scene_items / environment / attitude_min / attitude_value / scheduled_events / repeatable / player_goal / npc_dead）在样例模组中**全部缺失**，运行时测试靠内联构造。

补全清单（模组数据层可表达的全量设计元素）：
- L2 scene：`scene_items`（hidden + exposed 各一）、`environment`（两轴）
- NPC：`attitude_value`；interaction 挂 `attitude_min`
- 实体：`repeatable: true` 一例；AT 挂 `npc_dead:` requirement 一例
- 时间：`scheduled_events` 一例；`timed_effects` interval+payload 一例
- L3：`player_goal`；多结局 ending refs
- 存量元素盘点核对：boss_encounters / time_condition / scene_weapons / graded_result / 多场景移动，缺则补

**防漂移测试**：`tests/test_fixture_completeness.py` —— 维护「已设计元素清单」单一事实源，断言 e2e_testbed 每项有实例承载；将来新机制落地强制同步样例。

### 1.3 P1 测试

- 新 `tests/test_generation_schema.py`（确定性）：attitude_value 边界、非法档位报错、五档中值映射、validate_l2 对新字段通过。
- `test_fixture_completeness.py` 见 1.2。

## 2. P2 — Prompt 最小回填

| Prompt | 最小改动 |
|---|---|
| STEP2A | `scene_items`/`environment` 字段说明 + 输出示例各一行；difficulty 语义一句（hard=半值/extreme=1/5，P0-1 已生效）；repeatable 何时标 true 一句 |
| STEP4 | markup 词表加 `@attitude_change(npc_name, delta)` / `@env_change(...)` 各一条；`npc_dead:` requirement 语法一句；F8 模式一句（读典籍/目击神话挂 `@stat_change(克苏鲁神话,+N)`） |
| STEP25 | 输出格式加 `attitude_value`（数值，与档位一致）；枚举 allied→devoted |

**测试**（确定性，零 API）：
- 每个被改 prompt 的 builder 断言「必含新字段关键词」（防回退）。
- 收口跑 `pytest -m real_llm_smoke`（prompt 主路径改动）。

**明确缺口标注**：本次不做真实端到端生成验证（prompt 效果未实测），写入 ISSUES §4「模组生成管线影响清单」条目：「prompt 最小回填未做真实生成验证，待管线系统升级时一并重验」。

## 3. P3 — 工具

### 3.1 F33 lint 接 schema 校验

`lint.py` 的 `run_lint` 在现有 cross_validate 基础上调用 `validate_all`（layered_schema 全字段校验）；schema 问题默认 warning 级不挡 exit code（手写模组宽容），`--strict` 升 error 影响退出码。
测试：构造缺字段/错枚举模组 JSON，断言报告内容与 exit code。

### 3.2 F35 依赖图 mermaid 导出

`dependency_graph.py` 加 `to_mermaid()`；CLI `python -m module_designer.graph <module_dir>`（或 lint 子命令，实现时择一）输出 mermaid 文本：实体节点按类型着色、结局节点高亮、环检测标注。
测试：小图 → mermaid 字符串断言（节点/边/结局高亮）。
前端渲染备注进 ISSUES §4（随前端专项）。

## 4. 贯穿：消费端测试盘点补缺

对照近期落地清单逐一核 tests/ 覆盖：F5/F8/F10/F14/F17/F18/F19/F23/F25/F27/F29/F31/F32、B20/B21、N1/N3/N4、LLM fallback。

初查：大部分已有专测文件。疑似缺口（盘点时确认）：
- **存档 round-trip 覆盖新字段**：scene_items / environment / attitude_value / insanity / scheduled_events / repeatable completed 集入档后 load 回来是否齐（test_save_load.py 扩）。
- **run_game.py 交互路径**（非 game_loop harness）覆盖薄弱处。
- 盘点产出缺口清单，顺手补；补完直接可加载 e2e_testbed 样例（1.2 的收益）。

## 5. 收尾

- 簇评估 §10 回写：schema 已修 / prompt 最小回填 / 样例模组补全 / **真实生成验证未做（管线待系统升级）**；措辞修正（N1 schema 拆分、F19 锚 L2、P0-1/F8 由「应」改实态）。
- ISSUES §5 滚动收口 F33/F35；§4 备注 F35 前端化、prompt 未实测缺口。
- MAINTENANCE.md 同步（新函数/文件/行号）。
- commit 分 P1 / P2 / P3 三次；文档随对应阶段提交。

## 6. 验收标准

1. `pytest tests/ -q` 全绿（含新增 schema/fixture/lint/graph 测试）。
2. P2 后 `pytest -m real_llm_smoke` 通过。
3. e2e_testbed 通过 `run_lint --strict` 零 error（自证 schema 正确）。
4. `test_fixture_completeness` 覆盖清单 = 本 spec §1.2 全项。
5. ISSUES/§10/MAINTENANCE 三处文档回写一致。
