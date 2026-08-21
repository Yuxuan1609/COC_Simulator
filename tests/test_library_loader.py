"""loader:core+extensions 统一加载,base_dir 注入,摘要可见性。"""
import json
import shutil
import sys, os
from pathlib import Path

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
