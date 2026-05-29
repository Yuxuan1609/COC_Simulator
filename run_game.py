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
    _print_turn_output(initial.get("player_snapshot"), initial["brief"], initial["narrative"])

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

        _print_turn_output(result.get("player_snapshot"), result["brief"], result["narrative"])

        if ending:
            print("[info] 游戏结束。")
            break


def _build_scene_snapshot(world) -> dict | None:
    """从 world 构建 PlayerFacingSnapshot 格式的 dict。"""
    node = world.graph.nodes.get(world.current_location)
    if not node:
        return None
    return {
        "scene_name": world.current_location,
        "scene_description": node.description or "",
        "exits": [{"target": e.target, "method": e.method} for e in node.edges],
        "time": world.clock.to_dict(),
        "npcs": world.npcs.get_in_scene_snapshot(world.current_location) if world.npcs else [],
        "combat": None,
        "skill_checks": [],
    }


def _scene_text(world):
    """构建 Markdown 场景状态（/scene 命令用）。"""
    snap = _build_scene_snapshot(world)
    if not snap:
        return "（未知场景）"
    return _format_snapshot_chapters(snap)

def _g(obj, key, default=None):
    """Safe getter that works for both dicts and dataclass objects."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _format_snapshot_chapters(snap) -> str:
    """将 PlayerFacingSnapshot 格式化为半结构化 Markdown。
    
    输出示例:
    ## 场景
    6号车厢。车厢内弥漫着陈旧的气味...可以通往 7号车厢（向东走）。
    
    ## 角色
    京山人吉——瘦高男子，神色警惕。
    
    ## 时间
    第1天，夜间 04:30。
    
    ## 技能
    I1: 侦查检定 → 常规成功 (D100=45/50)
    """
    chapters = []
    
    # Scene
    name = _g(snap, "scene_name", "")
    desc = _g(snap, "scene_description", "")
    exits = _g(snap, "exits", [])
    scene_prose = name or "未知"
    if desc:
        scene_prose += f"。{desc.strip().rstrip('。')}"
    if exits:
        exit_labels = [f"{e.get('target','?')}（{e.get('method','?')}）" for e in exits]
        scene_prose += f"。可以通往{'、'.join(exit_labels)}"
    scene_prose += "。"
    chapters.append(f"## 场景\n{scene_prose}")
    
    # NPCs
    npcs = _g(snap, "npcs", [])
    if npcs:
        npc_prose = "、".join(
            f"{_g(n, 'name', '?')}——{_g(n, 'brief', '')}{'，'+_g(n,'demeanor','') if _g(n,'demeanor') else ''}"
            for n in npcs
        )
        chapters.append(f"## 角色\n{npc_prose}。")
    
    # Time — clock.to_dict() returns {"game_time": int, "time_context": str}
    t = _g(snap, "time", {})
    if t:
        parts = []
        gt = _g(t, "game_time", 0)
        day = gt // 1440 if gt else 0
        hour_val = (gt % 1440) // 60 if gt else 0
        min_val = gt % 60
        if day:
            parts.append(f"第{day}天")
        if hour_val < 5: tod = "夜间"
        elif hour_val < 8: tod = "早晨"
        elif hour_val < 17: tod = "白天"
        elif hour_val < 20: tod = "黄昏"
        else: tod = "夜间"
        parts.append(tod)
        parts.append(f"{hour_val:02d}:{min_val:02d}")
        if parts:
            chapters.append(f"## 时间\n{'，'.join(parts)}\u3002")
    
    # Combat
    combat = _g(snap, "combat")
    if combat:
        outcome = _g(combat, "outcome", "?")
        narrative = _g(combat, "narrative", "")
        chapters.append(f"## 战斗\n结果: {outcome}\u3002{narrative}")
    
    # Skills
    skill_checks = _g(snap, "skill_checks", [])
    if skill_checks:
        tier_labels = {"extreme": "极难成功", "hard": "困难成功", "regular": "常规成功",
                       "failure": "失败", "fumble": "大失败"}
        lines = []
        for sc in skill_checks:
            eid = _g(sc, "entity_id", "?")
            tier = _g(sc, "tier", "")
            tier_label = tier_labels.get(tier, tier or "?")
            raw = _g(sc, "raw_roll", 0)
            target = _g(sc, "target", 0)
            dice_str = f"（D100={raw}/{target}）" if raw else ""
            succ = "成功" if _g(sc, "success") else "失败"
            enh = _g(sc, "enhancement")
            enh_str = f"→特质增强为{_g(enh,'tier','')}" if enh and _g(enh, "tier") else ""
            lines.append(f"{eid}: {succ}，{tier_label}{dice_str}{'，'+enh_str if enh_str else ''}")
        chapters.append(f"## 技能\n" + "\n".join(lines))
    
    return "\n\n".join(chapters)

def _print_turn_output(snap, brief, narrative):
    """统一的回合输出：Narrator 叙事 + World Snapshot。"""
    output_parts = []
    
    if narrative:
        output_parts.append(f"## 叙事\n{narrative}")
    
    if snap:
        output_parts.append(_format_snapshot_chapters(snap))
    elif brief:
        output_parts.append(brief)
    
    print("\n\n" + "\n\n".join(output_parts))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TRPG 调查员助手 — 命令行游戏")
    parser.add_argument("--character", "-c", type=str, default=None,
                        help="调查员角色卡路径（默认：investigator/test_character.json）")
    args = parser.parse_args()
    run_game(character_path=args.character)
