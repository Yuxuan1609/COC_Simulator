# src/investigator/serialization.py
"""JSON 序列化 / 反序列化"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Any

from investigator.models import (
    Stats, DerivedStats, Skill, Occupation, Weapon, Investigator, ItemManager,
)


def _occupation_dict_to_obj(d: dict) -> Occupation:
    """dict → Occupation"""
    return Occupation(
        name=d.get("name", "Unknown"),
        description=d.get("description", ""),
        occupation_skills=d.get("occupation_skills", []),
        credit_rating_min=d.get("credit_rating_min", 0),
        credit_rating_max=d.get("credit_rating_max", 99),
        skill_points_formula=d.get("skill_points_formula", "EDU*4"),
    )


def to_dict(inv: Investigator) -> dict:
    """Investigator → dict"""
    occ_data = None
    if inv.occupation:
        occ_data = {
            "name": inv.occupation.name,
            "description": inv.occupation.description,
            "occupation_skills": inv.occupation.occupation_skills,
            "credit_rating_min": inv.occupation.credit_rating_min,
            "credit_rating_max": inv.occupation.credit_rating_max,
            "skill_points_formula": inv.occupation.skill_points_formula,
        }

    return {
        "meta": {
            "version": "2.2",
            "created_at": datetime.now().isoformat(),
            "rules_edition": "COC7",
        },
        "personal": {
            "name": inv.name,
            "age": inv.age,
            "gender": inv.gender,
            "occupation": occ_data,
            "description": inv.personal_description,
            "appearance": inv.appearance,
            "extra": getattr(inv, 'extra', ''),
            "label": getattr(inv, 'label', ''),
        },
        "stats": {
            "STR": inv.stats.STR, "CON": inv.stats.CON,
            "DEX": inv.stats.DEX, "APP": inv.stats.APP, "INT": inv.stats.INT,
            "POW": inv.stats.POW, "EDU": inv.stats.EDU, "LUCK": inv.stats.LUCK,
        },
        "derived": {
            "HP": inv.derived.HP, "HP_MAX": inv.derived.HP_MAX,
            "MP": inv.derived.MP, "MP_MAX": inv.derived.MP_MAX,
            "SAN": inv.derived.SAN, "SAN_MAX": inv.derived.SAN_MAX,
            "DB": inv.derived.DB,
            "BUILD": inv.derived.BUILD, "DODGE": inv.derived.DODGE,
        },
        "skills": [
            {
                "name": s.name,
                "base": s.base_value,
                "value": s.value,
                "category": s.category,
                "is_occupation": s.is_occupation,
            }
            for s in inv.skills
        ],
        "combat": {
            "weapons": [
                {
                    "name": w.name,
                    "skill_name": w.skill_name,
                    "damage": w.damage,
                    "range": w.range,
                    "ammo": w.ammo,
                    "malfunction": w.malfunction,
                }
                for w in inv.weapons
            ],
        },
        "equipment": list(getattr(inv, 'equipment', [])),
        "item_manager": inv.item_manager.to_dict() if inv.item_manager._items else {},
        "backstory": inv.backstory,
        "avatar_url": inv.avatar_url,
        "known_spells": list(getattr(inv, 'known_spells', [])),
        "timed_effects": [dict(t) for t in getattr(inv, 'timed_effects', [])],
    }


def to_json(inv: Investigator, path: str) -> None:
    """导出 Investigator 为 JSON 文件"""
    data = to_dict(inv)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def from_dict(data: dict) -> Investigator:
    """dict → Investigator。旧 45 技能/含 SIZ 结构的卡拒绝加载（U9 强制重建）。"""
    stats_data = data.get("stats", {})
    if "SIZ" in stats_data:
        raise ValueError(
            "旧版角色卡（含 SIZ 的 45 技能体系）不兼容新技能体系，请重建角色。")
    personal = data.get("personal", {})
    derived_data = data.get("derived", {})
    skills_data = data.get("skills", [])
    combat_data = data.get("combat", {})

    occ = None
    occ_data = personal.get("occupation")
    if occ_data and isinstance(occ_data, dict):
        occ = _occupation_dict_to_obj(occ_data)

    stats = Stats(
        STR=stats_data.get("STR", 0), CON=stats_data.get("CON", 0),
        DEX=stats_data.get("DEX", 0),
        APP=stats_data.get("APP", 0), INT=stats_data.get("INT", 0),
        POW=stats_data.get("POW", 0), EDU=stats_data.get("EDU", 0),
        LUCK=stats_data.get("LUCK", 0),
    )

    derived = DerivedStats(
        HP=derived_data.get("HP", 0), HP_MAX=derived_data.get("HP_MAX", derived_data.get("HP", 0)),
        MP=derived_data.get("MP", 0),
        MP_MAX=derived_data.get("MP_MAX", derived_data.get("MP", 0)),
        SAN=derived_data.get("SAN", 0), SAN_MAX=derived_data.get("SAN_MAX", 99),
        DB=derived_data.get("DB", "0"),
        BUILD=derived_data.get("BUILD", 0), DODGE=derived_data.get("DODGE", 0),
    )

    skills = [
        Skill(
            name=s["name"],
            base_value=s.get("base", 0),
            value=s.get("value", s.get("base", 0)),
            category=s.get("category", "通用"),
            is_occupation=s.get("is_occupation", False),
        )
        for s in skills_data
    ]

    weapons = [
        Weapon(
            name=w["name"],
            skill_name=w.get("skill_name", "格斗"),
            damage=w.get("damage", "1D3+DB"),
            range=w.get("range", "接触"),
            ammo=w.get("ammo", 0),
            malfunction=w.get("malfunction", 100),
        )
        for w in combat_data.get("weapons", [])
    ]

    equipment = list(data.get("equipment", []))

    inv = Investigator(
        name=personal.get("name", "Unknown"),
        age=personal.get("age", 20),
        gender=personal.get("gender", ""),
        occupation=occ,
        stats=stats,
        derived=derived,
        skills=skills,
        weapons=weapons,
        equipment=equipment,
        backstory=data.get("backstory", ""),
        appearance=personal.get("appearance", ""),
        personal_description=personal.get("description", ""),
        avatar_url=data.get("avatar_url", ""),
        extra=personal.get("extra", ""),
    )
    inv.label = personal.get("label", "")
    im_data = data.get("item_manager", {})
    if im_data:
        inv.item_manager = ItemManager.from_dict(im_data)
    inv.known_spells = list(data.get("known_spells", []) or [])
    inv.timed_effects = [dict(t) for t in (data.get("timed_effects", []) or [])
                         if isinstance(t, dict) and "expire_at" in t]
    return inv


def from_json(path: str) -> Investigator:
    """从 JSON 文件加载 Investigator"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return from_dict(data)
