"""
游戏主循环 —— 多 Agent 架构入口。
Keeper (KP) / Narrator (叙事者) / Author (作者)
"""
from __future__ import annotations
from typing import Any
import json

from scenario_core import DirectedGraph, ScenarioWorld, ItemGain, StatChange, SpawnEnemy, GrantWeapon, NPCStateChange
from game.agents import Keeper, Narrator, Author
from game.messages import TurnInput
from game.escalation import EscalationPolicy


# ── Side effect application ──

def _apply_side_effects(world: ScenarioWorld, side_effects: list) -> list:
    msgs = []
    for effect in side_effects:
        if isinstance(effect, ItemGain):
            world.memory.note_item(effect.item_name)
            msgs.append(f"[获得物品] {effect.item_name}")
        elif isinstance(effect, SpawnEnemy):
            target_scene = effect.scene or world.current_location
            msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}")
        elif isinstance(effect, GrantWeapon):
            world.memory.note_item(effect.weapon_ref)
            msgs.append(f"[授予武器] {effect.weapon_ref} x{effect.quantity}")
        elif isinstance(effect, NPCStateChange):
            world.set_npc_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")
        elif isinstance(effect, StatChange):
            sign = '+' if (isinstance(effect.delta, (int, float)) and effect.delta > 0) else ''
            msgs.append(f"[属性变化] {effect.stat_name} {sign}{effect.delta}（未自动应用）")
    return msgs


# ── Debug command handler ──

def _handle_spawn_command(user_input: str, world, weapon_lib=None, enemy_lib=None, injector=None) -> dict | None:
    """Handle /spawn and /inject debug commands. Returns None if not a debug command."""
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
                return {"brief": f"离线注入：{'开' if s['offline_enabled'] else '关'} | 运行时注入：{'开' if s['runtime_enabled'] else '关'} | 武器：{s['weapons_loaded']} | 敌人：{s['enemies_loaded']}",
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


# ── New entry point ──

def init_game(l2_path: str, l1_path: str, l3_path: str,
              escalation_config_path: str,
              start_node: str = "6号车厢",
              background_path: str | None = None) -> dict[str, Any]:
    """Initialize all agents and world state from JSON files."""
    # Load L2
    with open(l2_path, "r", encoding="utf-8") as f:
        l2 = json.load(f)

    # Load L1
    with open(l1_path, "r", encoding="utf-8") as f:
        l1 = json.load(f)

    # Load L3
    with open(l3_path, "r", encoding="utf-8") as f:
        l3 = json.load(f)

    # Load escalation config (optional)
    escalation_policy = None
    try:
        with open(escalation_config_path, "r", encoding="utf-8") as f:
            escalation_policy = EscalationPolicy.from_dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        escalation_policy = EscalationPolicy()

    # Load background story (optional)
    background = ""
    if background_path:
        try:
            with open(background_path, "r", encoding="utf-8") as f:
                background = f.read()
        except FileNotFoundError:
            pass

    # Build world
    graph = DirectedGraph(scenes=l2["scenes"], events=l2.get("events", []))
    world = ScenarioWorld(graph, start_node=start_node, background_story=background)

    # Init agents
    narrator = Narrator(l1)
    keeper = Keeper(
        world,
        dependency_graph=l2.get("dependency_graph"),
        phase1=l2.get("_phase1"),
        escalation_policy=escalation_policy,
        npc_profiles=l2.get("npc_profiles"),
    )
    author = Author(l3)

    return {
        "keeper": keeper,
        "narrator": narrator,
        "author": author,
        "world": world,
        "l3_data": author.l3_data,
    }


def run_turn(game: dict, user_input: str) -> dict:
    """Execute one turn. Returns {"brief": str, "narrative": str, "full": str}."""
    keeper = game["keeper"]
    narrator = game["narrator"]
    author = game["author"]
    world = game["world"]
    l3_data = game["l3_data"]

    # Handle debug commands
    if user_input.strip().startswith("/"):
        cmd_result = _handle_spawn_command(user_input, world)
        if cmd_result:
            return cmd_result

    turn_input = TurnInput(raw_text=user_input, player=world.player)
    result = keeper.process_turn(turn_input, author=author)

    brief = result["brief"]
    if hasattr(brief, 'action_outcomes'):
        display_brief = "\n".join(o.message for o in brief.action_outcomes)
    else:
        display_brief = str(brief) if brief else ""

    try:
        narrative_brief, narrative = narrator.narrate(brief, l3_data)
    except Exception as e:
        narrative_brief = display_brief or "（处理中）"
        narrative = f"（叙事生成失败：{e}）"

    return {
        "brief": narrative_brief,
        "narrative": narrative,
        "full": f"{narrative_brief}\n\n\n{narrative}",
    }
