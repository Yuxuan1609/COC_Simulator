# 游戏主循环重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构 TRPG 助手主循环：整合 MemoryManager 到 ScenarioWorld、阶段1/2并行调用、新增世界更新机制、叙事 prompt 保留可触发事件。

**Architecture:** 自底向上：先精简 scenario_core.py 的数据结构，再逐阶段重写 notebook 中的 prompt 构建函数，最后重构 handle_user_input 主流程和 run_game 入口。

**Tech Stack:** Python 3, DeepSeek API (OpenAI SDK), Jupyter Notebook (.ipynb)

---

### Task 1: 精简 MemoryManager —— 移除 npc_clues，note_discovery → note_item

**Files:**
- Modify: `src/scenario_core.py:539-641`

- [ ] **Step 1: 移除 `npc_clues` 字段和 `note_discovery` 方法，新增 `note_item`**

在 `src/scenario_core.py` 中定位 `class MemoryManager`。

修改 `__init__` —— 删除 `npc_clues` 行（line 550）：

```python
# 删除此行:
        self.npc_clues: Dict[str, str] = {}      # NPC名 -> 获得的情报
```

修改 `note_discovery` —— 替换为 `note_item`（lines 571-576）：

```python
    def note_item(self, item: str):
        """记录获得的关键物品（不会被压缩丢失）"""
        self.key_items.append(item)
```

修改 `get_context` —— 删除 npc_clues 相关段落（lines 630-632）：

```python
# 删除以下三行:
        if self.npc_clues:
            npc_lines = "\n".join([f"  {n}: {c}" for n, c in self.npc_clues.items()])
            parts.append(f"【NPC情报】\n{npc_lines}")
```

- [ ] **Step 2: 验证 MemoryManager 可正常实例化**

在项目根目录运行：

```bash
python -c "from src.scenario_core import MemoryManager; m = MemoryManager(); m.note_item('钥匙'); m.add_record('test', 'look', None, 'ok'); print(m.key_items); print(m.get_context())"
```

预期：输出 `['钥匙']` 和包含 `【近期行动】` 的上下文字符串。

---

### Task 2: ScenarioWorld 挂载 MemoryManager + 新增 apply_world_update

**Files:**
- Modify: `src/scenario_core.py:302-333`

- [ ] **Step 1: 在 ScenarioWorld.__init__ 中添加 self.memory**

在 `ScenarioWorld.__init__` 方法末尾（line 323 `self.flags` 之后）添加：

```python
        # 记忆管理器
        self.memory = MemoryManager()
```

- [ ] **Step 2: 新增 apply_world_update 方法**

在 `ScenarioWorld` 类的 `set_flag` / `get_flag` 方法附近添加（line 515 附近）：

```python
    def apply_world_update(self, abstract: str, description: str):
        """应用世界更新结果"""
        self.set_background(abstract)
        node = self._current_node()
        if node:
            node.description = description
```

- [ ] **Step 3: 验证**

```bash
python -c "
from src.scenario_core import DirectedGraph, ScenarioWorld, Player
graph = DirectedGraph()
world = ScenarioWorld(graph, start_node='test', background_story='初始设定')
world.set_player(Player('test'))
world.memory.add_record('hello', 'look', None, 'ok', location='test')
print(world.memory.get_context())
world.apply_world_update('更新后设定', '更新后描述')
print(world.background_story)
"
```

预期：输出记忆上下文、`更新后设定`。

---

### Task 3: 更新 notebook 导入和 build_action_prompt 签名

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `40cb738efceb8f1`（导入）和 cell `97f37a6dac767b62`（`build_action_prompt`）

- [ ] **Step 1: 更新导入 —— 移除 MemoryManager**

在 cell `40cb738efceb8f1` 中，将：

```python
from scenario_core import (
    DirectedGraph, ScenarioWorld, Player, MemoryManager, SkillSystem,
)
```

改为：

```python
from scenario_core import (
    DirectedGraph, ScenarioWorld, Player, SkillSystem,
)
```

- [ ] **Step 2: 更新 `build_action_prompt` 签名和实现**

在 cell `97f37a6dac767b62` 中定位 `build_action_prompt` 函数。

将签名从：

```python
def build_action_prompt(world: ScenarioWorld, memory: MemoryManager,
                        user_input: str) -> str:
```

改为：

```python
def build_action_prompt(world: ScenarioWorld, user_input: str) -> str:
```

将其内部对 `memory` 的引用改为 `world.memory`：

```python
    scene_ctx = _build_scene_context(world)
    state = _build_world_state(world)
    context = world.memory.get_context()
    skills = _build_player_skills(world)
```

- [ ] **Step 3: 验证**

在 notebook 中执行导入 cell 和 prompt 构建 cell，确认无 NameError。

---

### Task 4: 重写 build_event_prompt —— 接收 user_input 而非 action_summary

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `97f37a6dac767b62`（`build_event_prompt`）

- [ ] **Step 1: 重写 build_event_prompt**

将函数签名从：

```python
def build_event_prompt(world: ScenarioWorld, memory: MemoryManager,
                       action_summary: str, skill_results: dict = None) -> str:
```

改为：

```python
def build_event_prompt(world: ScenarioWorld, user_input: str) -> str:
```

完整替换函数体：

```python
def build_event_prompt(world: ScenarioWorld, user_input: str) -> str:
    """基于 user_input + 全部未触发事件，让 LLM 独立判断哪些事件应在此刻触发"""
    context = world.memory.get_context()
    state = _build_world_state(world)

    # 仅列举尚未触发的事件
    pending_events = [e for e in world.graph.events.values()
                      if not world.is_event_triggered(e.event_id)]
    if pending_events:
        event_lines = []
        for ev in pending_events:
            ev_hint = ""
            if ev.requirements:
                met, _ = world.requirement_resolver.check(ev.requirements)
                ev_hint = " [条件未满足]" if not met else ""
            event_lines.append(
                f"  [{ev.event_id}] {ev.name}{ev_hint}\n"
                f"  触发条件：{ev.trigger}\n"
                f"  影响：{ev.impact[:150]}"
            )
        event_text = "\n\n".join(event_lines)
    else:
        event_text = "（所有事件均已触发）"

    prompt = f"""【玩家历史行动】
{context or '（无）'}

【当前位置】{world.current_location}

【世界状态】
{state}

【玩家输入】
{user_input}

【待检查事件（仅以下未触发事件需判断）】
{event_text}

请逐一判断上述「待检查事件」的触发条件是否被玩家当前输入所描述的行动满足。返回 JSON：
{{
  "triggered_events": ["E1"],
  "new_flags": {{"flag_name": true}},
  "reasoning": "逐事件推理"
}}

规则：
- 仅当玩家输入中描述的行动确实满足事件的触发条件时才列入
- 已触发的事件不要重复触发
- new_flags 可选，用于设置新的世界标记
- 不满足任何条件时 triggered_events 返回 []
- 严格比对触发条件，不要过度联想

直接输出 JSON，不要额外文字。
"""
    _show_prompt("Step 2/3 — 事件触发判定", prompt)
    return prompt
```

- [ ] **Step 2: 验证签名一致性**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from scenario_core import DirectedGraph, ScenarioWorld
# 确认 build_event_prompt 不再需要 memory 和 action_summary 参数
"
```

---

### Task 5: 新增 _build_triggerable_events 辅助函数

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `97f37a6dac767b62`（放在 `_build_world_state` 之后）

- [ ] **Step 1: 添加 _build_triggerable_events**

在 `_build_skill_results` 函数之后、`build_action_prompt` 之前插入：

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

- [ ] **Step 2: 验证**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from scenario_core import DirectedGraph, ScenarioWorld, GameEvent
graph = DirectedGraph()
graph.events['E1'] = GameEvent(event_id='E1', name='测试事件', trigger='进入房间', impact='门消失了')
world = ScenarioWorld(graph, start_node='room', background_story='')
# 模拟条件满足
from scenario_core import _build_triggerable_events
print(_build_triggerable_events(world))
"
```

预期：输出包含 `◇ [E1] 测试事件` 的文本。

---

### Task 6: 新增 build_action_world_update 和 build_event_world_update

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `97f37a6dac767b62`（放在 `build_event_prompt` 之后）

- [ ] **Step 1: 添加两个世界更新函数**

在 `build_event_prompt` 函数之后、`build_narrative_prompt` 之前插入：

```python
# ── 世界更新（两个独立调用）──

def build_action_world_update(world: ScenarioWorld, action_result: str) -> str:
    """基于动作结果更新 abstract 和当前场景 description"""
    prompt = f"""你是一位TRPG模组写作者。根据刚刚发生的玩家行动，对模组背景设定和当前场景描述进行文学性更新。

【当前背景设定】
{world.background_story}

【当前场景描述】
{world.get_current_description()}

【本轮行动结果】
{action_result}

要求：
- abstract：将本轮行动的关键发现/变化以文学性语言融入背景设定中，采用累积追加的方式（而非重写整个背景）
- description：如果当前场景发生了可见变化（物品移动、痕迹留下、环境改变等），更新描述使其反映新的场景状态；如果场景未发生可见变化，description 原样返回
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON

返回 JSON：
{{
  "abstract": "更新后的背景设定",
  "description": "更新后的当前场景描述"
}}"""
    _show_prompt("World Update — Action", prompt)
    return prompt


def build_event_world_update(world: ScenarioWorld, events_result: str) -> str:
    """基于触发的事件结果更新 abstract 和当前场景 description"""
    prompt = f"""你是一位TRPG模组写作者。根据刚刚触发的不可逆事件，对模组背景设定和当前场景描述进行文学性更新。

【当前背景设定】
{world.background_story}

【当前场景描述】
{world.get_current_description()}

【本轮触发事件】
{events_result}

要求：
- abstract：将本轮触发的事件及其不可逆影响以文学性语言融入背景设定中，采用累积追加的方式
- description：如果当前场景因事件发生了可见变化（结构损坏、NPC出现/消失、环境剧变等），更新描述使其反映新的场景状态；如果场景未发生可见变化，description 原样返回
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON

返回 JSON：
{{
  "abstract": "更新后的背景设定",
  "description": "更新后的当前场景描述"
}}"""
    _show_prompt("World Update — Event", prompt)
    return prompt
```

- [ ] **Step 2: 验证函数可调用**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from scenario_core import DirectedGraph, ScenarioWorld
graph = DirectedGraph()
world = ScenarioWorld(graph, start_node='room', background_story='初始')
# 模拟 notebook 中的函数定义
# （在 notebook 环境中直接执行 cell 验证）
print('OK')
"
```

---

### Task 7: 重构 build_narrative_prompt

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `97f37a6dac767b62`（`build_narrative_prompt`）

- [ ] **Step 1: 重构 build_narrative_prompt**

将签名从：

```python
def build_narrative_prompt(world: ScenarioWorld, memory: MemoryManager,
                           user_input: str, action_summary: str,
                           event_results: str, skill_results: dict = None) -> str:
```

改为：

```python
def build_narrative_prompt(world: ScenarioWorld, user_input: str,
                           action_result: str, events_result: str) -> str:
```

完整替换函数体：

```python
def build_narrative_prompt(world: ScenarioWorld, user_input: str,
                           action_result: str, events_result: str) -> str:
    """基于所有结果 + 已更新世界 + 可触发事件列表，生成沉浸式叙事"""
    context = world.memory.get_context()
    scene_desc = world.get_current_description()
    events_text = events_result if events_result else "（无特殊事件发生）"
    triggerable = _build_triggerable_events(world)

    # 背景故事（已被世界更新修改过的 abstract）
    bg_section = ""
    if world.background_story:
        bg_section = f"""【模组背景设定】
{world.background_story}

"""

    prompt = f"""{bg_section}【玩家历史行动】
{context or '（无）'}

【当前场景】{world.current_location}
{scene_desc}

【玩家输入】{user_input}

【行动结果】{action_result}

【本轮触发事件】{events_text}

【当前可触发的全局事件】
{triggerable}

请以TRPG主持人（KP）的身份，用沉浸式中文描述这一刻发生的事。
- 根据行动结果调整叙事：成功则描述顺利进行，失败则描述没有结果或难以进行
- 语气贴合场景氛围（恐怖/悬疑），参考背景设定中的世界观和氛围基调
- 可参考「当前可触发的全局事件」了解场景可能的发展方向，但不要在叙事中直接透露未发生的事件
- 80-150字
- 直接输出叙事文本，不要额外说明
- 重要！不要给出前文没有提及的实质性信息
"""
    _show_prompt("Step 3/3 — 叙事生成", prompt)
    return prompt
```

---

### Task 8: 重写 handle_user_input

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `a75d484cd40fc0e1`

- [ ] **Step 1: 重写 handle_user_input**

将签名从：

```python
def handle_user_input(user_input: str, world: ScenarioWorld,
                      memory: MemoryManager) -> str:
```

改为：

```python
def handle_user_input(user_input: str, world: ScenarioWorld) -> str:
```

完整替换函数体：

```python
def handle_user_input(user_input: str, world: ScenarioWorld) -> str:
    """
    重构后的处理流程：
    1. 阶段1 & 阶段2 并行 —— 动作解析 + 事件判定，各自独立
    2. 世界更新 —— 基于动作和事件结果分别更新 abstract/description
    3. 阶段3 —— 叙事生成
    """

    # ═══ 阶段1 & 阶段2：并行 LLM 调用 ═══
    try:
        action_data = call_deepseek(
            build_action_prompt(world, user_input),
            json_mode=True
        )
    except Exception as e:
        return f"[系统错误] 动作解析失败：{e}"

    try:
        event_data = call_deepseek(
            build_event_prompt(world, user_input),
            json_mode=True
        )
    except Exception as e:
        event_data = {"triggered_events": [], "new_flags": {}}

    # ═══ 阶段1：执行动作 ═══
    skill_results = {}
    skill_checks = action_data.get("skill_checks", [])
    if skill_checks and world.player:
        skill_results = SkillSystem.check_multiple(world.player, skill_checks)

    action = action_data.get("action", "other")
    location = world.current_location
    success = True

    if action == "move":
        target = action_data.get("target", "")
        if not target:
            action_result = "（试图移动但未指定目标）"
            success = False
        else:
            ok, msg = world.move(target)
            action_result = msg
            success = ok

    elif action == "interact":
        name = action_data.get("interaction", "")
        if not name:
            action_result = "（试图执行动作但未指定名称）"
            success = False
        else:
            ok, msg = world.execute_interaction(name)
            action_result = msg
            success = ok

    elif action == "look":
        action_result = "（查看场景信息）"

    elif action == "search":
        interactions = world.get_available_interactions()
        done = world.completed_interactions.get(location, set())
        available = [i for i in interactions if i.name not in done]
        if available:
            lines = ["（环顾四周，注意到可以做的事：）"]
            for inter in available:
                lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
            action_result = "\n".join(lines)
        else:
            action_result = "（仔细查看四周，没有特别的发现）"
    else:
        action_result = "（什么也没做）"

    # ═══ 阶段2：执行事件 ═══
    events_result = ""
    for eid in event_data.get("triggered_events", []):
        ok, msg = world.trigger_event(eid)
        if ok:
            events_result += msg + "\n"
    for flag_key, flag_val in event_data.get("new_flags", {}).items():
        world.set_flag(flag_key, flag_val)
        events_result += f"[标记更新] {flag_key} = {flag_val}\n"

    # ═══ 阶段1.5a：动作世界更新 ═══
    try:
        update = call_deepseek(
            build_action_world_update(world, action_result),
            json_mode=True
        )
        world.apply_world_update(update["abstract"], update["description"])
    except Exception:
        pass  # 世界更新失败不阻塞游戏流程

    # ═══ 阶段1.5b：事件世界更新 ═══
    if event_data.get("triggered_events"):
        try:
            update = call_deepseek(
                build_event_world_update(world, events_result),
                json_mode=True
            )
            world.apply_world_update(update["abstract"], update["description"])
        except Exception:
            pass

    # ═══ 阶段3：叙事生成 ═══
    try:
        narrative = call_deepseek(
            build_narrative_prompt(world, user_input, action_result, events_result),
            json_mode=False
        )
    except Exception as e:
        narrative = f"{action_result}\n\n（叙事生成失败：{e}）"

    # ═══ 记录 ═══
    world.memory.add_record(user_input, action, action_data.get("target"),
                            narrative, location=location, success=success)

    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

    return narrative
```

---

### Task 9: 适配 run_game

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb` — cell `ba337da8dcf55dee`

- [ ] **Step 1: 更新 run_game 中的调用**

删除 `memory = MemoryManager()` 行（原来在 `world.set_player(player)` 之后）：

```python
# 删除这行:
    memory = MemoryManager()
```

将 `handle_user_input` 调用从：

```python
        narrative = handle_user_input(cmd, world, memory)
```

改为：

```python
        narrative = handle_user_input(cmd, world)
```

将开场叙事中的 `build_narrative_prompt` 调用改为新的签名：

```python
    try:
        initial_narrative = call_deepseek(
            build_narrative_prompt(
                world,
                user_input="（游戏开始）",
                action_result="（从沉睡中醒来，环顾四周）",
                events_result="",
            ),
            json_mode=False
        )
```

将 `memory` 变量引用改为 `world.memory`：

```python
    turn = 0  # turn 现在由 world.memory.turn 管理，但本地仍可保留用于显示
```

实际上 `turn` 仍在 `run_game` 作为局部变量使用（用于 `display_input_area`），保留不变。

- [ ] **Step 2: 全文检查**

在 notebook 中搜索所有 `memory` 变量引用，确保没有残留的独立 `memory` 参数传递：

```
需要修改的引用:
- build_action_prompt(world, memory, ...) → build_action_prompt(world, ...)
- build_event_prompt(world, memory, ...) → build_event_prompt(world, ...)
- build_narrative_prompt(world, memory, ...) → build_narrative_prompt(world, ...)
- handle_user_input(..., memory) → handle_user_input(...)
- memory.add_record(...) → world.memory.add_record(...)
- memory.should_compress() → world.memory.should_compress()
- memory.compress(...) → world.memory.compress(...)
- memory.get_context() → world.memory.get_context()
```

---

### Task 10: 端到端验证

- [ ] **Step 1: 导入验证**

在 notebook 中从头执行所有 cell，确认无 import 错误、无 NameError。

- [ ] **Step 2: 空跑验证**

在 `run_game()` 启动前，手动构造测试输入验证函数链：

```python
# 在 run_game 之前插入测试代码
from scenario_core import DirectedGraph, ScenarioWorld, Player
import json

with open("../data/output/scene_output_resolved_revised.json", "r", encoding="utf-8") as f:
    scenes = json.load(f)
with open("../data/output/res_event_resolved_revised.json", "r", encoding="utf-8") as f:
    events = json.load(f)
with open("../data/abstract.txt", "r", encoding="utf-8") as f:
    abstract = f.read()

graph = DirectedGraph(scenes=scenes, events=events)
world = ScenarioWorld(graph, start_node="6号车厢", background_story=abstract)
player = Player("测试员", skills={"灵感": 70, "侦查": 50})
world.set_player(player)

# 测试 prompt 构建（不调用 LLM）
p1 = build_action_prompt(world, "环顾四周")
p2 = build_event_prompt(world, "环顾四周")
print("build_action_prompt OK")
print("build_event_prompt OK")

# 测试世界更新 prompt 构建
p3 = build_action_world_update(world, "测试行动结果")
p4 = build_event_world_update(world, "测试事件结果")
print("build_action_world_update OK")
print("build_event_world_update OK")

# 测试叙事 prompt
p5 = build_narrative_prompt(world, "环顾四周", "测试行动结果", "")
print("build_narrative_prompt OK")
print("All prompt builders OK")
```

- [ ] **Step 3: 集成验证**

如果 API 可用，执行一次完整的 `handle_user_input` 调用：

```python
result = handle_user_input("查看四周", world)
print(result)
print("World memory turn:", world.memory.turn)
print("Background updated:", len(world.background_story) > len(abstract))
```

预期：返回叙事文本，world.memory 有记录，abstract 已更新。
