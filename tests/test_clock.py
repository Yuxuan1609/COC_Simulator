import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from game.clock import GameClock


def test_time_of_day_bands():
    cases = [
        (0, "凌晨"), (4 * 60 + 59, "凌晨"),
        (5 * 60, "早晨"), (7 * 60 + 59, "早晨"),
        (8 * 60, "白天"), (16 * 60 + 59, "白天"),
        (17 * 60, "黄昏"), (19 * 60 + 59, "黄昏"),
        (20 * 60, "夜间"), (23 * 60 + 59, "夜间"),
    ]
    for minutes, expected in cases:
        c = GameClock(start_time=minutes)
        assert c.time_of_day == expected, f"{minutes}m hour={c.hour} got {c.time_of_day}"


def test_get_time_flags_uses_lingchen():
    c = GameClock(start_time=60)  # 01:00
    flags = c.get_time_flags()
    assert flags.get("time:凌晨") is True
    assert "time:夜间" not in flags
