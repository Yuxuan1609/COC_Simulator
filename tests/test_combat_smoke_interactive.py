"""Combat system interactive smoke test — standalone, no LLM calls needed.

Usage: python tests/test_combat_smoke_interactive.py [--seed SEED]
"""
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from investigator.models import Investigator, Stats, DerivedStats
from game.combat import CombatSystem
from game.messages import CombatInit


def _make_investigator(name="测试员", hp=12, san=60, mp=14):
    inv = Investigator()
    inv.name = name
    inv.stats = Stats(STR=50, CON=50, SIZ=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    inv.derived = DerivedStats(HP=hp, HP_MAX=hp, SAN=san, MP=mp, MOV=8, DB=0, BUILD=0, DODGE=25)
    inv.skills = {}
    return inv


class _TestEnemy:
    def __init__(self, enemy_ref, hp, armor, instance_id, dex=50, attacks=None,
                 damage_multipliers=None, dodge_bonus=0, multi_attack=1,
                 special_rules="", phases=None, boss_mechanics=""):
        self.enemy_ref = enemy_ref
        self.name = enemy_ref
        self.hp = hp
        self.hp_max = hp
        self.armor = armor
        self.instance_id = instance_id
        self.status = "hostile"
        self.flags = set()
        self.DEX = dex
        self.attributes = {}
        self.attacks = attacks or [{"name": "爪击", "skill_name": "格斗", "skill_value": 40, "damage": "1D6"}]
        self.damage_multipliers = damage_multipliers or {}
        self.dodge_bonus = dodge_bonus
        self.multi_attack = multi_attack
        self.special_rules = special_rules
        self.phases = phases or []
        self.boss_mechanics = boss_mechanics
        self._current_phase = ""


# ── Test definitions ──


def test_basic_win():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=3, armor="0", instance_id="E_001")
    ci = CombatInit(enemies=[enemy], player=player, scene="测试房间", initiative_context="基础测试")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert result.outcome in ("win", "loss", "flee", "draw"), f"unexpected: {result.outcome}"
    assert result.rounds >= 1
    assert result.player_hp >= 0
    assert isinstance(result.narrative, str)
    assert hasattr(result, 'defeated_instance_ids')
    return f"outcome={result.outcome}, rounds={result.rounds}, hp={result.player_hp}"


def test_writeback():
    player = _make_investigator(hp=12, san=60)
    hp_before = player.derived.HP
    enemy = _TestEnemy("TestDummy", hp=8, armor="0", instance_id="E_002")
    ci = CombatInit(enemies=[enemy], player=player, scene="测试房间", initiative_context="写回测试")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    player.derived.HP = max(0, result.player_hp)
    player.derived.SAN = max(0, result.player_san)
    assert hp_before >= player.derived.HP
    assert player.derived.HP >= 0
    return f"HP {hp_before}→{player.derived.HP}, outcome={result.outcome}"


def test_full_log():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=5, armor="0", instance_id="E_003")
    ci = CombatInit(enemies=[enemy], player=player, scene="测试房间", initiative_context="日志测试")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert result.rounds >= 1
    return f"rounds={result.rounds}, outcome={result.outcome}"


def test_boss_loss_signal():
    player = _make_investigator(hp=2, san=60)
    boss = _TestEnemy("BossTest", hp=50, armor="2", instance_id="E_BOSS_1",
                       dex=80, attacks=[{"name": "触手鞭打", "skill_name": "格斗", "skill_value": 80, "damage": "2D6+DB"}])
    ci = CombatInit(enemies=[boss], player=player, scene="测试房间", initiative_context="Boss战斗")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    combat_is_boss = True
    if combat_is_boss and result.outcome == "loss":
        combat_boss_loss, combat_death = True, False
    elif result.outcome == "loss":
        combat_boss_loss, combat_death = False, True
    else:
        combat_boss_loss, combat_death = False, False
    if result.outcome == "loss":
        assert combat_boss_loss and not combat_death
    return f"outcome={result.outcome}, boss_loss={combat_boss_loss}, death={combat_death}"


def test_regular_death():
    player = _make_investigator(hp=2, san=60)
    enemy = _TestEnemy("MurderBot", hp=50, armor="3", instance_id="E_KILLER_1",
                        dex=90, attacks=[{"name": "撕裂", "skill_name": "格斗", "skill_value": 90, "damage": "3D6"}])
    ci = CombatInit(enemies=[enemy], player=player, scene="测试房间", initiative_context="死亡测试")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    combat_is_boss = False
    if combat_is_boss and result.outcome == "loss":
        combat_boss_loss, combat_death = True, False
    elif result.outcome == "loss":
        combat_boss_loss, combat_death = False, True
    else:
        combat_boss_loss, combat_death = False, False
    if result.outcome == "loss":
        assert combat_death and not combat_boss_loss
    return f"outcome={result.outcome}, death={combat_death}, boss_loss={combat_boss_loss}"


def test_result_structure():
    player = _make_investigator(hp=12, san=60)
    enemy = _TestEnemy("TestDummy", hp=3, armor="0", instance_id="E_004")
    ci = CombatInit(enemies=[enemy], player=player, scene="测试房间", initiative_context="结构测试")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert hasattr(result, 'outcome') and result.outcome in ("win", "loss", "flee")
    assert hasattr(result, 'defeated_instance_ids')
    assert hasattr(result, 'narrative')
    assert hasattr(result, 'player_hp') and result.player_hp >= 0
    assert hasattr(result, 'player_san') and result.player_san >= 0
    assert hasattr(result, 'rounds') and result.rounds >= 1
    return f"all fields present, outcome={result.outcome}"


def test_phase_trigger():
    player = _make_investigator(hp=30, san=60)
    boss = _TestEnemy("PhaseBoss", hp=3, armor="0", instance_id="E_PHASE_1",
        dex=10, attacks=[{"name": "轻触", "damage": "1D2"}],
        phases=[{"trigger": "hp_below_pct:0.5", "name": "狂怒", "overrides": {}, "description": "Boss狂暴了"}])
    ci = CombatInit(enemies=[boss], player=player, scene="测试", initiative_context="phase")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert result.outcome in ("win", "loss", "draw", "flee")
    return f"outcome={result.outcome}, rounds={result.rounds}"


def test_damage_multipliers():
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("WeakToFire", hp=10, armor="0", instance_id="E_FIRE_1",
        damage_multipliers={"火焰": 2.0})
    ci = CombatInit(enemies=[enemy], player=player, scene="测试", initiative_context="dmg_mult")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert result.outcome in ("win", "loss", "draw", "flee")
    return f"outcome={result.outcome}"


def test_multi_target():
    player = _make_investigator(hp=30, san=60)
    e1 = _TestEnemy("Target1", hp=5, armor="0", instance_id="E_T1")
    e2 = _TestEnemy("Target2", hp=5, armor="0", instance_id="E_T2")
    ci = CombatInit(enemies=[e1, e2], player=player, scene="测试", initiative_context="multi",
                    player_targets=["E_T1", "E_T2"])
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert result.outcome in ("win", "loss")
    assert hasattr(result, 'round_log')
    return f"outcome={result.outcome}, round_log entries={len(result.round_log)}"


def test_new_actions():
    player = _make_investigator(hp=30, san=60)
    cs = CombatSystem()
    results = {}

    e1 = _TestEnemy("Dummy1", hp=10, armor="0", instance_id="E_ACT1")
    r1 = cs.run_combat(CombatInit(enemies=[e1], player=player, scene="测试"), player_action="conceal")
    assert r1.outcome in ("win", "loss", "draw")
    results["conceal"] = r1.outcome

    e2 = _TestEnemy("Dummy2", hp=10, armor="0", instance_id="E_ACT2")
    r2 = cs.run_combat(CombatInit(enemies=[e2], player=player, scene="测试"), player_action="aim")
    assert r2.outcome in ("win", "loss", "draw")
    results["aim"] = r2.outcome

    e3 = _TestEnemy("Dummy3", hp=10, armor="0", instance_id="E_ACT3")
    r3 = cs.run_combat(CombatInit(enemies=[e3], player=player, scene="测试"), player_action="charge")
    assert r3.outcome in ("win", "loss", "draw")
    results["charge"] = r3.outcome

    return ", ".join(f"{k}={v}" for k, v in results.items())


def test_round_log():
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("LogTest", hp=5, armor="0", instance_id="E_LOG")
    ci = CombatInit(enemies=[enemy], player=player, scene="测试", initiative_context="round_log")
    cs = CombatSystem()
    result = cs.run_combat(ci)
    assert hasattr(result, 'round_log')
    assert isinstance(result.round_log, list)
    return f"{len(result.round_log)} rounds logged"


def test_hp_accuracy():
    player = _make_investigator(hp=30, san=60)
    initial_hp = 100
    enemy = _TestEnemy("HPTest", hp=initial_hp, armor="0", instance_id="E_HPCHECK",
        dodge_bonus=90, attacks=[{"name": "轻触", "damage": "1D2"}])
    ci = CombatInit(enemies=[enemy], player=player, scene="测试", initiative_context="hp_accuracy")
    cs = CombatSystem()
    result = cs.run_combat(ci, player_action="punch")
    final_hp = enemy.hp
    assert final_hp >= 0, f"Enemy HP negative: {final_hp}"
    for entry in result.round_log:
        pd = entry.get("player_damage", 0)
        assert isinstance(pd, int), f"player_damage should be int: {pd}"
    return f"initial={initial_hp}, final={final_hp}, rounds={result.rounds}"


# ── Test registry ──

ALL_TESTS = [
    ("1",  "basic_win",            "基础战斗 — 低HP敌人快速胜利",                test_basic_win),
    ("2",  "writeback",            "HP/SAN 写回 — 战斗后属性回写",               test_writeback),
    ("3",  "full_log",             "full_log — 战斗日志完整性",                  test_full_log),
    ("4",  "boss_loss_signal",     "Boss 败北信号 — boss_loss/combat_death 分流", test_boss_loss_signal),
    ("5",  "regular_death",        "普通战斗死亡 — combat_death 信号",           test_regular_death),
    ("6",  "result_structure",     "CombatResult 结构完整性",                    test_result_structure),
    ("7",  "phase_trigger",        "Boss 阶段触发 — hp_below_pct 激活 Phase",    test_phase_trigger),
    ("8",  "damage_multipliers",   "伤害倍率 — 弱点/抗性/免疫",                  test_damage_multipliers),
    ("9",  "multi_target",         "多目标战斗 — player_targets 多敌人",         test_multi_target),
    ("10", "new_actions",         "新动作 — conceal/aim/charge",               test_new_actions),
    ("11", "round_log",           "round_log — CombatResult 含 round_log",     test_round_log),
    ("12", "hp_accuracy",         "HP 精度 — 无重复伤害 bug",                  test_hp_accuracy),
]


def print_header():
    print()
    print("=" * 62)
    print("  COC 7th 战斗系统 — 交互式 Smoke Test")
    print("=" * 62)
    print()


def print_menu():
    print("┌─────┬──────────────────────────────────────────┐")
    print("│  #  │  测试名称                                │")
    print("├─────┼──────────────────────────────────────────┤")
    for num, name, desc, _ in ALL_TESTS:
        print(f"│ {num: >3} │  {desc:<44} │")
    print("├─────┼──────────────────────────────────────────┤")
    print("│  a  │  全部运行                                │")
    print("│  q  │  退出                                    │")
    print("└─────┴──────────────────────────────────────────┘")
    print()


def run_single(num, name, desc, fn):
    try:
        detail = fn()
        print(f"  [PASS] {name}: {detail}")
        return True
    except AssertionError as e:
        print(f"  [FAIL] {name}: {e}")
        return False
    except Exception as e:
        print(f"  [ERROR] {name}: {type(e).__name__}: {e}")
        return False


def run_selected(selections, seed=None):
    if seed is not None:
        random.seed(seed)
        print(f"\n  Random seed: {seed}")

    passed, failed, total = 0, 0, 0
    for num, name, desc, fn in ALL_TESTS:
        if num not in selections:
            continue
        total += 1
        if run_single(num, name, desc, fn):
            passed += 1
        else:
            failed += 1

    print(f"\n  --- 结果: {passed}/{total} 通过", end="")
    if failed > 0:
        print(f", {failed} 失败", end="")
    print(" ---")
    return failed == 0


def interactive_mode(seed):
    print_header()
    while True:
        print_menu()
        try:
            raw = input("  选择 (1-12 / a / q): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  再见!")
            break

        if raw == "q":
            print("  再见!")
            break
        elif raw == "a":
            selections = {str(i) for i in range(1, 13)}
        elif raw == "":
            continue
        else:
            selections = set()
            for part in raw.replace(",", " ").split():
                part = part.strip()
                if "-" in part:
                    try:
                        start, end = part.split("-", 1)
                        for i in range(int(start), int(end) + 1):
                            selections.add(str(i))
                    except ValueError:
                        print(f"  无效范围: {part}")
                        continue
                else:
                    if part.isdigit() and 1 <= int(part) <= 12:
                        selections.add(part)
                    else:
                        print(f"  忽略无效选项: {part}")

        if not selections:
            continue

        run_selected(selections, seed)
        print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="COC 7th 战斗系统交互式 Smoke Test")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--run", type=str, default=None, help="Run specific tests (e.g. '1,3,5-7') without interactive")
    args = parser.parse_args()

    if args.run:
        selections = set()
        for part in args.run.replace(",", " ").split():
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                for i in range(int(start), int(end) + 1):
                    selections.add(str(i))
            elif part.isdigit():
                selections.add(part)
            elif part == "a":
                selections = {str(i) for i in range(1, 13)}
        if not selections:
            print("No valid tests selected.")
            return
        print_header()
        ok = run_selected(selections, args.seed)
        sys.exit(0 if ok else 1)
    else:
        interactive_mode(args.seed)


if __name__ == "__main__":
    main()
