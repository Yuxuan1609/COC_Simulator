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


# ── 2026-08-15 收尾：patch id 归一 / spawn·combat_end·boss 投影 / facts 补 Boss+物品 ──


def test_integrate_patch_records_real_entity_ids():
    """patch 实体缺 id 时构造回退 NEW_xxx，chronicle 必须记真实 id 而非空串。"""
    from game.agents.keeper import Keeper
    from game.messages import ModulePatch
    w = _make_world()
    keeper = Keeper(w)
    patch = ModulePatch(
        entities=[{"entity_type": "interaction", "name": "暗格",
                   "scene": "room_a", "type": "侦查", "requirement": "",
                   "trigger": "检查墙壁", "result": "发现暗格"}],
        scene_descriptions={}, justification="补暗格")
    keeper._integrate_patch(patch)
    ids = w.chronicle.patches[0]["entity_ids"]
    assert ids and all(ids), f"不得记空 id，实际 {ids}"
    node = w.graph.nodes["room_a"]
    assert ids == [e.id for e in node.interactions], "记录 id 必须与实际集成实体一致"


def _make_result_with_spawn():
    from game.messages import (TurnResult, TurnStatus, NarratorBrief,
                               ActionOutcome, ActionIntent)
    from game.side_effects import SpawnEnemy
    o = ActionOutcome(intent=ActionIntent(action="interaction"), success=True,
                      message="祭坛裂开", entity_id="EV_ALTAR",
                      entity_type="event", skill_tier="",
                      side_effects=[SpawnEnemy(enemy_ref="深潜者", scene="room_a", quantity=2)])
    brief = NarratorBrief(action_outcomes=[o], ambient_changes=[],
                          scene_snapshot=None, suggested_emphasis="")
    return TurnResult(status=TurnStatus.COMPLETED, brief=brief)


def test_record_turn_projects_spawn():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "触碰祭坛", _make_result_with_spawn(), w)
    assert c.events[0]["spawn"] == ["深潜者×2"]
    assert "spawn=深潜者×2" in c.render_for_author(w)


def _make_boss_world():
    """带 boss encounter 的 world：bosses 管理器挂好，实例预生成。"""
    w = _make_world()
    from game.boss_manager import BossManager
    from game.enemy_manager import EnemyManager

    class _Lib:
        def get(self, ref):
            return None
    w.enemies = EnemyManager(_Lib())
    w.bosses = BossManager(_Lib(), [{"id": "BOSS_T1", "boss_ref": "测试魔像",
                                     "scene": "room_a", "engage_type": "at"}])
    return w


def test_record_turn_projects_boss_engage_defeated():
    from scenario_core import WorldChronicle
    w = _make_boss_world()
    c = WorldChronicle()
    c.record_turn(1, "四处看看", _make_result(), w)
    assert "boss" not in c.events[0]

    w.bosses.mark_spawned("BOSS_T1")
    w.bosses._instance_ids["BOSS_T1"] = "inst_1"

    class _Inst:
        status = "engaged"
        enemy_ref = "测试魔像"
        scene = "room_a"
        flags = []
    w.enemies._instances["inst_1"] = _Inst()
    c.record_turn(2, "迎战", _make_result(), w)
    assert c.events[1]["boss"] == ["engage(BOSS_T1)"]

    w.enemies._instances["inst_1"].status = "dead"
    c.record_turn(3, "搜刮", _make_result(), w)
    assert c.events[2]["boss"] == ["defeated(BOSS_T1)"]

    c.record_turn(4, "离开", _make_result(), w)
    assert "boss" not in c.events[3], "diff 不得重复报"


def test_boss_seen_serialization_roundtrip():
    from scenario_core import WorldChronicle
    w = _make_boss_world()
    c = WorldChronicle()
    w.bosses.mark_spawned("BOSS_T1")
    c.record_turn(1, "迎战", _make_result(), w)
    back = WorldChronicle.from_dict(c.to_dict())
    c2 = WorldChronicle()
    c2.record_turn(1, "迎战", _make_result(), w)
    back.record_turn(2, "继续", _make_result(), w)
    assert "boss" not in back.events[-1], "读档后不得重报 engage"


def test_record_combat_end_annotates_last_event():
    from scenario_core import WorldChronicle
    w = _make_boss_world()
    c = WorldChronicle()
    w.bosses.mark_spawned("BOSS_T1")
    w.bosses._instance_ids["BOSS_T1"] = "inst_1"

    class _Inst:
        status = "engaged"
        enemy_ref = "测试魔像"
        scene = "room_a"
        flags = []
    w.enemies._instances["inst_1"] = _Inst()
    c.record_turn(1, "攻击", _make_result(), w)
    w.enemies._instances["inst_1"].status = "dead"
    c.record_combat_end("win", w)
    e = c.events[-1]
    assert e["combat_end"] == "win"
    assert "defeated(BOSS_T1)" in e.get("boss", []), "战斗同回合须捕到 defeated"
    assert len(c.events) == 1, "combat_end 标注在当回合，不新增条目"
    text = c.render_for_author(w)
    assert "combat=end(win)" in text


def test_complete_combat_turn_records_combat_end():
    """战斗结算统一入口 complete_combat_turn 必须把 outcome 记入编年史当回合。"""
    from game.agents.keeper import Keeper
    w = _make_world()
    keeper = Keeper(w)
    w.chronicle.record_turn(1, "攻击", _make_result(), w)
    keeper.complete_combat_turn("攻击", {"outcome": "win", "narrative": "x"})
    assert w.chronicle.events[-1]["combat_end"] == "win"


def test_render_facts_boss_block_and_key_items():
    from scenario_core import WorldChronicle
    from investigator import Investigator
    w = _make_boss_world()
    w.set_player(Investigator(name="t"))
    w.memory.key_items.append("测试钥匙")
    w.bosses.mark_spawned("BOSS_T1")
    w.bosses._instance_ids["BOSS_T1"] = "inst_1"

    class _Inst:
        status = "engaged"
        enemy_ref = "测试魔像"
        scene = "room_a"
        flags = []
        _current_phase = "狂暴"
    w.enemies._instances["inst_1"] = _Inst()
    text = WorldChronicle().render_for_author(w)
    assert "测试钥匙" in text, "玩家行须含关键物品"
    assert "Boss: BOSS_T1@room_a" in text and "狂暴" in text
    assert "未遭遇" not in text

    w2 = _make_boss_world()
    text2 = WorldChronicle().render_for_author(w2)
    assert "BOSS_T1" in text2 and "未遭遇" in text2, "未开战 Boss 也须可见"
