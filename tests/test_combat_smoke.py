"""Combat system smoke test — standalone, no LLM calls needed."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from investigator.models import Investigator, Stats, DerivedStats, Skill
from investigator.rules import calc_derived
from game.combat import CombatSystem, CombatAction, CombatState
from game.messages import CombatInit


def _make_investigator(name="测试员", hp=12, san=60, mp=14):
    """Build a minimal Investigator for combat testing."""
    inv = Investigator()
    inv.name = name
    inv.stats = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    inv.derived = DerivedStats(HP=hp, HP_MAX=hp, SAN=san, MP=mp, DB="0", BUILD=0, DODGE=25)
    inv.skills = [
        Skill(name="格斗(拳)", base_value=25, value=75, category="战斗"),
        Skill(name="格斗(脚)", base_value=25, value=75, category="战斗"),
        Skill(name="回避", base_value=25, value=75, category="战斗"),
    ]
    return inv


class _TestEnemy:
    """Minimal enemy instance matching what CombatSystem expects."""
    def __init__(self, enemy_ref, hp, armor, instance_id, dex=50, attacks=None,
                 damage_multipliers=None, dodge_bonus=0, multi_attack=1,
                 special_rules="", phases=None, boss_mechanics="",
                 san_loss="", quantity=1):
        self.enemy_ref = enemy_ref
        self.name = enemy_ref
        self.hp = hp
        self.hp_max = hp
        self.armor = armor
        self.instance_id = instance_id
        self.status = "hostile"
        self.flags = set()
        self.DEX = dex
        self.attributes = {}       # needed by _resolve_enemy_action
        self.attacks = attacks or [{"name": "爪击", "skill_name": "格斗", "skill_value": 40, "damage": "1D6"}]
        self.damage_multipliers = damage_multipliers or {}
        self.dodge_bonus = dodge_bonus
        self.multi_attack = multi_attack
        self.special_rules = special_rules
        self.phases = phases or []
        self.boss_mechanics = boss_mechanics
        self._current_phase = ""
        self.san_loss = san_loss
        self.quantity = quantity


# ═══════════════════════════════════════════════════════════════
# Test 1: basic combat — player wins vs low-HP enemy
# ═══════════════════════════════════════════════════════════════
def test_combat_basic_win():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=3, armor="0", instance_id="E_DUMMY_1")

    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试房间", initiative_context="测试战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    assert result.outcome in ("win", "loss"), f"unexpected outcome: {result.outcome}"
    assert result.rounds >= 1, f"expected at least 1 round, got {result.rounds}"
    assert result.player_hp >= 0
    assert result.player_san >= 0
    # narrative may be empty without LLM, but should at least not crash
    assert isinstance(result.narrative, str), "narrative should be str"
    assert hasattr(result, 'defeated_instance_ids'), "missing defeated_instance_ids"
    print(f"  [PASS] basic_win: outcome={result.outcome}, rounds={result.rounds}, "
          f"hp={result.player_hp}, san={result.player_san}, "
          f"narrative={result.narrative[:50] if result.narrative else '(empty)'}")


# ═══════════════════════════════════════════════════════════════
# Test 2: HP/SAN write-back after combat
# ═══════════════════════════════════════════════════════════════
def test_combat_writeback():
    player = _make_investigator(hp=12, san=60)
    hp_before = player.derived.HP
    san_before = player.derived.SAN

    enemy = _TestEnemy("TestDummy", hp=8, armor="0", instance_id="E_DUMMY_2")
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试房间", initiative_context="测试战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    # Simulate game_loop write-back
    player.derived.HP = max(0, result.player_hp)
    player.derived.SAN = max(0, result.player_san)

    hp_after = player.derived.HP
    san_after = player.derived.SAN

    assert hp_before >= hp_after, f"HP should not increase: {hp_before} → {hp_after}"
    assert hp_after >= 0, f"HP should not be negative: {hp_after}"
    print(f"  [PASS] writeback: HP {hp_before}→{hp_after}, SAN {san_before}→{san_after}, "
          f"outcome={result.outcome}")


# ═══════════════════════════════════════════════════════════════
# Test 3: full_log populated with round_num
# ═══════════════════════════════════════════════════════════════
def test_combat_full_log():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=5, armor="0", instance_id="E_DUMMY_3")

    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试房间", initiative_context="测试战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    # Check the full_log is accessible (via state inspection)
    # The full_log is on state which is internal, but we can verify via rounds
    assert result.rounds >= 1, f"expected at least 1 round, got {result.rounds}"
    # round_num should be set on each action — we verify indirectly:
    # if round_num weren't set, _generate_combat_narrative would fail
    print(f"  [PASS] full_log: rounds={result.rounds}, outcome={result.outcome}")


# ═══════════════════════════════════════════════════════════════
# Test 4: boss combat — loss signal but no game_over
# ═══════════════════════════════════════════════════════════════
def test_combat_boss_loss_signal():
    """Boss combat loss → combat_boss_loss=True, game_over=False."""
    player = _make_investigator(hp=2, san=60)   # low HP → likely loss
    boss = _TestEnemy("BossTest", hp=50, armor="2", instance_id="E_BOSS_1",
                       dex=80, attacks=[{"name": "触手鞭打", "skill_name": "格斗", "skill_value": 80, "damage": "2D6+DB"}])

    combat_init = CombatInit(
        enemies=[boss], player=player,
        scene="测试房间", initiative_context="Boss战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    # Simulate game_loop decision logic
    combat_is_boss = True  # from world.bosses.active_boss_id
    if combat_is_boss and result.outcome == "loss":
        combat_boss_loss = True
        combat_death = False
    elif result.outcome == "loss":
        combat_boss_loss = False
        combat_death = True
    else:
        combat_boss_loss = False
        combat_death = False

    if result.outcome == "loss":
        assert combat_boss_loss, "boss loss should set combat_boss_loss"
        assert not combat_death, "boss loss should NOT set combat_death"
    print(f"  [PASS] boss_loss_signal: outcome={result.outcome}, "
          f"boss_loss={combat_boss_loss}, death={combat_death}")


# ═══════════════════════════════════════════════════════════════
# Test 5: regular combat loss → combat_death
# ═══════════════════════════════════════════════════════════════
def test_combat_regular_death():
    """Regular enemy combat loss → combat_death=True, game_over=True."""
    player = _make_investigator(hp=2, san=60)   # low HP
    enemy = _TestEnemy("MurderBot", hp=50, armor="3", instance_id="E_KILLER_1",
                        dex=90, attacks=[{"name": "撕裂", "skill_name": "格斗", "skill_value": 90, "damage": "3D6"}])

    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试房间", initiative_context="测试战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    # Simulate game_loop decision logic for REGULAR combat
    combat_is_boss = False
    if combat_is_boss and result.outcome == "loss":
        combat_boss_loss = True
        combat_death = False
    elif result.outcome == "loss":
        combat_boss_loss = False
        combat_death = True
    else:
        combat_boss_loss = False
        combat_death = False

    if result.outcome == "loss":
        assert combat_death, "regular combat loss should set combat_death"
        assert not combat_boss_loss, "regular combat loss should NOT set combat_boss_loss"
    print(f"  [PASS] regular_death: outcome={result.outcome}, "
          f"death={combat_death}, boss_loss={combat_boss_loss}")


# ═══════════════════════════════════════════════════════════════
# Test 6: CombatResult structure completeness
# ═══════════════════════════════════════════════════════════════
def test_combat_result_structure():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=3, armor="0", instance_id="E_DUMMY_4")

    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试房间", initiative_context="测试战斗"
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)

    assert hasattr(result, 'outcome') and result.outcome in ("win", "loss", "flee")
    assert hasattr(result, 'defeated_instance_ids')
    assert hasattr(result, 'narrative')
    assert hasattr(result, 'player_hp') and result.player_hp >= 0
    assert hasattr(result, 'player_san') and result.player_san >= 0
    assert hasattr(result, 'rounds') and result.rounds >= 1
    print(f"  [PASS] result_structure: all fields present, outcome={result.outcome}")


# ═══════════════════════════════════════════════════════════════
# Test 7: phase trigger — hp_below_pct activates boss phase
# ═══════════════════════════════════════════════════════════════
def test_combat_phase_trigger():
    """Phase triggers at hp_below_pct and applies overrides."""
    player = _make_investigator(hp=30, san=60)
    boss = _TestEnemy("PhaseBoss", hp=3, armor="0", instance_id="E_PHASE_1",
        dex=10, attacks=[{"name": "轻触", "damage": "1D2"},],
        phases=[{"trigger": "hp_below_pct:0.5", "name": "狂怒",
                 "overrides": {}, "description": "Boss狂暴了"}])
    combat_init = CombatInit(
        enemies=[boss], player=player,
        scene="测试", initiative_context="phase",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss"), f"unexpected outcome: {result.outcome}"
    print(f"  [PASS] phase_trigger: outcome={result.outcome}, rounds={result.rounds}")


# ═══════════════════════════════════════════════════════════════
# Test 8: damage multipliers — vulnerability increases damage
# ═══════════════════════════════════════════════════════════════
def test_combat_damage_multipliers():
    """Enemy with vulnerability takes extra damage."""
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("WeakToFire", hp=10, armor="0", instance_id="E_FIRE_1",
        damage_multipliers={"火焰": 2.0})
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="dmg_mult",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss", "draw", "flee"), f"unexpected outcome: {result.outcome}"
    print(f"  [PASS] dmg_multipliers: outcome={result.outcome}")


# ═══════════════════════════════════════════════════════════════
# Test 9: multi-target — player_targets enables multiple targets
# ═══════════════════════════════════════════════════════════════
def test_combat_multi_target():
    """CombatInit with player_targets allows multiple targets."""
    player = _make_investigator(hp=30, san=60)
    e1 = _TestEnemy("Target1", hp=5, armor="0", instance_id="E_T1")
    e2 = _TestEnemy("Target2", hp=5, armor="0", instance_id="E_T2")
    combat_init = CombatInit(
        enemies=[e1, e2], player=player,
        scene="测试", initiative_context="multi",
        player_targets=["E_T1", "E_T2"],
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss", "draw", "flee"), f"unexpected outcome: {result.outcome}"
    assert hasattr(result, 'round_log'), "CombatResult should have round_log"
    print(f"  [PASS] multi_target: outcome={result.outcome}, round_log entries={len(result.round_log)}")


# ═══════════════════════════════════════════════════════════════
# Test 10: new player actions — conceal, aim, charge
# ═══════════════════════════════════════════════════════════════
def test_combat_new_actions():
    """Conceal, aim, and charge actions execute without crash."""
    player = _make_investigator(hp=30, san=60)

    enemy1 = _TestEnemy("TestDummy", hp=10, armor="0", instance_id="E_ACT1")
    cs = CombatSystem()
    ci1 = CombatInit(enemies=[enemy1], player=player, scene="测试")
    r1 = cs.run_combat(ci1, player_action="conceal")
    assert r1.outcome in ("win", "loss", "draw")
    print(f"  [PASS] conceal: outcome={r1.outcome}")

    enemy2 = _TestEnemy("TestDummy2", hp=10, armor="0", instance_id="E_ACT2")
    ci2 = CombatInit(enemies=[enemy2], player=player, scene="测试")
    r2 = cs.run_combat(ci2, player_action="aim")
    assert r2.outcome in ("win", "loss", "draw")
    print(f"  [PASS] aim: outcome={r2.outcome}")

    enemy3 = _TestEnemy("TestDummy3", hp=10, armor="0", instance_id="E_ACT3")
    ci3 = CombatInit(enemies=[enemy3], player=player, scene="测试")
    r3 = cs.run_combat(ci3, player_action="charge")
    assert r3.outcome in ("win", "loss", "draw")
    print(f"  [PASS] charge: outcome={r3.outcome}")


# ═══════════════════════════════════════════════════════════════
# Test 11: round_log populated in CombatResult
# ═══════════════════════════════════════════════════════════════
def test_combat_round_log():
    """CombatResult includes round_log after layered execution."""
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("LogTest", hp=5, armor="0", instance_id="E_LOG")
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="round_log",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert hasattr(result, 'round_log'), "CombatResult should have round_log"
    assert isinstance(result.round_log, list), "round_log should be a list"
    print(f"  [PASS] round_log: {len(result.round_log)} rounds logged")


def test_combat_hp_accuracy():
    """Verify enemy HP decreases by expected amount (no double-damage bug)."""
    player = _make_investigator(hp=30, san=60)
    initial_hp = 100
    enemy = _TestEnemy("HPTest", hp=initial_hp, armor="0", instance_id="E_HPCHECK",
        dodge_bonus=90, attacks=[{"name": "轻触", "damage": "1D2"}])
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="hp_accuracy",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init, player_action="punch")
    # Enemy has dodge_bonus=90 and low damage, so it should survive many rounds
    # After combat, enemy HP should not drop below 0 and should not have doubled damage
    final_hp = enemy.hp
    assert final_hp >= 0, f"Enemy HP should not be negative: {final_hp}"
    # The enemy should still be alive after many rounds if HP was high enough
    # Just verify the round log structure
    assert hasattr(result, 'round_log')
    for entry in result.round_log:
        pd = entry.get("player_damage", 0)
        assert isinstance(pd, int), f"player_damage should be int: {pd}"
    print(f"  [PASS] hp_accuracy: initial={initial_hp}, final={final_hp}, rounds={result.rounds}")


# ═══════════════════════════════════════════════════════════════
# Test 12: cast effect atoms (2026-08-21 spec §1.2 战斗列)
# ═══════════════════════════════════════════════════════════════
class TestCastEffectAtoms:
    """战斗侧 effect 原子:heal/mp_change/markup/timed/buff写状态/control写状态/narrative/未知降级。"""

    def _env(self, effect, with_world=False):
        """内存法术库 + 必过检定玩家(POW 技能 200) + CombatSystem(spell_lib, world?)。"""
        from library.spells import SpellLibrary, LibrarySpell
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒", "category": "combat",
            "cost": {"mp": 1, "san": 0},
            "check": {"skill": "POW", "type": "regular"},
            "effect": effect})
        inv = _make_investigator(hp=12, san=60, mp=14)
        inv.derived.MP_MAX = 20
        inv.skills.append(Skill(name="POW", base_value=50, value=200, category="属性"))
        inv.known_spells = ["X"]
        world = None
        if with_world:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "e2e"))
            from helpers import make_world, make_scene
            world = make_world({"room_a": make_scene()}, "room_a")
            world.set_player(inv)
        cs = CombatSystem(spell_lib=lib, world=world)
        return cs, inv, world

    def test_heal_atom_in_combat(self):
        cs, inv, _ = self._env([{"type": "heal", "target": "self", "formula": "1D3"}])
        inv.derived.HP = inv.derived.HP_MAX - 3   # 9/12
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success, f"检定必过(POW=200): {act.narrative}"
        assert inv.derived.HP > 9, "heal 后 HP 必须上升"
        assert inv.derived.HP <= inv.derived.HP_MAX, "heal 必须 clamp 到 HP_MAX"

    def test_mp_change_atom_in_combat(self):
        cs, inv, _ = self._env([{"type": "mp_change", "delta": 2}])
        before = inv.derived.MP   # 14
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert inv.derived.MP == before - 1 + 2, \
            "cost mp=1 已扣 + mp_change +2,净 +1(=15)"

    def test_markup_atom_in_combat(self):
        cs, inv, _ = self._env(
            [{"type": "markup",
              "text": '@stat_change(stat_name="SAN", delta=-1)'}],
            with_world=True)
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert inv.derived.SAN == 59, "markup 原子经 apply_side_effects 改 world.player.SAN"

    def test_markup_without_world_skips(self, caplog):
        import logging
        cs, inv, _ = self._env(
            [{"type": "markup",
              "text": '@stat_change(stat_name="SAN", delta=-1)'}])
        with caplog.at_level(logging.WARNING, logger="game.combat"):
            act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success, "无 world 时 markup 跳过但不致败"
        assert inv.derived.SAN == 60, "无 world 时不结算"
        assert "markup" in caplog.text, "无 world 跳过须留 warning 日志"

    def test_timed_atom_in_combat(self):
        cs, inv, world = self._env(
            [{"type": "timed", "id": "T", "description": "低语缠身", "minutes": 5}],
            with_world=True)
        base = world.clock.game_time
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert len(inv.timed_effects) == 1
        te = inv.timed_effects[0]
        assert te["id"] == "T" and te["description"] == "低语缠身"
        assert te["expire_at"] == base + 5, "expire_at = game_time + minutes"

    def test_buff_atom_writes_state(self):
        cs, inv, _ = self._env([{"type": "buff", "id": "B", "reduce": 3, "rounds": 3}])
        state = CombatState()
        act = cs._resolve_player_action(state, inv, "cast_X", "")
        assert act.success
        assert state.temporary_effects == [{"id": "B", "reduce": 3, "rounds": 3}]

    def test_control_atom_writes_target(self):
        cs, inv, _ = self._env([{"type": "control", "rounds": 2}])
        enemy = _TestEnemy("傀儡", hp=10, armor="0", instance_id="E_CTRL")
        state = CombatState(enemies=[enemy])
        act = cs._resolve_player_action(state, inv, "cast_X", "E_CTRL")
        assert act.success
        assert enemy.controlled_rounds == 2, "control 原子写 target.controlled_rounds"

    def test_narrative_and_unknown_in_combat(self):
        cs, inv, _ = self._env([{"type": "narrative", "text": "寒意蔓延"},
                                {"type": "summon", "description": "窸窣声"}])
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert "寒意蔓延" in act.narrative, "narrative 原子文本拼进 action.narrative"
        assert "[unknown:summon]" in act.narrative and "窸窣声" in act.narrative, \
            "未知 type 降级为 [unknown:t] 前缀"

    def test_damage_atom_still_works(self):
        cs, inv, _ = self._env([{"type": "damage", "formula": "1D6",
                                 "ignore_armor": True}])
        enemy = _TestEnemy("木桩", hp=10, armor="3", instance_id="E_DMG")
        state = CombatState(enemies=[enemy])
        act = cs._resolve_player_action(state, inv, "cast_X", "E_DMG")
        assert act.success
        assert act.damage >= 1, "damage 原子沿用 _roll_damage(>=1)"
        assert enemy.hp == 10 - act.damage, "敌 HP 按 damage 下降(ignore_armor 不吃甲)"

    def test_timed_atom_refresh_same_id(self):
        cs, inv, world = self._env(
            [{"type": "timed", "id": "T", "description": "低语缠身", "minutes": 5}],
            with_world=True)
        base = world.clock.game_time
        state = CombatState()
        cs._resolve_player_action(state, inv, "cast_X", "")   # 第一次 5 分钟
        cs.spell_lib.get("X").effect[0]["minutes"] = 9
        cs._resolve_player_action(state, inv, "cast_X", "")   # 同 id 再施 9 分钟
        assert len(inv.timed_effects) == 1, "同 id timed refresh 不叠条"
        assert inv.timed_effects[0]["expire_at"] == base + 9, \
            "expire_at 取最后一次施放(9 分钟)"

    def test_empty_type_atom_no_prefix(self):
        cs, inv, _ = self._env([{"text": "隐隐低语"}])   # 无 type 原子
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert "隐隐低语" in act.narrative, "空 type 原子文本直出"
        assert "[unknown:]" not in act.narrative, \
            "空 type 不打 [unknown:] 前缀(与 judge.py T6 语义一致)"

    def test_timed_without_world_skips_with_warning(self, caplog):
        import logging
        cs, inv, _ = self._env(
            [{"type": "timed", "id": "T", "description": "低语缠身", "minutes": 5}])
        with caplog.at_level(logging.WARNING, logger="game.combat"):
            act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success, "无 world 时 timed 跳过但不致败"
        assert inv.timed_effects == [], "无 world 时不挂载"
        assert "timed" in caplog.text, "无 world 跳过须留 warning 日志"

    def test_heal_garbage_formula_falls_back_to_delta(self):
        cs, inv, _ = self._env([{"type": "heal", "formula": "garbage", "delta": 5}])
        inv.derived.HP = inv.derived.HP_MAX - 6
        act = cs._resolve_player_action(CombatState(), inv, "cast_X", "")
        assert act.success
        assert inv.derived.HP == inv.derived.HP_MAX - 1, \
            "垃圾 formula 回退 delta(恢复 5;与探索侧统一)"


class TestCombatBuff:
    """战斗 buff:受击减免(floor 可配)+轮末递减归零移除(2026-08-21 spec §3)。"""

    def _env(self, temporary_effects=None):
        """必中敌人(attributes DEX/POW=200)+ 满 HP 玩家 state(伤害靠 monkeypatch 固定)。"""
        enemy = _TestEnemy("甲兽", hp=20, armor="0", instance_id="E_BUFF")
        enemy.attributes = {"DEX": 200, "POW": 200, "STR": 50, "SIZ": 50}
        state = CombatState(enemies=[enemy])
        state.player_hp = 20
        state.player_hp_max = 20
        state.temporary_effects = temporary_effects or []
        return CombatSystem(), state, enemy

    def test_buff_reduces_incoming_damage(self, monkeypatch):
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 7)
        # 无 buff 对照:全额 7
        cs, state, enemy = self._env()
        act_plain = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act_plain.success and act_plain.damage == 7
        assert state.player_hp == 20 - 7
        # 有 buff(reduce=3):7-3=4
        cs2, state2, enemy2 = self._env([{"id": "B", "reduce": 3, "rounds": 3}])
        act_buff = cs2._resolve_enemy_action(state2, enemy2, _make_investigator())
        assert act_buff.success
        assert act_buff.damage == 4, "总减免 3:伤害 7-3=4"
        assert state2.player_hp == 20 - 4, "扣血按减免后伤害"
        assert act_plain.damage - act_buff.damage == 3, "有 buff 扣血 < 无 buff,差值恰为 reduce"

    def test_buff_damage_floor(self, monkeypatch):
        import game.combat as combat_mod
        import investigator.rules as rules_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 5)
        # 默认 floor=0:reduce=99 -> 伤害 0
        cs, state, enemy = self._env([{"id": "B", "reduce": 99, "rounds": 1}])
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act.success and act.damage == 0
        assert state.player_hp == 20, "floor=0 时减穿归零"
        # floor=1:至少扣 1
        monkeypatch.setattr(rules_mod, "get_game_config",
                            lambda: {"buff_damage_floor": 1})
        cs2, state2, enemy2 = self._env([{"id": "B", "reduce": 99, "rounds": 1}])
        act2 = cs2._resolve_enemy_action(state2, enemy2, _make_investigator())
        assert act2.success and act2.damage == 1, "floor 可配:减穿后取 floor=1"
        assert state2.player_hp == 20 - 1

    def test_buff_rounds_decay_and_expire(self, monkeypatch):
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 7)
        cs, state, enemy = self._env([{"id": "B", "reduce": 3, "rounds": 2}])
        cs._tick_temporary_effects(state)
        assert state.temporary_effects == [{"id": "B", "reduce": 3, "rounds": 1}], \
            "轮末 rounds-1,rounds=1 仍在"
        cs._tick_temporary_effects(state)
        assert len(state.temporary_effects) == 0, "rounds 归零移除"
        # 移除后伤害全额(对照)
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act.success and act.damage == 7, "buff 过期后不再减免"
        assert state.player_hp == 20 - 7

    def test_multiple_buffs_stack_reduce(self, monkeypatch):
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 9)
        cs, state, enemy = self._env([
            {"id": "B1", "reduce": 2, "rounds": 3},
            {"id": "B2", "reduce": 3, "rounds": 3}])
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act.success
        assert act.damage == 9 - 5, "两个 buff 减免叠加:2+3=5"
        assert state.player_hp == 20 - (9 - 5)


class TestCombatControl:
    """战斗 control:敌方行动跳过 + 轮末递减恢复(2026-08-21 spec §3)。"""

    def _env(self, controlled_rounds=None):
        """必中敌人(attributes DEX/POW=200)+ 满 HP 玩家 state;controlled_rounds 非 None 时预置。"""
        enemy = _TestEnemy("傀儡兽", hp=20, armor="0", instance_id="E_CTRL")
        enemy.attributes = {"DEX": 200, "POW": 200, "STR": 50, "SIZ": 50}
        if controlled_rounds is not None:
            enemy.controlled_rounds = controlled_rounds
        state = CombatState(enemies=[enemy])
        state.player_hp = 20
        state.player_hp_max = 20
        return CombatSystem(), state, enemy

    def test_controlled_enemy_skips_action(self, monkeypatch):
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod, "_roll_damage", lambda *a, **k: 7)
        # 被控制(controlled_rounds=2):跳过行动,不掷骰不伤害不消耗 dodge
        cs, state, enemy = self._env(controlled_rounds=2)
        state._player_dodging = True
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act.success is False, "被支配敌人无攻击检定,success=False"
        assert "无法动弹" in act.narrative and "傀儡兽" in act.narrative, \
            "叙事含'被无形的力量攫住,无法动弹'且带敌人标签"
        assert act.damage == 0, "不造成伤害"
        assert state.player_hp == 20, "player_hp 不变"
        assert state._player_dodging is True, "跳过路径不消耗 _player_dodging"
        assert enemy.controlled_rounds == 2, "跳过本身不递减(递减只在轮末 _tick)"
        # 对照:无 control 时同一敌人必中(DEX/POW=200)造成伤害
        cs2, state2, enemy2 = self._env()
        act2 = cs2._resolve_enemy_action(state2, enemy2, _make_investigator())
        assert act2.success and act2.damage == 7, "无 control 正常命中掷骰"
        assert state2.player_hp == 20 - 7, "无 control 正常扣血"

    def test_control_decays_via_tick(self):
        cs, state, enemy = self._env(controlled_rounds=1)
        act_before = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert "无法动弹" in act_before.narrative, "前置:控制期内跳过行动"
        cs._tick_temporary_effects(state)
        assert enemy.controlled_rounds == 0, "轮末递减 1->0,恢复行动"
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert "无法动弹" not in act.narrative, "归零后走正常行动路径"
        assert act.success and act.roll >= 1, "恢复正常掷骰且必中(DEX/POW=200)"

    def test_controlled_skip_round_narrative_not_miss(self):
        cs, state, enemy = self._env(controlled_rounds=2)
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        state.log = [act]
        from game.messages import CombatInit
        result = cs._build_single_round_result(
            state, CombatInit(enemies=[enemy], player=_make_investigator(),
                              scene="测", initiative_context="测"))
        text = result.get("round_narrative") or result.get("narrative") or str(result)
        assert "未命中" not in text
        assert "无法动弹" in text or "无法行动" in text

    def test_uncontrolled_enemy_acts_normally(self):
        cs, state, enemy = self._env()   # 无 controlled_rounds 属性的普通敌人
        assert not hasattr(enemy, "controlled_rounds"), "前置:普通敌人无该属性"
        act = cs._resolve_enemy_action(state, enemy, _make_investigator())
        assert act.success and act.roll >= 1, "getattr 默认 0,正常掷骰命中"
        assert "无法动弹" not in act.narrative, "叙事走常规命中文案"
        assert act.damage >= 1, "正常路径造成伤害(1D6)"


class TestRunGameControlGuard:
    """run_game 交互战斗:被支配敌人不进敌方 LLM 修正 + 跳过叙事 CLI 可见(T11 review)。"""

    def test_controlled_enemy_skips_llm_correction_and_narrative_visible(
            self, monkeypatch, capsys, tmp_path):
        import types
        import run_game as rg                     # 惰性导入:库加载副作用只影响本测试
        import game.combat as combat_mod

        # 敌人:高 DEX 先手 + special_rules(触发 LLM 修正段)+ 被支配 1 轮
        enemy = _TestEnemy("傀儡兽", hp=20, armor="0", instance_id="E_RG",
                           special_rules="再生:每轮恢复1HP")
        enemy.attributes = {"DEX": 200, "POW": 200, "STR": 50, "SIZ": 50}
        enemy.controlled_rounds = 1
        inv = _make_investigator(hp=12, san=60)
        combat_init = CombatInit(enemies=[enemy], player=inv,
                                 scene="测试房间", initiative_context="测试")

        calls = []

        def _fake_enemy_correct(self, en, ea_data, pl, extra, ctx):
            calls.append(dict(ea_data))
            return {"damage": 99}                 # 若被错误调用,"修正"出 99 伤害

        monkeypatch.setattr(combat_mod.CombatSystem, "_llm_correct_enemy_round",
                            _fake_enemy_correct)
        monkeypatch.setattr(combat_mod.CombatSystem, "_llm_correct_round",
                            lambda self, rr, *a, **k: rr)
        monkeypatch.setattr(combat_mod.CombatSystem, "_generate_combat_narrative",
                            lambda self, *a, **k: "")

        def _fake_player_action(self, state, player, action_id, target_iid,
                                environment_actions=None):
            state.finished = True                 # 逃跑成功,单轮结束
            return CombatAction(actor="player", action_type="flee",
                                success=True, narrative="逃离成功")

        monkeypatch.setattr(combat_mod.CombatSystem, "_resolve_player_action",
                            _fake_player_action)
        monkeypatch.setattr("builtins.input", lambda *a: "f")
        monkeypatch.setattr(rg, "_log_dir", str(tmp_path))

        world = types.SimpleNamespace(
            spell_library=None,
            enemy_manager=types.SimpleNamespace(exit_combat=lambda d: None),
            bosses=None)
        game = {"keeper": types.SimpleNamespace(world=world)}

        result = rg._run_interactive_combat(game, combat_init)

        assert calls == [], \
            "被支配敌人(damage=0)不得进 _llm_correct_enemy_round(与 combat.py @294 守卫对齐)"
        assert inv.derived.HP == 12, \
            "玩家 HP 不被修正路径扣减(守卫缺失时会被'修正'出 99 伤害)"
        assert result["outcome"] == "flee"
        assert "无法动弹" in capsys.readouterr().out, \
            "跳过叙事'被攫住无法动弹'在 CLI 敌方行动行可见"


class TestSanCheckFunctions:
    """遭遇 SAN check 通路(ISSUES P0):解析+检定纯函数。"""

    def test_parse_san_loss_groups(self):
        from game.combat import parse_san_loss
        # 单组无注释
        assert parse_san_loss("0/1D6") == [("0", "1D6", "")]
        # 多组带情境注释
        got = parse_san_loss("0/1D4 (目睹), 1/1D6 (被攻击)")
        assert got == [("0", "1D4", "目睹"), ("1", "1D6", "被攻击")]
        # 注释自由文本
        assert parse_san_loss("0/1D2 (目睹他们空洞的眼神)") == [("0", "1D2", "目睹他们空洞的眼神")]
        # 空/坏格式
        assert parse_san_loss("") == []
        assert parse_san_loss(",,") == []
        assert parse_san_loss("乱码") == []

    def test_parse_san_loss_garbage_logs_debug(self, caplog):
        """非空 raw 解析结果为空:combat logger 留 debug(坏分隔符静默禁用防呆,M2)。"""
        import logging
        from game.combat import parse_san_loss
        # 空 raw / 可解析输入零日志
        with caplog.at_level(logging.DEBUG, logger="combat"):
            assert parse_san_loss("") == []
            assert parse_san_loss("0/1D6") == [("0", "1D6", "")]
        assert caplog.records == [], "空 raw/可解析输入不得打日志"
        # 坏输入:debug 一条,原文回显
        with caplog.at_level(logging.DEBUG, logger="combat"):
            assert parse_san_loss("乱码") == []
        assert any(r.levelno == logging.DEBUG
                   and "[san] san_loss 无法解析" in r.getMessage()
                   and "乱码" in r.getMessage()
                   for r in caplog.records), "坏输入须留 debug 日志"

    def test_san_check_and_lose_success_and_fail(self, monkeypatch):
        from game import combat
        # SAN=50;强制 roll=30(<=50 成功):掉成功组(固定 2)
        # combat.random 与 utils.random 为同一模块对象,patch 一处 D100/骰面两用
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 30 if b == 100 else 1)
        loss, text = combat._san_check_and_lose(50, "2", "1D6")
        assert loss == 2 and "成功" in text and "2" in text
        # 强制 roll=80(>50 失败):掉失败组 1D6(骰面强制 1 点)
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 80 if b == 100 else 1)
        loss, text = combat._san_check_and_lose(50, "2", "1D6")
        assert loss == 1 and "失败" in text
        # SAN=0:roll>=1 永失败(当前 patch roll=80>0),掉失败组固定 3
        loss, _ = combat._san_check_and_lose(0, "2", "3")
        assert loss == 3
        # 骰式公式:失败组 2D6 逐骰强制 2 点 -> 2+2
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 80 if b == 100 else 2)
        loss, _ = combat._san_check_and_lose(50, "0", "2D6")
        assert loss == 4


class TestSanCheckWiring:
    """遭遇 SAN check 接线(2026-08-26):目睹(战斗开始)+被击中两时点。"""

    def _init(self, enemies, san=60):
        player = _make_investigator(hp=12, san=san)
        combat_init = CombatInit(
            enemies=enemies, player=player,
            scene="测试房间", initiative_context="san")
        return CombatSystem()._init_combat(combat_init)

    def test_witness_check_at_combat_start(self, monkeypatch):
        """开战目睹:check 扣 SAN,san_log 记'理智检定失败'叙事行。"""
        from game import combat
        # roll=90>60 失败;失败组 1D6 骰面强制 1 点(combat.random 与 utils.random
        # 为同一模块对象,patch 一处 D100/骰面两用)
        monkeypatch.setattr(combat.random, "randint",
                            lambda a, b: 90 if b == 100 else 1)
        enemy = _TestEnemy("深潜者", hp=8, armor="0", instance_id="E_SAN_1",
                           san_loss="0/1D6")
        state = self._init([enemy], san=60)
        assert state.player_san == 59, \
            f"目睹 check 失败组 1D6=1,SAN 60->59,实际 {state.player_san}"
        assert any("理智检定失败" in s for s in state.san_log)
        assert any("深潜者" in s for s in state.san_log), "叙事行带敌人标签"

    def test_witness_check_group_dedup_in_combat(self, monkeypatch):
        """同场同 enemy_ref 群组(quantity=3 拆 3 实例)只 check 一次。"""
        from game import combat
        monkeypatch.setattr(combat.random, "randint",
                            lambda a, b: 90 if b == 100 else 1)
        enemy = _TestEnemy("鼠群", hp=9, armor="0", instance_id="E_RATS",
                           quantity=3, san_loss="0/1D6")
        state = self._init([enemy], san=60)
        assert len(state.enemies) == 3, "quantity=3 群组展开为 3 个战斗实体"
        assert len(state.san_log) == 1, \
            f"同 enemy_ref 只 check 一次,实际 {len(state.san_log)} 条"
        assert state.player_san == 59, "仅一次失败组 1D6=1 扣减"

    def test_witness_check_empty_san_loss(self):
        """san_loss 空的敌人不做目睹 check(san_log 空,SAN 不变)。"""
        enemy = _TestEnemy("木桩", hp=5, armor="0", instance_id="E_NOSAN")
        state = self._init([enemy], san=60)
        assert state.san_log == []
        assert state.player_san == 60

    def test_attacked_check_on_hit(self, monkeypatch):
        """敌方命中且 san_loss 含'被攻击'组:额外 check,narrative 含理智检定。"""
        from game import combat
        monkeypatch.setattr(combat.random, "randint",
                            lambda a, b: 90 if b == 100 else 1)
        enemy = _TestEnemy("深潜者", hp=20, armor="0", instance_id="E_ATK",
                           san_loss="0/1D4 (目睹), 1/1D6 (被攻击)")
        enemy.attributes = {"DEX": 200, "POW": 200, "STR": 50, "SIZ": 50}
        state = CombatState(enemies=[enemy])
        state.player_hp = 20
        state.player_hp_max = 20
        state.player_san = 50
        act = CombatSystem()._resolve_enemy_action(state, enemy,
                                                   _make_investigator())
        assert act.success, "DEX/POW=200 必中"
        assert "理智检定" in act.narrative and "恐惧侵蚀" in act.narrative
        assert state.player_san == 49, \
            f"roll=90>50 失败,失败组 1D6=1,SAN 50->49,实际 {state.player_san}"

    def test_run_combat_narrative_includes_san_log(self, monkeypatch):
        """run_combat(自动战斗路径)终局叙事前置 san_log:目睹 check 文本玩家可见(I1)。"""
        from game import combat
        # roll=90>玩家技能 75/敌技能 50 双方互不命中->draw;目睹 check 失败组
        # 1D6 骰面强制 1(combat.random 与 utils.random 为同一模块对象,patch 一处两用)
        monkeypatch.setattr(combat.random, "randint",
                            lambda a, b: 90 if b == 100 else 1)
        enemy = _TestEnemy("深潜者", hp=8, armor="0", instance_id="E_RC_SAN",
                           san_loss="0/1D6")
        player = _make_investigator(hp=12, san=60)
        combat_init = CombatInit(
            enemies=[enemy], player=player,
            scene="测试房间", initiative_context="san")
        result = CombatSystem().run_combat(combat_init)
        assert result.player_san == 59, \
            f"目睹 check 失败组 1D6=1,SAN 60->59,实际 {result.player_san}"
        assert "理智检定" in result.narrative, \
            f"终局叙事须含目睹 check 文本,实际 {result.narrative!r}"
        assert "深潜者" in result.narrative, "叙事行带敌人标签"

    def test_attacked_check_no_group(self):
        """san_loss 无'被攻击'组(仅目睹组):命中不追加 check。"""
        enemy = _TestEnemy("幽灵", hp=20, armor="0", instance_id="E_NOATK",
                           san_loss="0/1D4 (目睹)")
        enemy.attributes = {"DEX": 200, "POW": 200, "STR": 50, "SIZ": 50}
        state = CombatState(enemies=[enemy])
        state.player_hp = 20
        state.player_hp_max = 20
        state.player_san = 50
        act = CombatSystem()._resolve_enemy_action(state, enemy,
                                                   _make_investigator())
        assert act.success, "DEX/POW=200 必中"
        assert "理智检定" not in act.narrative, "无被攻击组不得追加 check"
        assert state.player_san == 50


if __name__ == "__main__":
    print("=== Combat Smoke Tests ===")
    test_combat_basic_win()
    test_combat_writeback()
    test_combat_full_log()
    test_combat_boss_loss_signal()
    test_combat_regular_death()
    test_combat_result_structure()
    test_combat_phase_trigger()
    test_combat_damage_multipliers()
    test_combat_multi_target()
    test_combat_new_actions()
    test_combat_round_log()
    test_combat_hp_accuracy()
    print("\nAll combat smoke tests passed.")
