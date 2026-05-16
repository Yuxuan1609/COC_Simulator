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
    description: str = ""

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
            "description": self.description,
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
            description=data.get("description", ""),
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
