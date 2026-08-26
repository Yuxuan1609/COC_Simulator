"""统一资源层库加载器:core + extensions 目录扫描(2026-08-21 spec §6)。

三个调用点统一:game_loop.init_game / run_pipeline 两处。
base_dir 参数供测试注入(base_dir 下应有 core/ 与 extensions/)。
"""
from __future__ import annotations
import json
from pathlib import Path

from library.items import ItemLibrary
from library.spells import SpellLibrary


def load_json_object(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"库文件加载失败: {path}") from e
    if not isinstance(data, dict):
        raise ValueError(f"库文件格式错误(顶层应为 object): {path}")
    return data

_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "library"


def _load(core_cls, core_file: str, ext_subdir: str, base_dir: str | None):
    lib = core_cls()
    base = Path(base_dir) if base_dir else _DATA_ROOT
    lib.load_core(str(base / "core" / core_file))
    ext_dir = base / "extensions" / ext_subdir
    if ext_dir.is_dir():
        for f in sorted(ext_dir.glob("*.json")):
            lib.load_extension(str(f))
    return lib


def load_item_library(base_dir: str | None = None) -> ItemLibrary:
    return _load(ItemLibrary, "items.json", "items", base_dir)


def load_spell_library(base_dir: str | None = None) -> SpellLibrary:
    return _load(SpellLibrary, "spells.json", "spells", base_dir)
