"""
frontend/server.py — 本地开发服务器，提供前端静态文件 + LLM 描述生成 API。

用法:
    python frontend/server.py                # 默认 http://localhost:8080
    python frontend/server.py --port 9000    # 自定义端口
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# 确保项目路径在 sys.path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm import call_deepseek

FRONTEND_DIR = Path(__file__).resolve().parent


# ── 系统提示词 ──

SYSTEM_APPEARANCE = (
    "你是一个COC 7th TRPG角色外貌描述生成器。"
    "根据用户提供的关键词或概念，生成一段简洁的外貌描述（150字以内）。"
    "风格应契合克苏鲁神话1920年代背景，可包含发型、衣着、体态、面部特征等细节。"
    "仅输出描述文本，不要任何前缀、标签或解释。"
)

SYSTEM_DESCRIPTION = (
    "你是一个COC 7th TRPG角色个人描述生成器。"
    "根据用户提供的关键词或概念，生成一段简洁的角色个人描述（150字以内）。"
    "应体现角色的职业、性格、背景或独特习惯，帮助玩家快速定位角色。"
    "仅输出描述文本，不要任何前缀、标签或解释。"
)


class APIHandler(SimpleHTTPRequestHandler):
    """自定义请求处理器：/api/generate-description → LLM 调用，其余 → 静态文件。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_POST(self):
        if self.path == "/api/generate-description":
            self._handle_generate()
        else:
            self.send_error(404, "Not Found")

    def _handle_generate(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_json({"error": "无效 JSON"}, 400)
            return

        field_type = data.get("type", "")
        user_prompt = data.get("prompt", "").strip()

        if not user_prompt:
            self._send_json({"error": "prompt 不能为空"}, 400)
            return

        if field_type == "appearance":
            system = SYSTEM_APPEARANCE
        elif field_type == "description":
            system = SYSTEM_DESCRIPTION
        else:
            self._send_json({"error": f"未知 type '{field_type}'，允许: appearance, description"}, 400)
            return

        try:
            result = call_deepseek(
                user_prompt,
                json_mode=False,
                system=system,
                model="deepseek-v4-flash",
                thinking=False,
                max_tokens=300,
                temperature=0.7,
                max_retries=1,
            )
            text = str(result).strip()
            self._send_json({"text": text})
        except Exception as e:
            self._send_json({"error": f"LLM 调用失败: {e}"}, 500)

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        # 简洁日志
        if "/api/" in str(args[0]):
            print(f"  [{self.command}] {args[0]}")
        else:
            pass  # 抑制静态文件请求日志


def _open_browser(url: str):
    """使用系统默认浏览器打开 URL。"""
    import subprocess
    import platform
    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(url)
        elif system == "Darwin":
            subprocess.run(["open", url])
        else:
            subprocess.run(["xdg-open", url])
    except Exception:
        pass  # 静默失败，手动打开即可


def main():
    parser = argparse.ArgumentParser(description="角色卡前端开发服务器")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认: 8080)")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}/character.html"

    print()
    print("  ═══════════════════════════════════════")
    print("    COC 7th 调查员创建 — 车卡模拟器")
    print("  ═══════════════════════════════════════")
    print(f"  服务器: http://localhost:{args.port}")
    print(f"  API:    /api/generate-description (deepseek-v4-flash)")

    if not args.no_open:
        print(f"  浏览器将自动打开，如未弹出请手动访问上述地址")
        _open_browser(url)

    print(f"  按 Ctrl+C 停止")
    print()

    server = HTTPServer(("localhost", args.port), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  服务器已停止")
        server.server_close()


if __name__ == "__main__":
    main()
