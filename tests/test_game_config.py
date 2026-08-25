"""game_config 参数中心:缺省兜底 + 文件覆盖 + 缓存 reset。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from investigator import rules


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
