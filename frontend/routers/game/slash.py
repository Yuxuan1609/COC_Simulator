"""frontend/routers/game/slash.py — 斜杠命令。"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Form

from frontend._paths import PROJECT_ROOT

router = APIRouter()

from . import session


def _handle_slash_command(cmd: str) -> dict:
    """Handle slash commands synchronously, return {text} plain text."""
    game = session.get_game()
    if not game:
        return {"text": "游戏已退出。请返回启动页重新开始。"}
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events",
                 "/save <slot>", "/load <slot>", "/quit", "/reset", "/help"]
        lines = ["  ".join(names)]
    elif cmd == "/scene":
        loc = world.current_location
        desc = world.get_current_description()
        lines.append(str(loc))
        lines.append(str(desc))
        for e in world.get_possible_exits():
            lines.append(f"→ {e.target}：{e.method}")
    elif cmd == "/char":
        if p:
            lines.append(f"{p.name} (HP {p.derived.HP} SAN {p.derived.SAN})")
            lines.append(
                "属性: "
                + " ".join(f"{k}={getattr(p.stats, k, 0)}"
                           for k in ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"])
            )
        else:
            lines.append("未设置调查员")
    elif cmd == "/flags":
        rs = world.runtime_state or {}
        if rs:
            for k, v in rs.items():
                if isinstance(v, dict):
                    desc = str(v)
                else:
                    desc = (
                        f"completed={getattr(v, 'completed', False)} "
                        f"tier={getattr(v, 'result_tier', '')} "
                        f"retries={getattr(v, 'retries', 0)} "
                        f"esc={getattr(v, 'escalated_difficulty', '')}"
                    )
                lines.append(f"{k}: {desc}")
        else:
            lines.append("无状态")
    elif cmd == "/events":
        triggered = world.triggered_events or []
        if triggered:
            for ev in triggered:
                lines.append(str(ev))
        else:
            lines.append("无已触发事件")
    elif cmd.startswith("/save"):
        slot = cmd.replace("/save", "").strip() or "1"
        try:
            from game_loop import save_game
            save_game(game, str(PROJECT_ROOT / f"save_{slot}.json"))
            lines.append(f"已存档到 save_{slot}.json")
        except Exception as e:
            lines.append(f"存档失败: {e}")
    elif cmd.startswith("/load"):
        slot = cmd.replace("/load", "").strip() or "1"
        spath = str(PROJECT_ROOT / f"save_{slot}.json")
        if Path(spath).exists():
            try:
                from game_loop import load_game
                load_game(game, spath)
                lines.append(f"已从 save_{slot}.json 读档")
            except Exception as e:
                lines.append(f"读档失败: {e}")
        else:
            lines.append(f"存档 save_{slot}.json 不存在")
    elif cmd in ("/quit", "/exit"):
        session._game_instance = None
        session._game_quit = True
        session._combat_sessions.clear()
        lines.append("游戏已退出。返回启动页以重新开始。")
    elif cmd == "/reset":
        session._game_instance = None
        session._game_quit = False
        session._combat_sessions.clear()
        lines.append("游戏已重置，刷新页面以重新开始")
    else:
        lines.append(f"未知命令: {cmd}。输入 /help 查看可用命令。")
    return {"text": "\n".join(lines)}


@router.post("/api/game/command")
async def game_command(cmd: str = Form(...)):
    return _handle_slash_command(cmd)
