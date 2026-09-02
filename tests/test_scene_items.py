"""F17 scene_items：加载映射 + 入档往返（S3-P3 spec §1.1）。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))


def test_scene_weapons_map_to_scene_items_exposed():
    from helpers import make_world, make_scene
    from game.side_effects import SceneWeapon
    world = make_world({"room_a": make_scene()}, "room_a")
    world.scene_weapons["room_a"] = [
        SceneWeapon(weapon_ref="手枪", scene="room_a", quantity=1)]
    world._hydrate_scene_items_from_weapons()
    items = world.scene_items.get("room_a", [])
    assert len(items) == 1
    assert items[0].kind == "weapon" and items[0].ref == "手枪"
    assert items[0].hidden is False
    assert not hasattr(items[0], "quantity") or items[0].quantity == 1


def test_node_scene_items_load_and_save_roundtrip():
    from scenario_core import DirectedGraph, ScenarioWorld
    graph = DirectedGraph({
        "room_a": {
            "from_here": [], "to_here": [], "interactions": [],
            "auto_triggers": [], "encounters": [], "scene_weapons": [],
            "scene_items": [
                {"kind": "item", "ref": "钥匙", "quantity": 1, "hidden": True},
                {"kind": "weapon", "ref": "手枪", "hidden": False},
            ],
        }
    })
    world = ScenarioWorld(graph, "room_a")
    items = world.scene_items["room_a"]
    assert {(i.kind, i.ref, i.hidden) for i in items} == {
        ("item", "钥匙", True), ("weapon", "手枪", False)}
    dumped = world.to_dict()
    world2 = ScenarioWorld.from_dict(dumped, graph)
    items2 = world2.scene_items["room_a"]
    assert {(i.kind, i.ref, i.hidden) for i in items2} == {
        ("item", "钥匙", True), ("weapon", "手枪", False)}


def test_legacy_save_scene_weapons_hydrate_on_load():
    """旧档只有 scene_weapons 键：加载后并入 scene_items（hidden=false）。"""
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    data = world.to_dict()
    data.pop("scene_items", None)
    data["scene_weapons"] = {"room_a": [{"weapon_ref": "手枪", "quantity": 1}]}
    world2 = type(world).from_dict(data, world.graph)
    items = world2.scene_items.get("room_a", [])
    assert any(i.kind == "weapon" and i.ref == "手枪" and not i.hidden for i in items)


class TestSearchExpose:
    def _game(self, monkeypatch, hidden=True, kind="item", ref="钥匙",
              parse=None, wlib=None):
        from helpers import make_world, make_scene, stub_keeper_llm, make_game
        from game.agents.keeper import Keeper
        from game.side_effects import SceneItem
        from investigator import Investigator, Skill

        world = make_world({"room_a": make_scene()}, "room_a",
                           weapon_library=wlib)
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        world.set_player(inv)
        world.scene_items["room_a"] = [
            SceneItem(kind=kind, ref=ref, hidden=hidden, quantity=1)]
        world._sync_scene_weapons_from_items()
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=parse or [[{"type": "search", "text": "搜索四周"}]])
        return make_game(keeper), world, inv, keeper

    def test_search_success_exposes_hidden(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 1)
        game, world, inv, keeper = self._game(monkeypatch)
        r = run_turn(game, "搜索四周")
        assert_player_turn_contract(r)
        assert r.pending_interaction is None
        items = world.scene_items.get("room_a", [])
        assert items and items[0].hidden is False
        assert "钥匙" in r.narrative

    def test_search_fail_does_not_expose(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 100)
        game, world, inv, keeper = self._game(monkeypatch)
        r = run_turn(game, "搜索四周")
        assert_player_turn_contract(r)
        items = world.scene_items.get("room_a", [])
        assert items and items[0].hidden is True
        assert r.pending_interaction is None

    def test_pickup_exposed_item_free(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game(
            monkeypatch, hidden=False,
            parse=[[{"type": "other", "text": "随便"}]])
        r = run_turn(game, "我捡起钥匙")
        assert_player_turn_contract(r)
        assert inv.item_manager.has("钥匙")
        assert not world.scene_items.get("room_a")
        assert r.pending_interaction is None

    def test_pickup_hidden_rejected(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game(
            monkeypatch, hidden=True,
            parse=[[{"type": "other", "text": "随便"}]])
        r = run_turn(game, "我捡起钥匙")
        assert_player_turn_contract(r)
        assert not inv.item_manager.has("钥匙")
        assert "没发现" in r.narrative
        assert world.scene_items["room_a"][0].hidden is True
        assert keeper.turn_number == 0

    def test_pickup_weapon_still_works(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        from library.weapons import WeaponLibrary, LibraryWeapon
        wlib = WeaponLibrary()
        wlib._weapons["手枪"] = LibraryWeapon(name="手枪", skill_name="射击(手枪)")
        game, world, inv, keeper = self._game(
            monkeypatch, hidden=False, kind="weapon", ref="手枪", wlib=wlib,
            parse=[[{"type": "other", "text": "随便"}]])
        r = run_turn(game, "我捡起手枪")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons)
        assert not world.scene_items.get("room_a")

    def test_pickup_prefers_longest_exposed_over_hidden_substring(self, monkeypatch):
        """暴露「小刀」长于隐藏「刀」：点名小刀应授予，不得 Early 没发现。"""
        from helpers import make_world, make_scene, stub_keeper_llm, make_game
        from helpers import assert_player_turn_contract
        from game.agents.keeper import Keeper
        from game.side_effects import SceneItem
        from game_loop import run_turn
        from investigator import Investigator, Skill
        from library.weapons import WeaponLibrary, LibraryWeapon

        wlib = WeaponLibrary()
        wlib._weapons["小刀"] = LibraryWeapon(name="小刀", skill_name="斗殴")
        world = make_world({"room_a": make_scene()}, "room_a", weapon_library=wlib)
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        world.set_player(inv)
        world.scene_items["room_a"] = [
            SceneItem(kind="weapon", ref="刀", hidden=True, quantity=1),
            SceneItem(kind="weapon", ref="小刀", hidden=False, quantity=1),
        ]
        world._sync_scene_weapons_from_items()
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "随便"}]])
        game = make_game(keeper)
        r = run_turn(game, "我捡起小刀")
        assert_player_turn_contract(r)
        assert "没发现" not in r.narrative
        assert any(w.name == "小刀" for w in inv.weapons)
        refs = [i.ref for i in world.scene_items.get("room_a", [])]
        assert "小刀" not in refs
        assert "刀" in refs


class TestDropToScene:
    def _game_with_item(self, monkeypatch, item="钥匙"):
        from helpers import make_world, make_scene, stub_keeper_llm, make_game
        from game.agents.keeper import Keeper
        from investigator import Investigator, Skill

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        inv.item_manager.add(item)
        world.set_player(inv)
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "随便"}]])
        return make_game(keeper), world, inv, keeper

    def _game_with_weapon(self, monkeypatch, name="手枪"):
        from helpers import make_world, make_scene, stub_keeper_llm, make_game
        from game.agents.keeper import Keeper
        from investigator import Investigator, Skill, Weapon

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        inv.add_weapon(Weapon(name=name, skill_name="射击(手枪)"))
        world.set_player(inv)
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "随便"}]])
        return make_game(keeper), world, inv, keeper

    def test_drop_item_to_scene_exposed(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_item(monkeypatch)
        r = run_turn(game, "我丢掉钥匙")
        assert_player_turn_contract(r)
        assert not inv.item_manager.has("钥匙")
        items = world.scene_items.get("room_a", [])
        assert any(i.kind == "item" and i.ref == "钥匙" and not i.hidden for i in items)
        assert keeper.turn_number == 0
        assert r.pending_interaction is None

    def test_drop_weapon_to_scene(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_weapon(monkeypatch)
        r = run_turn(game, "我丢掉手枪")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons)
        items = world.scene_items.get("room_a", [])
        assert any(i.kind == "weapon" and i.ref == "手枪" and not i.hidden for i in items)
        assert keeper.turn_number == 0

    def test_drop_then_pickup_roundtrip(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_item(monkeypatch)
        r1 = run_turn(game, "我丢掉钥匙")
        assert_player_turn_contract(r1)
        r2 = run_turn(game, "我捡起钥匙")
        assert_player_turn_contract(r2)
        assert inv.item_manager.has("钥匙")
        assert not world.scene_items.get("room_a")
        assert keeper.turn_number == 0

    def test_negative_does_not_drop(self, monkeypatch):
        from helpers import assert_player_turn_contract
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_item(monkeypatch)
        r = run_turn(game, "我不丢掉钥匙")
        assert_player_turn_contract(r)
        assert inv.item_manager.has("钥匙")
        assert not world.scene_items.get("room_a")

    def test_drop_does_not_merge_into_hidden(self, monkeypatch):
        """隐藏同 kind+ref 不得被合并；丢弃追加暴露行，无需搜索即可捡起暴露件。"""
        from helpers import assert_player_turn_contract
        from game.side_effects import SceneItem
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_item(monkeypatch)
        world.scene_items["room_a"] = [
            SceneItem(kind="item", ref="钥匙", hidden=True, quantity=1)]
        r1 = run_turn(game, "我丢掉钥匙")
        assert_player_turn_contract(r1)
        assert not inv.item_manager.has("钥匙")
        items = world.scene_items.get("room_a", [])
        hidden = [i for i in items if i.kind == "item" and i.ref == "钥匙" and i.hidden]
        exposed = [i for i in items if i.kind == "item" and i.ref == "钥匙" and not i.hidden]
        assert len(hidden) == 1 and hidden[0].quantity == 1
        assert len(exposed) == 1 and exposed[0].quantity == 1
        r2 = run_turn(game, "我捡起钥匙")
        assert_player_turn_contract(r2)
        assert inv.item_manager.has("钥匙")
        items2 = world.scene_items.get("room_a", [])
        assert any(i.kind == "item" and i.ref == "钥匙" and i.hidden for i in items2)
        assert not any(i.kind == "item" and i.ref == "钥匙" and not i.hidden
                       for i in items2)

    def test_drop_weapon_stacks_exposed_quantity(self, monkeypatch):
        """已有暴露同名武器时丢弃应 quantity+=1，不得吞掉玩家那把。"""
        from helpers import assert_player_turn_contract
        from game.side_effects import SceneItem
        from game_loop import run_turn
        game, world, inv, keeper = self._game_with_weapon(monkeypatch)
        world.scene_items["room_a"] = [
            SceneItem(kind="weapon", ref="手枪", hidden=False, quantity=1)]
        world._sync_scene_weapons_from_items()
        r = run_turn(game, "我丢掉手枪")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons)
        items = world.scene_items.get("room_a", [])
        exposed = [i for i in items
                   if i.kind == "weapon" and i.ref == "手枪" and not i.hidden]
        assert sum(i.quantity for i in exposed) >= 2

    def test_drop_unowned_early(self, monkeypatch):
        from helpers import make_world, make_scene, stub_keeper_llm, make_game
        from helpers import assert_player_turn_contract
        from game.agents.keeper import Keeper
        from game_loop import run_turn
        from investigator import Investigator, Skill

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        world.set_player(inv)
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "随便"}]])
        r = run_turn(make_game(keeper), "我丢掉钥匙")
        assert_player_turn_contract(r)
        assert "你没有钥匙" in r.narrative
        assert keeper.turn_number == 0
        assert not world.scene_items.get("room_a")


def test_grant_weapon_scene_survives_sync():
    """GrantWeapon(scene=...) 写入 scene_items；_sync 不得丢掉暴露武器。"""
    from helpers import make_world, make_scene
    from game.side_effects import GrantWeapon
    from scenario_core import apply_side_effects

    world = make_world({"room_a": make_scene()}, "room_a")
    apply_side_effects(world, [GrantWeapon(weapon_ref="手枪", scene="room_a")])
    world._sync_scene_weapons_from_items()
    items = world.scene_items.get("room_a", [])
    assert any(i.kind == "weapon" and i.ref == "手枪" and not i.hidden for i in items)


def _mixed_hidden_exposed_world():
    from helpers import make_world, make_scene
    from game.side_effects import SceneItem
    world = make_world({"room_a": make_scene()}, "room_a")
    world.scene_items["room_a"] = [
        SceneItem(kind="item", ref="钥匙", hidden=True, quantity=1),
        SceneItem(kind="item", ref="手电", hidden=False, quantity=2),
        SceneItem(kind="weapon", ref="手枪", hidden=False, quantity=1),
        SceneItem(kind="weapon", ref="匕首", hidden=True, quantity=1),
    ]
    world._sync_scene_weapons_from_items()
    return world


def test_snapshot_lists_only_exposed_scene_items():
    world = _mixed_hidden_exposed_world()
    snap = world.build_snapshot()
    items = snap["scene_items"]
    refs = [i["ref"] for i in items]
    assert "手电" in refs
    assert "手枪" in refs
    assert "钥匙" not in refs
    assert "匕首" not in refs
    for i in items:
        assert set(i) >= {"kind", "ref", "quantity"}
        assert "hidden" not in i
    wep_refs = [w["weapon_ref"] for w in snap["scene_weapons"]]
    assert "手枪" in wep_refs
    assert "匕首" not in wep_refs


def test_build_scene_state_lists_exposed_not_hidden():
    from prompts import _build_scene_state
    world = _mixed_hidden_exposed_world()
    text = _build_scene_state(world.build_snapshot())
    assert "手电" in text
    assert "手枪" in text
    assert "钥匙" not in text
    assert "匕首" not in text
