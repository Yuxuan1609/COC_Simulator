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


def log_skill_result(text: str, log_path: str | None = None):
    """将技能检定结果写入日志文件（如已配置）。可指定路径避免并行竞态。"""
    path = log_path or _log_file
    if not path:
        return
    import threading
    lock = getattr(log_skill_result, '_lock', None)
    if lock is None:
        lock = threading.Lock()
        log_skill_result._lock = lock
    with lock:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(f"--- 技能检定 ---\n")
            f.write(text)
            f.write("\n\n")


# ── 场景上下文（确定性，不依赖 LLM）──

def _build_scene_context(world: ScenarioWorld) -> str:
    """Get current scene position, description, and exits. Entities are listed separately."""
    node = world._current_node()
    if not node:
        return "未知地点"

    exits = world.get_possible_exits()
    exit_list = "\n".join([
        f"  → {e.target}：{e.method}" for e in exits
    ]) or "（无）"

    return f"""【当前位置】{world.current_location}
【场景描述】{node.description}

【可移动方向】
{exit_list}"""

def _build_player_skills(world: ScenarioWorld) -> str:
    """构建玩家技能列表（从 Investigator.skills）"""
    if not world.player or not world.player.skills:
        return "（无技能数据）"
    return ", ".join(f"{s.name}={s.value}" for s in world.player.skills)


def _build_investigator_info(world: ScenarioWorld) -> str:
    """构建调查员信息（description + appearance）"""
    p = world.player
    if not p:
        return ""
    parts = []
    desc = getattr(p, 'personal_description', '') or getattr(p, 'description', '')
    app = getattr(p, 'appearance', '')
    if desc:
        parts.append(f"  描述：{desc}")
    if app:
        parts.append(f"  外貌：{app}")
    if not parts:
        return ""
    return "【调查员】\n" + "\n".join(parts) + "\n"


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
        # L1 may be dict (from JSON) or dataclass — accept both
        _get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        atm = _get(l1_scene, "atmosphere", "")
        mood = _get(l1_scene, "mood", "")
        hints = _get(l1_scene, "ambient_hints", [])
        if atm:
            parts.append(f"  氛围：{atm}")
        if mood:
            parts.append(f"  情绪基调：{mood}")
        if hints:
            parts.append(f"  环境暗示：{', '.join(hints)}")
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

_SHOW_NON_TRIGGERABLE = True  # 设为 False 则不展示不可触发项

def _build_entity_lines(world) -> tuple[list[str], list[str], list[str], list[str]]:
    """Build triggerable / non-triggerable entity lists for current scene + events.

    Returns (triggerable_scene, non_triggerable_scene, triggerable_events, non_triggerable_events).
    """
    node = world._current_node()

    trig_scene = []
    nontrig_scene = []

    def _split_req(entity) -> tuple[str, str, bool]:
        """Split entity requirement by ||: hard (before) | soft (after).
        Returns (hard_str, soft_str, hard_met)."""
        req = getattr(entity, 'requirement', '') or ''
        if not req.strip():
            return "", "", True
        if "||" in req:
            hard, soft = req.split("||", 1)
            hard, soft = hard.strip(), soft.strip()
        else:
            hard, soft = req.strip(), ""
        if not hard:
            return "", soft, True
        # Check hard condition
        if hard.startswith("flag:"):
            met = world.flags.get(hard[5:], False)
        else:
            met = world._are_requirements_met(entity)
        return hard, soft, met

    def _fmt_inter(entity) -> str:
        """Format an interaction entity. Only show soft condition; hard checked by Judge."""
        done = world.completed_interactions.get(world.current_location, set())
        status = "（已完成）" if entity.name in done else ""
        parts = [f"id={entity.id}", f"name=\"{entity.name}\""]
        _, soft, _ = _split_req(entity)
        if soft:
            parts.append(f"条件=\"{soft}\"")
        if status:
            parts.append(status)
        return "  [INTERACT] " + " ".join(parts)

    def _fmt_at(entity, req_met: bool) -> str:
        """Format an auto-trigger entity. Only show soft condition; hard checked by Judge."""
        parts = [f"id={entity.id}", f"name=\"{entity.name}\""]
        _, soft, _ = _split_req(entity)
        if soft:
            parts.append(f"条件=\"{soft}\"")
        if entity.type and entity.type != "无":
            parts.append(f"skill={entity.type}")
        return "  [AUTO_TRIGGER] " + " ".join(parts)

    if node:
        for at in node.auto_triggers:
            _, _, met = _split_req(at)
            line = _fmt_at(at, met)
            if met:
                trig_scene.append(line)
            else:
                nontrig_scene.append(line)
        for inter in node.interactions:
            _, _, met = _split_req(inter)
            line = _fmt_inter(inter)
            if met:
                trig_scene.append(line)
            else:
                nontrig_scene.append(line)

    trig_events = []
    nontrig_events = []
    for ev in world.graph.events.values():
        triggered = world.is_event_triggered(ev.id)
        if triggered:
            continue
        parts = [f"id={ev.id}", f"name=\"{ev.name}\"",
                 f"trigger=\"{ev.trigger}\""]
        hard, soft, met = _split_req(ev)
        if soft:
            parts.append(f"条件=\"{soft}\"")
        line = "  [EVENT] " + " ".join(parts)
        if hard:
            overall_met = met
        else:
            overall_met = True
        if overall_met:
            trig_events.append(line)
        else:
            nontrig_events.append(line)

    return trig_scene, nontrig_scene, trig_events, nontrig_events


def build_keeper_parse_prompt(world, user_input: str) -> str:
    """Keeper step 1: match player input against ALL entities, evaluate NL requirements."""
    scene_ctx = _build_scene_context(world)
    state = _build_world_state(world)
    context = world.memory.get_context()
    inv_info = _build_investigator_info(world)

    trig_scene, nontrig_scene, trig_events, nontrig_events = _build_entity_lines(world)

    # Scene entities section — AUTO_TRIGGER + INTERACT
    scene_entity_parts = []
    if trig_scene:
        scene_entity_parts.append("【可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(trig_scene))
    if _SHOW_NON_TRIGGERABLE and nontrig_scene:
        scene_entity_parts.append("【暂不可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(nontrig_scene))
    scene_entity_text = "\n\n".join(scene_entity_parts) if scene_entity_parts else "（无）"

    # Events section — global, not scene-bound
    event_parts = []
    if trig_events:
        event_parts.append("【可触发 — EVENT】\n" + "\n".join(trig_events))
    if _SHOW_NON_TRIGGERABLE and nontrig_events:
        event_parts.append("【暂不可触发 — EVENT】\n" + "\n".join(nontrig_events))
    event_text = "\n\n".join(event_parts) if event_parts else "（无）"

    prompt = f"""【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

{inv_info}
{scene_ctx}

{scene_entity_text}

{event_text}

【玩家输入】
{user_input}

实体分为三类：INTERACT（场景交互）、AUTO_TRIGGER（自动触发）、EVENT（全局事件）。
硬性条件（flag/依赖关系）已由系统判定完成。你只需：
1. 判断玩家意图匹配了哪些实体。如有「条件=」字段（软性条件/自然语言描述），评估是否满足，不满足的排除。
2. 对于不匹配任何实体的输入，归类为 move/search/other。

返回 JSON：
{{
  "actions": [
    {{"type": "auto_trigger", "id": "AT1"}},
    {{"type": "interaction", "id": "I3"}},
    {{"type": "event", "id": "E22"}},
    {{"type": "move", "target": "7号车厢"}},
    {{"type": "search"}},
    {{"type": "other", "text": "唱了一首歌"}}
  ]
}}

规则：
- auto_trigger 必须排在列表最前面
- id 必须从上述实体列表中精确复制
- move：target 填可移动方向中列出的目标
- other：text 用自然语言简述玩家意图
- 排除已完成的交互和已触发的事件
- 如有「条件=」字段，评估是否满足，不满足的排除（硬性条件系统已处理）
- 直接输出 JSON，不要额外文字
"""
    _show_prompt("Keeper Parse", prompt)
    return prompt


# ── Keeper: Enrich (Step 3) ──

def build_keeper_enrich_prompt(world, judged_entities, user_input) -> str:
    """Keeper step 3: describe and enrich entity results. No trigger evaluation."""
    state = _build_world_state(world)

    entities_text = ""
    for e in judged_entities:
        entities_text += (
            f"  [{e['entity_type']}] id={e['id']} name=\"{e['name']}\" "
            f"result=\"{e['result']}\" success={e['success']}"
        )
        if e.get('skill_tier'):
            entities_text += f" skill_tier={e['skill_tier']}"
        entities_text += "\n"

    prompt = f"""【世界状态】
{state}

【当前场景】{world.current_location}
{world.get_current_description()}

【玩家输入】{user_input}

【本轮已触发实体】
{entities_text or '（无）'}

请为以上已触发实体做叙事整合：
1. 为 auto_trigger 实体生成简短描述（它们是无条件触发的环境变化）
2. 为 interaction/event 实体的结果文本润色，增加氛围和细节
3. 提供 emphasis_hint：本轮叙事的强调方向

返回 JSON：
{{
  "at_descriptions": {{"AT1": "环境变化描述"}},
  "enriched_results": {{"I3": "润色后的结果"}},
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt)
    return prompt


# ── Narrator prompt ──

def build_narrator_prompt(brief, l1_scene=None, inv_info: str = "") -> str:
    """Narrator: converts NarratorBrief + L1 context into immersive narrative."""
    outcomes_text = ""
    for o in brief.action_outcomes:
        outcomes_text += f"  {'✓' if o.success else '✗'} {o.message}\n"

    ambient_text = "\n".join(f"  · {a}" for a in brief.ambient_changes) or "（无）"

    l1_ctx = _build_l1l3_context(l1_scene=l1_scene,
                                  scene_name=brief.scene_snapshot.location)

    prompt = f"""{l1_ctx}

{inv_info}
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
