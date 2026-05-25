"""Integration test: NPC turn routing with mocked entities."""
from game.npc_manager import NPCManager, NPC


def test_follow_request_updates_state():
    from scenario_core import DirectedGraph, ScenarioWorld
    graph = DirectedGraph(scenes={
        "start": {"description": "", "interactions": [], "auto_triggers": []},
    })
    world = ScenarioWorld(graph, start_node="start")
    world.npcs = NPCManager()
    npc = NPC(name="老妇人", scene="start", can_follow=True)
    world.npcs._npcs["老妇人"] = npc
    ok, _ = world.npcs._check_follow_conditions(npc, world)
    assert ok
    world.npcs.set_following("老妇人", True)
    assert npc.following
    assert "老妇人" in [n.name for n in world.npcs.get_following()]


def test_state_gate_dead_no_dialogue():
    mgr = NPCManager()
    mgr._npcs["dead"] = NPC(name="dead", state="dead")
    r = mgr.talk_to("dead", "hi", lambda **kw: "X")
    assert "无法交谈" in r
