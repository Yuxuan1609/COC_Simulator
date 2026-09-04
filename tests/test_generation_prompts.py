"""生成 prompt 最小回填防回退：新字段/词表/语义必须出现在 prompt 文本中（spec §2）。

只断言「说明存在」，不断言教学措辞——prompt 从简约定，管线系统升级时允许重写措辞。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestStep2APrompt:
    def test_scene_items_and_environment_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "scene_items" in STEP2A_SYSTEM
        assert "environment" in STEP2A_SYSTEM
        assert "hidden" in STEP2A_SYSTEM
        assert "quiet" in STEP2A_SYSTEM  # noise 合法值，不是 normal

    def test_difficulty_semantics_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "半数" in STEP2A_SYSTEM or "半值" in STEP2A_SYSTEM
        assert "1/5" in STEP2A_SYSTEM or "五分之一" in STEP2A_SYSTEM

    def test_repeatable_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "repeatable" in STEP2A_SYSTEM


class TestStep4Prompt:
    def test_new_markup_verbs_documented(self):
        from module_designer.layered_parser import STEP4_SYSTEM
        assert "@attitude_change" in STEP4_SYSTEM
        assert "@env_change" in STEP4_SYSTEM
        assert "npc_dead:" in STEP4_SYSTEM
        assert "quiet" in STEP4_SYSTEM  # noise 合法值写进 @env_change 说明

    def test_mythos_pattern_documented(self):
        from module_designer.layered_parser import STEP4_SYSTEM
        assert "克苏鲁神话" in STEP4_SYSTEM


class TestStep25Prompt:
    def test_attitude_value_in_output(self):
        from module_designer.layered_parser import STEP25_COMBINED_SYSTEM
        assert "attitude_value" in STEP25_COMBINED_SYSTEM
        assert "devoted" in STEP25_COMBINED_SYSTEM
        assert "allied" not in STEP25_COMBINED_SYSTEM


class TestAssembleL2:
    def test_passthrough_scene_items_and_environment(self):
        from module_designer.layered_pipeline import _assemble_l2
        l2 = _assemble_l2(
            [], [], [],
            {"石室": {
                "from_here": [], "to_here": [],
                "scene_items": [{"kind": "item", "ref": "钥匙",
                                 "quantity": 1, "hidden": True}],
                "environment": {"lighting": "dim"},
            }},
            {},
        )
        scene = l2["scenes"]["石室"]
        assert scene["scene_items"][0]["ref"] == "钥匙"
        assert scene["environment"]["lighting"] == "dim"
