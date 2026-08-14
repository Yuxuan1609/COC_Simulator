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
    from investigator.models import Investigator
    inv = Investigator(name="t")
    inv.derived.DODGE = 99
    ok, msg, tier = inv.check_skill("闪避")
    assert ok and "未掌握" not in msg
