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


class TestLibraries:
    def test_item_library_core_load(self):
        from library.items import ItemLibrary
        lib = ItemLibrary(); lib.load_core()
        assert len(lib) >= 10
        kit = lib.get("急救包")
        assert kit is not None and kit.impact == "L1"
        assert lib.get("FIRST_AID_KIT") is kit, "id 与名称/别名均可查"
        assert "医疗包" in kit.aliases

    def test_spell_library_core_load(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        assert len(lib) >= 6
        sp = lib.get("心脏骤停")
        assert sp.category == "combat"
        assert sp.cost.get("mp", 0) > 0
        life = lib.get("LIFE_DETECTION")
        assert life is not None and life.impact == "L0"

    def test_extension_merge(self, tmp_path):
        from library.items import ItemLibrary
        import json as _json
        p = tmp_path / "ext.json"
        p.write_text(_json.dumps({"items": [
            {"id": "EXT_X", "name": "扩展物品", "impact": "L1"}]}, ensure_ascii=False),
            encoding="utf-8")
        lib = ItemLibrary(); lib.load_core(); lib.load_extension(str(p))
        assert lib.get("扩展物品") is not None


class TestGrantSpell:
    def _world(self):
        from scenario_core import DirectedGraph, ScenarioWorld
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        world = ScenarioWorld(DirectedGraph(scenes={}, events=[]),
                              start_node="room", spell_library=lib)
        return world

    def test_grant_spell_known_ref(self):
        from scenario_core import apply_side_effects
        from game.side_effects import GrantSpell
        from investigator import Investigator
        world = self._world()
        inv = Investigator(name="测试")
        world.set_player(inv)
        msgs = apply_side_effects(world, [GrantSpell(spell_ref="HEART_ARREST")])
        assert "HEART_ARREST" in inv.known_spells
        assert any("获得法术" in m for m in msgs)
        apply_side_effects(world, [GrantSpell(spell_ref="HEART_ARREST")])
        assert inv.known_spells.count("HEART_ARREST") == 1, "不重复授予"

    def test_grant_spell_unknown_ref_degrades(self):
        from scenario_core import apply_side_effects
        from game.side_effects import GrantSpell
        from investigator import Investigator
        world = self._world()
        world.set_player(Investigator(name="测试"))
        msgs = apply_side_effects(world, [GrantSpell(spell_ref="不存在的法术")])
        assert any("不存在" in m for m in msgs)

    def test_parse_markup_grant_spell(self):
        from game.side_effects import parse_markup
        eff = parse_markup('@grant_spell(spell_ref="HEART_ARREST")')
        assert eff is not None and eff.spell_ref == "HEART_ARREST"


class TestUseParserDeterministic:
    def _setup(self):
        from library.items import ItemLibrary
        from library.spells import SpellLibrary
        from game.use_parser import UseParser, ItemCatalog, SpellCatalog
        from investigator import Investigator
        ilib = ItemLibrary(); ilib.load_core()
        slib = SpellLibrary(); slib.load_core()
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=2)
        inv.known_spells = ["LIFE_DETECTION", "HEART_ARREST"]
        up = UseParser()
        cats = [ItemCatalog(ilib, inv.item_manager),
                SpellCatalog(slib, inv.known_spells)]
        return up, cats, inv

    def test_verb_name_exact_hit(self):
        up, cats, inv = self._setup()
        r = up.resolve("我使用急救包处理伤口", cats)
        assert r is not None and r.catalog_kind == "item"
        assert r.material_id == "FIRST_AID_KIT" and r.impact == "L1"

    def test_spell_cast_hit(self):
        up, cats, inv = self._setup()
        r = up.resolve("我闭上眼念诵生命觉察的咒文", cats)
        assert r is not None and r.catalog_kind == "spell"
        assert r.material_id == "LIFE_DETECTION" and r.impact == "L0"

    def test_alias_and_fuzzy(self):
        up, cats, inv = self._setup()
        inv.item_manager.add("威士忌", quantity=1)   # 别名"烈酒"命中 WHISKEY
        r = up.resolve("喝一口烈酒壮胆", cats)
        assert r is not None and r.material_id == "WHISKEY"

    def test_negation_rejected(self):
        up, cats, inv = self._setup()
        assert up.resolve("我不用急救包", cats) is None

    def test_unheld_item_not_in_catalog(self):
        up, cats, inv = self._setup()
        r = up.resolve("我使用撬棍撬开门", cats)
        assert r is None, "未持有的库物品不入目录，走 interaction 语义路径"

    def test_no_verb_no_hit(self):
        up, cats, inv = self._setup()
        assert up.resolve("急救包挺好的", cats) is None


class TestUseParserLLM:
    def test_resolve_llm_match(self):
        from library.items import ItemLibrary
        from game.use_parser import UseParser, ItemCatalog
        ilib = ItemLibrary(); ilib.load_core()
        from investigator import Investigator
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=1)
        import json as _json
        calls = {}
        def fake_llm(prompt, **kw):
            calls["prompt"] = prompt
            return _json.dumps({"matched": True, "material": "急救包",
                                "reason": "语义相同"}, ensure_ascii=False)
        up = UseParser(llm_call=fake_llm)
        cats = [ItemCatalog(ilib, inv.item_manager)]
        # 原文无动词/名匹配失败场景由 LLM 兜底
        r = up.resolve_llm("把那个能止血的包拿来用", cats)
        assert r is not None and r.material_id == "FIRST_AID_KIT"
        assert "急救包" in calls["prompt"]

    def test_resolve_llm_unmatched(self):
        from library.items import ItemLibrary
        from game.use_parser import UseParser, ItemCatalog
        from investigator import Investigator
        ilib = ItemLibrary(); ilib.load_core()
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=1)
        up = UseParser(llm_call=lambda p, **k: {"matched": False, "material": "", "reason": ""})
        assert up.resolve_llm("随便看看", [ItemCatalog(ilib, inv.item_manager)]) is None


class TestOpposedCheck:
    def test_outcomes_and_message(self):
        import random
        from investigator.rules import opposed_check
        random.seed(7)
        seen = set()
        for _ in range(300):
            outcome, detail = opposed_check(80, 30)
            assert outcome in ("win", "lose", "tie")
            assert "对抗 D100" in detail
            seen.add(outcome)
        assert "win" in seen, "80 vs 30 必然出现 win"

    def test_equal_values_outcome_follows_tiers(self):
        import random, re
        from investigator.rules import opposed_check
        random.seed(11)
        rank = {"fumble": 0, "failure": 0, "regular": 1, "hard": 2, "extreme": 3}
        for _ in range(50):
            outcome, detail = opposed_check(50, 50)
            m = re.search(r"攻方 \d+/50\((\w+)\) vs 守方 \d+/50\((\w+)\)", detail)
            a, d = rank[m.group(1)], rank[m.group(2)]
            if a == d:
                assert outcome == "tie", f"同值同级应平局：{detail}"
            else:
                assert outcome == ("win" if a > d else "lose"), f"等级高者应胜：{detail}"
