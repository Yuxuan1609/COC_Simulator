# src/investigator/rules.py
"""COC 7th 规则引擎 —— 全部为纯函数"""

from __future__ import annotations

import copy
import json
import math
import os
import random
from typing import List, Tuple

from investigator.models import Stats, DerivedStats, Skill, Occupation, Weapon


# ═══════════════════════════════════════════════════════════════
#  属性生成
# ═══════════════════════════════════════════════════════════════

def roll_stats() -> Stats:
    """掷骰生成核心属性。骰面读 skill_config.attributes.dice([count, sides] 或
    [count, sides, flat])，总乘数 game_config.stat_roll_multiplier(默认 5)。"""
    from utils import load_skill_config
    cfg = load_skill_config()
    times = get_game_config()["stat_roll_multiplier"]
    vals = {}
    for attr, ac in cfg["attributes"].items():
        dice = ac.get("dice", [3, 6])
        count, sides = int(dice[0]), int(dice[1])
        flat = int(dice[2]) if len(dice) > 2 else 0
        roll = sum(random.randint(1, sides) for _ in range(count))
        vals[attr] = (roll + flat) * times
    return Stats(**vals)


# ═══════════════════════════════════════════════════════════════
#  衍生属性计算
# ═══════════════════════════════════════════════════════════════

def _calc_db_build(key: int) -> Tuple[str, int]:
    """U9 查表键 = STR + CON//2，返回 (DB, BUILD)(表: game_config.db_build_table)。"""
    for row in get_game_config()["db_build_table"]:
        mk = row["max_key"]
        if mk is None or key <= mk:
            return row["db"], row["build"]
    return "0", 0  # 空表兜底


def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """U9 衍生公式(除数/基数见 game_config.derived)：HP=CON//hp_divisor；
    MP=POW//mp_divisor；DODGE=DEX//dodge_divisor；SAN 上限=san_max_base-神话；
    DB/BUILD 查表键=STR+CON//2。"""
    d = get_game_config()["derived"]
    hp = max(1, math.floor(stats.CON / d["hp_divisor"]))
    mp = math.floor(stats.POW / d["mp_divisor"])
    san = stats.POW
    san_max = d["san_max_base"] - cthulhu_mythos
    dodge = math.floor(stats.DEX / d["dodge_divisor"])
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
    多属性技能从各归属池分别获益叠加；focus 技能额外 +focus_bonus；
    上限 skill_value_cap(config)。"""
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
    cap = get_game_config()["skill_value_cap"]
    for s in skills:
        s.value = min(cap, max(s.value, s.base_value if s.name not in no_pool else 0))
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
    cfg = get_game_config()["age_modifiers"]
    if age < cfg["start_age"]:
        return

    tier = (age - cfg["start_age"]) // 10
    tier = min(tier, cfg["max_tier"],
               len(cfg["app_penalties"]) - 1, len(cfg["phys_penalties"]) - 1,
               len(cfg["edu_bonuses"]) - 1)

    stats.APP = max(0, stats.APP + cfg["app_penalties"][tier])
    if cfg["phys_penalties"][tier]:
        stats.STR = max(0, stats.STR + cfg["phys_penalties"][tier])
        stats.CON = max(0, stats.CON + cfg["phys_penalties"][tier])
        stats.DEX = max(0, stats.DEX + cfg["phys_penalties"][tier])
    stats.EDU = min(99, stats.EDU + cfg["edu_bonuses"][tier])


# ═══════════════════════════════════════════════════════════════
#  信用评级
# ═══════════════════════════════════════════════════════════════

def get_credit_level(value: int) -> str:
    """根据信用评级数值返回等级描述(表: game_config.credit_rating_table)。"""
    table = sorted(get_game_config()["credit_rating_table"])
    result = table[0][1] if table else "身无分文"
    for threshold, label in table:
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
        damage=get_game_config()["unarmed_damage"],
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


# ═══════════════════════════════════════════════════════════════
#  数值参数中心（data/game_config.json，见 2026-08-21 spec §5）
# ═══════════════════════════════════════════════════════════════

_GAME_CONFIG_DEFAULTS = {
    "mp_recovery_per_hour": 1,     # MP 每小时恢复点数
    "hp_recovery_per_day": 1,      # HP 每日自然恢复（跨日界结算，COC7）
    "san_recovery_per_day": 0,     # SAN 每日自然恢复（默认 0=不恢复；COC7 无自然恢复）
    "timed_default_minutes": 30,   # timed 原子缺省持续分钟
    "buff_damage_floor": 0,        # 战斗 buff 减伤后伤害下限
    "stat_roll_multiplier": 5,     # 属性掷骰总乘数(U9: 3D6*5 / (2D6+6)*5)
    "skill_value_cap": 99,         # 技能值上限
    "unarmed_damage": "1D3+DB",    # 默认徒手武器伤害
    "derived": {                   # 衍生公式参数(除数/基数)
        "hp_divisor": 3, "mp_divisor": 5, "dodge_divisor": 2, "san_max_base": 99,
    },
    "db_build_table": [            # DB/BUILD 查表(键=STR+CON//2,max_key None=兜底行)
        {"max_key": 64, "db": "-2", "build": -2},
        {"max_key": 84, "db": "-1", "build": -1},
        {"max_key": 124, "db": "0", "build": 0},
        {"max_key": 164, "db": "+1D4", "build": 1},
        {"max_key": 204, "db": "+1D6", "build": 2},
        {"max_key": None, "db": "+2D6", "build": 3},
    ],
    "age_modifiers": {             # 年龄修正(start_age 起每 10 年一档)
        "start_age": 40, "max_tier": 4,
        "app_penalties": [-5, -10, -15, -20, -25],
        "phys_penalties": [0, -5, -10, -20, -40],
        "edu_bonuses": [5, 10, 15, 20, 25],
    },
    "credit_rating_table": [       # 信用评级 [阈值, 标签](升序)
        [0, "身无分文"], [5, "拮据"], [10, "一般"], [20, "中等"],
        [30, "宽裕"], [50, "富裕"], [70, "富有"], [90, "极富"],
    ],
}
_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "game_config.json")
_game_config_cache: dict | None = None


def reset_game_config_cache() -> None:
    """测试用:清空配置缓存。"""
    global _game_config_cache
    _game_config_cache = None


def _cfg_shape_ok(v, dv) -> bool:
    """嵌套配置形状校验:dict 必需键齐全递归;list 非空且按首元素模板深校验行
    (行内 dict 键齐全、标量类型匹配或 None;list 行等长逐位类型)。"""
    if type(v) is not type(dv):
        return False
    if isinstance(dv, dict):
        return all(k in v and _cfg_shape_ok(v[k], dv[k]) for k in dv)
    if isinstance(dv, list):
        if not v:
            return False
        t0 = dv[0]
        if isinstance(t0, dict):
            return all(
                isinstance(a, dict) and all(
                    k in a and (a[k] is None or type(a[k]) is type(t0[k]))
                    for k in t0)
                for a in v)
        if isinstance(t0, list):
            return all(
                isinstance(a, list) and len(a) == len(t0) and all(
                    type(x) is type(y) for x, y in zip(a, t0))
                for a in v)
        return all(type(a) is type(t0) for a in v)
    return True


def get_game_config() -> dict:
    """惰性加载 game_config.json,缺省兜底,模块级缓存(返回副本)。"""
    global _game_config_cache
    if _game_config_cache is None:
        cfg = dict(_GAME_CONFIG_DEFAULTS)
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
            for k, dv in _GAME_CONFIG_DEFAULTS.items():
                v = data.get(k, dv)
                if _cfg_shape_ok(v, dv):
                    cfg[k] = v
        except (OSError, ValueError):
            pass
        _game_config_cache = cfg
    return copy.deepcopy(_game_config_cache)
