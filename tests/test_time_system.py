"""Tests for time system — deterministic, no LLM dependency."""
import json
import os
import pytest
from scenario_core import DirectedGraph, ScenarioWorld


@pytest.fixture
def world():
    return ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")


def test_clock_defaults(world):
    assert world.game_time == 0
    assert world.day == 0
    assert world.hour == 0
    assert world.time_of_day == "夜间"


def test_advance_time_minutes(world):
    world.advance_time(300)  # 5 hours
    assert world.game_time == 300
    assert world.day == 0
    assert world.hour == 5
    assert world.time_of_day == "早晨"


def test_advance_time_cross_day(world):
    world.advance_time(1500)  # 25 hours
    assert world.day == 1
    assert world.time_of_day == "夜间"


def test_time_of_day_transitions(world):
    assert world.time_of_day == "夜间"   # 0:00
    world.advance_time(300)             # 5:00
    assert world.time_of_day == "早晨"
    world.advance_time(180)             # 8:00
    assert world.time_of_day == "白天"
    world.advance_time(540)             # 17:00
    assert world.time_of_day == "黄昏"
    world.advance_time(180)             # 20:00
    assert world.time_of_day == "夜间"


def test_time_flags(world):
    flags = world.get_time_flags()
    assert flags["day:0"] is True
    assert flags["time:夜间"] is True


def test_time_flags_in_runtime_state(world):
    world.advance_time(480)  # 8:00, 白天
    state = world.get_runtime_state("time:白天")
    assert state.completed is True


def test_time_costs_file_exists():
    path = "data/library/core/time_costs.json"
    assert os.path.exists(path), f"{path} not found"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "search" in data
    assert "move" in data
    assert "guideline" in data["search"]


def test_time_costs_all_categories():
    path = "data/library/core/time_costs.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for cat in ("search", "move", "dialogue", "combat_round", "other"):
        assert cat in data, f"Missing category: {cat}"
        assert "guideline" in data[cat], f"Missing guideline in {cat}"
