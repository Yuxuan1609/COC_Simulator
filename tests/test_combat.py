"""Unit tests for combat system logic (no LLM calls)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game.combat import (
    _roll_damage, _apply_armor,
    CombatSystem, CombatState, CombatAction,
)
from game.messages import CombatResult


def test_roll_damage_simple():
    for _ in range(20):
        d = _roll_damage("1D6", 50, 50)
        assert 1 <= d <= 6, f"1D6 out of range: {d}"

def test_roll_damage_with_db():
    d = _roll_damage("1D3+DB", 130, 130)
    assert d >= 1, f"1D3+DB should be >= 1, got {d}"

def test_roll_damage_negative_db():
    d = _roll_damage("1D6+DB", 30, 30)
    assert d >= 0, f"1D6+DB with weak stats should be >= 0, got {d}"

def test_apply_armor():
    assert _apply_armor(5, "2点厚皮") == 3
    assert _apply_armor(1, "2点厚皮") == 0
    assert _apply_armor(10, "") == 10
    assert _apply_armor(3, "无护甲") == 3

def test_combat_state_init():
    state = CombatState()
    assert state.round == 1
    assert state.finished == False
    assert state.log == []

def test_combat_action_defaults():
    a = CombatAction()
    assert a.actor == ""
    assert a.success == False
    assert a.damage == 0

def test_combat_result():
    r = CombatResult(outcome="win", defeated_instance_ids=["e1"],
                    player_hp=10, player_san=50, rounds=3)
    assert r.outcome == "win"
    assert r.defeated_instance_ids == ["e1"]
    assert r.rounds == 3

def test_combat_system_init():
    cs = CombatSystem()
    assert cs.weapon_lib is None

def test_get_tier():
    cs = CombatSystem()
    assert cs._get_tier(1, 50) == "extreme"
    assert cs._get_tier(5, 50) == "extreme"   # <= 50/5=10
    assert cs._get_tier(15, 50) == "hard"      # <= 50/2=25
    assert cs._get_tier(40, 50) == "regular"

def test_damage_formula_parsing():
    """Exercise various damage formulas."""
    for _ in range(20):
        d = _roll_damage("2D6", 50, 50)
        assert 2 <= d <= 12, f"2D6: {d}"
        d = _roll_damage("1D10+2", 50, 50)
        assert 3 <= d <= 12, f"1D10+2: {d}"
    # Fixed damage (no D)
    d = _roll_damage("3", 50, 50)
    assert d == 3


if __name__ == "__main__":
    test_roll_damage_simple()
    test_roll_damage_with_db()
    test_roll_damage_negative_db()
    test_apply_armor()
    test_combat_state_init()
    test_combat_action_defaults()
    test_combat_result()
    test_combat_system_init()
    test_get_tier()
    test_damage_formula_parsing()
    print("All tests passed")
