"""F32 试玩报告：纯聚合无 rubric（S3-P2 spec §6）。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _summary(turns, **kw):
    base = {"module": "m", "player": "p", "turns": len(turns),
            "total_elapsed_s": 754.0, "game_over": None,
            "goal_achieved": False, "profile": {}, "turns_detail": turns}
    base.update(kw)
    return base


def _turn(n, loc, **kw):
    base = {"turn": n, "input": "x", "brief": "", "narrative": "",
            "skill_results": [], "combat": None, "npc_events": [],
            "npcs_visible": {}, "pending": None, "location": loc,
            "weapons": [], "player_alive": True, "ending": None,
            "elapsed_s": 16.0, "time_state": {}, "time_agent": None,
            "mech": ""}
    base.update(kw)
    return base


def _sr(eid, success=True, tier="regular"):
    return {"entity_id": eid, "entity_type": "interaction",
            "tier": tier, "success": success, "raw_check": {}}


class TestPlaytestReport:
    def test_scene_coverage(self):
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房"), _turn(2, "书房"), _turn(3, "走廊")]
        module = {"scenes": {"书房": {}, "走廊": {}, "阁楼": {}, "地下室": {}}}
        rep = build_report(_summary(turns), module)
        assert rep["scene_coverage"]["visited"] == 2
        assert rep["scene_coverage"]["total"] == 4
        assert "阁楼" in rep["scene_coverage"]["missing"]
        assert "地下室" in rep["scene_coverage"]["missing"]
        assert "书房" not in rep["scene_coverage"]["missing"]

    def test_ending_reached_with_turn(self):
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房"), _turn(2, "走廊"),
                 _turn(3, "出口", ending="ending_escape")]
        l3 = {"module_meta": {"title": "古宅钟声"},
              "ending_conditions": [{"id": "ending_escape"}, {"id": "ending_truth"}]}
        rep = build_report(_summary(turns), {"scenes": {"书房": {}, "走廊": {}, "出口": {}}}, l3)
        assert rep["endings"]["reached"] == "ending_escape"
        assert rep["endings"]["turn"] == 3
        assert "ending_truth" in rep["endings"]["missing"]
        assert "ending_escape" not in rep["endings"]["missing"]

    def test_ending_none(self):
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房")]
        l3 = {"ending_conditions": [{"id": "ending_escape"}]}
        rep = build_report(_summary(turns), {"scenes": {"书房": {}}}, l3)
        assert rep["endings"]["reached"] is None
        assert rep["endings"]["turn"] is None
        assert "ending_escape" in rep["endings"]["missing"]

    def test_entity_trigger_rate_and_missing(self):
        from module_designer.playtest_report import build_report
        turns = [
            _turn(1, "书房", skill_results=[_sr("IT_A")]),
            _turn(2, "走廊",
                  mech='T02 [1.2s] in="搜" | intent=search | entities=IT_B:regular | at=AT_C'),
        ]
        module = {
            "scenes": {
                "书房": {"interactions": [{"id": "IT_A", "difficulty": "regular"}],
                       "auto_triggers": []},
                "走廊": {"interactions": [{"id": "IT_B", "difficulty": "hard"}],
                       "auto_triggers": [{"id": "AT_C"}]},
            },
            "events": [{"id": "EV_D"}],
        }
        trig = build_report(_summary(turns), module)["entity_trigger"]
        assert trig["triggered"] == 3
        assert trig["total"] == 4
        assert trig["missing"] == ["EV_D"]

    def test_entity_trigger_npc_bound_counts(self):
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房", skill_results=[_sr("IT_NPC")])]
        module = {
            "scenes": {"书房": {"interactions": [], "auto_triggers": []}},
            "npc_profiles": {
                "管家": {"bound_interactions": [{"id": "IT_NPC"}],
                       "bound_auto_triggers": [{"id": "AT_NPC"}]},
            },
        }
        trig = build_report(_summary(turns), module)["entity_trigger"]
        assert trig["total"] == 2
        assert trig["triggered"] == 1
        assert "AT_NPC" in trig["missing"]

    def test_check_difficulty_distribution(self):
        """skill_results × 模组 difficulty 交叉统计。"""
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房", skill_results=[
            _sr("IT_A", success=True),
            _sr("IT_A", success=False, tier="failure"),
            _sr("IT_B", success=True, tier="hard"),
            _sr("IT_UNKNOWN", success=False),
        ])]
        module = {"scenes": {"书房": {"interactions": [
            {"id": "IT_A", "difficulty": "regular"},
            {"id": "IT_B", "check": {"difficulty": "hard"}},
        ]}}}
        dist = build_report(_summary(turns), module)["check_distribution"]
        assert dist["regular"]["success"] == 1
        assert dist["regular"]["failure"] == 1
        assert dist["hard"]["success"] == 1
        assert dist["unknown"]["failure"] == 1

    def test_elapsed_and_turns(self):
        from module_designer.playtest_report import build_report
        turns = [_turn(1, "书房"), _turn(2, "走廊")]
        rep = build_report(_summary(turns, total_elapsed_s=754.0),
                          {"scenes": {"书房": {}, "走廊": {}}})
        assert rep["elapsed"]["total_elapsed_s"] == 754.0
        assert rep["elapsed"]["turns"] == 2

    def test_markdown_output(self):
        """render_markdown 产出含四个指标段的报告文本。"""
        from module_designer.playtest_report import build_report, render_markdown
        turns = [
            _turn(1, "书房", skill_results=[_sr("IT_A")]),
            _turn(3, "走廊", ending="ending_escape"),
        ]
        module = {"scenes": {"书房": {"interactions": [{"id": "IT_A"}]},
                            "走廊": {}, "阁楼": {}}}
        l3 = {"module_meta": {"title": "古宅钟声"},
              "ending_conditions": [{"id": "ending_escape"}, {"id": "ending_truth"}]}
        md = render_markdown(build_report(_summary(turns), module, l3))
        assert "古宅钟声" in md
        assert "场景覆盖率" in md
        assert "结局触达" in md
        assert "ending_escape" in md
        assert "实体触发率" in md
        assert "检定分布" in md
        assert "耗时" in md

    def test_empty_turns(self):
        """零回合不崩：各项为 0/空。"""
        from module_designer.playtest_report import build_report
        module = {"scenes": {"书房": {"interactions": [{"id": "IT_A"}]}, "阁楼": {}}}
        l3 = {"ending_conditions": [{"id": "ending_escape"}]}
        rep = build_report(_summary([], total_elapsed_s=0.0), module, l3)
        assert rep["scene_coverage"]["visited"] == 0
        assert rep["scene_coverage"]["total"] == 2
        assert set(rep["scene_coverage"]["missing"]) == {"书房", "阁楼"}
        assert rep["endings"]["reached"] is None
        assert rep["entity_trigger"]["triggered"] == 0
        assert rep["entity_trigger"]["total"] == 1
        assert rep["elapsed"]["turns"] == 0
        assert rep["check_distribution"] == {}

    def test_goal_fallback_to_player_goal(self):
        """llm_player profile 无 goal 时读 module_meta.player_goal。"""
        from module_designer.playtest_report import resolve_player_goal
        assert resolve_player_goal({}, {"module_meta": {"player_goal": "活着离开"}}) == "活着离开"

    def test_goal_fallback_to_driving_force(self):
        from module_designer.playtest_report import resolve_player_goal
        df = "x" * 100
        assert resolve_player_goal({}, {"driving_force": df}) == df[:80]

    def test_goal_profile_wins(self):
        from module_designer.playtest_report import resolve_player_goal
        assert resolve_player_goal(
            {"goal": "A"}, {"module_meta": {"player_goal": "B"}, "driving_force": "C"}
        ) == "A"

    def test_goal_empty(self):
        from module_designer.playtest_report import resolve_player_goal
        assert resolve_player_goal({}, {}) == ""
        assert resolve_player_goal({"goal": "  "}, {"module_meta": {"player_goal": "G"}}) == "G"

    def test_run_report_writes_files(self, tmp_path):
        from module_designer.playtest_report import run_report
        turns = [_turn(1, "书房", skill_results=[_sr("IT_A")])]
        summary = _summary(turns)
        (tmp_path / "_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        mod = tmp_path / "mod"
        mod.mkdir()
        (mod / "l2_keeper.json").write_text(json.dumps({
            "scenes": {"书房": {"interactions": [{"id": "IT_A", "difficulty": "regular"}]},
                       "阁楼": {}},
        }, ensure_ascii=False), encoding="utf-8")
        (mod / "l3_designer.json").write_text(json.dumps({
            "module_meta": {"title": "测"},
            "ending_conditions": [],
        }, ensure_ascii=False), encoding="utf-8")
        out = tmp_path / "report.json"
        rep = run_report(str(tmp_path / "_summary.json"), str(mod), str(out))
        assert out.exists()
        assert (tmp_path / "report.md").exists()
        assert rep["scene_coverage"]["visited"] == 1
        assert json.loads(out.read_text(encoding="utf-8"))["elapsed"]["turns"] == 1

    def test_run_report_prefers_l2_keeper_test(self, tmp_path):
        from module_designer.playtest_report import run_report
        turns = [_turn(1, "测试房")]
        (tmp_path / "_summary.json").write_text(
            json.dumps(_summary(turns), ensure_ascii=False), encoding="utf-8")
        mod = tmp_path / "mod"
        mod.mkdir()
        (mod / "l2_keeper.json").write_text(json.dumps({
            "scenes": {"正式房": {}},
        }, ensure_ascii=False), encoding="utf-8")
        (mod / "l2_keeper_test.json").write_text(json.dumps({
            "scenes": {"测试房": {}},
        }, ensure_ascii=False), encoding="utf-8")
        (mod / "l3_designer.json").write_text("{}", encoding="utf-8")
        rep = run_report(str(tmp_path / "_summary.json"), str(mod),
                         str(tmp_path / "report.json"))
        cov = rep["scene_coverage"]
        assert cov["total"] == 1
        assert cov["visited"] == 1
        assert cov["missing"] == []
        assert "测试房" not in cov["missing"]
