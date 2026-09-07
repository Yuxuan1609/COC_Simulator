"""frontend/routers/game/charcard.py — 角色卡 JSON。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

from . import session

_STAT_KEYS = ("STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK")


def _known_spell_names(world, p) -> list[str]:
    """known_spells 的 id 列表解析为中文名(库外 id 原样保留)。"""
    lib = getattr(world, "spell_library", None)
    names = []
    for sid in getattr(p, "known_spells", []):
        sp = lib.get(sid) if lib else None
        names.append(sp.name if sp else sid)
    return names


def _occupation_name(p) -> str:
    occ = getattr(p, "occupation", None)
    if not occ:
        return ""
    return occ if isinstance(occ, str) else getattr(occ, "name", "") or ""


def _skills_payload(p) -> list[dict]:
    skills = getattr(p, "skills", None)
    if isinstance(skills, dict):
        items = list(skills.values())
    elif isinstance(skills, list):
        items = skills
    else:
        items = []
    out = []
    for s in items:
        out.append({
            "name": getattr(s, "name", ""),
            "value": getattr(s, "value", 0),
            "category": getattr(s, "category", None) or "其他",
        })
    return out


def _weapons_payload(p) -> list[dict]:
    weapons = getattr(p, "weapons", None) or []
    return [
        {"name": getattr(w, "name", ""), "damage": getattr(w, "damage", "?")}
        for w in weapons
    ]


def _spells_payload(world, p) -> list[dict]:
    lib = getattr(world, "spell_library", None)
    out = []
    for sid in getattr(p, "known_spells", []):
        sp = lib.get(sid) if lib else None
        if sp:
            raw_cat = getattr(sp, "category", "") or ""
            cat = "战斗" if raw_cat == "combat" else "探索"
            out.append({"id": sid, "name": sp.name, "category": cat})
        else:
            out.append({"id": sid, "name": sid, "category": None})
    return out


def _items_payload(p) -> str:
    mgr = getattr(p, "item_manager", None)
    if mgr and hasattr(mgr, "describe"):
        desc = mgr.describe()
        return desc if desc else "无"
    return "无"


@router.get("/api/game/character-card")
async def character_card():
    game = session.get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return {"name": None}

    stats = p.stats
    derived = p.derived
    return {
        "name": p.name,
        "age": getattr(p, "age", None),
        "gender": getattr(p, "gender", None),
        "occupation": _occupation_name(p),
        "avatar_url": getattr(p, "avatar_url", "") or "",
        "appearance": getattr(p, "appearance", "") or "",
        "personal_description": getattr(p, "personal_description", "") or "",
        "stats": {k: getattr(stats, k, 0) for k in _STAT_KEYS},
        "hp": derived.HP,
        "hp_max": derived.HP_MAX,
        "san": derived.SAN,
        "san_max": derived.SAN_MAX,
        "mp": derived.MP,
        "mp_max": derived.MP_MAX,
        "mov": getattr(derived, "MOV", 0),
        "db": getattr(derived, "DB", "0"),
        "build": getattr(derived, "BUILD", 0),
        "dodge": getattr(derived, "DODGE", 0),
        "skills": _skills_payload(p),
        "weapons": _weapons_payload(p),
        "spells": _spells_payload(world, p),
        "items": _items_payload(p),
    }
