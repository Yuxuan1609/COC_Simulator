"""F5 疯狂体系核心：on_san_loss 钩子 + insanity 字段入档（S3-P2 spec §1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_player(san=50, int_val=60):
    from helpers import make_world, make_scene
    from investigator import Investigator
    world = make_world({"room_a": make_scene()}, "room_a")
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.derived.SAN = san
    inv.stats.INT = int_val
    world.set_player(inv)
    return world, inv


def _force_roll(monkeypatch, value):
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: value)


class TestOnSanLoss:
    def test_accumulates_daily_loss(self):
        world, inv = _world_with_player()
        world.on_san_loss(3, "markup")
        world.on_san_loss(2, "markup")
        assert inv.insanity["san_lost_today"] == 5
        assert inv.insanity["san_day"] == world.clock.day

    def test_lazy_reset_on_day_change(self):
        world, inv = _world_with_player(san=50)
        world.on_san_loss(2, "markup")
        world.advance_time(1440)
        world.on_san_loss(4, "markup")
        assert inv.insanity["san_lost_today"] == 4
        assert inv.insanity["san_at_day_start"] == 50

    def test_single_loss_ge5_triggers_temporary_on_int_fail(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 100)
        result = world.on_san_loss(5, "markup")
        assert result["temporary"] is True
        assert inv.insanity["temporary"]

    def test_single_loss_ge5_int_success_no_temporary(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(5, "markup")
        assert result["temporary"] is False
        assert not inv.insanity.get("temporary")

    def test_temporary_not_retriggered(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 100)
        world.on_san_loss(5, "markup")
        first_text = inv.insanity["temporary"]
        result = world.on_san_loss(6, "markup")
        assert result["temporary"] is False
        assert inv.insanity["temporary"] == first_text

    def test_cumulative_triggers_indefinite(self, monkeypatch):
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(10, "markup")
        assert result["indefinite"] is True
        assert inv.insanity["indefinite"]

    def test_cumulative_below_threshold_no_indefinite(self, monkeypatch):
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(9, "markup")
        assert result["indefinite"] is False

    def test_zero_or_negative_loss_noop(self):
        world, inv = _world_with_player()
        result = world.on_san_loss(0, "markup")
        assert result == {"temporary": False, "indefinite": False}
        assert not inv.insanity

    def test_markup_san_loss_flows_to_hook(self, monkeypatch):
        from game.side_effects import StatChange
        from scenario_core import apply_side_effects
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        apply_side_effects(world, [StatChange(stat_name="SAN", delta=-3)])
        assert inv.derived.SAN == 47
        assert inv.insanity["san_lost_today"] == 3

    def test_insanity_serialization_roundtrip(self):
        from investigator.serialization import to_dict, from_dict
        world, inv = _world_with_player()
        inv.insanity = {"temporary": "幻觉丛生", "san_lost_today": 6, "san_day": 1}
        inv2 = from_dict(to_dict(inv))
        assert inv2.insanity["temporary"] == "幻觉丛生"
        assert inv2.insanity["san_lost_today"] == 6

    def test_insanity_default_missing_key(self):
        from investigator.serialization import to_dict, from_dict
        world, inv = _world_with_player()
        data = to_dict(inv)
        data.pop("insanity", None)
        inv2 = from_dict(data)
        assert inv2.insanity == {}
