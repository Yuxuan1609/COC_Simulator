"""N1 attitude_value dual-track + 档位映射 + 入档。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))


def test_tier_boundaries():
    from game.npc_manager import attitude_tier
    assert attitude_tier(-50)[0] == "hostile"
    assert attitude_tier(-49)[0] == "wary"
    assert attitude_tier(10)[0] == "neutral"
    assert attitude_tier(11)[0] == "friendly"


def test_set_attitude_delta_clamps():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    world.npcs.set_attitude("线人", delta=200)
    assert world.npcs._npcs["线人"].attitude_value == 100
    world.npcs.set_attitude("线人", delta=-300)
    assert world.npcs._npcs["线人"].attitude_value == -100


def test_save_load_attitude_value():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_attitude("线人", value=40)
    dumped = world.npcs.to_dict()
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict(dumped, {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == 40
    assert m._npcs["线人"].attitude == "friendly"


def test_legacy_save_attitude_string_maps_to_midpoint():
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict({"线人": {"scene": "room_a", "attitude": "hostile"}},
                {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == -75
    assert m._npcs["线人"].attitude == "hostile"


def test_snapshot_attitude_is_chinese_label():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    world.npcs.set_attitude("线人", value=40)
    snap = world.npcs.get_in_scene_snapshot("room_a")
    assert snap[0]["attitude"] == "友好"
