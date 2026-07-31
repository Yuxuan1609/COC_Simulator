"""确定性 E2E：stub LLM，真实 World+Keeper+run_turn 多回合闭环。零 API 调用。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from helpers import (make_scene, make_world, stub_keeper_llm, make_game,
                     assert_player_turn_contract)


def _player(world, name="测试员"):
    from investigator import Investigator
    inv = Investigator(name=name, age=25, gender="男")
    world.set_player(inv)
    return inv


class TestOfferAnswerLoop:
    def test_search_offer_then_pickup(self, monkeypatch):
        """搜索发现武器 → pending(weapon_offer) → 下回合"是" → 武器入包。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from game.side_effects import SceneWeapon
        from library.weapons import WeaponLibrary, LibraryWeapon

        wlib = WeaponLibrary()
        wlib._weapons["手枪"] = LibraryWeapon(name="手枪", skill_name="射击(手枪)")
        world = make_world({"room_a": make_scene()}, "room_a",
                           weapon_library=wlib)
        inv = _player(world)
        world.scene_weapons["room_a"] = [
            SceneWeapon(weapon_ref="手枪", scene="room_a", quantity=1)]

        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "search", "text": "搜索四周"}]])
        game = make_game(keeper)

        r1 = run_turn(game, "搜索四周")
        assert_player_turn_contract(r1)
        assert r1.pending_interaction is not None
        assert r1.pending_interaction.kind == "weapon_offer"

        r2 = run_turn(game, "是")
        assert_player_turn_contract(r2)
        assert any(w.name == "手枪" for w in inv.weapons), "武器必须入包"
        assert not world.scene_weapons.get("room_a"), "场景武器必须移除"
        assert keeper._weapon_offer is None, "offer 应答后必须清空"


class TestClarifyAnswerLoop:
    def test_ambiguous_then_clarified(self, monkeypatch):
        """模糊输入 → SUSPENDED → 澄清输入 → 回合正常推进。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from game.messages import PreParseResult, TurnStatus

        world = make_world({"room_a": make_scene()}, "room_a")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "other", "text": "检查桌子"}]])
        game = make_game(keeper)

        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="ambiguous", interpretation="", question="你想检查哪里？",
            resolved_text="")
        r1 = run_turn(game, "看看")
        assert_player_turn_contract(r1)
        assert r1.status == TurnStatus.SUSPENDED
        assert r1.pending_interaction.kind == "clarify"

        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="clear", interpretation="", question="",
            resolved_text="检查桌子")
        r2 = run_turn(game, "检查桌子")
        assert_player_turn_contract(r2)
        assert r2.status == TurnStatus.COMPLETED
        assert r2.narrative, "澄清后回合必须产出叙事"


class TestCombatCompletionFlow:
    def _hostile_world(self):
        from library.enemies import EnemyLibrary, LibraryEnemy
        lib = EnemyLibrary()
        lib._enemies["深潜者"] = LibraryEnemy.from_dict({
            "name": "深潜者", "type": "怪物",
            "attributes": {"CON": 50, "SIZ": 50}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        world = make_world({"room_a": make_scene()}, "room_a",
                           enemy_library=lib)
        world.enemies.spawn("深潜者", "room_a", 1)
        return world

    def test_hostile_combat_init_then_complete(self, monkeypatch):
        """hostile 遭遇 → combat_init → 结算 → complete_combat_turn 产出战斗 brief。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._hostile_world()
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "继续前进"}]],
            combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                          "reasoning": "遭遇"})
        game = make_game(keeper)

        r1 = run_turn(game, "继续前进")
        assert_player_turn_contract(r1)
        assert r1.combat_init is not None, "hostile 遭遇必须产出 combat_init"
        assert r1.combat_init.enemies, "combat_init 必须携带敌人"

        completed = keeper.complete_combat_turn(
            keeper._last_player_input,
            {"outcome": "win", "narrative": "激战过后你赢了"})
        assert completed is not None, "complete_combat_turn 必须有回放素材"
        assert completed.brief is not None
        msgs = [o.message for o in completed.brief.action_outcomes]
        assert any("战斗胜利" in m for m in msgs), f"brief 缺战斗 outcome: {msgs}"


class TestMoveSuccess:
    def test_valid_move_changes_location(self, monkeypatch):
        """合法移动 → current_location 变更。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({
            "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                         "requirement": ""}]),
            "room_b": make_scene(exits=[{"target": "room_a", "method": "步行",
                                         "requirement": ""}]),
        }, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        r = run_turn(game, "前往room_b", action_type="move",
                     action_target="room_b")
        assert_player_turn_contract(r)
        assert world.current_location == "room_b", \
            f"移动后位置应为 room_b，实际 {world.current_location}"


class TestEndingTrigger:
    def test_ending_marker_produces_game_over(self, monkeypatch):
        """交互结果含 ##END_ 标记 → EndingInfo → game_over。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        ending_interaction = {
            "id": "IT_END", "entity_type": "interaction",
            "name": "揭开真相", "scene": "room_a",
            "type": "None", "requirement": "", "trigger": "阅读完整日志",
            "result": "你读完最后一页。##END_真相:你揭开了霍桑实验的真相##",
            "side_effects": [], "difficulty": "None",
        }
        world = make_world(
            {"room_a": make_scene(interactions=[ending_interaction])}, "room_a")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_END"}]])
        game = make_game(keeper)

        r = run_turn(game, "阅读完整日志")
        assert_player_turn_contract(r)
        assert r.game_over is True, "结局标记必须触发 game_over"
        assert r.ending is not None
        assert r.ending.name == "真相"
        assert "霍桑" in r.ending.narrative


class TestNpcDialogueTurn:
    def test_pure_dialogue_turn(self, monkeypatch):
        """NPC 纯对话回合：COMPLETED + 对话文本 + npc_events。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a",
                           npc_profiles={"列车员": {
                               "name": "列车员", "scene": "room_a",
                               "can_interact": True}})
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "npc_interact",
                                         "npc_name": "列车员"}]])
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: "你好，乘客。车厢里不太平。")
        game = make_game(keeper)

        r = run_turn(game, "和列车员搭话")
        assert_player_turn_contract(r)
        assert "列车员" in r.narrative
        assert "你好，乘客" in r.narrative
        assert r.diagnostics["npc_events"], "npc_events 必须非空"


class TestMultiTurnStateSequence:
    def test_turn_sequence_state_integrity(self, monkeypatch):
        """多回合序列：回合号递增、时钟推进、无跨回合 pending 泄漏。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({
            "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                         "requirement": ""}]),
            "room_b": make_scene(),
        }, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch, time_delta=10)
        game = make_game(keeper)

        t0 = world.clock.game_time

        r1 = run_turn(game, "四处看看")
        assert_player_turn_contract(r1)
        assert keeper.turn_number == 1

        r2 = run_turn(game, "前往room_b", action_type="move",
                      action_target="room_b")
        assert_player_turn_contract(r2)
        assert keeper.turn_number == 2
        assert world.current_location == "room_b"

        r3 = run_turn(game, "休息片刻")
        assert_player_turn_contract(r3)
        assert keeper.turn_number == 3

        assert world.clock.game_time > t0, "时钟必须推进"
        assert keeper._standoff_pending is None
        assert keeper._weapon_offer is None
