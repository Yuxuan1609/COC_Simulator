import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from library.bosses import BossLibrary, LibraryBoss

SAMPLE_BOSS = {
    "name": "测试Boss",
    "type": "神话生物",
    "attributes": {"STR": 100, "CON": 80, "SIZ": 90, "DEX": 40, "POW": 60},
    "armor": "5点",
    "attacks": [{"name": "冲击", "damage": "2D6"}],
    "special_abilities": [{"name": "测试能力", "desc": "测试描述"}],
    "san_loss": "1/1D6",
    "description": "测试用Boss",
    "boss_mechanics": "弱点：测试弱点。击败触发END_TEST。",
    "flags": ["boss"],
}


def test_load_boss_library():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text(json.dumps({"测试Boss": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        lib = BossLibrary(str(core))
        boss = lib.get("测试Boss")
        assert boss is not None
        assert boss.name == "测试Boss"
        assert boss.type == "神话生物"
        assert boss.attributes["STR"] == 100
        assert len(boss.attacks) == 1
        assert boss.attacks[0]["name"] == "冲击"
        assert boss.boss_mechanics == "弱点：测试弱点。击败触发END_TEST。"
        assert "boss" in boss.flags


def test_get_nonexistent():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text("{}", encoding="utf-8")
        lib = BossLibrary(str(core))
        assert lib.get("不存在") is None


def test_list_all():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text(json.dumps({"B1": SAMPLE_BOSS, "B2": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        lib = BossLibrary(str(core))
        names = lib.list_names()
        assert set(names) == {"B1", "B2"}
