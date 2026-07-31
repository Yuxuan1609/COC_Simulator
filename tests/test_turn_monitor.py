"""TurnMonitor unit tests — no LLM calls needed."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import MagicMock
from monitor.turn_monitor import TurnMonitor, StepResult, TurnFrozenError


class TestStepResult:
    def test_defaults(self):
        sr = StepResult(step="test")
        assert sr.step == "test"
        assert sr.status == "pending"
        assert sr.retries == 0
        assert sr.duration_ms == 0.0
        assert sr.error == ""


class TestTurnMonitorExecuteStep:
    def test_successful(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        world.graph = MagicMock()
        world.graph.to_dict.return_value = {"nodes": {}}
        world.memory = MagicMock()
        world.memory.to_dict.return_value = {}
        world.player = None

        tm = TurnMonitor(sensor, world)
        result = tm.execute_step("parse", lambda: "parsed_result")

        assert result == "parsed_result"
        assert len(tm._steps) == 1
        assert tm._steps[0].step == "parse"
        assert tm._steps[0].status == "ok"

    def test_retry_then_success(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        tm = TurnMonitor(sensor, world)

        call_count = [0]

        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient")
            return "finally ok"

        result = tm.execute_step("parse", flaky_fn, max_retries=2)
        assert result == "finally ok"
        step = tm._steps[0]
        assert step.status == "ok"
        assert step.retries == 2

    def test_critical_fails_triggers_frozen(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        world.graph = MagicMock()
        world.graph.to_dict.return_value = {"nodes": {}}
        world.memory = MagicMock()
        world.memory.to_dict.return_value = {}
        world.__class__.from_dict = MagicMock(return_value=MagicMock())
        world.save_state = MagicMock()

        def always_fail():
            raise RuntimeError("critical error")

        tm = TurnMonitor(sensor, world)
        tm.begin_turn()

        with pytest.raises(TurnFrozenError):
            tm.execute_step("curate", always_fail, is_critical=True, max_retries=2)

        assert tm._steps[0].status == "failed"
        assert tm._steps[0].retries == 2
        assert "curate" in tm._freeze_message
        assert "critical error" in tm._freeze_message
        # freeze 不再自动存档（72e95a2 起），玩家按提示 /load 恢复
        world.save_state.assert_not_called()

    def test_non_critical_returns_none(self):
        sensor = MagicMock()
        world = MagicMock()
        tm = TurnMonitor(sensor, world)

        def fail():
            raise RuntimeError("non-critical")

        result = tm.execute_step("enrich", fail, is_critical=False, max_retries=1)
        assert result is None
        assert tm._steps[0].status == "failed"


class TestTurnMonitorSnapshot:
    def test_structure(self):
        sensor = MagicMock()
        sensor.history = []
        stats = MagicMock()
        stats.total_calls = 10
        stats.total_failures = 1
        stats.total_slow_calls = 2
        stats.avg_duration_ms = 1500.0
        stats.failure_rate = 0.1
        stats.slow_rate = 0.2
        sensor.get_stats.return_value = stats
        sensor._slow_threshold_ms = 8000
        world = MagicMock()
        tm = TurnMonitor(sensor, world)

        snap = tm.snapshot()
        assert "llm" in snap
        assert "turn" in snap
        assert "steps" in snap["turn"]
        assert not snap["turn"]["frozen"]

    def test_after_freeze(self):
        sensor = MagicMock()
        sensor.history = []
        stats = MagicMock()
        stats.total_calls = 0
        stats.total_failures = 0
        stats.total_slow_calls = 0
        stats.avg_duration_ms = 0.0
        stats.failure_rate = 0.0
        stats.slow_rate = 0.0
        sensor.get_stats.return_value = stats
        sensor._slow_threshold_ms = 8000
        world = MagicMock()
        world.to_dict.return_value = {}
        world.graph = MagicMock()
        world.graph.to_dict.return_value = {"nodes": {}}
        world.memory = MagicMock()
        world.memory.to_dict.return_value = {}
        world.player = None
        world.__class__.from_dict = MagicMock(return_value=MagicMock())
        world.save_state = MagicMock()

        tm = TurnMonitor(sensor, world)
        tm.begin_turn()

        try:
            tm.execute_step("parse", lambda: 1/0, is_critical=True, max_retries=0)
        except TurnFrozenError:
            pass

        snap = tm.snapshot()
        assert snap["turn"]["frozen"] is True
        assert len(snap["turn"]["freeze_message"]) > 0
