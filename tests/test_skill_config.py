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
