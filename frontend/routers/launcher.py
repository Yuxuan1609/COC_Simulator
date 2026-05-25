"""frontend/routers/launcher.py — Launcher page: module gen wizard + config + navigation."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse

router = APIRouter(tags=["launcher"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DEFAULT_CONFIG = {
    "model": "deepseek-v4-pro",
    "thinking": True,
    "reasoning_effort": "high",
    "flash_model": "deepseek-v4-flash",
    "llm_timeout_ms": 120000,
    "llm_slow_threshold_ms": 30000,
    "combat_llm_enhancement": False,
    "debug_mode": False,
}


def _config_path() -> Path:
    return PROJECT_ROOT / "config.json"


def _load_config() -> dict:
    cp = _config_path()
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))
    return dict(DEFAULT_CONFIG)


def _save_config(data: dict) -> None:
    _config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
async def launcher_page(request: Request):
    config = _load_config()
    return templates.TemplateResponse("launcher.html", {
        "request": request,
        "config": config,
    })


@router.get("/launcher/tabs/{tab}", response_class=HTMLResponse)
async def launcher_tab(request: Request, tab: str):
    config = _load_config()
    if tab == "module-gen":
        return templates.TemplateResponse("partials/launcher-module-gen.html", {"request": request})
    elif tab == "config":
        return templates.TemplateResponse("partials/launcher-config.html", {
            "request": request,
            "config": config,
        })
    return HTMLResponse("<p class='text-red-500'>Unknown tab</p>", status_code=404)


@router.post("/api/config/save")
async def save_config(
    model: str = Form(...),
    thinking: str = Form("off"),
    reasoning_effort: str = Form("high"),
    flash_model: str = Form("deepseek-v4-flash"),
    llm_timeout_ms: int = Form(120000),
    llm_slow_threshold_ms: int = Form(30000),
    combat_llm_enhancement: str = Form("off"),
    debug_mode: str = Form("off"),
):
    data = {
        "model": model,
        "thinking": thinking == "on",
        "reasoning_effort": reasoning_effort,
        "flash_model": flash_model,
        "llm_timeout_ms": llm_timeout_ms,
        "llm_slow_threshold_ms": llm_slow_threshold_ms,
        "combat_llm_enhancement": combat_llm_enhancement == "on",
        "debug_mode": debug_mode == "on",
    }
    _save_config(data)
    return PlainTextResponse("配置已保存 ✓")


@router.get("/api/config/load")
async def load_config():
    return _load_config()
