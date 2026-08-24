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


class TestTimedEffectsSerialization:
    """timed_effects 序列化 v2.2:往返一致 + 旧档缺省(2026-08-21 plan Task 5)。"""

    def test_timed_effects_roundtrip(self):
        from investigator import serialization
        inv = _inv()
        inv.timed_effects = [{"id": "SILENCE_VEIL",
                              "description": "帷幕吞掉一切声响",
                              "expire_at": 1234}]
        data = serialization.to_dict(inv)
        assert data["meta"]["version"] == "2.2"
        inv2 = serialization.from_dict(data)
        assert inv2.timed_effects == [{"id": "SILENCE_VEIL",
                                       "description": "帷幕吞掉一切声响",
                                       "expire_at": 1234}]
        assert inv2.timed_effects[0] is not inv.timed_effects[0], "roundtrip 必须元素级拷贝,不得别名"

    def test_v21_loads_with_empty_timed_effects(self):
        from investigator import serialization
        inv = _inv()
        data = serialization.to_dict(inv)
        data["meta"]["version"] = "2.1"
        del data["timed_effects"]
        inv2 = serialization.from_dict(data)
        assert inv2.timed_effects == []

    def test_default_empty_on_new_investigator(self):
        inv = _inv()
        assert inv.timed_effects == []

    def test_bad_elements_without_expire_at_filtered(self):
        from investigator import serialization
        inv = _inv()
        data = serialization.to_dict(inv)
        data["timed_effects"] = [{"id": "OK", "description": "d", "expire_at": 5},
                                 {"id": "NO_EXPIRE"},
                                 {"id": "STR_EXPIRE", "expire_at": "晚八点"},
                                 {"id": "NULL_EXPIRE", "expire_at": None},
                                 "junk"]
        inv2 = serialization.from_dict(data)
        assert inv2.timed_effects == [{"id": "OK", "description": "d", "expire_at": 5}]


class TestExecuteMaterialEffects:
    """探索侧 effect 原子结算(2026-08-21 spec §1.2 探索列)。"""

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
        inv.known_spells = ["X"]
        world.set_player(inv)
        return world, inv

    def _mat(self, **kw):
        from game.use_parser import UseParseResult
        kw.setdefault("impact", "L1")
        return UseParseResult(catalog_kind="spell", material_id="X", name="试咒",
                              matched_text="试咒", **kw)

    def test_heal_clamped(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.HP = inv.derived.HP_MAX - 1   # CON60 -> HP_MAX 20
        judge = Judge(world)
        m = self._mat(effect=[{"type": "heal", "target": "self",
                               "formula": "1D3"}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.HP == inv.derived.HP_MAX, "heal 必须 clamp 到 HP_MAX"

    def test_heal_garbage_formula_falls_back_to_delta(self):
        from game.judge import Judge
        world, inv = self._world()
        before = inv.derived.HP_MAX - 6
        inv.derived.HP = before
        judge = Judge(world)
        m = self._mat(effect=[{"type": "heal", "formula": "garbage",
                               "delta": 5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.HP == before + 5, \
            "垃圾 formula 回退 delta(恢复 5;与战斗侧统一)"

    def test_mp_change_clamped(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.MP = 1
        inv.derived.MP_MAX = 4
        judge = Judge(world)
        m = self._mat(effect=[{"type": "mp_change", "delta": 5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.MP == 4, "mp_change 必须 clamp 到 MP_MAX"

    def test_markup_atom_applies_side_effect(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.SAN = 50
        judge = Judge(world)
        m = self._mat(effect=[{"type": "markup",
                               "text": '@stat_change(stat_name="SAN", delta=-1)'}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.SAN == 49, "markup 原子走 apply_side_effects 通路"
        assert "[属性变化]" in out.message

    def test_timed_atom_mounts_on_player(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        base = world.clock.game_time
        m = self._mat(effect=[{"type": "timed", "id": "VEIL",
                               "description": "帷幕", "minutes": 10}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert len(inv.timed_effects) == 1
        te = inv.timed_effects[0]
        assert te["id"] == "VEIL" and te["description"] == "帷幕"
        assert te["expire_at"] == base + 10

    def test_timed_default_minutes_from_config(self, monkeypatch):
        import investigator.rules as rules_mod
        monkeypatch.setattr(rules_mod, "get_game_config",
                            lambda: {"timed_default_minutes": 45})
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        base = world.clock.game_time
        m = self._mat(effect=[{"type": "timed", "id": "T", "description": "低语"}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.timed_effects[0]["expire_at"] == base + 45, \
            "minutes 缺省读 game_config 的 timed_default_minutes"

    def test_damage_atom_skipped_with_warning(self, caplog):
        import logging
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(effect=[{"type": "damage", "formula": "1D6"},
                              {"type": "narrative", "text": "余音回荡。"}])
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            out = judge.execute_material(m, "试咒")
        assert out.success, "探索侧 damage 跳过,不得阻断"
        assert "余音回荡" in out.message
        assert any(r.levelno == logging.WARNING and "damage" in r.message
                   for r in caplog.records), "damage 跳过必须留 warning 日志"

    def test_unknown_type_degrades_to_narrative(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(effect=[{"type": "summon", "description": "阴影中传来窸窣声"}])
        out = judge.execute_material(m, "试咒")
        assert out.success, "未知 type 降级,永不报错阻断"
        assert "[unknown:summon]" in out.message
        assert "窸窣声" in out.message

    def test_buff_control_degrade_to_text(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(effect=[{"type": "buff", "reduce": 3, "rounds": 3,
                               "description": "石肤"},
                              {"type": "control", "rounds": 2,
                               "description": "支配"}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert "石肤" in out.message and "支配" in out.message, \
            "buff/control 探索侧降级为 description 文本进结果"

    def test_effect_atoms_execute_after_on_use(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.SAN = 50
        inv.derived.MP = 5
        judge = Judge(world)
        m = self._mat(
            on_use=['@stat_change(stat_name="SAN", delta=-1)'],
            effect=[{"type": "mp_change", "delta": 1}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.SAN == 49, "on_use 副作用先生效"
        assert inv.derived.MP == 6, "effect 原子后生效"
        assert out.message.index("[属性变化]") < out.message.index("MP"), \
            "on_use 行在 effect 行之前拼入 message"

    def test_l0_with_effect_not_shortcircuited(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(impact="L0",
                      result_slots={"on_success": "咒纹在空中一闪而逝。"},
                      effect=[{"type": "timed", "id": "T",
                               "description": "低语", "minutes": 5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert "咒纹在空中一闪而逝。" in out.message
        assert len(inv.timed_effects) == 1, \
            "L0+effect 不得因纯叙事短路而丢弃 effect(on_use/effect 对称)"
        assert inv.timed_effects[0]["id"] == "T"

    def test_effect_not_executed_on_check_failure(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.MP = 10
        inv.derived.HP = 10
        inv.check_skill = lambda s, d="regular": (False, "检定：D100=98 失败", "failure")
        judge = Judge(world)
        m = self._mat(check={"skill": "锁匠", "type": "regular"},
                      cost={"mp": 5, "san": 0}, refund_on_fail=True,
                      effect=[{"type": "heal", "delta": 3}])
        out = judge.execute_material(m, "试咒")
        assert not out.success and "没有产生效果" in out.message
        assert inv.derived.HP == 10, "检定失败路径 effect 不得生效(退款后免费获益)"
        assert inv.derived.MP == 10, "refund_on_fail 退回 MP"

    def test_timed_same_id_refresh(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        base = world.clock.game_time
        m1 = self._mat(effect=[{"type": "timed", "id": "VEIL",
                                "description": "帷幕", "minutes": 10}])
        judge.execute_material(m1, "试咒")
        m2 = self._mat(effect=[{"type": "timed", "id": "VEIL",
                                "description": "帷幕", "minutes": 30}])
        out = judge.execute_material(m2, "试咒")
        assert out.success
        assert len(inv.timed_effects) == 1, "同 id 重复施放 refresh,不叠条"
        assert inv.timed_effects[0]["expire_at"] == base + 30, \
            "时效以最后一次施放为准"

    def test_mp_change_lower_clamp(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.MP = 1
        judge = Judge(world)
        m = self._mat(effect=[{"type": "mp_change", "delta": -5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.MP == 0, "mp_change 下限 clamp 到 0"

    def test_heal_delta_path(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.HP = 10
        judge = Judge(world)
        m = self._mat(effect=[{"type": "heal", "delta": 5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.HP == 15, "heal delta 路径直加"
        assert "恢复" in out.message

    def test_heal_negative_delta_noop(self):
        from game.judge import Judge
        world, inv = self._world()
        inv.derived.HP = 10
        judge = Judge(world)
        m = self._mat(effect=[{"type": "heal", "delta": -5}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert inv.derived.HP == 10, "heal 负 delta 归零,不得反向扣血"

    def test_empty_type_atom_no_prefix(self):
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(effect=[{"text": "x"}])
        out = judge.execute_material(m, "试咒")
        assert out.success
        assert "x" in out.message
        assert "[unknown" not in out.message, "空 type 无标识符前缀"

    def test_degrade_atoms_log_warning(self, caplog):
        import logging
        from game.judge import Judge
        world, inv = self._world()
        judge = Judge(world)
        m = self._mat(effect=[{"type": "buff", "reduce": 3, "rounds": 3,
                               "description": "石肤"},
                              {"type": "control", "rounds": 2,
                               "description": "支配"},
                              {"type": "summon", "description": "窸窣声"}])
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            judge.execute_material(m, "试咒")
        warned = [r.message for r in caplog.records
                  if r.levelno == logging.WARNING]
        assert any("buff" in w for w in warned), "buff 降级记 warning"
        assert any("control" in w for w in warned), "control 降级记 warning"
        assert any("summon" in w for w in warned), "unknown 降级记 warning"


class TestAdvanceTimeHooks:
    """advance_time 三合一:推时钟 + MP 恢复(余数累计) + timed 过期清除(2026-08-21 spec §2.2/§4)。"""

    def _world(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))
        from helpers import make_world, make_scene
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = Investigator(name="测试", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        world.set_player(inv)
        return world, inv

    def test_mp_recovery_whole_hours(self):
        world, inv = self._world()
        inv.derived.MP = 0
        world.advance_time(120)
        assert inv.derived.MP == 2, "120 分钟=2 小时,默认 1 点/小时回 2"

    def test_mp_recovery_accumulates_remainder(self):
        world, inv = self._world()
        inv.derived.MP = 0
        world.advance_time(30)
        assert inv.derived.MP == 0, "30 分钟不足 1 小时,不回 MP"
        world.advance_time(30)
        assert inv.derived.MP == 1, "余数累计:再 30 分钟凑满 1 小时回 1 点"

    def test_mp_recovery_clamped(self):
        world, inv = self._world()
        inv.derived.MP = inv.derived.MP_MAX - 1
        world.advance_time(300)
        assert inv.derived.MP == inv.derived.MP_MAX, "恢复 clamp 到 MP_MAX 不超上限"

    def test_timed_effect_expires(self):
        world, inv = self._world()
        base = world.clock.game_time
        inv.timed_effects = [{"id": "V", "description": "帷幕",
                              "expire_at": base + 10}]
        world.advance_time(10)
        assert inv.timed_effects == [], "恰好到期(expire_at==now)即清除"

    def test_timed_effect_survives_before_expiry(self):
        world, inv = self._world()
        base = world.clock.game_time
        inv.timed_effects = [{"id": "V", "description": "帷幕",
                              "expire_at": base + 60}]
        world.advance_time(10)
        assert len(inv.timed_effects) == 1, "未到期不得误清"

    def test_mp_recovery_rate_from_config(self, monkeypatch):
        import investigator.rules as rules_mod
        monkeypatch.setattr(rules_mod, "get_game_config",
                            lambda: {"mp_recovery_per_hour": 3})
        world, inv = self._world()
        inv.derived.MP = 0
        world.advance_time(60)
        assert inv.derived.MP == 3, "恢复率读 game_config 的 mp_recovery_per_hour"

    def test_mp_regen_zero_rate_disables(self, monkeypatch):
        import investigator.rules as rules_mod
        monkeypatch.setattr(rules_mod, "get_game_config",
                            lambda: {"mp_recovery_per_hour": 0})
        world, inv = self._world()
        inv.derived.MP = 0
        world.advance_time(600)
        assert inv.derived.MP == 0, "0 速率关闭 MP 恢复"


class TestTimedFactsRender:
    """facts 玩家行渲染 timed_effects(2026-08-21 spec §2.3)。"""

    def _world(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))
        from helpers import make_world, make_scene
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = Investigator(name="测试", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        world.set_player(inv)
        return world, inv

    def test_active_timed_effects_rendered(self):
        from scenario_core import WorldChronicle
        world, inv = self._world()
        inv.timed_effects = [{"id": "SILENCE_VEIL",
                              "description": "帷幕吞掉一切声响",
                              "expire_at": world.clock.game_time + 10}]
        text = WorldChronicle().render_for_author(world)
        assert "帷幕吞掉一切声响" in text
        assert "生效中" in text, "状态区块标签"

    def test_timed_remaining_minutes_rendered(self):
        from scenario_core import WorldChronicle
        world, inv = self._world()
        inv.timed_effects = [{"id": "SILENCE_VEIL",
                              "description": "帷幕吞掉一切声响",
                              "expire_at": world.clock.game_time + 10}]
        text = WorldChronicle().render_for_author(world)
        assert "剩10分钟" in text, "剩余分钟必须可见"

    def test_no_timed_effects_no_block(self):
        from scenario_core import WorldChronicle
        world, inv = self._world()
        inv.timed_effects = []
        text = WorldChronicle().render_for_author(world)
        assert "生效中" not in text, "无 timed 效果时不得渲染空区块"


class TestLibraryContentUpgrade:
    """2026-08-21 spec §7 内容示范:新原子在核心库真实条目上就位。"""

    def test_stone_skin_has_buff_and_timed(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        sp = lib.get("STONE_SKIN")
        types = [a["type"] for a in sp.effect]
        assert "buff" in types and "timed" in types
        buff = next(a for a in sp.effect if a["type"] == "buff")
        assert buff["reduce"] >= 1 and buff["rounds"] >= 1

    def test_dominate_has_control(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        sp = lib.get("DOMINATE")
        assert any(a["type"] == "control" for a in sp.effect)
        ctrl = next(a for a in sp.effect if a["type"] == "control")
        assert ctrl["rounds"] >= 1

    def test_silence_veil_has_timed(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        sp = lib.get("SILENCE_VEIL")
        assert any(a["type"] == "timed" for a in sp.effect)

    def test_damage_spells_array_format(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        for sid in ("HEART_ARREST", "BLOOD_CALL"):
            sp = lib.get(sid)
            assert isinstance(sp.effect, list) and len(sp.effect) == 1
            assert sp.effect[0]["type"] == "damage"

    def test_necronomicon_page_grants_spell(self):
        from library.items import ItemLibrary
        lib = ItemLibrary(); lib.load_core()
        it = lib.get("NECRONOMICON_PAGE")
        assert any("@grant_spell" in u for u in it.on_use)

    def test_salt_has_timed_effect(self):
        from library.items import ItemLibrary
        lib = ItemLibrary(); lib.load_core()
        it = lib.get("SALT")
        assert any(a.get("type") == "timed" for a in it.effect)
