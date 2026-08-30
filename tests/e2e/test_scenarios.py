"""步骤 2：手写固定输入场景（真实 LLM）。

硬断言锁定结构/契约，宽断言处理 LLM 内容（存在性/非空/合法值域）。
每场景 retry 一次（pytest-rerunfailures 未安装，手写 retry_once 装饰器）。
日志落盘 data/debug/e2e/<timestamp>/<scenario>/，retry 另存 <scenario>_retry1/。

单点 stub 说明（命中的调用返回固定响应，其余全部真实 API）：
- S4/S5: combat_entry stub 为 enter_combat=True —— standoff 播种完全依赖该 LLM 判定，
  真实 LLM 可能不判进入战斗导致场景无法成立；standoff 之后的行为仍由真实 LLM 驱动。
- S5: standoff_match stub 为 matched=False —— 战斗路径需确定性进入战斗；
  match 判定与回避语义的真实覆盖见 S4。
"""
import functools
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

import pytest

from helpers import (load_env, make_scene, make_world,
                     assert_player_turn_contract, setup_llm_logging)

load_env()

pytestmark = pytest.mark.real_llm

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_ROOT = os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'debug', 'e2e', TIMESTAMP)

_ATTEMPTS = {}


def _scenario_log_dir(name):
    n = _ATTEMPTS.get(name, 0) + 1
    _ATTEMPTS[name] = n
    d = os.path.join(LOG_ROOT, name if n == 1 else f"{name}_retry{n - 1}")
    os.makedirs(d, exist_ok=True)
    return d


def retry_once(test_fn):
    """flaky 场景 retry-once：失败后整体重跑（世界在测试体内重建，状态干净）。"""
    @functools.wraps(test_fn)
    def wrapper(*args, **kwargs):
        try:
            return test_fn(*args, **kwargs)
        except Exception as e:
            print(f"\n[retry_once] 首次失败（{type(e).__name__}: {e}），重试一次...")
            return test_fn(*args, **kwargs)
    return wrapper


def _player(world, name="测试员", skills=None):
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name=name, age=25, gender="男")
    for sn, val in (skills or {}).items():
        inv.skills.append(Skill(name=sn, base_value=val))
    world.set_player(inv)
    return inv


def _l1(*scene_names):
    return {
        s: {
            "description": f"你身处{s}。空气潮湿而沉闷，昏黄的光线勉强照亮四周，"
                           f"阴影在墙角缓缓蠕动，远处隐约传来低沉的滴水声。",
            "atmosphere": "压抑、潮湿，仿佛有什么东西在暗处注视着你。",
            "perceptible": [],
            "ambient_hints": [],
            "npc_appearances": [],
        }
        for s in scene_names
    }


def _real_game(world, l1):
    """真实 Narrator（需要 l1_data）；author=None 避免 detector/author 分支。"""
    from game.agents.keeper import Keeper
    from game.agents.narrator import Narrator
    keeper = Keeper(world)
    keeper.narrator_l1 = l1
    return {"keeper": keeper, "narrator": Narrator(l1), "author": None}


def _deep_one_world(hostile_only=False):
    """room_a 有一只深潜者；avoidable 除非 hostile_only。"""
    from library.enemies import EnemyLibrary, LibraryEnemy
    lib = EnemyLibrary()
    lib._enemies["深潜者"] = LibraryEnemy.from_dict({
        "name": "深潜者", "type": "怪物",
        "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
        "attacks": [], "special_abilities": [], "san_loss": "0",
        "description": "来自深海的鱼头人身怪物", "combat_behavior": "",
    })
    world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
    inv = _player(world, skills={
        "潜行": 95, "话术": 95, "魅惑": 95, "说服": 95, "恐吓": 95, "斗殴": 95})
    inst = world.enemies.spawn("深潜者", "room_a", 1)
    if not hostile_only:
        inst.flags = ["avoidable"]
    return world, inv, inst


class TestS1NormalTurn:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_normal_action_turn(self):
        """S1：普通行动回合——全真实 LLM（pre_parse/parse/enrich/time_agent/narrator）。"""
        from game_loop import run_turn
        from game.messages import TurnStatus
        log_dir = _scenario_log_dir("s1_normal_turn")
        stop = setup_llm_logging(log_dir)
        try:
            world = make_world({"room_a": make_scene()}, "room_a")
            _player(world)
            game = _real_game(world, _l1("room_a"))

            r = run_turn(game, "我环顾四周，仔细观察这个房间的每个角落")
            assert_player_turn_contract(r)
            assert r.status == TurnStatus.COMPLETED, f"status={r.status}"
            assert r.brief, "brief 必须非空"
            assert r.narrative and len(r.narrative) > 20, \
                f"宽断言：narrative 非空且长度>20，实际 {len(r.narrative)}: {r.narrative[:80]}"
        finally:
            stop()


class TestS2AmbiguousClarify:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_ambiguous_then_clarified(self):
        """S2：模糊输入澄清——disambiguate 真实 LLM 判 ambiguous；澄清后回合推进。"""
        from game_loop import run_turn
        from game.messages import TurnStatus
        log_dir = _scenario_log_dir("s2_ambiguous_clarify")
        stop = setup_llm_logging(log_dir)
        try:
            world = make_world({"room_a": make_scene()}, "room_a")
            _player(world)
            game = _real_game(world, _l1("room_a"))

            r1 = run_turn(game, "那个")
            assert_player_turn_contract(r1)
            assert r1.status == TurnStatus.SUSPENDED, \
                f"宽断言：「那个」应被判 ambiguous，实际 status={r1.status}"
            assert r1.pending_interaction.kind == "clarify"

            r2 = run_turn(game, "我想仔细观察这个房间")
            assert_player_turn_contract(r2)
            assert r2.status == TurnStatus.COMPLETED, \
                f"澄清后回合应推进为 COMPLETED，实际 {r2.status}"
        finally:
            stop()


class TestS3WeaponOffer:
    @retry_once
    def test_search_offer_then_pickup(self):
        """S3：搜索→武器 offer→拾取。action_type=search 跳过 parse（offer 闭环是
        硬断言目标，输入序列保守化）；enrich/time_agent/narrator 仍真实。"""
        from game_loop import run_turn
        from game.side_effects import SceneWeapon
        from library.weapons import WeaponLibrary, LibraryWeapon
        log_dir = _scenario_log_dir("s3_weapon_offer")
        stop = setup_llm_logging(log_dir)
        try:
            wlib = WeaponLibrary()
            wlib._weapons["手枪"] = LibraryWeapon(name="手枪", skill_name="射击(手枪)")
            world = make_world({"room_a": make_scene()}, "room_a",
                               weapon_library=wlib)
            inv = _player(world)
            world.scene_weapons["room_a"] = [
                SceneWeapon(weapon_ref="手枪", scene="room_a", quantity=1)]
            game = _real_game(world, _l1("room_a"))
            keeper = game["keeper"]

            r1 = run_turn(game, "搜索", action_type="search")
            assert_player_turn_contract(r1)
            assert r1.pending_interaction is not None, "场景武器存在时搜索必须挂起 offer"
            assert r1.pending_interaction.kind == "weapon_offer"

            r2 = run_turn(game, "是")
            assert_player_turn_contract(r2)
            assert any(w.name == "手枪" for w in inv.weapons), "武器必须入包"
            assert not world.scene_weapons.get("room_a"), "场景武器必须移除"
            assert keeper._weapon_offer is None, "offer 应答后必须清空"
        finally:
            stop()


class TestS4StandoffAvoid:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_standoff_then_avoid(self):
        """S4：standoff 回避。combat_entry 单点 stub（见模块 docstring）；
        standoff_match/D100/enrich/narrator 真实。玩家回避技能 95 提高回避成功率。"""
        from game_loop import run_turn
        log_dir = _scenario_log_dir("s4_standoff_avoid")
        stop = setup_llm_logging(log_dir, stubs={
            "combat_entry": {"enter_combat": True, "enemy_instance_ids": [],
                             "reasoning": "玩家径直走向敌人（stub 播种 standoff）"},
        })
        try:
            world, inv, inst = _deep_one_world()
            game = _real_game(world, _l1("room_a"))

            r1 = run_turn(game, "我继续前进，径直走向那只深潜者")
            assert_player_turn_contract(r1)
            assert r1.pending_interaction is not None
            assert r1.pending_interaction.kind == "standoff"

            r2 = run_turn(game, "我举起双手表示无害，慢慢后退，悄悄绕开它")
            assert_player_turn_contract(r2)
            assert r2.combat_init is None, "standoff 内联处理，不得返回 combat_init"
            text = f"{r2.brief}\n{r2.narrative}"
            assert "进入战斗" not in text and "战斗胜利" not in text \
                   and "战斗败北" not in text, f"不应进入战斗: {text[:200]}"
            assert inst.status not in ("dead", "defeated"), "回避成功不应击杀敌人"
            assert any(kw in text for kw in ("绕过", "绕开", "避开", "敌意消退", "潜行")), \
                f"宽断言：回避成功语义缺失: {text[:200]}"
        finally:
            stop()


class TestS5StandoffCombat:
    @retry_once
    def test_standoff_then_combat(self):
        """S5：standoff 转战斗。combat_entry + standoff_match 单点 stub（见模块
        docstring）；战斗内联结算后 complete_combat_turn 的 enrich 与 narrator 真实。"""
        from game_loop import run_turn
        log_dir = _scenario_log_dir("s5_standoff_combat")
        stop = setup_llm_logging(log_dir, stubs={
            "combat_entry": {"enter_combat": True, "enemy_instance_ids": [],
                             "reasoning": "玩家径直走向敌人（stub 播种 standoff）"},
            "standoff_match": {"matched": False, "skill_name": "",
                               "reason": "玩家主动攻击，无回避意图（stub 保证战斗路径）"},
        })
        try:
            world, inv, inst = _deep_one_world()
            game = _real_game(world, _l1("room_a"))

            r1 = run_turn(game, "我继续前进，径直走向那只深潜者")
            assert_player_turn_contract(r1)
            assert r1.pending_interaction is not None
            assert r1.pending_interaction.kind == "standoff"

            r2 = run_turn(game, "我怒吼着扑向深潜者，挥拳猛击")
            assert_player_turn_contract(r2)
            assert r2.combat_init is None, "内联战斗已结算，不得再返回 combat_init"
            text = f"{r2.brief}\n{r2.narrative}"
            assert "战斗" in text, f"战斗必须发生（text/brief 含战斗内容）: {text[:200]}"
        finally:
            stop()


class TestS6CombatCompletion:
    @retry_once
    def test_combat_init_then_complete(self):
        """S6：战斗完成闭环。hostile 敌人 + combat_entry stub → combat_init；
        构造 combat_result 调 complete_combat_turn，内部 enrich 为真实 LLM。"""
        from game_loop import run_turn
        log_dir = _scenario_log_dir("s6_combat_completion")
        stop = setup_llm_logging(log_dir, stubs={
            "combat_entry": {"enter_combat": True, "enemy_instance_ids": [],
                             "reasoning": "hostile 敌人遭遇（stub 保证 combat_init）"},
        })
        try:
            world, inv, inst = _deep_one_world(hostile_only=True)
            game = _real_game(world, _l1("room_a"))
            keeper = game["keeper"]

            r1 = run_turn(game, "我继续前进，径直走向那只深潜者")
            assert_player_turn_contract(r1)
            assert r1.combat_init is not None, "hostile 遭遇必须产出 combat_init"
            assert r1.combat_init.enemies, "combat_init 必须携带敌人"

            completed = keeper.complete_combat_turn(
                keeper._last_player_input,
                {"outcome": "win", "narrative": "经过一番激战，你击倒了这个来自深海的怪物。"})
            assert completed is not None, "complete_combat_turn 必须有回放素材"
            assert completed.brief is not None
            msgs = [o.message for o in completed.brief.action_outcomes]
            assert any("战斗胜利" in m for m in msgs), f"brief 缺战斗 outcome: {msgs}"
            assert completed.brief.enriched_summary, \
                "宽断言：真实 enrich 应产出 enriched_summary"
        finally:
            stop()


class TestS7MoveClock:
    @retry_once
    def test_move_and_clock(self):
        """S7：移动 + 时钟。action_type=move 跳过 parse；enrich/time_agent/narrator 真实。"""
        from game_loop import run_turn
        log_dir = _scenario_log_dir("s7_move_clock")
        stop = setup_llm_logging(log_dir)
        try:
            world = make_world({
                "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                             "requirement": ""}]),
                "room_b": make_scene(exits=[{"target": "room_a", "method": "步行",
                                             "requirement": ""}]),
            }, "room_a")
            _player(world)
            game = _real_game(world, _l1("room_a", "room_b"))

            t0 = world.clock.game_time
            r = run_turn(game, "前往room_b", action_type="move",
                         action_target="room_b")
            assert_player_turn_contract(r)
            assert world.current_location == "room_b", \
                f"移动后位置应为 room_b，实际 {world.current_location}"
            ta = r.diagnostics["time_agent"]
            assert ta is None or isinstance(ta, dict), \
                f"time_agent 结构须为 dict 或 None，实际 {type(ta)}"
            if isinstance(ta, dict):
                assert ta.get("time_delta", 0) >= 0, \
                    f"宽断言：time_delta ≥ 0，实际 {ta.get('time_delta')}"
            assert world.clock.game_time >= t0, "时钟不得倒退"
        finally:
            stop()


class TestS8Frozen:
    def test_invalid_key_frozen(self, monkeypatch):
        """S8：FROZEN 诱发。llm.py 在模块级缓存 OpenAI client（key 于 import 时读取），
        因此仅 setenv 无效——monkeypatch 替换 llm.client 为无效 key 客户端，
        使底层 HTTP 调用抛鉴权异常；parse 是 critical step，重试耗尽后冻结。
        全确定性（每次调用必 401），无需 retry。"""
        from game_loop import run_turn
        from game.messages import TurnStatus
        import llm
        from openai import OpenAI
        from config_llm import LLM_BASE_URL, LLM_API_KEY_ENV
        log_dir = _scenario_log_dir("s8_frozen")
        stop = setup_llm_logging(log_dir)
        try:
            monkeypatch.setenv(LLM_API_KEY_ENV, "invalid-key")
            monkeypatch.setattr(
                llm, "client", OpenAI(api_key="invalid-key", base_url=LLM_BASE_URL))

            world = make_world({"room_a": make_scene()}, "room_a")
            _player(world)
            game = _real_game(world, _l1("room_a"))
            keeper = game["keeper"]

            r = run_turn(game, "我环顾四周，仔细观察这个房间")
            assert r.status == TurnStatus.FROZEN, f"status={r.status}"
            assert keeper.turn_monitor._freeze_message, "frozen_message 必须非空"
            assert r.narrative and (
                "游戏已暂停" in r.narrative or "系统异常" in r.narrative), \
                f"run_turn narrative 须含冻结信息: {r.narrative[:120]}"
            assert r.brief, "FROZEN 时 brief 须携带 frozen_message"
        finally:
            stop()


class TestS9Ending:
    @retry_once
    def test_ending_marker_game_over(self):
        """S9：结局触发。交互结果含 ##END_名字:叙事## 标记；真实 parse 需将输入
        映射到该交互（宽断言，retry 一次）；judge/enrich/narrator 真实。"""
        from game_loop import run_turn
        from game.messages import TurnStatus
        log_dir = _scenario_log_dir("s9_ending")
        stop = setup_llm_logging(log_dir)
        try:
            ending_interaction = {
                "id": "IT_END", "entity_type": "interaction",
                "name": "阅读桌上的完整日志", "scene": "room_a",
                "type": "None", "requirement": "", "trigger": "阅读桌上的完整日志",
                "result": "你读完最后一页，真相大白。##END_真相:你揭开了霍桑实验的真相##",
                "side_effects": [], "difficulty": "None",
            }
            world = make_world(
                {"room_a": make_scene(interactions=[ending_interaction])}, "room_a")
            _player(world)
            game = _real_game(world, _l1("room_a"))

            r = run_turn(game, "我坐下来，认真阅读桌上的完整日志")
            assert_player_turn_contract(r)
            assert r.status == TurnStatus.COMPLETED
            assert r.game_over is True, \
                "宽断言：parse 应映射到 IT_END 触发结局（未映射则 retry）"
            assert r.ending is not None
            assert r.ending.name == "真相"
            assert "霍桑" in r.ending.narrative
        finally:
            stop()


class TestS10TraitEnhancement:
    @retry_once
    def test_trait_enhancement_direction(self):
        """S10（试点）：特质增强数据通路——搜索检定后 enhancement 结构自洽：
        若 tier 被修正则 original_tier 必须存在且与最终 tier 不同；修正方向合法。
        action_type=search 跳过 parse；check_skill 真实骰子；特质增强真实 LLM。
        增强是否触发由 LLM 决定（宽断言只锁数据结构，不锁触发率）。"""
        from game_loop import run_turn
        from game.messages import TurnStatus
        log_dir = _scenario_log_dir("s10_trait_enhancement")
        stop = setup_llm_logging(log_dir)
        try:
            world = make_world({"room_a": make_scene()}, "room_a")
            inv = _player(world, skills={"侦查": 60})
            inv.personal_description = (
                "前登山向导，观察力敏锐，习惯在黑暗与复杂地形中察觉细微动静。")
            game = _real_game(world, _l1("room_a"))

            r = run_turn(game, "搜索", action_type="search")
            assert_player_turn_contract(r)
            assert r.status == TurnStatus.COMPLETED, f"status={r.status}"

            snap = r.player_snapshot
            checks = [s for s in (snap.skill_checks if snap else [])
                      if getattr(s, "entity_id", "") == "SEARCH"]
            assert checks, "搜索回合必须产生 SEARCH 检定记录"
            sc = checks[0]
            assert sc.raw_roll > 0 and sc.target > 0, \
                f"快照检定必须带解析后的骰点/目标值: {sc}"
            assert sc.tier in ("critical", "extreme", "hard", "regular",
                               "failure", "fumble"), f"非法 tier: {sc.tier}"

            enh = sc.enhancement
            if enh and enh.get("original_tier"):
                assert enh["original_tier"] != sc.tier, \
                    "tier 被修正时 original_tier 必须与最终 tier 不同"
                assert enh.get("tier") == sc.tier, \
                    f"enhancement.tier 必须等于最终 tier: {enh.get('tier')} vs {sc.tier}"
                assert enh.get("reason"), "特质修正必须给出理由"
                print(f"[S10] 增强触发: {enh['original_tier']} → {sc.tier}")
            else:
                print(f"[S10] 增强未改 tier（roll={sc.raw_roll}/{sc.target} "
                      f"tier={sc.tier}），数据结构断言通过")
        finally:
            stop()


class TestS11AutoTriggerFire:
    @retry_once
    def test_at_fires_on_scene_entry_real_llm(self):
        """S11（试点）：AT 点火真实 LLM 面——进入 room_b 后 2 回合内
        「首次进入」型 AT 应被 parse 语义命中并 spawn 敌人。"""
        from game_loop import run_turn
        from library.enemies import EnemyLibrary, LibraryEnemy
        log_dir = _scenario_log_dir("s11_at_fire")
        stop = setup_llm_logging(log_dir)
        try:
            lib = EnemyLibrary()
            lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
                "name": "测试巡游者", "type": "怪物",
                "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
                "attacks": [], "special_abilities": [], "san_loss": "0",
                "description": "缓慢游动的胶质生物", "combat_behavior": "",
            })
            at = {
                "id": "AT_SPAWN", "entity_type": "auto_trigger", "type": "无",
                "name": "巡游者出现", "requirement": "",
                "trigger": "玩家首次进入room_b时",
                "result": "水渍中鼓起一个胶质团块，缓缓向你游来。",
                "side_effects": ['@spawn_enemy(enemy_ref="测试巡游者", scene="room_b", quantity=1)'],
                "graded_result": None, "difficulty": "None",
                "scene": "room_b", "time_condition": [],
            }
            world = make_world({
                "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                             "requirement": ""}]),
                "room_b": make_scene(auto_triggers=[at]),
            }, "room_a", enemy_library=lib)
            _player(world)
            game = _real_game(world, _l1("room_a", "room_b"))

            r1 = run_turn(game, "前往room_b", action_type="move",
                          action_target="room_b")
            assert_player_turn_contract(r1)
            assert world.current_location == "room_b"

            fired = False
            for probe in ("环顾四周，观察这个房间", "仔细查看地面的水渍"):
                r = run_turn(game, probe)
                assert_player_turn_contract(r)
                if world.enemies.get_active_in_scene("room_b"):
                    fired = True
                    break
            assert fired, \
                "宽断言：进入 room_b 后 2 回合内 AT_SPAWN 应点火并生成测试巡游者（未命中则 retry）"
        finally:
            stop()


class TestS12SpellPerception:  # 统一资源层：L0 感知法术
    @retry_once
    def test_l0_spell_perception(self):
        """L0 感知法术：UseParser 命中 -> 扣 MP 叙事，真实 narrator。"""
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        slib = SpellLibrary(); slib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a", spell_library=slib)
        inv = Investigator(name="测试员", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        world.set_player(inv)
        inv.known_spells = ["LIFE_DETECTION"]
        game = _real_game(world, _l1("room_a"))
        from game_loop import run_turn
        r = run_turn(game, "我闭上眼睛，念诵生命觉察的咒文，感知周围的活物")
        assert_player_turn_contract(r)
        assert r.status.name == "COMPLETED"
        assert inv.derived.MP == 9, "L0 感知法术扣 3 MP（12-3）"


class TestS13ItemUse:  # 统一资源层：L1 物品消耗
    @retry_once
    def test_l1_first_aid(self):
        from library.items import ItemLibrary
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        ilib = ItemLibrary(); ilib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a", item_library=ilib)
        inv = Investigator(name="测试员", stats=Stats(
            STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
        inv.derived = calc_derived(inv.stats)
        world.set_player(inv)
        inv.item_manager.add("急救包", quantity=1)
        inv.derived.HP = max(1, inv.derived.HP_MAX - 5)
        game = _real_game(world, _l1("room_a"))
        from game_loop import run_turn
        r = run_turn(game, "我使用急救包，给自己处理伤口")
        assert_player_turn_contract(r)
        assert inv.item_manager.get("急救包") is None \
            or inv.item_manager.get("急救包").quantity == 0
        assert inv.derived.HP > max(1, inv.derived.HP_MAX - 5), "急救包回血生效"


class TestS14SpellAuthor:  # 统一资源层：库外素材 -> creative -> Author
    @retry_once
    def test_unknown_material_escalates(self):
        from game.agents.author import Author
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        keeper = Keeper(world)
        keeper.narrator_l1 = _l1("room_a")
        author = Author({"module_meta": {"name": "t"}, "scene_intents": {},
                         "ending_conditions": []})
        from helpers import StubNarrator
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": author}
        # parse 粗识别 use 但素材未命中（确定性层无该物品/法术）
        keeper._parse = lambda raw: [{"type": "use", "text": raw}]
        keeper.use_parser.llm_call = lambda p, **k: {"matched": False, "material": "", "reason": ""}
        from game_loop import run_turn
        r = run_turn(game, "我举起那台古怪的黄铜装置，按下了侧面的按钮")
        assert_player_turn_contract(r)
        # Author 通路真实 LLM：只断言回合完整，不硬断言 patch 内容


class TestS15ExtensionSpell:  # effect 表达力：扩展库法术游戏内施放（2026-08-21 spec §8）
    """S15：扩展库法术游戏内施放。
    tmp extensions 目录注入扩展法术（带 timed effect），走 load_spell_library(base_dir=...)
    -> make_world(spell_library=...) -> 完整 keeper 回合（"施放暗影低语"经 UseParser
    确定性短路 -> execute_material；check=null 无检定保定性）-> 断言扣 MP + timed 生效。
    enrich/time_agent/narrator 真实 LLM；time_delta 波动由 retry_once 消化
    （timed 15 分钟内被推满过期或 MP 恢复属偶发，复跑即过）。"""

    @retry_once
    def test_extension_spell_timed_effect(self, tmp_path):
        import json
        import shutil
        from pathlib import Path
        from library.loader import load_spell_library
        from investigator import Investigator
        from investigator.models import Stats
        from investigator.rules import calc_derived
        log_dir = _scenario_log_dir("s15_extension_spell")
        stop = setup_llm_logging(log_dir)
        try:
            # tmp 库根：core spells.json + extensions/spells/ext.json（_make_ext 模式）
            core = tmp_path / "core"
            ext_dir = tmp_path / "extensions" / "spells"
            core.mkdir(parents=True, exist_ok=True)   # exist_ok：retry_once 重入安全
            ext_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(Path(__file__).resolve().parents[2] / "data" / "library"
                        / "core" / "spells.json", core / "spells.json")
            (ext_dir / "ext.json").write_text(json.dumps({"spells": [{
                "id": "EXT_WHISPER", "name": "暗影低语",
                "category": "exploration", "impact": "L1",
                "cost": {"mp": 2, "san": 0}, "check": None,
                "effect": [{"type": "timed", "id": "EXT_WHISPER",
                            "description": "耳畔有低语萦绕", "minutes": 15}],
                "on_success": "你听见了阴影里的声音。",
            }]}, ensure_ascii=False), encoding="utf-8")

            slib = load_spell_library(base_dir=str(tmp_path))
            assert slib.get("EXT_WHISPER") is not None, "扩展法术必须经 loader 可见"
            assert slib.get("HEART_ARREST") is not None, "core 法术必须同时加载"

            world = make_world({"room_a": make_scene()}, "room_a", spell_library=slib)
            inv = Investigator(name="测试员", stats=Stats(
                STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
            inv.derived = calc_derived(inv.stats)
            world.set_player(inv)
            inv.known_spells = ["EXT_WHISPER"]
            game = _real_game(world, _l1("room_a"))
            from game_loop import run_turn

            base = world.clock.game_time
            r = run_turn(game, "施放暗影低语")
            assert_player_turn_contract(r)
            assert r.status.name == "COMPLETED", f"status={r.status}"
            # MP 扣 2（POW 60 -> MP 12 -> 10）
            assert inv.derived.MP == 10, \
                f"扩展法术扣 2 MP（12-2），实际 {inv.derived.MP}"
            # timed 生效：挂载 + 结构（id/描述/时效=施放时刻+15）
            assert len(inv.timed_effects) == 1, \
                f"timed 原子必须挂载，实际 {inv.timed_effects}"
            te = inv.timed_effects[0]
            assert te["id"] == "EXT_WHISPER"
            assert te["description"] == "耳畔有低语萦绕"
            assert te["expire_at"] == base + 15, \
                f"expire_at 应为施放时刻+15，实际 {te['expire_at']}（base={base}）"
            # 宽断言：叙事含结果语义（真实 narrator 改写，不锁原文）
            text = f"{r.brief}\n{r.narrative}"
            assert any(kw in text for kw in ("低语", "声音", "阴影")), \
                f"宽断言：叙事须含结果语义: {r.narrative[:120]}"
        finally:
            stop()


class TestS16SaveLoadContinue:  # 统一存档批：真实 LLM 下 save→load→继续回合
    """S16：搜索回合（真实 enrich/time_agent/narrator，action_type=search 跳过
    parse，骰点钉死保证 checked 确定性）→ save_game → load_game → 普通回合
    全真实 LLM（pre_parse/parse/enrich/time_agent/narrator）。锁读档后 restored
    world 走完整管线的完整性 + F14 checked 随 player_snapshot 持久化。"""

    @retry_once
    def test_save_load_then_turn_continues(self, monkeypatch):
        from game_loop import run_turn, save_game, load_game
        from game.messages import TurnStatus
        log_dir = _scenario_log_dir("s16_save_load_continue")
        stop = setup_llm_logging(log_dir)
        try:
            world = make_world({"room_a": make_scene()}, "room_a")
            inv = _player(world, skills={"侦查": 50})
            game = _real_game(world, _l1("room_a"))
            keeper = game["keeper"]
            # 骰点非 LLM：钉死保证 checked 确定性置位
            monkeypatch.setattr("investigator.models.random.randint",
                                lambda a, b: 30)

            r1 = run_turn(game, "搜索", action_type="search")
            assert_player_turn_contract(r1)
            assert r1.status == TurnStatus.COMPLETED, f"status={r1.status}"
            assert inv.get_skill("侦查").checked is True, "搜索成功必须置 checked"

            path = os.path.join(log_dir, "save.json")
            save_game(game, path)
            old_world = keeper.world
            load_game(game, path)

            assert keeper.world is not old_world, "load_game 必须重绑 world"
            assert keeper.world.current_location == "room_a"
            restored_inv = keeper.world.player
            assert restored_inv is not None, "player_snapshot 必须恢复"
            assert restored_inv.get_skill("侦查").checked is True, \
                "checked 必须随 player_snapshot 持久化"

            r2 = run_turn(game, "我仔细检查这个房间的墙壁，看有没有暗门")
            assert_player_turn_contract(r2)
            assert r2.status == TurnStatus.COMPLETED, \
                f"读档后回合应正常完成，实际 status={r2.status}"
            assert r2.narrative and len(r2.narrative) > 20, \
                f"宽断言：读档后 narrative 非空且长度>20: {r2.narrative[:80]}"
        finally:
            stop()
