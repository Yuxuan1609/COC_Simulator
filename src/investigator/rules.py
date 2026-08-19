# src/investigator/rules.py
"""COC 7th 规则引擎 —— 全部为纯函数"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

from utils import roll_d6
from investigator.models import Stats, DerivedStats, Skill, Occupation, Weapon


# ═══════════════════════════════════════════════════════════════
#  属性生成
# ═══════════════════════════════════════════════════════════════

def roll_stats() -> Stats:
    """掷骰生成核心属性（骰面配置见 skill_config.json attributes，U9 起无 SIZ）"""
    return Stats(
        STR=roll_d6(3) * 5,
        CON=roll_d6(3) * 5,
        DEX=roll_d6(3) * 5,
        APP=roll_d6(3) * 5,
        INT=(roll_d6(2) + 6) * 5,
        POW=roll_d6(3) * 5,
        EDU=(roll_d6(2) + 6) * 5,
        LUCK=roll_d6(3) * 5,
    )


# ═══════════════════════════════════════════════════════════════
#  衍生属性计算
# ═══════════════════════════════════════════════════════════════

def _calc_db_build(key: int) -> Tuple[str, int]:
    """U9 查表键 = STR + CON//2，返回 (DB, BUILD)"""
    if key <= 64:
        return "-2", -2
    elif key <= 84:
        return "-1", -1
    elif key <= 124:
        return "0", 0
    elif key <= 164:
        return "+1D4", 1
    elif key <= 204:
        return "+1D6", 2
    else:
        return "+2D6", 3


def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """U9 衍生公式：HP=CON//3；DB/BUILD 查表键=STR+CON//2；删 MOV。"""
    hp = max(1, math.floor(stats.CON / 3))
    mp = math.floor(stats.POW / 5)
    san = stats.POW
    san_max = 99 - cthulhu_mythos
    dodge = math.floor(stats.DEX / 2)
    db, build = _calc_db_build(stats.STR + stats.CON // 2)
    return DerivedStats(
        HP=hp, HP_MAX=hp, MP=mp, MP_MAX=mp, SAN=san, SAN_MAX=san_max,
        DB=db, BUILD=build, DODGE=dodge,
    )


# ═══════════════════════════════════════════════════════════════
#  技能系统
# ═══════════════════════════════════════════════════════════════

def create_skill_list() -> List[Skill]:
    """从 skill_config.json 生成新 20 项技能列表（克苏鲁神话 base=0 不走池）"""
    from utils import load_skill_config
    cfg = load_skill_config()
    return [
        Skill(name=s["name"], base_value=s["base"], value=s["base"],
              category="、".join(s.get("attr", [])))
        for s in cfg["skills"]
    ]


def allocate_skill_points(
    skills: List[Skill],
    stats: Stats,
    focus: List[str] | None = None,
    focus_bonus: int = 0,
) -> List[Skill]:
    """U9 属性池分配：每属性池=属性值×乘数（config），均分到归属技能；
    多属性技能从各归属池分别获益叠加；focus 技能额外 +focus_bonus；上限 99。"""
    from utils import load_skill_config
    cfg = load_skill_config()
    attrs_cfg = cfg["attributes"]
    skill_attrs = {s["name"]: s.get("attr", []) for s in cfg["skills"]}
    no_pool = {s["name"] for s in cfg["skills"] if s.get("special") == "no_pool"}

    by_name = {s.name: s for s in skills}
    for attr, ac in attrs_cfg.items():
        pool = int(getattr(stats, attr, 0) * float(ac.get("multiplier", 0)))
        members = [n for n, al in skill_attrs.items()
                   if attr in al and n not in no_pool and n in by_name]
        if not members or pool <= 0:
            continue
        per, rem = divmod(pool, len(members))
        for i, n in enumerate(members):
            by_name[n].value += per + (1 if i < rem else 0)
    for n in (focus or []):
        if n in by_name:
            by_name[n].value += focus_bonus
    for s in skills:
        s.value = min(99, max(s.value, s.base_value if s.name not in no_pool else 0))
    return skills


def calc_occupation_points(formula: str, stats: Stats) -> int:
    """根据职业公式计算职业技能点数。e.g. 'EDU*4' → stats.EDU * 4"""
    try:
        result = 0
        parts = formula.replace("-", "+-").split("+")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if "*" in part:
                attr, mul = part.split("*")
                attr = attr.strip().upper()
                mul = int(mul.strip())
                result += getattr(stats, attr, 0) * mul
            else:
                attr = part.strip().upper()
                if hasattr(stats, attr):
                    result += getattr(stats, attr)
        return result
    except Exception:
        return stats.EDU * 4  # fallback


# ═══════════════════════════════════════════════════════════════
#  年龄修正
# ═══════════════════════════════════════════════════════════════

def apply_age_modifiers(stats: Stats, age: int):
    """
    COC 7th 年龄修正（原位修改）。

    | 年龄段 (tier) | APP    | STR/CON/DEX   | EDU  |
    |---------------|--------|---------------|------|
    | 40-49 (0)     | -5     | 0             | +5   |
    | 50-59 (1)     | -10    | -5            | +10  |
    | 60-69 (2)     | -15    | -10           | +15  |
    | 70-79 (3)     | -20    | -20           | +20  |
    | 80+ (4)       | -25    | -40           | +25  |
    """
    if age < 40:
        return

    tier = (age - 40) // 10
    if tier > 4:
        tier = 4

    # Lookup tables by tier
    app_penalties = [-5, -10, -15, -20, -25]
    phys_penalties = [0, -5, -10, -20, -40]
    edu_bonuses = [5, 10, 15, 20, 25]

    stats.APP = max(0, stats.APP + app_penalties[tier])
    if phys_penalties[tier]:
        stats.STR = max(0, stats.STR + phys_penalties[tier])
        stats.CON = max(0, stats.CON + phys_penalties[tier])
        stats.DEX = max(0, stats.DEX + phys_penalties[tier])
    stats.EDU = min(99, stats.EDU + edu_bonuses[tier])


# ═══════════════════════════════════════════════════════════════
#  信用评级
# ═══════════════════════════════════════════════════════════════

CREDIT_RATING_TABLE: Dict[int, str] = {
    0: "身无分文",
    5: "拮据",
    10: "一般",
    20: "中等",
    30: "宽裕",
    50: "富裕",
    70: "富有",
    90: "极富",
}


def get_credit_level(value: int) -> str:
    """根据信用评级数值返回等级描述"""
    result = "身无分文"
    for threshold, label in sorted(CREDIT_RATING_TABLE.items()):
        if value >= threshold:
            result = label
    return result


# ═══════════════════════════════════════════════════════════════
#  战斗
# ═══════════════════════════════════════════════════════════════

def create_default_unarmed() -> Weapon:
    """创建默认徒手攻击武器"""
    return Weapon(
        name="徒手",
        skill_name="格斗",
        damage="1D3+DB",
        range="接触",
    )


# ═══════════════════════════════════════════════════════════════
#  职业加载
# ═══════════════════════════════════════════════════════════════

def load_occupations(path: str) -> List[Occupation]:
    """从 JSON 文件加载职业列表"""
    import json
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return [
        Occupation(
            name=d["name"],
            description=d.get("description", ""),
            occupation_skills=d.get("occupation_skills", []),
            credit_rating_min=d.get("credit_rating_min", 0),
            credit_rating_max=d.get("credit_rating_max", 99),
            skill_points_formula=d.get("skill_points_formula", "EDU*4"),
        )
        for d in data
    ]


def load_occupation_labels(path: str | None = None) -> list:
    """加载职业标签（U9 标签制）"""
    import json, os
    if path is None:
        path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "occupation_labels.json"))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def calc_db(STR: int, SIZ: int) -> str:
    """COC 7th Damage Bonus from STR + SIZ."""
    total = STR + SIZ
    if total <= 64:
        return "-2"
    if total <= 84:
        return "-1"
    if total <= 124:
        return "0"
    if total <= 164:
        return "+1D4"
    return "+1D6"


# ═══════════════════════════════════════════════════════════════
#  对抗检定（统一资源层：法术/物品 opposed 检定，战斗/探索两侧复用）
# ═══════════════════════════════════════════════════════════════

_TIER_RANK = {"fumble": 0, "failure": 0, "regular": 1, "hard": 2, "extreme": 3}


def _opposed_roll(value: int) -> tuple[int, str]:
    roll = random.randint(1, 100)
    if roll >= 96 and roll > value:
        return roll, "fumble"
    if roll == 1:
        return roll, "extreme"
    if roll <= max(1, value // 5):
        return roll, "extreme"
    if roll <= max(1, value // 2):
        return roll, "hard"
    if roll <= value:
        return roll, "regular"
    return roll, "failure"


def opposed_check(att_value: int, def_value: int) -> tuple[str, str]:
    """对抗检定：成功等级高者胜；同级比技能值；再同（或双败）为 tie。
    返回 ("win"|"lose"|"tie", detail)。"""
    a_roll, a_tier = _opposed_roll(att_value)
    d_roll, d_tier = _opposed_roll(def_value)
    detail = (f"对抗 D100: 攻方 {a_roll}/{att_value}({a_tier}) vs "
              f"守方 {d_roll}/{def_value}({d_tier})")
    if _TIER_RANK[a_tier] != _TIER_RANK[d_tier]:
        return ("win" if _TIER_RANK[a_tier] > _TIER_RANK[d_tier] else "lose"), detail
    if _TIER_RANK[a_tier] == 0:
        return "tie", detail + "（双方均失败）"
    if att_value != def_value:
        return ("win" if att_value > def_value else "lose"), detail + "（同级比技能值）"
    return "tie", detail + "（不分胜负）"
