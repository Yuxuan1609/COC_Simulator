"""frontend/routers/character.py — Character creation wizard API."""
from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, JSONResponse

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

import sys as _sys
if str(PROJECT_ROOT / "src") not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT / "src"))
from utils import load_skill_config

router = APIRouter(prefix="/character", tags=["character"])

TEMPLATES_DIR = FRONTEND_DIR / "templates"
UPLOADS_DIR = FRONTEND_DIR / "static" / "uploads"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Skills & stats from skill_config.json (U9: 20 技能/8 属性) ──
_SKILL_CFG = load_skill_config()
SKILLS = [{"name": s["name"], "base": s["base"], "cat": "、".join(s.get("attr", []))}
          for s in _SKILL_CFG["skills"]]

STATS = list(_SKILL_CFG["attributes"].keys())
STAT_LABELS = {"STR": "力量", "CON": "体质", "DEX": "敏捷", "APP": "外貌",
               "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
STAT_ROLLS = {
    k: (v["dice"][0], v["dice"][1] if len(v["dice"]) > 1 else 0)
    for k, v in _SKILL_CFG["attributes"].items()
}


def _load_labels():
    from investigator.rules import load_occupation_labels
    return load_occupation_labels()


def _roll_stat(dice: int, add: int) -> int:
    return (sum(random.randint(1, 6) for _ in range(dice)) + add) * 5


@router.get("", response_class=HTMLResponse)
async def character_page(request: Request):
    return templates.TemplateResponse(request, "character.html", {
        "skills": SKILLS,
        "stats": STATS,
        "stat_labels": STAT_LABELS,
        "labels": _load_labels(),
    })


@router.post("/upload-avatar")
async def upload_avatar(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix if file.filename else ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return JSONResponse({"error": "不支持的文件格式"}, status_code=400)
    filename = f"avatar_{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / "avatars" / filename
    content = await file.read()
    dest.write_bytes(content)
    url = f"/static/uploads/avatars/{filename}"
    return JSONResponse({"url": url})


@router.get("/step/{n}", response_class=HTMLResponse)
async def step_partial(request: Request, n: int):
    if n == 1:
        return templates.TemplateResponse(request, "partials/char-step1.html", {
            "stats": STATS, "stat_labels": STAT_LABELS, "stat_rolls": STAT_ROLLS,
        })
    elif n == 2:
        return templates.TemplateResponse(request, "partials/char-step2.html", {
            "skills": SKILLS, "labels": _load_labels(),
        })
    elif n == 3:
        return templates.TemplateResponse(request, "partials/char-step3.html", {})
    return HTMLResponse("<p class='text-red-500'>Invalid step</p>", status_code=404)


@router.post("/roll", response_class=HTMLResponse)
async def roll_stats():
    import random as _r
    values = {s: _roll_stat(*STAT_ROLLS[s]) for s in STATS}
    hp = max(1, values["CON"] // 3)
    mp = values["POW"] // 5
    san = values["POW"]
    dodge = values["DEX"] // 2
    ss = values["STR"] + values["CON"] // 2
    if ss <= 64: db, build = "-2", -2
    elif ss <= 84: db, build = "-1", -1
    elif ss <= 124: db, build = "0", 0
    elif ss <= 164: db, build = "+1D4", 1
    elif ss <= 204: db, build = "+1D6", 2
    else: db, build = "+2D6", 3

    cells = "".join(
        f'<div class="stat-card p-3 bg-[#1a150c] border border-[#3a2810] rounded text-center">'
        f'<div class="text-xs text-gray-500">{STAT_LABELS[s]} ({s})</div>'
        f'<input type="number" name="stat_{s}" value="{values[s]}" min="8" max="99" '
        f'class="stat-input w-16 text-xl font-bold text-aged-gold bg-transparent border-b border-gray-700 text-center focus:outline-none focus:border-aged-gold [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" '
        f'onchange="charRecalcDerived();charStoreStats()" oninput="charRecalcDerived()">'
        f'</div>'
        for s in STATS
    )
    derived = (
        f'<div id="derived-stats" class="grid grid-cols-3 gap-1 text-xs mt-2 text-gray-500">'
        f'<div>HP <input type="number" id="derived-hp" name="stat_HP" value="{hp}" readonly min="1" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-green-400 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>MP <input type="number" id="derived-mp" name="stat_MP" value="{mp}" readonly min="0" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-gray-200 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>SAN <input type="number" id="derived-san" name="stat_SAN" value="{san}" readonly min="0" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-aged-gold font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>DODGE <input type="number" id="derived-dodge" name="stat_DODGE" value="{dodge}" readonly min="1" max="99" class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'<div>DB <input type="text" id="derived-db" name="stat_DB" value="{db}" readonly class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none" tabindex="-1"></div>'
        f'<div>BUILD <input type="number" id="derived-build" name="stat_BUILD" value="{build}" readonly min="-2" max="6" class="derived-input w-12 bg-transparent border-0 text-center text-gray-300 font-bold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none" tabindex="-1"></div>'
        f'</div>'
    )
    return HTMLResponse(f'<div class="grid grid-cols-3 gap-3">{cells}</div><div class="mt-4 p-3 bg-[#1a150c] border border-[#3a2810] rounded">{derived}</div>')


@router.get("/skills-list", response_class=HTMLResponse)
async def skills_list(label: str = ""):
    # 职业标签 → 专精技能 +bonus
    focus, bonus = set(), 0
    for l in _load_labels():
        if l["name"] == label:
            focus, bonus = set(l.get("focus", [])), int(l.get("bonus", 0))
            break

    # 按归属属性分块；双属性技能重复出现，仅首个块可编辑
    attrs_cfg = _SKILL_CFG["attributes"]
    attr_of: dict[str, list] = {}
    for s in _SKILL_CFG["skills"]:
        for a in s.get("attr", []):
            attr_of.setdefault(a, []).append(s)
    special = [s for s in _SKILL_CFG["skills"] if not s.get("attr")]
    mult_js = json.dumps({k: v.get("multiplier", 0) for k, v in attrs_cfg.items()},
                         ensure_ascii=False)

    def _row(s, editable):
        name, base = s["name"], s["base"]
        is_focus = name in focus
        val = min(99, base + bonus) if is_focus else base
        badge = ('<span class="text-[10px] text-aged-gold bg-aged-brown/30 px-1 rounded">专精</span>'
                 if is_focus else '')
        border = "border-aged-gold" if is_focus else "border-[#4a3820]"
        bg = "bg-aged-brown/20" if is_focus else "bg-[#1a150c]"
        if editable:
            ctrl = (f'<input type="number" min="0" max="99" value="{val}" '
                    f'class="skill-input w-16 bg-[#1a150c] border {border} rounded px-2 py-1 text-xs text-gray-300 focus:border-aged-gold focus:outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none">')
        else:
            ctrl = f'<span class="w-16 text-center text-xs text-gray-600">{val}%</span>'
        return (f'<div class="flex items-center gap-2 py-1 px-2 {bg} rounded">'
                f'<span class="text-sm text-gray-300 w-32">{name} {badge}</span>'
                f'<span class="text-xs text-gray-600 w-16">基础 {base}%</span>{ctrl}</div>')

    rows = [f'<script>window._ATTR_MULT = {mult_js};</script>',
            f'<div id="skills-list-inner" data-label="{label}">',
            '<div class="text-sm text-gray-500 mb-2">技能按归属属性分块；专精技能已按标签加成</div>']
    if not label:
        rows.append('<div class="text-xs text-gray-600 mb-3">可先选择职业标签以标记专精技能</div>')

    seen = set()
    for attr, ac in attrs_cfg.items():
        members = attr_of.get(attr, [])
        if not members:
            continue
        rows.append(
            f'<div class="text-xs text-gray-500 font-bold mt-3 mb-1 border-b border-gray-800 pb-1">'
            f'{STAT_LABELS[attr]} ({attr}) ×{ac.get("multiplier", 0)}'
            f' · 池参考 <span class="pool-ref text-aged-gold" data-attr="{attr}"></span></div>')
        for s in members:
            editable = s["name"] not in seen
            seen.add(s["name"])
            rows.append(_row(s, editable))
    if special:
        rows.append('<div class="text-xs text-gray-500 font-bold mt-3 mb-1 border-b border-gray-800 pb-1">特殊</div>')
        for s in special:
            rows.append(_row(s, True))
    rows.append('</div>')

    html = "".join(rows)
    html += (
        '<script>'
        'setTimeout(function(){'
        '  document.querySelectorAll(".pool-ref").forEach(function(el){'
        '    var attr = el.dataset.attr;'
        '    var inp = document.querySelector("#roll-result input[name=\'stat_" + attr + "\']")'
        '           || document.getElementById("stat-" + attr);'
        '    var v = inp ? (parseInt(inp.value) || 0) : 0;'
        '    var mult = (window._ATTR_MULT || {})[attr] || 0;'
        '    el.textContent = Math.floor(v * mult);'
        '  });'
        '  var inner = document.getElementById("skills-list-inner");'
        '  var cur = inner ? inner.dataset.label : "";'
        '  var savedLabel = document.getElementById("skills-label")?.value || "";'
        '  var saved = document.getElementById("skills-json")?.value;'
        '  if (saved && savedLabel === cur) {'
        '    try { var obj = JSON.parse(saved);'
        '      document.querySelectorAll("#skills-list .skill-input").forEach(function(inp){'
        '        var label = inp.closest(".flex")?.querySelector("span")?.textContent?.replace(/(职业|专精)\\s*$/,"").trim();'
        '        if (label && obj[label] !== undefined) inp.value = obj[label];'
        '      });'
        '    } catch(e) {}'
        '  }'
        '  charStoreSkills();'
        '}, 200);'
        '</script>'
    )
    return HTMLResponse(html)


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


def _build_export(name: str, age: int, gender: str,
                  label: str, appearance: str, description: str,
                  backstory: str,
                  stat_STR: int, stat_CON: int,
                  stat_DEX: int, stat_APP: int, stat_INT: int,
                  stat_POW: int, stat_EDU: int, stat_LUCK: int,
                  stat_HP: int, stat_MP: int, stat_SAN: int,
                  stat_DODGE: int, stat_DB: str, stat_BUILD: int,
                  skills_json: str, avatar_url: str):
    import json as _json
    from datetime import datetime as _dt
    from investigator.models import Stats, DerivedStats
    from investigator.serialization import to_dict
    from investigator import Investigator
    from investigator.rules import create_skill_list

    inv = Investigator(name=name or "调查员", age=age, gender=gender or "男")
    inv.stats = Stats(
        STR=stat_STR, CON=stat_CON, DEX=stat_DEX,
        APP=stat_APP, INT=stat_INT, POW=stat_POW, EDU=stat_EDU, LUCK=stat_LUCK,
    )
    inv.derived = DerivedStats(
        HP=stat_HP, HP_MAX=stat_HP, MP=stat_MP, SAN=stat_SAN,
        DB=stat_DB, BUILD=stat_BUILD, DODGE=stat_DODGE,
    )
    skills = create_skill_list()
    custom = _json.loads(skills_json) if skills_json.strip() else {}
    for s in skills:
        if s.name in custom:
            s.value = int(custom[s.name])
    inv.skills = skills
    inv.occupation = None
    inv.label = label or ""
    inv.appearance = appearance or ""
    inv.description = description or ""
    inv.backstory = backstory or ""
    inv.avatar_url = avatar_url or ""

    data = to_dict(inv)
    data["meta"].update({
        "version": "2.2",
        "created_at": _dt.now().isoformat(),
        "rules_edition": "COC7",
    })
    content = _json.dumps(data, ensure_ascii=False, indent=2)

    import zipfile, io
    from urllib.parse import quote
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('character.json', content)
        if inv.avatar_url and inv.avatar_url.startswith('/static/uploads/avatars/'):
            avatar_path = PROJECT_ROOT / 'frontend' / 'static' / 'uploads' / 'avatars' / Path(inv.avatar_url).name
            if avatar_path.exists():
                zf.write(avatar_path, f'avatar{avatar_path.suffix}')

    buf.seek(0)
    safe_name = (name or "character").strip()
    encoded = quote(f"{safe_name}.zip", safe="")
    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


@router.get("/export")
async def export_character_get(
    name: str = "", age: int = 20, gender: str = "",
    label: str = "", appearance: str = "", description: str = "",
    backstory: str = "",
    stat_STR: int = 0, stat_CON: int = 0,
    stat_DEX: int = 0, stat_APP: int = 0, stat_INT: int = 0,
    stat_POW: int = 0, stat_EDU: int = 0, stat_LUCK: int = 0,
    stat_HP: int = 0, stat_MP: int = 0, stat_SAN: int = 0,
    stat_DODGE: int = 0, stat_DB: str = "0", stat_BUILD: int = 0,
    skills_json: str = "{}", avatar_url: str = "",
):
    return _build_export(name, age, gender, label, appearance, description,
                         backstory, stat_STR, stat_CON, stat_DEX,
                         stat_APP, stat_INT, stat_POW, stat_EDU, stat_LUCK,
                         stat_HP, stat_MP, stat_SAN, stat_DODGE, stat_DB,
                         stat_BUILD, skills_json, avatar_url)


@router.post("/export")
async def export_character(
    name: str = Form(""), age: int = Form(20), gender: str = Form(""),
    label: str = Form(""), appearance: str = Form(""),
    description: str = Form(""), backstory: str = Form(""),
    stat_STR: int = Form(0), stat_CON: int = Form(0),
    stat_DEX: int = Form(0), stat_APP: int = Form(0), stat_INT: int = Form(0),
    stat_POW: int = Form(0), stat_EDU: int = Form(0), stat_LUCK: int = Form(0),
    stat_HP: int = Form(0), stat_MP: int = Form(0), stat_SAN: int = Form(0),
    stat_DODGE: int = Form(0), stat_DB: str = Form("0"), stat_BUILD: int = Form(0),
    skills_json: str = Form("{}"),
    avatar_url: str = Form(""),
):
    return _build_export(name, age, gender, label, appearance, description,
                         backstory, stat_STR, stat_CON, stat_DEX,
                         stat_APP, stat_INT, stat_POW, stat_EDU, stat_LUCK,
                         stat_HP, stat_MP, stat_SAN, stat_DODGE, stat_DB,
                         stat_BUILD, skills_json, avatar_url)
