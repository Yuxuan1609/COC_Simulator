# U2 世界状态摘要层（WorldChronicle）设计方案

> 状态：初稿（2026-08-14 讨论定稿，待实施）
>
> 核心痛点：Author patch 时看不到"已经发生了什么"，`runtime_summary` 只有 `{entity_id: tier}`
> 干瘪标记，现行策略靠限制 Author 追加范围绕过。
> 定位：**世界侧基础设施**（挂 ScenarioWorld，与 memory 平级），生产者唯一、消费者 opt-in。
> keeper 明确不做消费者（已完善，不增负担）。本期唯一消费者 = Author；
> 未来消费者 = 法术系统等需要全局后果感知的机制。

---

## 1. 架构

```
ScenarioWorld.chronicle: WorldChronicle        ← 生产者，每回合末 game_loop 写入
  ├─ facts    真值表（不存储，渲染时从 world 实时采集）
  ├─ events   滚动编年史（deque，窗口 N=15）
  ├─ patches  Author 注入清单（append-only）
  └─ events_summary  预留：LLM 蒸馏摘要（本期不实现，见 §5 接口备注）
        ↓ 消费方各自渲染
Author prompt ←【世界编年史】块（keeper._build_scene_context_for_author 注入）
```

- 消费者不读原始结构，只拿渲染文本；渲染器按消费方预算参数化。
- 测试侧机制时间线（`llm_player._collect_mech_line`）与 events 同形定义，本期不改测试代码，后续可切源。

## 2. facts —— 真值表

渲染时从 world 实时采集（零存储、零一致性风险）：

| 组 | 内容 | 来源 |
|---|------|------|
| 位置 | 当前场景 / 已到访序列 / 可用场景 | current_location / memory.visited / graph.nodes |
| 时间 | 游戏时钟（day/时刻/累计分钟） | clock |
| 玩家 | HP/SAN/MP/LUCK 裸数值、持有武器、关键物品 | player / memory.key_items |
| 敌人 | ref×数量@场景 + 状态(neutral/hostile/engaged/defeated) + flags | enemies._instances |
| Boss | 已 spawn / 已 engage / 已击败 / 当前阶段 | bosses |
| NPC | 名字@场景 + 状态 + 是否跟随 | npcs / npc_states |
| 实体 | 已完成：id + tier + 完成回合号 + **结果文本截断 100 字** | runtime_state + outcomes 记录 |
| 场景武器 | 各场景剩余未拾武器 | scene_weapons |

> 结果文本来源：runtime_state 只有 tier，结果文本需 Chronicle 在 record_turn 时从
> TurnResult.outcomes 留存（`entity_results: {entity_id: 截断文本}`，随 facts 渲染）。

## 3. events —— 编年史

每回合一条机器骨架（单行），字段：

```
T{回合} | in="{玩家原话，截断 60 字}" | intent={parse 意图} | entities={ID:tier,...} |
at={点火 AT} | spawn={生成} | move={A→B} | boss={engage/defeated(ID)} |
combat={start/end(outcome)} | standoff={结果} | npc={交互对象} | ending={ID}
```

- **带玩家原话**（截断 60 字）——Author 需要理解"怎么发生的"（已拍板）
- 缺省字段不输出；窗口 N=15（deque(maxlen=15)）
- 与测试侧 `_collect_mech_line` 同形同字段

## 4. patches —— Author 注入清单

每次 Author 响应一条：回合号、级别（patch/structural/reject）、注入实体 id 列表、
新场景（structural）、justification 截断 100 字。
来源：keeper 在 `_integrate_patch`/`_integrate_supplement` 调用后记录（author.history 太薄，不依赖它）。

## 5. LLM 压缩接口（本期不实现，仅预留）

events 超窗条目目前是丢弃的。预留蒸馏通路：

```python
class WorldChronicle:
    events_summary: str = ""          # 蒸馏摘要（远期事件）
    def compress_events(self, llm_call) -> None:
        """将 deque 中较旧的一半蒸馏进 events_summary。
        本期不接线；调用时机建议=events 满窗时，模型=flash。
        接口签名固定，法术系统等未来消费者可直接依赖 events_summary 字段。"""
```

渲染规则：`events_summary` 非空时排在 events 窗口之前。

## 6. 序列化

`to_dict/from_dict`：events（list）、entity_results、patches、events_summary 入档。
facts 不入档（实时采集）。读档恢复后 Chronicle 状态连续。

## 7. Author 接入

- `keeper._build_scene_context_for_author()` 增 `chronicle` 键（渲染文本）
- `build_author_prompt()` 增【世界编年史】块：facts → patches → events_summary → events
- 预算目标：整块 ≤ 2500 token（facts ~500 + events 15×~100 + patches ~200 + 裕量）

## 8. 影响文件

| 文件 | 改动 |
|------|------|
| `src/scenario_core.py` | **WorldChronicle 类新建**；ScenarioWorld 挂 `chronicle`；序列化进出档 |
| `src/game_loop.py` | run_turn 回合末 `world.chronicle.record_turn(...)` |
| `src/game/agents/keeper.py` | `_build_scene_context_for_author` 注入渲染文本；patch/supplement 后记 patches |
| `src/prompts.py` | `build_author_prompt` 加编年史块 |
| `tests/` | Chronicle 单测（record/render/截断/窗口/序列化）+ 确定性 E2E（Author 上下文含编年史） |

## 9. 明确不做

- keeper parse/enrich/narrator 不接 Chronicle（控制范围，本期唯一消费者 Author）
- LLM 蒸馏（§5 仅接口预留）
- 测试侧 `_collect_mech_line` 切源（后续顺手做）
- 玩家可见的状态面板（Chronicle 是 LLM 饲料，不是 UI）
