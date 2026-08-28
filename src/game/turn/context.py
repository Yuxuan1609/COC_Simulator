"""回合管线契约：上下文、累积器、控制信号。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from ..messages import EnrichInput, TurnInput, TurnResult


@dataclass
class TurnContext:
    """输入侧（只读）。raw 可被 pre_parse 改写。"""
    turn_input: TurnInput
    author: Any = None
    depth: int = 0
    raw: str = ""


@dataclass
class TurnAccumulator:
    """产出侧累积（= 原 process_turn 局部变量显式分组）。"""
    pre_result: Any = None
    parse_result: list = field(default_factory=list)
    npc_interact_entries: list = field(default_factory=list)
    other_entries: list = field(default_factory=list)
    detect_future: Any = None
    executor: Any = None
    all_outcomes: list = field(default_factory=list)
    enrich_input: EnrichInput = field(default_factory=EnrichInput)
    combat_entry: Any = None
    standoff_prompt: dict | None = None
    combat_init_result: Any = None
    boss_accounting: tuple | None = None       # (boss_engaged_id, boss_enemy)，E 在 curate 后消费
    enrichment: dict | None = None
    ta_result: dict | None = None
    emphasis: str = ""
    enriched_summary: str = ""
    ending_result: dict | None = None
    brief: Any = None
    result: TurnResult | None = None


@dataclass
class Early:
    """阶段早退信号：携带完整 TurnResult，编排器直接返回。"""
    result: TurnResult


class Restart:
    """作者门接受 → 编排器落账后从 A 重跑（循环，非递归调用）。"""
