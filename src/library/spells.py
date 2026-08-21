"""法术库数据类 + 加载器（统一资源层）."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import os


def _normalize_effect(raw) -> list:
    """旧单 dict 自动包装为 [dict];None/缺省 -> [];list 透传(浅拷贝防外部篡改)。"""
    if not raw:
        return []
    if isinstance(raw, dict):
        return [dict(raw)]
    return [dict(e) for e in raw if isinstance(e, dict)]


@dataclass
class LibrarySpell:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "exploration"     # combat / exploration
    description: str = ""
    impact: str = "L1"
    cost: dict = field(default_factory=lambda: {"mp": 0, "san": 0})
    check: Optional[dict] = None      # {"skill": "POW", "type": "regular|hard|opposed"}
    on_use: list[str] = field(default_factory=list)
    on_success: str = ""
    on_failure: str = ""
    on_hard: str = ""
    on_extreme: str = ""
    refund_on_fail: bool = False
    constraints: dict = field(default_factory=dict)
    effect: list = field(default_factory=list)   # effect 原子数组(2026-08-21 spec §1.1);旧单 dict 归一化包装
    weight: str = "light"

    @classmethod
    def from_dict(cls, data: dict) -> "LibrarySpell":
        return cls(
            id=str(data.get("id", data.get("name", ""))),
            name=data.get("name", ""),
            aliases=list(data.get("aliases", []) or []),
            category=data.get("category", "exploration"),
            description=data.get("description", ""),
            impact=data.get("impact", "L1"),
            cost=dict(data.get("cost", {}) or {"mp": 0, "san": 0}),
            check=data.get("check") or None,
            on_use=list(data.get("on_use", []) or []),
            on_success=data.get("on_success", ""),
            on_failure=data.get("on_failure", ""),
            on_hard=data.get("on_hard", ""),
            on_extreme=data.get("on_extreme", ""),
            refund_on_fail=bool(data.get("refund_on_fail", False)),
            constraints=dict(data.get("constraints", {}) or {}),
            effect=_normalize_effect(data.get("effect")),
            weight=data.get("weight", "light"),
        )

    def matches(self, ref: str) -> bool:
        return ref in (self.id, self.name) or ref in self.aliases


class SpellLibrary:
    """法术库 -- core + extensions."""

    def __init__(self):
        self._spells: dict[str, LibrarySpell] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "data", "library", "core", "spells.json")
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for sp in data.get("spells", []):
            ls = LibrarySpell.from_dict(sp)
            self._spells[ls.id] = ls

    def get(self, ref: str) -> Optional[LibrarySpell]:
        for sp in self._spells.values():
            if sp.matches(ref):
                return sp
        return None

    def list_all(self) -> list[LibrarySpell]:
        return list(self._spells.values())

    def __len__(self) -> int:
        return len(self._spells)
