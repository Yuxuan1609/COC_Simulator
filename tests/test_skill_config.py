import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils import load_skill_config, normalize_skill_name, get_coc_skill_names


def test_config_loads_20_skills_8_attributes():
    cfg = load_skill_config()
    assert len(cfg["skills"]) == 20
    assert set(cfg["attributes"].keys()) == {
        "STR", "CON", "DEX", "APP", "INT", "POW", "EDU", "LUCK"}
    names = [s["name"] for s in cfg["skills"]]
    assert "侦查" in names and "话术" not in names


def test_normalize_exact_new_skill():
    assert normalize_skill_name("侦查") == ("skill", "侦查")


def test_normalize_legacy_map():
    assert normalize_skill_name("话术") == ("skill", "说服")
    assert normalize_skill_name("急救") == ("skill", "生存")
    assert normalize_skill_name("导航") == ("skill", "侦查")


def test_normalize_weapon_skill_names():
    """武器库 skill_name 归一(2026-08-19 已知观察收口:手枪/步枪/霰弹枪 -> 枪械)。"""
    assert normalize_skill_name("手枪") == ("skill", "枪械")
    assert normalize_skill_name("步枪") == ("skill", "枪械")
    assert normalize_skill_name("霰弹枪") == ("skill", "枪械")


def test_normalize_bracket_specialization():
    assert normalize_skill_name("格斗(拳)") == ("skill", "格斗")
    assert normalize_skill_name("射击（手枪）") == ("skill", "枪械")


def test_normalize_bracket_fallback_to_attr_and_pseudo():
    assert normalize_skill_name("敏捷（检定）") == ("attr", "DEX")


def test_normalize_empty_and_none():
    assert normalize_skill_name("") == ("unknown", "")
    assert normalize_skill_name(None) == ("unknown", "")


def test_custom_path_does_not_pollute_cache(tmp_path):
    import json
    alt = tmp_path / "alt_config.json"
    alt.write_text(json.dumps({"skills": [{"name": "假技能", "attr": [], "base": 0}]}),
                   encoding="utf-8")
    load_skill_config(str(alt))
    assert "假技能" not in get_coc_skill_names()


def test_normalize_attr_alias():
    assert normalize_skill_name("敏捷") == ("attr", "DEX")
    assert normalize_skill_name("意志") == ("attr", "POW")
    assert normalize_skill_name("SIZ") == ("attr", "CON")
    assert normalize_skill_name("灵感") == ("attr", "INT")


def test_normalize_pseudo_dodge():
    assert normalize_skill_name("回避") == ("pseudo", "DODGE")
    assert normalize_skill_name("闪避") == ("pseudo", "DODGE")


def test_normalize_deprecated_and_unknown():
    assert normalize_skill_name("母语") == ("ignore", "母语")
    assert normalize_skill_name("炼金术") == ("unknown", "炼金术")


def test_skill_names_from_config():
    names = get_coc_skill_names()
    assert len(names) == 20 and "运动" in names


def test_stats_no_siz_derived_no_mov():
    from investigator.models import Stats, DerivedStats
    s = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    assert not hasattr(s, "SIZ")
    d = DerivedStats()
    assert not hasattr(d, "MOV")


def test_check_skill_legacy_name_normalized():
    from investigator.models import Investigator, Skill
    inv = Investigator(name="t")
    inv.skills.append(Skill(name="说服", base_value=15, value=50))
    ok, msg, tier = inv.check_skill("话术")  # legacy → 说服
    assert "话术" in msg and "未掌握" not in msg


def test_check_skill_attr_channel():
    import random
    random.seed(0)  # DEX=99 时 roll≥96 大失败，定种子防 flake
    from investigator.models import Investigator, Stats
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=99, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    ok, msg, tier = inv.check_skill("敏捷")  # 属性通路，阈值=DEX=99
    assert ok and "未掌握" not in msg


def test_check_skill_unknown_warns_and_passes():
    from investigator.models import Investigator
    inv = Investigator(name="t")
    ok, msg, tier = inv.check_skill("炼金术")
    assert ok and "未掌握" in msg
    assert any("炼金术" in w for w in inv.check_warnings)


def test_spend_luck_and_pending_bonus():
    from investigator.models import Investigator, Stats, Skill
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    ok, msg = inv.spend_luck(10)
    assert ok and inv.stats.LUCK == 40
    inv.pending_luck_bonus = 10
    inv.skills.append(Skill(name="侦查", base_value=25, value=25))
    ok2, msg2, _ = inv.check_skill("侦查")
    assert inv.pending_luck_bonus == 0, "幸运加值必须一次性消费"
    ok3, _ = inv.spend_luck(99)
    assert not ok3, "余额不足必须拒绝"


def test_check_skill_pseudo_dodge():
    import random
    random.seed(0)  # DODGE=99 时 roll≥96 大失败，定种子防 flake
    from investigator.models import Investigator
    inv = Investigator(name="t")
    inv.derived.DODGE = 99
    ok, msg, tier = inv.check_skill("闪避")
    assert ok and "未掌握" not in msg


def test_modify_stat_con_recalcs_hp():
    from investigator.models import Investigator, Stats
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    inv.derived.HP = inv.derived.HP_MAX = 20
    inv.modify_stat("CON", -30)  # 跌到 30 → HP_MAX=10，HP 压到 10
    assert inv.derived.HP_MAX == 10 and inv.derived.HP <= 10
    inv.modify_stat("LUCK", -5)
    assert inv.stats.LUCK == 45


def test_roll_stats_no_siz():
    from investigator.rules import roll_stats
    s = roll_stats()
    assert not hasattr(s, "SIZ")
    assert 15 <= s.STR <= 90 and 40 <= s.INT <= 90


def test_calc_derived_new_formulas():
    from investigator.models import Stats
    from investigator.rules import calc_derived
    s = Stats(STR=80, CON=60, DEX=70, APP=50, INT=60, POW=55, EDU=65, LUCK=40)
    d = calc_derived(s)
    assert d.HP == 20 and d.HP_MAX == 20          # CON//3
    assert d.MP == 11 and d.SAN == 55              # POW//5 / POW
    assert d.DODGE == 35                           # DEX//2
    assert not hasattr(d, "MOV")
    # DB/BUILD 查表键 = STR + CON//2 = 80+30 = 110 → "0"/0
    assert d.DB == "0" and d.BUILD == 0


def test_create_skill_list_from_config():
    from investigator.rules import create_skill_list
    skills = create_skill_list()
    assert len(skills) == 20
    spot = next(s for s in skills if s.name == "侦查")
    assert spot.base_value == 25 and spot.value == 25


def test_allocate_attribute_pools():
    from investigator.models import Stats
    from investigator.rules import create_skill_list, allocate_skill_points
    stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    skills = create_skill_list()
    allocate_skill_points(skills, stats, focus=["侦查"], focus_bonus=10)
    spot = next(s for s in skills if s.name == "侦查")
    # 池：INT=60*1.5=90，EDU=60*1.5=90，各均分到归属技能后叠加；标签 +10
    assert spot.value > 25, "池分配后必须高于基础值"
    assert spot.value <= 99
    cthulhu = next(s for s in skills if s.name == "克苏鲁神话")
    assert cthulhu.value == 0, "克苏鲁神话不走池"
    luck = next((s for s in skills if s.name == "幸运"), None)
    assert luck is None, "LUCK 不在技能列表"


def test_load_occupation_labels():
    from investigator.rules import load_occupation_labels
    labels = load_occupation_labels()
    names = [l["name"] for l in labels]
    assert "侦探" in names and "自定义" in names


def test_roundtrip_new_structure():
    import tempfile
    from investigator.models import Investigator, Stats, Skill
    from investigator.rules import calc_derived
    from investigator.serialization import to_json, from_json
    inv = Investigator(name="新卡", age=30)
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    inv.derived = calc_derived(inv.stats)
    inv.skills.append(Skill(name="侦查", base_value=25, value=50))
    inv.label = "侦探"
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "c.json")
        to_json(inv, p)
        back = from_json(p)
    assert back.name == "新卡" and back.label == "侦探"
    assert back.get_skill("侦查").value == 50
    assert not hasattr(back.stats, "SIZ")


def test_old_card_rejected():
    import pytest
    from investigator.serialization import from_dict
    old = {"meta": {"version": "1.0"}, "personal": {"name": "旧卡"},
           "stats": {"STR": 60, "CON": 60, "SIZ": 65, "DEX": 60, "APP": 50,
                     "INT": 60, "POW": 55, "EDU": 65, "LUCK": 40},
           "skills": [{"name": "话术", "base": 5, "value": 40}]}
    with pytest.raises(ValueError, match="重建"):
        from_dict(old)


def test_allocate_attribute_pools_exact_value():
    """池语义精确断言（review 补充：>25 太松）。"""
    from investigator.models import Stats
    from investigator.rules import create_skill_list, allocate_skill_points
    stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    skills = create_skill_list()
    allocate_skill_points(skills, stats, focus=["侦查"], focus_bonus=10)
    spot = next(s for s in skills if s.name == "侦查")
    # INT 池 90/归属6技能=15；EDU 池 90/归属10技能=9；base 25 + 15 + 9 + focus 10 = 59
    assert spot.value == 59


def test_pipeline_stat_names_no_siz():
    """stat_names 不含 SIZ（SIZ→CON 由 attr_aliases 兜底）。"""
    import re
    src = open("src/module_designer/layered_pipeline.py", encoding="utf-8").read()
    m = re.search(r"stat_names\s*=\s*\[([^\]]*)\]", src)
    assert m and '"SIZ"' not in m.group(1)


def test_normalize_entity_type_for_storage():
    """落库归一：旧技能名→新名；属性名/未知名保留原文。"""
    from utils import normalize_skill_name
    assert normalize_skill_name("话术") == ("skill", "说服")
    assert normalize_skill_name("敏捷")[0] == "attr"


def test_modify_stat_siz_maps_to_con():
    """spec 7.2：旧模组 @stat_change(SIZ) 映射到 CON。"""
    from investigator.models import Investigator, Stats
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    inv.derived.HP = inv.derived.HP_MAX = 20
    inv.modify_stat("SIZ", -10)
    assert inv.stats.CON == 50, f"SIZ 必须映射 CON，实际 CON={inv.stats.CON}"
