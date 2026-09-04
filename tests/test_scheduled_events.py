"""F18 时刻事件触发（降级版）：advance_time 跨越即触发（S3-P2 spec §3）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_player(san=50):
    from helpers import make_world, make_scene
    from investigator import Investigator
    world = make_world({"room_a": make_scene()}, "room_a")
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.derived.SAN = san
    world.set_player(inv)
    return world, inv


class TestScheduledEvents:
    def test_crossing_triggers_markup(self):
        """advance_time 跨越 at_minutes → markup 结算并出队。"""
        world, inv = _world_with_player()
        world.scheduled_events = [{
            "id": "night_fall",
            "at_minutes": 60,
            "markup": '@stat_change(stat_name="SAN", delta=-1)',
            "description": "夜幕降临",
        }]
        world.advance_time(60)
        assert inv.derived.SAN == 49
        assert world.scheduled_events == []

    def test_not_reached_no_trigger(self):
        """未跨越不触发，队列保留。"""
        world, inv = _world_with_player()
        event = {
            "id": "night_fall",
            "at_minutes": 120,
            "markup": '@stat_change(stat_name="SAN", delta=-1)',
            "description": "夜幕降临",
        }
        world.scheduled_events = [event]
        world.advance_time(60)
        assert inv.derived.SAN == 50
        assert len(world.scheduled_events) == 1
        assert world.scheduled_events[0]["id"] == "night_fall"

    def test_multiple_events_in_one_advance(self, monkeypatch):
        """一次推进跨越多事件 → 按 at_minutes 升序触发并出队。"""
        world, _inv = _world_with_player()
        world.scheduled_events = [
            {
                "id": "ev2",
                "at_minutes": 90,
                "markup": '@stat_change(stat_name="SAN", delta=-3)',
                "description": "最晚",
            },
            {
                "id": "ev0",
                "at_minutes": 30,
                "markup": '@stat_change(stat_name="SAN", delta=-1)',
                "description": "最早",
            },
            {
                "id": "ev1",
                "at_minutes": 60,
                "markup": '@stat_change(stat_name="SAN", delta=-2)',
                "description": "中间",
            },
        ]
        fired = []
        import scenario_core
        orig = scenario_core.apply_side_effects

        def spy(w, effs, *a, **k):
            fired.append({-1: "ev0", -2: "ev1", -3: "ev2"}[effs[0].delta])
            return orig(w, effs, *a, **k)

        monkeypatch.setattr(scenario_core, "apply_side_effects", spy)
        world.advance_time(90)
        assert fired == ["ev0", "ev1", "ev2"]
        assert world.scheduled_events == []

    def test_first_event_failure_still_fires_later_and_dequeues(self):
        """首事件结算失败不影响后续触发，且均出队。"""
        world, inv = _world_with_player()
        world.scheduled_events = [
            {
                "id": "bad",
                "at_minutes": 30,
                "markup": '@item_gain(item_name="x", quantity="garbage")',
                "description": "坏事件",
            },
            {
                "id": "good",
                "at_minutes": 60,
                "markup": '@stat_change(stat_name="SAN", delta=-1)',
                "description": "好事件",
            },
        ]
        world.advance_time(60)
        assert inv.derived.SAN == 49
        assert world.scheduled_events == []

    def test_save_load_roundtrip(self, tmp_path):
        """scheduled_events 入档往返。"""
        world, _inv = _world_with_player()
        events = [{
            "id": "night_fall",
            "at_minutes": 180,
            "markup": '@stat_change(stat_name="SAN", delta=-1)',
            "description": "夜幕降临",
        }]
        world.scheduled_events = events
        path = str(tmp_path / "save.json")
        world.save_state(path)
        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)
        assert restored.scheduled_events == events


class TestScheduledEventsModuleLoad:
    def test_init_game_loads_scheduled_events(self, tmp_path):
        """l2 JSON 顶层 scheduled_events 键 → keeper.world.scheduled_events（断链修复）。"""
        import json
        import shutil
        src_dir = os.path.join(os.path.dirname(__file__), '..', 'data',
                               'modules', 'e2e_testbed')
        mod = tmp_path / "mod"
        shutil.copytree(src_dir, mod)
        l2p = mod / "l2_keeper.json"
        l2 = json.loads(l2p.read_text(encoding='utf-8'))
        assert l2.get("scheduled_events"), "fixture 应先含 scheduled_events（Task 4）"
        from game_loop import init_game
        game = init_game(str(l2p), str(mod / "l1_player.json"),
                         str(mod / "l3_designer.json"),
                         start_node="测试房间A")
        world = game["keeper"].world
        assert any(e.get("id") == "SE_NIGHT_CHILL" for e in world.scheduled_events)
