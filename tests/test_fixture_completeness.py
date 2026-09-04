"""e2e_testbed 样例模组完备性：模组数据层已设计元素必须有实例承载（spec §1.2）。

新增模组数据层机制时：① e2e_testbed 加实例 ② 此处加检查。两者必须同步。
timed_effects 为 markup 驱动运行时状态，无模组字段，由 test_periodic_effects.py 覆盖，不在此列。
"""
import json
import os

TESTBED = os.path.join(os.path.dirname(__file__), '..', 'data',
                       'modules', 'e2e_testbed')


def _load(name):
    with open(os.path.join(TESTBED, name), encoding='utf-8') as f:
        return json.load(f)


def _all_entities(l2):
    for s in (l2.get("scenes") or {}).values():
        yield from s.get("interactions") or []
        yield from s.get("auto_triggers") or []
    yield from l2.get("events") or []


class TestFixtureCompleteness:
    def test_scene_items_hidden_and_exposed(self):
        l2 = _load("l2_keeper.json")
        items = [i for s in l2["scenes"].values()
                 for i in (s.get("scene_items") or [])]
        assert any(i.get("hidden") for i in items), "缺 hidden scene_item 实例"
        assert any(not i.get("hidden") for i in items), "缺 exposed scene_item 实例"

    def test_environment_two_axes(self):
        l2 = _load("l2_keeper.json")
        envs = [s.get("environment") for s in l2["scenes"].values()
                if s.get("environment")]
        assert any("lighting" in e for e in envs), "缺 environment.lighting 实例"
        assert any("noise" in e for e in envs), "缺 environment.noise 实例"

    def test_npc_attitude_value_and_attitude_min(self):
        l2 = _load("l2_keeper.json")
        profiles = l2.get("npc_profiles") or {}
        assert any(p.get("attitude_value") is not None
                   for p in profiles.values()), "缺 NPC attitude_value 实例"
        assert any(e.get("attitude_min") is not None or
                   (e.get("extra") or {}).get("attitude_min") is not None
                   for e in _all_entities(l2)), "缺 interaction attitude_min 实例"

    def test_repeatable_entity(self):
        l2 = _load("l2_keeper.json")
        assert any(e.get("repeatable") for e in _all_entities(l2)), \
            "缺 repeatable: true 实体实例"

    def test_npc_dead_requirement(self):
        l2 = _load("l2_keeper.json")
        assert any("npc_dead:" in (e.get("requirement") or "")
                   for e in _all_entities(l2)), "缺 npc_dead: requirement 实例"

    def test_scheduled_events(self):
        l2 = _load("l2_keeper.json")
        evs = l2.get("scheduled_events") or []
        assert any(e.get("at_minutes") and e.get("markup")
                 for e in evs), "缺 scheduled_events 实例"

    def test_player_goal(self):
        l3 = _load("l3_designer.json")
        assert (l3.get("module_meta") or {}).get("player_goal"), \
            "缺 module_meta.player_goal"

    def test_multiple_endings(self):
        l3 = _load("l3_designer.json")
        assert len(l3.get("ending_conditions") or []) >= 2, \
            "缺多结局实例（>=2 个 ending_conditions）"

    def test_stock_elements_present(self):
        """存量元素回归：boss / time_condition / scene_weapons / graded_result / 多场景。"""
        l2 = _load("l2_keeper.json")
        assert l2.get("boss_encounters"), "boss_encounters 缺失"
        assert any(e.get("time_condition") for e in _all_entities(l2)), \
            "缺 time_condition 实例"
        assert any((s.get("scene_weapons") or []) for s in l2["scenes"].values()), \
            "缺 scene_weapons 实例"
        assert any(e.get("graded_result") for e in _all_entities(l2)), \
            "缺 graded_result 实例"
        assert len(l2["scenes"]) >= 2, "缺多场景"
        assert any((s.get("from_here") or []) for s in l2["scenes"].values()), \
            "缺跨场景 from_here"
