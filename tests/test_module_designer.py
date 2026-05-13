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
