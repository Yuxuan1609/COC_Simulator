"""library 包基础测试."""
import sys
import os
import json

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from library.weapons import LibraryWeapon, WeaponLibrary
from library.enemies import LibraryEnemy, EnemyLibrary


def test_weapon_from_dict():
    data = {
        "name": ".45自动手枪",
        "skill_name": "手枪",
        "damage": "1D10+2",
        "range": "15码",
        "shots": 7,
        "malfunction": 100,
        "era": "1920s",
        "rarity": "common",
        "special_rules": "可连射，每追加一发-5惩罚",
    }
    w = LibraryWeapon.from_dict(data)
    assert w.name == ".45自动手枪"
    assert w.shots == 7
    assert w.damage == "1D10+2"
    d = w.to_dict()
    assert d["name"] == ".45自动手枪"


def test_weapon_library_load_core():
    lib = WeaponLibrary()
    lib.load_core()
    assert len(lib) >= 5
    pistol = lib.get(".45自动手枪")
    assert pistol is not None
    assert pistol.skill_name == "手枪"


def test_weapon_search():
    lib = WeaponLibrary()
    lib.load_core()
    era_results = lib.search(era="1920s")
    assert len(era_results) > 0
    keyword_results = lib.search(keyword="手枪")
    assert all("手枪" in w.name for w in keyword_results)


def test_enemy_from_dict():
    data = {
        "name": "Clicker",
        "type": "神话生物",
        "attributes": {"STR": 80, "CON": 70, "SIZ": 65, "DEX": 50, "POW": 60},
        "armor": "2点厚皮",
        "attacks": [{"name": "噬咬", "damage": "1D8+DB"}],
        "special_abilities": [{"name": "盲感", "desc": "通过声音定位"}],
        "san_loss": "0/1D4",
        "combat_behavior": "优先攻击发出最大声音的目标",
    }
    e = LibraryEnemy.from_dict(data)
    assert e.name == "Clicker"
    assert len(e.attacks) == 1
    assert e.attacks[0].damage == "1D8+DB"


def test_enemy_library_load_core():
    lib = EnemyLibrary()
    lib.load_core()
    assert len(lib) >= 3
    clicker = lib.get("Clicker")
    assert clicker is not None
    assert clicker.type == "神话生物"


def test_enemy_search():
    lib = EnemyLibrary()
    lib.load_core()
    mythos = lib.search(enemy_type="神话生物")
    assert all(e.type == "神话生物" for e in mythos)


def test_enemy_flag_parsing():
    """LibraryEnemy.from_dict extracts [flags] from combat_behavior."""
    # Has flags
    raw = {"name": "Test", "type": "test", "attributes": {},
           "combat_behavior": "[adjacent_aware][avoidable] | 会主动攻击",
           "armor": "无", "attacks": [], "special_abilities": [],
           "san_loss": "0/0", "description": ""}
    enemy = LibraryEnemy.from_dict(raw)
    assert enemy.flags == ["adjacent_aware", "avoidable"]
    assert enemy.combat_behavior == "会主动攻击"

    # No flags
    raw2 = {"name": "Test2", "type": "test", "attributes": {},
            "combat_behavior": "看到人就打",
            "armor": "无", "attacks": [], "special_abilities": [],
            "san_loss": "0/0", "description": ""}
    enemy2 = LibraryEnemy.from_dict(raw2)
    assert enemy2.flags == []
    assert enemy2.combat_behavior == "看到人就打"

    # Only flags, no natural lang
    raw3 = {"name": "Test3", "type": "test", "attributes": {},
            "combat_behavior": "[adjacent_aware]",
            "armor": "无", "attacks": [], "special_abilities": [],
            "san_loss": "0/0", "description": ""}
    enemy3 = LibraryEnemy.from_dict(raw3)
    assert enemy3.flags == ["adjacent_aware"]
    assert enemy3.combat_behavior == ""


from library.judgment import JudgmentEngine, Tier1Result


def test_tier1_skill_check():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(50, "regular")
    assert result.target == 50
    assert 1 <= result.roll <= 100


def test_tier1_hard_difficulty():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(60, "hard")
    assert result.target == 30


def test_tier1_extreme_difficulty():
    engine = JudgmentEngine()
    result = engine.tier1_skill_check(50, "extreme")
    assert result.target == 10


def test_tier1_damage_roll():
    engine = JudgmentEngine()
    total, detail = engine.tier1_damage_roll("1D6+DB", db=4)
    assert 5 <= total <= 10
    assert "=" in detail


def test_tier1_san_check():
    engine = JudgmentEngine()
    s, f, formula = engine.tier1_san_check("1/1D6")
    assert s == 1
    assert 1 <= f <= 6


from library.injector import ContentInjector


def test_injector_init():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    assert injector.offline_enabled is True
    assert injector.runtime_enabled is True


def test_injector_offline_inject_scene_no_danger():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    scene = {"description": "test scene"}
    result = injector.offline_inject_scene(scene, {"danger_level": "safe"})
    assert result == scene  # unchanged


def test_injector_offline_inject_scene_high_danger():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    scene = {"description": "danger zone"}
    result = injector.offline_inject_scene(scene, {"danger_level": "extreme"})
    assert "encounters" in result
    assert "scene_weapons" in result


def test_injector_runtime_spawn_enemy_not_loaded():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    result = injector.runtime_spawn_enemy("Clicker", "2号车厢")
    assert result is None  # library not loaded


def test_injector_runtime_spawn_enemy_loaded():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    elib.load_core()
    injector = ContentInjector(wlib, elib)
    result = injector.runtime_spawn_enemy("Clicker", "2号车厢")
    assert result is not None
    assert result["enemy_ref"] == "Clicker"
    assert result["quantity"] == 1


def test_injector_status():
    wlib = WeaponLibrary()
    elib = EnemyLibrary()
    injector = ContentInjector(wlib, elib)
    s = injector.status
    assert "offline_enabled" in s
    assert "weapons_loaded" in s
