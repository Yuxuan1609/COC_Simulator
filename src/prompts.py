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
    """构建调查员信息（name + description + appearance）"""
    p = world.player
    if not p:
        return ""
    parts = []
    name = getattr(p, 'name', '') or getattr(p, 'character_name', '')
    if name:
        parts.append(f"  姓名：{name}")
    desc = getattr(p, 'personal_description', '') or getattr(p, 'description', '')
    if desc:
        parts.append(f"  描述：{desc}")
    app = getattr(p, 'appearance', '')
    if app:
        parts.append(f"  外貌：{app}")
    if not parts:
        return ""
    return "【调查员】\n" + "\n".join(parts) + "\n"



def _build_world_state(world: ScenarioWorld) -> str:
    """从 world 获取当前状态摘要"""
    triggered = [eid for eid, t in world.triggered_events.items() if t]
    completed_entities = [eid for eid, s in world.runtime_state.items() if s.completed]
    flags_str = ", ".join(completed_entities) or "（无）"
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
        # Normalize dict/dataclass access (L3 may be raw dict from JSON)
        _l3_get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        tc = _l3_get(l3_data, "tone_constraints", {})
        if tc:
            tc_genre = _l3_get(tc, "genre", "")
            if tc_genre:
                parts.append(f"  类型：{tc_genre}")
            tc_style = _l3_get(tc, "narrative_style", "")
            if tc_style:
                parts.append(f"  叙事风格：{tc_style}")
            tc_forbidden = _l3_get(tc, "forbidden", [])
            if tc_forbidden:
                parts.append(f"  禁止：{', '.join(tc_forbidden)}")
            tc_recommended = _l3_get(tc, "recommended", [])
            if tc_recommended:
                parts.append(f"  必须包含：{', '.join(tc_recommended)}")
        driving_force = _l3_get(l3_data, "driving_force", "")
        if driving_force:
            parts.append(f"  核心驱动力：{driving_force}")
        scene_intents = _l3_get(l3_data, "scene_intents", {})
        intent = None
        if scene_name and scene_intents:
            if isinstance(scene_intents, dict):
                intent = scene_intents.get(scene_name)
            else:
                intent = getattr(scene_intents, scene_name, None)
        if intent:
            intent_purpose = _l3_get(intent, "purpose", "")
            if intent_purpose:
                parts.append(f"  本场景设计意图：{intent_purpose}")
    if l1_scene:
        parts.append("【场景感知信息】")
        # L1 may be dict (from JSON) or dataclass — accept both
        _get = lambda obj, key, default="": obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
        desc = _get(l1_scene, "description", "")
        atm = _get(l1_scene, "atmosphere", "")
        mood = _get(l1_scene, "mood", "")
        hints = _get(l1_scene, "ambient_hints", [])
        if desc:
            parts.append(f"  描述：{desc}")
        if atm:
            parts.append(f"  氛围：{atm}")
        if mood:
            parts.append(f"  情绪基调：{mood}")
        if hints:
            parts.append(f"  环境暗示：{', '.join(hints)}")
    return "\n".join(parts) if parts else ""


def parse_narrative_output(response: dict | str) -> tuple[str, str, str]:
    """Parse narrator LLM response. Returns (brief, narrative, scene_update).
    Handles JSON dict input (new format), with fallback to string parsing (old format)."""
    if isinstance(response, dict):
        brief = response.get("brief", "")
        narrative = response.get("narrative", "")
        scene_update = response.get("scene_update", "")
        return brief, narrative, scene_update or ""

    # Fallback: string response — try old ### marker format or triple newline
    text = response
    if isinstance(text, str) and "### 结果" in text and "### 沉浸式叙事" in text:
        _, rest = text.split("### 结果", 1)
        result_part, rest2 = rest.split("### 沉浸式叙事", 1)
        brief = result_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
        scene_update = ""
        if "### 场景变化" in rest2:
            narrative_part, scene_part = rest2.split("### 场景变化", 1)
            scene_update = scene_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
            if scene_update == chr(26080) or not scene_update:
                scene_update = ""
        else:
            narrative_part = rest2
        narrative = narrative_part.strip().strip(chr(34)+chr(39)+chr(0x201C)+chr(0x201D)+chr(0x2018)+chr(0x2019))
        return brief, narrative, scene_update

    fb = text[:60] + "..." if len(text) > 60 else text
    return fb, text, ""


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
            from scenario_core import parse_hard_requirement
            met = parse_hard_requirement(hard, world.runtime_state)
        else:
            met = world._are_requirements_met(entity)
        return hard, soft, met

    def _fmt_inter(entity) -> str:
        """Format an interaction entity."""
        done = world.completed_interactions.get(world.current_location, set())
        status = "（已完成）" if entity.name in done else ""
        _, soft, _ = _split_req(entity)
        parts = [f"id={entity.id}", f"name=\"{entity.name}\"",
                 f"trigger=\"{entity.trigger}\"", f"条件=\"{soft}\""]
        if status:
            parts.append(status)
        return "  [INTERACT] " + " ".join(parts)

    def _fmt_at(entity) -> str:
        """Format an auto-trigger entity. No trigger/skill; condition covers it."""
        _, soft, _ = _split_req(entity)
        parts = [f"id={entity.id}", f"name=\"{entity.name}\"",
                 f"条件=\"{soft}\""]
        return "  [AUTO_TRIGGER] " + " ".join(parts)

    if node:
        for at in node.auto_triggers:
            _, _, met = _split_req(at)
            line = _fmt_at(at)
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
1. 判断玩家意图匹配了哪些可触发实体或者其他行为包括(move/search/other)。如有「条件=」字段（软性条件/自然语言描述），评估是否满足，不满足的排除。

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
- 玩家输入有明确对应的entity优先返回entity结果，之后再考虑search/move/other
- 没有明确指定对象的索、探查、感知行为属于search不触发entity
- 一般来讲玩家一个动作（注意不是一轮输入）只匹配一个结果，但也允许同时匹配多个结果的特殊情况，你可以基于具体文字发挥
- move指移动到别的场景，other泛指所有其他行为
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
1. 将所有实体（auto_trigger / interaction / event）的结果合并润色，统一为流畅连贯的叙事
2. 根据 success 调整叙事：
   - success=true → 结果被清晰、明确地描述并整合进叙事，玩家能确切感知到发生了什么
   - success=false → 结果晦涩、模糊、没有实际影响，仿佛是错觉或微不足道的细节，玩家难以确定是否真的发生了什么
3. 提供 reasoning：简短说明本轮整合的逻辑（为什么这样合并/改写）

返回 JSON：
{{
  "results": {{"AT1": "环境变化描述", "I3": "润色后的结果", "E22": "事件叙事"}},
  "reasoning": "简短说明整合逻辑",
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt)
    return prompt


# ── Narrator prompt ──

def build_narrator_prompt(brief, l1_scene=None, inv_info: str = "", user_input: str = "") -> str:
    """Narrator: converts NarratorBrief + L1 context into immersive narrative."""
    entity_outcomes = ""
    flavor_outcomes = ""
    for o in brief.action_outcomes:
        if o.intent.action == "other":
            flavor_outcomes += f"  · {o.message}\n"
        else:
            entity_outcomes += f"  {'✓' if o.success else '✗'} {o.message}\n"

    ambient_text = "\n".join(f"  · {a}" for a in brief.ambient_changes) or "（无）"

    l1_ctx = _build_l1l3_context(l1_scene=l1_scene,
                                  scene_name=brief.scene_snapshot.location)

    prompt = f"""{l1_ctx}

{inv_info}
【玩家输入】{user_input or '（无）'}

【当前场景】{brief.scene_snapshot.location}
{brief.scene_snapshot.description}

【可通行方向】{', '.join(f"{e['target']}({e['method']})" for e in brief.scene_snapshot.exits)}

【实体行动结果】
{entity_outcomes or '（无）'}

【即兴行为】{f'{chr(10)}{flavor_outcomes}' if flavor_outcomes else '（无）'}
【环境变化】
{ambient_text}

【叙事强调】{brief.suggested_emphasis}

请以TRPG主持人身份生成沉浸式叙事。

返回 JSON：
{{
  "brief": "简洁、清晰、客观的概括——本轮发生了什么。仅陈述事实，不含情绪色彩。",
  "narrative": "基于结果进行文学性展开，融入场景氛围，让玩家身临其境。中文不超过100字。",
  "scene_update": ""
}}

规则：
- brief 与 narrative 必须严格呼应，brief "简洁、清晰、客观的概述事实，narrative 基于结果进行文学性展开
- scene_update：判断本轮行动是否导致场景可见变化（物品移动、门打开、血迹、光源、NPC出现/消失等）。有变化则输出更新后的完整场景描述；无变化则为空字符串 ""
- 仅当本轮行动确实改变了场景时才填写 scene_update
- 「即兴行为」不导致场景变化，不填写 scene_update
- 不要给出前文没有的实质性信息
- 以上下文语境和场景氛围为准
- 叙事强调指明了本轮的叙事方向
- 「即兴行为」仅为叙述性描写，不对世界产生任何实际影响——场景状态、物品位置、
  NPC状态等均不因其改变。描述时作为短暂的、无后果的角色动作自然融入叙事，
  一带而过即可，不做展开
直接输出 JSON。
"""
    _show_prompt("Narrator", prompt)
    return prompt


# ── Author prompt ──

def build_author_prompt(request, l3_data) -> str:
    """Author: judges patch/structural level, generates content."""
    l3_ctx = _build_l1l3_context(
        l3_data=l3_data,
        scene_name=request.scene_context.get("location", ""),
    )

    wr0_enabled = request.scene_context.get("wr0_enabled", False)
    wr0_line = (
        "【WR0 创作者豁免】开启 — 你拥有完全创作自由，可突破任何世界规则。"
        if wr0_enabled else
        "【WR0 状态】关闭 — 扩展内容必须与既有世界规则、基调、L3设计意图保持一致。"
    )

    prompt = f"""{l3_ctx}

【当前场景】
  位置：{request.scene_context.get('location', '')}
  描述：{request.scene_context.get('description', '')}
  可用场景：{', '.join(request.scene_context.get('available_scenes', []))}
  NPC状态：{json.dumps(request.scene_context.get('npc_states', {}), ensure_ascii=False)}

【玩家意图】
  玩家想做什么：{request.intent}
  升级原因：{request.reasoning}
  玩家原话：{'; '.join(request.other_texts)}

{wr0_line}

请评估此意图的范围并生成响应：

1. 判断级别：
   - patch：行为合理但模组未覆盖 → 在当前可用场景中添加 entity
   - structural：行为完全超出模组范围，需要结构性扩展（新场景、新结局）

2. 如果 patch：
   {{
     "level": "patch",
     "entities": [
       {{
         "id": "SI1",
         "entity_type": "interaction",
         "scene": "场景名",
         "name": "entity名称",
         "type": "关联技能名或留空",
         "requirement": "",
         "trigger": "触发描述",
         "result": "结果描述",
         "side_effects": [],
         "graded_result": null,
         "difficulty": "regular"
       }}
     ],
     "scene_descriptions": {{}},
     "justification": "L3层面理由"
   }}

3. 如果 structural（触发补充管线）：
   {{
     "level": "structural",
     "entry_scene": "玩家当前场景",
     "exit_scene": "出口场景名或空",
     "justification": "为什么需要结构性扩展，引用L3设计意图"
   }}

4. 如果玩家意图违反世界规则且 WR0 关闭 → 打回：
   {{
     "level": "patch",
     "entities": [],
     "scene_descriptions": {{}},
     "justification": "为什么拒绝。格式: REJECTED: 具体原因"
   }}

规则：
- 只添加必要的entity，不要过度扩充
- structural 仅在玩家行为确实需要时才使用
- side_effects 使用 @function(param=value) 语法
- justification 必须引用L3设计意图
- entity ID 使用 S_ 前缀（SI1, SAT1, SE1 等）
- 直接输出 JSON
"""
    _show_prompt("Author", prompt)
    return prompt


# ── Combat Entry + Standoff ──

def build_combat_entry_prompt(
    player_input: str,
    outcomes_summary: str,
    enemy_context: str,
    current_scene: str,
) -> str:
    return f"""你是 COC 7th KP 助理。根据玩家行为、本轮结果和场景内敌人的习性，判断是否应进入回合制战斗。

玩家输入：{player_input}
本轮结果：{outcomes_summary}
当前位置：{current_scene}

场景内敌人：
{enemy_context}

请判断是否有敌人应进入战斗。输出 JSON：
{{"enter_combat": true/false, "enemy_instance_ids": ["..."], "reasoning": "简述判定理由"}}"""


_COC_SKILL_NAMES = [
    "会计", "人类学", "估价", "考古学", "魅惑", "攀爬", "计算机使用",
    "信用评级", "克苏鲁神话", "乔装", "闪避", "汽车驾驶", "电气维修",
    "电子学", "话术", "急救", "历史", "恐吓", "跳跃", "法律",
    "图书馆使用", "聆听", "锁匠", "机械维修", "医学", "博物学",
    "导航", "神秘学", "操作重型机械", "说服", "驾驶", "精神分析",
    "心理学", "读唇", "潜行", "侦查", "生存", "游泳", "投掷",
    "追踪", "驯兽",
]


def build_standoff_match_prompt(player_input: str) -> str:
    skill_list = "、".join(_COC_SKILL_NAMES)
    return f"""你是 COC 7th KP 助理。玩家在面对敌人时试图避免战斗。

玩家输入："{player_input}"

可用技能：{skill_list}

判断玩家意图对应的技能检定（如果有）：
{{"matched": true/false, "skill_name": "技能名", "reason": "简述为什么匹配"}}

规则：
- matched=false 表示玩家输入无法匹配为任何有意义的避免战斗的尝试（包括"什么都不做"、直接攻击等）
- 魅惑/取悦 → "魅惑"
- 说服/交涉/讲道理 → "说服"
- 潜行/偷偷溜走/绕过去 → "潜行"
- 恐吓/威胁 → "恐吓"
- 其他无法匹配的输出 matched=false"""


def build_combat_narrative_prompt(round_log: list, enemies_desc: str,
                                   player_name: str, scene: str) -> str:
    """Build prompt for per-round combat narrative generation."""
    log_text = ""
    for a in round_log:
        log_text += (
            f"  {'玩家' if a.actor == 'player' else a.actor} "
            f"{chr(10003) if a.success else chr(10007)} {a.weapon or a.action_type}: {a.narrative}\n"
        )

    return f"""你是一个TRPG战斗叙事者。根据本轮的机械结果，生成一段沉浸式战斗描写。

【场景】{scene}
【调查员】{player_name}
【敌人】{enemies_desc}

【本轮行动】
{log_text}

返回 JSON：
{{"narrative": "沉浸式战斗描写（中文不超过80字）", "scene_hint": ""}}
直接输出 JSON。"""
