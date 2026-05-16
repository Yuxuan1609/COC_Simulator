# tests/test_judge.py
import sys
sys.path.insert(0, "src")
from scenario_core import Entity, ScenarioWorld, DirectedGraph


# Minimal graph + world for testing
def _make_world():
    scenes = {
        "test_scene": {
            "description": "A test scene",
            "from_here": [],
            "to_here": [],
            "interactions": [
                {
                    "id": "I1", "scene": "test_scene", "type": "侦查",
                    "name": "检查房间", "requirement": "",
                    "trigger": "调查员检查时", "result": "你发现了线索",
                    "side_effects": [],
                    "graded_result": None,
                    "difficulty": "regular"
                },
                {
                    "id": "I2", "scene": "test_scene", "type": "无",
                    "name": "开门", "requirement": "flag:has_key",
                    "trigger": "调查员尝试开门时",
                    "result": "你打开了门",
                    "side_effects": ["@item_gain(item_name=钥匙)"],
                    "graded_result": None,
                    "difficulty": "None"
                }
            ],
            "auto_triggers": [
                {
                    "id": "AT1", "scene": "test_scene", "type": "无",
                    "name": "察觉气味", "requirement": "",
                    "trigger": "进入时自动", "result": "你闻到奇怪的气味",
                    "side_effects": [],
                    "difficulty": "None"
                }
            ],
            "encounters": [], "scene_weapons": [], "extra": {}
        }
    }
    events = []
    graph = DirectedGraph(scenes=scenes, events=events)
    world = ScenarioWorld(graph, start_node="test_scene")
    return world, graph


def test_judge_checks_simple_auto_triggers():
    from game.judge import Judge
    world, graph = _make_world()
    judge = Judge(world)
    at_results = judge.check_auto_triggers()
    assert len(at_results) == 1
    assert at_results[0].entity_id == "AT1"
    assert at_results[0].success is True


def test_judge_executes_interaction():
    from game.judge import Judge
    from game.messages import ActionIntent
    world, graph = _make_world()
    judge = Judge(world)
    intent = ActionIntent(action="interact", target="检查房间")
    outcome = judge.execute_interaction(intent)
    assert outcome.success is True
    assert "线索" in outcome.message


def test_judge_blocks_unmet_requirement():
    from game.judge import Judge
    from game.messages import ActionIntent
    world, graph = _make_world()
    judge = Judge(world)
    intent = ActionIntent(action="interact", target="开门")
    outcome = judge.execute_interaction(intent)
    assert outcome.success is False
    assert "has_key" in outcome.message.lower()


def test_judge_filters_unmet_events():
    from game.judge import Judge
    world, graph = _make_world()
    # Add an event with unmet requirement
    ev = Entity(id="E1", entity_type="event", name="test_event",
                type="无", requirement="flag:something_unmet",
                trigger="test", result="test", side_effects=[])
    graph.events["E1"] = ev
    judge = Judge(world)
    pending = judge.filter_pending_events()
    assert len(pending) == 0  # E1's requirement is unmet
