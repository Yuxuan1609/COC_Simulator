"""B1：存读档统一修复（①吞异常 ②引用重绑 ③注入重复）+ E 簇占坑 + v1 兼容。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _enemy_lib():
    from library.enemies import EnemyLibrary, LibraryEnemy
    lib = EnemyLibrary()
    lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
        "name": "测试巡游者", "type": "怪物",
        "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
        "attacks": [], "special_abilities": [], "san_loss": "0",
        "description": "", "combat_behavior": "",
    })
    return lib


class TestEnemyRestoreWithLibrary:
    def test_enemies_restored_with_library(self, tmp_path):
        """带库读档：敌人实例恢复（旧行为：库为 None → 吞异常 → enemies=None）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path, enemy_lib=lib)
        assert restored.enemies is not None, "带库读档 enemies 不得为 None"
        active = restored.enemies.get_active_in_scene("room_a")
        assert len(active) == 1, f"敌人实例应恢复，实际 {len(active)}"

    def test_missing_library_warns_not_silent(self, tmp_path):
        """无库读有敌人的档：enemies=None 但 load_warnings 非空（不静默）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)  # 不传库
        assert restored.enemies is None or not restored.enemies.get_active_in_scene("room_a")
        assert restored.load_warnings, "无库恢复敌人必须产生 warning（不静默）"

    def test_structural_corruption_raises(self, tmp_path):
        """结构性损坏（版本不支持）→ raise（旧世界不动）。"""
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": 99}), encoding="utf-8")
        from scenario_core import ScenarioWorld
        import pytest
        with pytest.raises(ValueError):
            ScenarioWorld.load_state(str(path))


class TestLoadRebindsReferences:
    def _keeper_game(self, monkeypatch):
        from helpers import make_world, make_scene, stub_keeper_llm, StubNarrator
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        from investigator import Investigator
        world.set_player(Investigator(name="测试员", age=25, gender="男"))
        keeper = Keeper(world)
        return {"keeper": keeper, "narrator": StubNarrator(), "author": None}

    def test_load_rebinds_judge_curator_monitor(self, tmp_path, monkeypatch):
        """load_game 后 judge/curator/turn_monitor 持新 world（旧 CLI 路径丢引用）。"""
        from game_loop import save_game, load_game
        game = self._keeper_game(monkeypatch)
        path = str(tmp_path / "save.json")
        save_game(game, path)
        old_world = game["keeper"].world

        load_game(game, path)
        keeper = game["keeper"]
        assert keeper.world is not old_world
        assert keeper.judge.world is keeper.world
        assert keeper.curator.world is keeper.world
        assert keeper.turn_monitor._world is keeper.world

    def test_meta_turn_number_restored(self, tmp_path, monkeypatch):
        """_meta.turn_number 随 load_game 恢复。"""
        from game_loop import save_game, load_game
        game = self._keeper_game(monkeypatch)
        game["keeper"].turn_number = 7
        path = str(tmp_path / "save.json")
        save_game(game, path)
        game["keeper"].turn_number = 0

        load_game(game, path)
        assert game["keeper"].turn_number == 7

    def test_load_copies_session_libraries(self, tmp_path, monkeypatch):
        """load_game 后 session 注入的库/字段从当前 world 拷到 restored（不入档）。"""
        from types import SimpleNamespace
        from game_loop import save_game, load_game
        game = self._keeper_game(monkeypatch)
        dummy_items = SimpleNamespace(name="item_lib")
        dummy_weapons = SimpleNamespace(name="weapon_lib")
        dummy_spells = SimpleNamespace(name="spell_lib")
        world = game["keeper"].world
        world.item_library = dummy_items
        world.weapon_library = dummy_weapons
        world.spell_library = dummy_spells
        world.time_costs = {"move": 5}
        world.comms_interval = 42
        path = str(tmp_path / "save.json")
        save_game(game, path)

        load_game(game, path)
        restored = game["keeper"].world
        assert restored.item_library is dummy_items
        assert restored.weapon_library is dummy_weapons
        assert restored.spell_library is dummy_spells
        assert restored.time_costs == {"move": 5}
        assert restored.comms_interval == 42


class TestNpcInjectionNoDuplicate:
    def test_injection_ids_survive_load(self, tmp_path, monkeypatch):
        """B1③：_npc_injected_at_ids 入档，读档后不重复注入。"""
        from helpers import make_world, make_scene
        from game_loop import save_game, load_game
        from game.agents.keeper import Keeper
        from helpers import StubNarrator

        profile = {"name": "列车员", "scene": "room_a", "can_interact": True,
                   "bound_auto_triggers": [{
                       "id": "AT_NPC1", "entity_type": "auto_trigger",
                       "name": "列车员的提醒", "type": "无", "requirement": "",
                       "trigger": "玩家进入车厢时", "result": "列车员低声提醒你。",
                       "difficulty": "None"}]}
        world = make_world({"room_a": make_scene()}, "room_a",
                           npc_profiles={"列车员": profile})
        keeper = Keeper(world)
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": None}
        keeper._inject_npc_at()
        node = world.graph.nodes["room_a"]
        assert sum(1 for e in node.auto_triggers if e.id == "AT_NPC1") == 1

        path = str(tmp_path / "save.json")
        save_game(game, path)
        load_game(game, path)

        keeper._inject_npc_at()
        node2 = keeper.world.graph.nodes["room_a"]
        ids = [e.id for e in node2.auto_triggers if e.id == "AT_NPC1"]
        assert len(ids) == 1, f"读档后 AT_NPC1 不得重复注入，实际 {len(ids)} 个"

    def test_session_state_roundtrip_minimal(self, tmp_path, monkeypatch):
        """session_state 最小集回环：注入集合/最近意图/上次通信时间。"""
        from helpers import make_world, make_scene, StubNarrator
        from game_loop import save_game, load_game
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        keeper = Keeper(world)
        keeper._npc_injected_at_ids.add("AT_X")
        keeper._recent_intents.append("练拳")
        keeper._last_comms_time = 42
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": None}

        path = str(tmp_path / "save.json")
        save_game(game, path)
        keeper._npc_injected_at_ids.clear()
        keeper._recent_intents.clear()
        keeper._last_comms_time = 0
        load_game(game, path)

        assert keeper._npc_injected_at_ids == {"AT_X"}
        assert keeper._recent_intents == ["练拳"]
        assert keeper._last_comms_time == 42


class TestFormatV2:
    def test_placeholder_containers_present(self, tmp_path):
        """E 簇占坑：存档含 clues/narrative_memory 空容器，回环保持。"""
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, "room_a")
        path = str(tmp_path / "save.json")
        world.save_state(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == 2
        assert data["world"]["clues"] == []
        assert data["world"]["narrative_memory"] == []

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)
        assert restored.clues == []
        assert restored.narrative_memory == []

    def test_v1_save_loads_with_defaults(self, tmp_path):
        """v1 旧档可读：缺 session_state/clues/checked 一律默认值。"""
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, "room_a")
        path = tmp_path / "save.json"
        world.save_state(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = 1                      # 模拟旧档
        data.pop("_meta", None)
        data["world"].pop("clues", None)
        data["world"].pop("narrative_memory", None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(str(path))
        assert restored.clues == []
        assert restored.narrative_memory == []
        assert restored.current_location == "room_a"

