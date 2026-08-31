"""F8：恢复生态——跨日界结算，速率 config 化。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_player(hp=10, san=50):
    from helpers import make_world, make_scene
    from investigator import Investigator
    world = make_world({"room_a": make_scene()}, "room_a")
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.derived.HP = hp
    inv.derived.HP_MAX = 20
    inv.derived.SAN = san
    world.set_player(inv)
    return world, inv


class TestDailyRecovery:
    def test_hp_recovers_per_day(self):
        """跨 1 天 → HP+1（默认 hp_recovery_per_day=1）。"""
        world, inv = _world_with_player()
        world.advance_time(1440)
        assert inv.derived.HP == 11

    def test_hp_clamped_at_max(self):
        """恢复不超过 HP_MAX。"""
        world, inv = _world_with_player()
        inv.derived.HP = inv.derived.HP_MAX
        world.advance_time(1440)
        assert inv.derived.HP == inv.derived.HP_MAX

    def test_san_default_no_recovery(self):
        """SAN 默认 san_recovery_per_day=0 → 跨天不恢复。"""
        world, inv = _world_with_player()
        world.advance_time(1440)
        assert inv.derived.SAN == 50

    def test_san_recovery_configurable(self, monkeypatch):
        """config 覆盖 san_recovery_per_day=2 → 跨 1 天 SAN+2（上限 SAN_MAX）。"""
        world, inv = _world_with_player()
        import investigator.rules as rules
        cfg = dict(rules.get_game_config())
        cfg["san_recovery_per_day"] = 2
        monkeypatch.setattr(rules, "get_game_config", lambda: cfg)
        monkeypatch.setattr("investigator.rules.get_game_config", lambda: cfg)
        world.advance_time(1440)
        assert inv.derived.SAN == 52

    def test_partial_day_no_recovery(self):
        """未跨日界不结算。"""
        world, inv = _world_with_player()
        world.advance_time(60)
        assert inv.derived.HP == 10

    def test_multi_day(self):
        """跨 2 天 → HP+2。"""
        world, inv = _world_with_player()
        world.advance_time(2880)
        assert inv.derived.HP == 12
