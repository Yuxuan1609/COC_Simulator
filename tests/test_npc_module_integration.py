"""NPC integration tests using 常暗更新 module data."""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game.npc_manager import NPC, NPCManager
from scenario_core import DirectedGraph, ScenarioWorld


MODULE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗更新")


def load_module():
    with open(os.path.join(MODULE_DIR, "l2_keeper.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def test_npc_profile_loaded_from_module():
    """NPC 档案正确从模块加载：scene / can_follow / follow_requirements 均已注入。"""
    l2 = load_module()
    profiles = l2.get("npc_profiles", {})

    assert len(profiles) == 1
    npc_data = profiles.get("京山人吉")
    assert npc_data is not None
    assert npc_data["scene"] == "4号车厢"
    assert npc_data["can_follow"] is True
    assert "急救" in npc_data.get("follow_requirements", "")


def test_npc_bound_entities():
    """NPC bound entities 已正确绑定：从 scene 剥离并保留 source_scene。"""
    l2 = load_module()
    profiles = l2.get("npc_profiles", {})
    npc_data = profiles["京山人吉"]

    bound_i = npc_data.get("bound_interactions", [])
    bound_at = npc_data.get("bound_auto_triggers", [])
    assert len(bound_i) == 2
    assert len(bound_at) == 3

    # Verify interactions are stripped from 4号车厢
    scenes = l2.get("scenes", {})
    car4 = scenes.get("4号车厢", {})
    assert len(car4.get("interactions", [])) == 0


def test_npc_scene_assignment_in_world():
    """NPC 初始化后 scene 正确设置，get_in_scene 返回正确 NPC。"""
    l2 = load_module()
    graph = DirectedGraph(scenes=l2.get("scenes", {}), events=l2.get("events", []))
    world = ScenarioWorld(graph, start_node="6号车厢",
                          npc_profiles=l2.get("npc_profiles", {}))

    npc = world.npcs.get("京山人吉")
    assert npc is not None
    assert npc.scene == "4号车厢"
    assert npc.can_follow is True
    assert "急救" in npc.follow_requirements

    # 在 4号车厢 应该可见
    visible = world.npcs.get_in_scene("4号车厢")
    assert len(visible) == 1
    assert visible[0].name == "京山人吉"

    # 在 6号车厢 不应该可见
    visible_6 = world.npcs.get_in_scene("6号车厢")
    assert len(visible_6) == 0


def test_npc_follow_conditions():
    """跟随条件检查：can_follow + state 决定可否跟随。"""
    mgr = NPCManager()

    # NPC with can_follow=True, alive
    mgr._npcs["京山人吉"] = NPC(name="京山人吉", scene="4号车厢",
                                can_follow=True, state="alive")
    ok, reason = mgr._check_follow_conditions(mgr.get("京山人吉"), world=None)
    assert ok
    assert reason == ""

    # NPC with can_follow=False
    mgr._npcs["老王"] = NPC(name="老王", can_follow=False, state="alive")
    ok, reason = mgr._check_follow_conditions(mgr.get("老王"), world=None)
    assert not ok
    assert "不愿意" in reason

    # NPC dead
    mgr._npcs["京山人吉"].state = "dead"
    ok, reason = mgr._check_follow_conditions(mgr.get("京山人吉"), world=None)
    assert not ok


def test_npc_serialization_roundtrip_with_module_data():
    """序列化往返：使用模块数据的 NPC。"""
    l2 = load_module()
    profiles = l2.get("npc_profiles", {})
    mgr = NPCManager()
    mgr.init_from_profiles(profiles)

    npc = mgr.get("京山人吉")
    npc.memory.append("玩家询问了钥匙的位置")
    mgr.set_following("京山人吉", True)

    data = mgr.to_dict()
    mgr2 = NPCManager()
    mgr2.init_from_profiles(profiles)
    mgr2.from_dict(data, profiles)

    restored = mgr2.get("京山人吉")
    assert restored.scene == "4号车厢"
    assert restored.can_follow is True
    assert restored.following is True
    assert "钥匙" in restored.memory[0]


def test_npc_talk_to_rejects_dead_state():
    """状态门：dead 状态 NPC 无法对话。"""
    mgr = NPCManager()
    mgr._npcs["京山人吉"] = NPC(name="京山人吉", state="dead")
    result = mgr.talk_to("京山人吉", "你好", lambda prompt, **kw: "不应该调用")
    assert "无法交谈" in result


def test_npc_not_in_scene_snapshot():
    """不在当前场景的 NPC 不出现在 get_in_scene 中。"""
    l2 = load_module()
    graph = DirectedGraph(scenes=l2.get("scenes", {}), events=l2.get("events", []))
    world = ScenarioWorld(graph, start_node="6号车厢",
                          npc_profiles=l2.get("npc_profiles", {}))

    # 京山人吉 在 4号车厢，查询 6号车厢 应该返回空
    in_scene_6 = world.npcs.get_in_scene("6号车厢")
    assert len(in_scene_6) == 0

    # 查询 4号车厢 应该返回京山人吉
    in_scene_4 = world.npcs.get_in_scene("4号车厢")
    assert len(in_scene_4) == 1
    assert in_scene_4[0].name == "京山人吉"

    # 快照也应反映同样结果
    snap = world.build_snapshot()
    npcs_in_scene = snap.get("npcs_in_scene", [])
    assert len(npcs_in_scene) == 0  # current = 6号车厢, NPC is in 4号车厢


def test_bound_entities_have_source_scene():
    """所有 bound entity 都保留了 source_scene 字段。"""
    l2 = load_module()
    profiles = l2.get("npc_profiles", {})
    npc_data = profiles["京山人吉"]

    for e in npc_data.get("bound_interactions", []):
        assert "source_scene" in e
        assert "id" in e

    for e in npc_data.get("bound_auto_triggers", []):
        assert "source_scene" in e
        assert "id" in e
