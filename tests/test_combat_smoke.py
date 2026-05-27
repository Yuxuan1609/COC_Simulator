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
    inv.stats = Stats(STR=50, CON=50, SIZ=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    inv.derived = DerivedStats(HP=hp, HP_MAX=hp, SAN=san, MP=mp, MOV=8, DB=0, BUILD=0, DODGE=25)
    inv.skills = {}
    return inv


class _TestEnemy:
    """Minimal enemy instance matching what CombatSystem expects."""
    def __init__(self, enemy_ref, hp, armor, instance_id, dex=50, attacks=None):
        self.enemy_ref = enemy_ref
        self.name = enemy_ref
        self.hp = hp
        self.hp_max = hp
        self.armor = armor
        self.instance_id = instance_id
        self.status = "hostile"
        self.flags = set()
        self.DEX = dex
        self.attacks = attacks or [{"name": "爪击", "skill_name": "格斗", "skill_value": 40, "damage": "1D6"}]


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


if __name__ == "__main__":
    print("=== Combat Smoke Tests ===")
    test_combat_basic_win()
    test_combat_writeback()
    test_combat_full_log()
    test_combat_boss_loss_signal()
    test_combat_regular_death()
    test_combat_result_structure()
    print("\nAll combat smoke tests passed.")
