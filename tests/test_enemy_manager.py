"""Tests for EnemyManager — deterministic, no LLM dependency."""
import pytest
from library.enemies import EnemyLibrary
from game.enemy_manager import EnemyInstance, EnemyManager
from scenario_core import DirectedGraph


@pytest.fixture
def lib():
    l = EnemyLibrary()
    l.load_core()
    return l


@pytest.fixture
def mgr(lib):
    return EnemyManager(lib)


def test_spawn_creates_instance(mgr):
    inst = mgr.spawn("深潜者", "车厢1", quantity=1)
    assert inst.instance_id.startswith("深潜者_")
    assert inst.enemy_ref == "深潜者"
    assert inst.scene == "车厢1"
    assert inst.quantity == 1
    assert inst.status == "neutral"
    assert "avoidable" in inst.flags
    assert inst.combat_behavior


def test_get_active_in_scene_filters_dead(mgr):
    a = mgr.spawn("深潜者", "车厢1")
    b = mgr.spawn("疯狂信徒", "车厢1")
    c = mgr.spawn("Clicker", "车厢2")
    mgr.mark_dead(b.instance_id)

    active = mgr.get_active_in_scene("车厢1")
    assert len(active) == 1
    assert active[0].instance_id == a.instance_id


def test_get_active_in_scene_shows_neutral_and_hostile(mgr):
    a = mgr.spawn("疯狂信徒", "车厢3")
    assert len(mgr.get_active_in_scene("车厢3")) == 1
    mgr.mark_dead(a.instance_id)
    assert len(mgr.get_active_in_scene("车厢3")) == 0


def test_group_by_ref(mgr):
    mgr.spawn("深潜者", "车厢4", quantity=2)
    mgr.spawn("疯狂信徒", "车厢4", quantity=3)
    mgr.spawn("深潜者", "车厢5")

    groups = mgr.group_by_ref("车厢4")
    assert len(groups) == 2
    assert len(groups["深潜者"]) == 1
    assert groups["深潜者"][0].quantity == 2
    assert len(groups["疯狂信徒"]) == 1
    assert groups["疯狂信徒"][0].quantity == 3


def test_enter_combat_and_exit(mgr):
    a = mgr.spawn("疯狂信徒", "车厢6")
    b = mgr.spawn("深潜者", "车厢6")

    mgr.enter_combat([a.instance_id, b.instance_id])
    assert a.status == "engaged"
    assert b.status == "engaged"
    assert mgr._combat_active is True

    mgr.exit_combat({
        "outcome": "win",
        "defeated_instance_ids": [a.instance_id],
    })
    assert a.status == "dead"
    assert b.status == "hostile"
    assert mgr._combat_active is False


def test_get_combat_context_no_enemies(mgr):
    ctx = mgr.get_combat_context("空场景")
    assert ctx is None


def test_get_combat_context_with_enemies(mgr):
    mgr.spawn("深潜者", "车厢7")
    mgr.spawn("疯狂信徒", "车厢7", quantity=2)
    ctx = mgr.get_combat_context("车厢7")
    assert ctx is not None
    assert "深潜者" in ctx
    assert "疯狂信徒" in ctx
    assert "neutral" in ctx


@pytest.fixture
def sample_graph():
    """车厢1 <-> 车厢2, 车厢2 <-> 车厢3"""
    return DirectedGraph(scenes={
        "车厢1": {
            "description": "",
            "interactions": [], "auto_triggers": [],
            "from_here": [{"target": "车厢2", "method": "走到"}],
        },
        "车厢2": {
            "description": "",
            "interactions": [], "auto_triggers": [],
            "from_here": [
                {"target": "车厢1", "method": "走回"},
                {"target": "车厢3", "method": "前进"},
            ],
        },
        "车厢3": {
            "description": "",
            "interactions": [], "auto_triggers": [],
            "from_here": [{"target": "车厢2", "method": "返回"}],
        },
    }, events=[])


def test_get_active_in_range_adjacent_aware(mgr, sample_graph):
    """adjacent_aware enemy in 车厢1 is detectable from adjacent 车厢2 but not 车厢3."""
    mgr.spawn("大嘴吞噬者", "车厢1")  # adjacent_aware
    mgr.spawn("疯狂信徒", "车厢2")

    # 车厢1: should see 大嘴吞噬者
    active_1 = mgr.get_active_in_range("车厢1", sample_graph)
    refs_1 = {i.enemy_ref for i in active_1}
    assert "大嘴吞噬者" in refs_1

    # 车厢2: should see 疯狂信徒 + 大嘴吞噬者 (adjacent)
    active_2 = mgr.get_active_in_range("车厢2", sample_graph)
    refs_2 = {i.enemy_ref for i in active_2}
    assert "疯狂信徒" in refs_2
    assert "大嘴吞噬者" in refs_2

    # 车厢3: should NOT see 大嘴吞噬者 (too far)
    active_3 = mgr.get_active_in_range("车厢3", sample_graph)
    refs_3 = {i.enemy_ref for i in active_3}
    assert "大嘴吞噬者" not in refs_3


def test_get_active_in_range_no_adjacent_aware(mgr, sample_graph):
    """Enemies without adjacent_aware flag only appear in their own scene."""
    mgr.spawn("疯狂信徒", "车厢1")
    active = mgr.get_active_in_range("车厢2", sample_graph)
    assert len(active) == 0
