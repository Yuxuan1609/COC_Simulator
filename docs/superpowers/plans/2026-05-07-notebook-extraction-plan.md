# Notebook 函数提取至 .py 模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 notebook 中的独立函数提取到 `src/` 模块，notebook 只保留导入、日志配置、`run_game` 入口。

**Architecture:** 三层拆分 —— `src/llm.py`（LLM 调用）、`src/prompts.py`（prompt 构建）、`src/game_loop.py`（游戏逻辑）。notebook 变为薄层接线器。不改变任何函数行为。

**Tech Stack:** Python 3, DeepSeek API (OpenAI SDK), Jupyter Notebook

**文件结构变更：**

```
src/
  llm.py           # + call_deepseek (统一入口)
  prompts.py       # NEW: 所有 prompt 构建器 + _show_prompt
  game_loop.py     # NEW: _execute_single_action + handle_user_input

notebooks/
  notebook_simplified.ipynb  # 4 cells: 导入, 配置, run_game, 启动
```

---

### Task 1: 在 `src/llm.py` 中添加统一 `call_deepseek`

**Files:**
- Modify: `src/llm.py`

**Context:** 现有 `call_deepseek_json`、`call_deepseek_write`、`call_deepseek_summarize` 三个函数保留不动（被 `pipeline.py`、`parsers.py` 引用）。新增统一入口 `call_deepseek(prompt, json_mode, system)` 供 notebook/game_loop 使用。

- [ ] **Step 1: 在 `_extract_json` 之后、`call_deepseek_json` 之前插入 `call_deepseek`**

```python
def call_deepseek(prompt: str, *, json_mode: bool = True,
                  system: str = None) -> dict | str:
    """
    统一 DeepSeek 调用入口。
    json_mode=True  → 返回解析后的 dict（用于结构化判定）
    json_mode=False → 返回原始文本（用于叙事生成/压缩）
    """
    if json_mode:
        model = "deepseek-v4-pro"
        default_system = "你是一个严格的规则判定助手，仅按给定条件输出 JSON。"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=16284,
            reasoning_effort="high",
            extra_body={"thinking": {"type": "enabled"}}
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```json"):
            raw = raw[7:-3].strip()
        elif raw.startswith("```"):
            raw = raw[3:-3].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            content = _extract_json(raw)
            return json.loads(content)
    else:
        model = "deepseek-v4-pro"
        default_system = "你是一个专业的TRPG主持人（KP），根据给定信息输出沉浸式中文叙事。"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        return response.choices[0].message.content.strip()
```

- [ ] **Step 2: 验证**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
from src.llm import call_deepseek, call_deepseek_json, call_deepseek_write
print('import OK')
# 验证旧函数仍可用
assert callable(call_deepseek_json)
assert callable(call_deepseek_write)
assert callable(call_deepseek)
print('all callable OK')
"
```

---

### Task 2: 创建 `src/prompts.py`

**Files:**
- Create: `src/prompts.py`

- [ ] **Step 1: 创建 `src/prompts.py`**

```python
"""
Prompt 构建器 —— 为 LLM 调用链构建结构化 prompt。

所有 build_* 函数只负责构造 prompt 字符串，不发起 LLM 调用。
通过 set_prompt_log_file() 配置日志输出路径。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld

# ── 日志配置 ──

_log_file: str | None = None


def set_prompt_log_file(path: str):
    """设置 prompt 日志文件路径。调用后所有 build_* 函数会将 prompt 写入该文件。"""
    global _log_file
    _log_file = path


def _show_prompt(label: str, content: str):
    """将 prompt 写入日志文件（如已配置）"""
    if not _log_file:
        return
    with open(_log_file, 'a', encoding='utf-8') as f:
        f.write(f"{'='*60}\n")
        f.write(f"=== {label} ===\n")
        f.write(f"{'='*60}\n")
        f.write(content)
        f.write("\n")


# ── 场景上下文（确定性，不依赖 LLM）──

def _build_scene_context(world: ScenarioWorld) -> str:
    """从 graph 获取当前场景的稳定上下文（不含世界状态）"""
    node = world._current_node()
    if not node:
        return "未知地点"

    exits = world.get_possible_exits()
    exit_list = "\n".join([
        f"  → {e.target}：{e.method}" for e in exits
    ]) or "（无）"

    interactions = world.get_available_interactions()
    done = world.completed_interactions.get(world.current_location, set())
    available = [i for i in interactions if i.name not in done]

    interaction_lines = []
    for i in available:
        hint = " [需要前置]" if not world._are_requirements_met(i) else ""
        interaction_lines.append(
            f'  名称（请原样复制）：「{i.name}」{hint}\n'
            f'  类型：{i.type}\n'
            f'  触发条件：{i.trigger}\n'
            f'  结果：{i.result[:120]}'
        )
    interaction_text = "\n\n".join(interaction_lines) if interaction_lines else "（当前场景无可执行动作）"

    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}

【可移动方向】
{exit_list}

【可执行动作】
{interaction_text}"""


def _build_player_skills(world: ScenarioWorld) -> str:
    """构建玩家技能列表"""
    if not world.player or not world.player.skills:
        return "（无技能数据）"
    return ", ".join(f"{name}={value}" for name, value in world.player.skills.items())


def _build_skill_results(skill_results: dict) -> str:
    """构建技能鉴定结果文本"""
    if not skill_results:
        return "（本次无技能鉴定）"
    lines = []
    for skill_name, (success, msg) in skill_results.items():
        status = "成功" if success else "失败"
        lines.append(f"  {skill_name}：{status} — {msg}")
    return "\n".join(lines)


def _build_world_state(world: ScenarioWorld) -> str:
    """从 world 获取当前状态摘要"""
    triggered = [eid for eid, t in world.triggered_events.items() if t]
    flags_str = ", ".join(f"{k}={v}" for k, v in world.flags.items()) or "（无）"
    return f"""已触发事件：{triggered or '（无）'}
世界标记：{flags_str}"""


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


# ── 第一阶段：动作解析 ──

def build_action_prompt(world: ScenarioWorld, user_input: str) -> str:
    """基于当前场景 JSON 信息，让 LLM 判断玩家意图，支持多动作识别"""
    scene_ctx = _build_scene_context(world)
    state = _build_world_state(world)
    context = world.memory.get_context()
    skills = _build_player_skills(world)

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

【玩家技能】
{skills}

{scene_ctx}

【玩家输入】
{user_input}

请判断玩家意图。玩家输入可能包含单个或多个连续意图（如"先检查桌子然后去7号车厢"），请按先后顺序拆分为多个动作。返回 JSON：
{{
  "actions": [
    {{
      "action": "move" | "interact" | "search" | "other",
      "target": "目标地点（仅 move 时填写）",
      "interaction": "动作名称（仅 interact 时填写，务必从上述「名称（请原样复制）」中精确复制）",
      "skill_checks": ["技能名"],
      "reasoning": "简要推理"
    }}
  ]
}}

规则：
- move：玩家明确想前往某方向/地点 → target 填「可移动方向」中列出的目标
- interact：玩家意图匹配某个可执行动作 → interaction 务必精确复制名称
- search：玩家想探索但无法精确匹配任何动作
- other：其他动作类型（不产生实际影响）
- skill_checks：根据动作的触发条件，列出需要鉴定的技能名称（如 侦查、灵感、急救 等），
  技能必须是玩家拥有的。无需鉴定时返回空数组 []，仅对 move 和 interact 生效
- 如果玩家输入只有单一意图，actions 数组仍包含 1 个元素
- actions 按玩家输入中的先后顺序排列

直接输出 JSON，不要额外文字。
"""
    _show_prompt("Step 1/3 — 动作解析", prompt)
    return prompt


# ── 第二阶段：事件触发判定 ──

def build_event_prompt(world: ScenarioWorld, user_input: str) -> str:
    """基于 user_input + 全部未触发事件，让 LLM 独立判断哪些事件应在此刻触发"""
    context = world.memory.get_context()
    state = _build_world_state(world)

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


# ── 世界更新 ──

def build_action_world_update(world: ScenarioWorld, action_result: str, user_input: str) -> str:
    """基于动作结果更新当前场景 description"""
    prompt = f"""你是一位TRPG模组写作者。根据刚刚发生的玩家行动，对模组背景设定和当前场景描述进行文学性更新。

【当前背景设定】
{world.background_story}

【当前场景描述】
{world.get_current_description()}

【玩家输入】
{user_input}

【本轮行动结果】
{action_result}

要求：
- description：如果当前场景发生了可见变化（物品移动、痕迹留下、环境改变等），更新描述使其反映新的场景状态；如果场景未发生可见变化，description 原样返回
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON

返回 JSON：
{{
  "description": "更新后的当前场景描述"
}}"""
    _show_prompt("World Update — Action", prompt)
    return prompt


def build_event_world_update(world: ScenarioWorld, events_result: str) -> str:
    """基于触发的事件结果更新 abstract"""
    prompt = f"""你是一位TRPG模组写作者。根据刚刚触发的不可逆事件，对模组背景设定和当前场景描述进行文学性更新。

【当前背景设定】
{world.background_story}

【当前场景描述】
{world.get_current_description()}

【本轮触发事件】
{events_result}

要求：
- abstract：将本轮触发的事件及其不可逆影响以文学性语言融入背景设定中，采用累积追加的方式
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON

返回 JSON：
{{
  "abstract": "更新后的背景设定",
}}"""
    _show_prompt("World Update — Event", prompt)
    return prompt


# ── 第三阶段：叙事生成 ──

def build_narrative_prompt(world: ScenarioWorld, user_input: str,
                           action_result: str, events_result: str) -> str:
    """基于所有结果 + 已更新世界 + 可触发事件列表，生成沉浸式叙事"""
    context = world.memory.get_context()
    scene_desc = world.get_current_description()
    events_text = events_result if events_result else "（无特殊事件发生）"

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


请以TRPG主持人（KP）的身份，用沉浸式中文描述这一刻发生的事。
- 根据行动结果调整叙事：成功则描述顺利进行，失败则描述没有结果或难以进行
- 语气贴合场景氛围（恐怖/悬疑），参考背景设定中的世界观和氛围基调
- 80-150字
- 直接输出叙事文本，不要额外说明
- 重要！不要给出前文没有提及的实质性信息
"""
    _show_prompt("Step 3/3 — 叙事生成", prompt)
    return prompt
```

- [ ] **Step 2: 验证导入**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
import sys; sys.path.insert(0, 'src')
from scenario_core import DirectedGraph, ScenarioWorld, Player
import json

# 加载真实数据
with open('data/output/scene_output_resolved_revised.json', 'r', encoding='utf-8') as f:
    scenes = json.load(f)
with open('data/output/res_event_resolved_revised.json', 'r', encoding='utf-8') as f:
    events = json.load(f)
with open('data/abstract.txt', 'r', encoding='utf-8') as f:
    abstract = f.read()

graph = DirectedGraph(scenes=scenes, events=events)
world = ScenarioWorld(graph, start_node='6号车厢', background_story=abstract)
player = Player('test', skills={'灵感':70})
world.set_player(player)

from prompts import (
    build_action_prompt, build_event_prompt, build_narrative_prompt,
    build_action_world_update, build_event_world_update,
    set_prompt_log_file,
)
set_prompt_log_file('logs/test_prompts.log')
p1 = build_action_prompt(world, '查看四周')
p2 = build_event_prompt(world, '查看四周')
p3 = build_narrative_prompt(world, '查看四周', 'ok', '')
print(f'build_action_prompt: {len(p1)} chars')
print(f'build_event_prompt: {len(p2)} chars')
print(f'build_narrative_prompt: {len(p3)} chars')
print('All prompt builders OK')
"
```

---

### Task 3: 创建 `src/game_loop.py`

**Files:**
- Create: `src/game_loop.py`

- [ ] **Step 1: 创建 `src/game_loop.py`**

```python
"""
游戏主循环 —— 动作执行 + LLM 调用链编排。

从 notebook_simplified.ipynb 提取，不包含 UI 逻辑。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld

from scenario_core import SkillSystem
from llm import call_deepseek
from prompts import (
    build_action_prompt,
    build_event_prompt,
    build_action_world_update,
    build_event_world_update,
    build_narrative_prompt,
)


def _execute_single_action(act: dict, world: ScenarioWorld, location: str) -> tuple:
    """执行单个动作，返回 (result_text, success)"""
    action = act.get("action", "other")

    skill_checks = act.get("skill_checks", [])
    if skill_checks and world.player:
        SkillSystem.check_multiple(world.player, skill_checks)

    if action == "move":
        target = act.get("target", "")
        if not target:
            return "（试图移动但未指定目标）", False
        ok, msg = world.move(target)
        return msg, ok

    elif action == "interact":
        name = act.get("interaction", "")
        if not name:
            return "（试图执行动作但未指定名称）", False
        ok, msg = world.execute_interaction(name)
        return msg, ok

    elif action == "look":
        return "（查看场景信息）", True

    elif action == "search":
        interactions = world.get_available_interactions()
        done = world.completed_interactions.get(location, set())
        available = [i for i in interactions if i.name not in done]
        if available:
            lines = ["（环顾四周，注意到可以做的事：）"]
            for inter in available:
                lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
            return "\n".join(lines), True
        else:
            return "（仔细查看四周，没有特别的发现）", True
    else:
        return "（什么也没做）", True


def handle_user_input(user_input: str, world: ScenarioWorld) -> str:
    """
    处理流程：
    1. 阶段1 & 阶段2 并行 —— 动作解析 + 事件判定
    2. 阶段1a：执行 interact/search/look 等场景内动作
    3. 阶段1.5a：动作世界更新（基于 interact 结果更新场景描述）
    4. 阶段1b：执行 move 动作（在已更新的场景中移动）
    5. 阶段2：执行事件
    6. 阶段1.5b：事件世界更新
    7. 阶段3：叙事生成
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

    # ═══ 阶段1a：执行场景内动作 ═══
    actions = action_data.get("actions", [])
    if not actions:
        actions = [{"action": "other"}]

    location = world.current_location
    scene_actions = [a for a in actions if a.get("action") != "move"]
    move_actions = [a for a in actions if a.get("action") == "move"]

    action_results = []
    overall_success = True

    for act in scene_actions:
        result, success = _execute_single_action(act, world, location)
        action_results.append(result)
        if not success:
            overall_success = False

    # ═══ 阶段1.5a：动作世界更新（在移动之前）═══
    had_interact = any(a.get("action") == "interact" for a in scene_actions)
    if had_interact:
        scene_action_result = "\n".join(action_results)
        try:
            update = call_deepseek(
                build_action_world_update(world, scene_action_result, user_input),
                json_mode=True
            )
            world.apply_scene_update(update["description"])
        except Exception:
            pass

    # ═══ 阶段1b：执行 move 动作 ═══
    for act in move_actions:
        result, success = _execute_single_action(act, world, location)
        action_results.append(result)
        if not success:
            overall_success = False

    action_result = "\n".join(action_results)

    # ═══ 阶段2：执行事件 ═══
    events_result = ""
    for eid in event_data.get("triggered_events", []):
        ok, msg = world.trigger_event(eid)
        if ok:
            events_result += msg + "\n"
    for flag_key, flag_val in event_data.get("new_flags", {}).items():
        world.set_flag(flag_key, flag_val)
        events_result += f"[标记更新] {flag_key} = {flag_val}\n"

    # ═══ 阶段1.5b：事件世界更新 ═══
    if event_data.get("triggered_events"):
        try:
            update = call_deepseek(
                build_event_world_update(world, events_result),
                json_mode=True
            )
            world.apply_world_update(update["abstract"])
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
    first_action = actions[0].get("action", "other")
    first_target = actions[0].get("target")
    world.memory.add_record(user_input, first_action, first_target,
                            narrative, location=location, success=overall_success)

    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

    return narrative
```

- [ ] **Step 2: 验证导入和函数签名**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
import sys; sys.path.insert(0, 'src')
from game_loop import handle_user_input, _execute_single_action
print('game_loop imports OK')
print(f'handle_user_input: {handle_user_input}')
print(f'_execute_single_action: {_execute_single_action}')
"
```

---

### Task 4: 简化 Notebook

**Files:**
- Modify: `notebooks/notebook_simplified.ipynb`

删除所有已提取到 `src/` 的代码，保留 4 个 cell。

- [ ] **Step 1: 替换 cell `40cb738efceb8f1`（导入）**

```python
# ═══════════════════════════════════════════════════════════════
#  TRPG 调查员助手 —— 主流程 Notebook
# ═══════════════════════════════════════════════════════════════

import sys
import json
from datetime import datetime
from IPython.display import HTML, display

# 将 src/ 加入路径以导入依赖模块
sys.path.insert(0, "../src")

from scenario_core import DirectedGraph, ScenarioWorld, Player, SkillSystem
from llm import call_deepseek
from prompts import (
    build_narrative_prompt,
    set_prompt_log_file,
)
from game_loop import handle_user_input
from trpg_display import (
    display_narrative, display_scene, display_system, display_debug,
    display_input_area, render_scene_to_html,
)
```

- [ ] **Step 2: 替换 cell `f1a93101133c462e`（日志配置）**

```python
# ═══════════════════════════════════════════════════════════════
#  Prompt 日志配置
# ═══════════════════════════════════════════════════════════════

PROMPT_LOG_FILE = f"../logs/prompt_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
set_prompt_log_file(PROMPT_LOG_FILE)
```

- [ ] **Step 3: 删除 cell `47828c98150cd488`（原 prompt 构建器）**

使用 NotebookEdit `delete` 模式删除。

- [ ] **Step 4: 删除 cell `3621b91e3850e8d7`（原 handle_user_input）**

使用 NotebookEdit `delete` 模式删除。

- [ ] **Step 5: 替换 cell `d39ea4f8cf47f3a6`（run_game）**

```python
def run_game():
    """启动 TRPG 游戏主循环"""
    import json as _json

    # ── 从文件直接加载数据 ──
    with open("../data/output/scene_output_resolved_revised.json", "r", encoding="utf-8") as f:
        scenes = _json.load(f)
    with open("../data/output/res_event_resolved_revised.json", "r", encoding="utf-8") as f:
        events = _json.load(f)
    with open("../data/abstract.txt", "r", encoding="utf-8") as f:
        abstract = f.read()

    # ── 构建世界 ──
    graph = DirectedGraph(scenes=scenes, events=events)
    world = ScenarioWorld(graph, start_node="6号车厢",
                          background_story=abstract)

    player = Player("调查员A", skills={"灵感": 70, "侦查": 50, "急救": 60})
    world.set_player(player)
    turn = 0

    # ── 开场 ──
    display_system("游戏开始。输入 /help 查看可用命令。", "info")
    display(HTML(render_scene_to_html(world)))

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
        display_narrative(initial_narrative)
    except Exception as e:
        display_system(f"初始叙事生成失败（API 可能未配置）：{e}", "warn")

    while True:
        turn += 1
        display_input_area(turn, world.current_location)
        cmd = input().strip()
        if not cmd:
            continue

        # ── 退出 ──
        if cmd.lower() in ("exit", "quit"):
            display_system("游戏结束。", "warn")
            break

        # ── 帮助 ──
        if cmd.lower() == "/help":
            display_system(
                "命令列表：\n"
                "  /scene   — 查看当前场景完整信息\n"
                "  /info    — 查看结构化 JSON 状态\n"
                "  /events  — 查看已触发事件\n"
                "  /flags   — 查看世界标记\n"
                "  /do 动作名 — 直接执行交互（跳过 LLM）\n"
                "  /trigger E1 — 手动触发事件\n"
                "  直接输入  — 正常游戏（LLM 调用链）\n"
                "  exit/quit — 退出",
                "info"
            )
            continue

        # ── 调试命令 ──
        if cmd.lower() == "/scene":
            display(HTML(render_scene_to_html(world)))
            continue
        if cmd.lower() == "/info":
            display_debug(_json.dumps(world.get_scene_info(), ensure_ascii=False, indent=2))
            continue
        if cmd.lower() == "/events":
            active = world.get_active_event_effects()
            if active:
                for name, impact in active:
                    display_system(f"◆ {name}\n{impact}", "event")
            else:
                display_system("尚无事件触发。", "info")
            continue
        if cmd.lower() == "/flags":
            if world.flags:
                items = "\n".join(f"  {k} = {v}" for k, v in world.flags.items())
                display_system(f"世界标记：\n{items}", "info")
            else:
                display_system("世界标记：（空）", "info")
            continue
        if cmd.lower().startswith("/trigger"):
            eid = cmd.split()[-1].strip().upper()
            ok, msg = world.trigger_event(eid)
            display_system(msg, "event" if ok else "warn")
            continue
        if cmd.lower().startswith("/do"):
            inter_name = cmd[3:].strip()
            ok, msg = world.execute_interaction(inter_name)
            if ok:
                display_system(msg, "info")
            else:
                display_system(msg, "warn")
            continue

        # ── 正常游戏流程 ──
        narrative = handle_user_input(cmd, world)
        display_narrative(narrative)


# 启动
run_game()
```

---

### Task 5: 端到端验证

- [ ] **Step 1: 导入链路验证**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
import sys; sys.path.insert(0, 'src')
# 验证所有新模块可导入
from llm import call_deepseek, call_deepseek_json, call_deepseek_write, call_deepseek_summarize
from prompts import (
    build_action_prompt, build_event_prompt, build_narrative_prompt,
    build_action_world_update, build_event_world_update,
    set_prompt_log_file, _show_prompt,
)
from game_loop import handle_user_input, _execute_single_action
from scenario_core import DirectedGraph, ScenarioWorld, Player, SkillSystem
print('All imports OK')
"
```

- [ ] **Step 2: 空跑验证（不调用 LLM）**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
import sys, json
sys.path.insert(0, 'src')
from scenario_core import DirectedGraph, ScenarioWorld, Player
from prompts import (
    build_action_prompt, build_event_prompt, build_narrative_prompt,
    build_action_world_update, build_event_world_update,
    set_prompt_log_file,
)

set_prompt_log_file('logs/test_extraction.log')

with open('data/output/scene_output_resolved_revised.json', 'r', encoding='utf-8') as f:
    scenes = json.load(f)
with open('data/output/res_event_resolved_revised.json', 'r', encoding='utf-8') as f:
    events = json.load(f)
with open('data/abstract.txt', 'r', encoding='utf-8') as f:
    abstract = f.read()

graph = DirectedGraph(scenes=scenes, events=events)
world = ScenarioWorld(graph, start_node='6号车厢', background_story=abstract)
player = Player('test', skills={'灵感':70, '侦查':50})
world.set_player(player)

# 测试所有 prompt builder
p1 = build_action_prompt(world, '查看四周然后去7号车厢')
assert 'actions' in p1, 'build_action_prompt should use actions array'
print(f'build_action_prompt: {len(p1)} chars OK')

p2 = build_event_prompt(world, '查看四周')
assert 'triggered_events' in p2
print(f'build_event_prompt: {len(p2)} chars OK')

p3 = build_action_world_update(world, '测试结果', '测试输入')
print(f'build_action_world_update: {len(p3)} chars OK')

p4 = build_event_world_update(world, '测试事件')
print(f'build_event_world_update: {len(p4)} chars OK')

p5 = build_narrative_prompt(world, '查看四周', '测试行动', '')
print(f'build_narrative_prompt: {len(p5)} chars OK')

print('All prompt builders verified OK')
"
```

- [ ] **Step 3: Notebook cell 数量验证**

```bash
cd "C:\Users\micha\PyCharmMiscProject" && python -c "
import json
with open('notebooks/notebook_simplified.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)
# Should have 4 code cells: imports, config, run_game, launch
code_cells = [c for c in nb['cells'] if c['cell_type'] == 'code']
print(f'Code cells: {len(code_cells)}')
for i, c in enumerate(code_cells):
    src = ''.join(c['source'])[:80]
    print(f'  Cell {i}: {src}...')
"
```
