"""frontend/routers/game/views.py — 页面与状态小接口。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter()

from . import session
from .charcard import _known_spell_names


def _clamp_history_limit(n: int) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 20
    return max(1, min(50, n))


def _paginate_narrative_log(entries, before_turn=None, limit=20):
    """newest-first page of narrative_log. next_before = 本页最小 turn（若还有更早）。"""
    limit = _clamp_history_limit(limit)
    items = [e for e in (entries or []) if isinstance(e, dict)]
    if before_turn is not None:
        try:
            bt = int(before_turn)
        except (TypeError, ValueError):
            bt = None
        if bt is not None:
            items = [e for e in items if e.get("turn", 0) < bt]
    newest_first = sorted(items, key=lambda e: e.get("turn", 0), reverse=True)
    page = newest_first[:limit]
    next_before = None
    if page:
        smallest = min(e.get("turn", 0) for e in page)
        if any(e.get("turn", 0) < smallest for e in newest_first):
            next_before = smallest
    return {
        "items": [
            {
                "turn": e.get("turn"),
                "brief": e.get("brief") or "",
                "narrative": e.get("narrative") or "",
            }
            for e in page
        ],
        "next_before": next_before,
    }


@router.get("/game", response_class=HTMLResponse)
async def game_page(request: Request):
    return session.templates.TemplateResponse(request, "game.html", {})


@router.get("/api/game/player-status")
async def player_status(format: str = ""):
    game = session.get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
    hp, san = p.derived.HP, p.derived.SAN
    has_avatar = getattr(p, 'avatar_url', '')
    occupation = getattr(p, 'occupation', '')
    occ_name = getattr(occupation, 'name', '') if occupation else ''
    spell_names = _known_spell_names(world, p)
    if format == "json":
        return {
            "hp": hp,
            "hp_max": p.derived.HP_MAX,
            "mp": p.derived.MP,
            "mp_max": p.derived.MP_MAX,
            "san": san,
            "san_max": p.derived.SAN_MAX,
            "name": p.name,
            "avatar_url": has_avatar,
            "occupation": occ_name,
            "age": p.age,
            "gender": p.gender,
            "known_spells": spell_names,
        }
    return HTMLResponse(
        f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
        f'<span class="text-gray-500 ml-2">MP </span><span class="text-coc-blue">{p.derived.MP}</span>'
        f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
    )


@router.get("/api/game/scene", response_class=HTMLResponse)
async def scene_info():
    game = session.get_game()
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


@router.get("/api/game/state")
async def game_state():
    game = session.get_game()
    world = game["keeper"].world
    p = world.player
    return {
        "location": world.current_location,
        "turn": game["keeper"].turn_number,
        "hp": p.derived.HP if p else 0,
        "hp_max": p.derived.HP_MAX if p else 0,
        "mp": p.derived.MP if p else 0,
        "mp_max": p.derived.MP_MAX if p else 0,
        "san": p.derived.SAN if p else 0,
        "san_max": p.derived.SAN_MAX if p else 99,
        "name": p.name if p else "",
        "known_spells": _known_spell_names(world, p) if p else [],
        "warning": game.get("_char_load_warning") if game else None,
    }


@router.get("/api/game/history")
async def game_history(before_turn: int | None = None, limit: int = 20):
    """F39：玩家侧叙事历史。只读 chronicle.narrative_log，不含 Author events。"""
    game = session.get_game()
    if game is None:
        return JSONResponse({"error": "no_game"}, status_code=400)
    world = game["keeper"].world
    chronicle = getattr(world, "chronicle", None)
    entries = getattr(chronicle, "narrative_log", []) if chronicle is not None else []
    return _paginate_narrative_log(entries, before_turn=before_turn, limit=limit)


@router.post("/api/game/autowin")
async def set_auto_win(request: Request):
    """Toggle auto-win combat short-circuit (testing aid)."""
    import json
    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session._auto_win = bool(data.get("enabled", False))
    return {"auto_win": session._auto_win}

