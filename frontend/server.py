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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Auto-create config_llm.py from template if missing
_config_template = PROJECT_ROOT / "src" / "config_llm.template.py"
_config_actual = PROJECT_ROOT / "src" / "config_llm.py"
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

FRONTEND_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")

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


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    port = int(os.environ.get("PORT", 8080))
    url = f"http://localhost:{port}"
    print(f"  TRPG Assistant v2.0 → {url}")
    webbrowser.open(url)  # /launcher route to be added in Task 3
    uvicorn.run(app, host="127.0.0.1", port=port)
