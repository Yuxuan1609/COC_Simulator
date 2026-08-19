"""UseParser -- use 大类的独立小型 parse 系统（统一资源层）。

待解析内容可换：MaterialCatalog 协议注入（ItemCatalog/SpellCatalog/未来素材源）。
确定性层优先（谓词 + 名称匹配），LLM 兜底（resolve_llm）。
输出标准化为 UseParseResult，on_use 编译为 @markup 序列，走 apply_side_effects 执行。
"""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol


USE_VERBS = ("使用", "服用", "施放", "施展", "念诵", "吟唱", "咏唱", "佩戴", "戴上",
             "翻阅", "涂抹", "喝", "饮", "吃", "敷", "用", "施法", "阅读", "翻开",
             "点燃", "打开")

_NEGATION_RE = re.compile(r"(不|别|无须|无需|没有|没法)")


@dataclass
class UseParseResult:
    catalog_kind: str          # "item" | "spell"（描述性）
    material_id: str
    name: str
    matched_text: str
    impact: str                # L0 / L1 / L2
    check: Optional[dict] = None
    cost: dict = field(default_factory=lambda: {"mp": 0, "san": 0})
    on_use: list[str] = field(default_factory=list)
    result_slots: dict = field(default_factory=dict)
    refund_on_fail: bool = False
    use_semantic: str = "none"
    constraints: dict = field(default_factory=dict)


class MaterialCatalog(Protocol):
    def entries(self) -> list[dict]:
        """返回可解析条目：{id, name, aliases, kind, description, impact, ...}"""
        ...


class ItemCatalog:
    """物品目录：ItemLibrary ∩ 玩家背包（仅持有物可用）。"""

    def __init__(self, item_lib, inventory):
        self._lib = item_lib
        self._inv = inventory

    def entries(self) -> list[dict]:
        out = []
        if not (self._lib and self._inv):
            return out
        for it in self._inv.list_all():
            li = self._lib.get(it.name)
            if li is None:
                continue   # 自由文本物品无库元数据，不进机械使用通路
            out.append({
                "id": li.id, "name": li.name, "aliases": list(li.aliases),
                "kind": "item", "description": li.description, "impact": li.impact,
                "check": li.check, "cost": {"mp": 0, "san": 0},
                "on_use": list(li.on_use),
                "result_slots": {"on_success": li.on_success, "on_failure": li.on_failure,
                                 "on_hard": li.on_hard, "on_extreme": li.on_extreme},
                "refund_on_fail": li.refund_on_fail,
                "use_semantic": li.use_semantic,
                "constraints": dict(li.constraints),
            })
        return out


class SpellCatalog:
    """法术目录：SpellLibrary ∩ known_spells。"""

    def __init__(self, spell_lib, known_spells: list[str]):
        self._lib = spell_lib
        self._known = known_spells

    def entries(self) -> list[dict]:
        out = []
        if not self._lib:
            return out
        for sid in self._known:
            sp = self._lib.get(sid)
            if sp is None:
                continue
            out.append({
                "id": sp.id, "name": sp.name, "aliases": list(sp.aliases),
                "kind": "spell", "description": sp.description, "impact": sp.impact,
                "check": sp.check, "cost": dict(sp.cost),
                "on_use": list(sp.on_use),
                "result_slots": {"on_success": sp.on_success, "on_failure": sp.on_failure,
                                 "on_hard": sp.on_hard, "on_extreme": sp.on_extreme},
                "refund_on_fail": sp.refund_on_fail,
                "use_semantic": "cast",
                "constraints": dict(sp.constraints),
            })
        return out


def _best_material_match(raw: str, entries: list[dict]):
    """精确 -> 包含 -> difflib(>=0.6) 三级匹配，返回 (entry, matched_text) 或 None。"""
    best = None
    best_score = 0.0
    for e in entries:
        candidates = [e["name"]] + list(e.get("aliases", []))
        for cand in candidates:
            if not cand:
                continue
            if cand == raw:
                return e, cand
            if cand in raw:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, cand, raw).ratio()
            if score > best_score:
                best_score = score
                best = (e, cand)
    if best_score >= 0.6:
        return best
    return None


class UseParser:
    def __init__(self, llm_call=None):
        self.llm_call = llm_call   # 可注入（keeper/测试）；None 时 LLM 兜底不可用

    # ── 确定性层 ──
    def resolve(self, raw: str, catalogs: list[MaterialCatalog]) -> Optional[UseParseResult]:
        if not raw or not catalogs:
            return None
        if _NEGATION_RE.search(raw):
            return None
        if not any(v in raw for v in USE_VERBS):
            return None
        entries = [e for c in catalogs for e in c.entries()]
        hit = _best_material_match(raw, entries)
        if hit is None:
            return None
        e, matched = hit
        return UseParseResult(
            catalog_kind=e["kind"], material_id=e["id"], name=e["name"],
            matched_text=matched, impact=e["impact"], check=e.get("check"),
            cost=dict(e.get("cost") or {"mp": 0, "san": 0}),
            on_use=list(e.get("on_use") or []),
            result_slots=dict(e.get("result_slots") or {}),
            refund_on_fail=bool(e.get("refund_on_fail", False)),
            use_semantic=e.get("use_semantic", "none"),
            constraints=dict(e.get("constraints") or {}),
        )

    # ── LLM 兜底层（Task 6 实现）──
    def resolve_llm(self, raw: str, catalogs: list[MaterialCatalog]) -> Optional[UseParseResult]:
        return None
