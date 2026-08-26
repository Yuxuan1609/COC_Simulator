"""loader:core+extensions 统一加载,base_dir 注入,摘要可见性。"""
import json
import shutil
import sys, os
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from library.loader import load_item_library, load_spell_library

_CORE = Path(__file__).resolve().parent.parent / "data" / "library" / "core"


def _make_ext(base, kind, entries):
    d = base / "extensions" / kind
    d.mkdir(parents=True, exist_ok=True)
    (d / "ext.json").write_text(json.dumps({kind: entries}, ensure_ascii=False),
                                encoding="utf-8")
    (base / "core").mkdir(exist_ok=True)
    shutil.copy(_CORE / f"{kind}.json", base / "core" / f"{kind}.json")
    return d


def test_load_spell_library_core_plus_extension(tmp_path):
    _make_ext(tmp_path, "spells", [
        {"id": "EXT_DARK", "name": "暗影低语", "category": "exploration",
         "impact": "L1", "cost": {"mp": 3, "san": 0}}])
    lib = load_spell_library(base_dir=str(tmp_path))
    sp = lib.get("EXT_DARK")
    assert sp is not None and sp.name == "暗影低语"
    assert lib.get("HEART_ARREST") is not None      # core 也加载了


def test_load_item_library_core_plus_extension(tmp_path):
    _make_ext(tmp_path, "items", [
        {"id": "EXT_TALISMAN", "name": "旧护符", "category": "key",
         "impact": "L0", "use_semantic": "none"}])
    lib = load_item_library(base_dir=str(tmp_path))
    assert lib.get("EXT_TALISMAN") is not None
    assert lib.get("FIRST_AID_KIT") is not None


def test_extension_visible_in_step1a_summary(tmp_path):
    """管线摘要可见性:扩展法术名进 build_step1a_prompt 文本。"""
    _make_ext(tmp_path, "spells", [
        {"id": "EXT_DARK", "name": "暗影低语", "category": "exploration",
         "impact": "L1", "cost": {"mp": 3, "san": 0}}])
    lib = load_spell_library(base_dir=str(tmp_path))
    from module_designer.layered_parser import build_step1a_prompt
    prompt = build_step1a_prompt(
        "源文档", spell_names=[s.name for s in lib.list_all()])
    assert "暗影低语" in prompt


def test_corrupt_extension_json_error_names_file(tmp_path):
    """ISSUES B7:损坏扩展 JSON 报错带文件路径。"""
    base = tmp_path
    (base / "core").mkdir(parents=True)
    (base / "core" / "items.json").write_text('{"items": []}', encoding="utf-8")
    ext = base / "extensions" / "items"
    ext.mkdir(parents=True)
    (ext / "bad.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json"):
        load_item_library(str(base))


def test_non_dict_library_json_error_names_file(tmp_path):
    """ISSUES B7:库文件顶层非 object(如数组)报错带文件路径。"""
    base = tmp_path
    (base / "core").mkdir(parents=True)
    (base / "core" / "spells.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="spells.json"):
        load_spell_library(str(base))


def test_corrupt_weapons_json_error_names_file(tmp_path):
    from library.weapons import WeaponLibrary
    p = tmp_path / "weapons.json"
    p.write_text("{oops", encoding="utf-8")
    lib = WeaponLibrary()
    with pytest.raises(ValueError, match="weapons.json"):
        lib._load_file(str(p))


def test_non_dict_enemies_json_error_names_file(tmp_path):
    from library.enemies import EnemyLibrary
    p = tmp_path / "enemies.json"
    p.write_text("[1, 2]", encoding="utf-8")
    lib = EnemyLibrary()
    with pytest.raises(ValueError, match="应为 object"):
        lib._load_file(str(p))


def test_corrupt_bosses_json_error_names_file(tmp_path):
    from library.bosses import BossLibrary
    p = tmp_path / "bosses.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="bosses.json"):
        BossLibrary(str(p))


def test_data_root_cwd_independent(tmp_path, monkeypatch):
    """ISSUES B12:loader 默认路径与 cwd 无关(_DATA_ROOT 为包相对绝对路径锁定)。"""
    monkeypatch.chdir(tmp_path)
    lib = load_item_library()      # 不传 base_dir,走 _DATA_ROOT
    assert len(lib) > 0
    assert len(load_spell_library()) > 0
