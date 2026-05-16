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
    description: str = ""

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
            "description": self.description,
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
            description=data.get("description", ""),
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
