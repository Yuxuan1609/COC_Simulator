# NPC 专项 N1：attitude 度量层设计稿（底稿，暂不实现）

> 2026-09-02。NPC 系统重检专项第 1 子项（N1-N5 拆解见文末 §6）。
> **状态：底稿，待 N2-N5 讨论完毕后统一评审，防止子项决策互相干涉。**

## 0. 问题陈述

现状：`attitude` 是**静态装饰**——profile 给定后运行时零通路修改（`set_attitude` 全 src 零调用；`@npc_state_change` 只改 state 不改 attitude），唯一消费是 talk_to prompt 一行文本（npc_manager.py:223）。「好感度」存在但无实际作用。

## 1. attitude 双轨模型（已拍板）

- **内部数值**：`attitude_value: int`，-100..100，入档（to_dict/from_dict 加字段，旧档缺省由档位文本反推中值或 0）。
- **对外档位**：数值 → 档位映射进 prompt，LLM 只见文本不见数字：

| 数值区间 | 档位 | 缺省阈值 |
|---|---|---|
| ≤ -50 | 敌意 hostile | game_config `npc_attitude_tiers` 可调 |
| -50..-10 | 警惕 wary | |
| -10..10 | 中立 neutral | |
| 10..50 | 友好 friendly | |
| > 50 | 信任 devoted | |

- 阈值表进 `game_config`（与 F19 env_check_modifiers 同模式）。

## 2. 变化通道：统一出口 @attitude_change

- markup 新增 `@attitude_change(npc_name="名称", delta=-30)`：side_effects 解析 + 执行，clamp -100..100；非法 NPC 名/参数 → 忽略 + warning（既有降级风格）。
- **两路来源（已拍板：LLM 自主调控是必须的，否则 attitude 不如直接用 interaction 硬门控）**：
  1. **模组显式**：作者在 interaction result/side_effects 里挂（帮他 +20 / 冒犯 -30）。
  2. **LLM 自主**：NPC 对话回复文本可内嵌 @attitude_change，展示前由 side_effects 解析剥离执行（talk_to 维持纯文本 json_mode=False，不动结构）。
- talk_to prompt 需明示 NPC「可根据交谈内容自主决定态度变化并内嵌 @attitude_change」（改 prompt → real_llm_smoke）。

## 3. 消费点（已拍板：确定性 + LLM 渲染 + improvise 三类）

**确定性门控**：
- `interaction_triggers` / `bound_interactions` 可加 attitude 门槛（如「友好才说出密室位置」）：schema 字段 `attitude_min: int`，不满足时该互动不可见/触发失败回退话术。
- `follow_requirements` 检查态度档位（敌意/警惕不得跟随）。
- talk_to：敌意 NPC 直接拒绝/驱赶（短路回复，不进自由对话）。

**LLM 渲染/即兴**：
- talk_to prompt 档位文本（现有，接动态值）。
- keeper/enrich/improvise prompt 注入当前场景 NPC 态度档位，即兴创作时呼应（警惕的线人说话闪烁其词）。

## 4. 死代码处置（已拍板）

- `set_attitude` 复活为数值版（加减 + clamp + 档位映射查询）。
- `process_npc_turn`（npc_manager.py:315+）确认零调用后**删除**；对话只留 understand.py 内联一条活路。

## 5. 本期不做

- mood 瞬态情绪字段（已拍板：attitude 够用；「激怒后平复」用 @attitude_change(-30) + 后续补回表达）。
- NPC 自主日程（无多人模拟承载，远期）。
- N2-N5 内容（inventory/谎言/死亡连锁/感知）见各自子项。

## 6. 专项拆解备忘（2026-09-02 拍板）

N1 度量层（本文）→ N2 NPC inventory + F1 给予 → N3 记忆真伪 + 谎言（F26）→ N4 死亡连锁降级版（F29）→ N5 感知体系（重评 F20/F26 联动）。

## 7. 测试约定（实现时）

- 默认套件 TDD；档位映射/门槛/clamp/入档往返/ markup 双来源/死代码删除后回归。
- 改 talk_to/keeper prompt → `pytest -m real_llm_smoke`。
- 【生成端】登记：attitude_min 门槛字段进 L2 schema 说明（生产端回填与否随 §10 清单统一处理）。
