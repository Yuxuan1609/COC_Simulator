import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from module_designer.dependency_graph import DependencyGraph, DependencyEdge, DependencyNode


def test_build_graph_from_dependencies():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
        {"entity_id": "E1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    assert "I1" in graph.nodes
    assert "I3" in graph.nodes
    assert "E1" in graph.nodes
    assert len(graph.edges) == 2


def test_no_cycle():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) == 0


def test_detect_simple_cycle():
    deps = [
        {"entity_id": "I1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) > 0


def test_cut_edge_breaks_cycle():
    deps = [
        {"entity_id": "I1", "requires": [
            {"type": "interaction", "id": "I3", "condition": "completed"}
        ]},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    cycles = graph.detect_cycles()
    assert len(cycles) > 0
    cut_edge = graph.edges[0]
    graph.cut_edge(cut_edge)
    cycles_after = graph.detect_cycles()
    assert len(cycles_after) == 0
    assert graph._circular_cut is True


def test_to_dict_and_from_dict():
    deps = [
        {"entity_id": "I1", "requires": []},
        {"entity_id": "I3", "requires": [
            {"type": "interaction", "id": "I1", "condition": "completed"}
        ]},
    ]
    graph = DependencyGraph()
    graph.build(deps)
    d = graph.to_dict()
    restored = DependencyGraph.from_dict(d)
    assert set(restored.nodes.keys()) == set(graph.nodes.keys())
    assert len(restored.edges) == len(graph.edges)
