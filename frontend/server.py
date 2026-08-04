"""
frontend/server.py — Unified FastAPI server for the TRPG assistant.
Intended to eventually replace frontend/server.py (old http.server) and frontend/game_server.py.

Usage:
    uvicorn frontend.server:app --reload --port 8080
    python frontend/server.py                # (local dev mode with webbrowser open)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path before local imports (for dev mode)
_proj = Path(__file__).resolve().parent.parent
if str(_proj) not in sys.path:
    sys.path.insert(0, str(_proj))

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Auto-create config_llm.py from template if missing
_src_dir = PROJECT_ROOT / "src"
_config_template = _src_dir / "config_llm.template.py"
_config_actual = _src_dir / "config_llm.py"
if _config_template.exists() and not _config_actual.exists():
    _config_actual.write_text(_config_template.read_text(encoding="utf-8"), encoding="utf-8")
    print("  [init] Created src/config_llm.py from template")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TRPG Assistant", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")
UPLOADS_DIR = FRONTEND_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
(UPLOADS_DIR / "avatars").mkdir(parents=True, exist_ok=True)

# Jinja2 template engine — used by all routers
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))

# Import and include routers (added in later tasks)
from frontend.routers import files
app.include_router(files.router)
from frontend.routers import launcher
app.include_router(launcher.router)
from frontend.routers import character
app.include_router(character.router)
from frontend.routers import game
app.include_router(game.router)
from frontend.routers import editor
app.include_router(editor.router)
from frontend.routers import assets
app.include_router(assets.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _open_app_window(url: str) -> None:
    try:
        import webview
    except ImportError:
        webview = None

    if webview is not None:
        webview.create_window(
            "TRPG 调查员助手", url,
            width=1280, height=800, min_size=(960, 600),
            text_select=True,
        )
        webview.start()
        return

    import shutil
    import subprocess
    import webbrowser

    candidates = [
        shutil.which("msedge"),
        shutil.which("chrome"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LocalAppData", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for exe in candidates:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe, f"--app={url}"])
            break
    else:
        webbrowser.open(url)

    print(f"服务运行中：{url}（按 Ctrl+C 停止）")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import threading
    import time
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    url = f"http://localhost:{port}"

    def start_server():
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    time.sleep(0.5)

    _open_app_window(url)
