"""frontend/routers/game/charcard.py — 角色卡 HTML。"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

from . import session


def _known_spell_names(world, p) -> list[str]:
    """known_spells 的 id 列表解析为中文名(库外 id 原样保留)。"""
    lib = getattr(world, "spell_library", None)
    names = []
    for sid in getattr(p, "known_spells", []):
        sp = lib.get(sid) if lib else None
        names.append(sp.name if sp else sid)
    return names


@router.get("/api/game/character-card", response_class=HTMLResponse)
async def character_card():
    game = session.get_game()
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

    # 职业名称（兼容字符串或 Occupation 对象）
    occ_name = ""
    if p.occupation:
        occ_name = p.occupation if isinstance(p.occupation, str) else getattr(p.occupation, 'name', '')

    header = (
        f'<div class="flex items-center gap-3 pb-3 border-b border-gray-800/60">'
        f'{avatar_block}'
        f'<div class="min-w-0">'
        f'<div class="text-sm font-bold text-aged-gold truncate">{p.name}</div>'
        f'<div class="text-[10px] text-gray-500">{p.age}岁 {p.gender} {occ_name}</div>'
        f'</div></div>'
    )

    # --- Introduction: appearance + personal description ---
    intro_parts = []
    if getattr(p, 'appearance', ''):
        intro_parts.append(f'<div class="text-[10px] text-gray-400"><span class="text-gray-500">外貌：</span>{p.appearance}</div>')
    if getattr(p, 'personal_description', ''):
        intro_parts.append(f'<div class="text-[10px] text-gray-400 leading-relaxed">{p.personal_description}</div>')
    intro_html = (
        f'<div class="space-y-1.5 pt-2">{ "".join(intro_parts) }</div>'
    ) if intro_parts else ''

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
    san_pct = min(100, max(0, derived.SAN / max(1, derived.SAN_MAX) * 100))
    derived_html = (
        f'<div class="pt-2"><div class="text-[10px] text-gray-500 font-bold mb-1.5">状态</div>'
        f'<div class="space-y-2">'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>HP</span><span class="text-coc-green">{derived.HP}/{derived.HP_MAX}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-coc-green rounded transition-all duration-500" style="width:{hp_pct}%"></div></div></div>'
        f'<div><div class="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>SAN</span><span class="text-aged-gold">{derived.SAN}</span></div>'
        f'<div class="h-1.5 bg-gray-800 rounded overflow-hidden"><div class="h-full bg-aged-gold rounded transition-all duration-500" style="width:{san_pct}%"></div></div></div>'
        f'<div class="flex gap-3 text-[10px] text-gray-400 pt-1">'
        f'<span>MP <span class="text-gray-300">{derived.MP}/{derived.MP_MAX}</span></span>'
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

    # --- Spells (统一资源层:已知法术列表区) ---
    spell_rows = []
    _lib = getattr(world, "spell_library", None)
    for sid in getattr(p, "known_spells", []):
        sp = _lib.get(sid) if _lib else None
        if sp:
            cat_label = "战斗" if getattr(sp, "category", "") == "combat" else "探索"
            spell_rows.append(
                f'<div class="flex justify-between text-xs text-gray-400 py-0.5">'
                f'<span>{sp.name}</span><span class="text-gray-500 text-[10px]">{cat_label}</span></div>'
            )
        else:
            spell_rows.append(
                f'<div class="flex justify-between text-xs text-gray-500 py-0.5">'
                f'<span>{sid}</span><span class="text-[10px]">库中未找到</span></div>'
            )
    spells_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">已知法术 ({len(spell_rows)})</div>'
        f'<div class="space-y-0.5">{"".join(spell_rows)}</div></div>'
    ) if spell_rows else ''

    # --- Items ---
    items_desc = p.item_manager.describe() if hasattr(p, 'item_manager') and p.item_manager else "无"
    items_html = (
        f'<div class="pt-2 border-t border-gray-800/60">'
        f'<div class="text-[10px] text-gray-500 font-bold mb-1.5">物品</div>'
        f'<div class="text-xs text-gray-400 leading-relaxed">{items_desc}</div></div>'
    )

    return HTMLResponse(
        header + intro_html + stats_html + derived_html + skills_html
        + weapons_html + spells_html + items_html
    )

