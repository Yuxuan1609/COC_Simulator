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
