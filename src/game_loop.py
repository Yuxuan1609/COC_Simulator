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
from scenario_core import FlagSet, ItemGain, StatChange, SpawnEnemy, GrantItem, NPCStateChange, ActionResult


def _apply_side_effects(world: ScenarioWorld, side_effects: list) -> list:
    """
    消费 side effects。当前实现：
    - ItemGain → world.memory.note_item
    - SpawnEnemy → 记录到运行时遭遇表
    - GrantItem → 记录到 world.memory
    - NPCStateChange → world.set_npc_state
    - StatChange → 仅记录不修改状态（COC SAN 规则待后续细化）

    返回人类可读的副作用摘要列表。
    """
    msgs = []
    for effect in side_effects:
        if isinstance(effect, FlagSet):
            world.set_flag(effect.key, effect.value)
            msgs.append(f"[标记] {effect.key} = {effect.value}")
        elif isinstance(effect, ItemGain):
            world.memory.note_item(effect.item_name)
            msgs.append(f"[获得物品] {effect.item_name}")
        elif isinstance(effect, SpawnEnemy):
            target_scene = effect.scene or world.current_location
            msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}")
        elif isinstance(effect, GrantItem):
            world.memory.note_item(effect.item_ref)
            msgs.append(f"[授予物品] {effect.item_ref}")
        elif isinstance(effect, NPCStateChange):
            world.set_npc_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} → {effect.new_state}")
        elif isinstance(effect, StatChange):
            msgs.append(f"[属性变化] {effect.stat_name} {'+' if effect.delta > 0 else ''}{effect.delta}（未自动应用）")
    return msgs


def _execute_single_action(act: dict, world: ScenarioWorld, location: str) -> tuple:
    """执行单个动作，返回 (ActionResult, any_executed: bool)"""
    action = act.get("action", "other")

    if action == "move":
        target = act.get("target", "")
        if not target:
            return ActionResult(False, "（试图移动但未指定目标）"), False
        result = world.move(target)
        return result, result.success

    elif action == "interact":
        name = act.get("interaction", "")
        if not name:
            return ActionResult(False, "（试图执行动作但未指定名称）"), False
        result = world.execute_interaction(name)
        return result, result.success

    elif action == "search":
        interactions = world.get_available_interactions()
        done = world.completed_interactions.get(location, set())
        available = [i for i in interactions if i.name not in done]
        if available:
            lines = ["（环顾四周，注意到可以做的事：）"]
            for inter in available:
                lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
            return ActionResult(True, "\n".join(lines)), True
        else:
            return ActionResult(True, "（仔细查看四周，没有特别的发现）"), True
    else:
        return ActionResult(True, "（没有特别的事情发生"
                                  ""
                                  "）"), True


# ── 调试命令处理 ──

def _handle_spawn_command(user_input: str, world: ScenarioWorld,
                          weapon_lib=None, enemy_lib=None, injector=None) -> dict | None:
    """处理 /spawn 和 /inject 调试命令。返回 None 表示不是调试命令。"""
    parts = user_input.strip().split()
    if not parts:
        return None

    cmd = parts[0].lower()

    if cmd == "/spawn":
        if len(parts) < 3:
            return {"brief": "/spawn 用法：/spawn enemy <name> 或 /spawn weapon <name>",
                    "narrative": "用法错误", "full": "用法错误"}
        sub = parts[1].lower()
        name = " ".join(parts[2:])
        if sub == "enemy":
            if not enemy_lib:
                return {"brief": "敌人库未加载", "narrative": "错误", "full": "错误"}
            enemy = enemy_lib.get(name)
            if not enemy:
                available = [e.name for e in enemy_lib.list_all()]
                return {"brief": f"未知敌人「{name}」。可用：{', '.join(available)}",
                        "narrative": f"敌人库中没有「{name}」", "full": f"未知敌人：{name}"}
            if injector:
                encounter = injector.runtime_spawn_enemy(name, world.current_location, world)
                if encounter:
                    return {"brief": f"[生成敌人] {name} x{encounter['quantity']} 在 {world.current_location}",
                            "narrative": f"KP从库中释放了{name}！",
                            "full": f"spawn enemy: {name}"}
            return {"brief": f"[生成敌人] {name} x1 在 {world.current_location}",
                    "narrative": f"KP从库中释放了{name}！",
                    "full": f"spawn enemy: {name}"}
        elif sub == "weapon":
            if not weapon_lib:
                return {"brief": "武器库未加载", "narrative": "错误", "full": "错误"}
            weapon = weapon_lib.get(name)
            if not weapon:
                available = [w.name for w in weapon_lib.list_all()]
                return {"brief": f"未知武器「{name}」。可用：{', '.join(available)}",
                        "narrative": f"武器库中没有「{name}」", "full": f"未知武器：{name}"}
            world.memory.note_item(name)
            return {"brief": f"[授予武器] {name}",
                    "narrative": f"你获得了{name}。",
                    "full": f"spawn weapon: {name}"}
        else:
            return {"brief": f"未知子命令「{sub}」。用法：/spawn enemy <name> 或 /spawn weapon <name>",
                    "narrative": "用法错误", "full": "用法错误"}

    if cmd == "/inject":
        if len(parts) < 2:
            if injector:
                s = injector.status
                return {"brief": f"离线注入：{'开' if s['offline_enabled'] else '关'} | "
                                f"运行时注入：{'开' if s['runtime_enabled'] else '关'} | "
                                f"武器：{s['weapons_loaded']} | 敌人：{s['enemies_loaded']}",
                        "narrative": f"注入状态：武器{s['weapons_loaded']}件，敌人{s['enemies_loaded']}个",
                        "full": str(s)}
            return {"brief": "注入器未初始化", "narrative": "错误", "full": "错误"}
        sub = parts[1].lower()
        if sub == "toggle" and injector:
            injector.runtime_enabled = not injector.runtime_enabled
            state = "开启" if injector.runtime_enabled else "关闭"
            return {"brief": f"运行时注入已{state}", "narrative": f"运行时注入已{state}",
                    "full": f"inject toggle: {state}"}
        elif sub == "status" and injector:
            s = injector.status
            return {"brief": str(s), "narrative": str(s), "full": str(s)}
        return {"brief": "用法：/inject [toggle|status]", "narrative": "用法错误", "full": "用法错误"}

    return None


def _check_deviation(user_input: str, world: ScenarioWorld,
                     l3_data=None, deviation_threshold: float = 0.5) -> float:
    """
    Phase 3.5 偏离检测桩。
    当前返回 0.0（始终无偏离）。完整的 LLM-based 偏离检测留待后续实现。
    """
    return 0.0


def handle_user_input(user_input: str, world: ScenarioWorld,
                      weapon_lib=None, enemy_lib=None, injector=None,
                      l1_data: dict = None, l3_data=None) -> dict:
    """
    处理流程：
    0. 调试命令检查（/spawn, /inject）
    1. 阶段1 & 阶段2 并行 —— 动作解析 + 事件判定
    2. 阶段1a：执行 interact/search/look 等场景内动作
    3. 阶段1.5a：动作世界更新（基于 interact 结果更新场景描述）
    4. 阶段1b：执行 move 动作（在已更新的场景中移动）
    5. 阶段2：执行事件
    6. 阶段1.5b：事件世界更新
    7. 阶段3：叙事生成 + 输出解析
    8. 阶段3.5：偏离检测 + 即兴注入（预留）

    返回 {"brief": 简要结果, "narrative": 沉浸式叙事, "full": 完整输出}
    """

    # ═══ 阶段0：调试命令检查 ═══
    if user_input.strip().startswith("/"):
        cmd_result = _handle_spawn_command(user_input, world, weapon_lib, enemy_lib, injector)
        if cmd_result:
            return cmd_result

    # 获取当前场景 L1 数据
    l1_scene = l1_data.get(world.current_location) if l1_data else None

    # ═══ 阶段1 & 阶段2：并行 LLM 调用 ═══
    try:
        # call_deepseek(json_mode=True) → temperature=0.3, max_tokens=162840
        action_data = call_deepseek(
            build_action_prompt(world, user_input),
            json_mode=True
        )
    except Exception as e:
        return {"brief": f"[系统错误] 动作解析失败：{e}",
                "narrative": f"（系统错误：{e}）",
                "full": f"[系统错误] 动作解析失败：{e}"}

    try:
        # call_deepseek(json_mode=True) → temperature=0.3, max_tokens=162840
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
        result, executed = _execute_single_action(act, world, location)
        action_results.append(result.message)
        if executed:
            any_scene_executed = True
            # 消费声明式副作用
            side_msgs = _apply_side_effects(world, result.side_effects)
            action_results.extend(side_msgs)

    # ═══ 阶段1.5a：动作世界更新（仅在闸门通过的动作实际执行后）═══
    if any_scene_executed:
        scene_action_result = "\n".join(action_results)
        try:
            # call_deepseek(json_mode=True) → temperature=0.3, max_tokens=162840
            update = call_deepseek(
                build_action_world_update(world, scene_action_result, user_input),
                json_mode=True
            )
            world.apply_scene_update(update["description"])
        except Exception:
            pass

    # ═══ 阶段1b：执行 move 动作 ═══
    any_move_executed = False
    for act in move_actions:
        result, executed = _execute_single_action(act, world, location)
        action_results.append(result.message)
        if executed:
            any_move_executed = True
            side_msgs = _apply_side_effects(world, result.side_effects)
            action_results.extend(side_msgs)

    action_result = "\n".join(action_results)

    # ═══ 阶段2：执行事件 ═══
    events_result = ""
    any_event_triggered = False
    for eid in event_data.get("triggered_events", []):
        # 引擎二次确认：条件是否真的满足
        event = world.graph.get_event(eid)
        if event and event.requirements:
            met, reason = world.requirement_resolver.check(event.requirements)
            if not met:
                events_result += f"（事件「{eid}」条件不满足：{reason}）\n"
                continue
        result = world.trigger_event(eid)
        if result.success:
            events_result += result.message + "\n"
            any_event_triggered = True
            side_msgs = _apply_side_effects(world, result.side_effects)
            events_result += "\n".join(side_msgs) + "\n"
        else:
            events_result += f"（事件「{eid}」触发失败：{result.message}）\n"
    for eid, condition_text in event_data.get("condition_events", {}).items():
        events_result += f"（无法触发事件「{eid}」：{condition_text}）\n"
    for flag_key, flag_val in event_data.get("new_flags", {}).items():
        world.set_flag(flag_key, flag_val)
        events_result += f"[标记更新] {flag_key} = {flag_val}\n"

    # ═══ 阶段1.5b：事件世界更新（仅在事件实际触发后）═══
    if any_event_triggered:
        try:
            # call_deepseek(json_mode=True) → temperature=0.3, max_tokens=162840
            update = call_deepseek(
                build_event_world_update(world, events_result),
                json_mode=True
            )
            world.apply_world_update(update["abstract"])
        except Exception:
            pass

    # ═══ 阶段3.5：偏离检测 + 即兴注入（桩）═══
    deviation_score = _check_deviation(user_input, world, l3_data)
    _ = deviation_score  # 预留，当前始终为 0

    # ═══ 阶段3：叙事生成 ═══
    first_action = actions[0].get("action", "other")
    all_other = all(a.get("action") == "other" for a in actions)
    try:
        if all_other and not event_data.get("triggered_events"):
            # call_deepseek(json_mode=False) → temperature=0.7, max_tokens=20000
            full_text = call_deepseek(
                build_improvise_prompt(world, user_input, action_result,
                                       l1_scene=l1_scene, l3_data=l3_data),
                json_mode=False
            )
        else:
            # call_deepseek(json_mode=False) → temperature=0.7, max_tokens=20000
            full_text = call_deepseek(
                build_narrative_prompt(world, user_input, action_result, events_result,
                                       l1_scene=l1_scene, l3_data=l3_data),
                json_mode=False
            )
        brief, narrative = parse_narrative_output(full_text)
    except Exception as e:
        brief = action_result
        narrative = f"（叙事生成失败：{e}）"
        full_text = f"{brief}\n\n\n沉浸式叙事：{narrative}"

    # ═══ 记录 ═══（只记录简要结果）
    first_target = actions[0].get("target")
    any_success = any_scene_executed or any_move_executed
    world.memory.add_record(user_input, first_action, first_target,
                            brief, location=location, success=any_success)

    if world.memory.should_compress():
        # call_deepseek(json_mode=False) → temperature=0.7, max_tokens=20000
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False))

    return {"brief": brief, "narrative": narrative, "full": full_text}
