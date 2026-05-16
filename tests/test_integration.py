# tests/test_integration.py
import sys
import json
sys.path.insert(0, "src")
from scenario_core import DirectedGraph, ScenarioWorld
from game.agents.keeper import Keeper
from game.agents.narrator import Narrator
from game.agents.author import Author
from game.escalation import EscalationPolicy


def test_full_init_chain():
    """Verify the entire init chain works with real L2 data."""
    with open("data/modules/常暗之厢/l2_keeper.json", "r", encoding="utf-8") as f:
        l2 = json.load(f)

    graph = DirectedGraph(scenes=l2["scenes"], events=l2.get("events", []))
    assert len(graph.nodes) > 0
    # events list may be empty for some modules
    assert isinstance(graph.events, dict)

    # Use the first scene node as start point
    start_node = list(graph.nodes.keys())[0]
    world = ScenarioWorld(graph, start_node=start_node)
    assert world.current_location == start_node

    # Verify interactions loaded as Entity
    node = graph.nodes[start_node]
    assert len(node.interactions) > 0
    inter = node.interactions[0]
    assert hasattr(inter, "entity_type")
    assert inter.entity_type == "interaction"
    assert len(inter.name) > 0

    # Verify edges loaded
    assert isinstance(node.edges, list)

    # Verify events loaded as Entity
    if graph.events:
        ev = list(graph.events.values())[0]
        assert hasattr(ev, "entity_type")
        assert ev.entity_type == "event"
        assert len(ev.name) > 0


def test_keeper_init_with_policy():
    with open("data/modules/常暗之厢/l2_keeper.json", "r", encoding="utf-8") as f:
        l2 = json.load(f)

    graph = DirectedGraph(scenes=l2["scenes"], events=l2.get("events", []))
    start_node = list(graph.nodes.keys())[0]
    world = ScenarioWorld(graph, start_node=start_node)
    policy = EscalationPolicy()

    keeper = Keeper(world, escalation_policy=policy)
    assert keeper.turn_number == 0
    assert keeper.judge is not None
    assert keeper.curator is not None


def test_narrator_init():
    narrator = Narrator({})
    assert narrator.l1_data is not None


def test_author_init():
    l3_data = type("L3", (), {
        "tone_constraints": type("TC", (), {
            "genre": "", "forbidden": [], "recommended": [], "required": [],
            "narrative_style": ""
        })(),
        "module_meta": {}, "scene_intents": {},
        "ending_conditions": [], "characters": [],
        "driving_force": "", "world_rules": [],
    })()
    author = Author(l3_data)
    assert author.l3_data is not None
