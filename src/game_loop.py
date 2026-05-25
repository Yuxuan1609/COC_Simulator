"""
游戏主循环 —— 多 Agent 架构入口。
Keeper (KP) / Narrator (叙事者) / Author (作者)
"""
from __future__ import annotations
from typing import Any
from datetime import datetime
import json

from scenario_core import DirectedGraph, ScenarioWorld
from game.agents import Keeper, Narrator, Author
from game.messages import TurnInput, CombatInit
from game.combat import CombatSystem
from game.turn_logger import TurnLogger
from config import WR0_ENABLED

_turn_logger: TurnLogger | None = None


def set_turn_logger(logger: TurnLogger):
    """Set the global turn logger (called from harness or main entry)."""
    global _turn_logger
    _turn_logger = logger




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

    if cmd == "/health":
        from monitor.health import PipelineHealth
        from llm import get_sensor
        sensor = get_sensor()
        if sensor:
            health = PipelineHealth(sensor)
            snap = health.snapshot()
            lines = ["Pipeline Health:"]
            lines.append(f"  Uptime: {snap['uptime_seconds']}s")
            lines.append(f"  Total calls: {snap['total_calls']} / Failures: {snap['total_failures']} / Slow: {snap['total_slow']}")
            for agent, stats in snap.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            return {"brief": "\n".join(lines), "narrative": "\n".join(lines), "full": "\n".join(lines)}
        return {"brief": "Monitor not initialized.", "narrative": "监控未初始化", "full": "监控未初始化"}

    return None


# ── New entry point ──

def init_game(l2_path: str, l1_path: str, l3_path: str,
               start_node: str = "6号车厢",
               wr0_enabled: bool = WR0_ENABLED) -> dict[str, Any]:
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

    # Load enemy library
    from library import EnemyLibrary
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()

    # Load weapon library
    from library.weapons import WeaponLibrary
    weapon_lib = WeaponLibrary()
    weapon_lib.load_core()

    # Load boss library
    from library.bosses import BossLibrary
    boss_library = BossLibrary("data/library/core/bosses.json")
    boss_encounters = l2.get("boss_encounters", [])

    # Prepare NPC profiles (scene assignment from L2 data)
    npc_profiles = l2.get("npc_profiles", {})
    for scene_name, scene_data in l2_scenes.items():
        for npc_data in scene_data.get("npcs", []):
            name = npc_data.get("name", "")
            if name in npc_profiles:
                if "scene" not in npc_profiles[name] or not npc_profiles[name]["scene"]:
                    npc_profiles[name] = {**npc_profiles[name], "scene": scene_name}

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib,
                          weapon_library=weapon_lib,
                          boss_library=boss_library,
                          boss_encounters=boss_encounters,
                          npc_profiles=npc_profiles)

    # Load dependency graph into world for runtime state tracking
    dep_graph = l2.get("dependency_graph", {})
    world.load_dependency_graph(dep_graph)

    # Load time costs reference
    try:
        import json as _json, os as _os
        tc_path = _os.path.join("data", "library", "core", "time_costs.json")
        if _os.path.exists(tc_path):
            with open(tc_path, "r", encoding="utf-8") as f:
                world.time_costs = _json.load(f)
    except Exception:
        world.time_costs = {}

    module_meta = l2.get("module_meta", {})
    if module_meta.get("comms_interval"):
        world.comms_interval = module_meta["comms_interval"]

    # Init agents
    narrator = Narrator(l1)
    keeper = Keeper(
        world,
        phase1=l2.get("_phase1"),
    )
    author = Author(l3)
    keeper.narrator_l1 = l1

    return {
        "keeper": keeper,
        "narrator": narrator,
        "author": author,
    }


def run_turn(game: dict, user_input: str,
             weapon_lib=None, enemy_lib=None, injector=None) -> dict:
    """Execute one turn. Returns {"brief": str, "narrative": str, "full": str}."""
    keeper = game["keeper"]
    from prompts import set_current_round
    set_current_round(keeper.turn_number)
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

    # Combat entry: if process_turn returned CombatInit, run the combat system
    combat_narrative = ""
    combat_result_outcome = None
    combat_init = result.get("combat_init")
    if combat_init and combat_init.enemies:
        try:
            cs = CombatSystem(weapon_lib=weapon_lib)
            combat_result = cs.run_combat(combat_init)
            combat_narrative = combat_result.narrative
            combat_result_outcome = combat_result.outcome
            # Callback to EnemyManager
            result_dict = {
                "outcome": combat_result.outcome,
                "defeated_instance_ids": combat_result.defeated_instance_ids,
            }
            world.enemy_manager.exit_combat(result_dict)

            # Boss post-combat resolution
            if world.bosses and world.bosses.active_boss_id:
                world.bosses.resolve_outcome(combat_result)
                if combat_result.outcome == "win":
                    world.mark_completed(world.bosses.active_boss_id, "")
                world.bosses.set_active(None)
        except Exception:
            combat_result_outcome = "error"

    # Extract skill check results from outcomes for player display
    skill_results = []
    if hasattr(brief, 'action_outcomes'):
        for o in brief.action_outcomes:
            if o.skill_tier and o.entity_id:
                entry = {
                    "entity_id": o.entity_id,
                    "entity_type": o.entity_type,
                    "tier": o.skill_tier,
                    "success": o.success,
                    "raw_check": o.skill_detail,
                }
                if o.enhancement:
                    entry["enhancement"] = o.enhancement
                skill_results.append(entry)

    try:
        snap = world.build_snapshot()
        narrative_brief, narrative, scene_update = narrator.narrate(
            brief, snap=snap, user_input=user_input)
        # Record brief to memory after narrator generates the final brief text
        world.memory.add_record(
            user_input, "narrated", "",
            narrative_brief, location=world.current_location,
            success=True,
        )
        if scene_update:
            world.apply_scene_update(scene_update)

        # TurnLogger: record player input + enrich + narrator output
        if _turn_logger:
            _turn_logger.log(
                player_input=user_input,
                enrich_result=result.get("enrich"),
                narrator_brief=narrative_brief,
                narrator_narrative=narrative,
            )
    except Exception as e:
        narrative_brief = display_brief or "（处理中）"
        narrative = "（叙事生成暂时不可用，但你的行动结果仍然有效。请继续输入下一步行动。）"
        scene_update = ""

    ending = result.get("ending")  # {name, narrative, game_over} or None
    standoff = result.get("standoff_prompt")
    full_text = f"{narrative_brief}"
    if combat_narrative:
        full_text += f"\n\n---\n⚔ 战斗回合\n{combat_narrative}"
    full_text += f"\n\n\n{narrative}"

    # NPC visible output
    npcs_visible = {"in_scene": [], "following": []}
    npc_events_out = result.get("npc_events", [])
    if world.npcs:
        in_scene = world.npcs.get_in_scene(world.current_location)
        npcs_visible["in_scene"] = [n.name for n in in_scene if n.state not in ("dead", "left")]
        npcs_visible["following"] = [n.name for n in world.npcs.get_following()]

    return {
        "brief": narrative_brief,
        "narrative": narrative,
        "full": full_text,
        "skill_results": skill_results,
        "combat": {
            "outcome": combat_result_outcome,
            "narrative": combat_narrative,
        } if combat_result_outcome else None,
        "standoff_prompt": standoff,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "ending": ending,
        "scene_update": scene_update,
        "game_over": ending.get("game_over", False) if ending else False,
        "time_agent": result.get("time_agent"),
        "npcs_visible": npcs_visible,
        "npc_events": npc_events_out,
    }


def continue_standoff(keeper, player_input: str) -> dict:
    """Process a standoff avoidance attempt. Returns updated state with optional combat_init."""
    s = keeper._standoff_pending
    if not s:
        return {"standoff_resolved": True, "avoided": False,
                "message": "无待处理的对峙。", "combat_init": None}

    result = keeper.resolve_standoff(s, player_input)

    combat_init = None
    if result.get("avoided"):
        groups = s.get("groups", {})
        current_ref = s.get("current_group", "")
        remaining = [ref for ref in groups if ref != current_ref]
        if remaining:
            next_ref = remaining[0]
            s["current_group"] = next_ref
            result["next_standoff"] = f"你还有最后一次机会避免与{next_ref}的战斗——你要怎么做？"
        elif s.get("hostile_iids"):
            enemies = [keeper.world.enemy_manager.get_by_id(iid)
                      for iid in s["hostile_iids"]
                      if keeper.world.enemy_manager and keeper.world.enemy_manager.get_by_id(iid)]
            enemies = [e for e in enemies if e is not None]
            if enemies and keeper.world.enemy_manager:
                keeper.world.enemy_manager.enter_combat(s["hostile_iids"])
                combat_init = CombatInit(
                    enemies=enemies, player=keeper.world.player,
                    scene=keeper.world.current_location,
                    initiative_context=s.get("reasoning", ""),
                )
    else:
        all_iids = s.get("all_enemy_iids", [])
        enemies = [keeper.world.enemy_manager.get_by_id(iid)
                  for iid in all_iids
                  if keeper.world.enemy_manager and keeper.world.enemy_manager.get_by_id(iid)]
        enemies = [e for e in enemies if e is not None]
        if enemies and keeper.world.enemy_manager:
            keeper.world.enemy_manager.enter_combat(all_iids)
            combat_init = CombatInit(
                enemies=enemies, player=keeper.world.player,
                scene=keeper.world.current_location,
                initiative_context=s.get("reasoning", ""),
            )

    result["combat_init"] = combat_init

    # Run combat if resolved into combat
    if combat_init and combat_init.enemies:
        try:
            cs = CombatSystem(weapon_lib=keeper.world.weapon_library)
            combat_result = cs.run_combat(combat_init)
            result["combat_narrative"] = combat_result.narrative
            result["combat_outcome"] = combat_result.outcome
            keeper.world.enemy_manager.exit_combat({
                "outcome": combat_result.outcome,
                "defeated_instance_ids": combat_result.defeated_instance_ids,
            })
        except Exception:
            result["combat_outcome"] = "error"

    return result
