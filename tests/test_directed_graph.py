# tests/test_directed_graph.py
import sys
sys.path.insert(0, "src")
from scenario_core import DirectedGraph, Entity


L2_SAMPLE = {
    "scenes": {
        "6号车厢": {
            "description": "测试场景描述",
            "from_here": [{"target": "7号车厢", "method": "步行", "requirement": ""}],
            "to_here": [{"source": "7号车厢", "method": "返回", "requirement": ""}],
            "interactions": [
                {
                    "id": "I1", "scene": "6号车厢", "type": "侦查",
                    "name": "感知电车异常", "requirement": "",
                    "trigger": "调查员苏醒时",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {"on_failure": "fail", "on_regular": "ok"},
                    "difficulty": "regular"
                }
            ],
            "auto_triggers": [
                {
                    "id": "AT1", "scene": "6号车厢", "type": "无",
                    "name": "察觉异常", "requirement": "",
                    "trigger": "自动触发", "result": "你感到不安",
                    "side_effects": [],
                    "difficulty": "None"
                }
            ],
            "encounters": [],
            "scene_weapons": [],
            "extra": {}
        }
    },
    "events": [
        {
            "id": "E1", "type": "无", "name": "退路断绝",
            "requirement": "", "trigger": "触发条件",
            "result": "##END_坏结局:结束##",
            "side_effects": [], "difficulty": "None"
        }
    ],
    "npc_profiles": {},
    "dependency_graph": {"nodes": {}, "edges": [], "_circular_cut": False, "_cut_info": None},
    "_phase1": {"enemies": [], "weapons": []}
}


def test_graph_loads_scene_with_interactions():
    graph = DirectedGraph(scenes=L2_SAMPLE["scenes"], events=L2_SAMPLE["events"])
    assert "6号车厢" in graph.nodes
    node = graph.nodes["6号车厢"]
    assert len(node.interactions) == 1
    assert node.interactions[0].name == "感知电车异常"
    assert node.interactions[0].id == "I1"


def test_graph_loads_auto_triggers():
    graph = DirectedGraph(scenes=L2_SAMPLE["scenes"], events=L2_SAMPLE["events"])
    node = graph.nodes["6号车厢"]
    assert len(node.auto_triggers) == 1
    assert node.auto_triggers[0].name == "察觉异常"


def test_graph_loads_events():
    graph = DirectedGraph(scenes=L2_SAMPLE["scenes"], events=L2_SAMPLE["events"])
    assert "E1" in graph.events
    assert graph.events["E1"].name == "退路断绝"


def test_graph_from_here():
    graph = DirectedGraph(scenes=L2_SAMPLE["scenes"], events=L2_SAMPLE["events"])
    edges = graph.get_edges_from("6号车厢")
    assert len(edges) == 1
    assert edges[0].target == "7号车厢"


def test_graph_roundtrip():
    graph = DirectedGraph(scenes=L2_SAMPLE["scenes"], events=L2_SAMPLE["events"])
    data = graph.to_dict()
    graph2 = DirectedGraph.from_dict(data)
    assert "6号车厢" in graph2.nodes
    assert len(graph2.nodes["6号车厢"].interactions) == 1
    assert len(graph2.nodes["6号车厢"].auto_triggers) == 1
    assert "E1" in graph2.events
