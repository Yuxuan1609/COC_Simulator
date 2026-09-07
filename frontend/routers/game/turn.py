"""frontend/routers/game/turn.py — process_turn + WS 进度。"""
from __future__ import annotations

import asyncio
import html
import traceback
from dataclasses import asdict
from functools import partial

from fastapi import APIRouter, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

router = APIRouter()

from . import session
from . import slash
from . import combat


def _slash_payload(cmd) -> dict:
    text = cmd.get("text", "") if isinstance(cmd, dict) else str(cmd)
    return {
        "brief": "",
        "narrative": text,
        "slash": {"text": text},
        "combat": None,
        "skill_results": [],
        "game_over": False,
        "ending": None,
        "timestamp": "",
        "player_snapshot": None,
    }


def _exited_payload() -> dict:
    return {
        "brief": "",
        "narrative": "游戏已退出。请返回启动页重新开始。",
        "combat": None,
        "skill_results": [],
        "game_over": True,
        "ending": None,
        "timestamp": "",
        "player_snapshot": None,
        "turn_dynamic_text": "",
    }


def _engine_error_html(exc) -> HTMLResponse:
    safe = html.escape(str(exc), quote=True)
    return HTMLResponse(
        f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 '
        f'border-red-500 bg-[#1a0a0a]">游戏引擎错误: {safe}</div>'
    )


def _turn_error_html(exc) -> HTMLResponse:
    safe = html.escape(str(exc), quote=True)
    return HTMLResponse(
        f'<div class="msg-narrative px-3 py-2 text-red-400 border-l-2 border-red-500 bg-[#1a0a0a]">'
        f'错误: {safe}</div>'
    )


def _frozen_payload(turn) -> dict:
    frozen_message = turn.narrative or "系统异常"
    frozen = {
        "status": "frozen",
        "brief": "",
        "narrative": frozen_message,
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
    if turn.debug is not None:
        frozen["debug"] = turn.debug
    return frozen


def _serialize_combat_init(turn):
    combat_init = turn.combat_init if turn else None
    combat_result = turn.combat if turn else None
    if combat_init and combat_init.enemies and not combat_result:
        return {
            "enemies": combat._serialize_enemies_for_frontend(combat_init.enemies),
            "scene": combat_init.scene,
            "initiative_context": combat_init.initiative_context,
            "environment_actions": getattr(combat_init, 'environment_actions', []),
            "player_action": combat_init.player_action,
            "player_targets": getattr(combat_init, 'player_targets', []),
            "player_extra": getattr(combat_init, 'player_extra', ''),
        }
    return None


def _join_enemy_library(player_snapshot):
    if not (player_snapshot and player_snapshot.get("enemies") and session._enemy_lib is not None):
        return
    for e in player_snapshot["enemies"]:
        lib_e = session._enemy_lib.get(e.get("enemy_ref", ""))
        if not lib_e:
            continue
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


def _attach_potential_threats(player_snapshot):
    if player_snapshot is None:
        return
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


def _narrative_html(brief, narrative) -> str:
    html = ""
    if brief:
        html += (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 '
            f'border-gray-600 mb-2">{brief}</div>'
        )
    if narrative:
        html += (
            f'<div class="msg-narrative px-3 py-2 text-parchment border-l-2 '
            f'border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'
        )
    if not html:
        html = (
            f'<div class="msg-brief px-3 py-2 text-sm text-gray-500">'
            f'（没有返回叙事内容）</div>'
        )
    return html


def _completed_payload(turn) -> dict:
    narrative = turn.narrative if turn else ""
    brief = turn.brief if turn else ""
    combat_result = turn.combat if turn else None
    skill_results = turn.skill_results if turn else []
    game_over = turn.game_over if turn else False
    ending = asdict(turn.ending) if turn and turn.ending else None
    timestamp = turn.timestamp if turn else ""
    player_snapshot = turn.player_snapshot if turn else None
    pending_data = asdict(turn.pending_interaction) if turn and turn.pending_interaction else None
    status = turn.status.value if turn else "completed"

    if player_snapshot and hasattr(player_snapshot, '__dataclass_fields__'):
        player_snapshot = asdict(player_snapshot)

    _join_enemy_library(player_snapshot)
    _attach_potential_threats(player_snapshot)

    turn_dynamic_text = ""
    try:
        from game_loop import format_turn_dynamic
        turn_dynamic_text = format_turn_dynamic(player_snapshot, brief, narrative)
    except Exception:
        traceback.print_exc()

    payload = {
        "status": status,
        "brief": brief,
        "narrative": narrative,
        "narrative_html": _narrative_html(brief, narrative),
        "pending_interaction": pending_data,
        "combat": combat_result,
        "combat_init": _serialize_combat_init(turn),
        "skill_results": skill_results,
        "game_over": game_over,
        "ending": ending,
        "timestamp": timestamp,
        "player_snapshot": player_snapshot,
        "turn_dynamic_text": turn_dynamic_text,
    }
    if turn and turn.debug is not None:
        payload["debug"] = turn.debug
    return payload


def _on_progress_bridge(loop):
    """工作线程进度 → 事件循环线程 put_nowait（asyncio.Queue 非线程安全）。"""
    def on_progress(step, status):
        loop.call_soon_threadsafe(_push_progress, step, status)
    return on_progress


@router.post("/api/game/turn")
async def process_turn(
    user_input: str = Form(""),
    action_type: str = Form(""),
    action_target: str = Form(""),
    debug: int = Form(0),
):
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
        return _slash_payload(slash._handle_slash_command(stripped))

    from game_loop import run_turn
    from game.messages import TurnStatus

    try:
        game = session.get_game()
        if game is None:
            return _exited_payload()
    except Exception as e:
        traceback.print_exc()
        return _engine_error_html(e)

    loop = asyncio.get_running_loop()
    on_progress = _on_progress_bridge(loop)
    try:
        turn = await loop.run_in_executor(
            None,
            partial(
                run_turn, game, user_input, session._weapon_lib, session._enemy_lib,
                session._injector, action_type, action_target, debug=bool(debug),
                on_progress=on_progress,
            ),
        )
    except Exception as e:
        traceback.print_exc()
        _push_progress("complete", "")
        return _turn_error_html(e)

    if turn and turn.status == TurnStatus.FROZEN:
        return _frozen_payload(turn)
    return _completed_payload(turn)


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
    msg = {"step": step, "status": status}
    for q in list(session._progress_queues.values()):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass
