"""
游戏主循环 —— 动作执行 + LLM 调用链编排。

从 notebook_simplified.ipynb 提取，不包含 UI 逻辑。
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld
from llm import call_deepseek
from prompts import (
    build_action_prompt,
    build_event_prompt,
    build_action_world_update,
    build_event_world_update,
    build_narrative_prompt,
    build_improvise_prompt,
    log_skill_result,
    parse_narrative_output,
)


def _execute_single_action(act: dict, world: ScenarioWorld, location: str) -> tuple:
    """执行单个动作，返回 (result_text, success)"""
    action = act.get("action", "other")

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


def handle_user_input(user_input: str, world: ScenarioWorld) -> dict:
    """
    处理流程：
    1. 阶段1 & 阶段2 并行 —— 动作解析 + 事件判定
    2. 阶段1a：执行 interact/search/look 等场景内动作
    3. 阶段1.5a：动作世界更新（基于 interact 结果更新场景描述）
    4. 阶段1b：执行 move 动作（在已更新的场景中移动）
    5. 阶段2：执行事件
    6. 阶段1.5b：事件世界更新
    7. 阶段3：叙事生成 + 输出解析

    返回 {"brief": 简要结果, "narrative": 沉浸式叙事, "full": 完整输出}
    """

    # ═══ 阶段1 & 阶段2：并行 LLM 调用 ═══
    try:
        action_data = call_deepseek(
            build_action_prompt(world, user_input),
            json_mode=True
        )
    except Exception as e:
        return {"brief": f"[系统错误] 动作解析失败：{e}",
                "narrative": f"（系统错误：{e}）",
                "full": f"[系统错误] 动作解析失败：{e}"}

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
    any_scene_executed = False  # 是否有动作通过闸门并执行（用于世界更新判定）

    for act in scene_actions:
        # ── 统一闸门：条件检查 + 技能检定 ──
        condition = act.get("condition", "")
        if condition:
            action_results.append(f"（无法执行：{condition}）")
            continue

        skill_checks = act.get("skill_checks", [])
        if skill_checks and world.player:
            all_pass, skill_result = world.player.check_skills(skill_checks)
            log_skill_result(skill_result)
            if not all_pass:
                action_results.append(skill_result)
                continue

        # 闸门通过，执行动作
        result, _ = _execute_single_action(act, world, location)
        action_results.append(result)
        any_scene_executed = True

    # ═══ 阶段1.5a：动作世界更新（仅在闸门通过的动作实际执行后）═══
    if any_scene_executed:
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
        result, _ = _execute_single_action(act, world, location)
        action_results.append(result)

    action_result = "\n".join(action_results)

    # ═══ 阶段2：执行事件 ═══
    events_result = ""
    any_event_triggered = False
    for eid in event_data.get("triggered_events", []):
        ok, msg = world.trigger_event(eid)
        if ok:
            events_result += msg + "\n"
            any_event_triggered = True
        else:
            events_result += f"（事件「{eid}」触发失败：{msg}）\n"
    for eid, condition_text in event_data.get("condition_events", {}).items():
        events_result += f"（无法触发事件「{eid}」：{condition_text}）\n"
    for flag_key, flag_val in event_data.get("new_flags", {}).items():
        world.set_flag(flag_key, flag_val)
        events_result += f"[标记更新] {flag_key} = {flag_val}\n"

    # ═══ 阶段1.5b：事件世界更新（仅在事件实际触发后）═══
    if any_event_triggered:
        try:
            update = call_deepseek(
                build_event_world_update(world, events_result),
                json_mode=True
            )
            world.apply_world_update(update["abstract"])
        except Exception:
            pass

    # ═══ 阶段3：叙事生成 ═══
    first_action = actions[0].get("action", "other")
    all_other = all(a.get("action") == "other" for a in actions)
    try:
        if all_other and not event_data.get("triggered_events"):
            full_text = call_deepseek(
                build_improvise_prompt(world, user_input, action_result),
                json_mode=False
            )
        else:
            full_text = call_deepseek(
                build_narrative_prompt(world, user_input, action_result, events_result),
                json_mode=False
            )
        brief, narrative = parse_narrative_output(full_text)
    except Exception as e:
        brief = action_result
        narrative = f"（叙事生成失败：{e}）"
        full_text = f"{brief}\n\n\n沉浸式叙事：{narrative}"

    # ═══ 记录 ═══（只记录简要结果）
    first_target = actions[0].get("target")
    any_success = any_scene_executed or bool(move_actions)
    world.memory.add_record(user_input, first_action, first_target,
                            brief, location=location, success=any_success)

    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

    return {"brief": brief, "narrative": narrative, "full": full_text}
