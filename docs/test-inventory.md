# 游戏机制测试清单

> 2026-08-06 整理。目的：盘点引擎全部机制子系统 × 测试覆盖现状 × 待测项。
> 约定：持久化（存读档）属于已知功能升级点，不在本清单的检查范围内。
> 覆盖标记：✅ 已有覆盖 | ⚠️ 部分/间接覆盖 | ❌ 未覆盖 | ⏸ 暂缓

## 测试资产现状

| 层 | 位置 | 内容 |
|----|------|------|
| 确定性 E2E | `tests/e2e/test_deterministic.py` | 7 场景（stub LLM）：offer拾取/clarify/战斗init+完成/移动/结局/纯对话/多回合状态完整性 |
| 真实 LLM 场景 | `tests/e2e/test_scenarios.py`（S1-S9，`real_llm`） | 固定输入 9 场景，combat_entry/standoff_match 单点 stub |
| 场景化 runner | `tests/e2e/run_scenario.py` + `scenarios/*.yaml` | goal 驱动 llm_player + 三层判定（pilot：standoff_avoid） |
| 升级决策 | `tests/e2e/test_escalation_real.py`（`real_llm`） | Author/escalation 5 case |
| 单元/契约 | `tests/test_*.py` | 回合契约、前端契约、turn_monitor、P0 修复、harness 稳定性、战斗冒烟 |

## 子系统 × 覆盖矩阵

### A. 核心回合管线

| # | 子系统 | 落点 | 覆盖 | 待测项 |
|---|--------|------|------|--------|
| A1 | 意图解析（pre_parse clarify 门 → Parse 实体匹配 → Judge 执行/门槛） | `pre_parse.py` / `keeper.py` Step 0-2 / `judge.py` | ✅ | clarify 误杀率（真实模块自由输入）；requirement 软硬门槛（`\|\|`）组合 |
| A2 | 触发器/依赖图（auto_trigger LLM 点火、events、依赖边级联） | `judge.py:check_auto_triggers` / `keeper.py:467` | ⚠️ | **AT 点火率**（"进房/条件"类 trigger 的语义匹配稳定性——波动最大来源）；依赖边级联；world AT 初始化 |
| A3 | Enrich → Curator → Narrator 三段叙事管线 | `keeper.py` Step 3 / `curator.py` / `narrator.py` | ⚠️ | 从未单独验证：enriched_summary 与 outcome 事实分离、brief 信息完整性、叙事与事实一致性（可走 runner judge 层） |
| A4 | 技能检定 + 特质增强 | `investigator.check_skill` / `prompts.apply_trait_enhancement` | ⚠️ | 特质增强触发率与方向正确性（原 tier→新 tier）；大成功/大失败不参与修正；搜索/交互/standoff 三路径一致性 |
| A5 | 失败惩罚/难度升级 | `judge.py` retries/escalated_difficulty/penalty markup | ❌ | 连续失败→难度升级→惩罚叙事生效；升级后成功回落 |
| A6 | 结局系统 | `keeper._scan_ending` / `##END_##` markup | ✅ | 多结局模块的分流（常暗之厢 END1/2/3/TEST） |
| A7 | 待定交互状态机（clarify / weapon_offer / standoff 三个 pending 门） | `keeper.py:140/201` / `game_loop.continue_standoff` | ⚠️ | **已知坑 F2**：offer 门吞掉非回答输入；**F3**：standoff×boss 同回合冲突；pending 跨回合正确清账 |
| A8 | 冻结保护 | `turn_monitor` FROZEN | ✅ | — |

### B. 实体系统

| # | 子系统 | 落点 | 覆盖 | 待测项 |
|---|--------|------|------|--------|
| B1 | NPC（attitude/state/follow、bound AT/交互注入） | `npc_manager.py` / `keeper._inject_npc_at` | ✅ | 态度迁移链路（交谈→态度变→解锁跟随）；跟随 NPC 跨场景注入；**场景 S-B npc_befriend 待写** |
| B2 | 战斗系统（回合制、武器、阶段） | `combat.py` | ⏸ | 整体暂缓；有 AUTO 开关短接 |
| B3 | Boss 遭遇机制（engage 类型、预生成、active 记账、phases 切换） | `boss_manager.py` / `keeper.py:603` | ⚠️ | at/interaction/event 三型 engage；预生成实例复用；**场景 S-C boss_fight 待写**（含阶段切换观察） |
| B4 | 对峙回避 standoff（语义匹配→D100→特质增强→群体链） | `keeper.resolve_standoff` / `game_loop.continue_standoff` | ✅ | 多组敌人链式 standoff；standoff 中特质增强路径 |
| B5 | 武器/物品（scene_weapons、拾取 offer、item_gain/consume 模糊匹配） | `side_effects.py` / `keeper.py:140` | ⚠️ | consume_item LLM 模糊匹配兜底；装备与战斗联动（随 B2） |
| B6 | 即时内容生成（injector 离线/运行时注入） | `library/injector.py` | ⚠️ | 运行时注入触发条件与节奏；注入内容与模块调性一致性 |

### C. 世界与元系统

| # | 子系统 | 落点 | 覆盖 | 待测项 |
|---|--------|------|------|--------|
| C1 | 时间推进（clock、TimeAgent LLM 估时、time_costs 表） | `clock.py` / `time_agent.py` | ⚠️ | 估时合理区间；时间上下文（time_context）流转；时限压力触发（常暗之厢 time_pressure） |
| C2 | 时间压力通讯 | `keeper.py` TimeCommsPacket dispatch / `author.assess_time_pressure` | ❌ | 周期间隔 dispatch；comms 内容对玩家可见性 |
| C3 | Author 干预（ModulePatch/StructuralEdit 动态改模组） | `author.py` / `intent_detector.py` | ✅（escalation 5 case） | patch 应用后世界一致性；递归深度保护 |
| C4 | 记忆系统（raw_history、异步压缩总结） | `scenario_core.MemoryManager` / `keeper.py:855` | ❌ | 长局记忆压缩触发；压缩后上下文连续性；NPC 事件记忆 |
| C5 | 世界规则（WR0/world_rules 绝对规则注入） | `config.WR0_ENABLED` / 各 prompt | ❌ | 规则违抗检测（玩家试图打破绝对规则时 keeper 的处理） |
| C6 | side_effects @markup 语言 | `side_effects.py` | ✅ | 各指令容错（未知 ref 降级，已修）；组合副作用原子性 |
| C7 | 可观测性（TurnLogger/prompt 日志） | `turn_logger.py` / `prompts.log_skill_result` | ✅ | — |

### D. 引擎外

| # | 子系统 | 覆盖 | 待测项 |
|---|--------|------|--------|
| D1 | 模组生产管线（launcher step0/pipeline/validate，L1/L2/L3 生成） | ❌ | 生产侧，独立排期 |
| D2 | 前端展示层 | ⚠️ 手动 | 见 UPDATES.md 前端重构条目；可考虑 Playwright 冒烟 |

## 近期优先队列（建议）

1. **A7 两个已知坑修复**（F2 offer 吞回合 / F3 standoff×boss 互斥）+ 回归测试
2. **A2 AT 点火率调查**——决定"有时不灵"类问题的天花板
3. **场景 S-B / S-C**（runner 体系：npc_befriend、boss_fight）——覆盖 B1/B3 深层链路
4. **A3 叙事管线判定**（runner judge 层：叙事-事实一致性 rubric）
5. **A5 失败升级**、**C1 时间**、**C4 记忆**——各补一个针对性场景
