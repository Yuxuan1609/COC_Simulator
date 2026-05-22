"""GameClock unit tests — no LLM dependency."""
import pytest
from game.clock import GameClock


@pytest.fixture
def clock():
    return GameClock()


def test_defaults(clock):
    assert clock.game_time == 0
    assert clock.day == 0
    assert clock.hour == 0
    assert clock.time_of_day == "夜间"


def test_advance_minutes(clock):
    clock.advance_time(300)
    assert clock.game_time == 300
    assert clock.day == 0
    assert clock.hour == 5
    assert clock.time_of_day == "早晨"


def test_advance_cross_day(clock):
    clock.advance_time(1500)
    assert clock.day == 1
    assert clock.hour == 1
    assert clock.time_of_day == "夜间"


def test_time_of_day_transitions(clock):
    assert clock.time_of_day == "夜间"
    clock.advance_time(300)
    assert clock.time_of_day == "早晨"
    clock.advance_time(180)
    assert clock.time_of_day == "白天"
    clock.advance_time(540)
    assert clock.time_of_day == "黄昏"
    clock.advance_time(180)
    assert clock.time_of_day == "夜间"


def test_time_flags(clock):
    flags = clock.get_time_flags()
    assert flags == {"day:0": True, "time:夜间": True}


def test_time_flags_after_advance(clock):
    clock.advance_time(480)
    flags = clock.get_time_flags()
    assert flags == {"day:0": True, "time:白天": True}


def test_advance_zero(clock):
    clock.advance_time(0)
    assert clock.game_time == 0


def test_advance_midnight_boundary(clock):
    clock.advance_time(1440)
    assert clock.day == 1
    assert clock.hour == 0
    assert clock.time_of_day == "夜间"


def test_serialization_roundtrip(clock):
    clock.advance_time(360)
    clock.time_context = "天色渐暗"
    data = clock.to_dict()
    restored = GameClock.from_dict(data)
    assert restored.game_time == 360
    assert restored.time_context == "天色渐暗"
    assert restored.time_of_day == clock.time_of_day


def test_separate_instances(clock):
    """Verify two clocks don't share state."""
    c2 = GameClock(start_time=100)
    clock.advance_time(50)
    assert c2.game_time == 100
