# E2E 测试方案（分层体系 · 流程 · 审计约定）

> 2026-08-06 定稿。配套文档：`docs/test-inventory.md`（子系统×覆盖矩阵详表）。
> 命名约定：为避免与模组 L1/L2/L3 文件层重名，测试分层称为 **骨架层 / 实连层 / 场景层**。

## 一、分层定义

| 层 | 名称 | 管什么 | LLM | 运行时机 |
|----|------|--------|-----|----------|
| 骨架层 | 确定性 E2E | 机制骨架对不对（状态机、数据流、契约） | 全 stub | 默认套件，每次必跑 |
| 实连层 | 固定输入真实 LLM | LLM 环节接不接得住（固定输入 → 真实模型） | 真实，单点 stub 战斗判定 | on-demand（`real_llm`） |
| 场景层 | goal 驱动 runner | 系统级行为对不对（多回合自由推进 + 审计） | 真实 | on-demand CLI |

**骨架层 stub 的精确层级**（`tests/e2e/helpers.py:stub_keeper_llm`）：替换 keeper 的 LLM 触点——`pre_parse.disambiguate` / `_parse` / `_enrich` / `_run_time_agent` 方法级替换，keeper 命名空间 `call_deepseek` 兜底（combat_entry 判定），Narrator 换 StubNarrator 原样回显 brief。**judge / scenario_core / side_effects / enemy_manager 等确定性逻辑全真运行**——骨架层测的是"除 LLM 外的全部机制"。

## 二、子系统编号表

| 编号 | 子系统 | 落点 |
|------|--------|------|
| **A 核心回合管线** | | |
| A1 | 意图解析（pre_parse clarify 门 → Parse 实体匹配 → Judge 执行/门槛） | `pre_parse.py` / `keeper.py` Step 0-2 / `judge.py` |
| A2 | 触发器/依赖图（auto_trigger LLM 点火、events、依赖边级联） | `judge.py:check_auto_triggers` / `keeper.py:467` |
| A3 | Enrich → Curator → Narrator 三段叙事管线 | `curator.py` / `narrator.py` |
| A4 | 技能检定 + 特质增强（tier 修正、大成功/大失败） | `investigator.check_skill` / `prompts.apply_trait_enhancement` |
| A5 | 失败惩罚/难度升级（retries、escalated_difficulty） | `judge.py` |
| A6 | 结局系统（_scan_ending、##END_## markup） | `keeper.py` |
| A7 | 待定交互状态机（clarify / weapon_offer / standoff 三个 pending 门） | `keeper.py:140/201` / `game_loop.continue_standoff` |
| A8 | 冻结保护（turn_monitor FROZEN） | `turn_monitor` |
| **B 实体系统** | | |
| B1 | NPC（attitude/state/follow、bound AT/交互注入） | `npc_manager.py` |
| B2 | 战斗系统（回合制、武器、阶段） | `combat.py` — **整体暂缓** |
| B3 | Boss 遭遇机制（engage 类型、预生成、active 记账、phases） | `boss_manager.py` |
| B4 | 对峙回避 standoff（语义匹配→D100→特质增强→群体链） | `keeper.resolve_standoff` |
| B5 | 武器/物品（scene_weapons、拾取 offer、item_gain/consume） | `side_effects.py` |
| B6 | 即时内容生成（injector 离线/运行时注入） | `library/injector.py` |
| **C 世界与元系统** | | |
| C1 | 时间推进（clock、TimeAgent 估时、time_costs） | `clock.py` / `time_agent.py` |
| C2 | 时间压力通讯（TimeCommsPacket dispatch） | `keeper.py` / `author.assess_time_pressure` |
| C3 | Author 干预（ModulePatch/StructuralEdit、IntentDetector 升级决策） | `author.py` / `intent_detector.py` |
| C4 | 记忆系统（raw_history、异步压缩总结） | `scenario_core.MemoryManager` |
| C5 | 世界规则（WR0/world_rules 绝对规则） | `config.WR0_ENABLED` |
| C6 | side_effects @markup 语言 | `side_effects.py` |
| C7 | 可观测性（TurnLogger/prompt 日志） | `turn_logger.py` |
| **D 引擎外** | | |
| D1 | 模组生产管线（launcher/L1-L2-L3 生成） | 生产侧，独立排期 |
| D2 | 前端展示层 | 手动 + 后续 Playwright 冒烟 |

## 三、完备性映射（一个测试可覆盖多个子系统）

### 骨架层（增量进 `test_deterministic.py`）

| 测试 | 覆盖 | 状态 |
|------|------|------|
| D-搜索→offer→拾取 | A1/A7/B5 | 已有 |
| D-clarify | A1/A7 | 已有 |
| D-战斗 init+完成 | B3浅 | 已有 |
| D-移动/结局/NPC/多回合 | A1/A6/B1/A7 | 已有 |
| D8 AT点火→@spawn_enemy→敌人可见 | A2/C6 | 新增 |
| D9 失败→重试→难度升级→惩罚 | A5 | 新增 |
| D10 Boss预生成→engage→phases（stub 战斗） | B3 | 新增 |
| D11 记忆压缩触发（调低阈值） | C4 | 新增 |
| D12 时间推进（TimeAgent stub 固定估时） | C1 | 新增 |

### 实连层（**先试点 1-2 个 case，验证无问题再全量**）

| 测试 | 覆盖 | 状态 |
|------|------|------|
| S1-S9 | A1/A6/A7/B4/B5/C1浅 | 已有，保留不动 |
| S10 特质增强方向（登山向导卡搜索，验 original_tier→tier） | A4 | **试点 ①** |
| S11 AT 点火真实面（进 B 触发巡游者） | A2 | **试点 ②** |
| 试点通过后再扩全量 | | 后续 |

### 场景层（基于 testbed 模组；**不实际进战斗**——走 AUTO 自动胜利短接，战斗与后续逻辑差异大，B2 另测）

| 场景 | 覆盖 | 状态 |
|------|------|------|
| S-A standoff_avoid | B4/A7 | ✅ pilot 通过 |
| S-B npc_befriend（结交→态度迁移→跟随） | B1 | 待写 |
| S-C boss_fight（接近→standoff/engage→**AUTO 胜利**→Boss 记账） | B3 | 待写（改 AUTO 版） |
| S-D 箱庭全链路通关（搜索→钥匙→NPC→跟随→standoff→Boss AUTO→结局） | A1-A7/B1-B5/C1 | 待写，完备性主干 |
| 巡检层 verdict 化 | C7 | 收尾 |

### 暂不接 E2E

C2 时间压力通讯、C5 世界规则——依赖常暗之厢/对抗性输入，后续单独场景，不阻塞本轮。

## 四、输出呈现（三档）

| 档 | 内容 |
|----|------|
| 默认 | 每场景一行进度 + 结束判定总结 |
| `-v` | 每回合一行机制时间线：`T03 [12.3s] "搜索房间" → intent=search tier=hard(原regular↑) AT:IT_SEARCH \| pending=offer` |
| 完整日志 | 永远落盘（现有 `logs/prompt_log_*` 体系），终端只打印路径 |

判定输出：rubric 逐项 `✓/✗ + 一句证据`，不贴大段原文。

## 五、审计 LLM 约定

**输入三层**：
1. **操作手册**（`tests/e2e/scenarios/audit_guide.md`，全局一份）：机制名词表（AT 点火/tier/pending 状态机/standoff/boss engage/阶段…）、机制事件类型说明、判定程序、常见误判警示（如"AT 未语义匹配≠机制失败，需看输入是否真满足 trigger"）——**先行编写**，它定义事件名词表，runner 时间线采集格式与之对齐
2. **机制事件时间线**（机器采集，结构化事实层）：judge 不可违背，防捏造证据
3. **场景 rubric**（YAML judging 段，**声明式**）：`必须发生`（事件 + 宽松顺序约束）+ `禁止发生` + 自由心证项；不写逐回合脚本（真实 LLM 波动下会 flaky）

judge 只看叙事摘录，不看完整 prompt 日志（防淹没）；深挖由人翻日志文件。

## 六、实施顺序

1. **Phase 0**：审计操作手册（audit_guide.md）
2. **Phase 1**：runner 升级（机制事件时间线采集 + 三档输出 + 手册注入 judge）
3. **Phase 2**：骨架层 D8-D12
4. **Phase 3**：实连层试点 S10/S11 → 验证 → 全量
5. **Phase 4**：场景层 S-B / S-C（AUTO 版）/ S-D + 巡检 verdict 化

回归基线：默认套件 68+ 全绿；骨架层新增进默认套件；实连层/场景层 on-demand。
