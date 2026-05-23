"""
交互式战斗接入测试 —— 从 CombatInit 构造到 CombatResult 输出。

模拟完整的战斗入口链路：加载敌人库 → 创建调查员 → 构造 CombatInit →
进入战斗 → 每轮交互选择动作 → 直到战斗结束。

用法：
    cd tests && python test_combat_interactive.py
    cd tests && python test_combat_interactive.py --enemy Clicker
    cd tests && python test_combat_interactive.py --enemy 深潜者 --hp 15
"""
from __future__ import annotations
import sys, os, random

# Fix Unicode output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure src/ is importable from tests/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from investigator.models import Investigator, Stats, DerivedStats, Skill, Weapon
from investigator.rules import create_skill_list
from library.enemies import EnemyLibrary
from game.enemy_manager import EnemyManager
from game.messages import CombatInit, CombatResult
from game.combat import CombatSystem


# ═══════════════════════════════════════════════════════════════
# 模拟值：构造调查员
# ═══════════════════════════════════════════════════════════════

def _make_test_player(hp: int = 12, with_weapon: bool = True) -> Investigator:
    """Create a test Investigator with preset stats."""
    stats = Stats(
        STR=60, CON=55, SIZ=65, DEX=50,
        APP=40, INT=60, POW=55, EDU=70, LUCK=50,
    )
    derived = DerivedStats(
        HP=hp, MP=11, SAN=55, SAN_MAX=99,
        MOV=8, DB="+1D4", BUILD=1, DODGE=25,
    )
    skills = create_skill_list()
    # Boost combat skills
    for s in skills:
        if s.name == "格斗(拳)":
            s.value = 50
        elif s.name == "格斗(脚)":
            s.value = 40
        elif s.name == "闪避":
            s.value = 30

    weapons = []
    if with_weapon:
        weapons.append(Weapon(name="撬棍", skill_name="格斗", damage="1D8+DB"))
        # Set matching skill
        for s in skills:
            if s.name == "格斗":
                s.value = 50

    return Investigator(
        name="测试调查员", age=25, gender="男",
        stats=stats, derived=derived, skills=skills, weapons=weapons,
        personal_description="普通调查员，体力尚可，随身携带一根撬棍。"
    )


# ═══════════════════════════════════════════════════════════════
# 交互式战斗主循环
# ═══════════════════════════════════════════════════════════════

def run_interactive_combat(enemy_ref: str = "Clicker", player_hp: int = 12):
    """交互式战斗测试：从 CombatInit → CombatResult"""

    # 1. 加载敌人库
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()
    available = [e.name for e in enemy_lib.list_all()]
    if enemy_ref not in available:
        print(f"错误：敌人 '{enemy_ref}' 不在库中。可用：{', '.join(available)}")
        return

    # 2. 创建 EnemyManager + 生成敌人实例
    em = EnemyManager(enemy_lib)
    enemy_inst = em.spawn(enemy_ref, "测试场景", quantity=1)
    print(f"========================================")
    print(f"       COC 7th 战斗接入测试")
    print(f"----------------------------------------")
    print(f"  敌人：{enemy_inst.enemy_ref:<20s} HP≈{enemy_inst.hp}")
    print(f"  描述：{enemy_inst.description[:40]}")
    print(f"========================================")
    print()

    # 3. 创建调查员
    player = _make_test_player(hp=player_hp)

    # 4. 构造 CombatInit（模拟 Keeper.process_turn 产出）
    combat_init = CombatInit(
        enemies=[enemy_inst],
        player=player,
        scene="测试场景",
        initiative_context=f"测试：调查员遭遇{enemy_ref}",
    )

    # 5. 初始化战斗系统
    cs = CombatSystem()
    state = cs._init_combat(combat_init)
    alive_enemies = [e for e in state.enemies
                     if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']

    print("=== 战斗开始！===")
    print(f"玩家 HP: {state.player_hp}/{state.player_hp_max}")
    for e in alive_enemies:
        print(f"敌人 {e.enemy_ref}({e.instance_id[:8]}): HP≈{e.hp}")
    print()

    # 6. 交互式回合循环
    while not state.finished:
        alive_enemies = [e for e in state.enemies
                        if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_enemies:
            break

        target = alive_enemies[0].instance_id

        # 显示可用动作
        actions = cs._get_player_actions(player)
        print(f"--- 第 {state.round} 轮 ---")
        print(f"  玩家 HP: {state.player_hp}")
        for e in alive_enemies:
            print(f"  {e.enemy_ref}({e.instance_id[:8]}): HP≈{e.hp}")
        print()
        print("  可用动作：")
        for i, a in enumerate(actions):
            dmg = a.get("damage", "")
            info = f"技能={a['skill']}, 值={a['value']}"
            if dmg:
                info += f", 伤害={dmg}"
            print(f"    [{i}] {a['label']:<10s}  {info}")
        print()

        # 获取玩家选择
        choice = input("  选择动作编号（或 q 退出）: ").strip()
        if choice.lower() == "q":
            print("  退出战斗。")
            return
        try:
            idx = int(choice)
            if idx < 0 or idx >= len(actions):
                print(f"  无效编号，请输入 0-{len(actions)-1}")
                continue
        except ValueError:
            print("  请输入数字编号。")
            continue

        action_id = actions[idx]["id"]
        print(f"\n  >> 你选择了「{actions[idx]['label']}」")

        # 执行一轮
        round_actions = cs._process_round(state, player, action_id, target)
        print("  本轮行动：")
        for a in round_actions:
            actor_name = "你" if a.actor == "player" else f"敌人({a.actor[:8]})"
            result_icon = "+" if a.success else "-"
            print(f"    [{result_icon}] {actor_name}: {a.narrative}")
            if a.damage > 0:
                print(f"        -> 造成 {a.damage} 点伤害")
        print()

    # 7. 战斗结束
    result = CombatResult(
        outcome="win" if state.player_hp > 0 else "loss",
        defeated_instance_ids=[
            e.instance_id for e in combat_init.enemies
            if getattr(e, 'hp', 1) <= 0 or getattr(e, 'status', '') == 'dead'
        ],
        player_hp=state.player_hp,
        player_san=state.player_san,
        rounds=state.round,
    )

    print("=" * 40)
    print(f"  战斗结束！")
    print(f"  结果：{'胜利' if result.outcome == 'win' else '战败'}")
    print(f"  用时：{result.rounds} 轮")
    print(f"  玩家剩余 HP：{result.player_hp}")
    print(f"  击败敌人：{', '.join(id[:12] for id in result.defeated_instance_ids) or '(无)'}")
    print("=" * 40)
    return result


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="COC 7th 交互式战斗接入测试")
    parser.add_argument("--enemy", type=str, default="Clicker",
                        help="敌人名称（默认：Clicker）")
    parser.add_argument("--hp", type=int, default=12,
                        help="调查员 HP（默认：12）")
    parser.add_argument("--list", action="store_true",
                        help="列出可用敌人")
    args = parser.parse_args()

    if args.list:
        lib = EnemyLibrary()
        lib.load_core()
        for e in lib.list_all():
            print(f"  {e.name} — {e.type} — {e.description[:50]}")
    else:
        run_interactive_combat(enemy_ref=args.enemy, player_hp=args.hp)
