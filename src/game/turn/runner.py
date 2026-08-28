"""TurnRunner：回合编排器。W0 为委托壳，W6 起为循环编排器。"""
from __future__ import annotations

from monitor.turn_monitor import TurnFrozenError


class TurnRunner:
    def __init__(self, keeper):
        self.keeper = keeper

    def execute(self, turn_input, author=None):
        try:
            return self.keeper._run_turn_pipeline(turn_input, author, 0)
        except TurnFrozenError as e:
            return self.keeper._build_frozen_response(e)
