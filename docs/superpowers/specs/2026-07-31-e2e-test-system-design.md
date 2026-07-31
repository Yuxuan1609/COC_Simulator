# 分层 E2E 测试体系设计

> 2026-07-31 | 状态：已批准
>
> 目的：为即将到来的重构（resolver 注册表 / B5 战斗契约 / C1 process_turn 拆分）与存读档修复提供回归安全网（主），兼顾 LLM 行为质量评估（次）。

## 背景

- TurnResult/PlayerTurnResult 契约迁移已完成（main @ d2e4fdd），单测层有 `test_turn_result_contract.py`（23）、`test_p0_pipeline_fixes.py`（6）、`test_frontend_contract.py`（1）。
- 真实 LLM 资产现状：`test_escalation_real.py`（5 case，基建已修，脚本模式 5/5；C/E 依赖 Author 升级决策有真实波动）、`test_harness_parallel.py` / `test_harness_stability.py`（脚本式 case 体系）、`llm_player.py`（LLM 自主玩家整局游玩 + 日志）。
- 已确认原则：**回归确定性由场景层保底，有机覆盖由巡检层补充**；契约结构 = 硬断言，LLM 内容 = 宽断言 + retry。

## 总体结构：三步走

| 步骤 | 内容 | LLM | 运行方式 |
|------|------|-----|---------|
| 1 | 确定性 E2E 补齐 | stub（零 API） | 默认 pytest 套件 |
| 2 | 手写固定输入 9 场景 | 真实 API | `real_llm` marker，on-demand |
| 3 | 巡检层 + 场景化 llm_player | 真实 API | 独立 runner，on-demand |

步骤 3 的提示词指引不在本设计范围，另行讨论；本设计只定义其接口与审计器骨架。

## 目录布局

统一收进 `tests/e2e/`：

```
tests/e2e/
  __init__.py
  helpers.py               # 三步共用基建
  conftest.py              # real_llm marker 注册 + 共享 fixture
  test_deterministic.py    # 步骤 1
  test_scenarios.py        # 步骤 2
  test_escalation_real.py  # 从 tests/ 迁入（仅调整 sys.path 引用与输出路径）
  scenarios/               # 步骤 3 场景定义目录（本计划只建空目录 + README 说明格式）
```

`tests/test_escalation_real.py` 迁移时保持脚本模式（`python tests/e2e/test_escalation_real.py A`）与 pytest 模式均可用。

### helpers.py 内容

- `load_env()`：`load_dotenv` 封装（real_llm 测试用）
- world 工厂：复用 escalation 的 `_make_world` 模式，参数化场景/敌人/武器种子
- `stub_keeper_llm(keeper, monkeypatch, parse_results=...)`：从 `test_turn_result_contract.py` 的 `_stub_llm` 提取并泛化（可配置 parse 序列、enrich/time_agent/combat_entry 响应）
- `assert_turn_contract(result)`：PlayerTurnResult/TurnResult 结构审计——必填字段类型、status 与 pending_interaction 一致性、diagnostics 结构、不变量（SUSPENDED 无 brief 等）
- `setup_llm_logging(log_dir)`：从 escalation 提取的 logging wrapper（已修好的 `**extra` 版），步骤 2 复用

## 步骤 1：确定性 E2E 补齐

**定义**：stub 掉全部 LLM 调用，用真实 `ScenarioWorld` + `Keeper` + `run_turn` 跑多回合循环，断言行为与契约。

**现状已有**（test_turn_result_contract.py，并入 e2e 或保留原位均可——保留原位，helpers 反向 import）：
ambiguous→SUSPENDED、正常回合、非法移动、standoff 播种与清理、continue_standoff、weapon_offer pending、run_turn SUSPENDED/dispatch/FROZEN 日志。

**新增缺口**（全部经 `run_turn` 闭环，非仅 process_turn）：

1. **offer 应答闭环**：搜索发现武器 → pending(weapon_offer) → 下回合输入"是" → `world.player` 武器入包、场景武器移除
2. **clarify 应答闭环**：模糊输入 → SUSPENDED → 澄清输入经 run_turn 正常推进（验证 pre_parse resolved_text 路径）
3. **战斗闭环**：hostile 敌人遭遇 → combat_init → 调用方结算 → `complete_combat_turn` → brief 含战斗 outcome（direct-hostile 路径，补 standoff 路径已有测试之外的覆盖）
4. **合法移动**：有效目标 → `world.current_location` 变更 + 场景描述更新
5. **结局触发**：构造结局条件满足 → `EndingInfo` → run_turn `game_over=True`
6. **NPC 纯对话回合**：NPC 在场 + 对话输入 → COMPLETED text 路径 + npc_events
7. **多回合状态序列**：串联 3-4 个上述回合，验证回合间状态——`turn_number` 递增、时钟推进（stub time_agent 返回 time_delta）、`_standoff_pending`/`_weapon_offer` 不跨回合泄漏

**验收**：默认套件（`pytest tests/ --deselect real_llm`）全绿、零 API 调用（可用 `python -m pytest tests/e2e/test_deterministic.py` 单独验证）。

## 步骤 2：手写固定输入 9 场景（真实 LLM）

**文件**：`tests/e2e/test_scenarios.py`，全部打 `@pytest.mark.real_llm`，conftest 默认 deselect。

**场景清单**（Q3 已确认 1-6 + 9；7/8 视预算实现时评估）：

| # | 场景 | 硬断言 | 软/宽断言 |
|---|------|--------|----------|
| S1 | 普通行动回合 | 契约结构、status=COMPLETED、brief 非空 | narrative 非空、长度下限 |
| S2 | 模糊输入澄清 | status=SUSPENDED、pending.kind=clarify；澄清后回合推进 | — |
| S3 | 搜索→武器 offer→拾取 | pending.kind=weapon_offer；"是"后武器入包 | — |
| S4 | standoff 回避 | pending.kind=standoff；回避输入后未进战斗 | — |
| S5 | standoff 转战斗 | 敌对输入后 combat_init 或战斗已结算 | — |
| S6 | 战斗完成闭环 | combat_init → 结算 → complete_combat_turn brief 非空 | — |
| S7 | 移动 + 时钟 | current_location 变更；time_agent 返回结构合法 | 时钟推进（delta ≥ 0） |
| S8 | FROZEN 诱发 | 无效 API key 场景下 status=FROZEN、frozen_message 非空、CLI/前端映射存在 | — |
| S9 | 结局触发 | game_over=True、EndingInfo 字段完整 | — |

**flaky 策略**：每场景最多 retry 一次（pytest-rerunfailures 或手写装饰器）；retry 仍失败才计失败。LLM 内容断言一律用宽断言（存在性/非空/结构合法），不做语义等值判断。

**日志**：每场景经 `setup_llm_logging` 落盘 prompt/response/meta 到 `data/debug/e2e/<timestamp>/<scenario>/`，便于失败后人工溯源。

**成本预估**：9 场景 ≈ 10-20 分钟 + API 费用；on-demand 运行，不进默认套件、不进 CI 阻塞。

## 步骤 3：巡检层 + 场景化 llm_player（骨架）

**本计划只做接口与骨架，提示词指引另议。**

1. **llm_player 目标注入接口**：
   - CLI 新参 `--goal-file <path>`：读取场景定义（Markdown/YAML，含测试指引、成功判据、max_turns）
   - 指引文本注入玩家 agent 的决策 prompt（作为"本局目标"段）
   - 每回合后调用成功判据检查（判据 = 结构化日志字段表达式，如 `inventory contains "手枪"`、`standoff_occurred == true`），达标即停
2. **audit 升级**：`src/audit_player_log.py` 的日志校验逻辑抽为可复用函数 `audit_turn_logs(log_dir) -> AuditReport`（结构合规、异常检测、契约不变量），场景层与巡检层共用；CLI 保留
3. **巡检层 runner**：`tests/e2e/run_patrol.py`（或 pytest real_llm case）：无引导自由游玩 N 回合 + `audit_turn_logs` 硬断言结构合规；行为质量输出软报告（不阻塞）
4. **scenarios/ 目录**：格式 README（场景 = 初始状态种子 + 指引 + 判据 + max_turns），示例场景 1 个（搜索拾取）

## 断言分层原则（全局）

| 层 | 对象 | 断言方式 | 失败处理 |
|----|------|---------|---------|
| 契约结构 | 每回合 TurnResult/PlayerTurnResult/日志结构 | 硬断言 | 立即失败 |
| 游戏逻辑状态 | 武器入包、位置变更、game_over、pending 清理 | 硬断言（确定性部分） | 立即失败 |
| LLM 内容决策 | parse 选择、Author 升级、叙事文本 | 宽断言（存在性/非空/合法值域） | retry 一次后失败 |
| 行为质量 | 叙事好坏、决策合理性 | 软报告 | 不阻塞 |

## 非目标（YAGNI）

- 不统一重写 harness_parallel / harness_stability / llm_player 主体
- 不引入 LLM judge（质量评估靠巡检层软报告 + 人工抽查日志）
- 步骤 3 的具体场景提示词指引（另行讨论）
- CI 集成（real_llm 套件为本地 on-demand）

## 风险与缓解

- **LLM 波动致场景误报**（已在 escalation C/E 观察到）：宽断言 + retry 一次 + 日志落盘溯源
- **固定输入脚本与实际走向错位**（如意外 standoff 吞掉下条输入）：场景设计时输入序列保守化（每步只依赖上一步的硬断言状态）；步骤 3 的指引化玩家从根本上解决此类问题
- **测试模块维护成本**：契约路径场景复用 escalation 风格的最小测试模块；真实模块仅用于巡检层
