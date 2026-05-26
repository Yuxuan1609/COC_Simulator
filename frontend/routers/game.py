"""frontend/routers/game.py — Game loop API + WebSocket progress stream."""
from __future__ import annotations

import json
import asyncio
import queue
import threading
from pathlib import Path
from fastapi import APIRouter, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["game"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Game instance (lazy init) ──
_game_instance: dict | None = None
_weapon_lib = None
_enemy_lib = None
_injector = None

_progress_queues: dict[str, queue.Queue] = {}


def _init_libraries(weapon_path="", enemy_path="", boss_path=""):
    global _weapon_lib, _enemy_lib, _injector
    if _weapon_lib is not None:
        return
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    from library.injector import ContentInjector

    _weapon_lib = WeaponLibrary()
    if weapon_path:
        _weapon_lib.load_core(str(PROJECT_ROOT / weapon_path))
    else:
        _weapon_lib.load_core()
    _enemy_lib = EnemyLibrary()
    if enemy_path:
        _enemy_lib.load_core(str(PROJECT_ROOT / enemy_path))
    else:
        _enemy_lib.load_core()
    _injector = ContentInjector(_weapon_lib, _enemy_lib)


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

        from game.turn_logger import TurnLogger
        from game_loop import set_turn_logger
        set_turn_logger(TurnLogger(log_dir=log_dir))

        _init_libraries()

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
    return templates.TemplateResponse(request, "game.html", {})


@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    import asyncio
    import traceback
    from game_loop import run_turn

    try:
        game = get_game()
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
        turn = await loop.run_in_executor(None, run_turn, game, user_input, _weapon_lib, _enemy_lib, _injector)
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

    narrative = turn.get("narrative", "") if turn else ""
    brief = turn.get("brief", "") if turn else ""

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


@router.post("/api/game/command", response_class=HTMLResponse)
async def game_command(cmd: str = Form(...)):
    game = get_game()
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events", "/do <动作>", "/trigger <E1>",
                 "/save <槽位>", "/load <槽位>", "/reset", "/help"]
        lines = [f'<div class="text-xs text-gray-500">{"  ".join(names)}</div>']
    elif cmd == "/scene":
        loc = world.current_location
        desc = world.get_current_description()
        lines.append(f'<div class="font-bold text-aged-brown">{loc}</div>')
        lines.append(f'<div class="text-xs text-gray-500 mt-1">{desc}</div>')
        for e in world.get_possible_exits():
            lines.append(f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>')
    elif cmd == "/char":
        if p:
            lines.append(f'<div class="text-sm text-aged-gold">{p.name} (HP {p.derived.HP} SAN {p.derived.SAN})</div>')
            lines.append(f'<div class="text-xs text-gray-500">属性: {" ".join(f"{k}={getattr(p.stats,k,0)}" for k in ["STR","CON","SIZ","DEX","APP","INT","POW","EDU","LUCK"])}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">未设置调查员</div>')
    elif cmd == "/flags":
        rs = world.runtime_state or {}
        if rs:
            for k, v in rs.items():
                c = "text-green-400" if v.get("completed") else "text-gray-500"
                lines.append(f'<div class="text-xs {c}">{k}: {v}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无状态</div>')
    elif cmd == "/events":
        triggered = world.triggered_events or []
        if triggered:
            for ev in triggered:
                lines.append(f'<div class="text-xs text-gray-400">• {ev}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无已触发事件</div>')
    elif cmd.startswith("/save"):
        slot = cmd.replace("/save", "").strip() or "1"
        try:
            from game_loop import save_game
            save_game(game, str(PROJECT_ROOT / f"save_{slot}.json"))
            lines.append(f'<div class="text-xs text-green-400">已存档到 save_{slot}.json</div>')
        except Exception as e:
            lines.append(f'<div class="text-xs text-red-400">存档失败: {e}</div>')
    elif cmd.startswith("/load"):
        slot = cmd.replace("/load", "").strip() or "1"
        spath = str(PROJECT_ROOT / f"save_{slot}.json")
        if Path(spath).exists():
            try:
                from game_loop import load_game
                load_game(game, spath)
                lines.append(f'<div class="text-xs text-green-400">已从 save_{slot}.json 读档</div>')
            except Exception as e:
                lines.append(f'<div class="text-xs text-red-400">读档失败: {e}</div>')
        else:
            lines.append(f'<div class="text-xs text-gray-500">存档 save_{slot}.json 不存在</div>')
    elif cmd == "/reset":
        global _game_instance
        _game_instance = None
        lines.append('<div class="text-xs text-green-400">游戏已重置，刷新页面以重新开始</div>')
    else:
        lines.append(f'<div class="text-xs text-gray-500">未知命令: {cmd}。输入 /help 查看可用命令。</div>')
    return HTMLResponse("".join(lines))


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

    # Initialize libraries with user-specified paths
    _init_libraries(weapon_path, enemy_path, boss_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(PROJECT_ROOT / f"logs/prompt_log_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)

    from game.turn_logger import TurnLogger
    from game_loop import set_turn_logger
    set_turn_logger(TurnLogger(log_dir=log_dir))

    # Determine start scene: L3.start_scene > L3.scene_intents first key > L2 first scene
    start_node = _resolve_start_scene(l2_path, l3_path)

    try:
        g = init_game(
            l2_path=str(PROJECT_ROOT / l2_path),
            l1_path=str(PROJECT_ROOT / l1_path),
            l3_path=str(PROJECT_ROOT / l3_path),
            start_node=start_node,
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


@router.get("/api/game/state")
async def game_state():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    return {
        "location": world.current_location,
        "turn": game["keeper"].turn_number,
        "hp": p.derived.HP if p else 0,
        "san": p.derived.SAN if p else 0,
        "name": p.name if p else "",
    }


@router.get("/api/game/npcs", response_class=HTMLResponse)
async def npc_list():
    game = get_game()
    world = game["keeper"].world
    npcs = world.npcs or []
    if not npcs or not hasattr(npcs, 'get_in_scene'):
        return HTMLResponse('<span class="text-xs text-gray-500">无 NPC</span>')
    visible = npcs.get_in_scene(world.current_location)
    if not visible:
        return HTMLResponse('<span class="text-xs text-gray-500">当前场景无 NPC</span>')
    cards = ""
    for n in visible:
        att = n.attitude or "neutral"
        att_cls = {"hostile": "text-red-400", "wary": "text-yellow-400", "friendly": "text-green-400"}.get(att, "text-gray-400")
        cards += (f'<div class="text-xs flex gap-2 py-1"><span class="text-gray-300">{n.name}</span>'
                  f'<span class="{att_cls}">[{att}]</span></div>')
    return HTMLResponse(cards)


def _resolve_start_scene(l2_path: str, l3_path: str) -> str:
    """Determine the starting scene for game init.

    Priority:
    1. L3 JSON top-level 'start_scene' field
    2. L3 JSON module_meta.start_scene
    3. First key in L3 scene_intents dict
    4. First key in L2 scenes dict
    5. Fallback: "测试房间"
    """
    import json as _json
    l2_full = PROJECT_ROOT / l2_path
    l3_full = PROJECT_ROOT / l3_path

    # Try L3 first
    if l3_full.exists():
        try:
            l3 = _json.loads(l3_full.read_text(encoding="utf-8"))
            # Check top-level start_scene
            if isinstance(l3, dict):
                if "start_scene" in l3 and l3["start_scene"]:
                    return l3["start_scene"]
                # Check module_meta.start_scene
                meta = l3.get("module_meta", {})
                if isinstance(meta, dict) and meta.get("start_scene"):
                    return meta["start_scene"]
                # First scene_intents key
                si = l3.get("scene_intents", {})
                if isinstance(si, dict) and si:
                    return next(iter(si.keys()))
        except Exception:
            pass

    # Try L2 scenes dict
    if l2_full.exists():
        try:
            l2 = _json.loads(l2_full.read_text(encoding="utf-8"))
            scenes = l2.get("scenes", {})
            if isinstance(scenes, dict) and scenes:
                return next(iter(scenes.keys()))
        except Exception:
            pass

    return "测试房间"


def _make_default_inv():
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    inv = Investigator(name="调查员", age=25, gender="男")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    return inv
