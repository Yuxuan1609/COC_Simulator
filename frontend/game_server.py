"""
frontend/game_server.py — TRPG 游戏 Web 服务器 + API。
用法:
    python frontend/game_server.py                 # http://localhost:8080
    python frontend/game_server.py --port 9000     # 自定义端口
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from game_loop import init_game, run_turn
from game.messages import ActionIntent
from prompts import set_prompt_log_dir, set_current_round
from llm import set_llm_log_dir
from library import WeaponLibrary, EnemyLibrary, ContentInjector
from scenario_core import ScenarioWorld
from trpg_display import render_scene_to_html
from investigator import load_investigator, Investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list

FRONTEND_DIR = Path(__file__).resolve().parent

_game = None
_game_lock = threading.Lock()
weapon_lib = None
enemy_lib = None
injector = None


def _init_libraries():
    global weapon_lib, enemy_lib, injector
    weapon_lib = WeaponLibrary()
    weapon_lib.load_core()
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()
    injector = ContentInjector(weapon_lib, enemy_lib)


def get_game():
    global _game
    if _game is None:
        with _game_lock:
            if _game is None:
                _game = _init_game_instance()
    return _game


def _init_game_instance():
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_dir = str(PROJECT_ROOT / f"logs/prompt_log_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)

    g = init_game(
        l2_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l2_test.json"),
        l1_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l1_test.json"),
        l3_path=str(PROJECT_ROOT / "data/modules/常暗之厢/l3_test.json"),
        start_node="测试房间",
    )

    char_path = str(PROJECT_ROOT / "investigator/test_character.json")
    if os.path.exists(char_path):
        inv = load_investigator(char_path)
    else:
        inv = Investigator(name="调查员A", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)

    g["keeper"].world.set_player(inv)
    return g


def _handle_command(cmd: str, world) -> dict:
    """Handle all debug commands. Returns {command:, text:, ...} for display."""
    parts = cmd.strip().split()
    c = parts[0].lower()

    # ── /scene ──
    if c == "/scene":
        html = render_scene_to_html(world)
        return {"command": "scene", "html": html}

    # ── /info ──
    if c == "/info":
        info = world.get_scene_info()
        return {"command": "info", "text": json.dumps(info, ensure_ascii=False, indent=2)}

    # ── /char ──
    if c == "/char":
        if world.player:
            return {"command": "char", "text": str(world.player)}
        return {"command": "char", "text": "未设置调查员"}

    # ── /flags ──
    if c == "/flags":
        items = []
        for eid, s in world.runtime_state.items():
            if s.completed:
                items.append(f"{eid}: tier={s.result_tier or '-'} retries={s.retries}")
        return {"command": "flags", "text": "\n".join(items) if items else "（无已完成实体）"}

    # ── /events ──
    if c == "/events":
        active = world.get_active_event_effects()
        if active:
            lines = [f"◆ {name}\n  {impact}" for name, impact in active]
            return {"command": "events", "text": "\n".join(lines)}
        return {"command": "events", "text": "（无已触发事件）"}

    # ── /help ──
    if c == "/help":
        return {"command": "help", "text": (
            "/scene | /info | /char | /flags | /events\n"
            "/do <动作名> | /trigger <E1>\n"
            "/spawn enemy <名> | /spawn weapon <名> | /inject [toggle|status]\n"
            "/save <槽位> | /load <槽位> | /reset | /help"
        )}

    # ── /do <动作名> ──
    if c == "/do":
        if len(parts) < 2:
            return {"command": "do", "text": "用法：/do <动作名>"}
        name = " ".join(parts[1:])
        node = world._current_node()
        if not node:
            return {"command": "do", "text": "当前场景不存在"}
        entity = None
        for e in node.interactions + node.auto_triggers:
            if e.name == name:
                entity = e
                break
        if not entity:
            available = [e.name for e in node.interactions + node.auto_triggers]
            return {"command": "do", "text": f"未找到「{name}」。可用：{', '.join(available)}"}
        from game.judge import Judge
        judge = Judge(world)
        intent = ActionIntent(action="interaction" if entity.entity_type == "interaction" else "other",
                              target=entity.name if entity.entity_type == "interaction" else "")
        outcome = judge._execute_entity(entity, intent=intent)
        return {"command": "do", "text": f"{'✓' if outcome.success else '✗'} [{entity.id}] {outcome.message}",
                "skill": {"entity_id": entity.id, "tier": outcome.skill_tier, "success": outcome.success}}

    # ── /trigger <E1> ──
    if c == "/trigger":
        if len(parts) < 2:
            return {"command": "trigger", "text": "用法：/trigger <事件ID>"}
        eid = parts[1].upper()
        entity = None
        for ev in world.graph.get_all_events():
            if ev.id == eid:
                entity = ev
                break
        if not entity:
            eids = [ev.id for ev in world.graph.get_all_events()]
            return {"command": "trigger", "text": f"未找到事件「{eid}」。可用：{', '.join(eids)}"}
        from game.judge import Judge
        judge = Judge(world)
        outcome = judge._execute_entity(entity)
        return {"command": "trigger", "text": f"触发 [{eid}] {outcome.message}"}

    # ── /spawn ──
    if c == "/spawn":
        if len(parts) < 3:
            return {"command": "spawn", "text": "用法：/spawn enemy <名称> 或 /spawn weapon <名称>"}
        sub = parts[1].lower()
        name = " ".join(parts[2:])
        if sub == "enemy":
            if not enemy_lib:
                return {"command": "spawn", "text": "敌人库未加载"}
            enemy = enemy_lib.get(name)
            if not enemy:
                available = [e.name for e in enemy_lib.list_all()]
                return {"command": "spawn", "text": f"未知敌人「{name}」。可用：{', '.join(available)}"}
            injector.runtime_spawn_enemy(name, world.current_location, world)
            return {"command": "spawn", "text": f"[生成敌人] {name} 在 {world.current_location}"}
        elif sub == "weapon":
            if not weapon_lib:
                return {"command": "spawn", "text": "武器库未加载"}
            weapon = weapon_lib.get(name)
            if not weapon:
                available = [w.name for w in weapon_lib.list_all()]
                return {"command": "spawn", "text": f"未知武器「{name}」。可用：{', '.join(available)}"}
            world.memory.note_item(name)
            return {"command": "spawn", "text": f"[授予武器] {name}"}
        else:
            return {"command": "spawn", "text": f"未知子命令「{sub}」"}

    # ── /inject ──
    if c == "/inject":
        if not injector:
            return {"command": "inject", "text": "注入器未初始化"}
        if len(parts) < 2:
            s = injector.status
            return {"command": "inject", "text": json.dumps(s, ensure_ascii=False)}
        sub = parts[1].lower()
        if sub == "toggle":
            injector.runtime_enabled = not injector.runtime_enabled
            return {"command": "inject", "text": f"运行时注入已{'开启' if injector.runtime_enabled else '关闭'}"}
        elif sub == "status":
            return {"command": "inject", "text": json.dumps(injector.status, ensure_ascii=False)}
        return {"command": "inject", "text": "用法：/inject [toggle|status]"}

    # ── /save /load ──
    if c == "/save":
        slot = parts[1] if len(parts) > 1 else "quick"
        path = str(PROJECT_ROOT / f"data/saves/{slot}.json")
        os.makedirs(str(PROJECT_ROOT / "data/saves"), exist_ok=True)
        world.save_state(path)
        return {"command": "save", "text": f"存档已保存至 saves/{slot}.json"}

    if c == "/load":
        slot = parts[1] if len(parts) > 1 else "quick"
        path = str(PROJECT_ROOT / f"data/saves/{slot}.json")
        if os.path.exists(path):
            new_world = ScenarioWorld.load_state(path)
            get_game()["keeper"].world = new_world
            return {"command": "load", "text": f"已从 saves/{slot}.json 读档"}
        return {"command": "load", "text": f"存档 saves/{slot}.json 不存在"}

    # ── /reset ──
    if c == "/reset":
        global _game
        with _game_lock:
            _game = _init_game_instance()
        return {"command": "reset", "text": "游戏已重置"}

    # ── unknown ──
    return {"command": "unknown", "text": f"未知命令「{c}」。输入 /help 查看可用命令。"}


class GameAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/state":
            self._handle_state()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/turn":
            self._handle_turn()
        elif self.path == "/api/reset":
            self._handle_reset()
        else:
            self.send_error(404, "Not Found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_turn(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body)
            user_input = data.get("input", "").strip()
        except json.JSONDecodeError:
            self._send_json({"error": "无效 JSON"}, 400)
            return

        if not user_input:
            self._send_json({"error": "输入不能为空"}, 400)
            return

        game = get_game()
        world = game["keeper"].world

        # Debug commands handled directly (no LLM)
        if user_input.startswith("/"):
            result = _handle_command(user_input, world)
            self._send_json(result)
            return

        # Normal turn via game_loop (with weapon/enemy/injector support)
        try:
            turn = run_turn(game, user_input,
                          weapon_lib=weapon_lib, enemy_lib=enemy_lib, injector=injector)
        except Exception as e:
            self._send_json({"error": f"回合处理失败: {e}"}, 500)
            return

        self._send_json({
            "brief": turn.get("brief", ""),
            "narrative": turn.get("narrative", ""),
            "timestamp": turn.get("timestamp", ""),
            "skill_results": turn.get("skill_results", []),
            "ending": turn.get("ending"),
        })

    def _handle_reset(self):
        global _game
        with _game_lock:
            _game = _init_game_instance()
        self._send_json({"ok": True})

    def _handle_state(self):
        game = get_game()
        world = game["keeper"].world
        self._send_json({
            "location": world.current_location,
            "description": world.get_current_description(),
            "exits": [{"target": e.target, "method": e.method} for e in world.get_possible_exits()],
            "player": {
                "name": world.player.name if world.player else "",
                "hp": world.player.derived.HP if world.player else 0,
                "san": world.player.derived.SAN if world.player else 0,
            } if world.player else None,
        })

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if "/api/" in str(args[0]):
            print(f"  [{self.command}] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="TRPG 游戏 Web 服务器")
    parser.add_argument("--port", type=int, default=8080, help="端口 (默认 8080)")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    _init_libraries()

    url = f"http://localhost:{args.port}/game.html"
    print()
    print("  ═══════════════════════════════════════")
    print("    TRPG 调查员助手 — 游戏服务器")
    print("  ═══════════════════════════════════════")
    print(f"  地址: {url}")
    print(f"  API:  POST /api/turn  GET /api/state")
    print(f"  武器库: {len(weapon_lib)} 件 | 敌人库: {len(enemy_lib)} 个")
    print(f"  按 Ctrl+C 停止")
    print()

    if not args.no_open:
        import subprocess
        import platform
        try:
            if platform.system() == "Windows":
                os.startfile(url)
            elif platform.system() == "Darwin":
                subprocess.run(["open", url])
            else:
                subprocess.run(["xdg-open", url])
        except Exception:
            pass

    server = HTTPServer(("localhost", args.port), GameAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
