# ═══════════════════════════════════════════════════════════════
#  TRPG 调查员助手 —— 主流程 (Multi-Agent 架构, CLI 纯文本)
#  ═══════════════════════════════════════════════════════════════
#  运行: python run_game.py
#  依赖: pip install openai

import sys
import json
import os as _os
from datetime import datetime

sys.path.insert(0, "src")

from game_loop import init_game, run_turn
from llm import set_llm_log_dir
from prompts import set_prompt_log_dir, set_current_round
from library import WeaponLibrary, EnemyLibrary, ContentInjector
from investigator import Investigator, load_investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list

# ═══════════════════════════════════════════════════════════════
#  Prompt 日志配置（按 agent/round 分目录）
# ═══════════════════════════════════════════════════════════════

_log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
_log_dir = f"logs/prompt_log_{_log_timestamp}"
_os.makedirs(_log_dir, exist_ok=True)
set_prompt_log_dir(_log_dir)
set_llm_log_dir(_log_dir)

from game.turn_logger import TurnLogger
from game_loop import set_turn_logger
set_turn_logger(TurnLogger(log_dir=_log_dir))

# ═══════════════════════════════════════════════════════════════
#  武器/敌人库初始化
# ═══════════════════════════════════════════════════════════════

weapon_lib = WeaponLibrary()
weapon_lib.load_core()
enemy_lib = EnemyLibrary()
enemy_lib.load_core()
injector = ContentInjector(weapon_lib, enemy_lib)
print(f"[info] 武器库：{len(weapon_lib)} 件 | 敌人库：{len(enemy_lib)} 个 | "
      f"注入器：{'就绪' if injector else '未初始化'}")

# ═══════════════════════════════════════════════════════════════
#  游戏主循环
# ═══════════════════════════════════════════════════════════════

def run_game(character_path: str = None):
    game = init_game(
        l2_path="data/modules/常暗更新/l2_keeper.json",
        l1_path="data/modules/常暗更新/l1_player.json",
        l3_path="data/modules/常暗更新/l3_designer.json",
        start_node="5号车厢",
    )

    keeper = game["keeper"]
    world = keeper.world
    print(f"场景数：{len(world.graph.nodes)}, 事件数：{len(world.graph.events)}")

    # 加载调查员
    if character_path is None:
        character_path = "investigator/test_character.json"

    if _os.path.exists(character_path):
        investigator = load_investigator(character_path)
        print(f"[info] 已加载调查员：{investigator.name} | "
              f"职业：{investigator.occupation.name if investigator.occupation else '无'} | "
              f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}")
    else:
        print(f"[warn] 未找到角色卡 {character_path}，掷骰生成默认调查员...")
        investigator = Investigator(name="调查员A", age=25, gender="男")
        investigator.stats = roll_stats()
        investigator.skills = create_skill_list()
        investigator.derived = calc_derived(investigator.stats, investigator.age)
        print(f"[info] 已生成调查员：{investigator.name} | "
              f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}")

    world.set_player(investigator)
    _os.makedirs("data/saves", exist_ok=True)

    print("[info] 游戏开始。输入 /help 查看可用命令。")
    print(f"\n── 当前场景 ──")
    print(_scene_text(world))

    # 开场
    initial = run_turn(game, "（游戏开始）")
    ts = initial.get("timestamp", "")
    if ts:
        print(f"[{ts}]")
    _print_snapshot(initial.get("player_snapshot"))
    _print_split(initial["brief"], initial["narrative"])

    # 主循环
    while True:
        try:
            cmd = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[info] 游戏结束。")
            break
        if not cmd:
            continue

        if cmd in ("exit", "quit", "/quit", "/exit"):
            print("[info] 游戏结束。")
            break
        elif cmd.startswith("/scene"):
            print(_scene_text(world))
            continue
        elif cmd.startswith("/info"):
            print(json.dumps(world.get_scene_info(), ensure_ascii=False, indent=2))
            continue
        elif cmd.startswith("/events"):
            active = world.get_active_event_effects()
            if active:
                for name, impact in active:
                    print(f"◆ {name}\n  {impact}")
            else:
                print("（无已触发事件）")
            continue
        elif cmd.startswith("/flags"):
            rs = world.runtime_state
            if rs:
                items = []
                for eid, s in rs.items():
                    if s.completed:
                        items.append(f"{eid}: {'✓' if s.completed else '✗'} tier={s.result_tier or '-'} retries={s.retries}")
                print("已完成实体：\n" + "\n".join(items) if items else "（无）")
            else:
                print("（无运行时状态）")
            continue
        elif cmd.startswith("/char"):
            if world.player:
                print(str(world.player))
            else:
                print("[warn] （未设置调查员）")
            continue
        elif cmd.startswith("/save"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            world.save_state(path)
            print(f"[info] 存档已保存至 {path}")
            continue
        elif cmd.startswith("/load"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            if _os.path.exists(path):
                from scenario_core import ScenarioWorld
                new_world = ScenarioWorld.load_state(path)
                keeper.world = new_world
                world = new_world
                print(f"[info] 已从 {path} 读档")
                print(_scene_text(world))
            else:
                print(f"[warn] 存档 {path} 不存在")
            continue
        elif cmd.startswith("/help"):
            print(
                "/scene 场景 | /info 状态 | /events 事件 | /flags 运行时状态\n"
                "/char 角色 | /trigger <E1> | /spawn enemy/weapon <名称>\n"
                "/save <槽位> | /load <槽位> | exit"
            )
            continue

        # 正常回合
        result = run_turn(game, cmd)

        ending = result.get("ending")
        if ending:
            print(f"\n【结局触发】{ending['name']}：{ending['narrative']}")

        ts = result.get("timestamp", "")
        if ts:
            print(f"[{ts}]")

        _print_snapshot(result.get("player_snapshot"))

        _print_split(result["brief"], result["narrative"])

        if ending:
            print("[info] 游戏结束。")
            break


def _scene_text(world):
    """构建纯文本场景描述。"""
    node = world.graph.nodes.get(world.current_location)
    if not node:
        return "（未知场景）"
    lines = [f"Location: {node.node_id}"]
    if node.description:
        lines.append(node.description)
    if node.edges:
        edges_str = ", ".join(f"{e.target} ({e.method})" for e in node.edges)
        lines.append(f"出口：{edges_str}")
    return "\n".join(lines)


def _print_snapshot(snap: dict):
    """打印 PlayerFacingSnapshot 辅助信息。"""
    if not snap:
        return
    # 场景
    name = snap.get("scene_name", "")
    desc = snap.get("scene_description", "")
    if name or desc:
        print(f"\n── {name or '当前场景'} ──")
        if desc:
            print(desc)
    # 出口
    exits = snap.get("exits", [])
    if exits:
        labels = [f"{e.get('target','?')} ({e.get('method','?')})" for e in exits]
        print(f"  出口: {', '.join(labels)}")
    # 时间
    t = snap.get("time", {})
    if t:
        parts = []
        if t.get("day"):
            parts.append(f"第{t['day']}天")
        if t.get("time_of_day"):
            parts.append(t["time_of_day"])
        if t.get("game_time_minutes"):
            h, m = divmod(t["game_time_minutes"], 60)
            parts.append(f"{h:02d}:{m:02d}")
        if parts:
            print(f"  时间: {' '.join(parts)}")
    # NPC
    npcs = snap.get("npcs", [])
    if npcs:
        names = [n.get("name", "?") for n in npcs]
        print(f"  NPC: {', '.join(names)}")
    # 战斗
    combat = snap.get("combat")
    if combat:
        outcome = combat.get("outcome", "")
        print(f"\n  ⚔ 战斗结果: {outcome}")
    # 技能检定
    skill_checks = snap.get("skill_checks", [])
    if skill_checks:
        tier_labels = {"extreme": "极难成功", "hard": "困难成功", "regular": "常规成功",
                       "failure": "失败", "fumble": "大失败"}
        for sc in skill_checks:
            eid = sc.get("entity_id", "?")
            tier = sc.get("tier", "")
            tier_label = tier_labels.get(tier, tier or "?")
            emoji = "✓" if sc.get("success") else "✗"
            raw_roll = sc.get("raw_roll", 0)
            target = sc.get("target", 0)
            dice_str = f"D100={raw_roll}/{target}" if raw_roll else ""
            enh = sc.get("enhancement")
            enh_str = f" → {enh.get('tier','')}" if enh and enh.get("tier") else ""
            print(f"  {emoji} 检定 [{eid}] {tier_label}  {dice_str}{enh_str}")


def _print_split(brief, narrative):
    """打印叙事输出：目前结果 → 沉浸式叙述。"""
    if brief:
        print(f"\n── 目前结果 ──")
        print(brief)
    if narrative:
        print(f"\n── 沉浸式输出 ──")
        print(narrative)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TRPG 调查员助手 — 命令行游戏")
    parser.add_argument("--character", "-c", type=str, default=None,
                        help="调查员角色卡路径（默认：investigator/test_character.json）")
    args = parser.parse_args()
    run_game(character_path=args.character)
