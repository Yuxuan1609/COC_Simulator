"""frontend/routers/game.py — Game loop API + WebSocket progress stream."""
from __future__ import annotations

import json
import asyncio
import queue
import threading
from pathlib import Path
from fastapi import APIRouter, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["game"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Game instance (lazy init) ──
_game_instance: dict | None = None

_progress_queues: dict[str, queue.Queue] = {}


def get_game() -> dict:
    global _game_instance
    if _game_instance is None:
        from game_loop import init_game
        from investigator import load_investigator, Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        import os
        from datetime import datetime
        from prompts import set_prompt_log_dir
        from llm import set_llm_log_dir

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = str(PROJECT_ROOT / f"logs/prompt_log_{timestamp}")
        os.makedirs(log_dir, exist_ok=True)
        set_prompt_log_dir(log_dir)
        set_llm_log_dir(log_dir)

        g = init_game(
            l2_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l2_test.json"),
            l1_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l1_test.json"),
            l3_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l3_test.json"),
            start_node="测试房间",
        )
        char_path = str(PROJECT_ROOT / "investigator/test_character.json")
        if os.path.exists(char_path):
            inv = load_investigator(char_path)
        else:
            inv = Investigator(name="调查员A", age=25, gender="男")
            inv.stats = roll_stats()
            inv.skills = create_skill_list()
            inv.derived = calc_derived(inv.stats, inv.age)
        g["keeper"].world.set_player(inv)
        _game_instance = g
    return _game_instance


@router.get("/game", response_class=HTMLResponse)
async def game_page(request: Request):
    return templates.TemplateResponse("game.html", {"request": request})


@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    from game_loop import run_turn
    game = get_game()

    _push_progress("parse", "running")
    turn = run_turn(game, user_input)
    _push_progress("parse", "done")
    _push_progress("judge", "done")
    _push_progress("enrich", "done")
    _push_progress("combat_entry", "done")
    _push_progress("curate", "done")
    _push_progress("narrate", "done")
    _push_progress("complete", "")

    narrative = turn.get("narrative", "") if turn else ""
    brief = turn.get("brief", "") if turn else ""

    narrative_html = ""
    if brief:
        narrative_html += f'<div class="msg-brief px-3 py-2 text-sm text-gray-500 border-l-2 border-gray-600 mb-2">{brief}</div>'
    if narrative:
        narrative_html += f'<div class="msg-narrative px-3 py-2 text-parchment border-l-3 border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'

    return HTMLResponse(narrative_html)


@router.get("/api/game/player-status", response_class=HTMLResponse)
async def player_status():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
    hp, san = p.derived.HP, p.derived.SAN
    return HTMLResponse(
        f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
        f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
    )


@router.get("/api/game/scene", response_class=HTMLResponse)
async def scene_info():
    game = get_game()
    world = game["keeper"].world
    loc = world.current_location
    desc = world.get_current_description()
    exits = world.get_possible_exits()
    exits_html = "".join(
        f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>' for e in exits
    )
    return HTMLResponse(
        f'<div class="font-bold text-aged-brown">{loc}</div>'
        f'<div class="text-xs text-gray-500 mt-1">{desc}</div>'
        f'{exits_html}'
    )


@router.websocket("/api/game/progress")
async def game_progress(ws: WebSocket):
    await ws.accept()
    q: queue.Queue = queue.Queue()
    qid = str(id(ws))
    _progress_queues[qid] = q
    try:
        while True:
            try:
                msg = q.get(timeout=30)
                await ws.send_json(msg)
                if msg.get("step") == "complete":
                    break
            except queue.Empty:
                await ws.send_json({"step": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        _progress_queues.pop(qid, None)


def _push_progress(step: str, status: str):
    """Send progress update to all connected WS clients."""
    msg = {"step": step, "status": status}
    for q in list(_progress_queues.values()):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


@router.post("/api/game/init")
async def init_game_api(
    request: Request,
    l1_path: str = Form(""),
    l2_path: str = Form(""),
    l3_path: str = Form(""),
    char_path: str = Form(""),
    weapon_path: str = Form(""),
    enemy_path: str = Form(""),
    boss_path: str = Form(""),
):
    global _game_instance
    import os
    from datetime import datetime
    from game_loop import init_game
    from investigator import load_investigator, Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    from prompts import set_prompt_log_dir
    from llm import set_llm_log_dir

    # Default paths if empty
    if not l2_path:
        l2_path = "data/modules/常暗之厢/l2_test.json"
    if not l1_path:
        l1_path = "data/modules/常暗之厢/l1_test.json"
    if not l3_path:
        l3_path = "data/modules/常暗之厢/l3_test.json"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(PROJECT_ROOT / f"logs/prompt_log_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)

    try:
        g = init_game(
            l2_path=str(PROJECT_ROOT / l2_path),
            l1_path=str(PROJECT_ROOT / l1_path),
            l3_path=str(PROJECT_ROOT / l3_path),
            start_node="测试房间",
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    if char_path and os.path.exists(str(PROJECT_ROOT / char_path)):
        try:
            inv = load_investigator(str(PROJECT_ROOT / char_path))
        except Exception:
            inv = _make_default_inv()
    else:
        inv = _make_default_inv()

    g["keeper"].world.set_player(inv)
    _game_instance = g

    return {
        "success": True,
        "location": g["keeper"].world.current_location,
        "hp": inv.derived.HP,
        "san": inv.derived.SAN,
        "name": inv.name,
    }


def _make_default_inv():
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    inv = Investigator(name="调查员", age=25, gender="男")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    return inv
