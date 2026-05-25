"""frontend/routers/character.py — Character creation wizard API."""
from __future__ import annotations

import json
import random
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

router = APIRouter(prefix="/character", tags=["character"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Skill base values (COC 7th) ──
SKILLS = [
    {"name": "会计", "base": 5, "cat": "知识"}, {"name": "人类学", "base": 1, "cat": "知识"},
    {"name": "估价", "base": 5, "cat": "知识"}, {"name": "考古学", "base": 1, "cat": "知识"},
    {"name": "魅惑", "base": 15, "cat": "社交"}, {"name": "攀爬", "base": 20, "cat": "操作"},
    {"name": "信用评级", "base": 0, "cat": "社交"}, {"name": "克苏鲁神话", "base": 0, "cat": "知识"},
    {"name": "乔装", "base": 5, "cat": "社交"}, {"name": "汽车驾驶", "base": 20, "cat": "操作"},
    {"name": "电气维修", "base": 10, "cat": "操作"}, {"name": "电子学", "base": 1, "cat": "知识"},
    {"name": "话术", "base": 5, "cat": "社交"}, {"name": "格斗", "base": 25, "cat": "战斗"},
    {"name": "枪械", "base": 20, "cat": "战斗"}, {"name": "急救", "base": 30, "cat": "操作"},
    {"name": "历史", "base": 5, "cat": "知识"}, {"name": "恐吓", "base": 15, "cat": "社交"},
    {"name": "跳跃", "base": 20, "cat": "操作"}, {"name": "外语", "base": 1, "cat": "知识"},
    {"name": "母语", "base": 50, "cat": "知识"}, {"name": "法律", "base": 5, "cat": "知识"},
    {"name": "图书馆使用", "base": 20, "cat": "知识"}, {"name": "聆听", "base": 20, "cat": "感知"},
    {"name": "锁匠", "base": 1, "cat": "操作"}, {"name": "机械维修", "base": 10, "cat": "操作"},
    {"name": "医学", "base": 1, "cat": "知识"}, {"name": "博物学", "base": 10, "cat": "知识"},
    {"name": "导航", "base": 10, "cat": "知识"}, {"name": "神秘学", "base": 5, "cat": "知识"},
    {"name": "操作重型机械", "base": 1, "cat": "操作"}, {"name": "说服", "base": 10, "cat": "社交"},
    {"name": "驾驶", "base": 20, "cat": "操作"}, {"name": "心理学", "base": 10, "cat": "感知"},
    {"name": "精神分析", "base": 1, "cat": "知识"}, {"name": "骑术", "base": 5, "cat": "操作"},
    {"name": "科学", "base": 1, "cat": "知识"}, {"name": "妙手", "base": 10, "cat": "操作"},
    {"name": "潜行", "base": 20, "cat": "操作"}, {"name": "侦查", "base": 25, "cat": "感知"},
    {"name": "生存", "base": 10, "cat": "操作"}, {"name": "游泳", "base": 20, "cat": "操作"},
    {"name": "投掷", "base": 20, "cat": "战斗"}, {"name": "追踪", "base": 10, "cat": "感知"},
]

STATS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
STAT_LABELS = {"STR": "力量", "CON": "体质", "SIZ": "体型", "DEX": "敏捷", "APP": "外貌",
               "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
STAT_ROLLS = {
    "STR": (3, 0), "CON": (3, 0), "DEX": (3, 0), "APP": (3, 0), "POW": (3, 0),
    "SIZ": (2, 6), "INT": (2, 6), "EDU": (2, 6), "LUCK": (3, 0),
}


def _load_occupations():
    path = PROJECT_ROOT / "data" / "occupations.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _roll_stat(dice: int, add: int) -> int:
    return (sum(random.randint(1, 6) for _ in range(dice)) + add) * 5


@router.get("", response_class=HTMLResponse)
async def character_page(request: Request):
    return templates.TemplateResponse("character.html", {
        "request": request,
        "skills": SKILLS,
        "stats": STATS,
        "stat_labels": STAT_LABELS,
        "occupations": _load_occupations(),
    })


@router.get("/step/{n}", response_class=HTMLResponse)
async def step_partial(request: Request, n: int):
    if n == 1:
        return templates.TemplateResponse("partials/char-step1.html", {
            "request": request, "stats": STATS, "stat_labels": STAT_LABELS, "stat_rolls": STAT_ROLLS,
        })
    elif n == 2:
        return templates.TemplateResponse("partials/char-step2.html", {
            "request": request, "skills": SKILLS, "occupations": _load_occupations(),
        })
    elif n == 3:
        return templates.TemplateResponse("partials/char-step3.html", {"request": request})
    return HTMLResponse("<p class='text-red-500'>Invalid step</p>", status_code=404)


@router.post("/roll", response_class=HTMLResponse)
async def roll_stats():
    import random as _r
    values = {s: _roll_stat(*STAT_ROLLS[s]) for s in STATS}
    hp = (values["CON"] + values["SIZ"]) // 10
    mp = values["POW"] // 5
    san = values["POW"]
    dodge = values["DEX"] // 2
    ss = values["STR"] + values["SIZ"]
    if ss <= 64: db, build = "-2", -2
    elif ss <= 84: db, build = "-1", -1
    elif ss <= 124: db, build = "0", 0
    elif ss <= 164: db, build = "+1D4", 1
    elif ss <= 204: db, build = "+1D6", 2
    else: db, build = "+2D6", 3

    cells = "".join(
        f'<div class="stat-card p-3 bg-[#1a150c] border border-[#3a2810] rounded text-center">'
        f'<div class="text-xs text-gray-500">{STAT_LABELS[s]} ({s})</div>'
        f'<div class="text-2xl font-bold text-aged-gold">{values[s]}</div>'
        f'</div>'
        for s in STATS
    )
    derived = f'<div class="grid grid-cols-4 gap-2 text-xs"><div>HP {hp}</div><div>MP {mp}</div><div>SAN {san}</div><div>DODGE {dodge}</div><div>DB {db}</div><div>BUILD {build}</div></div>'
    return HTMLResponse(f'<div class="grid grid-cols-3 gap-3">{cells}</div><div class="mt-4 p-3 bg-[#1a150c] border border-[#3a2810] rounded">{derived}</div>')


@router.post("/generate-description")
async def generate_description(type: str = Form(...), prompt: str = Form(...)):
    from llm import call_deepseek
    if type == "appearance":
        system = "你是一个COC 7th TRPG角色外貌描述生成器。根据用户提供的关键词生成一段简洁的外貌描述（150字以内）。仅输出描述文本。"
    else:
        system = "你是一个COC 7th TRPG角色个人描述生成器。根据用户提供的关键词生成一段简洁的角色个人描述（150字以内）。仅输出描述文本。"
    try:
        result = call_deepseek(prompt, json_mode=False, system=system,
                              model="deepseek-v4-flash", thinking=False,
                              max_tokens=300, temperature=0.7, max_retries=1)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(str(result).strip())
    except Exception as e:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"[生成失败: {e}]", status_code=500)


@router.post("/export")
async def export_character(
    name: str = Form(""), age: int = Form(20), gender: str = Form(""),
    occupation: str = Form(""), appearance: str = Form(""),
    description: str = Form(""), backstory: str = Form(""),
):
    import json as _json
    from datetime import datetime as _dt
    data = {
        "meta": {"version": "1.0", "created_at": _dt.now().isoformat(), "rules_edition": "COC7"},
        "personal": {"name": name, "age": age, "gender": gender, "occupation": occupation,
                     "appearance": appearance, "description": description},
        "backstory": backstory,
    }
    content = _json.dumps(data, ensure_ascii=False, indent=2)
    from fastapi.responses import Response
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename={name or 'character'}_character.json"})
