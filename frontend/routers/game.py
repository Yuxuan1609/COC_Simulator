"""frontend/routers/game.py — Game loop API + WebSocket progress stream."""
from __future__ import annotations

import json
import asyncio
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
_game_quit: bool = False  # prevents auto-reinit after /quit
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


def get_game() -> dict | None:
    global _game_instance, _game_quit
    if _game_quit:
        return None
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


def _handle_slash_command(cmd: str) -> str:
    """Handle slash commands synchronously, return HTML."""
    global _game_instance
    game = get_game()
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events",
                 "/save <slot>", "/load <slot>", "/quit", "/reset", "/help"]
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
                lines.append(f'<div class="text-xs text-gray-400">{ev}</div>')
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
    elif cmd in ("/quit", "/exit"):
        global _game_quit
        _game_instance = None
        _game_quit = True
        lines.append('<div class="text-xs text-green-400">游戏已退出。返回启动页以重新开始。</div>')
    elif cmd == "/reset":
        _game_instance = None
        _game_quit = False
        lines.append('<div class="text-xs text-green-400">游戏已重置，刷新页面以重新开始</div>')
    else:
        lines.append(f'<div class="text-xs text-gray-500">未知命令: {cmd}。输入 /help 查看可用命令。</div>')
    return "".join(lines)


@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    import asyncio
    import traceback
    from game_loop import run_turn

    # Route slash commands directly — skip LLM pipeline
    stripped = user_input.strip()
    if stripped.startswith("/"):
        cmd_html = _handle_slash_command(stripped)
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
        game = get_game()
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
    combat = turn.get("combat") if turn else None
    skill_results = turn.get("skill_results", []) if turn else []
    game_over = turn.get("game_over", False) if turn else False
    ending = turn.get("ending") if turn else None
    timestamp = turn.get("timestamp", "") if turn else ""
    player_snapshot = turn.get("player_snapshot") if turn else None

    # Serialize PlayerFacingSnapshot to dict
    if player_snapshot and hasattr(player_snapshot, '__dataclass_fields__'):
        from dataclasses import asdict
        player_snapshot = asdict(player_snapshot)

    # Format dynamic turn text from snapshot
    turn_dynamic_text = ""
    try:
        from game_loop import format_turn_dynamic
        turn_dynamic_text = format_turn_dynamic(player_snapshot, brief, narrative)
    except Exception:
        pass

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
        "brief": brief,
        "narrative": narrative,
        "narrative_html": narrative_html,
        "combat": combat,
        "skill_results": skill_results,
        "game_over": game_over,
        "ending": ending,
        "timestamp": timestamp,
        "player_snapshot": player_snapshot,
        "turn_dynamic_text": turn_dynamic_text,
    }


@router.get("/api/game/character-card", response_class=HTMLResponse)
async def character_card():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-500">无调查员</span>')

    stats = p.stats
    derived = p.derived
    avatar = getattr(p, 'avatar_url', '') or ""

    # --- Header block ---
    avatar_block = (
        f'<img src="{avatar}" class="w-14 h-14 rounded-full object-cover border-2 border-gray-700" onerror="this.style.display=\'none\'">'
        if avatar else
        '<div class="w-14 h-14 rounded-full bg-gray-800 flex items-center justify-center text-gray-500 border-2 border-gray-700">'
        '<svg class="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
        '</div>'
    )

    header = (
        f'<div class="flex items-center gap-3 pb-3 border-b border-gray-800/60">'
        f'{avatar_block}'
        f'<div class="min-w-0">'
        f'<div class="text-sm font-bold text-aged-gold truncate">{p.name}</div>'
        f'<div class="text-[10px] text-gray-500">{p.age}岁 {p.gender} {p.occupation or ""}</div>'
        f'</div></div>'
    )

    # --- Stats grid (3x3) ---
    stat_labels = {"STR": "力量", "CON": "体质", "SIZ": "体型", "DEX": "敏捷", "APP": "外貌",
                   "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
    stats_cells = "".join(
        f'<div class="text-center p-1.5 bg-[#1a150c]/60 rounded border border-gray-800/40">'
        f'<div class="text-[10px] text-gray-500">{stat_labels.get(k, k)}</div>'
        f'<div class="text-sm font-bold text-gray-300">{getattr(stats, k, 0)}</div>'
        f'</div>'
        for k in ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
    )
    stats_html = (
        f'<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">属性</div>'
        f'<div class="grid grid-cols-3 gap-1.5">{stats_cells}</div></div>'
    )

    # --- Derived stats bar ---
    hp_pct = min(100, max(0, (derived.HP / derived.HP_MAX * 100) if derived.HP_MAX else 0))
    san_pct = min(100, max(0, derived.SAN / 99 * 100))
    derived_html = (
        f'<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">状态</div>'
        f'<div class="space-y-2">'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>HP</span><span class="text-coc-green">{derived.HP}/{derived.HP_MAX}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-coc-green rounded transition-all duration-500" style="width:{hp_pct}%"></div></div></div>'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>SAN</span><span class="text-aged-gold">{derived.SAN}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-aged-gold rounded transition-all duration-500" style="width:{san_pct}%"></div></div></div>'
        f'<div class="flex gap-3 text-[10px] text-gray-400 pt-1">'
        f'<span>MP <span class="text-gray-300">{derived.MP}</span></span>'
        f'<span>MOV <span class="text-gray-300">{derived.MOV}</span></span>'
        f'<span>DB <span class="text-gray-300">{derived.DB}</span></span>'
        f'<span>BUILD <span class="text-gray-300">{derived.BUILD}</span></span>'
        f'<span>DODGE <span class="text-gray-300">{derived.DODGE}</span></span>'
        f'</div></div></div>'
    )

    # --- Skills by category ---
    skills_list = list(p.skills.values()) if isinstance(p.skills, dict) else (p.skills if isinstance(p.skills, list) else [])
    cats = {}
    for s in skills_list:
        cat = getattr(s, 'category', '其他')
        cats.setdefault(cat, []).append(s)
    cat_order = ["战斗", "操作", "感知", "知识", "社交", "其他"]
    cat_colors = {"战斗": "text-red-400/70", "操作": "text-blue-400/70", "感知": "text-green-400/70",
                  "知识": "text-purple-400/70", "社交": "text-yellow-400/70", "其他": "text-gray-500"}

    skills_sections = []
    for cat in cat_order:
        if cat not in cats:
            continue
        items = cats[cat]
        items_html = "".join(
            f'<div class="flex justify-between items-center py-0.5">'
            f'<span class="text-xs text-gray-400">{s.name}</span>'
            f'<span class="text-xs font-mono {cat_colors.get(cat, "text-gray-500")}">{s.value}%</span>'
            f'</div>'
            for s in sorted(items, key=lambda x: -x.value)
        )
        skills_sections.append(
            f'<details class="group">'
            f'<summary class="flex items-center justify-between cursor-pointer py-1 text-[10px] text-gray-500 hover:text-gray-300 list-none">'
            f'<span class="flex items-center gap-1"><span class="w-1 h-1 rounded-full {cat_colors.get(cat, "bg-gray-500")}"></span>{cat} ({len(items)})</span>'
            f'<span class="text-gray-600 group-open:rotate-180 transition-transform">▼</span>'
            f'</summary>'
            f'<div class="pl-3 border-l border-gray-800/40 ml-1 space-y-0.5">{items_html}</div>'
            f'</details>'
        )
    skills_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">技能 ({len(skills_list)})</div>'
        f'<div class="space-y-1">{"".join(skills_sections)}</div></div>'
    ) if skills_list else ''

    # --- Weapons ---
    weapons = getattr(p, 'weapons', [])
    weapons_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">武器 ({len(weapons)})</div>'
        f'<div class="space-y-1">'
        + "".join(
            f'<div class="flex justify-between text-xs text-gray-400 py-0.5">'
            f'<span>{w.name}</span><span class="text-gray-500">{getattr(w, "damage", "?")}</span>'
            f'</div>'
            for w in weapons
        )
        + '</div></div>'
    ) if weapons else ''

    # --- Items ---
    items_desc = p.item_manager.describe() if hasattr(p, 'item_manager') and p.item_manager else "无"
    items_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">物品</div>'
        f'<div class="text-xs text-gray-400 leading-relaxed">{items_desc}</div></div>'
    )

    return HTMLResponse(
        header + stats_html + derived_html + skills_html + weapons_html + items_html
    )


@router.get("/api/game/player-status")
async def player_status(format: str = ""):
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
    hp, san = p.derived.HP, p.derived.SAN
    has_avatar = getattr(p, 'avatar_url', '')
    occupation = getattr(p, 'occupation', '')
    occ_name = getattr(occupation, 'name', '') if occupation else ''
    if format == "json":
        return {
            "hp": hp,
            "hp_max": p.derived.HP_MAX,
            "san": san,
            "name": p.name,
            "avatar_url": has_avatar,
            "occupation": occ_name,
            "age": p.age,
            "gender": p.gender,
        }
    return HTMLResponse(
        f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
        f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
    )


@router.post("/api/game/command", response_class=HTMLResponse)
async def game_command(cmd: str = Form(...)):
    global _game_instance
    game = get_game()
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events",
                 "/save <slot>", "/load <slot>", "/quit", "/reset", "/help"]
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
    elif cmd in ("/quit", "/exit"):
        global _game_quit
        _game_instance = None
        _game_quit = True
        lines.append('<div class="text-xs text-green-400">游戏已退出。返回启动页以重新开始。</div>')
    elif cmd == "/reset":
        _game_instance = None
        _game_quit = False
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
    q: asyncio.Queue = asyncio.Queue()
    qid = str(id(ws))
    _progress_queues[qid] = q
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
        _progress_queues.pop(qid, None)


def _push_progress(step: str, status: str):
    """Send progress update to all connected WS clients."""
    import asyncio as _asyncio
    msg = {"step": step, "status": status}
    for q in list(_progress_queues.values()):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
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
    global _game_instance, _game_quit
    _game_quit = False
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

    # Fire initial turn to trigger scene auto_triggers
    initial_brief = ""
    initial_narrative = ""
    try:
        from game_loop import run_turn
        initial = run_turn(g, "[游戏开始]", _weapon_lib, _enemy_lib, _injector)
        initial_brief = initial.get("brief", "") if initial else ""
        initial_narrative = initial.get("narrative", "") if initial else ""
    except Exception:
        pass

    return {
        "success": True,
        "location": g["keeper"].world.current_location,
        "hp": inv.derived.HP,
        "san": inv.derived.SAN,
        "name": inv.name,
        "initial_brief": initial_brief,
        "initial_narrative": initial_narrative,
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
