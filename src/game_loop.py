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
        condition = act.get("condition", "")
        if condition:
            result = f"（无法执行：{condition}）"
            success = False
        else:
            # ═══ 技能闸门（COC 7th D100 检定）═══
            skill_checks = act.get("skill_checks", [])
            if skill_checks and world.player:
                all_pass, skill_result = world.player.check_skills(skill_checks)
                log_skill_result(skill_result)
                if not all_pass:
                    action_results.append(skill_result)
                    overall_success = False
                    continue
            result, success = _execute_single_action(act, world, location)
        action_results.append(result)
        if not success:
            overall_success = False

    # ═══ 阶段1.5a：动作世界更新（在移动之前）═══
    # had_interact = any(a.get("action") == "interact" for a in scene_actions)
    had_interact = True # 暂时设置为常触发，之后修改
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
    for eid, condition_text in event_data.get("condition_events", {}).items():
        events_result += f"（无法触发事件「{eid}」：{condition_text}）\n"
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
    first_action = actions[0].get("action", "other")
    all_other = all(a.get("action") == "other" for a in actions)
    try:
        if all_other and not event_data.get("triggered_events"):
            narrative = call_deepseek(
                build_improvise_prompt(world, user_input, action_result),
                json_mode=False
            )
        else:
            narrative = call_deepseek(
                build_narrative_prompt(world, user_input, action_result, events_result),
                json_mode=False
            )
    except Exception as e:
        narrative = f"{action_result}\n\n（叙事生成失败：{e}）"

    # ═══ 记录 ═══
    first_target = actions[0].get("target")
    world.memory.add_record(user_input, first_action, first_target,
                            narrative, location=location, success=overall_success)

    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

    return narrative
