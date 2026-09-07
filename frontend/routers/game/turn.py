"""frontend/routers/game/turn.py — process_turn + WS 进度。"""
from __future__ import annotations

import asyncio
from fastapi import APIRouter, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

router = APIRouter()

from . import session
from . import slash
from . import combat


@router.post("/api/game/turn")
async def process_turn(
    user_input: str = Form(""),
    action_type: str = Form(""),
    action_target: str = Form(""),
):
    import asyncio
    import traceback
    from game_loop import run_turn

    # Check autosave flag before processing
    try:
        import game_loop as _gl
        g = session.get_game()
        if g:
            _gl._check_autosave(g)
    except Exception:
        pass

    # Route slash commands directly — skip LLM pipeline
    stripped = user_input.strip()
    if stripped.startswith("/"):
        cmd_html = slash._handle_slash_command(stripped)
        return {
            "brief": stripped,
            "narrative": "",
            "narrative_html": cmd_html,
            "combat": None,
            "skill_results": [],
            "game_over": False,
            "ending": None,
            "timestamp": "",
            "player_snapshot": None,
        }

    try:
        game = session.get_game()
        if game is None:
            return {
                "brief": "",
                "narrative": "",
                "narrative_html": '<div class="text-gray-500 text-sm">游戏已退出。请返回启动页重新开始。</div>',
                "combat": None,
                "skill_results": [],
                "game_over": True,
                "ending": None,
                "timestamp": "",
                "player_snapshot": None,
                "turn_dynamic_text": "",
            }
    except Exception as e:
        traceback.print_exc()
        return HTMLResponse(
            f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 '
            f'border-red-500 bg-[#1a0a0a]">游戏引擎错误: {e}</div>'
        )

    _push_progress("parse", "running")

    # Run blocking LLM call in thread pool to avoid blocking event loop
    loop = asyncio.get_running_loop()
    try:
        turn = await loop.run_in_executor(
            None, run_turn, game, user_input, session._weapon_lib, session._enemy_lib, session._injector,
            action_type, action_target,
        )
    except Exception as e:
        traceback.print_exc()
        _push_progress("complete", "")
        return HTMLResponse(
            f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 border-red-500 bg-[#1a0a0a]">'
            f'错误: {e}</div>'
        )

    _push_progress("parse", "done")
    _push_progress("judge", "done")
    _push_progress("enrich", "done")
    _push_progress("combat_entry", "done")
    _push_progress("curate", "done")
    _push_progress("narrate", "done")
    _push_progress("complete", "")

    from dataclasses import asdict
    from game.messages import TurnStatus

    if turn and turn.status == TurnStatus.FROZEN:
        frozen_message = turn.narrative or "系统异常"
        return {
            "status": "frozen",
            "brief": "",
            "narrative": "",
            "narrative_html": (
                '<div class="msg-frozen px-4 py-3 text-red-400 border-2 border-red-600 '
                'bg-[#1a0a0a] rounded">' + (frozen_message.replace("\n", "<br>")) + '</div>'
            ),
            "pending_interaction": None,
            "combat": None,
            "skill_results": [],
            "game_frozen": True,
            "frozen_message": frozen_message,
            "game_over": False,
            "ending": None,
            "timestamp": "",
            "player_snapshot": None,
        }

    narrative = turn.narrative if turn else ""
    brief = turn.brief if turn else ""

    # Combat: if combat_init present, return it to frontend for interactive handling
    combat_init = turn.combat_init if turn else None
    combat = turn.combat if turn else None
    combat_init_data = None
    if combat_init and combat_init.enemies and not combat:
        combat_init_data = {
            "enemies": combat._serialize_enemies_for_frontend(combat_init.enemies),
            "scene": combat_init.scene,
            "initiative_context": combat_init.initiative_context,
            "environment_actions": getattr(combat_init, 'environment_actions', []),
            "player_action": combat_init.player_action,
            "player_targets": getattr(combat_init, 'player_targets', []),
            "player_extra": getattr(combat_init, 'player_extra', ''),
        }

    skill_results = turn.skill_results if turn else []
    game_over = turn.game_over if turn else False
    ending = asdict(turn.ending) if turn and turn.ending else None
    timestamp = turn.timestamp if turn else ""
    player_snapshot = turn.player_snapshot if turn else None
    pending_data = asdict(turn.pending_interaction) if turn and turn.pending_interaction else None
    status = turn.status.value if turn else "completed"

    # Serialize PlayerFacingSnapshot to dict
    if player_snapshot and hasattr(player_snapshot, '__dataclass_fields__'):
        from dataclasses import asdict
        player_snapshot = asdict(player_snapshot)

    # Join enemy library fields into snapshot enemies (for debug detail view)
    if player_snapshot and player_snapshot.get("enemies") and session._enemy_lib is not None:
        for e in player_snapshot["enemies"]:
            lib_e = session._enemy_lib.get(e.get("enemy_ref", ""))
            if lib_e:
                e["detail"] = {
                    "type": getattr(lib_e, "type", ""),
                    "armor": getattr(lib_e, "armor", ""),
                    "attacks": [
                        {
                            "name": getattr(a, "name", ""),
                            "damage": getattr(a, "damage", {}),
                            "skill_name": getattr(a, "skill_name", ""),
                            "skill_value": getattr(a, "skill_value", 0),
                        }
                        for a in getattr(lib_e, "attacks", [])
                    ],
                    "special_abilities": [
                        {"name": getattr(s, "name", ""), "desc": getattr(s, "desc", "")}
                        for s in getattr(lib_e, "special_abilities", [])
                    ],
                    "san_loss": getattr(lib_e, "san_loss", ""),
                    "multi_attack": getattr(lib_e, "multi_attack", 1),
                    "phases": getattr(lib_e, "phases", []),
                    "description": getattr(lib_e, "description", ""),
                }

    # Potential threats for debug view: unengaged boss encounters + AT-lurking enemy spawns
    if player_snapshot is not None:
        try:
            game = session.get_game()
            world = game["keeper"].world if game else None
            loc = world.current_location if world else ""
            threats = []
            bosses = getattr(world, "bosses", None)
            if bosses:
                for enc in bosses._encounters:
                    bid = enc.get("id", enc.get("boss_ref", ""))
                    if enc.get("scene") != loc:
                        continue
                    if bosses.has_spawned(bid) or world.is_entity_completed(bid):
                        continue
                    if bid in getattr(bosses, "_instance_ids", {}):
                        continue  # 已预生成实例，直接显示在敌对生物区块
                    threats.append({
                        "kind": "boss",
                        "ref": enc.get("boss_ref", ""),
                        "note": f"Boss 遭遇（{enc.get('engage_type', '?')}）",
                    })
            node = world.graph.nodes.get(loc) if world else None
            if node:
                import re as _re
                present = {e.get("enemy_ref") for e in (player_snapshot.get("enemies") or [])}
                for at in getattr(node, "auto_triggers", []):
                    if world.is_entity_completed(getattr(at, "id", "")):
                        continue
                    for se in getattr(at, "side_effects", []) or []:
                        if not isinstance(se, str):
                            continue
                        m = _re.search(r'@spawn_enemy\([^)]*enemy_ref\s*=\s*"([^"]+)"', se)
                        if m and m.group(1) not in present:
                            threats.append({
                                "kind": "enemy",
                                "ref": m.group(1),
                                "note": f"埋伏于 {getattr(at, 'name', getattr(at, 'id', '?'))}",
                            })
                            present.add(m.group(1))
            player_snapshot["potential_threats"] = threats
        except Exception:
            pass

    # Format dynamic turn text from snapshot
    turn_dynamic_text = ""
    try:
        from game_loop import format_turn_dynamic
        turn_dynamic_text = format_turn_dynamic(player_snapshot, brief, narrative)
    except Exception:
        import traceback
        traceback.print_exc()

    narrative_html = ""
    if brief:
        narrative_html += (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 '
            f'border-gray-600 mb-2">{brief}</div>'
        )
    if narrative:
        narrative_html += (
            f'<div class="msg-narrative px-3 py-2 text-parchment border-l-2 '
            f'border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'
        )
    if not narrative_html:
        narrative_html = (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-500">'
            f'（没有返回叙事内容）</div>'
        )

    return {
        "status": status,
        "brief": brief,
        "narrative": narrative,
        "narrative_html": narrative_html,
        "pending_interaction": pending_data,
        "combat": combat,
        "combat_init": combat_init_data,
        "skill_results": skill_results,
        "game_over": game_over,
        "ending": ending,
        "timestamp": timestamp,
        "player_snapshot": player_snapshot,
        "turn_dynamic_text": turn_dynamic_text,
    }


@router.websocket("/api/game/progress")
async def game_progress(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    qid = str(id(ws))
    session._progress_queues[qid] = q
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30)
                await ws.send_json(msg)
                if msg.get("step") == "complete":
                    break
            except asyncio.TimeoutError:
                await ws.send_json({"step": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        session._progress_queues.pop(qid, None)


def _push_progress(step: str, status: str):
    """Send progress update to all connected WS clients."""
    import asyncio as _asyncio
    msg = {"step": step, "status": status}
    for q in list(session._progress_queues.values()):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass

