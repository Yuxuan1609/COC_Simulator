"""Integration tests: SpawnEnemy -> EnemyManager -> combat entry context."""
import pytest
from scenario_core import (
    DirectedGraph, ScenarioWorld, Entity, Edge, Node,
    apply_side_effects, parse_markup_all,
)
from library.enemies import EnemyLibrary


@pytest.fixture
def lib():
    l = EnemyLibrary()
    l.load_core()
    return l


@pytest.fixture
def world(lib):
    graph = DirectedGraph(scenes={
        "车厢1": {"description": "测试场景",
                  "interactions": [], "auto_triggers": [], "from_here": []},
    }, events=[])
    return ScenarioWorld(graph, start_node="车厢1", enemy_library=lib)


def test_spawnenemy_instantiates_enemy(world):
    """@spawn_enemy side effect creates an EnemyInstance via EnemyManager."""
    se_text = '@spawn_enemy(enemy_ref="深潜者", scene="车厢1", quantity=1)'
    effects = parse_markup_all(se_text)
    assert len(effects) == 1

    msgs = apply_side_effects(world, effects)
    assert len(msgs) == 1
    assert "生成敌人" in msgs[0]
    assert "深潜者" in msgs[0]

    active = world.enemy_manager.get_active_in_scene("车厢1")
    assert len(active) == 1
    assert active[0].enemy_ref == "深潜者"
    assert "avoidable" in active[0].flags


def test_spawnenemy_works_without_enemy_library():
    """@spawn_enemy degrades gracefully when no enemy_library is set."""
    graph = DirectedGraph(scenes={
        "test": {"description": "", "interactions": [], "auto_triggers": [], "from_here": []},
    }, events=[])
    w = ScenarioWorld(graph, start_node="test")  # no enemy_library

    se_text = '@spawn_enemy(enemy_ref="深潜者", scene="test", quantity=1)'
    effects = parse_markup_all(se_text)
    msgs = apply_side_effects(w, effects)
    assert len(msgs) == 1
    assert "生成敌人" in msgs[0]
    assert w.enemy_manager is None


def test_combat_context_skips_empty(world):
    ctx = world.enemy_manager.get_combat_context("车厢1")
    assert ctx is None


def test_combat_context_includes_enemy_info(world):
    world.enemy_manager.spawn("深潜者", "车厢1", quantity=2)
    ctx = world.enemy_manager.get_combat_context("车厢1")
    assert ctx is not None
    assert "深潜者" in ctx
    assert "x2" in ctx


def test_enter_combat_exit_combat_cycle(world):
    inst = world.enemy_manager.spawn("疯狂信徒", "车厢1")
    assert inst.status == "neutral"

    world.enemy_manager.enter_combat([inst.instance_id])
    assert inst.status == "engaged"
    assert world.enemy_manager._combat_active

    world.enemy_manager.exit_combat({
        "outcome": "win",
        "defeated_instance_ids": [inst.instance_id],
    })
    assert inst.status == "dead"
    assert not world.enemy_manager._combat_active


def test_flag_parsing_in_enemy_library(lib):
    """Verify flags are correctly parsed from enemies.json."""
    h = lib.get("深潜者")
    assert h is not None
    assert "avoidable" in h.flags
    assert "[avoidable]" not in h.combat_behavior

    big = lib.get("大嘴吞噬者")
    assert big is not None
    assert "adjacent_aware" in big.flags

    c = lib.get("Clicker")
    assert c is not None
    assert c.flags == []
