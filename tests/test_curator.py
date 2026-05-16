# tests/test_curator.py
import sys
sys.path.insert(0, "src")
from scenario_core import Entity, ScenarioWorld, DirectedGraph
from game.messages import ActionIntent, ActionOutcome, NarratorBrief, SceneSnapshot


def _make_world():
    scenes = {
        "6号车厢": {
            "description": "测试车厢",
            "from_here": [{"target": "7号车厢", "method": "步行", "requirement": ""}],
            "to_here": [],
            "interactions": [
                {"id": "I1", "scene": "6号车厢", "type": "侦查",
                 "name": "观察", "requirement": "", "trigger": "观察时",
                 "result": "你看到了什么", "side_effects": [],
                 "graded_result": None, "difficulty": "regular"}
            ],
            "auto_triggers": [],
            "encounters": [], "scene_weapons": [], "extra": {}
        }
    }
    graph = DirectedGraph(scenes=scenes, events=[])
    world = ScenarioWorld(graph, start_node="6号车厢")
    return world


def test_curator_assembles_brief():
    from game.curator import Curator
    world = _make_world()
    curator = Curator(world)

    outcomes = [
        ActionOutcome(
            intent=ActionIntent(action="interact", target="观察"),
            success=True, message="你仔细观察了四周",
            entity_id="I1", entity_type="interaction"
        )
    ]
    ambient = ["你闻到了一股淡淡的霉味"]

    brief = curator.assemble(outcomes, ambient, emphasis="紧张探索")

    assert isinstance(brief, NarratorBrief)
    assert len(brief.action_outcomes) == 1
    assert brief.ambient_changes == ambient
    assert brief.scene_snapshot.location == "6号车厢"
    assert len(brief.scene_snapshot.exits) == 1
    assert brief.suggested_emphasis == "紧张探索"


def test_curator_scene_snapshot():
    from game.curator import Curator
    world = _make_world()
    curator = Curator(world)
    snapshot = curator._build_snapshot()
    assert snapshot.location == "6号车厢"
    assert snapshot.description == "测试车厢"
    assert snapshot.exits == [{"target": "7号车厢", "method": "步行"}]
    assert "观察" in snapshot.perceptible_interactions
