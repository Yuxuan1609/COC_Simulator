"""TurnRunner：回合编排器（五宏阶段 + Restart 循环）。"""
from __future__ import annotations

from config import MAX_ESCALATION_DEPTH
from monitor.turn_monitor import TurnFrozenError
from .context import TurnContext, TurnAccumulator, Early, Restart


class TurnRunner:
    def __init__(self, keeper):
        self.keeper = keeper

    def execute(self, turn_input, author=None, debug=False, on_phase=None):
        from .understand import phase_a_understand
        from .adjudicate import phase_b_adjudicate
        from .encounter import phase_c_encounter
        from .enrich import phase_d_enrich
        from .finalize import phase_e_finalize
        tools = self.keeper
        depth = 0
        trace = [] if debug else None
        # Restart 重跑会重复推相位（允许，前端按最新状态覆盖）。
        phases = (
            ("understand", phase_a_understand),
            ("adjudicate", phase_b_adjudicate),
            ("encounter", phase_c_encounter),
            ("enrich", phase_d_enrich),
            ("finalize", phase_e_finalize),
        )
        while True:
            ctx = TurnContext(turn_input=turn_input, author=author, depth=depth,
                              raw=turn_input.raw_text, trace=trace)
            self.keeper._turn_trace = trace
            judge = getattr(self.keeper, "judge", None)
            if judge is not None:
                judge._turn_trace = trace
            acc = TurnAccumulator()
            try:
                for name, phase in phases:
                    if on_phase:
                        on_phase(name, "start")
                    r = phase(ctx, acc, tools)
                    if on_phase:
                        on_phase(name, "done")
                    if isinstance(r, Early):
                        return r.result
                    if isinstance(r, Restart):
                        tools._apply_pending()   # 保持现语义：重入前落账
                        break
                else:
                    return acc.result
            except TurnFrozenError as e:
                return tools._build_frozen_response(e)
            depth += 1
            if depth >= MAX_ESCALATION_DEPTH:
                return tools._process_deterministic_only(turn_input)
