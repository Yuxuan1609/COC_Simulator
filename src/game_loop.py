"""
游戏主循环 —— 多 Agent 架构入口。
Keeper (KP) / Narrator (叙事者) / Author (作者)
"""
from __future__ import annotations
from typing import Any
from datetime import datetime
import json

from scenario_core import DirectedGraph, ScenarioWorld, ItemGain, StatChange, SpawnEnemy, GrantWeapon, NPCStateChange
from game.agents import Keeper, Narrator, Author
from game.messages import TurnInput
from prompts import _build_investigator_info


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
              escalation_config_path: str,  # deprecated, kept for backward compat
              start_node: str = "6号车厢",
              wr0_enabled: bool = False) -> dict[str, Any]:
    """Initialize all agents and world state from JSON files.

    Returns dict with keys: keeper, narrator, author, l3_data.
    Access world via keeper.world.
    """
    # Load L2
    with open(l2_path, "r", encoding="utf-8") as f:
        l2 = json.load(f)

    # Load L1
    with open(l1_path, "r", encoding="utf-8") as f:
        l1 = json.load(f)

    # Load L3
    with open(l3_path, "r", encoding="utf-8") as f:
        l3 = json.load(f)

    # Resolve scene naming: L2 uses internal IDs (S1-S7) but game loop expects
    # Chinese names. _scene_names map (injected by pipeline Phase 2) provides
    # the mapping. In its absence, fall back to the old behaviour (S-keys).
    scene_map = l2.get("_scene_names", {})
    l2_scenes = l2.get("scenes", {})

    if scene_map:
        remapped_scenes = {}
        for sid, scene_data in l2_scenes.items():
            cn_name = scene_map.get(sid, sid)
            for lst in ("interactions", "auto_triggers"):
                for ent in scene_data.get(lst, []):
                    if ent.get("scene") in scene_map:
                        ent["scene"] = scene_map[ent["scene"]]
            for edge in scene_data.get("from_here", []):
                if edge.get("target") in scene_map:
                    edge["target"] = scene_map[edge["target"]]
            for edge in scene_data.get("to_here", []):
                for field in ("source", "target"):
                    if edge.get(field) in scene_map:
                        edge[field] = scene_map[edge[field]]
            if not scene_data.get("description"):
                l1_scene = l1.get(cn_name, {})
                if isinstance(l1_scene, dict) and l1_scene.get("description"):
                    scene_data["description"] = l1_scene["description"]
            remapped_scenes[cn_name] = scene_data
        for ev in l2.get("events", []):
            if ev.get("scene") in scene_map:
                ev["scene"] = scene_map[ev["scene"]]
        start_node = scene_map.get(start_node, start_node)
        graph = DirectedGraph(scenes=remapped_scenes, events=l2.get("events", []))
    else:
        graph = DirectedGraph(scenes=l2_scenes, events=l2.get("events", []))

    world = ScenarioWorld(graph, start_node=start_node, wr0_enabled=wr0_enabled)

    # Load dependency graph into world for runtime state tracking
    dep_graph = l2.get("dependency_graph", {})
    world.load_dependency_graph(dep_graph)

    # Init agents
    narrator = Narrator(l1)
    keeper = Keeper(
        world,
        dependency_graph=l2.get("dependency_graph"),
        phase1=l2.get("_phase1"),
        npc_profiles=l2.get("npc_profiles"),
    )
    author = Author(l3)
    keeper.narrator_l1 = l1  # Keeper holds reference for supplement merging

    return {
        "keeper": keeper,
        "narrator": narrator,
        "author": author,
    }


def run_turn(game: dict, user_input: str,
             weapon_lib=None, enemy_lib=None, injector=None) -> dict:
    """Execute one turn. Returns {"brief": str, "narrative": str, "full": str}."""
    keeper = game["keeper"]
    narrator = game["narrator"]
    author = game["author"]
    world = keeper.world

    # Handle debug commands
    if user_input.strip().startswith("/"):
        cmd_result = _handle_spawn_command(user_input, world, weapon_lib, enemy_lib, injector)
        if cmd_result:
            return cmd_result

    turn_input = TurnInput(raw_text=user_input, player=world.player)
    result = keeper.process_turn(turn_input, author=author)

    brief = result["brief"]
    if hasattr(brief, 'action_outcomes'):
        display_brief = "\n".join(o.message for o in brief.action_outcomes)
    else:
        display_brief = str(brief) if brief else ""

    # Extract skill check results from outcomes for player display
    skill_results = []
    if hasattr(brief, 'action_outcomes'):
        for o in brief.action_outcomes:
            if o.skill_tier and o.entity_id:
                skill_results.append({
                    "entity_id": o.entity_id,
                    "entity_type": o.entity_type,
                    "tier": o.skill_tier,
                    "success": o.success,
                    "detail": o.skill_detail,
                })

    try:
        narrative_brief, narrative = narrator.narrate(
            brief, inv_info=_build_investigator_info(world), user_input=user_input)
    except Exception as e:
        narrative_brief = display_brief or "（处理中）"
        narrative = "（叙事生成暂时不可用，但你的行动结果仍然有效。请继续输入下一步行动。）"

    ending = result.get("ending_name")
    return {
        "brief": narrative_brief,
        "narrative": narrative,
        "full": f"{narrative_brief}\n\n\n{narrative}",
        "skill_results": skill_results,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "ending": {"name": ending, "narrative": result.get("ending_narrative", "")} if ending else None,
    }
