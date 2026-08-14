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


class TestWeaponPickupRules:
    """R1 直接拾取通路 + R2 offer 门严格是/否匹配。"""

    def _setup(self, monkeypatch):
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
                        parse_results=[[{"type": "other", "text": "随便"}]])
        game = make_game(keeper)
        return run_turn, world, inv, keeper, game

    def test_offer_gate_fuzzy_yes_rejected(self, monkeypatch):
        """R2：含"是"的非回答输入不触发拾取，offer 作废，回合正常推进。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        keeper._weapon_offer = [{"weapon_ref": "手枪", "scene": "room_a"}]
        r = run_turn(game, "别怕，我是来帮你的")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons), "模糊输入不得触发拾取"
        assert keeper._weapon_offer is None, "非回答输入必须作废 offer"
        assert world.scene_weapons.get("room_a"), "作废≠拾取：武器必须留在场景"
        assert "你拾起了" not in r.narrative and "你忽略了" not in r.narrative

    def test_offer_gate_exact_yes_grants(self, monkeypatch):
        """「是。」（容忍标点）→ 拾取。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        keeper._weapon_offer = [{"weapon_ref": "手枪", "scene": "room_a"}]
        r = run_turn(game, "是。")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons)
        assert not world.scene_weapons.get("room_a")

    def test_offer_gate_exact_no_declines(self, monkeypatch):
        """「否」→ 拒绝，武器留场景，offer 清空。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        keeper._weapon_offer = [{"weapon_ref": "手枪", "scene": "room_a"}]
        r = run_turn(game, "否")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons)
        assert world.scene_weapons.get("room_a"), "拒绝后武器必须留在场景"
        assert keeper._weapon_offer is None

    def test_direct_pickup_by_name(self, monkeypatch):
        """R1：无 offer 时明说「捡+武器名」直接入包。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "我捡起手枪")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons), "直接拾取必须入包"
        assert not world.scene_weapons.get("room_a"), "场景武器必须移除"

    def test_direct_pickup_unnamed_single_weapon(self, monkeypatch):
        """场景仅一件可拾武器时，未点名也直接拾取。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "把地上的武器捡起来")
        assert_player_turn_contract(r)
        assert any(w.name == "手枪" for w in inv.weapons)

    def test_direct_pickup_negative_ignored(self, monkeypatch):
        """含否定词的拾取表述不触发直接拾取。"""
        run_turn, world, inv, keeper, game = self._setup(monkeypatch)
        r = run_turn(game, "我才不捡那把手枪")
        assert_player_turn_contract(r)
        assert not any(w.name == "手枪" for w in inv.weapons)
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
        """大估时跨天 → day 递增；narrative_hint 写入 time_context。"""
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
