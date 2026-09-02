"""F19 environment：修正表 + check_skill 技能值 ±N（S3-P3 spec §2）。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))


def _inv(value=50):
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.skills = [Skill(name="侦查", base_value=value, value=value, category="探索")]
    return inv


def test_dark_spot_hidden_applies_minus_20(monkeypatch):
    """侦查 50 + modifier=-20 → 有效目标 30；roll=40 失败。"""
    inv = _inv(50)
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
    ok, msg, tier = inv.check_skill("侦查", modifier=-20)
    assert not ok
    assert "/30" in msg or "30" in msg


def test_no_environment_zero_mod(monkeypatch):
    inv = _inv(50)
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
    ok, msg, tier = inv.check_skill("侦查", modifier=0)
    assert ok


def test_explicit_difficulty_still_applied_plus_env(monkeypatch):
    """hard + modifier=-20：effective=30，hard 阈值 15；roll=20 失败。"""
    inv = _inv(50)
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 20)
    ok, msg, tier = inv.check_skill("侦查", difficulty="hard", modifier=-20)
    assert not ok


def test_clamp_1_99(monkeypatch):
    inv = _inv(5)
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 1)
    ok, msg, tier = inv.check_skill("侦查", modifier=-20)
    assert ok
    assert "/1" in msg


def test_current_environment_dark_spot_hidden_modifier():
    from helpers import make_world, make_scene
    from investigator.rules import env_check_modifier
    world = make_world(
        {"room_a": make_scene(environment={"lighting": "dark"})}, "room_a")
    assert world.current_environment().get("lighting") == "dark"
    assert env_check_modifier(world, "侦查") == -20
    assert env_check_modifier(world, "潜行") == 10
    assert env_check_modifier(world, "聆听") == 0


def test_empty_environment_zero_mod():
    from helpers import make_world, make_scene
    from investigator.rules import env_check_modifier
    world = make_world({"room_a": make_scene()}, "room_a")
    assert env_check_modifier(world, "侦查") == 0


def test_multi_axis_sums_mods():
    from helpers import make_world, make_scene
    from investigator.rules import env_check_modifier
    world = make_world(
        {"room_a": make_scene(environment={"lighting": "dark", "noise": "noisy"})},
        "room_a")
    assert env_check_modifier(world, "侦查") == -20
    assert env_check_modifier(world, "聆听") == -20
    assert env_check_modifier(world, "潜行") == 10


def test_node_environment_load_and_to_dict():
    from scenario_core import DirectedGraph
    graph = DirectedGraph({
        "room_a": {
            "from_here": [], "to_here": [], "interactions": [],
            "auto_triggers": [], "encounters": [], "scene_weapons": [],
            "environment": {"lighting": "dim", "noise": "noisy"},
        }
    })
    assert graph.nodes["room_a"].environment == {
        "lighting": "dim", "noise": "noisy"}
    dumped = graph.to_dict()
    graph2 = DirectedGraph.from_dict(dumped)
    assert graph2.nodes["room_a"].environment == {
        "lighting": "dim", "noise": "noisy"}


def test_env_change_lighting_normal_clears_dark_modifier():
    from helpers import make_world, make_scene
    from investigator.rules import env_check_modifier
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world = make_world(
        {"room_a": make_scene(environment={"lighting": "dark"})}, "room_a")
    assert env_check_modifier(world, "侦查") == -20
    apply_side_effects(
        world, parse_markup_all('@env_change(axis="lighting", value="normal")'))
    assert world.current_environment().get("lighting") == "normal"
    assert env_check_modifier(world, "侦查") == 0


def test_illegal_env_change_ignored_with_warning(caplog):
    import logging
    from helpers import make_world, make_scene
    from investigator.rules import env_check_modifier
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world = make_world(
        {"room_a": make_scene(environment={"lighting": "dark"})}, "room_a")
    with caplog.at_level(logging.WARNING):
        apply_side_effects(
            world, parse_markup_all('@env_change(axis="weather", value="rain")'))
        apply_side_effects(
            world, parse_markup_all('@env_change(axis="lighting", value="blinding")'))
    assert world.current_environment().get("lighting") == "dark"
    assert env_check_modifier(world, "侦查") == -20
    assert any("env_change" in r.message for r in caplog.records)


def test_environment_overrides_save_load_roundtrip():
    from helpers import make_world, make_scene
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects, ScenarioWorld
    world = make_world(
        {"room_a": make_scene(environment={"lighting": "dark"})}, "room_a")
    apply_side_effects(
        world, parse_markup_all('@env_change(axis="lighting", value="normal")'))
    dumped = world.to_dict()
    world2 = ScenarioWorld.from_dict(dumped, world.graph)
    assert world2.environment_overrides.get("room_a", {}).get("lighting") == "normal"
    assert world2.current_environment().get("lighting") == "normal"
