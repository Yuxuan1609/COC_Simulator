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
