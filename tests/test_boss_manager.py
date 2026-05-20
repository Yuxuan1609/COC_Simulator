import sys
import os
import json
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game.boss_manager import BossManager
from game.messages import CombatInit
from library.bosses import BossLibrary

SAMPLE_BOSS = {
    "name": "测试Boss",
    "type": "神话生物",
    "attributes": {"STR": 100, "CON": 80, "SIZ": 90, "DEX": 40, "POW": 60},
    "armor": "5点",
    "attacks": [{"name": "冲击", "damage": "2D6"}],
    "special_abilities": [],
    "san_loss": "1/1D6",
    "description": "测试用Boss",
    "boss_mechanics": "弱点：测试弱点。",
    "flags": ["boss"],
}


def _make_library():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bosses.json"
        p.write_text(json.dumps({"测试Boss": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        return BossLibrary(str(p))


def test_check_by_engage_type_at():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_1", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "测试Boss", "scene": "6号车厢",
         "requirements": "I1 || 软性条件", "description": "测试"}
    ]
    mgr = BossManager(lib, encounters)

    result = mgr.check_by_engage_type("at", scene="6号车厢")
    assert len(result) == 1
    assert result[0]["id"] == "BOSS_1"

    result2 = mgr.check_by_engage_type("at", scene="2号车厢")
    assert len(result2) == 0

    result3 = mgr.check_by_engage_type("interaction")
    assert len(result3) == 0


def test_check_by_engage_type_event():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_E1", "type": "boss_encounter", "engage_type": "event",
         "boss_ref": "测试Boss", "scene": "",
         "requirements": "runtime_state.I_done.completed", "description": "全局事件"}
    ]
    mgr = BossManager(lib, encounters)
    result = mgr.check_by_engage_type("event")
    assert len(result) == 1


def test_build_combat_init():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_1", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "测试Boss", "scene": "6号车厢",
         "requirements": "", "description": "Boss登场！"}
    ]
    mgr = BossManager(lib, encounters)

    class MockPlayer:
        class Stats:
            DEX = 50; STR = 50; CON = 50; SIZ = 50; POW = 50; APP = 50; INT = 50; EDU = 50
        class Derived:
            HP = 12; SAN = 60
        stats = Stats(); derived = Derived()
        def get_skill(self, name): return type('s', (), {'value': 50})()

    ci = mgr.build_combat_init(encounters[0], MockPlayer(), "6号车厢")
    assert isinstance(ci, CombatInit)
    assert ci.scene == "6号车厢"
    assert len(ci.enemies) == 1
    enemy = ci.enemies[0]
    assert enemy.enemy_ref == "测试Boss"
    assert enemy.attributes["STR"] == 100
    assert enemy.armor == "5点"
    assert enemy.hp == (80 + 90) // 10
    assert "boss" in enemy.flags
    assert enemy.boss_mechanics == "弱点：测试弱点。"


def test_get_nonexistent_boss():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_X", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "不存在", "scene": "6号车厢",
         "requirements": "", "description": ""}
    ]
    mgr = BossManager(lib, encounters)
    try:
        mgr.build_combat_init(encounters[0], None, "6号车厢")
        assert False, "Should have raised"
    except KeyError:
        pass


def test_set_active():
    lib = _make_library()
    mgr = BossManager(lib, [])
    assert mgr._active_boss_id is None
    mgr.set_active("BOSS_1")
    assert mgr._active_boss_id == "BOSS_1"
    mgr.set_active(None)
    assert mgr._active_boss_id is None


def test_resolve_outcome():
    lib = _make_library()
    mgr = BossManager(lib, [])
    assert mgr.resolve_outcome(type('R', (), {'outcome': 'win'})()) is None
    mgr.set_active("BOSS_1")
    class R:
        outcome = "win"
    assert mgr.resolve_outcome(R()) == "win"
