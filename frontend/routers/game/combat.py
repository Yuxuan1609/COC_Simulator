"""frontend/routers/game/combat.py — 战斗序列化与 /api/combat/*。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

from . import session


def _serialize_enemies_for_frontend(enemies: list) -> list[dict]:
    """Serialize enemy list for frontend display."""
    return [
        {
            "instance_id": getattr(e, 'instance_id', ''),
            "enemy_ref": getattr(e, 'enemy_ref', ''),
            "hp": getattr(e, 'hp', 0),
            "hp_max": getattr(e, 'hp_max', getattr(e, 'hp', 0)),
            "quantity": getattr(e, 'quantity', 1),
            "status": getattr(e, 'status', ''),
            "attributes": getattr(e, 'attributes', {}),
            "boss_mechanics": getattr(e, 'boss_mechanics', ''),
            "special_rules": getattr(e, 'special_rules', ''),
            "armor": getattr(e, 'armor', ''),
            "multi_attack": getattr(e, 'multi_attack', 1),
            "phases": getattr(e, 'phases', []),
            "san_loss": getattr(e, 'san_loss', ''),
            "flags": list(getattr(e, 'flags', []) or []),
        }
        for e in enemies
    ]


def _serialize_combat_state_for_frontend(state) -> dict:
    """Serialize CombatState fields needed by frontend."""
    return {
        "round": state.round,
        "player_hp": state.player_hp,
        "player_hp_max": state.player_hp_max,
        "player_san": state.player_san,
        "player_san_max": getattr(state, "player_san_max", 99),
        "enemies": _serialize_enemies_for_frontend(state.enemies),
        "initiative_order": state.initiative_order,
        "finished": state.finished,
    }


def _iter_scene_enemies(world):
    """当前场景敌人（含 _instances；无场景字段则全收）。"""
    mgr = getattr(world, "enemies", None) if world is not None else None
    if mgr is None:
        return []
    loc = getattr(world, "current_location", None)
    instances = getattr(mgr, "_instances", None)
    if isinstance(instances, dict):
        out = []
        for e in instances.values():
            scene = getattr(e, "scene", None)
            if loc is not None and scene not in (None, loc):
                continue
            out.append(e)
        return out
    getter = getattr(mgr, "get_active_in_scene", None)
    if callable(getter) and loc:
        return list(getter(loc) or [])
    return []


def _take_pre_combat_snapshot(world) -> dict:
    """战斗重置前的临时回滚，不求完备（目睹 SAN / 镜像字段允许不准）。"""
    p = getattr(world, "player", None) if world is not None else None
    derived = getattr(p, "derived", None) if p is not None else None
    enemies = {}
    for e in _iter_scene_enemies(world):
        key = getattr(e, "instance_id", "") or ""
        if not key:
            continue
        enemies[key] = {
            "hp": getattr(e, "hp", 0),
            "status": getattr(e, "status", ""),
        }
    seen = getattr(world, "san_seen_sources", None) if world is not None else None
    return {
        "hp": getattr(derived, "HP", 0) if derived is not None else 0,
        "san": getattr(derived, "SAN", 0) if derived is not None else 0,
        "mp": getattr(derived, "MP", 0) if derived is not None else 0,
        "enemies": enemies,
        "san_seen_sources": set(seen) if seen is not None else set(),
    }


def _apply_pre_combat_snapshot(world, snap) -> None:
    """把战前快照写回 player HP/SAN/MP、场景敌人 hp/status、san_seen_sources。"""
    if not snap or world is None:
        return
    p = getattr(world, "player", None)
    derived = getattr(p, "derived", None) if p is not None else None
    if derived is not None:
        if "hp" in snap:
            derived.HP = snap["hp"]
        if "san" in snap:
            derived.SAN = snap["san"]
        if "mp" in snap:
            derived.MP = snap["mp"]
    mgr = getattr(world, "enemies", None)
    for iid, es in (snap.get("enemies") or {}).items():
        live = None
        if mgr is not None and hasattr(mgr, "get_by_id"):
            live = mgr.get_by_id(iid)
        if live is None:
            instances = getattr(mgr, "_instances", None) if mgr is not None else None
            if isinstance(instances, dict):
                live = instances.get(iid)
        if live is None:
            continue
        if "hp" in es:
            live.hp = es["hp"]
        if "status" in es:
            live.status = es["status"]
    if hasattr(world, "san_seen_sources"):
        world.san_seen_sources = set(snap.get("san_seen_sources") or [])


def _peek_world():
    game = session._game_instance
    if not game:
        return None
    try:
        return game["keeper"].world
    except Exception:
        return None


def _discard_combat_sessions() -> None:
    """回滚残留战斗会话的战前快照并清空。无快照则只清 dict。

    enter_combat 发生在 combat/start 之前，快照不含 _combat_active；
    回滚后必须 abort 清闩，否则 phase_c_encounter 跳过、无法再进战斗。
    abort 不当 win（不把敌人标 defeated）。
    """
    sessions = session._combat_sessions
    world = _peek_world()
    for sess in list(sessions.values()):
        snap = sess.get("pre_world") if isinstance(sess, dict) else None
        if snap and world is not None:
            _apply_pre_combat_snapshot(world, snap)
    sessions.clear()
    mgr = getattr(world, "enemies", None) if world is not None else None
    if mgr is not None and hasattr(mgr, "exit_combat"):
        mgr.exit_combat({"outcome": "abort"})


def _deserialize_enemies_for_combat(enemy_data_list: list) -> list:
    """Deserialize enemy dicts to objects usable by CombatSystem."""
    from dataclasses import dataclass, field

    @dataclass
    class _Enemy:
        instance_id: str = ""
        enemy_ref: str = ""
        hp: int = 0
        hp_max: int = 0
        status: str = ""
        quantity: int = 1
        attributes: dict = field(default_factory=dict)
        boss_mechanics: str = ""
        special_rules: str = ""
        phases: list = field(default_factory=list)
        damage_multipliers: dict = field(default_factory=dict)
        armor: str = ""
        multi_attack: int = 1
        attacks: list = field(default_factory=list)
        dex: int = 50
        dodge_bonus: int = 0
        flags: list = field(default_factory=list)

    enemies = []
    for data in enemy_data_list:
        e = _Enemy()
        for k, v in data.items():
            if hasattr(e, k):
                setattr(e, k, v)
        enemies.append(e)
    return enemies


@router.post("/api/combat/start")
async def combat_start(request: Request):
    """Initialize a combat session from a CombatInit object.

    Request body JSON:
        {"combat_init": {... serialized CombatInit ...}}
    """
    import json, uuid
    from game.combat import CombatSystem
    from game.messages import CombatInit

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    combat_init_data = data.get("combat_init", {})

    game = session.get_game()
    if game is None:
        return JSONResponse({"error": "游戏未初始化"}, status_code=400)

    world = game["keeper"].world
    player = world.player
    if not player:
        return JSONResponse({"error": "未设置调查员"}, status_code=400)

    # Reconstruct CombatInit with live player
    enemies = _deserialize_enemies_for_combat(combat_init_data.get("enemies", []))
    combat_init = CombatInit(
        enemies=enemies,
        player=player,
        scene=combat_init_data.get("scene", ""),
        initiative_context=combat_init_data.get("initiative_context", ""),
        environment_actions=combat_init_data.get("environment_actions", []),
        player_action=combat_init_data.get("player_action", ""),
        player_targets=combat_init_data.get("player_targets", []),
        player_extra=combat_init_data.get("player_extra", ""),
    )

    if session._combat_sessions:
        _discard_combat_sessions()

    # Auto-win short-circuit: skip the combat system entirely (testing aid)
    if session._auto_win:
        world = game["keeper"].world
        keep = game["keeper"]
        narr = game["narrator"]
        is_boss = any(getattr(e, "boss_mechanics", "") for e in enemies)
        if world.enemies:
            for e in enemies:
                live = world.enemies.get_by_id(e.instance_id)
                if live:
                    live.hp = 0
        boss_id = world.bosses.active_boss_id if world.bosses else None
        if boss_id:
            world.get_runtime_state(boss_id).completed = True
            world.bosses.set_active(None)
        if world.enemies:
            world.enemies.exit_combat({"outcome": "win"})
        completed_brief = ""
        completed_narrative = ""
        combat_result = {
            "outcome": "win",
            "narrative": "战斗在转瞬间分出了胜负。（自动胜利）",
            "is_boss": is_boss,
        }
        completed = keep.complete_combat_turn(keep._last_player_input, combat_result) if keep._last_player_input else None
        if completed and completed.brief:
            try:
                snap = world.build_snapshot()
                completed_brief, completed_narrative, _ = narr.narrate(
                    completed.brief, snap=snap, user_input=keep._last_player_input)
                from game_loop import _turn_logger as tl
                if tl:
                    tl.log(
                        player_input=keep._last_player_input,
                        enrich_result=completed.diagnostics.enrich_raw,
                        narrator_brief=completed_brief,
                        narrator_narrative=completed_narrative,
                    )
            except Exception:
                pass
        keep._last_player_input = ""
        return {
            "auto_win": True,
            "finished": True,
            "outcome": "win",
            "is_boss": is_boss,
            "combat_completed": bool(completed_brief),
            "combat_completed_brief": completed_brief,
            "combat_completed_narrative": completed_narrative,
        }

    pre_world = _take_pre_combat_snapshot(world)
    cs = CombatSystem(spell_lib=getattr(world, "spell_library", None), world=world)
    state = cs._init_combat(combat_init)

    session_id = str(uuid.uuid4())[:8]
    session._combat_sessions[session_id] = {
        "state": state,
        "combat_init": combat_init,
        "pre_world": pre_world,
    }

    available = cs._get_player_actions(player, getattr(combat_init, 'environment_actions', []))
    actions = [{"id": a["id"], "label": a["label"],
                "multi_attack": a.get("multi_attack", 1),
                "damage_type": a.get("damage_type", "物理")}
               for a in available]

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "actions": actions,
    }


@router.post("/api/combat/round")
async def combat_round(request: Request):
    """Execute one combat round.

    Request body JSON:
        {"session_id": "...", "action_id": "...", "target_ids": [...], "player_extra": "..."}
    """
    import json
    from game.combat import CombatSystem

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session_id = data.get("session_id", "")

    combat_sess = session._combat_sessions.get(session_id)
    if not combat_sess:
        _discard_combat_sessions()
        return JSONResponse({"error": "combat_session_lost"}, status_code=409)

    state = combat_sess["state"]
    combat_init = combat_sess["combat_init"]
    action_id = data.get("action_id", "punch")
    target_ids = data.get("target_ids", [])
    player_extra = data.get("player_extra", "")

    _game = session.get_game()
    _world = _game["keeper"].world if _game else None
    cs = CombatSystem(spell_lib=getattr(_world, "spell_library", None), world=_world)
    result = cs.run_single_round(combat_init, state, action_id, target_ids, player_extra)

    # Update session with mutated state
    combat_sess["state"] = state

    # Serialize round_log for JSON response
    round_log = []
    for a in result.get("round_log", []):
        round_log.append({
            "actor": getattr(a, 'actor', ''),
            "action_type": getattr(a, 'action_type', ''),
            "weapon": getattr(a, 'weapon', ''),
            "skill_name": getattr(a, 'skill_name', ''),
            "skill_value": getattr(a, 'skill_value', 0),
            "roll": getattr(a, 'roll', 0),
            "tier": getattr(a, 'tier', ''),
            "target": getattr(a, 'target', ''),
            "damage": getattr(a, 'damage', 0),
            "damage_type": getattr(a, 'damage_type', '物理'),
            "hp_before": getattr(a, 'hp_before', 0),
            "hp_after": getattr(a, 'hp_after', 0),
            "narrative": getattr(a, 'narrative', ''),
            "success": getattr(a, 'success', False),
            "round_num": getattr(a, 'round_num', 0),
        })

    # Generate combat narrative on finish
    combat_narrative = ""
    if result.get("finished"):
        try:
            from prompts import _log_dir as prompt_log_dir
            combat_narrative = cs._generate_combat_narrative(
                state, combat_init.player, combat_init.scene,
                log_dir=prompt_log_dir or "")
        except Exception:
            pass
        # Write HP/SAN back to player
        if combat_init.player:
            combat_init.player.derived.HP = max(0, state.player_hp)
            combat_init.player.derived.SAN = max(0, state.player_san)

        completed_brief = ""
        completed_narrative = ""
        g = session.get_game()
        if g:
            world = g["keeper"].world
            keep = g["keeper"]
            narr = g["narrator"]
            if result.get("outcome") == "win":
                boss_id = world.bosses.active_boss_id if world.bosses else None
                if boss_id:
                    world.get_runtime_state(boss_id).completed = True
                    world.bosses.set_active(None)
            world.enemies.exit_combat({"outcome": result.get("outcome", "")})

            # Combat completion: re-enrich + curate with combat result (same turn)
            combat_result = {
                "outcome": result.get("outcome", ""),
                "narrative": combat_narrative or "",
                "is_boss": result.get("is_boss", False),
            }
            completed = keep.complete_combat_turn(keep._last_player_input, combat_result) if keep._last_player_input else None
            if completed and completed.brief:
                try:
                    snap = world.build_snapshot()
                    completed_brief, completed_narrative, _ = narr.narrate(
                        completed.brief, snap=snap, user_input=keep._last_player_input)
                    from game.turn_logger import TurnLogger
                    from game_loop import _turn_logger as tl
                    if tl:
                        tl.log(
                            player_input=keep._last_player_input,
                            enrich_result=completed.diagnostics.enrich_raw,
                            narrator_brief=completed_brief,
                            narrator_narrative=completed_narrative,
                        )
                except Exception:
                    pass
            keep._last_player_input = ""

        session._combat_sessions.pop(session_id, None)
        return {
            "session_id": session_id,
            "state": _serialize_combat_state_for_frontend(state),
            "finished": True,
            "outcome": result.get("outcome"),
            "round_log": round_log,
            "round_narrative": result.get("round_narrative", ""),
            "combat_narrative": combat_narrative,
            "is_boss": result.get("is_boss", False),
            "game_over": result.get("game_over", False),
            "round": state.round,
            "combat_completed": bool(completed_brief),
            "combat_completed_brief": completed_brief,
            "combat_completed_narrative": completed_narrative,
        }

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "finished": result.get("finished", False),
        "outcome": result.get("outcome"),
        "round_log": round_log,
        "round_narrative": result.get("round_narrative", ""),
        "combat_narrative": combat_narrative,
        "is_boss": result.get("is_boss", False),
        "game_over": result.get("game_over", False),
        "round": result.get("round", 1),
    }

