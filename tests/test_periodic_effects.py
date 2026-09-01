"""F10 周期性/环境效应：timed 条目 interval+payload（S3-P2 spec §4）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_player(hp=10):
    from helpers import make_world, make_scene
    from investigator import Investigator
    world = make_world({"room_a": make_scene()}, "room_a")
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.derived.HP = hp
    inv.derived.HP_MAX = 20
    inv.derived.SAN = 50
    world.set_player(inv)
    return world, inv


class TestPeriodicEffects:
    def test_no_interval_legacy_behavior(self):
        """无 interval 条目维持现状：只到期清除，不结算。"""
        world, inv = _world_with_player()
        inv.timed_effects.append({"id": "雾", "description": "浓雾",
                                  "expire_at": world.clock.game_time + 120})
        world.advance_time(60)
        assert inv.derived.HP == 10
        assert len(inv.timed_effects) == 1

    def test_hourly_payload_fires_per_crossing(self):
        """interval=hour + heal payload：推进 150 分钟 → 结算 2 次。"""
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "疗养", "description": "", "interval": "hour",
            "expire_at": world.clock.game_time + 300,
            "payload": [{"type": "heal", "delta": 1}],
        })
        world.advance_time(150)
        assert inv.derived.HP == 12

    def test_daily_payload(self):
        """interval=day：跨 2 天 → 结算 2 次（叠加 F8 日界 HP+2）。"""
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "诅咒", "description": "", "interval": "day",
            "expire_at": world.clock.game_time + 3000,
            "payload": [{"type": "heal", "delta": 1}],
        })
        world.advance_time(2880)
        assert inv.derived.HP == 14

    def test_payload_stops_after_expiry(self):
        """到期条目不再结算且被清除。"""
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "毒", "description": "", "interval": "hour",
            "expire_at": world.clock.game_time + 60,
            "payload": [{"type": "heal", "delta": 1}],
        })
        world.advance_time(300)
        assert inv.derived.HP == 11
        assert inv.timed_effects == []

    def test_san_payload_flows_to_insanity_hook(self):
        """payload 中 SAN 损失汇入 F5 钩子。"""
        world, inv = _world_with_player()
        inv.timed_effects.append({
            "id": "雾中恐惧", "description": "", "interval": "hour",
            "expire_at": world.clock.game_time + 300,
            "payload": [{"type": "markup",
                         "text": '@stat_change(stat_name="SAN", delta=-2)'}],
        })
        world.advance_time(120)
        assert inv.insanity["san_lost_today"] == 4

    def test_hourly_split_advances_accumulate(self):
        """三次 advance_time(50) 累计 150 分钟，hourly heal+1 应结算 2 次。"""
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "疗养", "description": "", "interval": "hour",
            "expire_at": world.clock.game_time + 300,
            "payload": [{"type": "heal", "delta": 1}],
        })
        world.advance_time(50)
        world.advance_time(50)
        world.advance_time(50)
        assert inv.derived.HP == 12

    def test_timed_atom_mounts_interval_payload(self):
        """timed 原子挂载须保留 interval+payload，advance 后 payload 结算。"""
        from game.judge import Judge
        world, inv = _world_with_player(hp=10)
        Judge(world)._execute_effect_atoms([{
            "type": "timed", "id": "疗养", "description": "",
            "minutes": 300, "interval": "hour",
            "payload": [{"type": "heal", "delta": 1}],
        }], inv)
        te = inv.timed_effects[0]
        assert te.get("interval") == "hour"
        assert te.get("payload") == [{"type": "heal", "delta": 1}]
        world.advance_time(150)
        assert inv.derived.HP == 12

    def test_payload_atom_failure_isolates_later_atoms(self):
        """坏 markup 原子不阻断后续 heal（per-atom 隔离）。"""
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "混杂", "description": "", "interval": "hour",
            "expire_at": world.clock.game_time + 300,
            "payload": [
                {"type": "markup",
                 "text": '@item_gain(item_name="x", quantity="garbage")'},
                {"type": "heal", "delta": 1},
            ],
        })
        world.advance_time(60)
        assert inv.derived.HP == 11

    def test_round_interval_fires_on_combat_tick(self):
        """interval=round 在战斗轮末 tick 各结算一次，两次 tick → HP+2。"""
        from game.combat import CombatSystem, CombatState
        world, inv = _world_with_player(hp=10)
        inv.timed_effects.append({
            "id": "毒雾", "description": "", "interval": "round",
            "expire_at": world.clock.game_time + 9999,
            "payload": [{"type": "heal", "delta": 1}],
        })
        cs = CombatSystem(world=world)
        state = CombatState()
        cs._tick_temporary_effects(state)
        cs._tick_temporary_effects(state)
        assert inv.derived.HP == 12
