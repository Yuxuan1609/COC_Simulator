# NPC 系统重检专项设计稿（N1 attitude 度量层 + N3 谎言策略 + N4 死亡反应）

> 2026-09-02。替代《2026-09-02-npc-n1-attitude-design.md》（N1 底稿已并入本文）。
> 专项拆解与收敛过程（2026-09-02 逐问拍板）：
> - 原拆 N1-N5；**N2 NPC inventory 整项跳过**（投机式基建：无消费者，队友化真正落地时形状大概率不同；叙事交接用「bound_interaction + item requirement + consume」假性流转覆盖，F1 给予随 F28 队友化一并设计）。
> - **N5 感知体系跳过**（只做对抗层意义不大，随 F28 队友化大升级；F20 潜行维持 §4 缓）。
> - 本期 = N1 + N3 + N4。

## 0. 问题陈述

- `attitude` 是静态装饰：profile 给定后运行时零通路修改（`set_attitude` 零调用；`@npc_state_change` 只改 state），唯一消费是 talk_to prompt 一行文本（npc_manager.py:223）。
- 玩家陈述无条件写入 npc.memory，prompt 明示「如实告知」（npc_manager.py:227）——伪装/套话无支撑。
- NPC 死亡只做门控，存活 NPC 无任何反应通道。
- 死代码：`process_npc_turn`（npc_manager.py:315+，零调用）。

## 1. N1 attitude 双轨度量层

### 1.1 模型

- 内部数值 `attitude_value: int`（-100..100），入档（旧档缺省 0/由旧档位文本反推中值）。
- 对外档位：数值 → 文本档位进 prompt，LLM 只见档位不见数字：

| 数值区间 | 档位 |
|---|---|
| ≤ -50 | 敌意 hostile |
| -50..-10 | 警惕 wary |
| -10..10 | 中立 neutral |
| 10..50 | 友好 friendly |
| > 50 | 信任 devoted |

- 阈值表进 `game_config.npc_attitude_tiers`（与 F19 env_check_modifiers 同模式，可调）。

### 1.2 变化通道：统一出口 @attitude_change

- markup 新增 `@attitude_change(npc_name="名称", delta=-30)`：side_effects 解析+执行，clamp；非法目标 → 忽略 + warning。
- **两路来源**（已拍板：LLM 自主调控是必须的，否则 attitude 不如直接用 interaction 硬门控）：
  1. **模组显式**：作者在 interaction result/side_effects 挂（帮他 +20 / 冒犯 -30）。
  2. **LLM 自主**：NPC 对话回复文本可内嵌 @attitude_change，展示前 side_effects 解析剥离执行（talk_to 维持纯文本 json_mode=False）。
- talk_to prompt 明示 NPC 可根据交谈内容自主决定态度变化并内嵌 markup。

### 1.3 消费点（确定性 + LLM 渲染 + improvise 三类，已拍板）

**确定性**：
- `interaction_triggers` / `bound_interactions` 加 `attitude_min: int` 门槛（不满足 → 互动不可见/失败回退话术）。
- `follow_requirements` 检查态度（敌意/警惕不得跟随）。
- talk_to 短路：敌意 NPC 拒绝/驱赶，不进自由对话。

**LLM 渲染/即兴**：talk_to/keeper/enrich prompt 注入当前场景 NPC 态度档位，即兴创作呼应（警惕的线人闪烁其词）。

### 1.4 死代码处置（已拍板）

- `set_attitude` 复活为数值版（加减 + clamp + 档位查询）。
- `process_npc_turn` 确认零调用后删除；对话只留 understand.py 内联一条活路。

## 2. N3 谎言/欺骗：纯 LLM 策略化（零新数据结构）

- talk_to 及 NPC 相关 prompt 策略重写：
  - 删除「如实告知所知内容，不刻意隐瞒」无条件指令。
  - 改为按 **attitude 档位 + 信息敏感度**决定透露程度（敌意不答/警惕套话/友好有限透露/信任才交底）。
  - 玩家身份声明与陈述由 LLM 按 NPC 所知自主判断采信（伪装成警察能否唬住线人 = LLM 演绎，态度低时更容易起疑）。
- memory 维持现状（flat 文本），不加真伪标记——真伪判断是 LLM 每次对话的现场演绎，不落库。
- 改 prompt → 必跑 `pytest -m real_llm_smoke`；real_llm 套件加对话行为用例（敌意 NPC 不泄密 / 高态度才交底）。

## 3. N4 死亡反应：AT + LLM 演绎（零新结构）

- 死亡单点 `set_state` 已入 Chronicle；存活 NPC 下次对话由 LLM 按态度 + 所知自由反应（叙事层）。
- 模组作者要确定性反应分支：用 **AT（bound_auto_triggers）挂「NPC X 死亡」条件**——实现时验证 AT 触发条件是否覆盖 NPC 死亡事件，缺则小补（set_state 死亡时触发 AT 检查）。
- 不做广播式连锁、不做独立 on_death 声明结构（已拍板）。

## 4. 关键改动点（行号以 2026-09-02 HEAD 为准）

| 位置 | 改动 |
|---|---|
| game/npc_manager.py | NPC 增 attitude_value；档位映射；set_attitude 数值化；process_npc_turn 删除；to_dict/from_dict 加字段 |
| game/side_effects.py + scenario_core apply_side_effects | @attitude_change 解析+执行 |
| game/npc_manager.py talk_to | prompt 策略重写（态度档位/透露策略/自主 markup/敌意短路）；回复 markup 剥离执行 |
| prompts.py | keeper/enrich/improvise 注入 NPC 态度档位；talk_to 模板调整 |
| module_designer/layered_schema.py | interaction/bound_interaction 加 attitude_min 可选字段 |
| investigator/rules.py game_config | npc_attitude_tiers 阈值表 |
| understand.py | talk 入口敌意短路判定 |
| scenario_core.py set_state | 死亡时 AT 触发检查（缺口小补） |

## 5. 测试约定

- 默认套件 TDD：档位映射/门槛/clamp/入档往返/@attitude_change 双来源/敌意短路/死亡 AT 触发/死代码删除回归。
- prompt 主路径改动 → `pytest -m real_llm_smoke`；新增 real_llm 对话行为用例。
- 【生成端】登记 §10：attitude_min 字段说明、NPC prompt 生成端 attitude 初始值标注（生产端回填随管线回查统一处理）。

## 6. 不做清单（本专项）

- N2 NPC inventory / F1 给予（→ F28 队友化大升级）
- N5 感知体系（→ F28；F20 潜行维持 §4 缓）
- mood 瞬态情绪（attitude 够用）
- NPC 自主日程（远期）
- F27 的日程部分、F26 的结构化真伪标记（LLM 策略化替代）
