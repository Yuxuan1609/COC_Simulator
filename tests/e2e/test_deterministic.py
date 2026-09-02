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
        """搜索成功暴露隐藏武器 → 无 pending → 下回合直接拾取入包。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from game.side_effects import SceneItem
        from investigator import Investigator, Skill
        from library.weapons import WeaponLibrary, LibraryWeapon

        wlib = WeaponLibrary()
        wlib._weapons["手枪"] = LibraryWeapon(name="手枪", skill_name="射击(手枪)")
        world = make_world({"room_a": make_scene()}, "room_a",
                           weapon_library=wlib)
        inv = Investigator(name="测试员", age=25, gender="男",
                           skills=[Skill(name="侦查", base_value=50)])
        world.set_player(inv)
        world.scene_items["room_a"] = [
            SceneItem(kind="weapon", ref="手枪", hidden=True, quantity=1)]
        world._sync_scene_weapons_from_items()

        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "search", "text": "搜索四周"}]])
        game = make_game(keeper)
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 1)

        r1 = run_turn(game, "搜索四周")
        assert_player_turn_contract(r1)
        assert r1.pending_interaction is None
        items = world.scene_items.get("room_a", [])
        assert items and items[0].hidden is False

        r2 = run_turn(game, "我捡起手枪")
        assert_player_turn_contract(r2)
        assert any(w.name == "手枪" for w in inv.weapons), "武器必须入包"
        assert not world.scene_items.get("room_a"), "场景物品必须移除"
        assert not world.scene_weapons.get("room_a"), "场景武器必须移除"


class TestWeaponPickupRules:
    """R1 直接拾取通路（exposed scene_items）。"""

    def _setup(self, monkeypatch):
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from game.side_effects import SceneItem
        from library.weapons import WeaponLibrary, LibraryWeapon

        wlib = WeaponLibrary()
        wlib._weapons["手枪"] = LibraryWeapon(name="手枪", skill_name="射击(手枪)")
        world = make_world({"room_a": make_scene()}, "room_a",
                           weapon_library=wlib)
        inv = _player(world)
        world.scene_items["room_a"] = [
            SceneItem(kind="weapon", ref="手枪", hidden=False, quantity=1)]
        world._sync_scene_weapons_from_items()
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "other", "text": "随便"}]])
        game = make_game(keeper)
        return run_turn, world, inv, keeper, game

    def test_direct_pickup_by_name(self, monkeypatch):
        """R1：明说「捡+武器名」直接入包。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "我捡起手枪")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons), "直接拾取必须入包"
        assert not world.scene_items.get("room_a"), "场景物品必须移除"
        assert not world.scene_weapons.get("room_a"), "场景武器必须移除"

    def test_direct_pickup_unnamed_single_weapon(self, monkeypatch):
        """场景仅一件可拾武器时，未点名也直接拾取。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "把地上的武器捡起来")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons)
        assert not world.scene_items.get("room_a")

    def test_direct_pickup_negative_ignored(self, monkeypatch):
        """含否定词的拾取表述不触发直接拾取。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "我才不捡那把手枪")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons)
        assert world.scene_items.get("room_a")
        assert world.scene_weapons.get("room_a")

    def test_direct_pickup_owned_not_duplicated(self, monkeypatch):
        """已持有的武器不入拾取池，不重复入包。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        run_turn(game, "我捡起手枪")
        r2 = run_turn(game, "再捡起手枪")
        assert_player_turn_contract(r2)
        assert sum(1 for w in inv.weapons if w.name == "手枪") == 1


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

    def test_pure_dialogue_records_memory(self, monkeypatch):
        """F24: 纯对话短路也必须 add_record,parse 下轮能看见已问情报。"""
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

        run_turn(game, "和列车员搭话")
        hist = world.memory.raw_history
        assert hist, "纯对话必须写入 memory.raw_history"
        rec = hist[-1]
        assert "搭话" in rec["user_input"]
        assert "车厢里不太平" in rec["result"] or "你好" in rec["result"]
        ctx = world.memory.get_context()
        assert "车厢里不太平" in ctx or "你好" in ctx, "parse prompt 的近期行动须含对话内容"


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


def _enemy_lib_with(name="测试巡游者"):
    from library.enemies import EnemyLibrary
    lib = EnemyLibrary()
    lib._enemies[name] = __import__("library.enemies", fromlist=["LibraryEnemy"]).LibraryEnemy.from_dict({
        "name": name, "type": "怪物",
        "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
        "attacks": [], "special_abilities": [], "san_loss": "0",
        "description": "", "combat_behavior": "",
    })
    return lib


class TestAutoTriggerSpawn:  # D8: A2/C6
    def test_at_fires_spawn_enemy_visible(self, monkeypatch):
        """AT 被 parse 命中 → @spawn_enemy 副作用 → 敌人实例出现在场景快照。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        lib = _enemy_lib_with()
        at = {
            "id": "AT_SPAWN", "entity_type": "auto_trigger", "type": "无",
            "name": "巡游者出现", "requirement": "",
            "trigger": "玩家首次进入时",
            "result": "黑暗中有什么东西蠕动着靠近。",
            "side_effects": ['@spawn_enemy(enemy_ref="测试巡游者", scene="room_a", quantity=1)'],
            "graded_result": None, "difficulty": "None",
            "scene": "room_a", "time_condition": [],
        }
        world = make_world({"room_a": make_scene(auto_triggers=[at])}, "room_a",
                           enemy_library=lib)
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "auto_trigger", "id": "AT_SPAWN"}]])
        game = make_game(keeper)

        r = run_turn(game, "环顾四周")
        assert_player_turn_contract(r)
        active = world.enemies.get_active_in_scene("room_a")
        assert len(active) == 1, f"AT 副作用必须生成敌人，实际 {len(active)}"
        assert active[0].enemy_ref == "测试巡游者"
        snap = world.enemies.get_active_in_scene_snapshot("room_a")
        assert snap and snap[0]["enemy_ref"] == "测试巡游者"

    def test_at_spawn_unknown_ref_degrades(self, monkeypatch):
        """@spawn_enemy 引用库中不存在的敌人 → 回合不炸，警告进叙事。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        lib = _enemy_lib_with()
        at = {
            "id": "AT_BAD", "entity_type": "auto_trigger", "type": "无",
            "name": "错误生成", "requirement": "", "trigger": "进入时",
            "result": "（生成失败）",
            "side_effects": ['@spawn_enemy(enemy_ref="不存在的怪", scene="room_a", quantity=1)'],
            "graded_result": None, "difficulty": "None",
            "scene": "room_a", "time_condition": [],
        }
        world = make_world({"room_a": make_scene(auto_triggers=[at])}, "room_a",
                           enemy_library=lib)
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "auto_trigger", "id": "AT_BAD"}]])
        game = make_game(keeper)

        r = run_turn(game, "环顾四周")
        assert_player_turn_contract(r)
        assert not world.enemies.get_active_in_scene("room_a")
        assert any("不存在" in w for w in keeper._warnings), \
            f"未知 enemy_ref 必须降级为 warning，实际 warnings={keeper._warnings}"


class TestFailureEscalation:  # D9: A5
    def _fail_world(self):
        interaction = {
            "id": "IT_LOCK", "entity_type": "interaction",
            "name": "撬锁", "scene": "room_a",
            "type": "锁匠", "requirement": "", "trigger": "尝试撬锁",
            "result": "##GRADED##",
            "graded_result": {"on_failure": "锁纹丝不动。",
                              "on_regular": "锁开了。",
                              "on_hard": "锁开了。", "on_extreme": "锁开了。"},
            "side_effects": [], "difficulty": "regular", "time_condition": [],
        }
        world = make_world({"room_a": make_scene(interactions=[interaction])}, "room_a")
        inv = _player(world)
        inv.check_skill = lambda skill, diff: (False, f"{skill}检定：D100=98/10", "failure")
        return world

    def test_failure_escalates_difficulty_and_counts_retries(self, monkeypatch):
        """首次失败→难度升一档；重试计数递增；重复失败不炸回合。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._fail_world()
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        state = world.get_runtime_state("IT_LOCK")
        r1 = run_turn(game, "撬锁")
        assert_player_turn_contract(r1)
        assert state.retries == 1
        assert state.escalated_difficulty == "hard", \
            f"首次失败后难度应 regular→hard，实际 {state.escalated_difficulty}"

        r2 = run_turn(game, "再试一次撬锁")
        assert_player_turn_contract(r2)
        assert state.retries == 2
        assert state.escalated_difficulty == "hard", "难度升级后不得回落"


class TestLockKeyFlow:  # F16: 锁-钥匙 infra 链路锁定(不加机制)
    def _lock_world(self):
        lock = {
            "id": "IT_LOCK", "entity_type": "interaction",
            "name": "撬锁", "scene": "room_a",
            "type": "锁匠", "requirement": "", "trigger": "撬锁",
            "result": "##GRADED##",
            "graded_result": {"on_failure": "锁纹丝不动。",
                              "on_regular": "锁开了。",
                              "on_hard": "锁开了。", "on_extreme": "锁开了。"},
            "side_effects": [], "difficulty": "regular", "time_condition": [],
        }
        world = make_world({
            "room_a": make_scene(
                interactions=[lock],
                exits=[{"target": "room_b", "method": "步行",
                        "requirement": "IT_LOCK"}]),
            "room_b": make_scene(),
        }, "room_a")
        return world

    def test_door_blocked_before_unlock(self, monkeypatch):
        """开锁前:出口硬条件挡住移动。"""
        world = self._lock_world()
        _player(world)
        blocked = world.move("room_b")
        assert not blocked.success, "锁未完成前移动必须被挡"
        assert world.current_location == "room_a"

    def test_lockpick_success_unlocks_door(self, monkeypatch):
        """撬锁检定成功 → mark_completed → 同一出口即时通过。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._lock_world()
        inv = _player(world)
        inv.check_skill = lambda skill, diff: (True, f"{skill}检定：D100=10/50", "regular")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        r = run_turn(game, "撬锁")
        assert_player_turn_contract(r)
        assert world.is_entity_completed("IT_LOCK"), "检定成功必须翻转锁的 completed"

        ok = world.move("room_b")
        assert ok.success and world.current_location == "room_b", \
            "锁已开,移动必须即时通过"

    def test_lockpick_failure_keeps_door_shut(self, monkeypatch):
        """撬锁失败 → 门保持关闭(与 TestFailureEscalation 难度升级不冲突)。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._lock_world()
        inv = _player(world)
        inv.check_skill = lambda skill, diff: (False, f"{skill}检定：D100=98/10", "failure")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        r = run_turn(game, "撬锁")
        assert_player_turn_contract(r)
        assert not world.is_entity_completed("IT_LOCK")
        assert not world.move("room_b").success


class TestBossPrespawnEngage:  # D10: B3
    def _boss_world(self, tmp_path):
        import json as _json
        from library.bosses import BossLibrary
        boss_data = {"测试魔像": {
            "type": "神话造物",
            "attributes": {"STR": 120, "CON": 140, "SIZ": 130, "DEX": 30, "POW": 80},
            "armor": "4点石壳", "attacks": [], "special_abilities": [],
            "san_loss": "1/1D6", "description": "测试用",
            "boss_mechanics": "两阶段测试",
            "flags": ["boss"], "multi_attack": 1,
            "phases": [{"trigger": "hp_below_pct:0.5", "name": "崩解",
                        "overrides": {"multi_attack": 2},
                        "description": "外壳碎裂"}],
        }}
        p = tmp_path / "bosses.json"
        p.write_text(_json.dumps(boss_data, ensure_ascii=False), encoding="utf-8")
        bl = BossLibrary(str(p))
        enc = {"id": "BOSS_T1", "type": "boss_encounter", "engage_type": "at",
               "boss_ref": "测试魔像", "scene": "room_a",
               "requirements": "", "description": "测试遭遇"}
        lib = _enemy_lib_with()
        world = make_world({"room_a": make_scene()}, "room_a",
                           enemy_library=lib, boss_library=bl,
                           boss_encounters=[enc])
        return world, enc

    def test_prespawn_visible_and_engage_reuses_instance(self, monkeypatch, tmp_path):
        """预生成实例场景可见；engage 复用同一实例不重复造人。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world, enc = self._boss_world(tmp_path)
        _player(world)
        inst = world.bosses.spawn_instance(enc)
        world.enemies.register(inst)

        snap = world.enemies.get_active_in_scene_snapshot("room_a")
        assert any(e["enemy_ref"] == "测试魔像" for e in snap), \
            "预生成 Boss 必须在场景快照可见"
        assert inst.phases and inst.phases[0]["name"] == "崩解"

        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        r = run_turn(game, "环顾四周")
        assert_player_turn_contract(r)
        assert r.combat_init is not None, "at 型 Boss 在场景回合必须 engage"
        ci_ids = [e.instance_id for e in r.combat_init.enemies]
        assert ci_ids == [inst.instance_id], \
            f"engage 必须复用预生成实例 {inst.instance_id}，实际 {ci_ids}"
        assert len(world.enemies._instances) == 1, "不得产生重复 Boss 实例"
        assert world.bosses.has_spawned("BOSS_T1")

    def test_phase_triggers_below_hp_threshold(self, tmp_path):
        """HP 低于阈值 → _check_phase 返回阶段名；未低于则不触发。"""
        from types import SimpleNamespace
        from game.combat import CombatSystem

        world, enc = self._boss_world(tmp_path)
        inst = world.bosses.spawn_instance(enc)
        cs = CombatSystem()
        state = SimpleNamespace(round=1)

        inst.hp_max = 27
        inst.hp = 27
        assert cs._check_phase(state, inst) is None, "满血不得触发阶段"
        inst.hp = 10  # 10/27 ≈ 0.37 < 0.5
        assert cs._check_phase(state, inst) == "崩解"


class TestStandoffBossMutex:  # F3: standoff×boss 同回合互斥
    def _mixed_world(self, tmp_path):
        import json as _json
        from library.bosses import BossLibrary
        boss_data = {"测试魔像": {
            "type": "神话造物",
            "attributes": {"STR": 120, "CON": 140, "SIZ": 130, "DEX": 30, "POW": 80},
            "armor": "4点石壳", "attacks": [], "special_abilities": [],
            "san_loss": "1/1D6", "description": "测试用",
            "boss_mechanics": "两阶段测试",
            "flags": ["boss"], "multi_attack": 1, "phases": [],
        }}
        p = tmp_path / "bosses.json"
        p.write_text(_json.dumps(boss_data, ensure_ascii=False), encoding="utf-8")
        bl = BossLibrary(str(p))
        enc = {"id": "BOSS_T1", "type": "boss_encounter", "engage_type": "at",
               "boss_ref": "测试魔像", "scene": "room_a",
               "requirements": "", "description": "测试遭遇"}
        from library.enemies import EnemyLibrary, LibraryEnemy
        lib = EnemyLibrary()
        lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
            "name": "测试巡游者", "type": "怪物",
            "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "[avoidable] 行动迟缓",
        })
        world = make_world({"room_a": make_scene()}, "room_a",
                           enemy_library=lib, boss_library=bl,
                           boss_encounters=[enc])
        return world, enc

    def test_boss_engage_devours_standoff(self, monkeypatch, tmp_path):
        """Boss 强制战命中时：standoff 不播种，avoidable 敌人并入 Boss 战。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world, enc = self._mixed_world(tmp_path)
        _player(world)
        boss_inst = world.bosses.spawn_instance(enc)
        world.enemies.register(boss_inst)
        world.enemies.spawn("测试巡游者", "room_a", 1)

        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "环顾四周"}]],
            combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                          "reasoning": "遭遇"})
        game = make_game(keeper)

        r = run_turn(game, "环顾四周")
        assert_player_turn_contract(r)
        assert r.combat_init is not None, "Boss engage 必须产出 combat_init"
        ci_refs = sorted(getattr(e, "enemy_ref", "") for e in r.combat_init.enemies)
        assert ci_refs == ["测试巡游者", "测试魔像"], \
            f"avoidable 敌人必须并入 Boss 战，实际 {ci_refs}"
        assert keeper._standoff_pending is None, "Boss 开战时不得残留 standoff 播种"
        if r.pending_interaction is not None:
            assert r.pending_interaction.kind != "standoff", \
                "Boss 开战时不得发出 standoff pending"
        assert "最后一次机会" not in r.brief, \
            f"Boss 开战时不得出现对峙话术: {r.brief[:200]}"
        assert boss_inst.status == "engaged"
        wanderer = [i for i in world.enemies._instances.values()
                    if i.enemy_ref == "测试巡游者"][0]
        assert wanderer.status == "engaged", \
            f"卷入战斗的 avoidable 敌人必须 engaged，实际 {wanderer.status}"

    def test_standoff_without_boss_unchanged(self, monkeypatch, tmp_path):
        """无 Boss 时 avoidable 对峙照常播种（互斥不破坏原通路）。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from library.enemies import EnemyLibrary, LibraryEnemy

        lib = EnemyLibrary()
        lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
            "name": "测试巡游者", "type": "怪物",
            "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "[avoidable] 行动迟缓",
        })
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        _player(world)
        world.enemies.spawn("测试巡游者", "room_a", 1)

        keeper = Keeper(world)
        stub_keeper_llm(
            keeper, monkeypatch,
            parse_results=[[{"type": "other", "text": "环顾四周"}]],
            combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                          "reasoning": "遭遇"})
        game = make_game(keeper)

        r = run_turn(game, "环顾四周")
        assert_player_turn_contract(r)
        assert keeper._standoff_pending is not None, "无 Boss 时 standoff 必须照常播种"
        assert r.pending_interaction is not None
        assert r.pending_interaction.kind == "standoff"


class TestEscalationGate:
    def test_mixed_entity_and_other_suppresses_escalation(self, monkeypatch):
        """实体+other 混合输入：升级被硬性门控抑制——实体结果正常交付、
        完成标记与叙事一致、Author 不被咨询（防递归丢帧回归）。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        key_interaction = {
            "id": "IT_KEY", "entity_type": "interaction",
            "name": "翻开松砖找钥匙", "scene": "room_a",
            "type": "None", "requirement": "", "trigger": "翻开松砖",
            "result": "你在松砖下摸到了一把测试钥匙。",
            "side_effects": [], "difficulty": "None", "time_condition": [],
        }
        world = make_world(
            {"room_a": make_scene(interactions=[key_interaction])}, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch, parse_results=[[
            {"type": "interaction", "id": "IT_KEY"},
            {"type": "other", "text": "大喊救命"},
        ]])

        class _FakeAuthor:
            time_pressure = None
            calls = 0
            def handle_request(self, request, turn_number=0):
                _FakeAuthor.calls += 1
                raise AssertionError("混合输入下不应升级 Author")

        game = {"keeper": keeper, "narrator": None, "author": _FakeAuthor()}
        from helpers import StubNarrator
        game["narrator"] = StubNarrator()

        r = run_turn(game, "翻开松砖找钥匙，顺便大喊救命")
        assert_player_turn_contract(r)
        assert world.is_entity_completed("IT_KEY"), "实体必须执行并完成标记"
        assert "测试钥匙" in (r.narrative or ""), \
            f"实体结果必须交付玩家（不得被递归丢弃）: {(r.narrative or '')[:120]}"
        assert _FakeAuthor.calls == 0, "混合输入下 Author 不得介入"
        assert len(world.graph.nodes["room_a"].interactions) == 1, \
            "不得产生动态 patch 实体"

    def test_pure_other_still_escalates(self, monkeypatch):
        """纯 other 输入：升级通路保持可用（门控不误伤正常 patch）。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "other", "text": "对着空气唱歌"}]])

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False
                    intent = ""
                    reasoning = ""
                return R()
        keeper.intent_detector = _FakeDetector()

        class _FakeAuthor:
            time_pressure = None
        game = {"keeper": keeper, "narrator": None, "author": _FakeAuthor()}
        from helpers import StubNarrator
        game["narrator"] = StubNarrator()

        r = run_turn(game, "对着空气唱歌")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 1, "纯 other 回合 detector 必须启动"


class TestMemoryCompression:  # D11: C4
    def test_compress_trigger_and_preserve(self):
        """raw_history 超阈值 → should_compress；压缩后摘要生成且近期记录保留。"""
        from scenario_core import MemoryManager

        mm = MemoryManager(max_raw=2)
        for i in range(3):
            mm.add_record(f"输入{i}", "other", None, f"结果{i}", location="room_a")
        assert mm.should_compress(), "3 条记录 > max_raw=2 必须触发压缩建议"

        called = {}
        def fake_llm(prompt):
            called["prompt"] = prompt
            return "压缩摘要：玩家连续调查。"
        mm.compress(fake_llm)
        assert mm.summary == "压缩摘要：玩家连续调查。"
        assert len(mm.raw_history) <= 2, "压缩后原始记录必须裁减"
        assert "输入0" in called["prompt"], "被压缩的旧记录必须送入 LLM"


class TestTimeAdvance:  # D12: C1
    def test_time_delta_crosses_day_and_sets_context(self, monkeypatch):
        """大估时跨天 -> day 递增；narrative_hint 写入 time_context。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch, time_delta=1500)
        keeper._run_time_agent = lambda a, r: {
            "time_delta": 1500, "narrative_hint": "一天一夜过去了。"}
        game = make_game(keeper)

        d0 = world.clock.day
        r = run_turn(game, "长途跋涉")
        assert_player_turn_contract(r)
        assert world.clock.day == d0 + 1, "1500 分钟必须跨天"
        assert world.clock.time_context == "一天一夜过去了。"

    def test_time_delta_triggers_time_hooks(self, monkeypatch):
        """T7 三合一:keeper 时间推进必须走 world.advance_time 入口,
        MP 恢复与 timed 过期清除在真实回合流中生效(而非仅测试直调)。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch, time_delta=120)
        game = make_game(keeper)

        inv.derived.MP_MAX = 10
        inv.derived.MP = 0
        inv.timed_effects = [{"id": "V", "description": "帷幕",
                              "expire_at": world.clock.game_time + 60}]
        r = run_turn(game, "原地休整")
        assert_player_turn_contract(r)
        assert inv.derived.MP == 2, "回合推 120 分钟必须触发 MP 恢复钩子(1点/小时)"
        assert inv.timed_effects == [], "回合推 120 分钟必须清除已到期 timed 效果"


class TestChronicleWiring:  # U2: game_loop 每回合写编年史
    def test_turn_recorded_with_move(self, monkeypatch):
        """跑一回合 move → chronicle.events 含该回合，facts 位置已更新。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({
            "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                         "requirement": ""}]),
            "room_b": make_scene(),
        }, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        loc_before = world.current_location
        run_turn(game, "前往room_b", action_type="move", action_target="room_b")
        assert len(world.chronicle.events) == 1, "回合必须入编年史"
        e = world.chronicle.events[0]
        assert e["turn"] == 1 and "前往room_b" in e["input"]
        assert e.get("move") == "room_a→room_b", "移动轨迹必须入编年史"


class TestLuckDeclare:  # U9: LUCK 输入声明式消耗
    def test_burn_luck_applies_bonus(self, monkeypatch):
        """输入"烧5点幸运"→ LUCK -5，pending_luck_bonus 被当回合检定消费。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper
        from investigator.models import Skill

        interaction = {
            "id": "IT_LOCK", "entity_type": "interaction",
            "name": "撬锁", "scene": "room_a",
            "type": "锁匠", "requirement": "", "trigger": "尝试撬锁",
            "result": "开了。", "side_effects": [], "difficulty": "regular",
            "time_condition": [],
        }
        world = make_world({"room_a": make_scene(interactions=[interaction])}, "room_a")
        inv = _player(world)
        inv.stats.LUCK = 50
        # 「锁匠」归一为「偷窃」；须掌握该技能，检定才会真正掷骰消费 pending 加值
        inv.skills.append(Skill(name="偷窃", base_value=50))
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        run_turn(game, "烧5点幸运，然后撬锁")
        assert inv.stats.LUCK == 45, f"LUCK 必须扣 5，实际 {inv.stats.LUCK}"
        assert inv.pending_luck_bonus == 0, "加值必须已被检定消费"

    def test_burn_luck_insufficient_rejected(self, monkeypatch):
        """LUCK 余额不足 → 不扣减，记 warning。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.stats.LUCK = 3
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        run_turn(game, "烧10点幸运")
        assert inv.stats.LUCK == 3, "余额不足不得扣减"
        assert any("幸运" in w for w in keeper._warnings)


class TestUseTurnFlow:  # 统一资源层：use 大类接入
    def _setup(self, monkeypatch):
        from game.agents.keeper import Keeper
        from library.items import ItemLibrary
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.rules import calc_derived
        ilib = ItemLibrary(); ilib.load_core()
        slib = SpellLibrary(); slib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a",
                           item_library=ilib, spell_library=slib)
        from investigator.models import Stats
        inv = Investigator(name="测试员", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 20
        world.set_player(inv)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        return world, inv, keeper, game

    def test_preparse_shortcut_item_use(self, monkeypatch):
        from game_loop import run_turn
        world, inv, keeper, game = self._setup(monkeypatch)
        inv.item_manager.add("急救包", quantity=1)
        inv.derived.HP = 3
        r = run_turn(game, "我使用急救包")
        assert_player_turn_contract(r)
        assert not inv.item_manager.get("急救包") or \
            inv.item_manager.get("急救包").quantity == 0
        assert inv.derived.HP > 3
        assert r.status.name == "COMPLETED"

    def test_parse_use_entry_routes_to_material(self, monkeypatch):
        """pre-parse 确定性未命中（无动词直配），parse 返回 use 类型 -> LLM 兜底仍可解析。"""
        from game_loop import run_turn
        world, inv, keeper, game = self._setup(monkeypatch)
        inv.item_manager.add("急救包", quantity=1)
        keeper._parse = lambda raw: [{"type": "use", "text": raw}]
        def fake_llm(prompt, **kw):
            import json as _json
            return _json.dumps({"matched": True, "material": "急救包", "reason": ""},
                               ensure_ascii=False)
        keeper.use_parser.llm_call = fake_llm
        r = run_turn(game, "急救的那个包，快用")
        assert_player_turn_contract(r)
        assert not inv.item_manager.get("急救包") or \
            inv.item_manager.get("急救包").quantity == 0, \
            "LLM 兜底解析的 use 必须执行（物品被消耗）"

    def test_unresolved_use_becomes_creative(self, monkeypatch):
        from game_loop import run_turn
        world, inv, keeper, game = self._setup(monkeypatch)
        keeper._parse = lambda raw: [{"type": "use", "text": "用不知名的古怪装置"}]
        keeper.use_parser.llm_call = lambda p, **k: {"matched": False, "material": "", "reason": ""}

        class _FakeAuthor:
            time_pressure = None
            calls = 0
            def handle_request(self, request, turn_number=0):
                _FakeAuthor.calls += 1
                from game.messages import ModulePatch
                return ModulePatch(entities=[], scene_descriptions=[], justification="x")

        game["author"] = _FakeAuthor()
        from helpers import StubNarrator
        game["narrator"] = StubNarrator()
        r = run_turn(game, "用不知名的古怪装置")
        assert_player_turn_contract(r)
        assert _FakeAuthor.calls == 1, "未命中素材的 use 应转 creative 升 Author"


class TestGateFlavorExemption:
    """门控 flavor 豁免：氛围 AT 捎带不挡 creative；实质性动作仍硬挡。"""

    def _world_with_at(self):
        at = {
            "id": "AT_AMBIENT", "entity_type": "auto_trigger", "type": "无",
            "name": "灯泡闪烁", "requirement": "", "trigger": "进入房间",
            "result": "灯泡滋滋作响。", "side_effects": [],
            "graded_result": None, "difficulty": "None",
            "scene": "room_a", "time_condition": [],
        }
        return make_world({"room_a": make_scene(auto_triggers=[at])}, "room_a")

    def test_at_plus_creative_still_escalates(self, monkeypatch):
        from game.agents.keeper import Keeper

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        world = self._world_with_at()
        _p = _player(world)
        keeper = Keeper(world)
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "auto_trigger", "id": "AT_AMBIENT"},
                                        {"type": "other", "impact": "creative",
                                         "text": "在墙上刻字求救"}]])
        class _FakeAuthor:
            time_pressure = None
        from helpers import StubNarrator
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "在墙上刻字求救")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 1, "AT 捎带 + creative：实质性动作缺席，detector 必须启动（escalation C/E 修复）"

    def test_interaction_plus_creative_suppressed(self, monkeypatch):
        from game.agents.keeper import Keeper
        inter = {
            "id": "IT_KEY", "entity_type": "interaction", "name": "翻砖",
            "scene": "room_a", "type": "None", "requirement": "",
            "trigger": "翻开松砖", "result": "找到钥匙。",
            "side_effects": [], "difficulty": "None", "time_condition": [],
        }
        world = make_world({"room_a": make_scene(interactions=[inter])}, "room_a")
        _p = _player(world)
        keeper = Keeper(world)

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_KEY"},
                                        {"type": "other", "impact": "creative",
                                         "text": "顺便大喊救命"}]])
        class _FakeAuthor:
            time_pressure = None
        from helpers import StubNarrator
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "翻砖，顺便大喊救命")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 0, "实质性实体 + creative：维持硬挡（防递归丢帧）"

    def test_flavor_never_triggers_detector(self, monkeypatch):
        from game.agents.keeper import Keeper
        world = self._world_with_at()
        _p = _player(world)
        keeper = Keeper(world)

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "other", "impact": "flavor",
                                         "text": "哼着歌"}]])
        class _FakeAuthor:
            time_pressure = None
        from helpers import StubNarrator
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "哼着歌走两步")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 0, "flavor 永不触发 detector"


class TestRequirementItem:  # 统一资源层：item: 硬条件
    def _world(self):
        inter = {
            "id": "IT_DOOR", "entity_type": "interaction", "name": "开锁",
            "scene": "room_a", "type": "None",
            "requirement": "item:黄铜钥匙", "trigger": "用钥匙开门",
            "result": "门开了。", "side_effects": [],
            "difficulty": "None", "time_condition": [],
        }
        return make_world({"room_a": make_scene(interactions=[inter])}, "room_a")

    def test_item_gate_blocks_and_allows(self, monkeypatch):
        from game.agents.keeper import Keeper
        from game_loop import run_turn
        world = self._world()
        inv = _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_DOOR"}]])
        game = make_game(keeper)

        r1 = run_turn(game, "用钥匙开门")     # 无钥匙
        assert_player_turn_contract(r1)
        assert not world.is_entity_completed("IT_DOOR")
        assert "黄铜钥匙" in r1.brief, "无钥匙时必须给出需要物品的失败信息"

        inv.item_manager.add("黄铜钥匙", quantity=1)
        r2 = run_turn(game, "用钥匙开门")     # 有钥匙
        assert_player_turn_contract(r2)
        assert world.is_entity_completed("IT_DOOR")


class TestChronicleSpellFacts:  # 统一资源层：编年史 + 快照字段
    def test_player_line_contains_spells_and_mp_max(self, monkeypatch):
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.known_spells = ["HEART_ARREST"]
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        from game_loop import run_turn
        run_turn(game, "四处看看")
        rendered = world.chronicle.render_for_author(world)
        assert "HEART_ARREST" in rendered, "编年史玩家行必须含已知法术"
        assert "MP" in rendered

    def test_snapshot_has_mp_max_and_spells(self):
        from investigator import Investigator
        from investigator.rules import calc_derived
        from investigator.models import Stats
        inv = Investigator(name="快照", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        inv.known_spells = ["LIFE_DETECTION"]
        snap = inv.build_snapshot()
        assert snap.get("mp_max") == inv.derived.MP_MAX
        assert snap.get("known_spells") == ["LIFE_DETECTION"]


class TestTimedAndCombatEffectsE2E:  # T13: spec §8 e2e 三场景
    """2026-08-21 spec §8 e2e:帷幕 timed 入档+过期、石肤战斗减伤、支配控制轮次。

    帷幕走完整 keeper 回合(UseParser 确定性短路 -> judge.execute_material ->
    timed 挂载 -> advance_time 过期);石肤/支配从战斗入口(真实 core 法术库 +
    EnemyLibrary 实例 + CombatInit -> _init_combat)走 cast -> effect 原子 ->
    敌方结算链路。全程真实产品代码,骰点/对抗检定 monkeypatch 固定保确定性。
    """

    def _spell_world(self, known_spells, enemy_library=None):
        """真实 core 法术库世界 + 满 HP/MP 调查员(POW 技能 200:战斗施法必过)。"""
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.models import Stats, Skill
        from investigator.rules import calc_derived

        slib = SpellLibrary(); slib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a",
                           spell_library=slib, enemy_library=enemy_library)
        inv = Investigator(name="施法者", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        inv.derived.HP = 20; inv.derived.HP_MAX = 20
        inv.derived.MP = 20; inv.derived.MP_MAX = 20
        inv.skills.append(Skill(name="POW", base_value=50, value=200, category="属性"))
        inv.known_spells = list(known_spells)
        world.set_player(inv)
        return world, inv, slib

    @staticmethod
    def _fresh_state(cs, inv, enemy):
        """CombatInit -> _init_combat:同一敌人/玩家的干净战斗 state(群组展开副本)。"""
        from game.messages import CombatInit
        ci = CombatInit(enemies=[enemy], player=inv, scene="room_a",
                        initiative_context="测试战斗")
        return cs._init_combat(ci)

    def _combat_env(self, known_spells):
        """战斗场景:必中敌人(DEX/POW=200)+ CombatSystem(spell_lib, world)+ 展开后 state。"""
        from library.enemies import EnemyLibrary, LibraryEnemy
        from game.combat import CombatSystem

        elib = EnemyLibrary()
        elib._enemies["石壳傀儡"] = LibraryEnemy.from_dict({
            "name": "石壳傀儡", "type": "怪物",
            "attributes": {"STR": 50, "SIZ": 50, "DEX": 200, "POW": 200},
            "armor": "", "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        world, inv, slib = self._spell_world(known_spells, enemy_library=elib)
        enemy = world.enemies.spawn("石壳傀儡", "room_a", 1)
        cs = CombatSystem(spell_lib=slib, world=world)
        return cs, self._fresh_state(cs, inv, enemy), inv, world, enemy

    def test_silence_veil_timed_mounts_and_expires(self, monkeypatch):
        """静默帷幕:keeper 回合"施放静默帷幕" -> timed 入档+MP 扣 5+叙事可见;
        advance_time(10) 推满时长后过期清除。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world, inv, _slib = self._spell_world(["SILENCE_VEIL"])
        # 探索侧检定走 check_skill(POW 属性路径有 96+ 大失败,stub 保确定性)
        inv.check_skill = lambda skill, diff="regular": (
            True, f"{skill}检定：D100=10/60", "regular")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        base = world.clock.game_time
        r = run_turn(game, "施放静默帷幕")
        assert_player_turn_contract(r)
        assert r.status.name == "COMPLETED"
        # timed 入档:id/描述/时效(施放时刻 + 10 分钟)
        assert len(inv.timed_effects) == 1, \
            f"timed 原子必须入档,实际 {inv.timed_effects}"
        te = inv.timed_effects[0]
        assert te["id"] == "SILENCE_VEIL"
        assert te["description"] == "无形的帷幕吞掉帷幕内的一切声响"
        assert te["expire_at"] == base + 10, \
            f"expire_at 应为施放时刻+10,实际 {te['expire_at']}(base={base})"
        # MP 扣 5(20 -> 15)
        assert inv.derived.MP == 15, f"MP 应扣 5,实际 {inv.derived.MP}"
        # 回合叙事交付 on_success 槽文本
        assert "世界忽然安静下来" in r.narrative, \
            f"叙事必须含帷幕生效描述: {r.narrative[:120]}"
        # advance_time 过期:推满 10 分钟 -> timed 清空
        world.advance_time(10)
        assert inv.timed_effects == [], \
            f"推满时长后 timed 必须过期清除,实际 {inv.timed_effects}"

    def test_stone_skin_reduces_damage_in_combat(self, monkeypatch):
        """石肤术:战斗施法挂 buff+timed;敌方攻击伤害 7-3=4,对照无 buff 全额 7。"""
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 7)

        cs, state, inv, world, enemy = self._combat_env(["STONE_SKIN"])
        # 施法:POW 技能 200 必过 -> buff 挂 state + timed 挂 world.player
        act = cs._resolve_player_action(state, inv, "cast_STONE_SKIN", "")
        assert act.success, f"POW 200 施法必过: {act.narrative}"
        assert state.temporary_effects == [
            {"id": "STONE_SKIN", "reduce": 3, "rounds": 3}], \
            f"buff 原子挂 state.temporary_effects: {state.temporary_effects}"
        assert "皮肤紧绷如石" in act.narrative, "on_text 拼进施法叙事"
        assert inv.derived.MP == 14, \
            f"cost mp=6 已扣(20->14),实际 {inv.derived.MP}"
        assert any(t["id"] == "STONE_SKIN"
                   and t["expire_at"] == world.clock.game_time + 30
                   for t in inv.timed_effects), \
            f"timed 原子挂 world.player(30 分钟): {inv.timed_effects}"
        # 敌方攻击(必中 DEX/POW=200,伤害固定 7):石肤减免 3 -> 扣 4
        act_e = cs._resolve_enemy_action(state, state.enemies[0], inv)
        assert act_e.success and act_e.damage == 4, \
            f"石肤减免后伤害应为 7-3=4,实际 {act_e.damage}"
        assert state.player_hp == 20 - 4, "扣血按减免后伤害"
        # 对照:同一敌人/玩家干净 state(无 buff)全额 7
        state_c = self._fresh_state(cs, inv, enemy)
        act_c = cs._resolve_enemy_action(state_c, state_c.enemies[0], inv)
        assert act_c.success and act_c.damage == 7, "无 buff 全额伤害"
        assert state_c.player_hp == 20 - 7
        assert act_c.damage - act_e.damage == 3, "差额恰为 reduce=3"

    def test_dominate_skips_enemy_action(self, monkeypatch):
        """支配:对抗必胜 -> 敌 controlled_rounds=2 跳过行动不掉血;
        轮末递减两次后恢复行动(必中全额伤害)。"""
        import game.combat as combat_mod
        import investigator.rules as rules_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 7)
        monkeypatch.setattr(
            rules_mod, "opposed_check",
            lambda a, d: ("win", "对抗 D100: 攻方 5/200(extreme) vs 守方 90/200(failure)"))

        cs, state, inv, _world, _enemy = self._combat_env(["DOMINATE"])
        target = state.enemies[0]
        # 施法:对抗检定 monkeypatch 必胜 -> control 写 target.controlled_rounds=2
        act = cs._resolve_player_action(state, inv, "cast_DOMINATE",
                                        target.instance_id)
        assert act.success
        assert "无法动弹" in act.narrative, f"施法叙事须含控制描述: {act.narrative}"
        assert target.controlled_rounds == 2, \
            f"control 原子写 controlled_rounds=2,实际 {target.controlled_rounds}"
        assert inv.derived.MP == 10, \
            f"cost mp=10 已扣(20->10),实际 {inv.derived.MP}"
        assert inv.derived.SAN == 59, \
            f"cost san=1 已扣(60->59),实际 {inv.derived.SAN}"
        # 被支配敌方跳过行动:不掷骰不伤害
        act_e = cs._resolve_enemy_action(state, target, inv)
        assert act_e.success is False, "被支配敌人无攻击检定"
        assert "无法动弹" in act_e.narrative and "石壳傀儡" in act_e.narrative
        assert act_e.damage == 0
        assert state.player_hp == 20, "被支配期间玩家不掉血"
        # 轮末递减:2->1 仍跳过;再 1->0 恢复行动(必中全额 7)
        cs._tick_temporary_effects(state)
        assert target.controlled_rounds == 1
        act_e2 = cs._resolve_enemy_action(state, target, inv)
        assert "无法动弹" in act_e2.narrative, "控制期内(剩 1 轮)仍须跳过"
        cs._tick_temporary_effects(state)
        assert target.controlled_rounds == 0
        act_e3 = cs._resolve_enemy_action(state, target, inv)
        assert "无法动弹" not in act_e3.narrative, "归零后恢复正常行动路径"
        assert act_e3.success and act_e3.damage == 7, "恢复后必中全额伤害"
        assert state.player_hp == 20 - 7


class TestSanCheckE2E:  # 遭遇 SAN check 通路 e2e(2026-08-26 接线)
    """带 san_loss 库敌人走完整回合:目睹 check 进首轮叙事,SAN 扣减写回。

    真实 EnemyLibrary 实例(san_loss 经 spawn 桥接进 EnemyInstance)+
    CombatInit -> _init_combat(目睹 check)-> run_single_round(完整回合,
    san_log 渲染进 round_narrative)-> 写回链路(game_loop/run_game 同语义)。
    """

    def test_combat_with_san_loss_enemy(self):
        from library.enemies import EnemyLibrary, LibraryEnemy
        from game.combat import CombatSystem
        from game.messages import CombatInit

        elib = EnemyLibrary()
        elib._enemies["深渊幼体"] = LibraryEnemy.from_dict({
            "name": "深渊幼体", "type": "怪物",
            "attributes": {"STR": 50, "SIZ": 50, "DEX": 10, "POW": 10},
            "armor": "", "attacks": [], "special_abilities": [],
            "san_loss": "1/1D6",
            "description": "", "combat_behavior": "",
        })
        world = make_world({"room_a": make_scene()}, "room_a",
                           enemy_library=elib)
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        inv = Investigator(name="调查员", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        world.set_player(inv)
        san_before = inv.derived.SAN
        enemy = world.enemies.spawn("深渊幼体", "room_a", 1)

        cs = CombatSystem()
        ci = CombatInit(enemies=[enemy], player=inv, scene="room_a",
                        initiative_context="遭遇")
        state = cs._init_combat(ci)
        result = cs.run_single_round(ci, state, "punch",
                                     [state.enemies[0].instance_id])

        # 1) 首轮结果文本含目睹 SAN check(无论成功/失败组,文案均带"理智检定")
        assert "理智检定" in result["round_narrative"], \
            f"首轮叙事必须含目睹 SAN check: {result['round_narrative']}"
        # 2) 写回链路同 game_loop/run_game 语义,战后 SAN <= 战前(宽断言)
        inv.derived.SAN = max(0, result["player_san"])
        assert inv.derived.SAN <= san_before, \
            f"遭遇目睹后 SAN 不得回升: {san_before} -> {inv.derived.SAN}"
        # 渲染一次性:san_log 清空,不随下一轮重复
        assert state.san_log == []


class TestTimeFlagHygiene:
    """ISSUES B2:advance_time 清旧 day:/time: flag,防 prompt/存档累积。"""

    def test_stale_day_time_flags_cleared(self):
        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        world.advance_time(6 * 60)   # game_time=360: day 0, hour 6(早晨)
        assert "day:0" in world.runtime_state
        assert "time:早晨" in world.runtime_state

        world.advance_time(18 * 60)  # game_time=1440: day 1, hour 0(凌晨)
        assert "day:1" in world.runtime_state
        assert "day:0" not in world.runtime_state
        # time flag 只保留当前时段
        tods = [k for k in world.runtime_state if k.startswith("time:")]
        assert tods == ["time:凌晨"]

        world.advance_time(8 * 60)    # game_time=1920: day 1, hour 8(白天)
        assert "time:白天" in world.runtime_state
        assert "time:凌晨" not in world.runtime_state

        # build_snapshot completed 列表不再累积旧 day flag
        snap = world.build_snapshot()
        completed = snap["runtime"]["completed"]
        assert "day:0" not in completed and "day:1" in completed


class TestAutoTriggerTimeCondition:
    def _at(self, times):
        import json
        return {
            "id": "AT_DAWN", "entity_type": "auto_trigger",
            "name": "凌晨低语", "scene": "room_a",
            "type": "None", "requirement": "", "trigger": "time",
            "result": "黑暗中传来低语。", "side_effects": [],
            "difficulty": "None",
            "time_condition": json.dumps([{"day": "ALL", "times": times}]),
        }

    def test_dawn_at_fires_only_at_lingchen(self):
        from game.judge import Judge
        from game.clock import GameClock

        day_world = make_world({"room_a": make_scene(
            auto_triggers=[self._at(["凌晨"])])}, "room_a")
        day_world.clock = GameClock(start_time=12 * 60)  # 白天
        assert Judge(day_world).check_auto_triggers() == []

        dawn_world = make_world({"room_a": make_scene(
            auto_triggers=[self._at(["凌晨"])])}, "room_a")
        dawn_world.clock = GameClock(start_time=60)  # 01:00 凌晨
        out = Judge(dawn_world).check_auto_triggers()
        assert len(out) == 1 and out[0].success

    def test_empty_time_condition_still_fires(self):
        from game.judge import Judge
        world = make_world({"room_a": make_scene(
            auto_triggers=[{
                "id": "AT_ALWAYS", "entity_type": "auto_trigger",
                "name": "常驻", "scene": "room_a", "type": "None",
                "requirement": "", "trigger": "enter",
                "result": "灯在闪。", "side_effects": [],
                "difficulty": "None", "time_condition": [],
            }])}, "room_a")
        out = Judge(world).check_auto_triggers()
        assert len(out) == 1

    def test_list_time_condition_blocked_in_daytime(self):
        from game.judge import Judge
        from game.clock import GameClock

        world = make_world({"room_a": make_scene(
            auto_triggers=[{
                "id": "AT_DAWN", "entity_type": "auto_trigger",
                "name": "凌晨低语", "scene": "room_a",
                "type": "None", "requirement": "", "trigger": "time",
                "result": "黑暗中传来低语。", "side_effects": [],
                "difficulty": "None",
                "time_condition": [{"day": "ALL", "times": ["凌晨"]}],
            }])}, "room_a")
        world.clock = GameClock(start_time=12 * 60)
        assert Judge(world).check_auto_triggers() == []


class TestSanSeenPersistence:  # F9 入档
    def test_san_seen_sources_roundtrip(self):
        """san_seen_sources 经 to_dict/from_dict 回环保持。"""
        from scenario_core import DirectedGraph, ScenarioWorld
        graph = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world = ScenarioWorld(graph, start_node="room_a")
        world.san_seen_sources = {"深潜者", "食尸鬼"}
        data = world.to_dict()
        graph2 = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world2 = ScenarioWorld.from_dict(data, graph2)
        assert world2.san_seen_sources == {"深潜者", "食尸鬼"}

    def test_san_seen_sources_default_empty_on_old_save(self):
        """旧档无该字段 -> 默认空集,不炸。"""
        from scenario_core import DirectedGraph, ScenarioWorld
        graph = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world = ScenarioWorld.from_dict({"current_location": "room_a"}, graph)
        assert world.san_seen_sources == set()


class TestAuthorRecursion:
    """W6：作者门迁至 B 尾部后的递归语义锁定。"""

    def _recursion_world(self):
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, start_node="room_a")
        from investigator import Investigator
        world.set_player(Investigator(name="测试员", age=25, gender="男"))
        return world

    def _accept_author(self):
        from types import SimpleNamespace
        from game.messages import ModulePatch
        patch = ModulePatch(
            entities=[{"id": "NEW1", "entity_type": "interaction", "name": "墙壁回音",
                       "scene": "room_a", "type": "无", "requirement": "",
                       "trigger": "听回音", "result": "墙回应了你。",
                       "side_effects": [], "difficulty": "None"}],
            scene_descriptions={}, justification="作者补充了墙壁回音")
        return SimpleNamespace(time_pressure=None, l3_data={},
                               handle_request=lambda req, turn: patch)

    def _stub_creative_other(self, keeper, monkeypatch, time_delta=0,
                             combat_entry=None):
        from helpers import stub_keeper_llm
        stub_keeper_llm(keeper, monkeypatch, time_delta=time_delta,
                        combat_entry=combat_entry,
                        parse_results=[[{"type": "other", "impact": "creative",
                                         "text": "对着墙打一套拳"}]])
        from types import SimpleNamespace
        keeper.intent_detector.detect = lambda *a, **k: SimpleNamespace(
            needs_author=True, intent="练拳", reasoning="r")

    def test_recursion_advances_time_once(self, monkeypatch):
        """递归路径 TA 只运行一次（旧行为：外帧+内帧双涨）。"""
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch, time_delta=60)
        t0 = world.clock.game_time
        keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                            author=self._accept_author())
        assert world.clock.game_time - t0 == 60, (
            f"期望推进 60（TA 单次），实际 {world.clock.game_time - t0}")

    def test_recursion_runs_enrich_once(self, monkeypatch):
        """递归路径 enrich 只运行一次（旧行为：外帧白跑一次）。"""
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        calls = {"n": 0}
        def counting_enrich(e, r):
            calls["n"] += 1
            return {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._enrich = counting_enrich
        keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                            author=self._accept_author())
        assert calls["n"] == 1, f"期望 enrich 1 次，实际 {calls['n']}"

    def test_author_rejection_outcome_present(self, monkeypatch):
        """作者拒绝 → 拒绝信息进 outcomes（新旧行为一致，回归锁）。"""
        from types import SimpleNamespace
        from game.agents.keeper import Keeper
        from game.messages import TurnInput, ModulePatch
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        author = SimpleNamespace(
            time_pressure=None, l3_data={},
            handle_request=lambda req, turn: ModulePatch(
                entities=[], scene_descriptions={},
                justification="REJECTED: 不合理"))
        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=author)
        assert any("你尝试了" in o.message for o in result.brief.action_outcomes)

    def test_escalation_depth_guard(self, monkeypatch):
        """intent 每次不同（绕过冷却）→ 深度守卫触发 deterministic-only。"""
        from types import SimpleNamespace
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        counter = {"n": 0}
        def detect(*a, **k):
            counter["n"] += 1
            return SimpleNamespace(needs_author=True,
                                   intent=f"练拳{counter['n']}", reasoning="r")
        keeper.intent_detector.detect = detect
        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=self._accept_author())
        assert result.brief is not None
        assert any("没有什么特别的事情发生" in o.message
                   for o in result.brief.action_outcomes)

    def test_recursion_combat_init_survives_restart(self, monkeypatch):
        """被弃帧零遭遇副作用（直接断言，替代 enrich 次数代理）：
        enter_combat 仅在发货帧执行一次，且 combat_init 随结果返回。
        旧行为：外帧先 enter_combat → _combat_active=True → 内帧跳过
        战斗判定 → combat_init 被吞（敌人进了战斗态但玩家收不到）。"""
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        lib = _enemy_lib_with()
        world = make_world({"room_a": make_scene()}, start_node="room_a",
                           enemy_library=lib)
        _player(world)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        keeper = Keeper(world)
        self._stub_creative_other(
            keeper, monkeypatch,
            combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                          "reasoning": "遭遇"})
        calls = {"n": 0}
        orig_enter = world.enemies.enter_combat
        def counting_enter(iids):
            calls["n"] += 1
            return orig_enter(iids)
        world.enemies.enter_combat = counting_enter

        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=self._accept_author())
        assert calls["n"] == 1, \
            f"enter_combat 应只在发货帧执行一次，实际 {calls['n']}"
        assert result.combat_init is not None, \
            "递归后 combat_init 必须随发货帧返回（旧行为被吞）"
        assert result.combat_init.enemies, "combat_init 必须携带敌人"

    def test_recursion_boss_accounting_exactly_once(self, monkeypatch, tmp_path):
        """被弃帧零 Boss 记账：mark_spawned/set_active 恰好一次，不重复造实例。
        （新旧行为一致的回归锁——把 deferral 保证从隐式变显式）"""
        import json as _json
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        from library.bosses import BossLibrary
        boss_data = {"测试魔像": {
            "type": "神话造物",
            "attributes": {"STR": 120, "CON": 140, "SIZ": 130, "DEX": 30, "POW": 80},
            "armor": "4点石壳", "attacks": [], "special_abilities": [],
            "san_loss": "1/1D6", "description": "测试用",
            "boss_mechanics": "两阶段测试",
            "flags": ["boss"], "multi_attack": 1,
            "phases": [{"trigger": "hp_below_pct:0.5", "name": "崩解",
                        "overrides": {"multi_attack": 2},
                        "description": "外壳碎裂"}],
        }}
        p = tmp_path / "bosses.json"
        p.write_text(_json.dumps(boss_data, ensure_ascii=False), encoding="utf-8")
        bl = BossLibrary(str(p))
        enc = {"id": "BOSS_T1", "type": "boss_encounter", "engage_type": "at",
               "boss_ref": "测试魔像", "scene": "room_a",
               "requirements": "", "description": "测试遭遇"}
        world = make_world({"room_a": make_scene()}, "room_a",
                           enemy_library=_enemy_lib_with(), boss_library=bl,
                           boss_encounters=[enc])
        _player(world)
        inst = world.bosses.spawn_instance(enc)
        world.enemies.register(inst)
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)

        calls = {"mark": 0, "active": 0}
        orig_mark = world.bosses.mark_spawned
        orig_active = world.bosses.set_active
        def counting_mark(boss_id):
            calls["mark"] += 1
            return orig_mark(boss_id)
        def counting_active(boss_id):
            calls["active"] += 1
            return orig_active(boss_id)
        world.bosses.mark_spawned = counting_mark
        world.bosses.set_active = counting_active

        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=self._accept_author())
        assert result.combat_init is not None, "Boss 战必须随发货帧返回"
        assert calls["mark"] == 1, \
            f"mark_spawned 应恰好一次，实际 {calls['mark']}"
        assert calls["active"] == 1, \
            f"set_active 应恰好一次，实际 {calls['active']}"
        assert world.bosses.has_spawned("BOSS_T1")
        assert len(world.enemies._instances) == 1, "不得产生重复 Boss 实例"


class TestSaveLoadContinue:  # 统一存档批回归：turn→save→load→turn
    def test_save_load_then_turn_continues(self, monkeypatch, tmp_path):
        """读档后 stub 管线继续跑通；F14 checked 随 player_snapshot 持久化。"""
        from game_loop import run_turn, save_game, load_game
        from game.messages import TurnStatus
        from game.agents.keeper import Keeper
        from investigator.models import Skill
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.skills.append(Skill(name="侦查", base_value=50))
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        monkeypatch.setattr("investigator.models.random.randint",
                            lambda a, b: 30)

        r1 = run_turn(game, "搜索", action_type="search")
        assert_player_turn_contract(r1)
        assert r1.status == TurnStatus.COMPLETED, f"status={r1.status}"
        assert inv.get_skill("侦查").checked is True, "搜索成功必须置 checked"

        path = str(tmp_path / "save.json")
        save_game(game, path)
        old_world = keeper.world
        load_game(game, path)

        assert keeper.world is not old_world, "load_game 必须重绑 world"
        assert keeper.world.current_location == "room_a"
        restored = keeper.world.player
        assert restored is not None, "player_snapshot 必须恢复"
        assert restored.get_skill("侦查").checked is True, \
            "checked 必须随 player_snapshot 持久化"

        r2 = run_turn(game, "继续探索")
        assert_player_turn_contract(r2)
        assert r2.status == TurnStatus.COMPLETED, \
            f"读档后回合应正常完成，实际 status={r2.status}"
