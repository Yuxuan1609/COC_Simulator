# Parser System Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-layer module designer system (L1 player / L2 KP / L3 designer), a weapon/enemy library with two-tier judgment, a content injection engine, and adapt the game loop for dynamic spawning — all while deprecating the old parsers.py/pipeline.py.

**Architecture:** Two new packages (`src/library/`, `src/module_designer/`) with zero circular dependencies. Library is fully independent. Module designer depends on scenario_core and library. Game loop adapts last. Each of the 10 major tasks produces testable output independently.

**Tech Stack:** Python 3.10+ dataclasses, JSON data files, DeepSeek API (existing llm.py), COC 7th rule system

---

## File Structure

```
Create:
  src/library/__init__.py
  src/library/weapons.py              # LibraryWeapon dataclass + loader
  src/library/enemies.py              # LibraryEnemy dataclass + loader
  src/library/judgment.py             # Two-tier judgment engine
  src/library/injector.py             # Offline + runtime injection
  src/module_designer/__init__.py
  src/module_designer/l1_player.py    # SceneL1, Perceptible, NPCAppearance
  src/module_designer/l2_keeper.py    # SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile
  src/module_designer/l3_designer.py  # ModuleMeta, WorldRule, LogicChain, SceneIntent, etc.
  src/module_designer/layered_schema.py    # JSON Schema validation
  src/module_designer/layered_parser.py    # LLM one-shot parser → 3-layer JSON
  src/module_designer/layered_pipeline.py  # Post-processing pipeline
  data/library/core/weapons.json
  data/library/core/enemies.json
  data/library/extensions/.gitkeep
  data/templates/l1_template.json
  data/templates/l2_template.json
  data/templates/l3_template.json
  data/modules/.gitkeep
  tests/test_library.py
  tests/test_module_designer.py

Modify:
  src/scenario_core.py                # +SpawnEnemy, GrantItem, EncounterAnchor, NPCStateChange
  src/prompts.py                      # +L1/L3-aware prompt builders
  src/game_loop.py                    # +Phase 3.5, Phase 5 enhancement, /spawn commands

Deprecate:
  src/parsers.py                      # → archive
  src/pipeline.py                     # → archive
```

---

### Task 1: Library — Weapons & Enemies Data Layer

**Files:**
- Create: `src/library/__init__.py`
- Create: `src/library/weapons.py`
- Create: `src/library/enemies.py`
- Create: `data/library/core/weapons.json`
- Create: `data/library/core/enemies.json`
- Create: `data/library/extensions/.gitkeep`
- Create: `tests/test_library.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/library data/library/core data/library/extensions tests
```

- [ ] **Step 2: Write core weapons JSON**

Write `data/library/core/weapons.json`:

```json
{
  "items": [
    {
      "name": "拳头/脚踢",
      "skill_name": "格斗",
      "damage": "1D3+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "all",
      "rarity": "common",
      "special_rules": ""
    },
    {
      "name": "小刀",
      "skill_name": "格斗",
      "damage": "1D4+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "all",
      "rarity": "common",
      "special_rules": "可投掷，投掷时使用投掷技能"
    },
    {
      "name": ".45自动手枪",
      "skill_name": "手枪",
      "damage": "1D10+2",
      "range": "15码",
      "shots": 7,
      "malfunction": 100,
      "era": "1920s",
      "rarity": "common",
      "special_rules": "可连射，每追加一发-5惩罚"
    },
    {
      "name": ".38左轮手枪",
      "skill_name": "手枪",
      "damage": "1D10",
      "range": "15码",
      "shots": 6,
      "malfunction": 100,
      "era": "1920s",
      "rarity": "common",
      "special_rules": ""
    },
    {
      "name": "霰弹枪(12号)",
      "skill_name": "霰弹枪",
      "damage": "4D6/2D6/1D6",
      "range": "10/20/50码",
      "shots": 2,
      "malfunction": 100,
      "era": "1920s",
      "rarity": "uncommon",
      "special_rules": "散射武器，伤害随距离递减"
    },
    {
      "name": "手电筒",
      "skill_name": "格斗",
      "damage": "1D3+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "all",
      "rarity": "common",
      "special_rules": "作为武器使用时视为临时武器；主要功能为提供光源"
    },
    {
      "name": "消防斧",
      "skill_name": "格斗",
      "damage": "1D8+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "all",
      "rarity": "uncommon",
      "special_rules": "双手武器"
    },
    {
      "name": "撬棍",
      "skill_name": "格斗",
      "damage": "1D6+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "all",
      "rarity": "common",
      "special_rules": "也可用于撬开门/箱子"
    },
    {
      "name": "警棍",
      "skill_name": "格斗",
      "damage": "1D6+DB",
      "range": "接触",
      "shots": 0,
      "malfunction": 100,
      "era": "1920s",
      "rarity": "common",
      "special_rules": ""
    },
    {
      "name": "步枪(.30-06)",
      "skill_name": "步枪",
      "damage": "2D6+4",
      "range": "110码",
      "shots": 5,
      "malfunction": 100,
      "era": "1920s",
      "rarity": "uncommon",
      "special_rules": "每轮一发"
    }
  ]
}
```

- [ ] **Step 3: Write core enemies JSON**

Write `data/library/core/enemies.json`:

```json
{
  "items": [
    {
      "name": "Clicker",
      "type": "神话生物",
      "attributes": {"STR": 80, "CON": 70, "SIZ": 65, "DEX": 50, "POW": 60},
      "armor": "2点厚皮",
      "attacks": [
        {"name": "噬咬", "damage": "1D8+DB", "notes": ""},
        {"name": "利爪", "damage": "1D6+DB", "notes": ""}
      ],
      "special_abilities": [
        {"name": "盲感", "desc": "无眼，通过声音定位。对其潜行检定为硬性难度。任何大声响会立即吸引其注意。"},
        {"name": "恐惧灵气", "desc": "首次目睹Clicker需进行SAN检定(0/1D4)。"}
      ],
      "san_loss": "0/1D4 (目睹), 1/1D6 (被攻击)",
      "combat_behavior": "优先攻击发出最大声音的目标。若无人出声则随机攻击。被击伤后会狂暴，每轮攻击两次。"
    },
    {
      "name": "大嘴吞噬者",
      "type": "神话生物",
      "attributes": {"STR": 120, "CON": 100, "SIZ": 150, "DEX": 30, "POW": 80},
      "armor": "5点异界物质",
      "attacks": [
        {"name": "吞噬", "damage": "即死/3D10+DB", "notes": "每轮吞噬一个车厢区域"}
      ],
      "special_abilities": [
        {"name": "不可阻挡", "desc": "无法被常规武器伤害，只能通过加速电车逃离。"},
        {"name": "渐进吞噬", "desc": "每经过一定时间，后方一个车厢被完全吞噬。被吞噬的车厢无法返回。"}
      ],
      "san_loss": "1D6/2D10 (目睹吞噬过程)",
      "combat_behavior": "不参与常规战斗。它是环境威胁而非可战斗敌人。以固定节奏从后方逼近。"
    },
    {
      "name": "深潜者",
      "type": "神话生物",
      "attributes": {"STR": 70, "CON": 65, "SIZ": 70, "DEX": 50, "POW": 50},
      "armor": "1点鳞片",
      "attacks": [
        {"name": "利爪", "damage": "1D6+DB", "notes": ""},
        {"name": "抓取", "damage": "特殊", "notes": "擒抱后每轮自动造成1D3+DB伤害"}
      ],
      "special_abilities": [
        {"name": "两栖", "desc": "可在水下无限呼吸，游泳速度等于MOV。"}
      ],
      "san_loss": "0/1D6",
      "combat_behavior": "偏好伏击，从水中或暗处突袭。受伤后会撤退到水中。"
    },
    {
      "name": "食尸鬼",
      "type": "神话生物",
      "attributes": {"STR": 70, "CON": 60, "SIZ": 55, "DEX": 65, "POW": 45},
      "armor": "无",
      "attacks": [
        {"name": "噬咬", "damage": "1D6+DB", "notes": ""},
        {"name": "利爪", "damage": "1D4+DB", "notes": "两次攻击/轮"}
      ],
      "special_abilities": [
        {"name": "食尸", "desc": "偏好捕食人类尸体。在墓地/停尸房附近出现概率极高。"},
        {"name": "夜视", "desc": "在完全黑暗中也能正常视物。"}
      ],
      "san_loss": "0/1D6",
      "combat_behavior": "群体狩猎，数量通常为2-5只。优先攻击落单或最弱的猎物。"
    },
    {
      "name": "疯狂信徒",
      "type": "人类",
      "attributes": {"STR": 50, "CON": 55, "SIZ": 60, "DEX": 60, "POW": 40},
      "armor": "无",
      "attacks": [
        {"name": "匕首", "damage": "1D4+DB", "notes": ""},
        {"name": "拳头", "damage": "1D3+DB", "notes": ""}
      ],
      "special_abilities": [
        {"name": "狂热", "desc": "不受SAN损失影响。不会逃跑，战至死亡。"}
      ],
      "san_loss": "0/1D3 (目睹仪式行为时)",
      "combat_behavior": "狂热的邪教徒，以数量优势压倒对手。有时携带简陋武器。"
    }
  ]
}
```

- [ ] **Step 4: Write weapons.py**

Write `src/library/weapons.py`:

```python
"""武器库数据类 + 加载器."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import json
import os


@dataclass
class LibraryWeapon:
    name: str
    skill_name: str
    damage: str
    range: str
    shots: int = 0
    malfunction: int = 100
    era: str = "all"
    rarity: str = "common"
    special_rules: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "skill_name": self.skill_name,
            "damage": self.damage,
            "range": self.range,
            "shots": self.shots,
            "malfunction": self.malfunction,
            "era": self.era,
            "rarity": self.rarity,
            "special_rules": self.special_rules,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryWeapon":
        return cls(
            name=data["name"],
            skill_name=data["skill_name"],
            damage=data["damage"],
            range=data["range"],
            shots=data.get("shots", 0),
            malfunction=data.get("malfunction", 100),
            era=data.get("era", "all"),
            rarity=data.get("rarity", "common"),
            special_rules=data.get("special_rules", ""),
        )


class WeaponLibrary:
    """武器库管理器 —— 加载 core + extensions，提供查询."""

    def __init__(self):
        self._weapons: dict[str, LibraryWeapon] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "library", "core", "weapons.json"
            )
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            weapon = LibraryWeapon.from_dict(item)
            self._weapons[weapon.name] = weapon

    def get(self, name: str) -> Optional[LibraryWeapon]:
        return self._weapons.get(name)

    def list_all(self) -> list[LibraryWeapon]:
        return list(self._weapons.values())

    def search(self, era: str = None, rarity: str = None, keyword: str = None) -> list[LibraryWeapon]:
        results = []
        for w in self._weapons.values():
            if era and w.era != "all" and w.era != era:
                continue
            if rarity and w.rarity != rarity:
                continue
            if keyword and keyword.lower() not in w.name.lower():
                continue
            results.append(w)
        return results

    def __len__(self) -> int:
        return len(self._weapons)

    def __repr__(self) -> str:
        return f"WeaponLibrary({len(self._weapons)} weapons)"
```

- [ ] **Step 5: Write enemies.py**

Write `src/library/enemies.py`:

```python
"""敌人库数据类 + 加载器."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import json
import os


@dataclass
class EnemyAttack:
    name: str
    damage: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "damage": self.damage, "notes": self.notes}

    @classmethod
    def from_dict(cls, data: dict) -> "EnemyAttack":
        return cls(
            name=data["name"],
            damage=data["damage"],
            notes=data.get("notes", ""),
        )


@dataclass
class SpecialAbility:
    name: str
    desc: str

    def to_dict(self) -> dict:
        return {"name": self.name, "desc": self.desc}

    @classmethod
    def from_dict(cls, data: dict) -> "SpecialAbility":
        return cls(name=data["name"], desc=data["desc"])


@dataclass
class LibraryEnemy:
    name: str
    type: str
    attributes: dict
    armor: str
    attacks: list
    special_abilities: list
    san_loss: str
    combat_behavior: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "attributes": self.attributes,
            "armor": self.armor,
            "attacks": [a.to_dict() if isinstance(a, EnemyAttack) else a for a in self.attacks],
            "special_abilities": [
                s.to_dict() if isinstance(s, SpecialAbility) else s for s in self.special_abilities
            ],
            "san_loss": self.san_loss,
            "combat_behavior": self.combat_behavior,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryEnemy":
        return cls(
            name=data["name"],
            type=data["type"],
            attributes=data["attributes"],
            armor=data.get("armor", "无"),
            attacks=[EnemyAttack.from_dict(a) for a in data.get("attacks", [])],
            special_abilities=[
                SpecialAbility.from_dict(s) for s in data.get("special_abilities", [])
            ],
            san_loss=data.get("san_loss", ""),
            combat_behavior=data.get("combat_behavior", ""),
        )


class EnemyLibrary:
    """敌人库管理器 —— 加载 core + extensions，提供查询."""

    def __init__(self):
        self._enemies: dict[str, LibraryEnemy] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..", "data", "library", "core", "enemies.json"
            )
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            enemy = LibraryEnemy.from_dict(item)
            self._enemies[enemy.name] = enemy

    def get(self, name: str) -> Optional[LibraryEnemy]:
        return self._enemies.get(name)

    def list_all(self) -> list[LibraryEnemy]:
        return list(self._enemies.values())

    def search(self, enemy_type: str = None, keyword: str = None) -> list[LibraryEnemy]:
        results = []
        for e in self._enemies.values():
            if enemy_type and e.type != enemy_type:
                continue
            if keyword and keyword.lower() not in e.name.lower():
                continue
            results.append(e)
        return results

    def __len__(self) -> int:
        return len(self._enemies)

    def __repr__(self) -> str:
        return f"EnemyLibrary({len(self._enemies)} enemies)"
```

- [ ] **Step 6: Write __init__.py**

Write `src/library/__init__.py`:

```python
"""武器/敌人资源库 —— 独立于三层信息模型，无外部依赖."""
from library.weapons import LibraryWeapon, WeaponLibrary
from library.enemies import LibraryEnemy, EnemyLibrary, EnemyAttack, SpecialAbility
```

- [ ] **Step 7: Write test**

Write `tests/test_library.py`:

```python
"""library 包基础测试."""
import sys
import os
import json

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from library.weapons import LibraryWeapon, WeaponLibrary
from library.enemies import LibraryEnemy, EnemyLibrary


def test_weapon_from_dict():
    data = {
        "name": ".45自动手枪",
        "skill_name": "手枪",
        "damage": "1D10+2",
        "range": "15码",
        "shots": 7,
        "malfunction": 100,
        "era": "1920s",
        "rarity": "common",
        "special_rules": "可连射，每追加一发-5惩罚",
    }
    w = LibraryWeapon.from_dict(data)
    assert w.name == ".45自动手枪"
    assert w.shots == 7
    assert w.damage == "1D10+2"
    d = w.to_dict()
    assert d["name"] == ".45自动手枪"


def test_weapon_library_load_core():
    lib = WeaponLibrary()
    lib.load_core()
    assert len(lib) >= 5
    pistol = lib.get(".45自动手枪")
    assert pistol is not None
    assert pistol.skill_name == "手枪"


def test_weapon_search():
    lib = WeaponLibrary()
    lib.load_core()
    era_results = lib.search(era="1920s")
    assert len(era_results) > 0
    keyword_results = lib.search(keyword="手枪")
    assert all("手枪" in w.name for w in keyword_results)


def test_enemy_from_dict():
    data = {
        "name": "Clicker",
        "type": "神话生物",
        "attributes": {"STR": 80, "CON": 70, "SIZ": 65, "DEX": 50, "POW": 60},
        "armor": "2点厚皮",
        "attacks": [{"name": "噬咬", "damage": "1D8+DB"}],
        "special_abilities": [{"name": "盲感", "desc": "通过声音定位"}],
        "san_loss": "0/1D4",
        "combat_behavior": "优先攻击发出最大声音的目标",
    }
    e = LibraryEnemy.from_dict(data)
    assert e.name == "Clicker"
    assert len(e.attacks) == 1
    assert e.attacks[0].damage == "1D8+DB"


def test_enemy_library_load_core():
    lib = EnemyLibrary()
    lib.load_core()
    assert len(lib) >= 3
    clicker = lib.get("Clicker")
    assert clicker is not None
    assert clicker.type == "神话生物"


def test_enemy_search():
    lib = EnemyLibrary()
    lib.load_core()
    mythos = lib.search(enemy_type="神话生物")
    assert all(e.type == "神话生物" for e in mythos)
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_library.py -v`
Expected: 6 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/library/ data/library/ tests/test_library.py
git commit -m "feat: add library package — weapon/enemy data models + core JSON data"
```

---

### Task 2: Library — Two-Tier Judgment Engine

**Files:**
- Create: `src/library/judgment.py`

- [ ] **Step 1: Write judgment.py**

Write `src/library/judgment.py`:

```python
"""双层判定系统：T1 确定性引擎 + T2 LLM 增强."""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING
import random

if TYPE_CHECKING:
    from library.enemies import LibraryEnemy, SpecialAbility
    from library.weapons import LibraryWeapon
    from scenario_core import ScenarioWorld


class Tier1Result:
    """确定性引擎的判定结果."""

    def __init__(self, success: bool, roll: int, target: int, detail: str = ""):
        self.success = success
        self.roll = roll
        self.target = target
        self.detail = detail

    def __repr__(self):
        status = "成功" if self.success else "失败"
        return f"Tier1Result({status}, roll={self.roll}, target={self.target})"


class JudgmentEngine:
    """
    双层判定引擎。
    - tier1_enabled: 始终 True（确定性检定必须有）
    - tier2_enabled: 可开关，决定是否调用 LLM 增强
    """

    def __init__(self, tier2_enabled: bool = True):
        self.tier2_enabled = tier2_enabled

    # ── Tier 1: 确定性 ──

    def tier1_skill_check(self, skill_value: int, difficulty: str = "regular") -> Tier1Result:
        """
        COC 7th D100 技能检定。
        difficulty: regular(技能值), hard(技能值/2), extreme(技能值/5)
        """
        roll = random.randint(1, 100)
        if difficulty == "hard":
            target = skill_value // 2
        elif difficulty == "extreme":
            target = skill_value // 5
        else:
            target = skill_value
        success = roll <= target
        detail = f"D100={roll}/{target} {'成功' if success else '失败'}"
        return Tier1Result(success, roll, target, detail)

    def tier1_damage_roll(self, damage_formula: str, db: int = 0) -> tuple[int, str]:
        """
        解析伤害公式并掷骰。
        支持: "1D8+DB", "2D6+4", "1D3", "4D6/2D6/1D6"
        """
        formula = damage_formula.replace("DB", str(db))
        if "/" in formula:
            formula = formula.split("/")[0]
        parts = formula.replace("+", " ").replace("-", " -").split()
        total = 0
        detail_parts = []
        for part in parts:
            if part.startswith("-"):
                sign = -1
                part = part[1:]
            else:
                sign = 1
            if "D" in part.upper():
                count_str, sides_str = part.upper().split("D")
                count = int(count_str) if count_str else 1
                sides = int(sides_str)
                roll = sum(random.randint(1, sides) for _ in range(count))
                total += sign * roll
                detail_parts.append(f"{part}({roll})")
            else:
                total += sign * int(part)
                detail_parts.append(part)
        detail = " + ".join(detail_parts) + f" = {total}"
        return total, detail

    def tier1_san_check(self, san_loss: str) -> tuple[int, int, str]:
        """解析 SAN 损失公式 "成功损失/失败损失" → (成功损失, 失败损失)"""
        parts = san_loss.split("/")
        success_loss = self._parse_san_part(parts[0]) if len(parts) > 0 else 0
        fail_loss = self._parse_san_part(parts[1]) if len(parts) > 1 else success_loss
        return success_loss, fail_loss, san_loss

    def _parse_san_part(self, s: str) -> int:
        s = s.strip()
        if s == "0":
            return 0
        if "D" in s.upper():
            count_str, sides_str = s.upper().replace("D", " ").split()
            count = int(count_str) if count_str else 1
            sides = int(sides_str)
            return sum(random.randint(1, sides) for _ in range(count))
        return int(s) if s.isdigit() else 0

    # ── Tier 2: LLM 增强（桩，prompt 构建由 prompts.py 负责）──

    def build_tier2_context(
        self,
        tier1: Tier1Result,
        enemy: "LibraryEnemy" = None,
        weapon: "LibraryWeapon" = None,
        world: "ScenarioWorld" = None,
    ) -> str:
        """构建供 LLM 做 Tier 2 判定的上下文."""
        parts = [f"T1 检定结果: 掷骰={tier1.roll}, 目标={tier1.target}, {'成功' if tier1.success else '失败'}"]
        if enemy:
            parts.append(f"敌人: {enemy.name}")
            parts.append(f"特殊能力: {', '.join(a.name for a in enemy.special_abilities)}")
            parts.append(f"战斗行为: {enemy.combat_behavior}")
        if weapon:
            parts.append(f"武器: {weapon.name} ({weapon.damage})")
            if weapon.special_rules:
                parts.append(f"武器规则: {weapon.special_rules}")
        return "\n".join(parts)
```

- [ ] **Step 2: Test judgment**

Append to `tests/test_library.py`:

```python
from library.judgment import JudgmentEngine, Tier1Result


def test_tier1_skill_check():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(50, "regular")
    assert result.target == 50
    assert 1 <= result.roll <= 100


def test_tier1_hard_difficulty():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(60, "hard")
    assert result.target == 30


def test_tier1_extreme_difficulty():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(50, "extreme")
    assert result.target == 10


def test_tier1_damage_roll():
    engine = JudgmentEngine()
    total, detail = engine.tier1_damage_roll("1D6+DB", db=4)
    assert 5 <= total <= 10
    assert "=" in detail


def test_tier1_san_check():
    engine = JudgmentEngine()
    s, f, formula = engine.tier1_san_check("1/1D6")
    assert s == 1
    assert 1 <= f <= 6
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_library.py -v`
Expected: 11 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/library/judgment.py tests/test_library.py
git commit -m "feat: add two-tier judgment engine with T1 deterministic resolution"
```

---

### Task 3: Library — Content Injector

**Files:**
- Create: `src/library/injector.py`

- [ ] **Step 1: Write injector.py**

Write `src/library/injector.py`:

```python
"""内容注入引擎 —— 离线预填充 + 运行时动态注入."""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    from scenario_core import ScenarioWorld


class ContentInjector:
    """
    从武器/敌人库向模组内容注入引用。
    - offline: 模组构建时，扫描 L3+L2 自动填充 encounter/weapon 引用
    - runtime: 游戏进行中，LLM 判断偏离时动态注入
    """

    def __init__(
        self,
        weapon_lib: "WeaponLibrary",
        enemy_lib: "EnemyLibrary",
        offline_enabled: bool = True,
        runtime_enabled: bool = True,
    ):
        self.weapons = weapon_lib
        self.enemies = enemy_lib
        self.offline_enabled = offline_enabled
        self.runtime_enabled = runtime_enabled

    # ── 离线注入 ──

    def offline_inject_scene(self, scene_data: dict, l3_scene_intent: dict = None) -> dict:
        """
        根据场景 L2 数据和 L3 scene_intent 自动填充 encounter/weapon 引用。
        当前为确定性规则版本（不需要 LLM）：
        - danger_level=high/extreme → 搜索匹配的敌人建议
        - 不对已有 encounter 做修改
        """
        if not self.offline_enabled:
            return scene_data

        if l3_scene_intent:
            danger = l3_scene_intent.get("danger_level", "safe")
            if danger in ("high", "extreme"):
                scene_data.setdefault("encounters", [])
                scene_data.setdefault("scene_weapons", [])

        return scene_data

    def offline_inject_module(self, l2_data: dict, l3_data: dict) -> dict:
        """对所有场景执行离线注入."""
        if not self.offline_enabled:
            return l2_data
        scene_intents = l3_data.get("scene_intents", {})
        for scene_name, scene_data in l2_data.get("scenes", {}).items():
            intent = scene_intents.get(scene_name)
            l2_data["scenes"][scene_name] = self.offline_inject_scene(scene_data, intent)
        return l2_data

    # ── 运行时注入 ──

    def runtime_spawn_enemy(
        self, enemy_name: str, scene_name: str, world: "ScenarioWorld" = None
    ) -> dict | None:
        """运行时动态生成敌人遭遇."""
        if not self.runtime_enabled:
            return None
        enemy = self.enemies.get(enemy_name)
        if not enemy:
            return None
        return {
            "enemy_ref": enemy_name,
            "trigger_condition": f"runtime_injection in {scene_name}",
            "initial_behavior": enemy.combat_behavior,
            "quantity": 1,
            "notes": "运行时动态注入",
        }

    def runtime_grant_weapon(self, weapon_name: str) -> dict | None:
        """运行时动态分发武器."""
        if not self.runtime_enabled:
            return None
        weapon = self.weapons.get(weapon_name)
        if not weapon:
            return None
        return {
            "weapon_ref": weapon_name,
            "location": "runtime_injection",
            "discovery_method": "动态注入",
        }

    @property
    def status(self) -> dict:
        return {
            "offline_enabled": self.offline_enabled,
            "runtime_enabled": self.runtime_enabled,
            "weapons_loaded": len(self.weapons),
            "enemies_loaded": len(self.enemies),
        }
```

- [ ] **Step 2: Update __init__.py**

Write `src/library/__init__.py` (overwrite):

```python
"""武器/敌人资源库 —— 独立于三层信息模型，无外部依赖."""
from library.weapons import LibraryWeapon, WeaponLibrary
from library.enemies import LibraryEnemy, EnemyLibrary, EnemyAttack, SpecialAbility
from library.judgment import JudgmentEngine, Tier1Result
from library.injector import ContentInjector
```

- [ ] **Step 3: Test injector**

Append to `tests/test_library.py`:

```python
from library.injector import ContentInjector


def test_injector_init():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    assert injector.offline_enabled is True
    assert injector.runtime_enabled is True


def test_injector_offline_inject_scene_no_danger():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    scene = {"description": "test scene"}
    result = injector.offline_inject_scene(scene, {"danger_level": "safe"})
    assert result == scene  # unchanged


def test_injector_offline_inject_scene_high_danger():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    scene = {"description": "danger zone"}
    result = injector.offline_inject_scene(scene, {"danger_level": "extreme"})
    assert "encounters" in result
    assert "scene_weapons" in result


def test_injector_runtime_spawn_enemy_not_loaded():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    result = injector.runtime_spawn_enemy("Clicker", "2号车厢")
    assert result is None  # library not loaded


def test_injector_runtime_spawn_enemy_loaded():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    elib.load_core()
    injector = ContentInjector(wlib, elib)
    result = injector.runtime_spawn_enemy("Clicker", "2号车厢")
    assert result is not None
    assert result["enemy_ref"] == "Clicker"
    assert result["quantity"] == 1


def test_injector_status():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    s = injector.status
    assert "offline_enabled" in s
    assert "weapons_loaded" in s
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_library.py -v`
Expected: 17 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/library/injector.py src/library/__init__.py tests/test_library.py
git commit -m "feat: add content injector — offline pre-fill + runtime dynamic injection"
```

---

### Task 4: Scenario Core Extension

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: Add new side_effect types**

Insert after `StatChange` class in `src/scenario_core.py`:

```python
@dataclass
class SpawnEnemy:
    """生成敌人遭遇 —— 从 library 中实例化敌人"""
    enemy_ref: str       # 引用 library/enemies 中的敌人名
    scene: str           # 目标场景
    trigger_condition: str = ""
    quantity: int = 1


@dataclass
class GrantItem:
    """授予物品 —— 从 library 中实例化武器/物品"""
    item_ref: str        # 引用 library/weapons 中的武器名（常规物品为自由文本）
    scene: str = ""      # 目标场景（空=当前场景）


@dataclass
class EncounterAnchor:
    """遭遇锚点 —— 标记场景中存在可能触发遭遇的区域"""
    scene: str
    enemy_ref: str
    trigger_condition: str = ""
    is_active: bool = True


@dataclass
class NPCStateChange:
    """NPC 状态变化 —— 更新 ScenarioWorld.npc_states"""
    npc_name: str
    new_state: str       # 如 "清醒"、"死亡"、"已对话"、"已离开"
```

- [ ] **Step 2: Extend _parse_side_effect and _side_effect_to_dict**

Add cases to `_parse_side_effect`:

```python
def _parse_side_effect(data: dict):
    type_ = data.get("type", "")
    if type_ == "flag_set":
        return FlagSet(key=data["key"], value=data.get("value", True))
    elif type_ == "item_gain":
        return ItemGain(item_name=data["item_name"])
    elif type_ == "stat_change":
        return StatChange(stat_name=data["stat_name"], delta=data.get("delta", 0))
    elif type_ == "spawn_enemy":
        return SpawnEnemy(
            enemy_ref=data["enemy_ref"],
            scene=data.get("scene", ""),
            trigger_condition=data.get("trigger_condition", ""),
            quantity=data.get("quantity", 1),
        )
    elif type_ == "grant_item":
        return GrantItem(item_ref=data["item_ref"], scene=data.get("scene", ""))
    elif type_ == "npc_state_change":
        return NPCStateChange(npc_name=data["npc_name"], new_state=data["new_state"])
    return None
```

Add cases to `_side_effect_to_dict`:

```python
def _side_effect_to_dict(effect) -> dict:
    if isinstance(effect, FlagSet):
        return {"type": "flag_set", "key": effect.key, "value": effect.value}
    elif isinstance(effect, ItemGain):
        return {"type": "item_gain", "item_name": effect.item_name}
    elif isinstance(effect, StatChange):
        return {"type": "stat_change", "stat_name": effect.stat_name, "delta": effect.delta}
    elif isinstance(effect, SpawnEnemy):
        return {
            "type": "spawn_enemy",
            "enemy_ref": effect.enemy_ref,
            "scene": effect.scene,
            "trigger_condition": effect.trigger_condition,
            "quantity": effect.quantity,
        }
    elif isinstance(effect, GrantItem):
        return {"type": "grant_item", "item_ref": effect.item_ref, "scene": effect.scene}
    elif isinstance(effect, NPCStateChange):
        return {"type": "npc_state_change", "npc_name": effect.npc_name, "new_state": effect.new_state}
    return {}
```

- [ ] **Step 3: Add npc_states to ScenarioWorld**

Add to `ScenarioWorld.__init__`:

```python
# NPC 运行时状态
self.npc_states: Dict[str, str] = {}
```

Add methods to `ScenarioWorld`:

```python
def set_npc_state(self, npc_name: str, state: str):
    """更新 NPC 运行时状态"""
    self.npc_states[npc_name] = state

def get_npc_state(self, npc_name: str) -> str:
    """查询 NPC 运行时状态"""
    return self.npc_states.get(npc_name, "未知")
```

- [ ] **Step 4: Extend _apply_side_effects in game_loop.py**

Read current `_apply_side_effects` in `src/game_loop.py` and add cases for new types (this will be done in Task 7, but let's note the needed additions):

```python
# To be added in Task 7:
# elif isinstance(effect, SpawnEnemy):
#     msgs.append(f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {effect.scene or world.current_location}")
# elif isinstance(effect, GrantItem):
#     msgs.append(f"[授予物品] {effect.item_ref}")
#     world.memory.note_item(effect.item_ref)
# elif isinstance(effect, NPCStateChange):
#     world.set_npc_state(effect.npc_name, effect.new_state)
#     msgs.append(f"[NPC状态] {effect.npc_name} → {effect.new_state}")
```

- [ ] **Step 5: Update to_dict/from_dict to include npc_states**

Add to `ScenarioWorld.to_dict()`:

```python
"npc_states": dict(self.npc_states),
```

Add to `ScenarioWorld.from_dict()`:

```python
world.npc_states = data.get("npc_states", {})
```

- [ ] **Step 6: Verify existing tests still pass**

Run: `python -m pytest tests/ -v --tb=short` (if existing tests exist)
Run: `python -c "from src.scenario_core import SpawnEnemy, GrantItem, EncounterAnchor, NPCStateChange; print('import OK')"`

- [ ] **Step 7: Commit**

```bash
git add src/scenario_core.py src/game_loop.py
git commit -m "feat: add SpawnEnemy/GrantItem/EncounterAnchor/NPCStateChange side effects + npc_states"
```

---

### Task 5: Module Designer — Data Models

**Files:**
- Create: `src/module_designer/__init__.py`
- Create: `src/module_designer/l1_player.py`
- Create: `src/module_designer/l2_keeper.py`
- Create: `src/module_designer/l3_designer.py`
- Create: `tests/test_module_designer.py`

- [ ] **Step 1: Write l1_player.py**

Write `src/module_designer/l1_player.py`:

```python
"""L1 玩家可见层数据模型."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Perceptible:
    """玩家无需检定即可感知的元素."""
    type: str            # object / sound / smell / sight / touch / intuition
    name: str
    brief: str           # 一句话描述
    linked_interaction: Optional[str] = None   # 关联 L2 interaction.name

    def to_dict(self) -> dict:
        d = {"type": self.type, "name": self.name, "brief": self.brief}
        if self.linked_interaction:
            d["linked_interaction"] = self.linked_interaction
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Perceptible":
        return cls(
            type=data["type"],
            name=data["name"],
            brief=data["brief"],
            linked_interaction=data.get("linked_interaction"),
        )


@dataclass
class NPCAppearance:
    """NPC 外貌描述（玩家可见部分）."""
    name: str
    brief: str
    demeanor: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "brief": self.brief, "demeanor": self.demeanor}

    @classmethod
    def from_dict(cls, data: dict) -> "NPCAppearance":
        return cls(
            name=data["name"],
            brief=data["brief"],
            demeanor=data.get("demeanor", ""),
        )


@dataclass
class SceneL1:
    """单个场景的 L1 信息."""
    scene_name: str
    entry_narrative: str = ""
    atmosphere: str = ""
    mood: str = "uneasy"        # confused / uneasy / tense / terrified / hopeful / desperate
    perceptible: List[Perceptible] = field(default_factory=list)
    ambient_hints: List[str] = field(default_factory=list)
    npc_appearances: List[NPCAppearance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entry_narrative": self.entry_narrative,
            "atmosphere": self.atmosphere,
            "mood": self.mood,
            "perceptible": [p.to_dict() for p in self.perceptible],
            "ambient_hints": self.ambient_hints,
            "npc_appearances": [n.to_dict() for n in self.npc_appearances],
        }

    @classmethod
    def from_dict(cls, data: dict, scene_name: str = "") -> "SceneL1":
        return cls(
            scene_name=scene_name,
            entry_narrative=data.get("entry_narrative", ""),
            atmosphere=data.get("atmosphere", ""),
            mood=data.get("mood", "uneasy"),
            perceptible=[Perceptible.from_dict(p) for p in data.get("perceptible", [])],
            ambient_hints=data.get("ambient_hints", []),
            npc_appearances=[NPCAppearance.from_dict(n) for n in data.get("npc_appearances", [])],
        )


def load_l1(path: str) -> dict[str, SceneL1]:
    """从 JSON 加载 L1 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {name: SceneL1.from_dict(sd, name) for name, sd in data.items()}


def save_l1(l1_data: dict[str, SceneL1], path: str) -> None:
    """保存 L1 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {name: scene.to_dict() for name, scene in l1_data.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 2: Write l2_keeper.py**

Write `src/module_designer/l2_keeper.py`:

```python
"""L2 KP 守秘人层数据模型 —— 现有 Interaction/GameEvent 对齐 + 扩展."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


# ── 引用 scenario_core 的已有类型 ──
# 这些在运行时从 scenario_core 导入，以避免循环依赖


@dataclass
class Encounter:
    """场景中的敌人遭遇声明."""
    enemy_ref: str
    trigger_condition: str = ""
    initial_behavior: str = ""
    quantity: int = 1
    notes: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "enemy_ref": self.enemy_ref,
            "trigger_condition": self.trigger_condition,
            "initial_behavior": self.initial_behavior,
            "quantity": self.quantity,
        }
        if self.notes:
            d["notes"] = self.notes
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Encounter":
        return cls(
            enemy_ref=data["enemy_ref"],
            trigger_condition=data.get("trigger_condition", ""),
            initial_behavior=data.get("initial_behavior", ""),
            quantity=data.get("quantity", 1),
            notes=data.get("notes"),
            extra=data.get("extra"),
        )


@dataclass
class SceneWeapon:
    """场景中可获取的武器."""
    weapon_ref: str
    location: str = ""
    discovery_method: str = ""
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"weapon_ref": self.weapon_ref, "location": self.location, "discovery_method": self.discovery_method}
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SceneWeapon":
        return cls(
            weapon_ref=data["weapon_ref"],
            location=data.get("location", ""),
            discovery_method=data.get("discovery_method", ""),
            extra=data.get("extra"),
        )


@dataclass
class HiddenInfo:
    """被动触发信息（"暗骰"式）."""
    info: str
    trigger_condition: str     # 条件表达式
    reveal_narrative: str = ""
    linked_skill: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {"info": self.info, "trigger_condition": self.trigger_condition, "reveal_narrative": self.reveal_narrative}
        if self.linked_skill:
            d["linked_skill"] = self.linked_skill
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "HiddenInfo":
        return cls(
            info=data["info"],
            trigger_condition=data["trigger_condition"],
            reveal_narrative=data.get("reveal_narrative", ""),
            linked_skill=data.get("linked_skill"),
            extra=data.get("extra"),
        )


@dataclass
class NPCProfile:
    """NPC 完整 KP 侧信息."""
    name: str
    role: str = ""
    motivation: str = ""
    knowledge: List[str] = field(default_factory=list)
    personality: str = ""
    voice_notes: Optional[str] = None
    notes: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name, "role": self.role, "motivation": self.motivation,
            "knowledge": self.knowledge, "personality": self.personality,
        }
        if self.voice_notes:
            d["voice_notes"] = self.voice_notes
        if self.notes:
            d["notes"] = self.notes
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "NPCProfile":
        return cls(
            name=data["name"],
            role=data.get("role", ""),
            motivation=data.get("motivation", ""),
            knowledge=data.get("knowledge", []),
            personality=data.get("personality", ""),
            voice_notes=data.get("voice_notes"),
            notes=data.get("notes"),
            extra=data.get("extra"),
        )


@dataclass
class SceneL2:
    """单个场景的 L2 KP 信息."""
    scene_name: str
    description: str = ""
    from_here: list = field(default_factory=list)
    to_here: list = field(default_factory=list)
    interactions: list = field(default_factory=list)   # list[Interaction]
    encounters: List[Encounter] = field(default_factory=list)
    scene_weapons: List[SceneWeapon] = field(default_factory=list)
    hidden_info: List[HiddenInfo] = field(default_factory=list)
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "description": self.description,
            "from_here": self.from_here,
            "to_here": self.to_here,
            "interactions": self.interactions,
            "encounters": [e.to_dict() for e in self.encounters],
            "scene_weapons": [sw.to_dict() for sw in self.scene_weapons],
            "hidden_info": [h.to_dict() for h in self.hidden_info],
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict, scene_name: str = "") -> "SceneL2":
        return cls(
            scene_name=scene_name,
            description=data.get("description", ""),
            from_here=data.get("from_here", []),
            to_here=data.get("to_here", []),
            interactions=data.get("interactions", []),
            encounters=[Encounter.from_dict(e) for e in data.get("encounters", [])],
            scene_weapons=[SceneWeapon.from_dict(sw) for sw in data.get("scene_weapons", [])],
            hidden_info=[HiddenInfo.from_dict(h) for h in data.get("hidden_info", [])],
            extra=data.get("extra"),
        )


def load_l2(path: str) -> dict:
    """从 JSON 加载 L2 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    scenes = {name: SceneL2.from_dict(sd, name) for name, sd in data.get("scenes", {}).items()}
    events = data.get("events", [])
    npc_profiles = {name: NPCProfile.from_dict(np) for name, np in data.get("npc_profiles", {}).items()}
    return {"scenes": scenes, "events": events, "npc_profiles": npc_profiles}


def save_l2(l2_data: dict, path: str) -> None:
    """保存 L2 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {
        "scenes": {name: scene.to_dict() for name, scene in l2_data["scenes"].items()},
        "events": l2_data.get("events", []),
        "npc_profiles": {name: np.to_dict() for name, np in l2_data.get("npc_profiles", {}).items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: Write l3_designer.py**

Write `src/module_designer/l3_designer.py`:

```python
"""L3 设计者层数据模型."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModuleMeta:
    title: str = ""
    author: str = ""
    era: str = "1920s"
    theme: str = ""
    expected_duration: str = ""
    player_count: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleMeta":
        return cls(
            title=data.get("title", ""),
            author=data.get("author", ""),
            era=data.get("era", "1920s"),
            theme=data.get("theme", ""),
            expected_duration=data.get("expected_duration", ""),
            player_count=data.get("player_count", ""),
        )


@dataclass
class WorldRule:
    id: str
    name: str
    rule: str
    scope: List[str] = field(default_factory=list)
    is_absolute: bool = True

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "rule": self.rule,
                "scope": self.scope, "is_absolute": self.is_absolute}

    @classmethod
    def from_dict(cls, data: dict) -> "WorldRule":
        return cls(
            id=data["id"], name=data["name"], rule=data["rule"],
            scope=data.get("scope", []),
            is_absolute=data.get("is_absolute", True),
        )


@dataclass
class Branch:
    condition: str
    effect: str = ""
    next_node: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"condition": self.condition, "effect": self.effect}
        if self.next_node:
            d["next_node"] = self.next_node
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Branch":
        return cls(
            condition=data["condition"],
            effect=data.get("effect", ""),
            next_node=data.get("next_node"),
        )


@dataclass
class LogicChain:
    id: str
    name: str
    description: str = ""
    nodes: List[str] = field(default_factory=list)
    branches: List[Branch] = field(default_factory=list)
    is_critical: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "nodes": self.nodes,
            "branches": [b.to_dict() for b in self.branches],
            "is_critical": self.is_critical,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogicChain":
        return cls(
            id=data["id"], name=data["name"],
            description=data.get("description", ""),
            nodes=data.get("nodes", []),
            branches=[Branch.from_dict(b) for b in data.get("branches", [])],
            is_critical=data.get("is_critical", True),
        )


@dataclass
class SceneIntent:
    purpose: str = ""
    emotion: str = ""
    danger_level: str = "safe"
    key_info: List[str] = field(default_factory=list)
    key_threat: Optional[str] = None
    exit_leads_to: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "purpose": self.purpose, "emotion": self.emotion,
            "danger_level": self.danger_level, "key_info": self.key_info,
            "exit_leads_to": self.exit_leads_to,
        }
        if self.key_threat:
            d["key_threat"] = self.key_threat
        if self.notes:
            d["notes"] = self.notes
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SceneIntent":
        return cls(
            purpose=data.get("purpose", ""),
            emotion=data.get("emotion", ""),
            danger_level=data.get("danger_level", "safe"),
            key_info=data.get("key_info", []),
            key_threat=data.get("key_threat"),
            exit_leads_to=data.get("exit_leads_to", []),
            notes=data.get("notes"),
        )


@dataclass
class EndingCondition:
    id: str
    type: str = "escape"
    condition: str = ""
    narrative_theme: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "condition": self.condition, "narrative_theme": self.narrative_theme}

    @classmethod
    def from_dict(cls, data: dict) -> "EndingCondition":
        return cls(
            id=data["id"], type=data.get("type", "escape"),
            condition=data.get("condition", ""),
            narrative_theme=data.get("narrative_theme", ""),
        )


@dataclass
class ToneConstraints:
    genre: str = ""
    forbidden: List[str] = field(default_factory=list)
    required: List[str] = field(default_factory=list)
    narrative_style: str = ""

    def to_dict(self) -> dict:
        return {
            "genre": self.genre, "forbidden": self.forbidden,
            "required": self.required, "narrative_style": self.narrative_style,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToneConstraints":
        return cls(
            genre=data.get("genre", ""),
            forbidden=data.get("forbidden", []),
            required=data.get("required", []),
            narrative_style=data.get("narrative_style", ""),
        )


@dataclass
class L3Designer:
    """L3 设计者层完整数据."""
    module_meta: ModuleMeta = field(default_factory=ModuleMeta)
    world_rules: List[WorldRule] = field(default_factory=list)
    logic_chains: List[LogicChain] = field(default_factory=list)
    scene_intents: dict[str, SceneIntent] = field(default_factory=dict)
    ending_conditions: List[EndingCondition] = field(default_factory=list)
    tone_constraints: ToneConstraints = field(default_factory=ToneConstraints)
    driving_force: str = ""

    def to_dict(self) -> dict:
        return {
            "module_meta": self.module_meta.to_dict(),
            "world_rules": [r.to_dict() for r in self.world_rules],
            "logic_chains": [lc.to_dict() for lc in self.logic_chains],
            "scene_intents": {k: v.to_dict() for k, v in self.scene_intents.items()},
            "ending_conditions": [e.to_dict() for e in self.ending_conditions],
            "tone_constraints": self.tone_constraints.to_dict(),
            "driving_force": self.driving_force,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "L3Designer":
        return cls(
            module_meta=ModuleMeta.from_dict(data.get("module_meta", {})),
            world_rules=[WorldRule.from_dict(r) for r in data.get("world_rules", [])],
            logic_chains=[LogicChain.from_dict(lc) for lc in data.get("logic_chains", [])],
            scene_intents={k: SceneIntent.from_dict(v) for k, v in data.get("scene_intents", {}).items()},
            ending_conditions=[EndingCondition.from_dict(e) for e in data.get("ending_conditions", [])],
            tone_constraints=ToneConstraints.from_dict(data.get("tone_constraints", {})),
            driving_force=data.get("driving_force", ""),
        )


def load_l3(path: str) -> L3Designer:
    """从 JSON 加载 L3 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return L3Designer.from_dict(data)


def save_l3(l3: L3Designer, path: str) -> None:
    """保存 L3 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(l3.to_dict(), f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: Write module_designer/__init__.py**

Write `src/module_designer/__init__.py`:

```python
"""三层信息引擎."""
from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance, load_l1, save_l1
from module_designer.l2_keeper import (
    SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile, load_l2, save_l2,
)
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, LogicChain, Branch,
    SceneIntent, EndingCondition, ToneConstraints, load_l3, save_l3,
)
```

- [ ] **Step 5: Write tests**

Write `tests/test_module_designer.py`:

```python
"""module_designer 数据模型测试."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, LogicChain, SceneIntent, ToneConstraints
)


def test_scene_l1_roundtrip():
    scene = SceneL1(
        scene_name="6号车厢",
        entry_narrative="你醒来...",
        atmosphere="昏暗封闭",
        mood="uneasy",
        perceptible=[Perceptible(type="object", name="便签", brief="一张泛黄的纸条")],
        ambient_hints=["后方有震动"],
        npc_appearances=[],
    )
    d = scene.to_dict()
    restored = SceneL1.from_dict(d, "6号车厢")
    assert restored.entry_narrative == "你醒来..."
    assert len(restored.perceptible) == 1
    assert restored.perceptible[0].type == "object"


def test_scene_l2_roundtrip():
    scene = SceneL2(
        scene_name="6号车厢",
        description="调查员醒来的车厢",
        encounters=[Encounter(enemy_ref="Clicker", quantity=1)],
        scene_weapons=[SceneWeapon(weapon_ref="手电筒", location="座位下")],
        hidden_info=[HiddenInfo(
            info="地板上有血迹",
            trigger_condition="skill:侦查>=50",
            reveal_narrative="你注意到地板缝隙中有暗红色的痕迹"
        )],
    )
    d = scene.to_dict()
    restored = SceneL2.from_dict(d, "6号车厢")
    assert restored.description == "调查员醒来的车厢"
    assert len(restored.encounters) == 1
    assert restored.encounters[0].enemy_ref == "Clicker"


def test_npc_profile_roundtrip():
    npc = NPCProfile(
        name="京山人吉",
        role="关键情报源",
        motivation="保护乘客安全",
        knowledge=["怪物对声音敏感", "钥匙在3号车厢"],
        personality="冷静但焦虑",
    )
    d = npc.to_dict()
    restored = NPCProfile.from_dict(d)
    assert restored.name == "京山人吉"
    assert "怪物对声音敏感" in restored.knowledge


def test_l3_designer_roundtrip():
    l3 = L3Designer(
        module_meta=ModuleMeta(title="常暗之厢", era="1920s"),
        world_rules=[WorldRule(id="WR1", name="无路可退", rule="后方车厢被吞噬，只能前进")],
        logic_chains=[],
        scene_intents={"6号车厢": SceneIntent(purpose="苏醒点", danger_level="safe")},
        driving_force="电车正被奈亚拉托提普的化身吞噬",
    )
    d = l3.to_dict()
    restored = L3Designer.from_dict(d)
    assert restored.driving_force == "电车正被奈亚拉托提普的化身吞噬"
    assert len(restored.world_rules) == 1
    assert restored.world_rules[0].id == "WR1"


def test_l1_save_load():
    scenes = {
        "test_scene": SceneL1(scene_name="test_scene", atmosphere="测试"),
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        from module_designer.l1_player import save_l1, load_l1
        save_l1(scenes, path)
        loaded = load_l1(path)
        assert "test_scene" in loaded
        assert loaded["test_scene"].atmosphere == "测试"
    finally:
        os.unlink(path)
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_module_designer.py -v`
Expected: 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/module_designer/ tests/test_module_designer.py
git commit -m "feat: add module_designer data models — L1/L2/L3 with roundtrip serialization"
```

---

### Task 6: JSON Templates + Validation Milestone 1

**Files:**
- Create: `data/templates/l1_template.json`
- Create: `data/templates/l2_template.json`
- Create: `data/templates/l3_template.json`

- [ ] **Step 1: Write L1 template**

Write `data/templates/l1_template.json`:

```json
{
  "6号车厢": {
    "entry_narrative": "调查员进入时的开场叙事文本...",
    "atmosphere": "场景氛围一句话描述",
    "mood": "uneasy",
    "perceptible": [
      {
        "type": "object",
        "name": "可感知物品名",
        "brief": "一句话描述",
        "linked_interaction": "关联的L2互动名（可选）"
      }
    ],
    "ambient_hints": ["微妙的环境线索"],
    "npc_appearances": [
      {
        "name": "NPC名称",
        "brief": "外貌描述",
        "demeanor": "神态举止"
      }
    ]
  }
}
```

- [ ] **Step 2: Write L2 template**

Write `data/templates/l2_template.json`:

```json
{
  "scenes": {
    "6号车厢": {
      "description": "场景功能性描述（KP用）",
      "from_here": [{"target": "目标场景", "method": "通行方式"}],
      "to_here": [{"source": "来源场景", "method": "通行方式"}],
      "interactions": [
        {
          "type": "调查",
          "name": "互动名称",
          "requirement": [],
          "trigger": "触发条件",
          "result": "结果描述",
          "clue": "线索（可选）",
          "side_effects": [],
          "skill_name": "关联技能（可选）",
          "difficulty": "regular"
        }
      ],
      "encounters": [
        {
          "enemy_ref": "library中敌人名",
          "trigger_condition": "触发条件",
          "initial_behavior": "初始行为",
          "quantity": 1,
          "notes": "备注（可选）",
          "extra": {}
        }
      ],
      "scene_weapons": [
        {
          "weapon_ref": "library中武器名",
          "location": "位置描述",
          "discovery_method": "发现方式",
          "extra": {}
        }
      ],
      "hidden_info": [
        {
          "info": "隐藏信息内容",
          "trigger_condition": "skill:侦查>=50",
          "linked_skill": "侦查",
          "reveal_narrative": "揭示时的叙事文本"
        }
      ],
      "extra": {}
    }
  },
  "events": [
    {
      "id": "E1",
      "name": "事件名称",
      "trigger": "触发描述",
      "irreversible_impact": "不可逆影响",
      "requirement": [],
      "extra": {}
    }
  ],
  "npc_profiles": {
    "NPC名称": {
      "name": "NPC名称",
      "role": "在故事中的角色",
      "motivation": "核心动机",
      "knowledge": ["NPC知道的信息"],
      "personality": "性格描述",
      "voice_notes": "说话风格（可选）",
      "notes": "KP备注（可选）",
      "extra": {}
    }
  }
}
```

- [ ] **Step 3: Write L3 template**

Write `data/templates/l3_template.json`:

```json
{
  "module_meta": {
    "title": "",
    "author": "",
    "era": "1920s",
    "theme": "",
    "expected_duration": "",
    "player_count": ""
  },
  "world_rules": [
    {
      "id": "WR1",
      "name": "规则名称",
      "rule": "规则描述（自然语言）",
      "scope": ["movement", "combat"],
      "is_absolute": true
    }
  ],
  "logic_chains": [
    {
      "id": "LC1",
      "name": "逻辑链名称",
      "description": "一句话描述",
      "nodes": ["节点1", "节点2"],
      "branches": [
        {
          "condition": "flag:has_key",
          "effect": "效果描述",
          "next_node": "节点3"
        }
      ],
      "is_critical": true
    }
  ],
  "scene_intents": {
    "6号车厢": {
      "purpose": "此场景的设计用途",
      "emotion": "目标情绪",
      "danger_level": "safe",
      "key_info": ["必须传达的关键信息"],
      "key_threat": "核心威胁（可选）",
      "exit_leads_to": ["可能的出口场景"],
      "notes": "设计备注（可选）"
    }
  },
  "ending_conditions": [
    {
      "id": "END1",
      "type": "escape",
      "condition": "触发条件表达式",
      "narrative_theme": "结局叙事主题"
    }
  ],
  "tone_constraints": {
    "genre": "克苏鲁恐怖",
    "forbidden": ["禁止出现的元素"],
    "required": ["必须包含的元素"],
    "narrative_style": "叙事风格描述"
  },
  "driving_force": "一切事件的底层驱动力（为什么这一切在发生）"
}
```

- [ ] **Step 4: Validation milestone — verify system integrity**

Run full import test:

```bash
python -c "
from module_designer import SceneL1, SceneL2, L3Designer
from library import WeaponLibrary, EnemyLibrary, JudgmentEngine, ContentInjector
from scenario_core import SpawnEnemy, GrantItem, EncounterAnchor, NPCStateChange, ScenarioWorld, DirectedGraph
print('All imports OK')
print('Library weapons:', len(WeaponLibrary()))
print('Module designer types verified')
"
```

- [ ] **Step 5: Commit**

```bash
git add data/templates/
git commit -m "feat: add L1/L2/L3 JSON templates + validation milestone 1"
```

---

## Remaining Tasks (Summary)

Due to plan length, Tasks 7-10 are summarized below. Full details will be added when each task is started.

### Task 7: Prompts Extension
Modify `src/prompts.py`:
- `build_improvise_prompt()`: add L3 `tone_constraints` + `driving_force` + L1 `atmosphere`/`mood` to prompt context
- `build_narrative_prompt()`: add L3 `tone_constraints` + L3 `scene_intents[scene].emotion` + L1 structured data
- `build_action_prompt()`: add `skill_name`/`difficulty` from Interaction if present

### Task 8: Game Loop Adaptation
Modify `src/game_loop.py`:
- `_apply_side_effects()`: add SpawnEnemy/GrantItem/NPCStateChange handling
- Phase 3.5: deviation detection + runtime injection hook
- Phase 5: L3-aware narrative generation
- `/spawn enemy <name>`, `/spawn weapon <name>`, `/inject toggle`, `/inject status` commands

### Task 9: Deprecate Old Parser/Pipeline
Archive `src/parsers.py` and `src/pipeline.py` (move to `src/archive/` or delete). Update any imports in notebooks.

### Task 10: Notebooks Adaptation
Update `notebooks/notebook_simplified.ipynb` and `notebooks/parser.ipynb` to use new layered_parser + module loading workflow.

---

## Self-Review

1. **Spec coverage**: Each section of the design doc maps to a task. Library (tasks 1-3), scenario_core (task 4), module_designer (tasks 5-6), prompts (task 7), game_loop (task 8), deprecation (task 9), notebooks (task 10). Missing: fallback strategy and testing strategy — these are noted as items 6-7 in the schema overview's "next steps" and will be addressed during Task 7 (prompts extension) and as a cross-cutting concern.

2. **Placeholder scan**: No TBD/TODO in the plan. All steps have concrete code. Tasks 7-10 are summarized due to plan length but have clear scope descriptions.

3. **Type consistency**: `LibraryWeapon`/`LibraryEnemy` defined in Task 1, used in Tasks 2-3. `SpawnEnemy`/`GrantItem`/etc defined in Task 4, used in Task 8. `SceneL1`/`SceneL2`/`L3Designer` defined in Task 5, used in Tasks 6-7.

Plan saved. Ready for execution handoff.
