"""game_config 参数中心:缺省兜底 + 文件覆盖 + 缓存 reset。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from investigator import rules


def setup_function():
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
