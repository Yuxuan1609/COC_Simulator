"""F4: effect 原子防御分支断言(探索侧降级/跳过/未知 type/timed 渲染兜底)。零 API。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))

import logging
from helpers import make_scene, make_world


def _player(world):
    from investigator import Investigator
    inv = Investigator(name="测试员", age=25, gender="男")
    world.set_player(inv)
    return inv


def _judge(world):
    from game.judge import Judge
    return Judge(world)


class TestExploreSideDegrade:
    def test_damage_atom_skipped_in_exploration(self, caplog):
        """damage 原子探索侧跳过+日志,不改 HP。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        hp_before = inv.derived.HP
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            msgs = _judge(world)._execute_effect_atoms(
                [{"type": "damage", "delta": 5}], inv)
        assert inv.derived.HP == hp_before
        assert msgs == []
        assert any("damage" in r.message for r in caplog.records)

    def test_buff_atom_degrades_to_text_in_exploration(self):
        """buff 原子探索侧降级为文本行。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        msgs = _judge(world)._execute_effect_atoms(
            [{"type": "buff", "description": "力量涌现"}], inv)
        assert msgs == ["力量涌现"]

    def test_unknown_type_degrades_into_result(self, caplog):
        """未知 type 降级进结果文本 + 告警,不抛异常。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            msgs = _judge(world)._execute_effect_atoms(
                [{"type": "teleport", "text": "瞬移"}], inv)
        assert msgs == ["[unknown:teleport] 瞬移"], "未知 type 须带标识符前缀降级进结果"
        assert any("teleport" in r.message for r in caplog.records)


class TestTimedRenderFallback:
    def test_render_missing_expire_at_and_description(self):
        """timed_effects 缺 expire_at 按 0 兜底;缺 description 的条目不渲染。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.timed_effects = [
            {"id": "A", "description": "亢奋"},               # 缺 expire_at
            {"id": "B", "expire_at": world.clock.game_time + 60},  # 缺 description
        ]
        text = world.chronicle.render_for_author(world)
        assert "亢奋" in text and "剩0分钟" in text
        assert "剩60分钟" not in text, "无 description 条目不得渲染"
