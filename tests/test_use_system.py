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


class TestExecuteMaterial:
    def _world(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))
        from helpers import make_world, make_scene
        from library.spells import SpellLibrary
        from library.items import ItemLibrary
        from investigator import Investigator
        slib = SpellLibrary(); slib.load_core()
        ilib = ItemLibrary(); ilib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a",
                           item_library=ilib, spell_library=slib)
        from investigator.models import Stats
        inv = Investigator(name="测试", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        from investigator.rules import calc_derived
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 20
        world.set_player(inv)
        return world, inv

    def test_l0_spell_no_cost_no_check(self):
        from game.judge import Judge
        from game.use_parser import UseParser, SpellCatalog
        world, inv = self._world()
        inv.known_spells = ["LIFE_DETECTION"]
        judge = Judge(world)
        up = UseParser()
        m = up.resolve("念诵生命觉察", [SpellCatalog(world.spell_library, inv.known_spells)])
        out = judge.execute_material(m, "念诵生命觉察")
        assert out.success and out.entity_type == "material"
        assert inv.derived.MP == 17, "L0 感知法术也要扣 MP cost"
        assert "轮廓" in out.message

    def test_l1_item_consume_heals(self):
        from game.judge import Judge
        from game.use_parser import UseParser, ItemCatalog
        world, inv = self._world()
        inv.item_manager.add("急救包", quantity=2)
        inv.derived.HP = 5
        judge = Judge(world)
        m = UseParser().resolve("使用急救包", [ItemCatalog(world.item_library, inv.item_manager)])
        out = judge.execute_material(m, "使用急救包")
        assert out.success
        assert inv.item_manager.get("急救包").quantity == 1
        assert inv.derived.HP > 5, "@stat_change HP 恢复生效"

    def test_mp_insufficient_rejected(self):
        from game.judge import Judge
        from game.use_parser import UseParser, SpellCatalog
        world, inv = self._world()
        inv.known_spells = ["HEART_ARREST"]
        inv.derived.MP = 3
        judge = Judge(world)
        m = UseParser().resolve("施放心脏骤停", [SpellCatalog(world.spell_library, inv.known_spells)])
        out = judge.execute_material(m, "施放心脏骤停")
        assert not out.success and "MP不足" in out.message
        assert inv.derived.MP == 3 and inv.derived.SAN == inv.derived.SAN

    def test_unknown_spell_rejected(self):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = self._world()
        judge = Judge(world)
        m = UseParseResult(catalog_kind="spell", material_id="HEART_ARREST",
                           name="心脏骤停", matched_text="心脏骤停", impact="L1")
        out = judge.execute_material(m, "施法")
        assert not out.success and "尚未习得" in out.message

    def test_check_failure_uses_slot_and_refund(self):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = self._world()
        inv.item_manager.add("开锁工具", quantity=1)
        judge = Judge(world)
        m = UseParseResult(
            catalog_kind="item", material_id="LOCKPICKS", name="开锁工具",
            matched_text="开锁工具", impact="L1",
            check={"skill": "锁匠", "type": "regular"},
            cost={"mp": 0, "san": 0},
            result_slots={"on_success": "锁开了。", "on_failure": "锁纹丝不动。"},
            refund_on_fail=True, use_semantic="tool")
        inv.check_skill = lambda s, d="regular": (False, "锁匠检定：D100=98/10 失败", "failure")
        out = judge.execute_material(m, "开锁")
        assert not out.success and "纹丝不动" in out.message
        assert inv.item_manager.has("开锁工具"), "tool 语义失败不消耗，refund 兜底"


class TestCombatCast:
    def _combat(self):
        from game.combat import CombatSystem
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.rules import calc_derived
        slib = SpellLibrary(); slib.load_core()
        cs = CombatSystem(spell_lib=slib)
        from investigator.models import Stats
        inv = Investigator(name="法师", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 30
        inv.known_spells = ["HEART_ARREST", "LIFE_DETECTION"]
        return cs, slib, inv

    def test_actions_include_known_combat_spells_only(self):
        cs, slib, inv = self._combat()
        acts = cs._get_player_actions(inv)
        ids = [a["id"] for a in acts]
        assert "cast_HEART_ARREST" in ids
        assert "cast_LIFE_DETECTION" not in ids, "exploration 类不进战斗动作"

    def test_cast_without_known_spell_fails(self):
        import random
        random.seed(3)
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        inv.known_spells = []
        state = SimpleNamespace(enemies=[], _player_dodging=False)
        act = cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "")
        assert not act.success and "尚未习得" in act.narrative

    def test_cast_deducts_mp(self):
        import random
        random.seed(5)
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        enemy = SimpleNamespace(instance_id="E1", enemy_ref="深潜者", hp=10,
                                status="hostile", attributes={"POW": 30}, armor="")
        state = SimpleNamespace(enemies=[enemy], _player_dodging=False)
        before = inv.derived.MP
        cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "E1")
        assert inv.derived.MP == before - 12, "施法必须扣 MP（12）"

    def test_mp_insufficient_fails_without_deduction(self):
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        inv.derived.MP = 3
        state = SimpleNamespace(enemies=[], _player_dodging=False)
        act = cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "")
        assert not act.success and "MP不足" in act.narrative
        assert inv.derived.MP == 3


class TestPipelineAwareness:
    def test_cross_validate_flags_unknown_spell_ref(self):
        from module_designer.layered_pipeline import cross_validate_layers
        from library.spells import SpellLibrary
        slib = SpellLibrary(); slib.load_core()
        l1 = {"scenes": {}}
        l2 = {"scenes": {"s1": {"interactions": [{
            "id": "I1", "entity_type": "interaction", "name": "读书",
            "type": "None", "requirement": "", "trigger": "读书",
            "result": "你学会了咒文。", "scene": "s1",
            "side_effects": ['@grant_spell(spell_ref="不存在的法术")'],
            "difficulty": "None"}], "auto_triggers": []}}, "events": []}
        l3 = {"module_meta": {}}
        report = cross_validate_layers(l1, l2, l3, None, None,
                                       spell_lib=slib)
        joined = " ".join(str(i) for i in report.issues)
        assert "不存在的法术" in joined, "未知 spell_ref 必须进交叉校验报告"

    def test_step1a_prompt_contains_libraries(self):
        from module_designer.layered_parser import build_step1a_prompt
        p = build_step1a_prompt("模组内容", ["小刀"], ["深潜者"], [],
                                item_names=["急救包（consumable）：止血"],
                                spell_names=["HEART_ARREST 心脏骤停（combat）：攥心"])
        assert "急救包" in p and "HEART_ARREST" in p


class TestEffectNormalize:
    """effect 字段升维:旧 dict 自动包装为 [dict],list 透传(2026-08-21 spec §1.1)。"""

    def test_spell_effect_dict_wraps_to_list(self):
        from library.spells import LibrarySpell
        sp = LibrarySpell.from_dict({"id": "X", "name": "X",
                                     "effect": {"type": "damage", "formula": "1D6"}})
        assert sp.effect == [{"type": "damage", "formula": "1D6"}]

    def test_spell_effect_list_passthrough(self):
        from library.spells import LibrarySpell
        eff = [{"type": "buff", "reduce": 3, "rounds": 3},
               {"type": "timed", "id": "S", "description": "d", "minutes": 10}]
        sp = LibrarySpell.from_dict({"id": "X", "name": "X", "effect": eff})
        assert sp.effect == eff
        assert sp.effect[0] is not eff[0], "元素级浅拷贝,不得别名外部 dict"

    def test_spell_effect_non_dict_filtered(self):
        from library.spells import LibrarySpell
        sp = LibrarySpell.from_dict({"id": "X", "name": "X",
                                     "effect": [{"type": "buff"}, "junk", 42,
                                                {"type": "timed"}]})
        assert [e["type"] for e in sp.effect] == ["buff", "timed"], "非 dict 元素必须被过滤"

    def test_spell_effect_defensive_copy(self):
        from library.spells import LibrarySpell
        eff = [{"type": "buff", "reduce": 3}]
        sp = LibrarySpell.from_dict({"id": "X", "name": "X", "effect": eff})
        sp.effect[0]["x"] = 1
        assert "x" not in eff[0], "改 sp.effect 不得污染原始输入 dict"

    def test_spell_effect_empty(self):
        from library.spells import LibrarySpell
        sp = LibrarySpell.from_dict({"id": "X", "name": "X"})
        assert sp.effect == []

    def test_item_effect_field(self):
        from library.items import LibraryItem
        it = LibraryItem.from_dict({"id": "SALT", "name": "盐袋",
                                    "effect": [{"type": "timed",
                                                "id": "SALT_LINE",
                                                "description": "白色盐线",
                                                "minutes": 60}]})
        assert it.effect[0]["type"] == "timed"
        it2 = LibraryItem.from_dict({"id": "Y", "name": "Y"})
        assert it2.effect == []

    def test_item_effect_dict_wraps(self):
        from library.items import LibraryItem
        it = LibraryItem.from_dict({"id": "Z", "name": "Z",
                                    "effect": {"type": "timed", "id": "T",
                                               "description": "d", "minutes": 5}})
        assert it.effect == [{"type": "timed", "id": "T",
                              "description": "d", "minutes": 5}]


class TestCatalogEffectPassthrough:
    """Catalog/UseParseResult 透传 effect 原子数组(2026-08-21 plan Task 4)。"""

    def test_spell_catalog_entries_carry_effect(self):
        from library.spells import SpellLibrary, LibrarySpell
        from game.use_parser import SpellCatalog
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒", "category": "exploration",
            "effect": [{"type": "timed", "id": "X_EFF",
                        "description": "耳畔嗡鸣", "minutes": 5}]})
        cat = SpellCatalog(lib, ["X"])
        entries = cat.entries()
        assert entries[0]["effect"] == [{"type": "timed", "id": "X_EFF",
                                         "description": "耳畔嗡鸣", "minutes": 5}]

    def test_item_catalog_entries_carry_effect(self):
        from library.items import ItemLibrary, LibraryItem
        from game.use_parser import ItemCatalog
        lib = ItemLibrary()
        lib._items["SALT"] = LibraryItem.from_dict({
            "id": "SALT", "name": "盐袋",
            "effect": [{"type": "timed", "id": "SALT_LINE",
                        "description": "白色盐线", "minutes": 60}]})
        # ItemCatalog 需要库存;用假 inventory: list_all() 返回带 .name 的对象
        from types import SimpleNamespace
        fake_inv = SimpleNamespace(list_all=lambda: [SimpleNamespace(name="盐袋", quantity=1)])
        cat = ItemCatalog(lib, fake_inv)
        entries = cat.entries()
        assert entries[0]["effect"][0]["id"] == "SALT_LINE"

    def test_resolve_result_carries_effect(self):
        from library.spells import SpellLibrary, LibrarySpell
        from game.use_parser import UseParser, SpellCatalog
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒",
            "effect": [{"type": "heal", "target": "self", "formula": "1D3"}]})
        r = UseParser().resolve("施放试咒", [SpellCatalog(lib, ["X"])])
        assert r is not None
        assert r.effect[0]["type"] == "heal"
        assert r.effect[0] is not lib._spells["X"].effect[0], "元素级拷贝,不得别名库单例"

    def test_resolve_llm_result_carries_effect(self):
        from library.spells import SpellLibrary, LibrarySpell
        from game.use_parser import UseParser, SpellCatalog
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒",
            "effect": [{"type": "heal", "target": "self", "formula": "1D3"}]})
        cats = [SpellCatalog(lib, ["X"])]
        up = UseParser(llm_call=lambda p, **k: {"matched": True, "material": "试咒",
                                                "reason": "语义相同"})
        r = up.resolve_llm("指尖轻点念念有词", cats)
        assert r is not None
        assert r.effect[0]["type"] == "heal", "LLM 回灌 resolve 路径 effect 不得丢失"
        assert r.effect[0] is not lib._spells["X"].effect[0], "回灌路径同样元素级拷贝"
