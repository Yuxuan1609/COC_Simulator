"""物品库数据类 + 加载器（统一资源层，同武器库模式）."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import os

from library.spells import _normalize_effect


@dataclass
class LibraryItem:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "misc"            # consumable/tool/document/clothing/key/misc
    description: str = ""
    impact: str = "L1"                # L0/L1/L2 默认档（库预标注）
    use_semantic: str = "none"        # consume/equip/read/tool/none
    stackable: bool = True
    check: Optional[dict] = None      # {"skill": "...", "type": "regular|hard|opposed"}
    on_use: list[str] = field(default_factory=list)   # @markup 序列
    on_success: str = ""
    on_failure: str = ""
    on_hard: str = ""
    on_extreme: str = ""
    refund_on_fail: bool = False
    constraints: dict = field(default_factory=dict)
    effect: list = field(default_factory=list)   # effect 原子数组(2026-08-21 spec §1.1)

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryItem":
        return cls(
            id=str(data.get("id", data.get("name", ""))),
            name=data.get("name", ""),
            aliases=list(data.get("aliases", []) or []),
            category=data.get("category", "misc"),
            description=data.get("description", ""),
            impact=data.get("impact", "L1"),
            use_semantic=data.get("use_semantic", "none"),
            stackable=bool(data.get("stackable", True)),
            check=data.get("check") or None,
            on_use=list(data.get("on_use", []) or []),
            on_success=data.get("on_success", ""),
            on_failure=data.get("on_failure", ""),
            on_hard=data.get("on_hard", ""),
            on_extreme=data.get("on_extreme", ""),
            refund_on_fail=bool(data.get("refund_on_fail", False)),
            constraints=dict(data.get("constraints", {}) or {}),
            effect=_normalize_effect(data.get("effect")),
        )

    def matches(self, ref: str) -> bool:
        return ref in (self.id, self.name) or ref in self.aliases


class ItemLibrary:
    """物品库 -- core + extensions，id/名称/别名三路查询."""

    def __init__(self):
        self._items: dict[str, LibraryItem] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "data", "library", "core", "items.json")
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"库文件加载失败: {path}") from e
        if not isinstance(data, dict):
            raise ValueError(f"库文件格式错误(顶层应为 object): {path}")
        for item in data.get("items", []):
            li = LibraryItem.from_dict(item)
            self._items[li.id] = li

    def get(self, ref: str) -> Optional[LibraryItem]:
        for it in self._items.values():
            if it.matches(ref):
                return it
        return None

    def list_all(self) -> list[LibraryItem]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
