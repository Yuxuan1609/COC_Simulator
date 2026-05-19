# ═══════════════════════════════════════════════════════════════
#  TRPG 调查员助手 —— 主流程 (Multi-Agent 架构)
#  ═══════════════════════════════════════════════════════════════
#  运行: python run_game.py
#  依赖: pip install openai ipython

import sys
import json
import os as _os
from datetime import datetime
from IPython.display import HTML, display

sys.path.insert(0, "src")

from game_loop import init_game, run_turn
from llm import set_llm_log_file
from prompts import set_prompt_log_file
from library import WeaponLibrary, EnemyLibrary, ContentInjector
from trpg_display import (
    display_narrative, display_scene, display_system, display_debug,
    display_input_area, render_scene_to_html, display_split_result,
)
from investigator import Investigator, load_investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list

# ═══════════════════════════════════════════════════════════════
#  Prompt 日志配置
# ═══════════════════════════════════════════════════════════════

PROMPT_LOG_FILE = f"logs/prompt_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
set_prompt_log_file(PROMPT_LOG_FILE)
set_llm_log_file(PROMPT_LOG_FILE)

# ═══════════════════════════════════════════════════════════════
#  武器/敌人库初始化
# ═══════════════════════════════════════════════════════════════

weapon_lib = WeaponLibrary()
weapon_lib.load_core()
enemy_lib = EnemyLibrary()
enemy_lib.load_core()
injector = ContentInjector(weapon_lib, enemy_lib)
display_system(
    f"武器库：{len(weapon_lib)} 件 | 敌人库：{len(enemy_lib)} 个 | "
    f"注入器：{'就绪' if injector else '未初始化'}",
    "info"
)

# ═══════════════════════════════════════════════════════════════
#  游戏主循环
# ═══════════════════════════════════════════════════════════════

def run_game(character_path: str = None):
    game = init_game(
        l2_path="data/modules/常暗之厢/l2_test.json",
        l1_path="data/modules/常暗之厢/l1_test.json",
        l3_path="data/modules/常暗之厢/l3_test.json",
        escalation_config_path="data/modules/常暗之厢/escalation_config.json",
        start_node="测试房间",
    )

    keeper = game["keeper"]
    world = keeper.world
    print(f"场景数：{len(world.graph.nodes)}, 事件数：{len(world.graph.events)}")

    # 加载调查员
    if character_path is None:
        character_path = "investigator/test_character.json"

    if _os.path.exists(character_path):
        investigator = load_investigator(character_path)
        display_system(
            f"已加载调查员：{investigator.name} | "
            f"职业：{investigator.occupation.name if investigator.occupation else '无'} | "
            f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}",
            "info"
        )
    else:
        display_system(f"未找到角色卡 {character_path}，掷骰生成默认调查员...", "warn")
        investigator = Investigator(name="调查员A", age=25, gender="男")
        investigator.stats = roll_stats()
        investigator.skills = create_skill_list()
        investigator.derived = calc_derived(investigator.stats, investigator.age)
        display_system(
            f"已生成调查员：{investigator.name} | "
            f"HP={investigator.derived.HP} SAN={investigator.derived.SAN}",
            "info"
        )

    world.set_player(investigator)
    _os.makedirs("data/saves", exist_ok=True)

    display_system("游戏开始。输入 /help 查看可用命令。", "info")
    display(HTML(render_scene_to_html(world)))

    # 开场
    initial = run_turn(game, "（游戏开始）")
    ts = initial.get("timestamp", "")
    if ts:
        display_system(f"[{ts}]", "info")
    display_split_result(initial["brief"], initial["narrative"])
    if initial.get("skill_results"):
        for sr in initial["skill_results"]:
            tier_label = {"extreme": "大成功", "hard": "困难成功", "regular": "成功",
                          "failure": "失败", "fumble": "大失败"}.get(sr["tier"], sr["tier"])
            detail = sr.get("detail", "")
            if detail:
                dice_line = detail.split("\n")[1] if "\n" in detail else detail
                display_system(f"[{sr['entity_id']}] {tier_label} | {dice_line.strip()}", "debug")
            else:
                display_system(f"[{sr['entity_id']}] 技能检定：{tier_label}", "debug")

    # 主循环
    while True:
        cmd = input("\n> ").strip()
        if not cmd:
            continue

        if cmd in ("exit", "quit"):
            display_system("游戏结束。", "info")
            break
        elif cmd.startswith("/scene"):
            display(HTML(render_scene_to_html(world)))
            continue
        elif cmd.startswith("/info"):
            display_system(json.dumps(world.get_scene_info(), ensure_ascii=False, indent=2), "debug")
            continue
        elif cmd.startswith("/events"):
            active = world.get_active_event_effects()
            if active:
                for name, impact in active:
                    display_system(f"◆ {name}\n  {impact}", "info")
            else:
                display_system("（无已触发事件）", "info")
            continue
        elif cmd.startswith("/flags"):
            rs = world.runtime_state
            if rs:
                items = []
                for eid, s in rs.items():
                    if s.completed:
                        items.append(f"{eid}: {'✓' if s.completed else '✗'} tier={s.result_tier or '-'} retries={s.retries}")
                display_system("已完成实体：\n" + "\n".join(items) if items else "（无）", "debug")
            else:
                display_system("（无运行时状态）", "debug")
            continue
        elif cmd.startswith("/char"):
            if world.player:
                display_system(str(world.player), "debug")
            else:
                display_system("（未设置调查员）", "warn")
            continue
        elif cmd.startswith("/save"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            world.save_state(path)
            display_system(f"存档已保存至 {path}", "info")
            continue
        elif cmd.startswith("/load"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            if _os.path.exists(path):
                from scenario_core import ScenarioWorld
                new_world = ScenarioWorld.load_state(path)
                keeper.world = new_world
                world = new_world
                display_system(f"已从 {path} 读档", "info")
                display(HTML(render_scene_to_html(world)))
            else:
                display_system(f"存档 {path} 不存在", "warn")
            continue
        elif cmd.startswith("/help"):
            display_system(
                "/scene 场景 | /info 状态 | /events 事件 | /flags 运行时状态\n"
                "/char 角色 | /trigger <E1> | /spawn enemy/weapon <名称>\n"
                "/save <槽位> | /load <槽位> | exit",
                "info"
            )
            continue

        # 正常回合
        result = run_turn(game, cmd)

        ending = result.get("ending")
        if ending:
            display_system(f"【结局触发】{ending['name']}：{ending['narrative']}", "warn")

        ts = result.get("timestamp", "")
        if ts:
            display_system(f"[{ts}]", "info")

        if result.get("skill_results"):
            for sr in result["skill_results"]:
                tier_label = {"extreme": "大成功", "hard": "困难成功", "regular": "成功",
                              "failure": "失败", "fumble": "大失败"}.get(sr["tier"], sr["tier"])
                emoji = "✓" if sr["success"] else "✗"
                detail = sr.get("detail", "")
                if detail:
                    dice_line = detail.split("\n")[1] if "\n" in detail else detail
                    display_system(f"{emoji} [{sr['entity_id']}] {tier_label} | {dice_line.strip()}", "debug")
                else:
                    display_system(f"{emoji} [{sr['entity_id']}] 技能检定：{tier_label}", "debug")

        display_split_result(result["brief"], result["narrative"])

        if ending:
            display_system("游戏结束。", "info")
            break


if __name__ == "__main__":
    run_game()
