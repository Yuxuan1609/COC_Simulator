import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _make_world():
    from scenario_core import DirectedGraph, ScenarioWorld
    scenes = {"room_a": {"interactions": [], "auto_triggers": [], "from_here": [],
                         "to_here": [], "encounters": [], "scene_weapons": [],
                         "extra": {}, "description": ""}}
    return ScenarioWorld(DirectedGraph(scenes=scenes, events=[]), start_node="room_a")


def _make_result(entity_id="IT_SEARCH", tier="regular", msg="你找到了一把钥匙。"):
    from game.messages import (TurnResult, TurnStatus, NarratorBrief,
                               ActionOutcome, ActionIntent)
    o = ActionOutcome(intent=ActionIntent(action="interaction"), success=True,
                      message=msg, entity_id=entity_id,
                      entity_type="interaction", skill_tier=tier)
    brief = NarratorBrief(action_outcomes=[o], ambient_changes=[],
                          scene_snapshot=None, suggested_emphasis="")
    return TurnResult(status=TurnStatus.COMPLETED, brief=brief)


def test_record_turn_appends_event_with_raw_input():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "仔细检查地板缝", _make_result(), w)
    assert len(c.events) == 1
    e = c.events[0]
    assert e["turn"] == 1 and "仔细检查地板缝" in e["input"]
    assert e["entities"] == {"IT_SEARCH": "regular"}


def test_entity_results_truncated_100():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "搜索", _make_result(msg="长" * 200), w)
    assert len(c.entity_results["IT_SEARCH"]) <= 100


def test_events_window_15():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    for i in range(20):
        c.record_turn(i + 1, f"动作{i}", _make_result(), w)
    assert len(c.events) == 15
    assert c.events[0]["turn"] == 6, "最旧的 5 条必须出窗"


def test_record_patch():
    from scenario_core import WorldChronicle
    c = WorldChronicle()
    c.record_patch(turn=3, level="patch", entity_ids=["SI1", "SI2"],
                   new_scenes=[], justification="补" * 150)
    assert len(c.patches) == 1
    assert c.patches[0]["entity_ids"] == ["SI1", "SI2"]
    assert len(c.patches[0]["justification"]) <= 100


def test_serialization_roundtrip():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "搜索", _make_result(), w)
    c.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                   new_scenes=[], justification="test")
    back = WorldChronicle.from_dict(c.to_dict())
    assert back.events == c.events
    assert back.entity_results == c.entity_results
    assert back.patches == c.patches
    assert back.events_summary == ""


def test_render_for_author_contains_sections():
    from scenario_core import WorldChronicle
    from investigator import Investigator
    w = _make_world()
    w.set_player(Investigator(name="t"))
    c = WorldChronicle()
    c.record_turn(1, "搜索房间", _make_result(), w)
    text = c.render_for_author(w)
    assert "【世界真值】" in text and "【编年史】" in text
    assert "IT_SEARCH" in text and "搜索房间" in text


def test_world_has_chronicle():
    w = _make_world()
    from scenario_core import WorldChronicle
    assert isinstance(w.chronicle, WorldChronicle)


def test_world_chronicle_in_save():
    """ScenarioWorld 存档通路必须带 chronicle 键，且 from_dict 回读内容一致。"""
    from scenario_core import ScenarioWorld
    w = _make_world()
    w.chronicle.record_turn(1, "搜索", _make_result(), w)
    w.chronicle.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                             new_scenes=[], justification="x")
    d = w.to_dict()
    assert "chronicle" in d, "ScenarioWorld.to_dict 必须包含 chronicle 键"
    assert d["chronicle"]["patches"][0]["entity_ids"] == ["SI1"]
    back = ScenarioWorld.from_dict(d, w.graph)
    assert back.chronicle.patches == w.chronicle.patches
    assert back.chronicle.events == w.chronicle.events
    assert back.chronicle.entity_results == w.chronicle.entity_results


def test_author_prompt_contains_chronicle():
    """Author prompt 必须含编年史块（facts + events + patches）。"""
    from prompts import build_author_prompt
    from scenario_core import WorldChronicle

    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "撬开地板", _make_result(), w)
    c.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                   new_scenes=[], justification="补缺")
    rendered = c.render_for_author(w)

    class _Req:
        intent = "看看地板下有什么"
        reasoning = "模组未覆盖"
        other_texts = ["撬开地板"]
        scene_context = {"location": "room_a", "description": "",
                         "available_scenes": ["room_a"], "npc_states": {},
                         "runtime_summary": {}, "wr0_enabled": False,
                         "chronicle": rendered}
    prompt = build_author_prompt(_Req(), {"world_rules": [], "driving_force": "找出真相"})
    assert "【世界编年史】" in prompt
    assert "IT_SEARCH" in prompt and "SI1" in prompt
