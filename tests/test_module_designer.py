"""module_designer 数据模型测试."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, LogicChain, SceneIntent, ToneConstraints
)


def test_scene_l1_roundtrip():
    scene = SceneL1(
        scene_name="6号车厢",
        entry_narrative="你醒来...",
        atmosphere="昏暗封闭",
        mood="uneasy",
        perceptible=[Perceptible(type="object", name="便签", brief="一张泛黄的纸条")],
        ambient_hints=["后方有震动"],
        npc_appearances=[],
    )
    d = scene.to_dict()
    restored = SceneL1.from_dict(d, "6号车厢")
    assert restored.entry_narrative == "你醒来..."
    assert len(restored.perceptible) == 1
    assert restored.perceptible[0].type == "object"


def test_scene_l2_roundtrip():
    scene = SceneL2(
        scene_name="6号车厢",
        description="调查员醒来的车厢",
        encounters=[Encounter(enemy_ref="Clicker", quantity=1)],
        scene_weapons=[SceneWeapon(weapon_ref="手电筒", location="座位下")],
        hidden_info=[HiddenInfo(
            info="地板上有血迹",
            trigger_condition="skill:侦查>=50",
            reveal_narrative="你注意到地板缝隙中有暗红色的痕迹"
        )],
    )
    d = scene.to_dict()
    restored = SceneL2.from_dict(d, "6号车厢")
    assert restored.description == "调查员醒来的车厢"
    assert len(restored.encounters) == 1
    assert restored.encounters[0].enemy_ref == "Clicker"


def test_npc_profile_roundtrip():
    npc = NPCProfile(
        name="京山人吉",
        role="关键情报源",
        motivation="保护乘客安全",
        knowledge=["怪物对声音敏感", "钥匙在3号车厢"],
        personality="冷静但焦虑",
    )
    d = npc.to_dict()
    restored = NPCProfile.from_dict(d)
    assert restored.name == "京山人吉"
    assert "怪物对声音敏感" in restored.knowledge


def test_l3_designer_roundtrip():
    l3 = L3Designer(
        module_meta=ModuleMeta(title="常暗之厢", era="1920s"),
        world_rules=[WorldRule(id="WR1", name="无路可退", rule="后方车厢被吞噬，只能前进")],
        logic_chains=[],
        scene_intents={"6号车厢": SceneIntent(purpose="苏醒点", danger_level="safe")},
        driving_force="电车正被奈亚拉托提普的化身吞噬",
    )
    d = l3.to_dict()
    restored = L3Designer.from_dict(d)
    assert restored.driving_force == "电车正被奈亚拉托提普的化身吞噬"
    assert len(restored.world_rules) == 1
    assert restored.world_rules[0].id == "WR1"


def test_l1_save_load():
    scenes = {
        "test_scene": SceneL1(scene_name="test_scene", atmosphere="测试"),
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        from module_designer.l1_player import save_l1, load_l1
        save_l1(scenes, path)
        loaded = load_l1(path)
        assert "test_scene" in loaded
        assert loaded["test_scene"].atmosphere == "测试"
    finally:
        os.unlink(path)


# ═══════════════════════════════════════════════════════════════
#  layered_schema 测试
# ═══════════════════════════════════════════════════════════════

from module_designer.layered_schema import (
    validate_l1, validate_l2, validate_l3, validate_all, is_valid,
)


def test_validate_l1_valid():
    data = {
        "6号车厢": {
            "entry_narrative": "你醒来...",
            "atmosphere": "昏暗封闭",
            "mood": "uneasy",
            "perceptible": [
                {"type": "object", "name": "便签", "brief": "一张纸条"}
            ],
            "ambient_hints": ["后方有震动"],
            "npc_appearances": [],
        }
    }
    report = validate_l1(data)
    assert report.is_valid
    assert len(report.errors) == 0


def test_validate_l1_invalid_mood():
    data = {
        "test": {
            "mood": "happy",  # 不在枚举中
        }
    }
    report = validate_l1(data)
    # 枚举违规是 warning，不是 error（LLM 可能生成近似值，后续可自动修正）
    assert any("happy" in w.message for w in report.warnings)


def test_validate_l2_valid():
    data = {
        "scenes": {
            "6号车厢": {
                "description": "测试场景",
                "interactions": [
                    {"type": "调查", "name": "搜查桌面", "difficulty": "regular"}
                ],
                "encounters": [
                    {"enemy_ref": "Clicker", "quantity": 1}
                ],
            }
        },
        "events": [
            {"id": "E1", "name": "测试事件"}
        ],
        "npc_profiles": {
            "NPC1": {"name": "NPC1", "role": "关键人物"}
        },
    }
    report = validate_l2(data)
    assert report.is_valid


def test_validate_l3_valid():
    data = {
        "module_meta": {"title": "测试", "era": "1920s"},
        "world_rules": [
            {"id": "WR1", "name": "测试规则", "rule": "一条规则"}
        ],
        "logic_chains": [],
        "scene_intents": {
            "6号车厢": {"purpose": "苏醒点", "danger_level": "safe"}
        },
        "ending_conditions": [],
        "tone_constraints": {"genre": "克苏鲁恐怖"},
        "driving_force": "测试驱动力",
    }
    report = validate_l3(data)
    assert report.is_valid


def test_validate_l3_invalid_danger():
    data = {
        "scene_intents": {
            "test": {"danger_level": "impossible"}  # 不在枚举中
        }
    }
    report = validate_l3(data)
    assert any("impossible" in w.message for w in report.warnings)


def test_validate_all():
    l1 = {"test": {"mood": "uneasy"}}
    l2 = {"scenes": {}, "events": [], "npc_profiles": {}}
    l3 = {"driving_force": "test"}
    reports = validate_all(l1, l2, l3)
    assert all(r.is_valid for r in reports.values())
    assert is_valid(l1, l2, l3)


# ═══════════════════════════════════════════════════════════════
#  layered_parser 测试（prompt 构建 + 桩函数测试）
# ═══════════════════════════════════════════════════════════════

from module_designer.layered_parser import (
    build_l1_prompt, build_l2_prompt, build_l3_prompt,
)


def test_build_l1_prompt_structure():
    prompt = build_l1_prompt("测试模组内容")
    assert "L1" in prompt or "玩家初始感知" in prompt or "6号车厢" in prompt
    assert "测试模组内容" in prompt
    assert "entry_narrative" in prompt
    assert "perceptible" in prompt


def test_build_l2_prompt_structure():
    prompt = build_l2_prompt("测试模组内容")
    assert "测试模组内容" in prompt
    assert "interactions" in prompt
    assert "side_effects" in prompt
    assert "encounters" in prompt
    assert "hidden_info" in prompt


def test_build_l3_prompt_structure():
    prompt = build_l3_prompt("测试模组内容")
    assert "测试模组内容" in prompt
    assert "world_rules" in prompt
    assert "logic_chains" in prompt
    assert "driving_force" in prompt


# ═══════════════════════════════════════════════════════════════
#  layered_pipeline 测试（交叉引用验证）
# ═══════════════════════════════════════════════════════════════

from module_designer.layered_pipeline import (
    cross_validate_layers, run_pipeline, PipelineResult, CrossRefReport,
)


def test_cross_validate_clean_data():
    l1 = {
        "6号车厢": {
            "perceptible": [
                {"type": "object", "name": "便签", "brief": "纸条",
                 "linked_interaction": "搜查桌面"}
            ]
        }
    }
    l2 = {
        "scenes": {
            "6号车厢": {
                "interactions": [
                    {"type": "调查", "name": "搜查桌面"}
                ]
            }
        },
        "events": [],
        "npc_profiles": {},
    }
    l3 = {"scene_intents": {"6号车厢": {"purpose": "test"}}}
    report = cross_validate_layers(l1, l2, l3)
    assert report.is_valid


def test_cross_validate_missing_interaction():
    l1 = {
        "6号车厢": {
            "perceptible": [
                {"type": "object", "name": "便签", "brief": "纸条",
                 "linked_interaction": "不存在的互动"}
            ]
        }
    }
    l2 = {"scenes": {"6号车厢": {"interactions": []}}, "events": [], "npc_profiles": {}}
    l3 = {}
    report = cross_validate_layers(l1, l2, l3)
    # L1→L2 引用缺失是 warning（pipeline 后续可能自动补充），但仍会在 report 中记录
    assert any("不存在的互动" in i.message for i in report.issues)


def test_pipeline_result_summary():
    result = PipelineResult()
    result.l1_data = {"test": {}}
    result.l2_data = {"scenes": {}, "events": [], "npc_profiles": {}}
    result.l3_data = {}
    result.schema_reports = validate_all(result.l1_data, result.l2_data, result.l3_data)
    result.cross_ref_report = CrossRefReport()
    summary = result.summary()
    assert "L1" in summary
    assert "L2" in summary
    assert "L3" in summary
