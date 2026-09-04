"""生成端 schema 契约：NPC 态度字段 + 枚举/中值单一事实源 + 场景嵌套（spec §1.1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _attitude_rows():
    from investigator.rules import get_game_config
    return get_game_config()["npc_attitude_tiers"]


class TestNpcProfileSchema:
    def test_attitude_value_field_accepted(self):
        """attitude_value 合法值不产生违规。未知字段静默时本测可能已绿，作锁测。"""
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": -75}}}
        report = validate_l2(data)
        assert not [v for v in report.violations if "attitude_value" in v.path]

    def test_attitude_value_out_of_range_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": 150}}}
        report = validate_l2(data)
        assert any("attitude_value" in v.path and v.severity == "warning"
                   for v in report.violations)

    def test_initial_attitude_enum_aligned_with_runtime(self):
        from module_designer.layered_schema import validate_l2
        keys = [t["key"] for t in _attitude_rows()]
        assert set(keys) == {"hostile", "wary", "neutral", "friendly", "devoted"}
        good = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "devoted"}}}
        assert not [v for v in validate_l2(good).violations
                    if "initial_attitude" in v.path]
        bad = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "allied"}}}
        assert any("initial_attitude" in v.path
                   for v in validate_l2(bad).violations)

    def test_runtime_known_profile_fields_accepted(self):
        from module_designer.layered_schema import L2_NPC_PROFILE_SCHEMA
        for f in ("attitude_value", "scene", "all_scenes",
                  "bound_interactions", "bound_auto_triggers"):
            assert f in L2_NPC_PROFILE_SCHEMA, f"schema 缺字段 {f}"

    def test_attitude_midpoints_single_source(self):
        """中值只来自 game_config.mid；npc_manager 无私有表。"""
        from game.npc_manager import _attitude_value_from_key
        import game.npc_manager as nm
        expected = {"hostile": -75, "wary": -30, "neutral": 0,
                    "friendly": 30, "devoted": 75}
        for row in _attitude_rows():
            assert row["mid"] == expected[row["key"]], row
            assert _attitude_value_from_key(row["key"]) == row["mid"]
        assert not hasattr(nm, "_ATTITUDE_MIDPOINTS")


class TestSceneNestedSchema:
    def test_illegal_noise_value_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"scenes": {"A": {"environment": {"noise": "normal"}}}}
        report = validate_l2(data)
        assert any("noise" in v.path for v in report.violations)

    def test_illegal_scene_item_kind_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"scenes": {"A": {"scene_items": [
            {"kind": "food", "ref": "面包", "quantity": 1, "hidden": False}]}}}
        report = validate_l2(data)
        assert any("kind" in v.path for v in report.violations)
