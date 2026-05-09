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
