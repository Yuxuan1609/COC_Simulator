"""game_config 参数中心:缺省兜底 + 文件覆盖 + 缓存 reset。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from investigator import rules
from investigator.models import Stats, Skill


def setup_function():
    rules.reset_game_config_cache()


def teardown_function():
    # 本文件各测试会把 tmp 路径的配置写入模块级缓存;结束时必须清掉,
    # 否则 monkeypatch 还原 _CONFIG_PATH 后缓存与真实文件不一致,污染后续测试文件。
    rules.reset_game_config_cache()


def test_defaults_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 1
    assert cfg["timed_default_minutes"] == 30
    assert cfg["buff_damage_floor"] == 0


def test_file_overrides_defaults(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"mp_recovery_per_hour": 2}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 2
    assert cfg["timed_default_minutes"] == 30   # 未给字段用缺省


def test_partial_field_fallback(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text('{"mp_recovery_per_hour": "x"}', encoding="utf-8")  # 非法类型
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 1     # 类型不符回缺省,不崩


def test_non_dict_json_falls_back(monkeypatch, tmp_path):
    """合法 JSON 但非 dict(如 []) -> 全部字段回缺省,不崩。"""
    p = tmp_path / "game_config.json"
    p.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg == rules._GAME_CONFIG_DEFAULTS   # 逐键等于缺省表(F2 扩键后共 10 键)


def test_bool_value_rejected_for_int_default(monkeypatch, tmp_path):
    """bool 是 int 子类:JSON true 不得混入 int 缺省。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"mp_recovery_per_hour": True}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] is not True   # bool 被拒
    assert cfg["mp_recovery_per_hour"] == 1          # 回缺省


def test_returned_dict_mutation_not_pollute_cache(monkeypatch, tmp_path):
    """返回副本:调用方改 dict 不得污染模块级缓存。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"mp_recovery_per_hour": 2}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    cfg["mp_recovery_per_hour"] = 999
    assert rules.get_game_config()["mp_recovery_per_hour"] == 2


def test_cache_hit_no_reread_then_reset(monkeypatch, tmp_path):
    """缓存命中不重读文件;reset 后才读新路径。"""
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"mp_recovery_per_hour": 2}), encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"mp_recovery_per_hour": 3}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(a))
    assert rules.get_game_config()["mp_recovery_per_hour"] == 2
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(b))
    assert rules.get_game_config()["mp_recovery_per_hour"] == 2   # 缓存,不重读
    rules.reset_game_config_cache()
    assert rules.get_game_config()["mp_recovery_per_hour"] == 3   # reset 后读新路径


def test_new_keys_present():
    """F2 收编键齐全(默认值)。"""
    cfg = rules.get_game_config()
    assert cfg["stat_roll_multiplier"] == 5
    assert cfg["skill_value_cap"] == 99
    assert cfg["unarmed_damage"] == "1D3+DB"
    assert cfg["derived"] == {"hp_divisor": 3, "mp_divisor": 5,
                              "dodge_divisor": 2, "san_max_base": 99}
    assert len(cfg["db_build_table"]) == 6
    assert cfg["db_build_table"][-1] == {"max_key": None, "db": "+2D6", "build": 3}
    assert cfg["age_modifiers"]["start_age"] == 40
    assert cfg["age_modifiers"]["app_penalties"] == [-5, -10, -15, -20, -25]
    assert len(cfg["credit_rating_table"]) == 8
    assert cfg["credit_rating_table"][0] == [0, "身无分文"]


def test_nested_config_deep_copy():
    """嵌套结构返回深拷贝:改返回值不污染缓存。"""
    cfg1 = rules.get_game_config()
    cfg1["derived"]["hp_divisor"] = 99
    cfg1["db_build_table"][0]["db"] = "HACK"
    cfg2 = rules.get_game_config()
    assert cfg2["derived"]["hp_divisor"] == 3
    assert cfg2["db_build_table"][0]["db"] == "-2"


def test_nested_type_mismatch_falls_back(monkeypatch, tmp_path):
    """嵌套键类型不匹配回退默认。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"derived": 3, "db_build_table": "x",
                             "credit_rating_table": 9}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["derived"]["hp_divisor"] == 3
    assert cfg["db_build_table"][0]["db"] == "-2"
    assert cfg["credit_rating_table"][0] == [0, "身无分文"]


def test_shipped_json_matches_defaults():
    """data/game_config.json 与 _GAME_CONFIG_DEFAULTS 全量一致(双份维护锁定)。"""
    with open(rules._CONFIG_PATH, encoding="utf-8") as f:
        assert json.load(f) == rules._GAME_CONFIG_DEFAULTS


def test_calc_derived_reads_config(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"derived": {"hp_divisor": 2, "mp_divisor": 10,
                                          "dodge_divisor": 4, "san_max_base": 90}}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = Stats(STR=50, CON=60, DEX=70, APP=40, INT=60, POW=50, EDU=70, LUCK=50)
    d = rules.calc_derived(st)
    assert d.HP == 30      # 60 // 2
    assert d.MP == 5       # 50 // 10
    assert d.DODGE == 17   # 70 // 4
    assert d.SAN_MAX == 90


def test_db_build_table_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"db_build_table": [
        {"max_key": 100, "db": "+9D9", "build": 9},
        {"max_key": None, "db": "0", "build": 0}]}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules._calc_db_build(50) == ("+9D9", 9)
    assert rules._calc_db_build(150) == ("0", 0)


def test_age_modifiers_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"age_modifiers": {"start_age": 20, "max_tier": 1,
                                                "app_penalties": [-1, -2],
                                                "phys_penalties": [0, -3],
                                                "edu_bonuses": [1, 2]}}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    rules.apply_age_modifiers(st, 35)   # (35-20)//10 = tier 1
    assert st.APP == 48 and st.STR == 47 and st.CON == 47 and st.DEX == 47
    assert st.EDU == 52


def test_credit_rating_table_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"credit_rating_table": [[0, "穷"], [80, "豪"]]}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules.get_credit_level(90) == "豪"
    assert rules.get_credit_level(10) == "穷"


def test_skill_cap_and_unarmed_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"skill_value_cap": 80, "unarmed_damage": "1D2"}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules.create_default_unarmed().damage == "1D2"
    sk = [Skill(name="射击", base_value=50, value=50, category="DEX")]
    st = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    out = rules.allocate_skill_points(sk, st, focus=["射击"], focus_bonus=100)
    assert out[0].value == 80   # 50+100 被 cap 80 截断


def test_nested_inner_bad_value_falls_back(monkeypatch, tmp_path):
    """嵌套内层坏值(derived.hp_divisor 字符串)整体回退默认(不炸消费方)。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"derived": {"hp_divisor": "x"}}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["derived"]["hp_divisor"] == 3


def test_roll_stats_range_matches_dice_config():
    """骰面读 skill_config.dice:STR 3D6*5∈[15,90];INT/EDU (2D6+6)*5∈[40,90]。"""
    for _ in range(200):
        st = rules.roll_stats()
        assert 15 <= st.STR <= 90
        assert 15 <= st.CON <= 90 and 15 <= st.DEX <= 90
        assert 40 <= st.INT <= 90 and 40 <= st.EDU <= 90
        assert 15 <= st.POW <= 90 and 15 <= st.LUCK <= 90


def test_roll_stats_multiplier_config(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"stat_roll_multiplier": 1}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = rules.roll_stats()
    assert 3 <= st.STR <= 18    # 3D6*1
    assert 8 <= st.INT <= 18    # (2D6+6)*1


def test_db_build_table_row_bad_value_falls_back(monkeypatch, tmp_path):
    """db_build_table 行内坏值(max_key 字符串/缺键)整体回退默认。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"db_build_table": [
        {"max_key": "oops", "db": "-2", "build": -2},
        {"max_key": None, "db": "0", "build": 0}]}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["db_build_table"][0]["max_key"] == 64


def test_age_tables_asymmetric_no_crash(monkeypatch, tmp_path):
    """三数组不对称(phys 配短)不炸:tier 统一 clamp 到最短表档位。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"age_modifiers": {
        "start_age": 40, "max_tier": 4,
        "app_penalties": [-5, -10, -15, -20, -25],
        "phys_penalties": [0, -5],
        "edu_bonuses": [5, 10, 15, 20, 25]}}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    rules.apply_age_modifiers(st, 85)   # 原始 tier 4 -> clamp 1(phys 长 2)
    assert st.APP == 40   # 50 + app[1](-10)  统一用 tier 1
    assert st.STR == 45   # 50 + phys[1](-5)
    assert st.EDU == 60   # 50 + edu[1](10)


def test_skill_config_attributes_match_stats_fields():
    """skill_config.attributes 键集与 Stats 字段集一致(roll_stats 的 Stats(**vals) 依赖)。"""
    from utils import load_skill_config
    from investigator.models import Stats
    import dataclasses
    assert set(load_skill_config()["attributes"]) == {f.name for f in dataclasses.fields(Stats)}
