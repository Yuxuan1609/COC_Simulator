"""N1 attitude_value dual-track + 档位映射 + 入档。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))


def test_tier_boundaries():
    from game.npc_manager import attitude_tier
    assert attitude_tier(-50)[0] == "hostile"
    assert attitude_tier(-49)[0] == "wary"
    assert attitude_tier(10)[0] == "neutral"
    assert attitude_tier(11)[0] == "friendly"


def test_set_attitude_delta_clamps():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    world.npcs.set_attitude("线人", delta=200)
    assert world.npcs._npcs["线人"].attitude_value == 100
    world.npcs.set_attitude("线人", delta=-300)
    assert world.npcs._npcs["线人"].attitude_value == -100


def test_save_load_attitude_value():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_attitude("线人", value=40)
    dumped = world.npcs.to_dict()
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict(dumped, {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == 40
    assert m._npcs["线人"].attitude == "friendly"


def test_legacy_save_attitude_string_maps_to_midpoint():
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict({"线人": {"scene": "room_a", "attitude": "hostile"}},
                {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == -75
    assert m._npcs["线人"].attitude == "hostile"


def test_snapshot_attitude_is_chinese_label():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    world.npcs.set_attitude("线人", value=40)
    snap = world.npcs.get_in_scene_snapshot("room_a")
    assert snap[0]["attitude"] == "友好"


def _npc_world():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    return world, world.npcs.get("线人")


def test_markup_delta_applied():
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world, npc = _npc_world()
    apply_side_effects(world, parse_markup_all('@attitude_change(npc_name="线人", delta=20)'))
    assert npc.attitude_value == 20
    assert npc.attitude == "friendly"


def test_talk_to_strips_and_applies():
    world, npc = _npc_world()
    def fake_llm(user, system="", **k):
        return "哼。@attitude_change(npc_name=\"线人\", delta=-15)"
    text = world.npcs.talk_to("线人", "滚开", fake_llm, world=world)
    assert "@attitude_change" not in text
    assert world.npcs.get("线人").attitude_value == -15


def test_illegal_npc_name_warning_no_crash(caplog):
    import logging
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world, npc = _npc_world()
    with caplog.at_level(logging.WARNING):
        apply_side_effects(
            world, parse_markup_all('@attitude_change(npc_name="不存在的人", delta=20)'))
    assert npc.attitude_value == 0
    assert any("attitude_change" in r.message or "不存在的人" in r.message
               for r in caplog.records)


def test_empty_npc_name_in_talk_to_applies_to_current():
    world, npc = _npc_world()
    def fake_llm(user, system="", **k):
        return "哼。@attitude_change(delta=-15)"
    text = world.npcs.talk_to("线人", "滚开", fake_llm, world=world)
    assert "@attitude_change" not in text
    assert npc.attitude_value == -15


def test_hostile_talk_does_not_call_llm():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "hostile"}})
    def fake_llm(*a, **k):
        raise AssertionError("llm should not be called")
    text = world.npcs.talk_to("线人", "你好", fake_llm, world=world)
    assert "不愿理会" in text or "驱赶" in text


def test_attitude_min_blocks_interaction():
    from helpers import make_world, make_scene
    from game.judge import Judge
    world = make_world({"room_a": make_scene(interactions=[{
        "id": "IT_ASK", "entity_type": "interaction",
        "name": "打听", "scene": "room_a",
        "type": "无", "requirement": "", "trigger": "打听",
        "result": "他说了。", "side_effects": [],
        "difficulty": "",
        "extra": {"attitude_min": 10, "npc_name": "线人"},
    }])}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    entity = world.graph.nodes["room_a"].interactions[0]
    outcome = Judge(world)._execute_entity(entity)
    assert not outcome.success
    assert "不愿配合" in outcome.message


def test_wary_cannot_follow():
    from helpers import make_world, make_scene
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a",
                "attitude": "wary", "can_follow": True}})
    npc = world.npcs.get("线人")
    world.npcs.set_following("线人", True)
    assert npc.following is False
    msgs = apply_side_effects(
        world, parse_markup_all('@npc_follow(npc_name="线人", follow=true)'))
    assert npc.following is False
    assert any("拒绝跟随" in m for m in msgs)


def test_talk_to_system_prompt_n3_strategy():
    world, npc = _npc_world()
    captured = {}

    def fake_llm(user, system="", **k):
        captured["system"] = system
        return "嗯。"

    world.npcs.talk_to("线人", "你好", fake_llm, world=world)
    system = captured["system"]
    assert "如实告知" not in system
    assert "当前态度" in system
    assert "敌意拒绝" in system
    assert "警惕套话" in system
    assert "@attitude_change" in system
    assert "当前态度：中立" in system
    assert "当前态度：neutral" not in system


def test_keeper_scene_state_attitude_disclosure():
    from prompts import _build_scene_state
    world, npc = _npc_world()
    text = _build_scene_state(world.build_snapshot())
    assert "按态度决定透露与采信" in text
    assert "中立" in text


def test_attitude_min_skips_keeper_inject():
    from helpers import make_world, make_scene
    from game.agents.keeper import Keeper
    profile = {
        "name": "线人", "scene": "room_a", "can_interact": True,
        "attitude": "neutral",
        "bound_interactions": [{
            "id": "IT_SECRET", "entity_type": "interaction",
            "name": "问秘密", "type": "无", "requirement": "",
            "trigger": "问秘密", "result": "他摇头。",
            "difficulty": "None",
            "attitude_min": 10,
        }],
    }
    world = make_world({"room_a": make_scene()}, "room_a",
                       npc_profiles={"线人": profile})
    keeper = Keeper(world)
    keeper._inject_npc_at()
    node = world.graph.nodes["room_a"]
    assert not any(e.id == "IT_SECRET" for e in node.interactions)


def test_npc_death_completes_runtime_flag_and_fires_at():
    from helpers import make_world, make_scene
    world = make_world({
        "room_a": make_scene(auto_triggers=[{
            "id": "AT_DEAD", "name": "线人死讯", "type": "无",
            "requirement": "npc_dead:线人",
            "result": "街上有人在议论线人的死。",
        }])
    }, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_state("线人", "dead")
    assert world.get_runtime_state("npc_dead:线人").completed
    from game.judge import Judge
    judge = Judge(world)
    outs = judge.check_auto_triggers()
    assert any(o.entity_id == "AT_DEAD" for o in outs)


def test_set_state_non_dead_does_not_set_flag():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_state("线人", "left")
    assert not world.get_runtime_state("npc_dead:线人").completed


def test_npc_death_flag_idempotent():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_state("线人", "dead")
    world.npcs.set_state("线人", "dead")
    assert world.get_runtime_state("npc_dead:线人").completed


def test_markup_npc_state_change_dead_sets_flag():
    from helpers import make_world, make_scene
    from game.side_effects import parse_markup_all
    from scenario_core import apply_side_effects
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    apply_side_effects(
        world, parse_markup_all('@npc_state_change(npc_name="线人", new_state="dead")'))
    assert world.npcs.get("线人").state == "dead"
    assert world.get_runtime_state("npc_dead:线人").completed
