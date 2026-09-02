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
