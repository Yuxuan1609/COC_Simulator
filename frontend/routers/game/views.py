"""frontend/routers/game/views.py — 页面与状态小接口。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

router = APIRouter()

from . import session
from .charcard import _known_spell_names


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


@router.post("/api/game/autowin")
async def set_auto_win(request: Request):
    """Toggle auto-win combat short-circuit (testing aid)."""
    import json
    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session._auto_win = bool(data.get("enabled", False))
    return {"auto_win": session._auto_win}

