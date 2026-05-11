# 游戏主循环重构设计

## 概述

四个改动按**执行流顺序**组织：先整合底层数据结构，再重构调用流程，最后调整各阶段的 prompt。

| 顺序 | 改动 | 说明 |
|------|------|------|
| 3 | 整合 MemoryManager → ScenarioWorld | 底层：减少传参，精简 API |
| 2 | 阶段1/2 并行调用 | 架构：动作解析与事件判定完全独立 |
| 1 | 世界更新（两个独立 LLM 调用） | 新增：每次交互/事件后更新 abstract + description |
| 4 | 叙事 prompt 保留可触发事件 | 调整：辅助叙事 LLM 了解场景发展可能 |

涉及文件：`src/scenario_core.py`、`notebooks/notebook_simplified.ipynb`

---

## 一、整合 MemoryManager → ScenarioWorld（基础）

### MemoryManager 精简

| 字段 | 处理 |
|------|------|
| `raw_history`, `summary`, `max_raw`, `turn`, `visited`, `key_items` | 保留 |
| `npc_clues` | 移除，改用 `world.flags[f"npc_{name}_clue"]` |
| `note_discovery()` | 精简为 `note_item(item)`，去掉 npc/clue 参数 |
| `add_record()`, `should_compress()`, `compress()`, `get_context()` | 保留不变 |

### 挂载到 ScenarioWorld

```python
class ScenarioWorld:
    def __init__(self, ...):
        ...
        self.memory = MemoryManager()

    def apply_world_update(self, abstract: str, description: str):
        """应用世界更新结果"""
        self.set_background(abstract)
        node = self._current_node()
        if node:
            node.description = description
```

### 函数签名变更

所有原本同时接收 `world` 和 `memory` 的函数，改为只接收 `world`，内部通过 `world.memory` 访问记忆。涉及：

| 函数 | 旧签名 | 新签名 |
|------|-------|-------|
| `build_action_prompt` | `(world, memory, user_input)` | `(world, user_input)` |
| `build_event_prompt` | `(world, memory, action_summary, skill_results)` | `(world, user_input)` |
| `build_narrative_prompt` | `(world, memory, user_input, action_summary, event_results, skill_results)` | `(world, user_input, action_result, events_result)` |
| `handle_user_input` | `(user_input, world, memory)` | `(user_input, world)` |

---

## 二、阶段1/2 并行（架构）

### 当前流程（串行）

```
阶段1: 动作解析 → 执行 → action_summary
    ↓
阶段2: 事件判定（依赖 action_summary）
    ↓
阶段3: 叙事生成
```

### 新流程

```
user_input
    |
    ├──→ 阶段1: 动作解析 → 执行动作 → action_result
    |        输入: scene context + world state + world.memory + user_input
    |        产出: action + target/interaction + skill_checks → 执行 → action_result
    |
    └──→ 阶段2: 事件判定 → 执行事件 → events_result
             输入: pending events + world state + world.memory + user_input
             产出: triggered_events[] + new_flags{} → 直接执行

[两者完全独立，无合并步骤]

阶段1.5a: 动作世界更新（见第三节）

阶段1.5b: 事件世界更新（见第三节，仅当本轮有新事件触发时执行）

阶段3: 叙事生成（见第四节）
```

### 阶段2 重写

`build_event_prompt` 不再接收 `action_summary`，改为接收 `user_input`。LLM 基于玩家意图独立判断：

```
输入: user_input + 全部未触发事件(含trigger条件+impact) + world state + world.memory
输出: { "triggered_events": ["E1"], "new_flags": {}, "reasoning": "..." }
```

---

## 三、世界更新 —— 两个独立 LLM 调用（新增）

阶段1和阶段2各自产出结果后，分别触发一次世界更新。两次调用顺序执行，后者在前者已更新的基础上继续修改。

### 调用一：`build_action_world_update`

```
输入: action_result + 当前 abstract + 当前 scene description
输出: { "abstract": "...", "description": "..." }
写入: world.apply_world_update()
```

### 调用二：`build_event_world_update`

```
输入: events_result + 上一步已更新的 abstract + 上一步已更新的 description
输出: { "abstract": "...", "description": "..." }
写入: world.apply_world_update()
```

仅在 `events_result` 中有实质触发事件时调用；无事件触发则跳过。

### 约束

- abstract 累积追加而非重写，避免丢失早期信息
- description 只在场景确有可见变化时修改，无变化原样返回
- **不得添加未实际发生的实质性信息**，避免误导 KP/玩家
- 保持原有世界观和恐怖氛围

---

## 四、叙事 prompt 保留可触发事件（调整）

`build_narrative_prompt` 中通过已更新的 abstract/description 承载已发生事件的文学性后果，同时保留"可触发事件"列表作为辅助上下文。

### 新增辅助函数

```python
def _build_triggerable_events(world: ScenarioWorld) -> str:
    """从 world 确定性提取：条件已满足、可触发但尚未触发的全局事件"""
    lines = []
    for ev in world.graph.events.values():
        if not world.is_event_triggered(ev.event_id):
            met, _ = world.requirement_resolver.check(ev.requirements)
            if met:
                lines.append(
                    f"  ◇ [{ev.event_id}] {ev.name}\n"
                    f"    触发条件：{ev.trigger}\n"
                    f"    预期影响：{ev.impact[:150]}"
                )
    return "\n\n".join(lines) if lines else "（暂无可触发事件）"
```

### prompt 结构

```
【模组背景设定】（已被世界更新修改过的 abstract）
【玩家历史行动】
【当前场景描述】（已被世界更新修改过的 description）
【玩家输入】
【行动结果】（来自阶段1）
【技能鉴定结果】
【本轮触发事件】（来自阶段2 events_result）
【当前可触发的全局事件】（确定性提取，辅助叙事）
  ◇ [E5] 先头车厢的真相
    触发条件：进入先头车厢
    预期影响：揭示电车运行的真相，最终抉择...
```

---

## 五、`handle_user_input` 完整伪代码

```python
def handle_user_input(user_input: str, world: ScenarioWorld) -> str:
    # ── 阶段1 & 阶段2：并行 ──
    action_data = call_llm(build_action_prompt(world, user_input), json_mode=True)
    event_data  = call_llm(build_event_prompt(world, user_input), json_mode=True)

    # ── 阶段1：执行动作 ──
    skill_results = SkillSystem.check_multiple(world.player, action_data.get("skill_checks", []))
    action_result = execute_action(world, action_data, skill_results)

    # ── 阶段2：执行事件 ──
    events_result = execute_events(world, event_data)

    # ── 阶段1.5a：动作世界更新 ──
    update = call_llm(build_action_world_update(action_result, world), json_mode=True)
    world.apply_world_update(update["abstract"], update["description"])

    # ── 阶段1.5b：事件世界更新（仅当有触发事件时）──
    if event_data.get("triggered_events"):
        update = call_llm(build_event_world_update(events_result, world), json_mode=True)
        world.apply_world_update(update["abstract"], update["description"])

    # ── 阶段3：叙事生成 ──
    narrative = call_llm(build_narrative_prompt(world, user_input, action_result, events_result), json_mode=False)

    # ── 记录 ──
    world.memory.add_record(user_input, action_data.get("action"), ...)
    if world.memory.should_compress():
        world.memory.compress(lambda p: call_llm(p, json_mode=False))

    return narrative
```

---

## 涉及文件汇总

| 文件 | 改动 |
|------|------|
| `src/scenario_core.py` | MemoryManager 精简（去 npc_clues、note_discovery→note_item）；ScenarioWorld 新增 `memory`、`apply_world_update()` |
| `notebooks/notebook_simplified.ipynb` | 新增 `build_action_world_update`、`build_event_world_update`、`_build_triggerable_events`；重写 `build_event_prompt`；重构 `build_narrative_prompt`、`build_action_prompt`（memory 从 world 取）；重写 `handle_user_input`；适配 `run_game` |
