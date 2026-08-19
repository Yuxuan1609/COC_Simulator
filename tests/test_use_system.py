"""统一资源层（U6 法术 + U8 物品）单元测试。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _inv():
    from investigator import Investigator
    from investigator.models import Stats
    from investigator.rules import calc_derived
    inv = Investigator(name="测试员", stats=Stats(
        STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
    inv.derived = calc_derived(inv.stats)
    return inv


class TestRecalcPreservesCurrent:
    def test_recalc_keeps_current_mp_hp_san(self):
        inv = _inv()
        inv.derived.MP = 2
        inv.derived.HP = 3
        inv.derived.SAN = 40
        inv._recalc_derived()
        assert inv.derived.MP_MAX == 12
        assert inv.derived.MP == 2, "recalc 不得重置当前 MP"
        assert inv.derived.HP == 3, "recalc 不得重置当前 HP"
        assert inv.derived.SAN == 40, "recalc 不得重置当前 SAN"

    def test_pow_growth_carries_mp(self):
        inv = _inv()          # POW60 -> MP_MAX 12
        inv.derived.MP = 2
        inv.modify_stat("POW", 10)   # POW70 -> MP_MAX 14，当前同步涨 2
        assert inv.derived.MP_MAX == 14
        assert inv.derived.MP == 4

    def test_pow_shrink_clamps_mp(self):
        inv = _inv()
        inv.modify_stat("POW", -10)  # POW50 -> MP_MAX 10，clamp
        assert inv.derived.MP_MAX == 10
        assert inv.derived.MP <= 10

    def test_con_growth_carries_hp(self):
        inv = _inv()          # HP_MAX 20
        inv.derived.HP = 5
        inv.modify_stat("CON", 30)   # CON90 -> HP_MAX 30，当前涨 10
        assert inv.derived.HP_MAX == 30
        assert inv.derived.HP == 15


class TestKnownSpells:
    def test_default_empty_and_roundtrip(self):
        inv = _inv()
        assert inv.known_spells == []
        inv.known_spells = ["HEART_ARREST", "LIFE_DETECTION"]
        from investigator.serialization import to_dict, from_dict
        d = to_dict(inv)
        assert d["meta"]["version"] == "2.1"
        assert d["known_spells"] == ["HEART_ARREST", "LIFE_DETECTION"]
        inv2 = from_dict(d)
        assert inv2.known_spells == ["HEART_ARREST", "LIFE_DETECTION"]

    def test_v20_card_loads_with_empty_spells(self):
        from investigator.serialization import from_dict
        d = {
            "meta": {"version": "2.0"},
            "personal": {"name": "旧卡", "age": 30, "gender": "女"},
            "stats": {"STR": 50, "CON": 50, "DEX": 50, "APP": 50,
                      "INT": 60, "POW": 55, "EDU": 65, "LUCK": 40},
            "derived": {"HP": 16, "HP_MAX": 16, "MP": 11, "SAN": 55, "SAN_MAX": 99,
                        "DB": "0", "BUILD": 0, "DODGE": 25},
            "skills": [], "combat": {"weapons": []},
        }
        inv = from_dict(d)
        assert inv.known_spells == []
        assert inv.derived.MP_MAX == 11, "v2.0 无 MP_MAX 时由 MP 回填"
