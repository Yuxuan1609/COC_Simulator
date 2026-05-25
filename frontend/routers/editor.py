"""frontend/routers/editor.py — Lightweight JSON module editor."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/editor", tags=["editor"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("", response_class=HTMLResponse)
async def editor_page(request: Request):
    return templates.TemplateResponse("editor.html", {"request": request})


@router.get("/load", response_class=HTMLResponse)
async def load_json(path: str = Query(...)):
    full = PROJECT_ROOT / path
    if not full.exists():
        return HTMLResponse('<p class="text-red-500 text-sm">文件不存在</p>')
    try:
        data = json.loads(full.read_text(encoding="utf-8"))
    except Exception as e:
        return HTMLResponse(f'<p class="text-red-500 text-sm">JSON 解析失败: {e}</p>')
    return HTMLResponse(_render_tree(data, path))


def _render_tree(data, filepath, indent=0):
    """Recursively render JSON as collapsible HTML tree."""
    if isinstance(data, dict):
        rows = ""
        for k, v in data.items():
            rows += f"""
            <details class="ml-{indent * 4}">
              <summary class="text-sm cursor-pointer hover:text-aged-gold py-0.5">
                <span class="text-gray-500">{k}:</span>
                <span class="text-gray-400">{_type_label(v)}</span>
              </summary>
              {_render_tree(v, filepath, indent + 1)}
            </details>"""
        return rows
    elif isinstance(data, list):
        rows = ""
        for i, item in enumerate(data):
            rows += f"""
            <details class="ml-{indent * 4}">
              <summary class="text-sm cursor-pointer hover:text-aged-gold py-0.5">
                <span class="text-gray-500">[{i}]:</span>
                <span class="text-gray-400">{_type_label(item)}</span>
              </summary>
              {_render_tree(item, filepath, indent + 1)}
            </details>"""
        return rows
    else:
        val_str = json.dumps(data, ensure_ascii=False)
        if len(val_str) > 80:
            val_str = val_str[:77] + "..."
        return f'<span class="text-sm text-gray-400 ml-{indent * 4}">{val_str}</span>'


def _type_label(v):
    if isinstance(v, dict):
        return f"{{{len(v)} keys}}"
    elif isinstance(v, list):
        return f"[{len(v)} items]"
    elif isinstance(v, bool):
        return "bool"
    elif isinstance(v, int):
        return "number"
    elif isinstance(v, str):
        return "string"
    return "null"
