"""
游戏主循环 —— 多 Agent 架构入口。
Keeper (KP) / Narrator (叙事者) / Author (作者)
"""
from __future__ import annotations
from typing import Any
from datetime import datetime
from pathlib import Path
import json
import os

from scenario_core import DirectedGraph, ScenarioWorld
from game.agents import Keeper, Narrator, Author
from game.messages import (TurnInput, CombatInit, CombatResult, PlayerFacingSnapshot, SkillCheckResult,
                           TurnStatus, TurnResult, PendingInteraction, PlayerTurnResult)
from game.turn_logger import TurnLogger
from config import WR0_ENABLED

_turn_logger: TurnLogger | None = None


def set_turn_logger(logger: TurnLogger):
    """Set the global turn logger (called from harness or main entry)."""
    global _turn_logger
    _turn_logger = logger


def setup_logging() -> str:
    """统一初始化日志目录 + TurnLogger。返回 log_dir 路径。"""
    from datetime import datetime
    from prompts import set_prompt_log_dir
    from llm import set_llm_log_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(Path(__file__).resolve().parent.parent / "logs" / f"prompt_log_{timestamp}")
    import os
    os.makedirs(log_dir, exist_ok=True)
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)
    set_turn_logger(TurnLogger(log_dir=log_dir))
    return log_dir




# ── Debug command handler ──

def _handle_spawn_command(user_input: str, world, weapon_lib=None, enemy_lib=None, injector=None, keeper=None) -> PlayerTurnResult | None:
    """Handle /spawn and /inject debug commands. Returns None if not a debug command."""
    parts = user_input.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower()

    if cmd == "/spawn":
        if len(parts) < 3:
            return PlayerTurnResult(status=TurnStatus.COMPLETED,
                    brief="/spawn 用法：/spawn enemy <name> 或 /spawn weapon <name>",
                    narrative="用法错误")
        sub = parts[1].lower()
        name = " ".join(parts[2:])
        if sub == "enemy":
            if not enemy_lib:
                return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="敌人库未加载", narrative="错误")
            enemy = enemy_lib.get(name)
            if not enemy:
                available = [e.name for e in enemy_lib.list_all()]
                return PlayerTurnResult(status=TurnStatus.COMPLETED,
                        brief=f"未知敌人「{name}」。可用：{', '.join(available)}",
                        narrative=f"敌人库中没有「{name}」")
            if injector:
                encounter = injector.runtime_spawn_enemy(name, world.current_location, world)
                if encounter:
                    return PlayerTurnResult(status=TurnStatus.COMPLETED,
                            brief=f"[生成敌人] {name} x{encounter['quantity']} 在 {world.current_location}",
                            narrative=f"KP从库中释放了{name}！")
            return PlayerTurnResult(status=TurnStatus.COMPLETED,
                    brief=f"[生成敌人] {name} x1 在 {world.current_location}",
                    narrative=f"KP从库中释放了{name}！")
        elif sub == "weapon":
            if not weapon_lib:
                return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="武器库未加载", narrative="错误")
            weapon = weapon_lib.get(name)
            if not weapon:
                available = [w.name for w in weapon_lib.list_all()]
                return PlayerTurnResult(status=TurnStatus.COMPLETED,
                        brief=f"未知武器「{name}」。可用：{', '.join(available)}",
                        narrative=f"武器库中没有「{name}」")
            world.memory.note_item(name)
            return PlayerTurnResult(status=TurnStatus.COMPLETED,
                    brief=f"[授予武器] {name}",
                    narrative=f"你获得了{name}。")
        else:
            return PlayerTurnResult(status=TurnStatus.COMPLETED,
                    brief=f"未知子命令「{sub}」。用法：/spawn enemy <name> 或 /spawn weapon <name>",
                    narrative="用法错误")

    if cmd == "/inject":
        if len(parts) < 2:
            if injector:
                s = injector.status
                return PlayerTurnResult(status=TurnStatus.COMPLETED,
                        brief=f"离线注入：{'开' if s['offline_enabled'] else '关'} | 运行时注入：{'开' if s['runtime_enabled'] else '关'} | 武器：{s['weapons_loaded']} | 敌人：{s['enemies_loaded']}",
                        narrative=f"注入状态：武器{s['weapons_loaded']}件，敌人{s['enemies_loaded']}个")
            return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="注入器未初始化", narrative="错误")
        sub = parts[1].lower()
        if sub == "toggle" and injector:
            injector.runtime_enabled = not injector.runtime_enabled
            state = "开启" if injector.runtime_enabled else "关闭"
            return PlayerTurnResult(status=TurnStatus.COMPLETED,
                    brief=f"运行时注入已{state}", narrative=f"运行时注入已{state}")
        elif sub == "status" and injector:
            s = injector.status
            return PlayerTurnResult(status=TurnStatus.COMPLETED, brief=str(s), narrative=str(s))
        return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="用法：/inject [toggle|status]", narrative="用法错误")

    if cmd == "/health":
        if keeper and hasattr(keeper, 'turn_monitor') and keeper.turn_monitor:
            snap = keeper.turn_monitor.snapshot()
            llm = snap["llm"]
            turn = snap["turn"]
            lines = ["Pipeline Health:"]
            lines.append(f"  Total calls: {llm['total_calls']} / Failures: {llm['total_failures']} / Slow: {llm['total_slow']}")
            for agent, stats in llm.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            if turn["steps"]:
                lines.append("Turn Steps:")
                for s in turn["steps"]:
                    icon = {"ok": "O", "failed": "X", "skipped": "-"}.get(s["status"], "?")
                    lines.append(f"  [{icon}] {s['step']} {s['duration_ms']:.0f}ms"
                               + (f" (retry x{s['retries']})" if s['retries'] else ""))
            frozen_str = "FROZEN" if turn["frozen"] else "OK"
            lines.append(f"Turn Status: {frozen_str}")
            return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="\n".join(lines), narrative="\n".join(lines))
        from monitor.health import PipelineHealth
        from llm import get_sensor
        sensor = get_sensor()
        if sensor:
            health = PipelineHealth(sensor)
            snap = health.snapshot()
            lines = ["Pipeline Health (legacy):"]
            lines.append(f"  Uptime: {snap['uptime_seconds']}s")
            lines.append(f"  Total calls: {snap['total_calls']} / Failures: {snap['total_failures']} / Slow: {snap['total_slow']}")
            for agent, stats in snap.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="\n".join(lines), narrative="\n".join(lines))
        return PlayerTurnResult(status=TurnStatus.COMPLETED, brief="Monitor not initialized.", narrative="监控未初始化")

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
    _enemy_ext_dir = Path("data/library/extensions/enemies")
    if _enemy_ext_dir.is_dir():
        for _f in sorted(_enemy_ext_dir.glob("*.json")):
            enemy_lib.load_extension(str(_f))

    # Load weapon library
    from library.weapons import WeaponLibrary
    weapon_lib = WeaponLibrary()
    weapon_lib.load_core()

    # 统一资源层:物品/法术库(core + extensions,统一 loader)
    from library.loader import load_item_library, load_spell_library
    item_lib = load_item_library()
    spell_lib = load_spell_library()

    # Load boss library
    from library.bosses import BossLibrary
    boss_library = BossLibrary(
        "data/library/core/bosses.json",
        extensions_dir="data/library/extensions/bosses",
    )
    boss_encounters = l2.get("boss_encounters", [])

    # Prepare NPC profiles (scene assignment now from Step 1a in pipeline)
    npc_profiles = l2.get("npc_profiles", {})

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib,
                          weapon_library=weapon_lib,
                          boss_library=boss_library,
                          boss_encounters=boss_encounters,
                          npc_profiles=npc_profiles,
                          item_library=item_lib,
                          spell_library=spell_lib)

    # Load dependency graph into world for runtime state tracking
    dep_graph = l2.get("dependency_graph", {})
    world.load_dependency_graph(dep_graph)

    # 显式执行 world 场景的 auto_triggers（world 不是玩家可达场景）
    world_node = graph.nodes.get("world")
    _pending_world_items: list[ItemGain] = []  # 延后：玩家尚未设置时暂存
    if world_node:
        from game.side_effects import parse_markup_all, SpawnEnemy, GrantWeapon, ItemGain, SceneWeapon as SW
        for at in world_node.auto_triggers:
            effects = parse_markup_all(getattr(at, 'result', '') or '')
            for se_text in (getattr(at, 'side_effects', []) or []):
                if isinstance(se_text, str) and "@" in se_text:
                    effects += parse_markup_all(se_text)
            for eff in effects:
                if isinstance(eff, SpawnEnemy):
                    if world.enemies:
                        target = eff.scene or start_node
                        inst = world.enemies.spawn(eff.enemy_ref, target, eff.quantity)
                        print(f"[World AT] spawned {eff.enemy_ref} x{eff.quantity} in {target} ({inst.instance_id})")
                elif isinstance(eff, GrantWeapon):
                    scene = eff.scene or start_node
                    if scene not in world.scene_weapons:
                        world.scene_weapons[scene] = []
                    world.scene_weapons[scene].append(SW(
                        weapon_ref=eff.weapon_ref, scene=scene, quantity=eff.quantity))
                    print(f"[World AT] granted {eff.weapon_ref} x{eff.quantity} in {scene}")
                elif isinstance(eff, ItemGain):
                    if world.player and hasattr(world.player, 'item_manager'):
                        world.player.item_manager.add(eff.item_name, quantity=eff.quantity)
                        qty_str = f" x{eff.quantity}" if eff.quantity > 1 else ""
                        print(f"[World AT] gained item {eff.item_name}{qty_str}")
                    else:
                        _pending_world_items.append(eff)
                        print(f"[World AT] item_gain {eff.item_name} deferred (player not yet set)")
    else:
        print("[World AT] No 'world' node found in graph")

    # Eagerly instantiate "at"-type boss encounters: boss exists in scene from the start
    if world.bosses and world.enemies:
        for enc in world.bosses.check_by_engage_type("at"):
            try:
                inst = world.bosses.spawn_instance(enc)
                world.enemies.register(inst)
                print(f"[Boss] pre-spawned {inst.enemy_ref} in {inst.scene} ({inst.instance_id})")
            except KeyError as e:
                print(f"[Boss] pre-spawn failed: {e}")

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
        "pending_world_items": _pending_world_items,
    }


def run_turn(game: dict, user_input: str,
             weapon_lib=None, enemy_lib=None, injector=None,
             action_type: str = "", action_target: str = "") -> PlayerTurnResult:
    """Execute one turn. Returns a PlayerTurnResult."""
    keeper = game["keeper"]
    from prompts import set_current_round
    set_current_round(keeper.turn_number)
    narrator = game["narrator"]
    author = game["author"]
    world = keeper.world

    _check_autosave(game)

    # Handle debug commands
    if user_input.strip().startswith("/"):
        cmd_result = _handle_spawn_command(user_input, world, weapon_lib, enemy_lib, injector, keeper=keeper)
        if cmd_result:
            return cmd_result

    # Pending standoff: route input to resolver instead of normal turn
    loc_before = getattr(world, "current_location", None)
    if getattr(keeper, "_standoff_pending", None):
        result = continue_standoff(keeper, user_input)
    else:
        turn_input = TurnInput(
            raw_text=user_input,
            player=world.player,
            action_type=action_type,
            action_target=action_target,
        )
        result = keeper.process_turn(turn_input, author=author)

    # U2 编年史：每回合入史（FROZEN 输入锁定不计）；须在 SUSPENDED 早退之前
    chronicle = getattr(world, "chronicle", None)
    if chronicle is not None and result.status != TurnStatus.FROZEN:
        chronicle.record_turn(keeper.turn_number, user_input, result, world)
        if loc_before is not None and world.current_location != loc_before and chronicle.events:
            chronicle.events[-1]["move"] = f"{loc_before}→{world.current_location}"

    # SUSPENDED: turn blocked on a question — return early, no narrator/snapshot
    if result.status == TurnStatus.SUSPENDED:
        if _turn_logger:
            _turn_logger.log(
                player_input=user_input,
                enrich_result=None,
                narrator_brief="",
                narrator_narrative=result.text,
            )
        return PlayerTurnResult(
            status=result.status,
            narrative=result.text,
            pending_interaction=result.pending_interaction,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            diagnostics={
                "time_agent": result.diagnostics.time_agent,
                "npc_events": result.npc_events,
                "npcs_visible": {"in_scene": [], "following": []},
            },
        )

    brief = result.brief
    if brief is not None and hasattr(brief, "action_outcomes"):
        display_brief = brief.enriched_summary or "\n".join(
            o.message for o in brief.action_outcomes)
    else:
        display_brief = result.text

    # Combat entry: caller handles combat (interactive CLI or auto frontend)
    combat_init = result.combat_init
    auto_win_combat = None

    # AUTO_WIN_COMBAT（测试辅助短接）：战斗直接判胜，不走回合制战斗系统。
    # 场景层 runner 通过 TRPG_AUTO_WIN=1 启用；战斗与后续逻辑差异大，单独测试。
    if combat_init and combat_init.enemies and os.environ.get("TRPG_AUTO_WIN") == "1":
        defeated_names = "、".join(getattr(e, "enemy_ref", "?") for e in combat_init.enemies)
        auto_narrative = f"战斗在转瞬间分出了胜负——{defeated_names}被击败。（自动胜利）"
        for e in combat_init.enemies:
            live = world.enemies.get_by_id(e.instance_id) if world.enemies else None
            if live:
                live.hp = 0
        if world.enemies:
            world.enemies.exit_combat({"outcome": "win"})
        boss_id = world.bosses.active_boss_id if world.bosses else None
        if not keeper._last_player_input:
            keeper._last_player_input = user_input
        completed = keeper.complete_combat_turn(
            keeper._last_player_input,
            {"outcome": "win", "narrative": auto_narrative,
             "is_boss": bool(boss_id)})
        if boss_id:
            world.get_runtime_state(boss_id).completed = True
            world.bosses.set_active(None)
        if completed is not None and completed.brief is not None:
            result.brief = completed.brief
            brief = result.brief
            display_brief = brief.enriched_summary or "\n".join(
                o.message for o in brief.action_outcomes)
        auto_win_combat = {"outcome": "win",
                           "narrative": auto_narrative,
                           "is_boss": bool(boss_id)}
        result.combat_init = None
        combat_init = None

    # Extract skill check results from outcomes for player display
    skill_results = []
    if brief is not None and hasattr(brief, 'action_outcomes'):
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

    if result.status == TurnStatus.FROZEN:
        narrative_brief = result.frozen_message
        narrative = result.frozen_message
        if _turn_logger:
            _turn_logger.log(
                player_input=user_input,
                enrich_result=result.diagnostics.enrich_raw,
                narrator_brief=narrative_brief,
                narrator_narrative=narrative,
            )
    elif brief is not None and hasattr(brief, 'scene_snapshot'):
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
                # Also update L1 description on narrator
                if narrator.l1_data and world.current_location in narrator.l1_data:
                    l1_scene = narrator.l1_data[world.current_location]
                    if isinstance(l1_scene, dict):
                        l1_scene["description"] = scene_update

            # TurnLogger: record player input + enrich + narrator output
            if _turn_logger:
                _turn_logger.log(
                    player_input=user_input,
                    enrich_result=result.diagnostics.enrich_raw,
                    narrator_brief=narrative_brief,
                    narrator_narrative=narrative,
                )
        except Exception:
            narrative_brief = display_brief or "（处理中）"
            narrative = "（叙事生成暂时不可用，但你的行动结果仍然有效。请继续输入下一步行动。）"
    else:
        # Keeper returned early with plain-text brief/narrative (boss trigger, weapon pickup, combat, etc.)
        narrative_brief = display_brief or "（处理中）"
        narrative = result.text or ""
        if result.npc_events:
            world.memory.add_record(
                user_input, "npc_dialogue", "",
                narrative or narrative_brief,
                location=world.current_location,
                success=True,
            )
        if _turn_logger:
            _turn_logger.log(
                player_input=user_input,
                enrich_result=result.diagnostics.enrich_raw,
                narrator_brief=narrative_brief,
                narrator_narrative=narrative,
            )

    # Surface pending weapon offer to player (narrator may omit the pickup prompt)
    if result.pending_interaction and result.pending_interaction.kind == "weapon_offer":
        wp_text = result.pending_interaction.question
        if wp_text not in (narrative or ""):
            narrative = (narrative or "") + ("\n\n" if narrative else "") + wp_text
            if not narrative_brief:
                narrative_brief = wp_text

    # NPC visible output
    npcs_visible = {"in_scene": [], "following": []}
    if world.npcs:
        in_scene = world.npcs.get_in_scene(world.current_location)
        npcs_visible["in_scene"] = [n.name for n in in_scene if n.state not in ("dead", "left")]
        npcs_visible["following"] = [n.name for n in world.npcs.get_following()]

    # ── Build PlayerFacingSnapshot ──
    import re as _re
    scene_name = world.current_location
    scene_description = ""
    if brief is not None and hasattr(brief, 'scene_snapshot') and brief.scene_snapshot:
        scene_description = brief.scene_snapshot.description
    # Prefer L1 immersive description over raw L2 node description
    narrator = game["narrator"]
    l1_scene = narrator.l1_data.get(world.current_location) if narrator.l1_data else None
    if l1_scene and isinstance(l1_scene, dict):
        l1_desc = l1_scene.get("description", "")
        if l1_desc and (not scene_description or scene_description == world.current_location
                or len(l1_desc) > len(scene_description)):
            scene_description = l1_desc
    if not scene_description:
        scene_description = world.get_current_description()

    # Build NPC list: deterministic base from NPC manager, enriched by Curator/L1
    scene_npcs = []
    live = {}
    if getattr(world, "npcs", None):
        try:
            live = {n.name: n for n in world.npcs.get_in_scene(scene_name)}
            live.update({n.name: n for n in world.npcs.get_following()})
        except Exception:
            live = {}
    for name, n in live.items():
        if getattr(n, "state", "") in ("dead", "left"):
            continue
        scene_npcs.append({
            "name": name,
            "brief": "",
            "demeanor": "",
            "attitude": getattr(n, "attitude", "") or "",
            "state": getattr(n, "state", "") or "",
            "following": bool(getattr(n, "following", False)),
            "can_follow": bool(getattr(n, "can_follow", False)),
        })
    # Enrich with Curator visible_npcs (brief/demeanor)
    if brief is not None and hasattr(brief, 'scene_snapshot') and brief.scene_snapshot:
        cur_map = {n.get("name", ""): n for n in brief.scene_snapshot.visible_npcs}
        for npc in scene_npcs:
            cur = cur_map.get(npc["name"])
            if cur:
                if cur.get("brief"):
                    npc["brief"] = cur["brief"]
                if cur.get("demeanor"):
                    npc["demeanor"] = cur["demeanor"]
    # Enrich with L1 NPC appearance (better brief/demeanor)
    if l1_scene and isinstance(l1_scene, dict):
        l1_npcs = l1_scene.get("npc_appearances") or l1_scene.get("npcs", [])
        if l1_npcs:
            l1_map = {n.get("name", ""): n for n in l1_npcs if isinstance(n, dict)}
            for npc in scene_npcs:
                l1_match = l1_map.get(npc["name"])
                if l1_match:
                    if l1_match.get("brief"):
                        npc["brief"] = l1_match["brief"]
                    if l1_match.get("demeanor"):
                        npc["demeanor"] = l1_match["demeanor"]
    exits_data = [
        {"target": e.target, "method": e.method}
        for e in world.get_possible_exits()
    ]
    time_data = world.clock.to_dict()

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
        enemies=world.enemies.get_active_in_scene_snapshot(scene_name) if world.enemies else [],
        combat=None,
        skill_checks=skill_checks_out,
        investigator=world.player,
    )

    return PlayerTurnResult(
        status=result.status,
        brief=narrative_brief,
        narrative=narrative,
        pending_interaction=result.pending_interaction,
        player_snapshot=player_snapshot,
        skill_results=skill_results,
        combat=auto_win_combat,
        combat_init=combat_init,
        ending=result.ending,
        game_over=bool(result.ending and result.ending.game_over),
        timestamp=datetime.now().strftime("%H:%M:%S"),
        diagnostics={
            "time_agent": result.diagnostics.time_agent,
            "npc_events": result.npc_events,
            "npcs_visible": npcs_visible,
        },
    )


# ── Save / Load ──

def save_game(game: dict, path: str) -> None:
    world = game["keeper"].world
    keeper = game["keeper"]
    author = game.get("author")

    world.save_state(path)
    import json as _json
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    data["_meta"] = {
        "turn_number": keeper.turn_number,
    }
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


def load_game(game: dict, path: str) -> None:
    world = game["keeper"].world
    import json as _json

    restored = world.__class__.load_state(path)
    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    meta = data.get("_meta", {})

    for attr in list(world.__dict__.keys()):
        if hasattr(restored, attr):
            setattr(world, attr, getattr(restored, attr))

    game["keeper"].turn_number = meta.get("turn_number", 0)


# ── Autosave ──

import threading
from config import AUTOSAVE_ENABLED, AUTOSAVE_INTERVAL_SEC, AUTOSAVE_MAX_COPIES, AUTOSAVE_DIR

_autosave_flag: bool = False
_autosave_timer: threading.Timer | None = None
_autosave_counter: int = 0


def _autosave_callback():
    global _autosave_flag, _autosave_timer
    _autosave_flag = True
    if AUTOSAVE_ENABLED:
        _autosave_timer = threading.Timer(AUTOSAVE_INTERVAL_SEC, _autosave_callback)
        _autosave_timer.daemon = True
        _autosave_timer.start()


def start_autosave(game: dict) -> None:
    global _autosave_timer
    if not AUTOSAVE_ENABLED:
        return
    if _autosave_timer:
        _autosave_timer.cancel()
    _autosave_timer = threading.Timer(AUTOSAVE_INTERVAL_SEC, _autosave_callback)
    _autosave_timer.daemon = True
    _autosave_timer.start()


def _check_autosave(game: dict) -> None:
    global _autosave_flag, _autosave_counter
    if not _autosave_flag:
        return
    _autosave_flag = False
    import os as _os
    save_dir = _os.path.join(AUTOSAVE_DIR)
    _os.makedirs(save_dir, exist_ok=True)

    _autosave_counter = (_autosave_counter % AUTOSAVE_MAX_COPIES) + 1
    path = _os.path.join(save_dir, f"autosave_{_autosave_counter}.json")
    try:
        save_game(game, path)
    except Exception:
        pass


def continue_standoff(keeper, player_input: str) -> TurnResult:
    """Process a standoff avoidance attempt. Combat runs inline; combat_init is None in the result."""
    s = keeper._standoff_pending
    if not s:
        return TurnResult(status=TurnStatus.COMPLETED, text="无待处理的对峙。")

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

    # Run combat if resolved into combat
    # TRPG_AUTO_WIN=1：跳过真实战斗直接判胜（测试辅助短接，战斗本体见 B2 专项）
    completed = None
    combat_ran = False
    combat_narrative = ""
    if combat_init and combat_init.enemies and os.environ.get("TRPG_AUTO_WIN") == "1":
        defeated_names = "、".join(getattr(e, "enemy_ref", "?") for e in combat_init.enemies)
        auto_narrative = f"战斗在转瞬间分出了胜负——{defeated_names}被击败。（自动胜利）"
        for e in combat_init.enemies:
            live = keeper.world.enemy_manager.get_by_id(e.instance_id) if keeper.world.enemy_manager else None
            if live:
                live.hp = 0
        keeper.world.enemy_manager.exit_combat({"outcome": "win"})
        if not keeper._last_player_input:
            keeper._last_player_input = player_input
        completed = keeper.complete_combat_turn(
            keeper._last_player_input,
            {"outcome": "win", "narrative": auto_narrative,
             "is_boss": bool(keeper.world.bosses and keeper.world.bosses.active_boss_id)})
        boss_id = keeper.world.bosses.active_boss_id if keeper.world.bosses else None
        if boss_id:
            keeper.world.get_runtime_state(boss_id).completed = True
            keeper.world.bosses.set_active(None)
        combat_ran = True
        combat_narrative = auto_narrative
    elif combat_init and combat_init.enemies:
        from game.combat import CombatSystem
        cs = CombatSystem(spell_lib=getattr(keeper.world, "spell_library", None),
                          world=keeper.world)
        cr = cs.run_combat(combat_init)
        combat_ran = True
        combat_narrative = cr.narrative or ""
        # HP/SAN 回写
        if combat_init.player:
            combat_init.player.derived.HP = max(0, cr.player_hp)
            combat_init.player.derived.SAN = max(0, cr.player_san)
        keeper.world.enemy_manager.exit_combat({"outcome": cr.outcome})
        # Combat completion: re-enrich with combat result (same turn)
        combat_result = {"outcome": cr.outcome, "narrative": combat_narrative, "is_boss": bool(keeper.world.bosses and keeper.world.bosses.active_boss_id)}
        if not keeper._last_player_input:
            # standoff path never sets it; use the standoff answer as replay context
            keeper._last_player_input = player_input
        completed = keeper.complete_combat_turn(keeper._last_player_input, combat_result)
        # Mark boss as completed on win
        if cr.outcome == "win":
            boss_id = keeper.world.bosses.active_boss_id
            if boss_id:
                keeper.world.get_runtime_state(boss_id).completed = True
                keeper.world.bosses.set_active(None)

    brief = completed.brief if completed else None
    text = result.get("message", "")
    if combat_ran and brief is None and combat_narrative:
        text = f"{text}\n{combat_narrative}" if text else combat_narrative
    next_pending = None
    if result.get("next_standoff"):
        next_pending = PendingInteraction(
            kind="standoff", question=result["next_standoff"],
            interaction_id="standoff")
    return TurnResult(
        status=TurnStatus.COMPLETED,
        brief=brief,
        text=text,
        pending_interaction=next_pending,
        combat_init=None if combat_ran else combat_init,
        npc_events=list(keeper._npc_events),
    )


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
        game_time = int(t.get("game_time", 0))
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
        h, m = divmod(int(game_time), 60)
        time_str += f"{h:02d}:{int(m):02d}"
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
