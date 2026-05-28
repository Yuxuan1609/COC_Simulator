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
from game.messages import TurnInput, CombatInit, CombatResult, PlayerFacingSnapshot, SkillCheckResult
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

    # Prepare NPC profiles (scene assignment now from Step 1a in pipeline)
    npc_profiles = l2.get("npc_profiles", {})

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

    # Combat entry: short-circuited — one-turn auto-win, combat engine bypassed
    combat_narrative = ""
    combat_result_outcome = None
    combat_is_boss = False
    combat_death = False
    combat_boss_loss = False
    combat_init = result.get("combat_init")
    if combat_init and combat_init.enemies:
        enemy_names = ", ".join(
            getattr(e, 'enemy_ref', getattr(e, 'name', '未知敌人'))
            for e in combat_init.enemies
        )
        defeated_ids = []
        for ei in combat_init.enemies:
            eid = getattr(ei, 'instance_id', '')
            if eid:
                defeated_ids.append(eid)
            if hasattr(ei, 'hp'):
                ei.hp = 0

        combat_result_outcome = "win"
        combat_narrative = (
            f"你侥幸战胜了{enemy_names}，但战斗极其惨烈。"
            f"你深深意识到正面冲突的危险——应尽可能通过潜行、回避或交涉来规避战斗。"
        )
        combat_is_boss = bool(world.bosses and world.bosses.active_boss_id)

        # Write back HP/SAN (unchanged — no damage in short-circuit)
        # Callback to EnemyManager
        result_dict = {
            "outcome": "win",
            "defeated_instance_ids": defeated_ids,
        }
        world.enemy_manager.exit_combat(result_dict)

        if combat_is_boss:
            world.bosses.resolve_outcome(CombatResult(
                outcome="win",
                defeated_instance_ids=defeated_ids,
                player_hp=combat_init.player.derived.HP if combat_init.player else 10,
                player_san=combat_init.player.derived.SAN if combat_init.player else 60,
                rounds=1,
                narrative=combat_narrative,
            ))
            world.mark_completed(world.bosses.active_boss_id, "")
            world.bosses.set_active(None)

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

    if hasattr(brief, 'scene_snapshot'):
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
    else:
        # Keeper returned early with plain-text brief/narrative (boss trigger, weapon pickup, combat, etc.)
        narrative_brief = display_brief or result.get("narrative", "") or "（处理中）"
        narrative = result.get("narrative", "") or ""
        scene_update = ""
        if _turn_logger:
            _turn_logger.log(
                player_input=user_input,
                enrich_result=result.get("enrich"),
                narrator_brief=narrative_brief,
                narrator_narrative=narrative,
            )

    # Surface pending weapon offer to player (narrator may omit the pickup prompt)
    if keeper._weapon_offer:
        wo = keeper._weapon_offer
        wp_text = f"（你发现了{wo['weapon_ref']}。是否拾取？（是/否））"
        narrative = (narrative or "") + ("\n\n" if narrative else "") + wp_text
        if not narrative_brief:
            narrative_brief = wp_text

    ending = result.get("ending")  # {name, narrative, game_over} or None
    standoff = result.get("standoff_prompt")
    npc_events_out = result.get("npc_events", [])

    full_text = narrative_brief or ""
    if combat_narrative:
        full_text += f"\n\n---\n⚔ 战斗回合\n{combat_narrative}"
    if npc_events_out:
        full_text += f"\n[NPC] {'；'.join(npc_events_out)}"
    full_text += f"\n\n\n{narrative}"

    # NPC visible output
    npcs_visible = {"in_scene": [], "following": []}
    npc_events_out = result.get("npc_events", [])
    if world.npcs:
        in_scene = world.npcs.get_in_scene(world.current_location)
        npcs_visible["in_scene"] = [n.name for n in in_scene if n.state not in ("dead", "left")]
        npcs_visible["following"] = [n.name for n in world.npcs.get_following()]

    # ── Build PlayerFacingSnapshot ──
    import re as _re
    scene_name = world.current_location
    scene_description = ""
    scene_npcs = []
    if hasattr(brief, 'scene_snapshot') and brief.scene_snapshot:
        scene_description = brief.scene_snapshot.description
        scene_npcs = [
            {"name": n.get("name", ""), "brief": n.get("brief", ""), "demeanor": n.get("demeanor", "")}
            for n in brief.scene_snapshot.visible_npcs
        ]
    if not scene_description:
        scene_description = world.get_current_description()
    exits_data = [
        {"target": e.target, "method": e.method}
        for e in world.get_possible_exits()
    ]
    time_data = world.clock.to_dict()

    combat_data = None
    if combat_result_outcome:
        combat_data = {
            "outcome": combat_result_outcome,
            "narrative": combat_narrative,
            "is_boss": combat_is_boss,
        }

    skill_checks_out = []
    for s in skill_results:
        raw = s.get("raw_check", "")
        raw_roll, target = 0, 0
        m = _re.search(r"D100\s*=\s*(\d+)\s*/\s*(\d+)", raw)
        if m:
            raw_roll, target = int(m.group(1)), int(m.group(2))
        skill_checks_out.append(SkillCheckResult(
            entity_id=s.get("entity_id", ""),
            entity_type=s.get("entity_type", ""),
            tier=s.get("tier", ""),
            success=s.get("success", False),
            raw_roll=raw_roll,
            target=target,
            enhancement=s.get("enhancement"),
        ))

    player_snapshot = PlayerFacingSnapshot(
        scene_name=scene_name,
        scene_description=scene_description,
        exits=exits_data,
        time=time_data,
        npcs=scene_npcs,
        combat=combat_data,
        skill_checks=skill_checks_out,
    )

    return {
        "brief": narrative_brief,
        "narrative": narrative,
        "full": full_text,
        "player_snapshot": player_snapshot,
        "skill_results": skill_results,
        "combat": {
            "outcome": combat_result_outcome,
            "narrative": combat_narrative,
            "is_boss": combat_is_boss,
        } if combat_result_outcome else None,
        "combat_death": combat_death,
        "combat_boss_loss": combat_boss_loss,
        "standoff_prompt": standoff,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "ending": ending,
        "scene_update": scene_update,
        "game_over": ending.get("game_over", False) if ending else False or combat_death,
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
                    player_action="",
                    player_targets=[],
                    player_extra="",
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
                player_action="",
                player_targets=[],
                player_extra="",
            )

    result["combat_init"] = combat_init

    # Run combat if resolved into combat (short-circuited — one-turn auto-win)
    if combat_init and combat_init.enemies:
        enemy_names = ", ".join(
            getattr(e, 'enemy_ref', getattr(e, 'name', '未知敌人'))
            for e in combat_init.enemies
        )
        defeated_ids = []
        for ei in combat_init.enemies:
            eid = getattr(ei, 'instance_id', '')
            if eid:
                defeated_ids.append(eid)
            if hasattr(ei, 'hp'):
                ei.hp = 0

        result["combat_narrative"] = f"经过对峙，你凭借机智与勇气战胜了{enemy_names}。"
        result["combat_outcome"] = "win"
        keeper.world.enemy_manager.exit_combat({
            "outcome": "win",
            "defeated_instance_ids": defeated_ids,
        })

    return result


def format_turn_dynamic(
    player_snapshot: PlayerFacingSnapshot | dict | None,
    brief: str = "",
    narrative: str = "",
) -> str:
    """将 PlayerFacingSnapshot 的动态信息（时间/战斗/技能检定）+ Narrator 输出格式化为纯文本。

    仅包含动态变化的信息（不包含 scene_name/scene_description/exits/npcs 等静态场景信息）。
    CLI 和未来客户端可直接调用此函数获取结构化文本输出。
    """
    if player_snapshot is None:
        player_snapshot = {}

    snap = player_snapshot if isinstance(player_snapshot, dict) else {
        "time": getattr(player_snapshot, "time", {}),
        "combat": getattr(player_snapshot, "combat", None),
        "skill_checks": getattr(player_snapshot, "skill_checks", []),
    }

    parts = []

    # Time — clock.to_dict() returns {"game_time": int, "time_context": str}
    # Compute day/time_of_day from game_time (minutes since start)
    t = snap.get("time", {}) if isinstance(snap, dict) else {}
    if t:
        game_time = t.get("game_time", 0)
        day = game_time // 1440 if game_time else 0
        hour_val = (game_time % 1440) // 60 if game_time else 0
        if hour_val < 5: tod = "夜间"
        elif hour_val < 8: tod = "早晨"
        elif hour_val < 17: tod = "白天"
        elif hour_val < 20: tod = "黄昏"
        else: tod = "夜间"
        time_str = ""
        if day:
            time_str += f"第{day}天 "
        h, m = divmod(game_time, 60)
        time_str += f"{h:02d}:{m:02d}"
        if time_str:
            parts.append(f"[时间] {time_str}")

    # Combat
    c = snap.get("combat") if isinstance(snap, dict) else getattr(player_snapshot, "combat", None) if player_snapshot else None
    if c:
        label = {"win": "胜利", "loss": "败北", "flee": "逃脱"}.get(c.get("outcome", ""), c.get("outcome", ""))
        parts.append(f"[战斗] {label}")
        if c.get("narrative"):
            parts.append(c["narrative"])

    # Skill checks (original D100 + LLM trait enhancement)
    sc_list = snap.get("skill_checks", []) if isinstance(snap, dict) else getattr(player_snapshot, "skill_checks", []) if player_snapshot else []
    if sc_list:
        sc_lines = []
        for sc in sc_list:
            scd = sc if isinstance(sc, dict) else {"entity_id": getattr(sc, "entity_id", ""), "skill_name": getattr(sc, "skill_name", ""), "tier": getattr(sc, "tier", ""), "raw_roll": getattr(sc, "raw_roll", 0), "target": getattr(sc, "target", 0), "success": getattr(sc, "success", False), "enhancement": getattr(sc, "enhancement", None)}
            status = "OK" if scd.get("success") else "FAIL"
            tier = scd.get("tier", "")
            roll_info = f"D100={scd.get('raw_roll', 0)}/{scd.get('target', 0)}" if scd.get("raw_roll") else ""
            enh = scd.get("enhancement")
            enh_text = ""
            if enh:
                enh_tier = enh.get("tier") if isinstance(enh, dict) else getattr(enh, "tier", "")
                enh_reason = enh.get("reason") if isinstance(enh, dict) else getattr(enh, "reason", "")
                enh_override = enh.get("detail_override") if isinstance(enh, dict) else getattr(enh, "detail_override", "")
                if enh_override:
                    enh_text = f" 增强: {enh_override}"
                elif enh_tier and enh_tier != tier:
                    enh_text = f" →{enh_tier}"
                elif enh_reason and len(enh_reason) < 80:
                    enh_text = f" ({enh_reason[:60]})"
            sc_lines.append(f"  [{status}] {scd.get('entity_id', '?')} [{tier}] {roll_info}{enh_text}")
        if sc_lines:
            parts.append("[技能检定]\n" + "\n".join(sc_lines))

    # Brief
    if brief:
        parts.append(f"[概要] {brief}")

    # Narrative
    if narrative:
        parts.append(f"[叙事]\n{narrative}")

    return "\n\n".join(parts)
