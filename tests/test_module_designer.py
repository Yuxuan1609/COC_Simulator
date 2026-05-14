"""module_designer 数据模型测试."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from module_designer.l1_player import SceneL1, Perceptible, NPCAppearance
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, AutoTrigger, NPCProfile
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, SceneIntent, ToneConstraints, EndingCondition,
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
        auto_triggers=[AutoTrigger(
            id="AT1",
            name="发现血迹",
            scene="S1",
            trigger_condition="调查员搜索地板时触发",
            effect_type="reveal_info",
            effect_ref="",
            reveal_narrative="你注意到地板缝隙中有暗红色的痕迹",
        )],
    )
    d = scene.to_dict()
    restored = SceneL2.from_dict(d, "6号车厢")
    assert restored.description == "调查员醒来的车厢"
    assert len(restored.encounters) == 1
    assert restored.encounters[0].enemy_ref == "Clicker"
    assert len(restored.auto_triggers) == 1
    assert restored.auto_triggers[0].id == "AT1"
    assert restored.auto_triggers[0].effect_type == "reveal_info"


def test_auto_trigger_roundtrip():
    at = AutoTrigger(
        id="AT1", name="Clicker 出现", scene="S2",
        trigger_condition="玩家进入7号车厢且持有钥匙",
        effect_type="spawn_enemy", effect_ref="Clicker",
        reveal_narrative="",
    )
    d = at.to_dict()
    restored = AutoTrigger.from_dict(d)
    assert restored.id == "AT1"
    assert restored.effect_type == "spawn_enemy"
    assert restored.effect_ref == "Clicker"


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
        scene_intents={"6号车厢": SceneIntent(purpose="苏醒点")},
        tone_constraints=ToneConstraints(genre="克苏鲁恐怖", recommended=["压迫感"]),
        ending_conditions=[EndingCondition(id="END1", condition="加速逃脱", narrative="重见光明")],
        driving_force="电车正被奈亚拉托提普的化身吞噬",
    )
    d = l3.to_dict()
    restored = L3Designer.from_dict(d)
    assert restored.driving_force == "电车正被奈亚拉托提普的化身吞噬"
    assert len(restored.world_rules) == 1
    assert restored.world_rules[0].id == "WR1"
    assert restored.tone_constraints.recommended == ["压迫感"]
    assert restored.ending_conditions[0].narrative == "重见光明"


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
                "auto_triggers": [
                    {
                        "id": "AT1",
                        "name": "发现血迹",
                        "trigger_condition": "玩家搜索地板时触发",
                        "effect_type": "reveal_info",
                    }
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
        "scene_intents": {
            "6号车厢": {"purpose": "苏醒点"}
        },
        "ending_conditions": [],
        "tone_constraints": {"genre": "克苏鲁恐怖"},
        "driving_force": "测试驱动力",
    }
    report = validate_l3(data)
    assert report.is_valid


def test_validate_l3_invalid_ending_missing_id():
    data = {
        "ending_conditions": [
            {"condition": "trigger condition"}  # 缺少必填 id
        ]
    }
    report = validate_l3(data)
    assert any("必填字段" in w.message for w in report.warnings)


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
    build_step1a_prompt, build_step1b_prompt,
    build_step2a_prompt, build_step2b_events_prompt, build_step2b_at_prompt,
    build_step2c_l1_prompt, build_step2c_l3_prompt,
    build_step3a_prompt, build_step3b_prompt, build_step4_prompt,
)


def test_build_step1a_prompt_structure():
    prompt = build_step1a_prompt("测试模组内容\n包含6号车厢和7号车厢")
    assert "测试模组内容" in prompt
    assert "scenes" in prompt
    assert "characters" in prompt
    assert "module_meta" in prompt


def test_build_step1b_prompt_structure():
    prompt = build_step1b_prompt("测试模组内容")
    assert "测试模组内容" in prompt
    assert "## module_overview" in prompt
    assert "## scenes" in prompt
    assert "## npcs" in prompt
    assert "## clues_and_items" in prompt
    assert "## events_summary" in prompt


# ═══════════════════════════════════════════════════════════════
#  layered_pipeline 测试（交叉引用验证）
# ═══════════════════════════════════════════════════════════════

from module_designer.layered_pipeline import (
    cross_validate_layers, run_pipeline, PipelineResult, CrossRefReport, save_pipeline_result,
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


def test_pipeline_result_summary_with_fallbacks():
    from module_designer.layered_pipeline import PipelineResult
    from module_designer.layered_schema import validate_all
    result = PipelineResult()
    result.fallbacks = ["Step 1a", "Step 3a"]
    result.l1_data = {"test": {}}
    result.l2_data = {"scenes": {}, "events": [], "npc_profiles": {}}
    result.l3_data = {}
    result.schema_reports = validate_all(result.l1_data, result.l2_data, result.l3_data)
    summary = result.summary()
    assert "Step 1a" in summary
    assert "Step 3a" in summary


def test_build_step2a_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}, {"id": "S2", "name": "7号车厢"}]
    prompt = build_step2a_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "interactions" in prompt
    assert "I1" in prompt
    assert "S1" in prompt
    assert "enemy_ref" in prompt
    assert "weapon_ref" in prompt
    assert "null" in prompt


def test_build_step2b_events_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": []}]
    prompt = build_step2b_events_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "events" in prompt
    assert "E1" in prompt
    assert "I1" in prompt


def test_build_step2b_at_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": []}]
    prompt = build_step2b_at_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "auto_triggers" in prompt
    assert "AT1" in prompt
    assert "reveal_info" in prompt
    assert "effect_ref" in prompt


def test_build_step2c_l1_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step2c_l1_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "感知" in prompt or "perceptible" in prompt
    assert "6号车厢" in prompt


def test_build_step2c_l3_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step2c_l3_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "world_rules" in prompt
    assert "driving_force" in prompt
    assert "scene_intents" in prompt


def test_build_step3a_prompt_structure():
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "requirement": "需要先找到线索"}]
    events = [{"id": "E1", "name": "事件", "requirement": "interaction I1 完成后"}]
    auto_triggers = [{"id": "AT1", "name": "触发", "scene": "S1", "trigger_condition": "玩家进入场景"}]
    prompt = build_step3a_prompt("精修模组", interactions, events, auto_triggers)
    assert "I1" in prompt
    assert "E1" in prompt
    assert "AT1" in prompt
    assert "flag" in prompt.lower()
    assert "requirement" in prompt


def test_build_step3b_prompt_structure():
    l1 = {"6号车厢": {"entry_narrative": "测试"}}
    l2 = {"interactions": [{"id": "I1", "name": "搜查"}], "events": [], "auto_triggers": []}
    l3 = {"scene_intents": {"6号车厢": {"purpose": "测试"}}}
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step3b_prompt("精修模组", l1, l2, l3, scenes)
    assert "linked_interaction" in prompt
    assert "6号车厢" in prompt
    assert "scene_intents" in prompt


def test_build_step4_prompt_structure():
    interactions = [{"id": "I1", "name": "战斗", "enemy_ref": None, "weapon_ref": None}]
    auto_triggers = [{"id": "AT1", "name": "触发", "effect_ref": None}]
    prompt = build_step4_prompt(
        interactions, auto_triggers,
        {"S1": "测试场景"},
        {"6号车厢": {"purpose": "测试"}},
        "精修模组参考",
        ["手电筒", ".45自动手枪"],
        ["Clicker", "深潜者"],
    )
    assert "Clicker" in prompt
    assert "手电筒" in prompt
    assert ".45自动手枪" in prompt
    assert "enemy_ref" in prompt
    assert "weapon_ref" in prompt
    assert "effect_ref" in prompt
