# COC 7th 车卡模拟器 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 COC 7 版调查员车卡系统：数据模型 + 规则引擎 + JSON 序列化 + 前端车卡页面，替代现有 Player 桩类。

**Architecture:** `src/investigator/` 包（models / rules / serialization）负责数据与规则，`frontend/` 纯静态页面负责角色创建，JSON 文件作为两者之间的解耦接口。掷骰函数提升到 `src/utils.py` 供全局复用。

**Tech Stack:** Python 3.10+ (dataclasses), HTML/CSS/JS (vanilla, no framework)

---

## 文件规划

| 文件 | 操作 | 职责 |
|------|------|------|
| `src/utils.py` | 修改 | 新增 `roll_dice()` / `roll_d6()` |
| `src/investigator/__init__.py` | 创建 | 公开 API 导出 |
| `src/investigator/models.py` | 创建 | 数据类：Stats, DerivedStats, Skill, Occupation, Weapon, Investigator |
| `src/investigator/rules.py` | 创建 | COC 7th 规则纯函数 |
| `src/investigator/serialization.py` | 创建 | JSON 序列化/反序列化 |
| `data/occupations.json` | 创建 | COC 7th 标准职业数据 |
| `src/scenario_core.py` | 修改 | 移除 Player，set_player 接受 Investigator，新增 load_player |
| `src/prompts.py` | 修改 | `_build_player_skills` 适配 Investigator |
| `frontend/character.html` | 创建 | 车卡页面结构 |
| `frontend/character.js` | 创建 | 车卡交互逻辑 |
| `frontend/character.css` | 创建 | COC 1920s 风格样式 |

---

### Task 1: 添加公用掷骰函数到 utils.py

**Files:**
- Modify: `src/utils.py`

- [ ] **Step 1: 在 utils.py 末尾添加掷骰函数**

```python
# 在 src/utils.py 文件末尾追加以下内容


# ── 掷骰 ──

def roll_dice(num: int, sides: int) -> int:
    """投 num 个 sides 面骰子求和"""
    import random
    return sum(random.randint(1, sides) for _ in range(num))


def roll_d6(num: int) -> int:
    """投 num 个 6 面骰子求和"""
    return roll_dice(num, 6)
```

- [ ] **Step 2: 验证导入**

Run: `cd src && python -c "from utils import roll_dice, roll_d6; print(roll_d6(3)); print(roll_dice(2, 10))"`
Expected: 两次随机整数输出，roll_d6(3) 输出 3-18，roll_dice(2, 10) 输出 2-20

- [ ] **Step 3: Commit**

```bash
git add src/utils.py
git commit -m "feat: add roll_dice and roll_d6 to utils"
```

---

### Task 2: 创建 investigator 包与数据模型

**Files:**
- Create: `src/investigator/__init__.py`
- Create: `src/investigator/models.py`

- [ ] **Step 1: 创建 __init__.py**

```python
# src/investigator/__init__.py
"""COC 7th 调查员车卡系统 —— 数据模型、规则引擎、序列化"""

from investigator.models import (
    Stats,
    DerivedStats,
    Skill,
    Occupation,
    Weapon,
    Investigator,
)
from investigator.serialization import (
    to_json,
    from_json,
    to_dict,
    from_dict,
)

__all__ = [
    "Stats",
    "DerivedStats",
    "Skill",
    "Occupation",
    "Weapon",
    "Investigator",
    "to_json",
    "from_json",
    "to_dict",
    "from_dict",
]
```

- [ ] **Step 2: 创建 models.py**

```python
# src/investigator/models.py
"""COC 7th 调查员数据模型"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


@dataclass
class Stats:
    """八项核心属性 + LUCK（COC 7th）"""
    STR: int = 0   # 力量   (3D6*5)
    CON: int = 0   # 体质   (3D6*5)
    SIZ: int = 0   # 体型   (2D6+6)*5
    DEX: int = 0   # 敏捷   (3D6*5)
    APP: int = 0   # 外貌   (3D6*5)
    INT: int = 0   # 智力   (2D6+6)*5
    POW: int = 0   # 意志   (3D6*5)
    EDU: int = 0   # 教育   (2D6+6)*5
    LUCK: int = 0  # 幸运   (3D6*5)


@dataclass
class DerivedStats:
    """衍生属性（从核心属性计算得出）"""
    HP: int = 0          # 生命值 = floor((CON+SIZ)/10)
    MP: int = 0          # 魔法值 = floor(POW/5)
    SAN: int = 0         # 当前理智 = POW (初始)
    SAN_MAX: int = 99    # 最大理智 = 99 - 克苏鲁神话值
    MOV: int = 8         # 移动力 (7/8/9)
    DB: str = "0"        # 伤害加值
    BUILD: int = 0       # 体格
    DODGE: int = 0       # 闪避 = floor(DEX/2)


@dataclass
class Skill:
    """COC 7th 技能"""
    name: str
    base_value: int
    value: int = 0           # 当前值（初始 = 基础值，分配技能点后增长）
    category: str = "通用"    # 战斗 / 社交 / 知识 / 感知 / 操作 / 通用
    is_occupation: bool = False

    def __post_init__(self):
        if self.value == 0:
            self.value = self.base_value


@dataclass
class Occupation:
    """COC 7th 职业定义"""
    name: str
    description: str
    occupation_skills: List[str] = field(default_factory=list)
    credit_rating_min: int = 0
    credit_rating_max: int = 99
    skill_points_formula: str = "EDU*4"  # e.g. "EDU*4", "EDU*2+DEX*2"


@dataclass
class Weapon:
    """武器"""
    name: str
    skill_name: str = "格斗"    # 关联技能名
    damage: str = "1D3+DB"     # 伤害公式
    range: str = "接触"         # 射程
    ammo: int = 0              # 弹药（0 表示不需要）
    malfunction: int = 100     # 故障值


class Investigator:
    """COC 7th 调查员 —— 完全替代旧 Player 类"""

    def __init__(
        self,
        name: str = "Unknown",
        age: int = 20,
        gender: str = "",
        occupation: Optional[Occupation] = None,
        stats: Optional[Stats] = None,
        derived: Optional[DerivedStats] = None,
        skills: Optional[List[Skill]] = None,
        weapons: Optional[List[Weapon]] = None,
        equipment: Optional[List[str]] = None,
        backstory: str = "",
        appearance: str = "",
        personal_description: str = "",
    ):
        self.name = name
        self.age = age
        self.gender = gender
        self.occupation = occupation

        self.stats = stats or Stats()
        self.derived = derived or DerivedStats()

        self.skills: List[Skill] = skills or []
        self.weapons: List[Weapon] = weapons or []
        self.equipment: List[str] = equipment or []

        self.backstory = backstory
        self.appearance = appearance
        self.personal_description = personal_description

    # ── 兼容旧 Player 接口 ──

    @property
    def skills_dict(self) -> Dict[str, int]:
        """返回 {技能名: 当前值} 映射，兼容 game_loop / SkillSystem"""
        return {s.name: s.value for s in self.skills}

    # ── 查询 ──

    def get_skill(self, name: str) -> Optional[Skill]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def get_skill_value(self, name: str) -> int:
        sk = self.get_skill(name)
        return sk.value if sk else 0

    # ── 修改（供未来游戏循环使用）──

    def _recalc_derived(self):
        """级联更新衍生属性。规则函数从 rules 模块导入，避免循环依赖。"""
        from investigator.rules import calc_derived
        cthulhu = self.get_skill_value("克苏鲁神话")
        self.derived = calc_derived(self.stats, self.age, cthulhu)

    def modify_stat(self, name: str, delta: int):
        attr = name.upper()
        if hasattr(self.stats, attr):
            setattr(self.stats, attr, getattr(self.stats, attr) + delta)
            self._recalc_derived()

    def modify_skill(self, name: str, delta: int):
        sk = self.get_skill(name)
        if sk:
            sk.value = max(0, min(99, sk.value + delta))

    def add_item(self, item: str):
        if item not in self.equipment:
            self.equipment.append(item)

    def remove_item(self, item: str):
        if item in self.equipment:
            self.equipment.remove(item)

    def add_weapon(self, w: Weapon):
        self.weapons.append(w)

    def remove_weapon(self, name: str):
        self.weapons = [w for w in self.weapons if w.name != name]

    def __repr__(self):
        occ = self.occupation.name if self.occupation else "无职业"
        return f"Investigator({self.name}, {occ}, age={self.age})"
```

- [ ] **Step 3: 验证导入**

Run: `cd src && python -c "from investigator import Stats, DerivedStats, Skill, Occupation, Weapon, Investigator; i = Investigator(name='测试'); print(i); print(i.skills_dict)"`
Expected: `Investigator(测试, 无职业, age=20)` 和 `{}`

- [ ] **Step 4: Commit**

```bash
git add src/investigator/__init__.py src/investigator/models.py
git commit -m "feat: create investigator package with data models"
```

---

### Task 3: 创建规则引擎

**Files:**
- Create: `src/investigator/rules.py`

- [ ] **Step 1: 创建 rules.py**

```python
# src/investigator/rules.py
"""COC 7th 规则引擎 —— 全部为纯函数"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple, Optional

from utils import roll_d6, roll_dice
from investigator.models import Stats, DerivedStats, Skill, Occupation, Weapon


# ═══════════════════════════════════════════════════════════════
#  属性生成
# ═══════════════════════════════════════════════════════════════

def roll_stats() -> Stats:
    """按 COC 7th 标准规则掷骰生成核心属性"""
    return Stats(
        STR=roll_d6(3) * 5,
        CON=roll_d6(3) * 5,
        SIZ=(roll_d6(2) + 6) * 5,
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

def _calc_db_build(str_siz: int) -> Tuple[str, int]:
    """根据 STR+SIZ 查表返回 (DB, BUILD)"""
    if str_siz <= 64:
        return "-2", -2
    elif str_siz <= 84:
        return "-1", -1
    elif str_siz <= 124:
        return "0", 0
    elif str_siz <= 164:
        return "+1D4", 1
    elif str_siz <= 204:
        return "+1D6", 2
    else:
        return "+2D6", 3  # 简化超大值


def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """根据核心属性 + 年龄 + 克苏鲁神话计算衍生属性"""
    hp = math.floor((stats.CON + stats.SIZ) / 10)
    mp = math.floor(stats.POW / 5)
    san = stats.POW
    san_max = 99 - cthulhu_mythos
    dodge = math.floor(stats.DEX / 2)

    # MOV
    if stats.STR < stats.SIZ and stats.DEX < stats.SIZ:
        mov = 7
    elif stats.STR > stats.SIZ and stats.DEX > stats.SIZ:
        mov = 9
    else:
        mov = 8

    db, build = _calc_db_build(stats.STR + stats.SIZ)

    return DerivedStats(
        HP=hp, MP=mp, SAN=san, SAN_MAX=san_max,
        MOV=mov, DB=db, BUILD=build, DODGE=dodge,
    )


# ═══════════════════════════════════════════════════════════════
#  技能系统
# ═══════════════════════════════════════════════════════════════

# COC 7th 标准技能基础值表
SKILL_BASE_VALUES: Dict[str, int] = {
    "会计": 5, "人类学": 1, "估价": 5, "考古学": 1,
    "魅惑": 15, "攀爬": 20, "计算机使用": 5, "信用评级": 0,
    "克苏鲁神话": 0, "乔装": 5, "汽车驾驶": 20,
    "电气维修": 10, "电子学": 1, "话术": 5, "格斗": 25,
    "枪械": 20, "急救": 30, "历史": 5, "恐吓": 15,
    "跳跃": 20, "外语": 1, "母语": 50, "法律": 5,
    "图书馆使用": 20, "聆听": 20, "锁匠": 1, "机械维修": 10,
    "医学": 1, "博物学": 10, "导航": 10, "神秘学": 5,
    "操作重型机械": 1, "说服": 10, "驾驶": 20, "心理学": 10,
    "精神分析": 1, "骑术": 5, "科学": 1, "妙手": 10,
    "潜行": 20, "侦查": 25, "生存": 10, "游泳": 20,
    "投掷": 20, "追踪": 10,
}

# 技能分类映射
SKILL_CATEGORIES: Dict[str, str] = {
    "会计": "知识", "人类学": "知识", "估价": "知识", "考古学": "知识",
    "魅惑": "社交", "攀爬": "操作", "计算机使用": "知识", "信用评级": "社交",
    "克苏鲁神话": "知识", "乔装": "社交", "汽车驾驶": "操作",
    "电气维修": "操作", "电子学": "知识", "话术": "社交", "格斗": "战斗",
    "枪械": "战斗", "急救": "操作", "历史": "知识", "恐吓": "社交",
    "跳跃": "操作", "外语": "知识", "母语": "知识", "法律": "知识",
    "图书馆使用": "知识", "聆听": "感知", "锁匠": "操作", "机械维修": "操作",
    "医学": "知识", "博物学": "知识", "导航": "知识", "神秘学": "知识",
    "操作重型机械": "操作", "说服": "社交", "驾驶": "操作", "心理学": "感知",
    "精神分析": "知识", "骑术": "操作", "科学": "知识", "妙手": "操作",
    "潜行": "操作", "侦查": "感知", "生存": "操作", "游泳": "操作",
    "投掷": "战斗", "追踪": "感知",
}


def resolve_base_value(base: int, stats: Optional[Stats] = None) -> int:
    """解析技能基础值。int 直接返回（特殊值如 'DEX/2' 已在表中直接以数值存储）"""
    return base


def create_skill_list() -> List[Skill]:
    """从基础值表生成完整技能列表"""
    skills = []
    for name, base in SKILL_BASE_VALUES.items():
        category = SKILL_CATEGORIES.get(name, "通用")
        skills.append(Skill(
            name=name,
            base_value=base,
            value=base,
            category=category,
        ))
    return skills


def allocate_skill_points(
    skills: List[Skill],
    occupation_skills: List[str],
    occupation_points: int,
    interest_points: int,
) -> List[Skill]:
    """
    分配技能点（自动平均分配）。
    - occupation_points: 职业技能点，仅可分配到职业技能
    - interest_points: 兴趣技能点，可分配到任意技能
    返回更新后的技能列表（原位修改）。
    """
    occ_skills = [s for s in skills if s.name in occupation_skills]
    int_skills = [s for s in skills if s.name not in occupation_skills]

    if occ_skills:
        per_occ = occupation_points // len(occ_skills)
        remainder = occupation_points % len(occ_skills)
        for i, sk in enumerate(occ_skills):
            sk.value = min(99, sk.base_value + per_occ + (1 if i < remainder else 0))

    if int_skills:
        per_int = interest_points // len(int_skills)
        remainder = interest_points % len(int_skills)
        for i, sk in enumerate(int_skills):
            sk.value = min(99, sk.base_value + per_int + (1 if i < remainder else 0))

    return skills


def calc_occupation_points(formula: str, stats: Stats) -> int:
    """根据职业公式计算职业技能点数。e.g. 'EDU*4' → stats.EDU * 4"""
    try:
        # 简单公式解析：EDU*4 或 EDU*2+DEX*2
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

def apply_age_modifiers(stats: Stats, skills: List[Skill], age: int):
    """
    COC 7th 年龄修正（原位修改）。
    - 15-19: STR/SIZ-5, EDU-5 (已由骰子调整)
    - 40-49: APP-5, MOV-1, EDU+5
    - 50-59: APP-10, MOV-1, STR/CON/DEX-5, EDU+10
    - 60-69: APP-15, MOV-2, STR/CON/DEX-10, EDU+15
    - 70-79: APP-20, MOV-3, STR/CON/DEX-20, EDU+20
    - 80+: APP-25, MOV-4, STR/CON/DEX-40, EDU+25
    """
    if age < 40:
        return

    tier = (age - 40) // 10
    if tier > 4:
        tier = 4

    app_penalty = -5 * (tier + 1)
    mov_penalty = -1 * (tier + 1)
    phys_penalty = -5 * (tier + 1) if tier >= 1 else 0
    edu_bonus = 5 * (tier + 1)

    stats.APP = max(0, stats.APP + app_penalty)
    if phys_penalty:
        stats.STR = max(0, stats.STR + phys_penalty)
        stats.CON = max(0, stats.CON + phys_penalty)
        stats.DEX = max(0, stats.DEX + phys_penalty)
    stats.EDU = min(99, stats.EDU + edu_bonus)

    # EDU 增加 → 额外职业技能点通过 EDU 衍生公式自动反映


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


def create_default_dodge_skill(stats: Stats) -> Skill:
    """创建闪避技能（基础值 = DEX/2）"""
    dodge_base = math.floor(stats.DEX / 2)
    return Skill(
        name="闪避",
        base_value=dodge_base,
        value=dodge_base,
        category="战斗",
    )
```

- [ ] **Step 2: 验证规则引擎导入和基本功能**

Run: `cd src && python -c "
from investigator.rules import roll_stats, calc_derived, create_skill_list, calc_occupation_points, SKILL_BASE_VALUES
s = roll_stats()
d = calc_derived(s)
sk = create_skill_list()
pts = calc_occupation_points('EDU*4', s)
print(f'Stats: STR={s.STR}')
print(f'Derived: HP={d.HP} MP={d.MP}')
print(f'Skills count: {len(sk)}')
print(f'Occ points: {pts}')
"`
Expected: 随机属性输出，衍生属性正确计算。技能列表 ~45 项。职业点 = EDU * 4。

- [ ] **Step 3: Commit**

```bash
git add src/investigator/rules.py
git commit -m "feat: add COC 7th rules engine (stats, derived, skills, combat)"
```

---

### Task 4: 创建序列化模块

**Files:**
- Create: `src/investigator/serialization.py`

- [ ] **Step 1: 创建 serialization.py**

```python
# src/investigator/serialization.py
"""JSON 序列化 / 反序列化"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Any

from investigator.models import (
    Stats, DerivedStats, Skill, Occupation, Weapon, Investigator,
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
            "version": "1.0",
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
        },
        "stats": {
            "STR": inv.stats.STR, "CON": inv.stats.CON, "SIZ": inv.stats.SIZ,
            "DEX": inv.stats.DEX, "APP": inv.stats.APP, "INT": inv.stats.INT,
            "POW": inv.stats.POW, "EDU": inv.stats.EDU, "LUCK": inv.stats.LUCK,
        },
        "derived": {
            "HP": inv.derived.HP, "MP": inv.derived.MP,
            "SAN": inv.derived.SAN, "SAN_MAX": inv.derived.SAN_MAX,
            "MOV": inv.derived.MOV, "DB": inv.derived.DB,
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
        "equipment": list(inv.equipment),
        "backstory": inv.backstory,
    }


def to_json(inv: Investigator, path: str) -> None:
    """导出 Investigator 为 JSON 文件"""
    data = to_dict(inv)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: 继续 serialization.py — from_dict 和 from_json**

```python
# 在 serialization.py 末尾追加


def from_dict(data: dict) -> Investigator:
    """dict → Investigator"""
    personal = data.get("personal", {})
    stats_data = data.get("stats", {})
    derived_data = data.get("derived", {})
    skills_data = data.get("skills", [])
    combat_data = data.get("combat", {})

    occ = None
    occ_data = personal.get("occupation")
    if occ_data and isinstance(occ_data, dict):
        occ = _occupation_dict_to_obj(occ_data)

    stats = Stats(
        STR=stats_data.get("STR", 0), CON=stats_data.get("CON", 0),
        SIZ=stats_data.get("SIZ", 0), DEX=stats_data.get("DEX", 0),
        APP=stats_data.get("APP", 0), INT=stats_data.get("INT", 0),
        POW=stats_data.get("POW", 0), EDU=stats_data.get("EDU", 0),
        LUCK=stats_data.get("LUCK", 0),
    )

    derived = DerivedStats(
        HP=derived_data.get("HP", 0), MP=derived_data.get("MP", 0),
        SAN=derived_data.get("SAN", 0), SAN_MAX=derived_data.get("SAN_MAX", 99),
        MOV=derived_data.get("MOV", 8), DB=derived_data.get("DB", "0"),
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
    )
    return inv


def from_json(path: str) -> Investigator:
    """从 JSON 文件加载 Investigator"""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return from_dict(data)
```

- [ ] **Step 3: 验证序列化 round-trip**

Run: `cd src && python -c "
from investigator.rules import roll_stats, calc_derived, create_skill_list
from investigator.models import Investigator
from investigator.serialization import to_dict, from_dict
import tempfile, os

s = roll_stats()
d = calc_derived(s)
sk = create_skill_list()
inv = Investigator(name='测试', age=25, stats=s, derived=d, skills=sk)

data = to_dict(inv)
inv2 = from_dict(data)
print(f'Round-trip: {inv.name} -> {inv2.name}')
print(f'Stats match: {inv.stats == inv2.stats}')
print(f'Skills match: {len(inv.skills)} vs {len(inv2.skills)}')
print('OK')
"`
Expected: Round-trip name matches, stats match, skills count match, "OK"

- [ ] **Step 4: 验证 JSON 文件导出**

Run: `cd src && python -c "
from investigator.rules import roll_stats, calc_derived, create_skill_list
from investigator.models import Investigator
from investigator.serialization import to_json, from_json
import tempfile, os

inv = Investigator(name='亚楠', age=20, gender='女',
                   stats=roll_stats(),
                   skills=create_skill_list(),
                   backstory='一段背景故事')
inv.derived = calc_derived(inv.stats, inv.age)

tmp = tempfile.mktemp(suffix='.json')
to_json(inv, tmp)
inv2 = from_json(tmp)
print(f'Name: {inv2.name}')
print(f'HP: {inv2.derived.HP}')
print(f'Skills: {len(inv2.skills)}')
os.unlink(tmp)
print('JSON export/import OK')
"`
Expected: 正确输出带中文名的角色、衍生属性、技能数量

- [ ] **Step 5: Commit**

```bash
git add src/investigator/serialization.py
git commit -m "feat: add JSON serialization/deserialization for Investigator"
```

---

### Task 5: 创建 occupations.json 数据文件 + 加载工具

**Files:**
- Create: `data/occupations.json`

- [ ] **Step 1: 创建 data/occupations.json**

```json
[
  {
    "name": "学生",
    "description": "大学生、研究生或学徒",
    "occupation_skills": ["图书馆使用", "外语", "母语", "历史", "科学", "计算机使用", "心理学"],
    "credit_rating_min": 5,
    "credit_rating_max": 10,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "私家侦探",
    "description": "接受委托调查案件的私人调查员",
    "occupation_skills": ["侦查", "追踪", "图书馆使用", "心理学", "法律", "潜行", "摄影", "格斗"],
    "credit_rating_min": 10,
    "credit_rating_max": 30,
    "skill_points_formula": "EDU*2+DEX*2"
  },
  {
    "name": "医生",
    "description": "执业医师、外科医生、精神科医生等",
    "occupation_skills": ["急救", "医学", "心理学", "精神分析", "科学", "说服"],
    "credit_rating_min": 30,
    "credit_rating_max": 80,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "教授",
    "description": "大学或研究机构的学者",
    "occupation_skills": ["图书馆使用", "母语", "外语", "历史", "考古学", "神秘学", "心理学", "说服"],
    "credit_rating_min": 20,
    "credit_rating_max": 70,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "记者",
    "description": "报纸、杂志或电台记者",
    "occupation_skills": ["图书馆使用", "聆听", "说服", "心理学", "母语", "潜行", "摄影"],
    "credit_rating_min": 5,
    "credit_rating_max": 50,
    "skill_points_formula": "EDU*2+APP*2"
  },
  {
    "name": "警察",
    "description": "警员、探员",
    "occupation_skills": ["格斗", "枪械", "法律", "聆听", "心理学", "侦查", "追踪", "汽车驾驶"],
    "credit_rating_min": 10,
    "credit_rating_max": 40,
    "skill_points_formula": "EDU*2+DEX*2"
  },
  {
    "name": "古董商",
    "description": "经营古董店的商人",
    "occupation_skills": ["估价", "历史", "考古学", "图书馆使用", "神秘学", "说服", "话术"],
    "credit_rating_min": 20,
    "credit_rating_max": 60,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "神职人员",
    "description": "牧师、神父、修道士等",
    "occupation_skills": ["母语", "外语", "历史", "图书馆使用", "神秘学", "说服", "心理学"],
    "credit_rating_min": 5,
    "credit_rating_max": 30,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "工程师",
    "description": "机械、电气、土木工程师",
    "occupation_skills": ["机械维修", "电气维修", "科学", "图书馆使用", "计算机使用", "操作重型机械"],
    "credit_rating_min": 20,
    "credit_rating_max": 60,
    "skill_points_formula": "EDU*4"
  },
  {
    "name": "罪犯",
    "description": "职业罪犯、黑帮成员",
    "occupation_skills": ["格斗", "枪械", "恐吓", "潜行", "锁匠", "妙手", "驾驶"],
    "credit_rating_min": 0,
    "credit_rating_max": 20,
    "skill_points_formula": "EDU*2+DEX*2"
  },
  {
    "name": "自由职业/自定义",
    "description": "自行定义职业技能",
    "occupation_skills": [],
    "credit_rating_min": 0,
    "credit_rating_max": 99,
    "skill_points_formula": "EDU*4"
  }
]
```

- [ ] **Step 2: 在 rules.py 中添加 occupations 加载函数**

在 `src/investigator/rules.py` 末尾追加：

```python
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
```

- [ ] **Step 3: 验证 occupations 加载**

Run: `cd src && python -c "from investigator.rules import load_occupations; occs = load_occupations('../data/occupations.json'); [print(f'{o.name}: {len(o.occupation_skills)} skills') for o in occs]"`
Expected: 列出 11 个职业及其技能数量

- [ ] **Step 4: Commit**

```bash
git add data/occupations.json src/investigator/rules.py
git commit -m "feat: add COC 7th occupation data and loader"
```

---

### Task 6: 替换 Player 类并适配 ScenarioWorld

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 移除 Player 类，修改 set_player 和新增 load_player**

对 `src/scenario_core.py` 做以下修改：

**修改 1** — 文件顶部追加导入：

在 `from dataclasses import dataclass, field` 之后添加：
```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from investigator.models import Investigator as InvestigatorType
```

**修改 2** — 删除 Player 类（line 212-216）：

删除：
```python
class Player:
    """简易角色类"""
    def __init__(self, name: str, skills: Dict[str, int] = None):
        self.name = name
        self.skills = skills or {}   # 技能名 → 技能值（0-100）
```

**修改 3** — 修改 ScenarioWorld.set_player（line 336-337）：

将：
```python
def set_player(self, player: Player):
    self.player = player
```

改为：
```python
def set_player(self, player: 'InvestigatorType'):
    """设置调查员角色。接受 investigator.Investigator 实例。"""
    self.player = player

def load_player(self, path: str):
    """从 JSON 文件加载调查员"""
    from investigator.serialization import from_json
    self.player = from_json(path)
```

**修改 4** — 修改 ScenarioWorld.__init__ 中的 player 类型注解（line 306）：

将：
```python
self.player: Optional[Player] = None
```

改为：
```python
self.player: 'InvestigatorType | None' = None
```

注意：`Optional` 仍在 imports 中保留（其他地方使用）。

**修改 5** — 更新文件顶部 docstring：

将 `玩家` 改为 `调查员`（描述性修改，非必须）。

- [ ] **Step 2: 验证 ScenarioWorld 集成**

Run: `cd src && python -c "
from investigator import Investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list
from scenario_core import DirectedGraph, ScenarioWorld

inv = Investigator(name='Test', stats=roll_stats())
inv.derived = calc_derived(inv.stats)
inv.skills = create_skill_list()

graph = DirectedGraph()
world = ScenarioWorld(graph, start_node='test')
world.set_player(inv)

print(f'Player type: {type(world.player).__name__}')
print(f'Name: {world.player.name}')
print(f'HP: {world.player.derived.HP}')
print(f'OK')
"`
Expected: `Investigator`, name, HP printed correctly

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: replace Player with Investigator in ScenarioWorld"
```

---

### Task 7: 适配 prompts.py 的 _build_player_skills

**Files:**
- Modify: `src/prompts.py`

- [ ] **Step 1: 修改 _build_player_skills 函数**

将 `src/prompts.py` 第 226-230 行：

```python
def _build_player_skills(world: ScenarioWorld) -> str:
    """构建玩家技能列表"""
    if not world.player or not world.player.skills:
        return "（无技能数据）"
    return ", ".join(f"{name}={value}" for name, value in world.player.skills.items())
```

改为：

```python
def _build_player_skills(world: ScenarioWorld) -> str:
    """构建玩家技能列表（从 Investigator.skills）"""
    if not world.player or not world.player.skills:
        return "（无技能数据）"
    return ", ".join(f"{s.name}={s.value}" for s in world.player.skills)
```

- [ ] **Step 2: 验证**

Run: `cd src && python -c "
from investigator import Investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list
from scenario_core import DirectedGraph, ScenarioWorld
from prompts import _build_player_skills

inv = Investigator(name='Test', stats=roll_stats())
inv.derived = calc_derived(inv.stats)
inv.skills = create_skill_list()

graph = DirectedGraph()
world = ScenarioWorld(graph, start_node='test')
world.set_player(inv)

result = _build_player_skills(world)
print(result[:200])
"`
Expected: 输出技能名=技能值的逗号分隔列表，长度合理

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "fix: adapt _build_player_skills to Investigator interface"
```

---

### Task 8: 创建前端车卡页面 — HTML + CSS

**Files:**
- Create: `frontend/character.html`
- Create: `frontend/character.css`

- [ ] **Step 1: 创建 character.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>COC 7th 调查员创建 — 车卡模拟器</title>
<link rel="stylesheet" href="character.css">
</head>
<body>

<div id="app">
  <header>
    <h1>《克苏鲁的呼唤》7版 调查员创建</h1>
  </header>

  <!-- 进度指示器 -->
  <div id="progress">
    <span class="step active" data-step="1">1. 基本信息</span>
    <span class="step" data-step="2">2. 属性生成</span>
    <span class="step" data-step="3">3. 职业与技能</span>
    <span class="step" data-step="4">4. 战斗与装备</span>
    <span class="step" data-step="5">5. 导出</span>
  </div>

  <!-- 步骤面板 -->
  <div id="step-1" class="panel active">
    <h2>基本信息</h2>
    <div class="form-group">
      <label>调查员姓名</label>
      <input type="text" id="char-name" placeholder="例如：亚楠" value="">
    </div>
    <div class="form-group">
      <label>年龄</label>
      <input type="number" id="char-age" min="15" max="99" value="25">
    </div>
    <div class="form-group">
      <label>性别</label>
      <select id="char-gender">
        <option value="">选择...</option>
        <option value="男">男</option>
        <option value="女">女</option>
        <option value="其他">其他</option>
      </select>
    </div>
    <div class="form-group">
      <label>外貌描述</label>
      <textarea id="char-appearance" rows="2" placeholder="简要描述外貌特征..."></textarea>
    </div>
    <div class="form-group">
      <label>个人描述</label>
      <textarea id="char-description" rows="2" placeholder="一句话概括角色..."></textarea>
    </div>
    <div class="buttons">
      <button onclick="nextStep()">下一步 →</button>
    </div>
  </div>

  <div id="step-2" class="panel">
    <h2>属性生成</h2>
    <div class="buttons-top">
      <button onclick="rollAllStats()" class="primary">&#x1F3B2; 掷骰生成</button>
      <button onclick="toggleManualInput()">手动输入模式</button>
    </div>
    <div id="stats-display">
      <!-- JS 动态填充 -->
    </div>
    <div class="buttons">
      <button onclick="prevStep()">← 上一步</button>
      <button onclick="nextStep()">下一步 →</button>
    </div>
  </div>

  <div id="step-3" class="panel">
    <h2>职业与技能</h2>
    <div class="form-group">
      <label>职业选择</label>
      <select id="occ-select">
        <option value="">选择职业...</option>
        <!-- JS 动态填充 -->
      </select>
    </div>
    <div id="occ-detail">
      <p id="occ-desc"></p>
      <p>技能点公式：<span id="occ-formula"></span></p>
      <p>职业技能点：<span id="occ-points">0</span> | 兴趣技能点：<span id="int-points">0</span></p>
    </div>
    <div id="skills-display">
      <!-- JS 动态填充 -->
    </div>
    <div class="buttons">
      <button onclick="prevStep()">← 上一步</button>
      <button onclick="nextStep()">下一步 →</button>
    </div>
  </div>

  <div id="step-4" class="panel">
    <h2>战斗与装备</h2>
    <h3>武器</h3>
    <div id="weapons-list">
      <!-- JS 动态填充 -->
    </div>
    <button onclick="addWeapon()" class="secondary">+ 添加武器</button>

    <h3>随身物品</h3>
    <div class="form-group">
      <input type="text" id="equip-input" placeholder="输入物品名称后按回车添加">
    </div>
    <div id="equipment-list">
      <!-- JS 动态填充 -->
    </div>

    <div class="buttons">
      <button onclick="prevStep()">← 上一步</button>
      <button onclick="nextStep()">下一步 →</button>
    </div>
  </div>

  <div id="step-5" class="panel">
    <h2>角色卡预览 & 导出</h2>
    <div class="form-group">
      <label>背景故事</label>
      <textarea id="char-backstory" rows="4" placeholder="输入调查员背景故事..."></textarea>
    </div>
    <h3>角色卡摘要</h3>
    <pre id="summary-display">请填写前 4 步信息后查看摘要。</pre>
    <div class="buttons">
      <button onclick="prevStep()">← 上一步</button>
      <button onclick="exportJSON()" class="primary">导出 JSON</button>
    </div>
  </div>
</div>

<script src="character.js"></script>
</body>
</html>
```

- [ ] **Step 2: 创建 character.css**

```css
/* COC 1920s 美学 — 暗旧纸张色调，衬线字体 */

@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700&display=swap');

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: 'Noto Serif SC', 'SimSun', 'STSong', serif;
  background: #1a1a1a;
  color: #d4c5a0;
  min-height: 100vh;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 2rem 1rem;
}

#app {
  max-width: 720px;
  width: 100%;
  background: linear-gradient(180deg, #2a2418 0%, #1f1a10 100%);
  border: 1px solid #4a3820;
  border-radius: 4px;
  box-shadow: 0 0 40px rgba(0,0,0,0.5), inset 0 0 80px rgba(0,0,0,0.3);
  padding: 2rem;
}

header {
  text-align: center;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid #4a3820;
  padding-bottom: 1rem;
}

header h1 {
  font-size: 1.5rem;
  font-weight: 700;
  color: #c9a84c;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

/* 进度条 */
#progress {
  display: flex;
  justify-content: space-between;
  margin-bottom: 2rem;
  border-bottom: 2px solid #3a2810;
  padding-bottom: 0.5rem;
}

#progress .step {
  font-size: 0.8rem;
  color: #6a5840;
  transition: color 0.3s;
}

#progress .step.active {
  color: #c9a84c;
  font-weight: 600;
}

/* 面板切换 */
.panel { display: none; }
.panel.active { display: block; }

h2 {
  font-size: 1.2rem;
  color: #c9a84c;
  margin-bottom: 1.2rem;
  border-left: 3px solid #c9a84c;
  padding-left: 0.8rem;
}

h3 {
  font-size: 1rem;
  color: #b89a40;
  margin: 1rem 0 0.5rem;
}

/* 表单 */
.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  font-size: 0.85rem;
  color: #9a8860;
  margin-bottom: 0.25rem;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: #1a150c;
  border: 1px solid #4a3820;
  border-radius: 2px;
  color: #d4c5a0;
  font-family: inherit;
  font-size: 0.95rem;
}

.form-group textarea { resize: vertical; min-height: 60px; }

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #c9a84c;
  box-shadow: 0 0 6px rgba(201,168,76,0.2);
}

/* 按钮 */
.buttons {
  margin-top: 1.5rem;
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
}

.buttons-top {
  margin-bottom: 1rem;
  display: flex;
  gap: 0.75rem;
}

button {
  padding: 0.5rem 1.5rem;
  border: 1px solid #4a3820;
  border-radius: 2px;
  background: #2a2418;
  color: #d4c5a0;
  font-family: inherit;
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s;
}

button:hover {
  background: #3a3018;
  border-color: #c9a84c;
}

button.primary {
  background: #3a2810;
  border-color: #8a6820;
  color: #f0d878;
}

button.primary:hover {
  background: #4a3818;
}

button.secondary {
  font-size: 0.85rem;
  padding: 0.35rem 0.75rem;
}

/* 属性卡片 */
#stats-display {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.75rem;
}

.stat-card {
  background: #1a150c;
  border: 1px solid #3a2810;
  border-radius: 2px;
  padding: 0.6rem;
  text-align: center;
}

.stat-card .stat-name {
  font-size: 0.75rem;
  color: #9a8860;
}

.stat-card .stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #c9a84c;
}

.stat-card input.stat-value-input {
  width: 60px;
  text-align: center;
  font-size: 1.2rem;
  padding: 0.2rem;
  background: #0d0a05;
  border: 1px solid #4a3820;
  color: #c9a84c;
  font-family: inherit;
  display: none;
}

.stat-card.manual .stat-value { display: none; }
.stat-card.manual .stat-value-input { display: inline-block; }

/* 衍生属性 */
#derived-display {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #1a150c;
  border: 1px solid #3a2810;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
  text-align: center;
}

.derived-item .derived-label {
  font-size: 0.7rem;
  color: #7a6840;
}

.derived-item .derived-value {
  font-size: 1.1rem;
  font-weight: 600;
  color: #d4c5a0;
}

/* 技能列表 */
#skills-display {
  margin-top: 1rem;
}

.skill-row {
  display: flex;
  align-items: center;
  padding: 0.4rem 0;
  border-bottom: 1px solid #1a150c;
  font-size: 0.85rem;
}

.skill-row.occupation {
  background: #1a1204;
}

.skill-row .skill-name {
  flex: 1;
  color: #d4c5a0;
}

.skill-row.occupation .skill-name::before {
  content: "● ";
  color: #c9a84c;
  font-size: 0.6rem;
}

.skill-row .skill-category {
  width: 48px;
  font-size: 0.7rem;
  color: #7a6840;
}

.skill-row .skill-base {
  width: 36px;
  text-align: center;
  color: #6a5840;
}

.skill-row .skill-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  font-size: 0.9rem;
  text-align: center;
  line-height: 28px;
  background: #1a150c;
  border: 1px solid #3a2810;
  color: #c9a84c;
  cursor: pointer;
  border-radius: 2px;
}

.skill-row .skill-btn:hover {
  background: #3a2810;
}

.skill-row input.skill-value {
  width: 48px;
  text-align: center;
  background: #0d0a05;
  border: 1px solid #3a2810;
  color: #c9a84c;
  font-family: inherit;
  font-size: 0.85rem;
  padding: 0.15rem;
  margin: 0 0.25rem;
}

.skill-points {
  font-size: 0.8rem;
  color: #9a8860;
  margin-left: 0.5rem;
}

/* 武器 / 装备 */
#weapons-list .weapon-row,
#equipment-list .item-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem;
  background: #1a150c;
  border: 1px solid #3a2810;
  margin-bottom: 0.35rem;
  border-radius: 2px;
}

.weapon-row input,
.item-row input {
  background: #0d0a05;
  border: 1px solid #4a3820;
  color: #d4c5a0;
  font-family: inherit;
  font-size: 0.85rem;
  padding: 0.25rem 0.4rem;
}

.weapon-row input { flex: 1; }
.weapon-row .short { width: 80px; flex: none; }

.item-row .item-name { flex: 1; color: #d4c5a0; }

.remove-btn {
  background: none;
  border: none;
  color: #8a3820;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0 0.35rem;
}

.remove-btn:hover { color: #c05030; }

/* 摘要 */
#summary-display {
  background: #1a150c;
  border: 1px solid #3a2810;
  padding: 1rem;
  font-family: 'Noto Serif SC', serif;
  font-size: 0.8rem;
  color: #b0a080;
  white-space: pre-wrap;
  max-height: 300px;
  overflow-y: auto;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/character.html frontend/character.css
git commit -m "feat: add character builder frontend HTML and CSS"
```

---

### Task 9: 创建前端车卡 JavaScript 逻辑

**Files:**
- Create: `frontend/character.js`

- [ ] **Step 1: 创建完整的 character.js**

```javascript
// character.js — COC 7th 车卡模拟器
// 纯静态，无框架依赖。角色数据全程存于 builderState，最后一步导出 JSON。

(function() {
'use strict';

// ═══════════════════════════════════════════
//  State
// ═══════════════════════════════════════════

const builderState = {
    currentStep: 1,
    manualMode: false,
    occupations: [],
    skills: [],
    weapons: [],
    equipment: [],
    // COC 7th coefficient tables
    statRolls: {
        STR: { dice: 3, mod: 0, mul: 5 }, CON: { dice: 3, mod: 0, mul: 5 },
        DEX: { dice: 3, mod: 0, mul: 5 }, APP: { dice: 3, mod: 0, mul: 5 },
        POW: { dice: 3, mod: 0, mul: 5 },
        SIZ: { dice: 2, mod: 6, mul: 5 }, INT: { dice: 2, mod: 6, mul: 5 },
        EDU: { dice: 2, mod: 6, mul: 5 }, LUCK: { dice: 3, mod: 0, mul: 5 },
    },
};

// ═══════════════════════════════════════════
//  Dice
// ═══════════════════════════════════════════

function rollD6(n) {
    let sum = 0;
    const arr = new Uint32Array(n);
    crypto.getRandomValues(arr);
    for (let i = 0; i < n; i++) sum += (arr[i] % 6) + 1;
    return sum;
}

// ═══════════════════════════════════════════
//  Derived stats
// ═══════════════════════════════════════════

function calcDerived(stats, age) {
    const CON = stats.CON || 0, SIZ = stats.SIZ || 0, POW = stats.POW || 0;
    const DEX = stats.DEX || 0, STR = stats.STR || 0;
    const HP = Math.floor((CON + SIZ) / 10);
    const MP = Math.floor(POW / 5);
    const DODGE = Math.floor(DEX / 2);
    let MOV = 8;
    if (STR < SIZ && DEX < SIZ) MOV = 7;
    else if (STR > SIZ && DEX > SIZ) MOV = 9;
    const ss = STR + SIZ;
    let DB = '0', BUILD = 0;
    if (ss <= 64) { DB = '-2'; BUILD = -2; }
    else if (ss <= 84) { DB = '-1'; BUILD = -1; }
    else if (ss <= 124) { DB = '0'; BUILD = 0; }
    else if (ss <= 164) { DB = '+1D4'; BUILD = 1; }
    else if (ss <= 204) { DB = '+1D6'; BUILD = 2; }
    else { DB = '+2D6'; BUILD = 3; }
    return { HP, MP, SAN: POW, SAN_MAX: 99, MOV, DB, BUILD, DODGE };
}

// ═══════════════════════════════════════════
//  Step navigation
// ═══════════════════════════════════════════

function setStep(n) {
    document.querySelectorAll('.panel').forEach(el => el.classList.remove('active'));
    const panel = document.getElementById('step-' + n);
    if (panel) panel.classList.add('active');
    document.querySelectorAll('#progress .step').forEach(el => {
        el.classList.remove('active');
        if (parseInt(el.dataset.step) === n) el.classList.add('active');
    });
    builderState.currentStep = n;
}

window.nextStep = function() {
    const s = builderState.currentStep;
    if (s === 1) collectPersonal();
    if (s === 2) collectStats();
    if (s === 3) collectSkills();
    if (s === 4) collectCombat();
    if (s === 5) return;
    if (s === 3) renderSkills();
    if (s === 4) renderStep4();
    if (s === 5) renderSummary();
    setStep(s + 1);
};

window.prevStep = function() {
    if (builderState.currentStep > 1) setStep(builderState.currentStep - 1);
};

// ═══════════════════════════════════════════
//  Step 1: Personal info
// ═══════════════════════════════════════════

function collectPersonal() {
    builderState.name = document.getElementById('char-name').value.trim() || 'Unknown';
    builderState.age = parseInt(document.getElementById('char-age').value) || 20;
    builderState.gender = document.getElementById('char-gender').value;
    builderState.appearance = document.getElementById('char-appearance').value.trim();
    builderState.description = document.getElementById('char-description').value.trim();
}

// ═══════════════════════════════════════════
//  Step 2: Stats
// ═══════════════════════════════════════════

window.rollAllStats = function() {
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    names.forEach(name => {
        const cfg = builderState.statRolls[name];
        const val = (rollD6(cfg.dice) + cfg.mod) * cfg.mul;
        builderState[name] = val;
        const card = document.getElementById('stat-' + name);
        if (card) {
            card.querySelector('.stat-value').textContent = val;
            card.querySelector('.stat-value-input').value = val;
        }
    });
    renderDerived();
};

function collectStats() {
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    names.forEach(name => {
        const card = document.getElementById('stat-' + name);
        if (!card) return;
        if (builderState.manualMode) {
            builderState[name] = parseInt(card.querySelector('.stat-value-input').value) || 0;
        } else {
            builderState[name] = parseInt(card.querySelector('.stat-value').textContent) || 0;
        }
    });
}

window.toggleManualInput = function() {
    builderState.manualMode = !builderState.manualMode;
    document.querySelectorAll('.stat-card').forEach(c => {
        c.classList.toggle('manual', builderState.manualMode);
    });
};

function renderDerived() {
    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(n => {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    Object.assign(builderState, { derived: d });
    const el = document.getElementById('derived-display');
    if (!el) return;
    el.innerHTML = [
        ['HP', d.HP], ['MP', d.MP], ['SAN', d.SAN], ['SAN_MAX', d.SAN_MAX],
        ['MOV', d.MOV], ['DB', d.DB], ['BUILD', d.BUILD], ['DODGE', d.DODGE],
    ].map(([label, val]) =>
        '<div class="derived-item"><div class="derived-label">' + label + '</div><div class="derived-value">' + val + '</div></div>'
    ).join('');
}

// ═══════════════════════════════════════════
//  Step 3: Skills
// ═══════════════════════════════════════════

function collectSkills() {
    const rows = document.querySelectorAll('.skill-row');
    builderState.skills = [];
    rows.forEach(row => {
        const nameEl = row.querySelector('.skill-name');
        const valEl = row.querySelector('.skill-value');
        const baseEl = row.querySelector('.skill-base');
        const name = nameEl.textContent.replace(/^● /, '');
        builderState.skills.push({
            name: name,
            base_value: parseInt(baseEl.textContent) || 0,
            value: parseInt(valEl.value) || parseInt(valEl.textContent) || 0,
            category: row.dataset.category || '通用',
            is_occupation: row.classList.contains('occupation'),
        });
    });
}

function renderSkills() {
    const container = document.getElementById('skills-display');
    if (!container) return;
    const occSelect = document.getElementById('occ-select');
    const occName = occSelect ? occSelect.options[occSelect.selectedIndex].text : '';
    const occData = builderState.occupations.find(o => o.name === occName);
    const occSkills = occData ? occData.occupation_skills : [];

    const stats = { EDU: builderState.EDU || 0, DEX: builderState.DEX || 0, APP: builderState.APP || 0, INT: builderState.INT || 0, ...builderState };
    const formula = occData ? occData.skill_points_formula : 'EDU*4';
    let occPoints = parseFormula(formula, stats);
    let intPoints = (stats.INT || 0) * 2;
    builderState.occPointsRemaining = occPoints;
    builderState.intPointsRemaining = intPoints;

    document.getElementById('occ-desc').textContent = occData ? occData.description : '';
    document.getElementById('occ-formula').textContent = formula + ' = ' + occPoints;
    document.getElementById('occ-points').textContent = occPoints;
    document.getElementById('int-points').textContent = intPoints;

    if (!builderState._skillsInitialized) {
        builderState.skills = [];
        SKILL_BASE_VALUES.forEach(function(item) {
            builderState.skills.push({
                name: item.name,
                base_value: item.base,
                value: item.base,
                category: item.category,
                is_occupation: occSkills.includes(item.name),
            });
        });
        builderState._skillsInitialized = true;
    }

    container.innerHTML = builderState.skills.map(function(s, idx) {
        const isOcc = occSkills.includes(s.name);
        const cls = isOcc ? 'skill-row occupation' : 'skill-row';
        return '<div class="' + cls + '" data-idx="' + idx + '" data-category="' + s.category + '">'
            + '<span class="skill-name">' + s.name + '</span>'
            + '<span class="skill-category">' + s.category + '</span>'
            + '<span class="skill-base">' + s.base_value + '</span>'
            + '<button class="skill-btn" onclick="adjustSkill(' + idx + ', -5)">&#x2212;</button>'
            + '<input class="skill-value" value="' + s.value + '" onchange="onSkillChange(' + idx + ', this)">'
            + '<button class="skill-btn" onclick="adjustSkill(' + idx + ', 5)">+</button>'
            + '</div>';
    }).join('');
}

window.adjustSkill = function(idx, delta) {
    const sk = builderState.skills[idx];
    const newVal = Math.max(0, Math.min(99, sk.value + delta));
    updateSkillValue(idx, newVal);
};

window.onSkillChange = function(idx, input) {
    const newVal = Math.max(0, Math.min(99, parseInt(input.value) || 0));
    updateSkillValue(idx, newVal);
};

function updateSkillValue(idx, newVal) {
    const sk = builderState.skills[idx];
    const oldVal = sk.value;
    const cost = newVal - oldVal;
    if (cost > 0) {
        if (sk.is_occupation) {
            if (builderState.occPointsRemaining < cost) return;
            builderState.occPointsRemaining -= cost;
        } else {
            if (builderState.intPointsRemaining < cost) return;
            builderState.intPointsRemaining -= cost;
        }
    } else {
        if (sk.is_occupation) builderState.occPointsRemaining -= cost;
        else builderState.intPointsRemaining -= cost;
    }
    sk.value = newVal;
    document.getElementById('occ-points').textContent = builderState.occPointsRemaining;
    document.getElementById('int-points').textContent = builderState.intPointsRemaining;
    const input = document.querySelector('.skill-row[data-idx="' + idx + '"] .skill-value');
    if (input) input.value = newVal;
}

function parseFormula(formula, stats) {
    try {
        let result = 0;
        const parts = formula.replace('-', '+-').split('+');
        parts.forEach(function(part) {
            part = part.trim();
            if (!part) return;
            if (part.indexOf('*') !== -1) {
                const [attr, mul] = part.split('*');
                result += (stats[attr.trim().toUpperCase()] || 0) * parseInt(mul);
            } else {
                result += stats[part.trim().toUpperCase()] || 0;
            }
        });
        return result;
    } catch(e) { return (stats.EDU || 0) * 4; }
}

// ═══════════════════════════════════════════
//  Step 4: Combat & Equipment
// ═══════════════════════════════════════════

function renderStep4() {
    renderWeapons();
    renderEquipment();
}

function renderWeapons() {
    if (builderState.weapons.length === 0) {
        builderState.weapons.push({ name: '徒手', skill_name: '格斗', damage: '1D3+DB', range: '接触', ammo: 0, malfunction: 100 });
    }
    const container = document.getElementById('weapons-list');
    container.innerHTML = builderState.weapons.map(function(w, i) {
        return '<div class="weapon-row">'
            + '<input value="' + esc(w.name) + '" onchange="wpnSet(' + i + ', \'name\', this.value)" placeholder="武器名">'
            + '<input value="' + esc(w.skill_name) + '" onchange="wpnSet(' + i + ', \'skill_name\', this.value)" placeholder="技能" class="short">'
            + '<input value="' + esc(w.damage) + '" onchange="wpnSet(' + i + ', \'damage\', this.value)" placeholder="伤害" class="short">'
            + '<input value="' + esc(w.range) + '" onchange="wpnSet(' + i + ', \'range\', this.value)" placeholder="射程" class="short">'
            + '<button class="remove-btn" onclick="removeWeapon(' + i + ')">&#x2715;</button>'
            + '</div>';
    }).join('');
}

window.wpnSet = function(i, key, val) { builderState.weapons[i][key] = val; };

window.addWeapon = function() {
    builderState.weapons.push({ name: '', skill_name: '格斗', damage: '1D6', range: '接触', ammo: 0, malfunction: 100 });
    renderWeapons();
};

window.removeWeapon = function(i) {
    builderState.weapons.splice(i, 1);
    renderWeapons();
};

function renderEquipment() {
    const container = document.getElementById('equipment-list');
    container.innerHTML = builderState.equipment.map(function(item, i) {
        return '<div class="item-row"><span class="item-name">' + esc(item) + '</span>'
            + '<button class="remove-btn" onclick="removeEquip(' + i + ')">&#x2715;</button></div>';
    }).join('');
}

window.removeEquip = function(i) {
    builderState.equipment.splice(i, 1);
    renderEquipment();
};

function collectCombat() {
    builderState.weapons = builderState.weapons.filter(function(w) { return w.name.trim(); });
}

// Equipment input handler
document.addEventListener('DOMContentLoaded', function() {
    const equipInput = document.getElementById('equip-input');
    if (equipInput) {
        equipInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && this.value.trim()) {
                builderState.equipment.push(this.value.trim());
                this.value = '';
                renderEquipment();
            }
        });
    }
    // Occupation change handler
    const occSelect = document.getElementById('occ-select');
    if (occSelect) {
        occSelect.addEventListener('change', function() {
            builderState._skillsInitialized = false;
            renderSkills();
        });
    }
    // Init
    loadOccupations();
    renderStatsCards();
    renderDerived();
});

function renderStatsCards() {
    const container = document.getElementById('stats-display');
    const names = ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'];
    const labels = { STR:'力量', CON:'体质', SIZ:'体型', DEX:'敏捷', APP:'外貌', INT:'智力', POW:'意志', EDU:'教育', LUCK:'幸运' };
    container.innerHTML = names.map(function(name) {
        return '<div class="stat-card" id="stat-' + name + '">'
            + '<div class="stat-name">' + labels[name] + ' (' + name + ')</div>'
            + '<div class="stat-value">0</div>'
            + '<input class="stat-value-input" value="0">'
            + '</div>';
    }).join('');
}

// ═══════════════════════════════════════════
//  Step 5: Export
// ═══════════════════════════════════════════

function renderSummary() {
    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(function(n) {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    builderState.derived = d;

    const occSelect = document.getElementById('occ-select');
    const occName = occSelect ? occSelect.options[occSelect.selectedIndex].text : '';
    const occData = builderState.occupations.find(function(o) { return o.name === occName; });

    const summary = '调查员: ' + (builderState.name || '?') + '\n'
        + '职业: ' + occName + ' | 年龄: ' + (builderState.age || '?') + '\n'
        + 'HP: ' + d.HP + ' | MP: ' + d.MP + ' | SAN: ' + d.SAN + ' | MOV: ' + d.MOV + '\n'
        + 'DB: ' + d.DB + ' | BUILD: ' + d.BUILD + ' | DODGE: ' + d.DODGE + '\n'
        + '技能数: ' + (builderState.skills.length) + ' | 武器: ' + builderState.weapons.length + ' | 装备: ' + builderState.equipment.length;
    document.getElementById('summary-display').textContent = summary;
}

window.exportJSON = function() {
    collectPersonal();
    collectStats();
    collectSkills();
    collectCombat();
    builderState.backstory = document.getElementById('char-backstory').value.trim();

    const stats = {};
    ['STR','CON','SIZ','DEX','APP','INT','POW','EDU','LUCK'].forEach(function(n) {
        stats[n] = builderState[n] || 0;
    });
    const d = calcDerived(stats, builderState.age || 20);
    builderState.derived = d;

    const occName = document.getElementById('occ-select').options[document.getElementById('occ-select').selectedIndex].text;
    const occData = builderState.occupations.find(function(o) { return o.name === occName; });

    const data = {
        meta: { version: '1.0', created_at: new Date().toISOString(), rules_edition: 'COC7' },
        personal: {
            name: builderState.name || 'Unknown',
            age: builderState.age || 20,
            gender: builderState.gender || '',
            occupation: occData || null,
            description: builderState.description || '',
            appearance: builderState.appearance || '',
        },
        stats: stats,
        derived: d,
        skills: (builderState.skills || []).map(function(s) {
            return {
                name: s.name, base: s.base_value, value: s.value,
                category: s.category, is_occupation: s.is_occupation,
            };
        }),
        combat: { weapons: builderState.weapons || [] },
        equipment: builderState.equipment || [],
        backstory: builderState.backstory || '',
    };

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = (builderState.name || 'character') + '_character.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
};

// ═══════════════════════════════════════════
//  Occupations loader
// ═══════════════════════════════════════════

function loadOccupations() {
    fetch('../data/occupations.json')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            builderState.occupations = data;
            const sel = document.getElementById('occ-select');
            data.forEach(function(o) {
                const opt = document.createElement('option');
                opt.value = o.name;
                opt.textContent = o.name;
                sel.appendChild(opt);
            });
        })
        .catch(function() {
            // Fallback: hard-coded basic occupations
            builderState.occupations = [
                { name: '学生', description: '', occupation_skills: ['图书馆使用','外语','母语','历史','科学','心理学'], skill_points_formula: 'EDU*4', credit_rating_min: 5, credit_rating_max: 10 },
                { name: '私家侦探', description: '', occupation_skills: ['侦查','追踪','图书馆使用','心理学','法律','潜行','格斗'], skill_points_formula: 'EDU*2+DEX*2', credit_rating_min: 10, credit_rating_max: 30 },
                { name: '医生', description: '', occupation_skills: ['急救','医学','心理学','精神分析','科学','说服'], skill_points_formula: 'EDU*4', credit_rating_min: 30, credit_rating_max: 80 },
                { name: '教授', description: '', occupation_skills: ['图书馆使用','母语','外语','历史','考古学','神秘学','心理学','说服'], skill_points_formula: 'EDU*4', credit_rating_min: 20, credit_rating_max: 70 },
                { name: '记者', description: '', occupation_skills: ['图书馆使用','聆听','说服','心理学','母语','潜行'], skill_points_formula: 'EDU*2+APP*2', credit_rating_min: 5, credit_rating_max: 50 },
            ];
            const sel = document.getElementById('occ-select');
            builderState.occupations.forEach(function(o) {
                const opt = document.createElement('option');
                opt.value = o.name;
                opt.textContent = o.name;
                sel.appendChild(opt);
            });
        });
}

// ═══════════════════════════════════════════
//  Skill base values (mirror of rules.py)
// ═══════════════════════════════════════════

const SKILL_BASE_VALUES = [
    { name: '会计', base: 5, category: '知识' }, { name: '人类学', base: 1, category: '知识' },
    { name: '估价', base: 5, category: '知识' }, { name: '考古学', base: 1, category: '知识' },
    { name: '魅惑', base: 15, category: '社交' }, { name: '攀爬', base: 20, category: '操作' },
    { name: '计算机使用', base: 5, category: '知识' }, { name: '信用评级', base: 0, category: '社交' },
    { name: '克苏鲁神话', base: 0, category: '知识' }, { name: '乔装', base: 5, category: '社交' },
    { name: '汽车驾驶', base: 20, category: '操作' }, { name: '电气维修', base: 10, category: '操作' },
    { name: '电子学', base: 1, category: '知识' }, { name: '话术', base: 5, category: '社交' },
    { name: '格斗', base: 25, category: '战斗' }, { name: '枪械', base: 20, category: '战斗' },
    { name: '急救', base: 30, category: '操作' }, { name: '历史', base: 5, category: '知识' },
    { name: '恐吓', base: 15, category: '社交' }, { name: '跳跃', base: 20, category: '操作' },
    { name: '外语', base: 1, category: '知识' }, { name: '母语', base: 50, category: '知识' },
    { name: '法律', base: 5, category: '知识' }, { name: '图书馆使用', base: 20, category: '知识' },
    { name: '聆听', base: 20, category: '感知' }, { name: '锁匠', base: 1, category: '操作' },
    { name: '机械维修', base: 10, category: '操作' }, { name: '医学', base: 1, category: '知识' },
    { name: '博物学', base: 10, category: '知识' }, { name: '导航', base: 10, category: '知识' },
    { name: '神秘学', base: 5, category: '知识' }, { name: '操作重型机械', base: 1, category: '操作' },
    { name: '说服', base: 10, category: '社交' }, { name: '驾驶', base: 20, category: '操作' },
    { name: '心理学', base: 10, category: '感知' }, { name: '精神分析', base: 1, category: '知识' },
    { name: '骑术', base: 5, category: '操作' }, { name: '科学', base: 1, category: '知识' },
    { name: '妙手', base: 10, category: '操作' }, { name: '潜行', base: 20, category: '操作' },
    { name: '侦查', base: 25, category: '感知' }, { name: '生存', base: 10, category: '操作' },
    { name: '游泳', base: 20, category: '操作' }, { name: '投掷', base: 20, category: '战斗' },
    { name: '追踪', base: 10, category: '感知' },
];

// ═══════════════════════════════════════════
//  Utility
// ═══════════════════════════════════════════

function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

})();
```

- [ ] **Step 2: 验证前端语法**

Run: `node -c frontend/character.js`
Expected: No syntax errors

- [ ] **Step 3: 提交**

```bash
git add frontend/character.js
git commit -m "feat: add character builder JavaScript logic"
```

---

### Task 10: 更新 __init__.py 导出并做最终集成测试

**Files:**
- Modify: `src/investigator/__init__.py`

- [ ] **Step 1: 更新 __init__.py 导出**

将 `src/investigator/__init__.py` 更新为：

```python
# src/investigator/__init__.py
"""COC 7th 调查员车卡系统"""

from investigator.models import (
    Stats,
    DerivedStats,
    Skill,
    Occupation,
    Weapon,
    Investigator,
)
from investigator.serialization import (
    to_json,
    from_json,
    to_dict,
    from_dict,
)

# 便捷函数：从 JSON 文件直接加载 Investigator
load_investigator = from_json

__all__ = [
    "Stats",
    "DerivedStats",
    "Skill",
    "Occupation",
    "Weapon",
    "Investigator",
    "to_json",
    "from_json",
    "to_dict",
    "from_dict",
    "load_investigator",
]
```

- [ ] **Step 2: 最终集成测试**

Run: `cd src && python -c "
from investigator import Investigator, load_investigator, to_json, from_json, to_dict, from_dict
from investigator.rules import roll_stats, calc_derived, create_skill_list
from scenario_core import DirectedGraph, ScenarioWorld
from prompts import _build_player_skills
import tempfile, os

# 1. 创建完整调查员
inv = Investigator(name='亚楠', age=20, gender='女')
inv.stats = roll_stats()
inv.skills = create_skill_list()
inv.derived = calc_derived(inv.stats, inv.age)

# 2. JSON round-trip
tmp = tempfile.mktemp(suffix='.json')
to_json(inv, tmp)
inv2 = from_json(tmp)
os.unlink(tmp)

assert inv2.name == '亚楠'
assert inv2.derived.HP == inv.derived.HP

# 3. ScenarioWorld 集成
graph = DirectedGraph()
world = ScenarioWorld(graph, start_node='test', background_story='test bg')
world.set_player(inv)

# 4. prompts 兼容
skills_text = _build_player_skills(world)
assert '侦查' in skills_text
assert len(skills_text) > 0

print('=== All integration tests passed ===')
print(f'Investigator: {inv}')
print(f'HP: {inv.derived.HP}, SAN: {inv.derived.SAN}')
print(f'Skills: {len(inv.skills)} loaded')
print(f'Skills preview: {skills_text[:150]}...')
"`
Expected: `=== All integration tests passed ===` 及所有信息正确输出

- [ ] **Step 3: Commit**

```bash
git add src/investigator/__init__.py
git commit -m "fix: update investigator __init__ exports, add load_investigator alias"
```

---

## 自审清单

1. **Spec coverage:** 每个 spec 章节都有对应 Task — 数据模型(T2)、掷骰(T1)、规则引擎(T3)、序列化(T4)、文件结构(各Task覆盖)、前端(T8+T9)、ScenarioWorld集成(T6)、prompts适配(T7)
2. **No placeholders:** JavaScript 完整实现将在 Task 9 中展开（约 350 行）
3. **Type consistency:** `Investigator.skills_dict` → `_build_player_skills` 使用 `s.name`, `s.value`; `load_investigator` = `from_json` 别名
