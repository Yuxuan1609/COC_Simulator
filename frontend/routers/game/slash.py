"""frontend/routers/game/slash.py — 斜杠命令。"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from frontend._paths import PROJECT_ROOT

router = APIRouter()

from . import session


def _handle_slash_command(cmd: str) -> str:
    """Handle slash commands synchronously, return HTML."""
    game = session.get_game()
    world = game["keeper"].world
    p = world.player
    cmd = cmd.strip().lower()
    lines = []
    if cmd == "/help":
        names = ["/scene", "/char", "/flags", "/events",
                 "/save <slot>", "/load <slot>", "/quit", "/reset", "/help"]
        lines = [f'<div class="text-xs text-gray-500">{"  ".join(names)}</div>']
    elif cmd == "/scene":
        loc = world.current_location
        desc = world.get_current_description()
        lines.append(f'<div class="font-bold text-aged-brown">{loc}</div>')
        lines.append(f'<div class="text-xs text-gray-500 mt-1">{desc}</div>')
        for e in world.get_possible_exits():
            lines.append(f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>')
    elif cmd == "/char":
        if p:
            lines.append(f'<div class="text-sm text-aged-gold">{p.name} (HP {p.derived.HP} SAN {p.derived.SAN})</div>')
            lines.append(f'<div class="text-xs text-gray-500">属性: {" ".join(f"{k}={getattr(p.stats,k,0)}" for k in ["STR","CON","SIZ","DEX","APP","INT","POW","EDU","LUCK"])}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">未设置调查员</div>')
    elif cmd == "/flags":
        rs = world.runtime_state or {}
        if rs:
            for k, v in rs.items():
                completed = v.get("completed") if isinstance(v, dict) else getattr(v, "completed", False)
                c = "text-green-400" if completed else "text-gray-500"
                if isinstance(v, dict):
                    desc = str(v)
                else:
                    desc = (f"completed={getattr(v, 'completed', False)} tier={getattr(v, 'result_tier', '')}"
                            f" retries={getattr(v, 'retries', 0)} esc={getattr(v, 'escalated_difficulty', '')}")
                lines.append(f'<div class="text-xs {c}">{k}: {desc}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无状态</div>')
    elif cmd == "/events":
        triggered = world.triggered_events or []
        if triggered:
            for ev in triggered:
                lines.append(f'<div class="text-xs text-gray-400">{ev}</div>')
        else:
            lines.append('<div class="text-xs text-gray-500">无已触发事件</div>')
    elif cmd.startswith("/save"):
        slot = cmd.replace("/save", "").strip() or "1"
        try:
            from game_loop import save_game
            save_game(game, str(PROJECT_ROOT / f"save_{slot}.json"))
            lines.append(f'<div class="text-xs text-green-400">已存档到 save_{slot}.json</div>')
        except Exception as e:
            lines.append(f'<div class="text-xs text-red-400">存档失败: {e}</div>')
    elif cmd.startswith("/load"):
        slot = cmd.replace("/load", "").strip() or "1"
        spath = str(PROJECT_ROOT / f"save_{slot}.json")
        if Path(spath).exists():
            try:
                from game_loop import load_game
                load_game(game, spath)
                lines.append(f'<div class="text-xs text-green-400">已从 save_{slot}.json 读档</div>')
            except Exception as e:
                lines.append(f'<div class="text-xs text-red-400">读档失败: {e}</div>')
        else:
            lines.append(f'<div class="text-xs text-gray-500">存档 save_{slot}.json 不存在</div>')
    elif cmd in ("/quit", "/exit"):
        session._game_instance = None
        session._game_quit = True
        lines.append('<div class="text-xs text-green-400">游戏已退出。返回启动页以重新开始。</div>')
    elif cmd == "/reset":
        session._game_instance = None
        session._game_quit = False
        lines.append('<div class="text-xs text-green-400">游戏已重置，刷新页面以重新开始</div>')
    else:
        lines.append(f'<div class="text-xs text-gray-500">未知命令: {cmd}。输入 /help 查看可用命令。</div>')
    return "".join(lines)


@router.post("/api/game/command", response_class=HTMLResponse)
async def game_command(cmd: str = Form(...)):
    return HTMLResponse(_handle_slash_command(cmd))

