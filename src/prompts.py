"""
Prompt 构建器 —— 为 LLM 调用链构建结构化 prompt。

所有 build_* 函数只负责构造 prompt 字符串，不发起 LLM 调用。
通过 set_prompt_log_file() 配置日志输出路径。
"""

from __future__ import annotations
import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld
    from module_designer.l1_player import SceneL1
    from module_designer.l3_designer import L3Designer

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


def log_skill_result(text: str):
    """将技能检定结果写入日志文件（如已配置）"""
    if not _log_file:
        return
    with open(_log_file, 'a', encoding='utf-8') as f:
        f.write(f"--- 技能检定 ---\n")
        f.write(text)
        f.write("\n\n")


# ── 触发状态分离（确定性，不依赖 LLM）──

_SHOW_NON_TRIGGERABLE = True  # 设为 False 则不展示不可触发项


def _categorize_interactions(world: ScenarioWorld) -> dict:
    """Split available (incomplete) interactions into triggerable / non-triggerable."""
    interactions = world.get_available_interactions()
    done = world.completed_interactions.get(world.current_location, set())
    available = [i for i in interactions if i.name not in done]

    triggerable = []
    non_triggerable = []

    for i in available:
        entry = {
            "name": i.name,
            "type": i.type,
            "trigger": i.trigger,
            "result": i.result[:120],
        }
        if world._are_requirements_met(i):
            triggerable.append(entry)
        else:
            unmet = world.requirement_resolver.get_unmet(i.requirements)
            reasons = []
            for req in unmet:
                if req.ref_type == "interaction":
                    reasons.append(f"需要先完成「{req.ref_scene}」的「{req.ref_name}」")
                elif req.ref_type == "event":
                    event = world.graph.get_event(req.ref_scene)
                    event_name = event.name if event else req.ref_scene
                    reasons.append(f"需要先触发事件「{event_name}」")
                elif req.ref_type == "flag":
                    reasons.append(f"需要世界标记「{req.ref_name}」")
            entry["unmet_reasons"] = reasons
            non_triggerable.append(entry)

    return {"triggerable": triggerable, "non_triggerable": non_triggerable}


def _categorize_pending_events(world: ScenarioWorld) -> dict:
    """Split pending (not yet triggered) events into triggerable / non-triggerable."""
    pending = [e for e in world.graph.events.values()
               if not world.is_event_triggered(e.event_id)]

    triggerable = []
    non_triggerable = []

    for ev in pending:
        entry = {
            "event_id": ev.event_id,
            "name": ev.name,
            "trigger": ev.trigger,
            "impact": ev.impact[:150],
        }
        if ev.requirements:
            met, _ = world.requirement_resolver.check(ev.requirements)
            if met:
                triggerable.append(entry)
            else:
                unmet = world.requirement_resolver.get_unmet(ev.requirements)
                reasons = []
                for req in unmet:
                    if req.ref_type == "interaction":
                        reasons.append(f"需要先完成「{req.ref_scene}」的「{req.ref_name}」")
                    elif req.ref_type == "event":
                        event = world.graph.get_event(req.ref_scene)
                        event_name = event.name if event else req.ref_scene
                        reasons.append(f"需要先触发事件「{event_name}」")
                    elif req.ref_type == "flag":
                        reasons.append(f"需要世界标记「{req.ref_name}」")
                entry["unmet_reasons"] = reasons
                non_triggerable.append(entry)
        else:
            triggerable.append(entry)

    return {"triggerable": triggerable, "non_triggerable": non_triggerable}


def _format_triggerable_interactions(interactions: list) -> str:
    """Format triggerable interactions for prompt display."""
    if not interactions:
        return ""
    lines_list = []
    for i in interactions:
        lines_list.append(
            f"  名称（请原样复制）：「{i['name']}」\n"
            f"  类型：{i['type']}\n"
            f"  触发条件：{i['trigger']}\n"
            f"  结果：{i['result']}"
        )
    text = "\n\n".join(lines_list)
    return f"【可执行动作】\n{text}"


def _format_non_triggerable_interactions(interactions: list) -> str:
    """Format non-triggerable interactions with unmet reasons."""
    if not interactions:
        return ""
    lines_list = []
    for i in interactions:
        reasons = "\n".join(f"    - {r}" for r in i["unmet_reasons"])
        lines_list.append(
            f"  名称：「{i['name']}」\n"
            f"  类型：{i['type']}\n"
            f"  触发条件：{i['trigger']}\n"
            f"  缺少前置：\n{reasons}"
        )
    text = "\n\n".join(lines_list)
    return f"【暂不可执行动作】（需满足前置条件）\n{text}"


def _format_triggerable_events(events: list) -> str:
    """Format triggerable events for prompt display."""
    if not events:
        return ""
    lines_list = []
    for ev in events:
        lines_list.append(
            f"  ◇ [{ev['event_id']}] {ev['name']}\n"
            f"    触发条件：{ev['trigger']}\n"
            f"    预期影响：{ev['impact']}"
        )
    text = "\n\n".join(lines_list)
    return f"【可触发事件】\n{text}"


def _format_non_triggerable_events(events: list) -> str:
    """Format non-triggerable events with unmet reasons."""
    if not events:
        return ""
    lines_list = []
    for ev in events:
        reasons = "\n".join(f"    - {r}" for r in ev["unmet_reasons"])
        lines_list.append(
            f"  ◇ [{ev['event_id']}] {ev['name']}\n"
            f"    触发条件：{ev['trigger']}\n"
            f"    预期影响：{ev['impact']}\n"
            f"    缺少前置：\n{reasons}"
        )
    text = "\n\n".join(lines_list)
    return f"【暂不可触发事件】（需满足前置条件）\n{text}"


# ── 场景上下文（确定性，不依赖 LLM）──

def _build_scene_context(world: ScenarioWorld, show_non_triggerable: bool = True) -> str:
    """从 graph 获取当前场景的稳定上下文（不含世界状态）"""
    node = world._current_node()
    if not node:
        return "未知地点"

    exits = world.get_possible_exits()
    exit_list = "\n".join([
        f"  → {e.target}：{e.method}" for e in exits
    ]) or "（无）"

    categorized = _categorize_interactions(world)

    interaction_parts = []
    triggerable_text = _format_triggerable_interactions(categorized["triggerable"])
    if triggerable_text:
        interaction_parts.append(triggerable_text)

    if show_non_triggerable:
        non_trig_text = _format_non_triggerable_interactions(categorized["non_triggerable"])
        if non_trig_text:
            interaction_parts.append(non_trig_text)

    interaction_text = "\n\n".join(interaction_parts) if interaction_parts else "（当前场景无可执行动作）"

    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}

【可移动方向】
{exit_list}

{interaction_text}"""

def _build_scene_context_event(world: ScenarioWorld) -> str:
    """从 graph 获取当前场景的稳定上下文（不含世界状态）"""
    node = world._current_node()
    if not node:
        return "未知地点"
    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}
"""

def _build_player_skills(world: ScenarioWorld) -> str:
    """构建玩家技能列表（从 Investigator.skills）"""
    if not world.player or not world.player.skills:
        return "（无技能数据）"
    return ", ".join(f"{s.name}={s.value}" for s in world.player.skills)


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

def build_action_prompt(world: ScenarioWorld, user_input: str,
                        show_non_triggerable: bool | None = None) -> str:
    """基于当前场景 JSON 信息，让 LLM 判断玩家意图，支持多动作识别"""
    if show_non_triggerable is None:
        show_non_triggerable = _SHOW_NON_TRIGGERABLE
    scene_ctx = _build_scene_context(world, show_non_triggerable=show_non_triggerable)
    state = _build_world_state(world)
    context = world.memory.get_context()
    skills = _build_player_skills(world)

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

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
      "reasoning": "简要推理",
      "condition":"缺少前置"
    }}
  ]
}}
整体规则：
-你是一个TRPG意图识别助手，请帮助识别玩家是否触发了了潜在事件（包括当前可触发的事件和暂时不可触发的事件）
-如果玩家试图进行不可触发事件则使用condition字段对其进行指引
-直接输出 JSON，不要额外文字
action字段份分类规则：
- move：玩家明确想前往某方向/地点 → target 填「可移动方向」中列出的目标 注意 查看/聆听/询问/非直接前往的方式 了解另外一个场景不适用move
- interact：玩家意图匹配某个可执行动作 → interaction 务必精确复制名称
- search：玩家想探索、调查当前场景
- other：其他动作类型（不产生实际影响）
其他规则：
- skill_checks：根据动作的触发条件，列出需要鉴定的技能名称（如 侦查、灵感、急救 等。
- 无需鉴定时返回空数组 []，仅对 move 和 interact 生效
- 如果玩家输入只有单一意图，actions 数组仍包含 1 个元素
- actions 按玩家输入中的先后顺序排列
其他规则：
- condition:平时为空值，当玩家试图进行【暂不可执行动作】时以描述性语言列出缺少的前置条件

"""
    _show_prompt("Step 1/3 — 动作解析", prompt)
    return prompt


# ── 第二阶段：事件触发判定 ──

def build_event_prompt(world: ScenarioWorld, user_input: str,
                       show_non_triggerable: bool | None = None) -> str:
    """基于 user_input + 全部未触发事件，让 LLM 独立判断哪些事件应在此刻触发"""
    if show_non_triggerable is None:
        show_non_triggerable = _SHOW_NON_TRIGGERABLE

    context = world.memory.get_context()
    state = _build_world_state(world)
    scene_ctx = _build_scene_context_event(world)
    categorized = _categorize_pending_events(world)

    event_parts = []
    triggerable_text = _format_triggerable_events(categorized["triggerable"])
    if triggerable_text:
        event_parts.append(triggerable_text)

    if show_non_triggerable:
        non_trig_text = _format_non_triggerable_events(categorized["non_triggerable"])
        if non_trig_text:
            event_parts.append(non_trig_text)

    event_text = "\n\n".join(event_parts) if event_parts else "（所有事件均已触发）"

    prompt = f"""【玩家历史行动】
{context or '（无）'}

{scene_ctx}
【世界状态】
{state}

【玩家输入】
{user_input}

【待检查事件（仅以下未触发事件需判断）】
{event_text}

请逐一判断上述「待检查事件」的触发条件是否被玩家当前输入所描述的行动满足。返回 JSON：
{{
  "triggered_events": ["E1"],
  "condition_events": {{"E2": "需要先完成..."}},
  "new_flags": {{"flag_name": true}},
  "reasoning": "逐事件推理"
}}

规则：
- 仅当玩家输入中描述的行动确实满足事件的触发条件时才列入 triggered_events
- 已触发的事件不要重复触发
- condition_events：当玩家试图触发【暂不可触发事件】时列出对应的事件ID和缺少的前置条件，未尝试触发则返回 {{}}
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
- description：如果当前场景发生了可见变化（物品移动、痕迹留下、环境改变等），更新描述使其反映新的场景状态；如果场景未发生可见变化，description 原样返回【当前场景描述】
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON
- 【当前场景描述】是需要修改的描述，【当前背景设定】仅供参考，判断核心来自【本轮行动结果】和【玩家输入】
返回 JSON：
{{
  "description": "更新后的【当前场景描述】描述"
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
- abstract：将本轮触发的事件及其不可逆影响以文学性语言融入【当前背景设定】中，采用累积追加的方式
- 不得添加未实际发生的实质性信息，避免误导
- 保持原有世界观和恐怖氛围
- 直接输出 JSON
- 【当前背景设定】是需要修改的描述，【当前场景描述】仅供参考，判断核心来自【本轮触发事件】
返回 JSON：
{{
  "abstract": "更新后的【当前背景设定】",
}}"""
    _show_prompt("World Update — Event", prompt)
    return prompt


# ── 第三阶段：叙事生成 ──

def build_narrative_prompt(world: ScenarioWorld, user_input: str,
                           action_result: str, events_result: str,
                           l1_scene: "SceneL1 | None" = None,
                           l3_data: "L3Designer | None" = None) -> str:
    """基于所有结果 + 已更新世界 + 可触发事件列表，生成沉浸式叙事"""
    context = world.memory.get_context()
    scene_desc = world.get_current_description()
    events_text = events_result if events_result else "（无特殊事件发生）"

    bg_section = ""
    if world.background_story:
        bg_section = f"""【模组背景设定】
{world.background_story}

"""

    l1l3_ctx = _build_l1l3_context(l1_scene=l1_scene, l3_data=l3_data, scene_name=world.current_location)

    prompt = f"""{bg_section}{l1l3_ctx}

【玩家历史行动】
{context or '（无）'}

【当前场景】{world.current_location}
{scene_desc}

【玩家输入】{user_input}

【行动结果】{action_result}

【本轮触发事件】{events_text}


请以TRPG主持人（KP）的身份，基于【行动结果】对【玩家输入】和【本轮触发事件】给出合理的回应，
输出格式请遵守 结果："简要描述" \n\n\n 沉浸式叙事："基于结果用沉浸式中文生成不超过100字"
请遵循这些具体要求：
- 重要！不要给出前文没有提及的实质性信息
- 重要！严格遵守输出格式，给出一个结果一个沉浸式叙事
- 根据行动结果调整叙事：成功则描述顺利进行，失败则描述没有结果或难以进行，没有提及则忽略这条
- 语气贴合场景氛围，参考【基调约束】中的世界观和氛围基调
- 遵守【基调约束】中的禁止项和必须包含项
- 叙事要体现【场景感知信息】中的氛围和情绪基调
- 直接输出叙事文本，不要额外说明
- 【模组背景设定】和【玩家历史行动】主要用于理解背景，尽量少重复叙述其中的内容
- 在满足以上要求的情况下进行合理自由发挥
"""
    _show_prompt("Step 3/3 — 叙事生成", prompt)
    return prompt


# ── 第三阶段（备用）：即兴叙事 ──

def build_improvise_prompt(world: ScenarioWorld, user_input: str,
                           action_result: str,
                           l1_scene: "SceneL1 | None" = None,
                           l3_data: "L3Designer | None" = None) -> str:
    """当动作解析结果为 other 且无事件触发时调用，生成即兴叙事"""
    context = world.memory.get_context()
    scene_desc = world.get_current_description()

    bg_section = ""
    if world.background_story:
        bg_section = f"""【模组背景设定】
{world.background_story}

"""

    l1l3_ctx = _build_l1l3_context(l1_scene=l1_scene, l3_data=l3_data, scene_name=world.current_location)

    prompt = f"""{bg_section}{l1l3_ctx}

【玩家历史行动】
{context or '（无）'}

【当前场景】{world.current_location}
{scene_desc}

【玩家输入】{user_input}

请以TRPG主持人（KP）的身份，【玩家输入】给出合理的回应，
输出格式请遵守 结果："简要描述" \n\n\n 沉浸式叙事："基于结果用沉浸式中文生成不超过100字"
请遵循这些具体要求：
- 重要！不要给出前文没有提及的实质性信息
- 重要！当前玩家行动没有产生实际影响，请以符合场景的语言委婉提示玩家这一点
- 重要！严格遵守输出格式，给出一个结果一个沉浸式叙事
- 用沉浸式中文生成20-100字
- 语气贴合场景氛围，参考【基调约束】和【场景感知信息】
- 遵守【基调约束】中的禁止项
- 【模组背景设定】和【玩家历史行动】主要用于理解背景，尽量少重复叙述其中的内容
"""
    _show_prompt("Step 3b — 即兴叙事", prompt)
    return prompt


# ── 叙事输出解析 ──

def _build_l1l3_context(
    l1_scene: "SceneL1 | None" = None,
    l3_data: "L3Designer | None" = None,
    scene_name: str = "",
) -> str:
    """构建 L1 + L3 增强上下文，供叙事/即兴 prompt 使用."""
    parts = []
    if l3_data:
        parts.append("【基调约束】")
        tc = l3_data.tone_constraints
        if tc.genre:
            parts.append(f"  类型：{tc.genre}")
        if tc.narrative_style:
            parts.append(f"  叙事风格：{tc.narrative_style}")
        if tc.forbidden:
            parts.append(f"  禁止：{', '.join(tc.forbidden)}")
        if tc.required:
            parts.append(f"  必须包含：{', '.join(tc.required)}")
        if l3_data.driving_force:
            parts.append(f"  核心驱动力：{l3_data.driving_force}")
        intent = l3_data.scene_intents.get(scene_name) if scene_name else None
        if intent:
            if intent.purpose:
                parts.append(f"  本场景设计意图：{intent.purpose}")
            if intent.emotion:
                parts.append(f"  目标情绪：{intent.emotion}")
    if l1_scene:
        parts.append("【场景感知信息】")
        if l1_scene.atmosphere:
            parts.append(f"  氛围：{l1_scene.atmosphere}")
        if l1_scene.mood:
            parts.append(f"  情绪基调：{l1_scene.mood}")
        if l1_scene.ambient_hints:
            parts.append(f"  环境暗示：{', '.join(l1_scene.ambient_hints)}")
    return "\n".join(parts) if parts else ""


def parse_narrative_output(text: str) -> tuple[str, str]:
    """
    解析 LLM 叙事输出，按 \n\n\n 分割为 (简要结果, 沉浸式叙事)。
    解析失败时 fallback 到原文。
    """
    parts = text.split("\n\n\n", 1)
    if len(parts) != 2:
        # 尝试其他分隔
        parts = text.split("\n\n", 1)

    if len(parts) == 2:
        first, second = parts
        brief = first
        narrative = second

        # 提取 "结果：" 或 "结果:" 后的内容
        for sep in ["结果：", "结果:"]:
            if sep in first:
                brief = first.split(sep, 1)[1].strip()
                brief = brief.strip('"').strip("'").strip(""").strip(""")
                break

        # 提取 "沉浸式叙事：" 后的内容
        for sep in ["沉浸式叙事：", "沉浸式叙事:"]:
            if sep in second:
                narrative = second.split(sep, 1)[1].strip()
                narrative = narrative.strip('"').strip("'").strip(""").strip(""")
                break

        return brief, narrative

    # Fallback: 整个文本作为叙事
    fallback_brief = text[:60] + "..." if len(text) > 60 else text
    return fallback_brief, text


# ── Keeper: Parse (Step 1) ──

def build_keeper_parse_prompt(world, user_input: str) -> str:
    """Keeper step 1: parse raw player input into structured ActionIntent[]."""
    scene_ctx = _build_scene_context(world)
    state = _build_world_state(world)
    context = world.memory.get_context()

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

{scene_ctx}

【玩家输入】
{user_input}

请判断玩家意图。返回 JSON：
{{
  "actions": [
    {{
      "action": "move" | "interact" | "search" | "other",
      "target": "目标地点或动作名称",
      "skill_checks": ["技能名"],
      "reasoning": "简要推理"
    }}
  ]
}}
规则：
- move：target 填可移动方向中列出的目标
- interact：target 精确复制可执行动作的名称
- search：探索当前场景
- 直接输出 JSON，不要额外文字
"""
    _show_prompt("Keeper Parse", prompt)
    return prompt


# ── Keeper: Enrich (Step 3) ──

def build_keeper_enrich_prompt(world, action_outcomes, at_results, pending_events,
                                deferred_ats, user_input) -> str:
    """Keeper step 3: LLM enriches results, matches events, resolves NL ATs."""
    state = _build_world_state(world)

    outcomes_text = ""
    for o in action_outcomes:
        outcomes_text += f"  [{o.entity_type}] {o.entity_id}: {o.message} (success={o.success})\n"

    at_text = ""
    for a in at_results:
        at_text += f"  [AT] {a.entity_id}: {a.message}\n"

    deferred_at_text = ""
    for dat in deferred_ats:
        deferred_at_text += f"  [{dat.id}] {dat.name}: requirement=\"{dat.requirement}\" trigger=\"{dat.trigger}\"\n"

    events_text = ""
    for ev in pending_events:
        events_text += f"  [{ev.id}] {ev.name}: trigger=\"{ev.trigger}\"\n"

    prompt = f"""【世界状态】
{state}

【当前场景】{world.current_location}
{world.get_current_description()}

【玩家输入】{user_input}

【已执行动作结果】
{outcomes_text or '（无）'}

【已触发Auto-trigger】
{at_text or '（无）'}

【待判定Auto-trigger（自然语言前置条件）】
{deferred_at_text or '（无）'}

【待判定Event】
{events_text or '（无）'}

请判断：
1. 哪些待判定AT应触发（其自然语言前置条件是否满足）
2. 哪些待判定Event的触发条件被满足
3. 为所有已触发的entity丰富结果描述
4. 设置新的world flags

返回 JSON：
{{
  "triggered_ats": ["AT2"],
  "triggered_events": ["E1"],
  "enriched_results": {{"I1": "丰富后的结果描述"}},
  "new_flags": {{"flag_name": true}},
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt)
    return prompt


# ── Narrator prompt ──

def build_narrator_prompt(brief, l1_scene=None) -> str:
    """Narrator: converts NarratorBrief + L1 context into immersive narrative."""
    outcomes_text = ""
    for o in brief.action_outcomes:
        outcomes_text += f"  {'✓' if o.success else '✗'} {o.message}\n"

    ambient_text = "\n".join(f"  · {a}" for a in brief.ambient_changes) or "（无）"

    l1_ctx = _build_l1l3_context(l1_scene=l1_scene,
                                  scene_name=brief.scene_snapshot.location)

    prompt = f"""{l1_ctx}

【当前场景】{brief.scene_snapshot.location}
{brief.scene_snapshot.description}

【可通行方向】{', '.join(f"{e['target']}({e['method']})" for e in brief.scene_snapshot.exits)}

【行动结果】
{outcomes_text}

【环境变化】
{ambient_text}

【叙事强调】{brief.suggested_emphasis}

请以TRPG主持人身份生成沉浸式叙事。
输出格式：结果："简要描述" \n\n\n 沉浸式叙事："沉浸式中文不超过100字"

规则：
- 不要给出前文没有的实质性信息
- 以上下文语境和场景氛围为准
- 叙事强调指明了本轮的叙事方向
"""
    _show_prompt("Narrator", prompt)
    return prompt


# ── Author prompt ──

def build_author_prompt(request, l3_data) -> str:
    """Author: generates ModulePatch from EscalationRequest + L3 context."""
    l3_ctx = _build_l1l3_context(l3_data=l3_data, scene_name=request.world_context.get("location", ""))

    prompt = f"""{l3_ctx}

【玩家输入】{request.player_input}
【触发维度】{request.trigger} (severity={request.severity})
【原因】{request.reason}
【未匹配意图】{request.unmatched_intent or '无'}
【世界上下文】
{json.dumps(request.world_context, ensure_ascii=False, indent=2)}

你拥有WR0创作者豁免权。请基于L3设计意图，为KP创建新的entity（interaction/auto_trigger/event）来处理这个超出KP能力的情况。

返回 JSON：
{{
  "entities": [
    {{
      "id": "NEW_1",
      "entity_type": "interaction",
      "scene": "场景名",
      "name": "entity名称",
      "type": "关联技能名或留空",
      "requirement": "",
      "trigger": "触发描述",
      "result": "结果描述",
      "side_effects": ["@stat_change(stat_name=SAN, delta=-1, narrative=xxx)"],
      "graded_result": null,
      "difficulty": "regular"
    }}
  ],
  "scene_descriptions": {{}},
  "justification": "L3层面理由"
}}

规则：
- 只添加必要的entity，不要过度扩充
- side_effects 使用 @function(param=value) 语法
- justification 必须引用L3设计意图
- 直接输出 JSON
"""
    _show_prompt("Author", prompt)
    return prompt
