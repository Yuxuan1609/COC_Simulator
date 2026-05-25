# Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild all 4 frontend pages (Launcher, Character, Game, Editor) with FastAPI + HTMX + Tailwind CSS, replacing the existing vanilla HTML/CSS/JS + http.server prototype.

**Architecture:** Single FastAPI server (`frontend/server.py`) with APIRouter modules, Jinja2 templates with `base.html` inheritance, HTMX for declarative AJAX, Tailwind CDN for CSS. `frontend/` imports from `src/`, never reverse. Existing `src/` game engine unchanged.

**Tech Stack:** FastAPI, uvicorn, Jinja2, HTMX (~14KB script tag), Tailwind CSS v4 (CDN dev → standalone prod)

---

## File Structure

```
frontend/
├── server.py                  # FastAPI app entry — mount static, include routers, startup
├── routers/
│   ├── __init__.py
│   ├── launcher.py            # / + /api/pipeline/* + /api/config/*
│   ├── character.py           # /character + /character/* + /api/character/*
│   ├── game.py                # /game + /api/game/* + WS /api/game/progress
│   ├── editor.py              # /editor + /api/editor/*
│   └── files.py               # /api/files?dir=... (shared)
├── templates/
│   ├── base.html              # <html> shell — Tailwind CDN, layout skeleton, htmx script
│   ├── launcher.html          # Extends base — 3-zone launcher
│   ├── character.html         # Extends base — 3-step wizard
│   ├── game.html              # Extends base — visual-novel layout
│   ├── editor.html            # Extends base — 3-pane JSON editor
│   └── partials/
│       ├── file-browser.html  # Reusable directory listing
│       ├── step-indicator.html# WS-driven progress bar
│       ├── help-launcher.html
│       ├── help-character.html
│       ├── help-game.html
│       └── help-editor.html
├── static/
│   └── fonts/                 # Bundled Noto Serif SC woff2 (added later)
```

---

### Task 1: Project Scaffold

**Files:**
- Create: `frontend/routers/__init__.py`
- Create: `frontend/server.py`
- Create: `frontend/templates/base.html`
- Create: `requirements-dev.txt` (add fastapi, uvicorn, jinja2)

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p frontend/routers frontend/templates/partials frontend/static/fonts
```

- [ ] **Step 2: Create `frontend/routers/__init__.py`**

```python
# frontend/routers/__init__.py
```

- [ ] **Step 3: Write `frontend/server.py` — FastAPI skeleton**

```python
"""
frontend/server.py — Unified FastAPI server for the TRPG assistant.
Replaces frontend/server.py and frontend/game_server.py.

Usage:
    uvicorn frontend.server:app --reload --port 8080
    python frontend/server.py                # (production mode with webbrowser open)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

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

# Import and include routers (added in later tasks)
# from frontend.routers import launcher, character, game, editor, files
# app.include_router(launcher.router)
# ...


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    port = int(os.environ.get("PORT", 8080))
    url = f"http://localhost:{port}"
    print(f"  TRPG Assistant v2.0 → {url}")
    webbrowser.open(url + "/launcher")
    uvicorn.run(app, host="127.0.0.1", port=port)
```

- [ ] **Step 4: Write `frontend/templates/base.html` — root layout**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}TRPG 调查员助手{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            parchment: {
              DEFAULT: '#d4c5a0',
              light: '#e8dcc8',
              dark: '#1a1410',
            },
            aged: {
              gold: '#c9a060',
              brown: '#8b5a3c',
              dark: '#2a2418',
              darker: '#1f1a10',
            },
            coc: {
              red: '#8b3a3a',
              green: '#3a6b3a',
              dim: '#6b635a',
            },
          },
          fontFamily: {
            serif: ['Noto Serif SC', 'SimSun', 'serif'],
            mono: ['JetBrains Mono', 'Consolas', 'monospace'],
          },
        },
      },
    }
  </script>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <style>
    /* Base body style — dark parchment background */
    body { background: #0d0d0d; color: #c8c0b8; font-family: 'Noto Serif SC', 'SimSun', serif; }
    /* Crossfade transition for images */
    .image-crossfade { transition: opacity 0.5s ease-in-out; }
    .image-crossfade.switching { opacity: 0; }
    /* Slide-up panel animation */
    .slide-up-enter { transform: translateY(100%); transition: transform 0.3s ease-out; }
    .slide-up-enter.active { transform: translateY(0); }
    /* Highlight flash for new narrative */
    @keyframes narrative-flash {
      0% { background: rgba(201,168,76,0.1); }
      100% { background: transparent; }
    }
    .narrative-flash { animation: narrative-flash 1.5s ease-out; }
  </style>
  {% block head %}{% endblock %}
</head>
<body class="min-h-screen flex flex-col">
  {% block body %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Install dependencies**

```bash
pip install fastapi uvicorn jinja2
```

- [ ] **Step 6: Verify server starts**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
print('FastAPI app created:', app.title)
"
```

Expected: `FastAPI app created: TRPG Assistant`

- [ ] **Step 7: Commit**

```bash
git add frontend/server.py frontend/routers/__init__.py frontend/templates/base.html
git commit -m "feat: add FastAPI server scaffold + base template with Tailwind CDN + HTMX"
```

---

### Task 2: File Browser API + Component

**Files:**
- Create: `frontend/routers/files.py`
- Create: `frontend/templates/partials/file-browser.html`
- Modify: `frontend/server.py`

- [ ] **Step 1: Write `frontend/routers/files.py` — file listing API**

```python
"""frontend/routers/files.py — File browser API for navigating project directories."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api/files", tags=["files"])

ALLOWED_EXTENSIONS = {".json", ".docx", ".txt", ".pdf", ".md"}
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _safe_dir(directory: str) -> Path:
    raw = (PROJECT_ROOT / directory).resolve()
    if not str(raw).startswith(str(PROJECT_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal denied")
    if not raw.is_dir():
        raise HTTPException(status_code=404, detail=f"Not a directory: {directory}")
    return raw


@router.get("")
async def list_files(dir: str = Query(default="data")):
    base = _safe_dir(dir)
    items = list(base.iterdir())
    dirs = sorted(
        [{"name": d.name, "path": str(d.relative_to(PROJECT_ROOT))} for d in items if d.is_dir() and not d.name.startswith(".")],
        key=lambda x: x["name"],
    )
    files = sorted(
        [{"name": f.name, "path": str(f.relative_to(PROJECT_ROOT)), "ext": f.suffix}
         for f in items if f.is_file() and f.suffix in ALLOWED_EXTENSIONS],
        key=lambda x: x["name"],
    )
    parent = str(base.parent.relative_to(PROJECT_ROOT)) if base != PROJECT_ROOT else None
    current = str(base.relative_to(PROJECT_ROOT))
    return {"dirs": dirs, "files": files, "parent": parent, "current": current}
```

- [ ] **Step 2: Write `frontend/templates/partials/file-browser.html` — reusable component**

```html
{# Usage: {% include "partials/file-browser.html" with context %} #}
{# Requires: browser_id (unique), start_dir, allow_files (bool), allow_dirs (bool), multi_select (bool) #}
<div id="{{ browser_id }}-container"
     hx-get="/api/files?dir={{ start_dir }}"
     hx-trigger="load"
     hx-swap="innerHTML">
  <div class="text-sm text-gray-500">加载中...</div>
</div>

{# The listing fragment (returned by server on hx-get): #}
{% if listing is defined %}
<div id="{{ browser_id }}-listing" class="border border-gray-700 rounded bg-[#0d0d0d] text-sm">
  {# Breadcrumb #}
  <div class="flex items-center gap-1 px-2 py-1.5 border-b border-gray-800 text-xs text-gray-500">
    {% set parts = current.split('/') %}
    {% set cum = namespace(path='') %}
    {% for part in parts %}
      {% set cum.path = cum.path + '/' + part if cum.path else part %}
      <span class="text-gray-600">/</span>
      <button class="hover:text-aged-gold"
              hx-get="/api/files?dir={{ cum.path }}"
              hx-target="#{{ browser_id }}-listing"
              hx-swap="outerHTML">{{ part }}</button>
    {% endfor %}
  </div>

  {# Directories #}
  {% if allow_dirs %}
  {% for d in dirs %}
  <button class="flex items-center gap-2 w-full px-3 py-1.5 hover:bg-gray-800 text-left
                 {{ 'text-aged-gold bg-gray-800' if d.path == selected_dir else 'text-gray-400' }}"
          hx-get="/api/files?dir={{ d.path }}"
          hx-target="#{{ browser_id }}-listing"
          hx-swap="outerHTML">
    <span class="text-xs">📁</span> {{ d.name }}
  </button>
  {% endfor %}
  {% endif %}

  {# Files #}
  {% if allow_files %}
  {% for f in files %}
  <div class="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-800 cursor-pointer text-gray-400
              {{ 'text-aged-gold bg-gray-800' if f.path in selected_files else '' }}"
       {% if multi_select %}
       hx-post="/api/files/toggle?path={{ f.path }}&browser={{ browser_id }}"
       {% else %}
       onclick="document.getElementById('{{ browser_id }}-value').value='{{ f.path }}';
                this.closest('#{{ browser_id }}-listing').querySelectorAll('.selected').forEach(e=>e.classList.remove('selected'));
                this.classList.add('selected');"
       {% endif %}
       hx-target="#{{ browser_id }}-listing" hx-swap="outerHTML">
    <span class="text-xs">📄</span> {{ f.name }}
  </div>
  {% endfor %}
  {% endif %}

  {% if not dirs and not files %}
  <div class="px-3 py-3 text-gray-600 text-center">（空目录）</div>
  {% endif %}

  {# Selected indicator #}
  {% if selected_files %}
  <div class="px-3 py-1.5 border-t border-gray-800 text-xs text-aged-gold">
    已选: {{ selected_files | join(', ') }}
  </div>
  {% endif %}
</div>
{% endif %}

{# Hidden input to store selection #}
<input type="hidden" id="{{ browser_id }}-value" name="{{ browser_id }}" value="{{ selected_files[0] if selected_files else '' }}">
```

- [ ] **Step 3: Register files router in `frontend/server.py`**

Edit `frontend/server.py` — add after `app.mount(...)`:

```python
from frontend.routers import files
app.include_router(files.router)
```

- [ ] **Step 4: Test file API**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/api/files?dir=data/modules')
print(resp.status_code)
print(resp.json()['dirs'][:3])
"
```

Expected: 200 with directory listing.

- [ ] **Step 5: Commit**

```bash
git add frontend/routers/files.py frontend/templates/partials/file-browser.html frontend/server.py
git commit -m "feat: add file browser API + reusable HTMX component"
```

---

### Task 3: Launcher Page — Module Gen Wizard + Config + Nav

**Files:**
- Create: `frontend/routers/launcher.py`
- Create: `frontend/templates/launcher.html`
- Modify: `frontend/server.py`

- [ ] **Step 1: Write `frontend/routers/launcher.py`**

```python
"""frontend/routers/launcher.py — Launcher page: module gen wizard + config + navigation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["launcher"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Jinja2 setup
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
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("配置已保存 ✓")


@router.get("/api/config/load")
async def load_config():
    return _load_config()
```

- [ ] **Step 2: Write `frontend/templates/launcher.html`**

```html
{% extends "base.html" %}
{% block title %}TRPG 助手 — 启动{% endblock %}
{% block body %}
<div class="min-h-screen bg-[#0d0d0d] flex">
  {# Left: Navigation #}
  <nav class="w-56 border-r border-gray-800 bg-[#0f0f0f] flex flex-col p-4 gap-3">
    <h1 class="text-lg text-aged-gold font-bold tracking-wider border-b border-gray-800 pb-3">TRPG 助手</h1>
    <a href="/character" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded border border-transparent hover:border-gray-700">
      🎲 创建调查员
    </a>
    <a href="/game" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded border border-transparent hover:border-gray-700">
      📖 开始游戏
    </a>
    <a href="/editor" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded border border-transparent hover:border-gray-700">
      ✏️ JSON 编辑器
    </a>
  </nav>

  {# Right: Content area — two tabs #}
  <div class="flex-1 overflow-y-auto p-6">
    <div id="launcher-content"
         hx-get="/launcher/tabs/module-gen"
         hx-trigger="load"
         hx-swap="innerHTML">
      <p class="text-gray-500 text-sm">加载中...</p>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add tab switching endpoint to `launcher.py`**

```python
@router.get("/launcher/tabs/{tab}", response_class=HTMLResponse)
async def launcher_tab(request: Request, tab: str):
    config = _load_config()
    if tab == "module-gen":
        return templates.TemplateResponse("partials/launcher-module-gen.html", {
            "request": request,
        })
    elif tab == "config":
        return templates.TemplateResponse("partials/launcher-config.html", {
            "request": request,
            "config": config,
        })
```

- [ ] **Step 4: Create module gen tab partial**

Create `frontend/templates/partials/launcher-module-gen.html`:

```html
<div>
  <div class="flex gap-4 mb-6">
    <button class="px-4 py-1.5 text-sm border border-gray-700 rounded text-gray-400 hover:text-aged-gold hover:border-aged-gold bg-[#0f0f0f]"
            hx-get="/launcher/tabs/module-gen" hx-target="#launcher-content" hx-swap="innerHTML">
      模组生成
    </button>
    <button class="px-4 py-1.5 text-sm border border-gray-700 rounded text-gray-400 hover:text-aged-gold hover:border-aged-gold bg-[#0f0f0f]"
            hx-get="/launcher/tabs/config" hx-target="#launcher-content" hx-swap="innerHTML">
      参数配置
    </button>
  </div>

  <h2 class="text-xl text-aged-gold mb-4">模组生成向导</h2>

  <form hx-post="/api/pipeline/start" hx-target="#pipeline-progress" hx-swap="innerHTML"
        class="space-y-4 max-w-2xl">
    {# Source document #}
    <div>
      <label class="block text-sm text-gray-400 mb-1">源文档</label>
      <div class="flex gap-2">
        <input type="text" name="source" placeholder="data/常暗之厢.docx"
               class="flex-1 bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
        <button type="button"
                hx-get="/api/files?dir=data"
                hx-target="#file-browser-modal"
                hx-swap="innerHTML"
                onclick="document.getElementById('file-modal').classList.remove('hidden')"
                class="px-3 py-1.5 border border-gray-700 rounded text-xs text-gray-500 hover:text-aged-gold">
          浏览...
        </button>
      </div>
    </div>

    {# Module name #}
    <div>
      <label class="block text-sm text-gray-400 mb-1">模组名称</label>
      <input type="text" name="module_name" placeholder="例如：常暗之厢"
             class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
    </div>

    {# Output directory #}
    <div>
      <label class="block text-sm text-gray-400 mb-1">输出目录</label>
      <input type="text" name="output_dir" value="data/modules/"
             class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
    </div>

    {# Pipeline steps #}
    <div>
      <label class="block text-sm text-gray-400 mb-1">管线步骤</label>
      <select name="start_from" class="bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300">
        <option value="step_1a">完整生成（从 Step 1a 开始）</option>
        <option value="step_2a">从 Step 2a 续跑</option>
        <option value="step_3a">从 Step 3a 续跑</option>
        <option value="step_3b">仅交叉核对</option>
      </select>
    </div>

    <button type="submit"
            class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30">
      开始生成
    </button>
  </form>

  {# Progress area #}
  <div id="pipeline-progress" class="mt-6"></div>

  {# File browser modal (hidden by default) #}
  <div id="file-modal" class="hidden fixed inset-0 bg-black/60 z-50 flex items-center justify-center"
       onclick="if(event.target===this)this.classList.add('hidden')">
    <div id="file-browser-modal" class="bg-[#141414] border border-gray-700 rounded-lg p-4 w-[500px] max-h-[70vh] overflow-y-auto">
      <!-- Populated by HTMX -->
    </div>
  </div>
</div>
```

- [ ] **Step 5: Create config tab partial**

Create `frontend/templates/partials/launcher-config.html`:

```html
<div>
  <div class="flex gap-4 mb-6">
    <button class="px-4 py-1.5 text-sm border border-gray-700 rounded text-gray-400 hover:text-aged-gold hover:border-aged-gold bg-[#0f0f0f]"
            hx-get="/launcher/tabs/module-gen" hx-target="#launcher-content" hx-swap="innerHTML">
      模组生成
    </button>
    <button class="px-4 py-1.5 text-sm border border-gray-700 rounded text-gray-400 hover:text-aged-gold hover:border-aged-gold bg-[#0f0f0f]"
            hx-get="/launcher/tabs/config" hx-target="#launcher-content" hx-swap="innerHTML">
      参数配置
    </button>
  </div>

  <h2 class="text-xl text-aged-gold mb-4">参数配置</h2>

  <form hx-post="/api/config/save" hx-target="#config-result" hx-swap="innerHTML"
        class="space-y-4 max-w-xl">
    <div>
      <label class="block text-sm text-gray-400 mb-1">模型</label>
      <select name="model" class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300">
        <option value="deepseek-v4-pro" {{ 'selected' if config.model == 'deepseek-v4-pro' }}>deepseek-v4-pro</option>
        <option value="deepseek-v4-flash" {{ 'selected' if config.model == 'deepseek-v4-flash' }}>deepseek-v4-flash</option>
      </select>
    </div>

    <div class="flex items-center gap-4">
      <label class="flex items-center gap-2 text-sm text-gray-400">
        <input type="checkbox" name="thinking" {{ 'checked' if config.thinking }} class="accent-aged-brown">
        Thinking 模式
      </label>
      <select name="reasoning_effort" class="bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1 text-xs text-gray-300">
        <option value="low" {{ 'selected' if config.reasoning_effort == 'low' }}>low</option>
        <option value="medium" {{ 'selected' if config.reasoning_effort == 'medium' }}>medium</option>
        <option value="high" {{ 'selected' if config.reasoning_effort == 'high' }}>high</option>
        <option value="max" {{ 'selected' if config.reasoning_effort == 'max' }}>max</option>
      </select>
    </div>

    <div>
      <label class="block text-sm text-gray-400 mb-1">Flash 模型</label>
      <input type="text" name="flash_model" value="{{ config.flash_model }}"
             class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div>
        <label class="block text-sm text-gray-400 mb-1">LLM 超时 (ms)</label>
        <input type="number" name="llm_timeout_ms" value="{{ config.llm_timeout_ms }}"
               class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300">
      </div>
      <div>
        <label class="block text-sm text-gray-400 mb-1">慢调用阈值 (ms)</label>
        <input type="number" name="llm_slow_threshold_ms" value="{{ config.llm_slow_threshold_ms }}"
               class="w-full bg-[#0d0d0d] border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-300">
      </div>
    </div>

    <div class="flex items-center gap-4">
      <label class="flex items-center gap-2 text-sm text-gray-400">
        <input type="checkbox" name="combat_llm_enhancement" {{ 'checked' if config.combat_llm_enhancement }} class="accent-aged-brown">
        Combat LLM 增强
      </label>
      <label class="flex items-center gap-2 text-sm text-gray-400">
        <input type="checkbox" name="debug_mode" {{ 'checked' if config.debug_mode }} class="accent-aged-brown">
        调试模式
      </label>
    </div>

    <button type="submit"
            class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30">
      保存配置
    </button>
    <span id="config-result" class="text-sm text-gray-500"></span>
  </form>
</div>
```

- [ ] **Step 6: Register launcher router in `frontend/server.py`**

```python
from frontend.routers import launcher
app.include_router(launcher.router)
```

- [ ] **Step 7: Verify launcher page renders**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/')
print(resp.status_code)  # 200
print('launcher' in resp.text)  # True
"
```

Expected: 200, True.

- [ ] **Step 8: Commit**

```bash
git add frontend/routers/launcher.py frontend/templates/launcher.html frontend/templates/partials/launcher-module-gen.html frontend/templates/partials/launcher-config.html frontend/server.py
git commit -m "feat: add launcher page — module gen wizard + config tabs + nav"
```

---

### Task 4: Character Creation — 3-Step Wizard

**Files:**
- Create: `frontend/routers/character.py`
- Create: `frontend/templates/character.html`
- Modify: `frontend/server.py`

- [ ] **Step 1: Write `frontend/routers/character.py`**

```python
"""frontend/routers/character.py — Character creation wizard API."""
from __future__ import annotations

import json
import random
from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

router = APIRouter(prefix="/character", tags=["character"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Skill base values (mirror of COC 7th) ──
SKILLS = [
    {"name": "会计", "base": 5, "cat": "知识"}, {"name": "人类学", "base": 1, "cat": "知识"},
    {"name": "估价", "base": 5, "cat": "知识"}, {"name": "考古学", "base": 1, "cat": "知识"},
    {"name": "魅惑", "base": 15, "cat": "社交"}, {"name": "攀爬", "base": 20, "cat": "操作"},
    {"name": "信用评级", "base": 0, "cat": "社交"}, {"name": "克苏鲁神话", "base": 0, "cat": "知识"},
    {"name": "乔装", "base": 5, "cat": "社交"}, {"name": "汽车驾驶", "base": 20, "cat": "操作"},
    {"name": "电气维修", "base": 10, "cat": "操作"}, {"name": "电子学", "base": 1, "cat": "知识"},
    {"name": "话术", "base": 5, "cat": "社交"}, {"name": "格斗", "base": 25, "cat": "战斗"},
    {"name": "枪械", "base": 20, "cat": "战斗"}, {"name": "急救", "base": 30, "cat": "操作"},
    {"name": "历史", "base": 5, "cat": "知识"}, {"name": "恐吓", "base": 15, "cat": "社交"},
    {"name": "跳跃", "base": 20, "cat": "操作"}, {"name": "外语", "base": 1, "cat": "知识"},
    {"name": "母语", "base": 50, "cat": "知识"}, {"name": "法律", "base": 5, "cat": "知识"},
    {"name": "图书馆使用", "base": 20, "cat": "知识"}, {"name": "聆听", "base": 20, "cat": "感知"},
    {"name": "锁匠", "base": 1, "cat": "操作"}, {"name": "机械维修", "base": 10, "cat": "操作"},
    {"name": "医学", "base": 1, "cat": "知识"}, {"name": "博物学", "base": 10, "cat": "知识"},
    {"name": "导航", "base": 10, "cat": "知识"}, {"name": "神秘学", "base": 5, "cat": "知识"},
    {"name": "操作重型机械", "base": 1, "cat": "操作"}, {"name": "说服", "base": 10, "cat": "社交"},
    {"name": "驾驶", "base": 20, "cat": "操作"}, {"name": "心理学", "base": 10, "cat": "感知"},
    {"name": "精神分析", "base": 1, "cat": "知识"}, {"name": "骑术", "base": 5, "cat": "操作"},
    {"name": "科学", "base": 1, "cat": "知识"}, {"name": "妙手", "base": 10, "cat": "操作"},
    {"name": "潜行", "base": 20, "cat": "操作"}, {"name": "侦查", "base": 25, "cat": "感知"},
    {"name": "生存", "base": 10, "cat": "操作"}, {"name": "游泳", "base": 20, "cat": "操作"},
    {"name": "投掷", "base": 20, "cat": "战斗"}, {"name": "追踪", "base": 10, "cat": "感知"},
]

STATS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
STAT_LABELS = {"STR": "力量", "CON": "体质", "SIZ": "体型", "DEX": "敏捷", "APP": "外貌",
               "INT": "智力", "POW": "意志", "EDU": "教育", "LUCK": "幸运"}
STAT_ROLLS = {
    "STR": (3, 0), "CON": (3, 0), "DEX": (3, 0), "APP": (3, 0), "POW": (3, 0),
    "SIZ": (2, 6), "INT": (2, 6), "EDU": (2, 6), "LUCK": (3, 0),
}


def _load_occupations():
    path = PROJECT_ROOT / "data" / "occupations.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def _roll_stat(dice: int, add: int) -> int:
    return (sum(random.randint(1, 6) for _ in range(dice)) + add) * 5


@router.get("", response_class=HTMLResponse)
async def character_page(request: Request):
    return templates.TemplateResponse("character.html", {
        "request": request,
        "skills": SKILLS,
        "stats": STATS,
        "stat_labels": STAT_LABELS,
        "occupations": _load_occupations(),
    })


@router.get("/step/{n}", response_class=HTMLResponse)
async def step_partial(request: Request, n: int):
    if n == 1:
        return templates.TemplateResponse("partials/char-step1.html", {
            "request": request, "stats": STATS, "stat_labels": STAT_LABELS, "stat_rolls": STAT_ROLLS,
        })
    elif n == 2:
        return templates.TemplateResponse("partials/char-step2.html", {
            "request": request, "skills": SKILLS, "occupations": _load_occupations(),
        })
    elif n == 3:
        return templates.TemplateResponse("partials/char-step3.html", {"request": request})
    return HTMLResponse("<p class='text-red-500'>Invalid step</p>", status_code=404)


@router.post("/roll", response_class=HTMLResponse)
async def roll_stats():
    import random as _r
    values = {s: _roll_stat(*STAT_ROLLS[s]) for s in STATS}
    # Derived stats
    hp = (values["CON"] + values["SIZ"]) // 10
    mp = values["POW"] // 5
    san = values["POW"]
    dodge = values["DEX"] // 2
    ss = values["STR"] + values["SIZ"]
    if ss <= 64: db, build = "-2", -2
    elif ss <= 84: db, build = "-1", -1
    elif ss <= 124: db, build = "0", 0
    elif ss <= 164: db, build = "+1D4", 1
    elif ss <= 204: db, build = "+1D6", 2
    else: db, build = "+2D6", 3

    cells = "".join(
        f'<div class="stat-card p-3 bg-[#1a150c] border border-[#3a2810] rounded text-center">'
        f'<div class="text-xs text-gray-500">{STAT_LABELS[s]} ({s})</div>'
        f'<div class="text-2xl font-bold text-aged-gold">{values[s]}</div>'
        f'</div>'
        for s in STATS
    )
    derived = f'<div class="grid grid-cols-4 gap-2 text-xs"><div>HP {hp}</div><div>MP {mp}</div><div>SAN {san}</div><div>DODGE {dodge}</div><div>DB {db}</div><div>BUILD {build}</div></div>'
    return HTMLResponse(f'<div class="grid grid-cols-3 gap-3">{cells}</div><div class="mt-4 p-3 bg-[#1a150c] border border-[#3a2810] rounded">{derived}</div>')
```

- [ ] **Step 2: Write `frontend/templates/character.html` — wizard shell**

```html
{% extends "base.html" %}
{% block title %}COC 7th — 创建调查员{% endblock %}
{% block body %}
<div class="min-h-screen bg-[#0d0d0d] max-w-3xl mx-auto py-8 px-4">
  <h1 class="text-2xl text-aged-gold text-center tracking-widest border-b border-gray-800 pb-4 mb-6">
    调查员创建
  </h1>

  {# Progress bar #}
  <div class="flex justify-between mb-8 px-8" id="wizard-progress">
    <span class="step-dot text-sm px-4 py-1 rounded {{ 'text-aged-gold bg-aged-brown/20 border border-aged-gold/30' if step|default(1) == 1 else 'text-gray-600' }}"
          id="step-dot-1">1. 基本信息 & 属性</span>
    <span class="step-dot text-sm px-4 py-1 rounded {{ 'text-aged-gold bg-aged-brown/20 border border-aged-gold/30' if step|default(1) == 2 else 'text-gray-600' }}"
          id="step-dot-2">2. 职业 & 技能</span>
    <span class="step-dot text-sm px-4 py-1 rounded {{ 'text-aged-gold bg-aged-brown/20 border border-aged-gold/30' if step|default(1) == 3 else 'text-gray-600' }}"
          id="step-dot-3">3. 预览 & 导出</span>
  </div>

  {# Step content (loaded via HTMX) #}
  <div id="step-content"
       hx-get="/character/step/1"
       hx-trigger="load"
       hx-swap="innerHTML">
    <p class="text-gray-500 text-sm">加载中...</p>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Create step 1 partial**

Create `frontend/templates/partials/char-step1.html`:

```html
<div>
  <h2 class="text-lg text-aged-gold mb-4 border-l-2 border-aged-gold pl-3">基本信息</h2>
  <div class="grid grid-cols-3 gap-4 mb-6">
    <div>
      <label class="block text-xs text-gray-500 mb-1">姓名</label>
      <input type="text" name="name" placeholder="调查员姓名"
             class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
    </div>
    <div>
      <label class="block text-xs text-gray-500 mb-1">年龄</label>
      <input type="number" name="age" value="25" min="15" max="99"
             class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300 focus:border-aged-gold focus:outline-none">
    </div>
    <div>
      <label class="block text-xs text-gray-500 mb-1">性别</label>
      <select name="gender" class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300">
        <option value="">选择...</option>
        <option value="男">男</option>
        <option value="女">女</option>
        <option value="其他">其他</option>
      </select>
    </div>
  </div>

  <div class="mb-4">
    <label class="block text-xs text-gray-500 mb-1">外貌描述 <span class="text-gray-700">(输入 /llm 自动生成)</span></label>
    <textarea name="appearance" rows="2" placeholder="外貌描述..."
              class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300 focus:border-aged-gold focus:outline-none resize-none"></textarea>
  </div>
  <div class="mb-6">
    <label class="block text-xs text-gray-500 mb-1">个人描述 <span class="text-gray-700">(输入 /llm 自动生成)</span></label>
    <textarea name="description" rows="2" placeholder="个人描述..."
              class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300 focus:border-aged-gold focus:outline-none resize-none"></textarea>
  </div>

  <h2 class="text-lg text-aged-gold mb-4 border-l-2 border-aged-gold pl-3">属性掷骰</h2>
  <button hx-post="/character/roll" hx-target="#roll-result" hx-swap="innerHTML"
          class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30 mb-4">
    🎲 掷骰生成
  </button>
  <div id="roll-result" class="mb-6">
    <p class="text-sm text-gray-600">点击上方按钮生成属性</p>
  </div>

  <div class="flex justify-end">
    <button hx-get="/character/step/2" hx-target="#step-content" hx-swap="innerHTML"
            onclick="document.getElementById('step-dot-1').className='text-gray-600 text-sm px-4 py-1 rounded';document.getElementById('step-dot-2').className='text-aged-gold bg-aged-brown/20 border border-aged-gold/30 text-sm px-4 py-1 rounded'"
            class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30">
      下一步 →
    </button>
  </div>
</div>
```

- [ ] **Step 4: Create step 2 + step 3 partials**

Create `frontend/templates/partials/char-step2.html` (skills):

```html
<div>
  <h2 class="text-lg text-aged-gold mb-4 border-l-2 border-aged-gold pl-3">职业与技能</h2>
  <div class="mb-4">
    <label class="block text-xs text-gray-500 mb-1">职业</label>
    <select name="occupation" class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300"
            hx-get="/character/skills-list" hx-target="#skills-list" hx-trigger="change" hx-include="this">
      <option value="">选择职业...</option>
      {% for occ in occupations %}
      <option value="{{ occ.name }}">{{ occ.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div id="skills-list" class="text-sm text-gray-600">选择职业后显示技能列表</div>

  <div class="flex justify-between mt-6">
    <button hx-get="/character/step/1" hx-target="#step-content" hx-swap="innerHTML"
            onclick="document.getElementById('step-dot-2').className='text-gray-600 text-sm px-4 py-1 rounded';document.getElementById('step-dot-1').className='text-aged-gold bg-aged-brown/20 border border-aged-gold/30 text-sm px-4 py-1 rounded'"
            class="px-6 py-2 border border-gray-700 rounded text-sm text-gray-400 hover:text-aged-gold">
      ← 上一步
    </button>
    <button hx-get="/character/step/3" hx-target="#step-content" hx-swap="innerHTML"
            onclick="document.getElementById('step-dot-2').className='text-gray-600 text-sm px-4 py-1 rounded';document.getElementById('step-dot-3').className='text-aged-gold bg-aged-brown/20 border border-aged-gold/30 text-sm px-4 py-1 rounded'"
            class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30">
      下一步 →
    </button>
  </div>
</div>
```

Create `frontend/templates/partials/char-step3.html` (preview/export):

```html
<div>
  <h2 class="text-lg text-aged-gold mb-4 border-l-2 border-aged-gold pl-3">预览与导出</h2>
  <div class="mb-4">
    <label class="block text-xs text-gray-500 mb-1">背景故事</label>
    <textarea name="backstory" rows="4" placeholder="调查员背景故事..."
              class="w-full bg-[#1a150c] border border-[#4a3820] rounded px-3 py-2 text-sm text-gray-300 focus:border-aged-gold focus:outline-none resize-none"></textarea>
  </div>
  <div id="preview-summary" class="p-4 bg-[#1a150c] border border-[#3a2810] rounded text-sm text-gray-500 font-mono whitespace-pre-wrap">
    请填写前两步后查看预览。
  </div>
  <div class="flex justify-between mt-6">
    <button hx-get="/character/step/2" hx-target="#step-content" hx-swap="innerHTML"
            class="px-6 py-2 border border-gray-700 rounded text-sm text-gray-400 hover:text-aged-gold">
      ← 上一步
    </button>
    <button onclick="exportCharacter()"
            class="px-6 py-2 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30">
      导出 JSON
    </button>
  </div>
</div>
```

- [ ] **Step 5: Register character router in `frontend/server.py`**

```python
from frontend.routers import character
app.include_router(character.router)
```

- [ ] **Step 6: Verify page renders**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/character')
print(resp.status_code)  # 200
"
```

Expected: 200.

- [ ] **Step 7: Commit**

```bash
git add frontend/routers/character.py frontend/templates/character.html frontend/templates/partials/char-step1.html frontend/templates/partials/char-step2.html frontend/templates/partials/char-step3.html frontend/server.py
git commit -m "feat: add character creation wizard — 3-step HTMX flow"
```

---

### Task 5: Game Loop — Visual-Novel Layout + WebSocket

**Files:**
- Create: `frontend/routers/game.py`
- Create: `frontend/templates/game.html`
- Create: `frontend/templates/partials/step-indicator.html`
- Modify: `frontend/server.py`

- [ ] **Step 1: Write `frontend/routers/game.py`**

```python
"""frontend/routers/game.py — Game loop API + WebSocket progress stream."""
from __future__ import annotations

import json
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["game"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Game instance (lazy init) ──
_game_instance: dict | None = None


def get_game() -> dict:
    global _game_instance
    if _game_instance is None:
        from game_loop import init_game
        from investigator import load_investigator, Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        import os
        from datetime import datetime
        from prompts import set_prompt_log_dir
        from llm import set_llm_log_dir

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
        _game_instance = g
    return _game_instance


@router.get("/game", response_class=HTMLResponse)
async def game_page(request: Request):
    return templates.TemplateResponse("game.html", {"request": request})


@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    from game_loop import run_turn
    game = get_game()
    turn = run_turn(game, user_input)
    narrative = turn.get("narrative", "") if turn else ""
    brief = turn.get("brief", "") if turn else ""

    # Return HTML fragments for HTMX swaps
    narrative_html = ""
    if brief:
        narrative_html += f'<div class="msg-brief px-3 py-2 text-sm text-gray-500 border-l-2 border-gray-600 mb-2">{brief}</div>'
    if narrative:
        narrative_html += f'<div class="msg-narrative px-3 py-2 text-parchment border-l-3 border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'

    return HTMLResponse(narrative_html)


@router.get("/api/game/player-status", response_class=HTMLResponse)
async def player_status():
    game = get_game()
    world = game["keeper"].world
    p = world.player
    if not p:
        return HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
    hp, san = p.derived.HP, p.derived.SAN
    return HTMLResponse(
        f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
        f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
    )


@router.get("/api/game/scene", response_class=HTMLResponse)
async def scene_info():
    game = get_game()
    world = game["keeper"].world
    loc = world.current_location
    desc = world.get_current_description()
    exits = world.get_possible_exits()
    exits_html = "".join(
        f'<div class="text-xs text-gray-600">→ {e.target}：{e.method}</div>' for e in exits
    )
    return HTMLResponse(
        f'<div class="font-bold text-aged-brown">{loc}</div>'
        f'<div class="text-xs text-gray-500 mt-1">{desc}</div>'
        f'{exits_html}'
    )


@router.websocket("/api/game/progress")
async def game_progress(ws: WebSocket):
    await ws.accept()
    steps = ["parse", "judge", "enrich", "combat_entry", "curate", "narrate"]
    try:
        for step in steps:
            await ws.send_json({"step": step, "status": "running"})
            await asyncio.sleep(3)  # Placeholder — replaced by real hooks in wire-up phase
            await ws.send_json({"step": step, "status": "done"})
        await ws.send_json({"step": "complete"})
    except WebSocketDisconnect:
        pass
```

- [ ] **Step 2: Write `frontend/templates/game.html` — visual-novel layout**

```html
{% extends "base.html" %}
{% block title %}TRPG 游戏{% endblock %}
{% block body %}
<div class="h-screen flex flex-col bg-black relative overflow-hidden" id="game-root">

  {# Full-screen background image #}
  <div id="scene-image" class="absolute inset-0 image-crossfade bg-gradient-to-b from-[#1a1410] via-[#2a1a0a] to-[#1a1410] z-0">
    <!-- Image loaded dynamically -->
  </div>

  {# HUD overlay — top left #}
  <div id="hud" class="absolute top-3 left-3 z-20 bg-black/70 border border-white/10 rounded px-3 py-2 backdrop-blur-sm">
    <div id="hud-scene" class="text-sm font-bold text-aged-brown">
      <!-- Scene name via HTMX -->
    </div>
    <div id="hud-stats" class="mt-0.5">
      <!-- Player stats via HTMX -->
    </div>
  </div>

  {# Step indicator — top right #}
  <div id="step-indicator" class="absolute top-3 right-3 z-20 bg-black/50 rounded px-2 py-1 text-[10px] font-mono text-gray-600">
    <!-- WebSocket updates -->
  </div>

  {# Help button — top right below step indicator #}
  <button id="help-toggle" class="absolute top-12 right-3 z-20 text-gray-600 hover:text-aged-gold text-xs"
          onclick="document.getElementById('help-panel').classList.toggle('hidden')">
    ? 帮助
  </button>

  {# Help panel (hidden) #}
  <div id="help-panel" class="hidden absolute top-20 right-3 z-20 bg-black/90 border border-gray-700 rounded p-3 w-56 text-xs text-gray-500">
    <b class="text-gray-400">命令</b><br>
    /scene | /char | /flags | /events<br>
    /do &lt;动作&gt; | /trigger &lt;E1&gt;<br>
    /save &lt;槽位&gt; | /load &lt;槽位&gt;<br>
    /reset | /help
  </div>

  {# Compact narrative bar — bottom #}
  <div id="narrative-bar"
       class="absolute bottom-0 left-0 right-0 z-20 bg-[#0a0806]/95 border-t border-aged-brown/30 p-3 cursor-pointer"
       onclick="togglePanel(true)">
    <div id="compact-narrative" class="text-sm text-parchment leading-relaxed line-clamp-2 mb-2">
      <!-- Latest narrative -->
    </div>
    <div class="flex items-center gap-3">
      <input type="text" id="user-input"
             placeholder="输入你的行动..."
             class="flex-1 bg-transparent border-none text-sm text-gray-400 placeholder-gray-700 focus:outline-none"
             autocomplete="off">
      <button onclick="event.stopPropagation(); sendTurn()"
              class="px-4 py-1.5 bg-aged-brown text-parchment text-sm rounded hover:bg-[#7a4a2c] border border-aged-gold/30">
        行动
      </button>
      <span class="text-[10px] text-gray-600 ml-2">▲ 展开</span>
    </div>
  </div>

  {# Expanded chat panel (slide-up, hidden by default) #}
  <div id="chat-panel"
       class="absolute bottom-0 left-0 right-0 z-30 bg-[#0a0806]/98 border-t-2 border-aged-gold hidden flex flex-col"
       style="height:65%">
    <div class="flex justify-between items-center px-4 py-2 border-b border-gray-800 text-xs">
      <span class="text-aged-brown">会话记录</span>
      <button class="text-gray-500 hover:text-gray-300" onclick="togglePanel(false)">▼ 收起</button>
    </div>
    <div id="chat-history" class="flex-1 overflow-y-auto px-4 py-3 space-y-2">
      <!-- HTMX appends new messages here -->
    </div>
    <div class="px-4 py-2 border-t border-gray-800 flex gap-2">
      <input type="text" id="user-input-expanded"
             placeholder="输入你的行动..."
             class="flex-1 bg-transparent border-none text-sm text-gray-400 placeholder-gray-700 focus:outline-none"
             autocomplete="off">
      <button onclick="sendTurn()"
              class="px-6 py-2 bg-aged-brown text-parchment text-sm rounded hover:bg-[#7a4a2c] border border-aged-gold/30">
        行动
      </button>
    </div>
  </div>

</div>

<script>
  // Panel toggle
  function togglePanel(show) {
    const panel = document.getElementById('chat-panel');
    const image = document.getElementById('scene-image');
    if (show) {
      panel.classList.remove('hidden');
      panel.classList.add('slide-up-enter');
      setTimeout(() => panel.classList.add('active'), 10);
      image.style.filter = 'brightness(0.4)';
    } else {
      panel.classList.add('hidden');
      panel.classList.remove('active');
      image.style.filter = '';
    }
  }

  // Close panel when clicking dimmed area
  document.getElementById('scene-image').addEventListener('click', function(e) {
    if (!document.getElementById('chat-panel').classList.contains('hidden')) {
      togglePanel(false);
    }
  });

  // Send turn
  async function sendTurn() {
    const compactInput = document.getElementById('user-input');
    const expandedInput = document.getElementById('user-input-expanded');
    const text = (compactInput.value || expandedInput.value).trim();
    if (!text) return;

    compactInput.value = '';
    expandedInput.value = '';
    compactInput.disabled = true;

    // Show step indicator starting
    const steps = document.getElementById('step-indicator');
    steps.innerHTML = 'parse ...';

    try {
      const formData = new FormData();
      formData.append('user_input', text);
      const resp = await fetch('/api/game/turn', { method: 'POST', body: formData });
      const html = await resp.text();

      // Update compact bar
      document.getElementById('compact-narrative').innerHTML = html;

      // Also append to chat history if panel is open
      const chatHistory = document.getElementById('chat-history');
      if (chatHistory && !document.getElementById('chat-panel').classList.contains('hidden')) {
        chatHistory.insertAdjacentHTML('beforeend', html);
        chatHistory.scrollTop = chatHistory.scrollHeight;
      }

      // Refresh HUD
      htmx.ajax('GET', '/api/game/player-status', '#hud-stats');
      htmx.ajax('GET', '/api/game/scene', '#hud-scene');

    } catch(e) {
      document.getElementById('compact-narrative').innerHTML = '<span class="text-red-500">网络错误</span>';
    }
    compactInput.disabled = false;
    compactInput.focus();
  }

  // Enter key to send
  document.getElementById('user-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendTurn();
  });
  document.getElementById('user-input-expanded').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendTurn();
  });

  // Initial HUD load
  document.addEventListener('DOMContentLoaded', function() {
    htmx.ajax('GET', '/api/game/player-status', '#hud-stats');
    htmx.ajax('GET', '/api/game/scene', '#hud-scene');
  });

  // WebSocket for step progress
  (function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(protocol + '//' + location.host + '/api/game/progress');
    ws.onmessage = function(e) {
      const data = JSON.parse(e.data);
      if (data.step === 'complete') {
        document.getElementById('step-indicator').innerHTML = '<span class="text-aged-gold">完成</span>';
      } else {
        document.getElementById('step-indicator').innerHTML =
          data.step + ' <span class="' + (data.status === 'done' ? 'text-coc-green' : 'text-gray-500') + '">' +
          (data.status === 'done' ? '✓' : '...') + '</span>';
      }
    };
    ws.onclose = function() { setTimeout(connectWS, 2000); };
  })();
</script>
{% endblock %}
```

- [ ] **Step 3: Create `frontend/templates/partials/step-indicator.html`**

```html
<div id="step-progress" class="flex gap-2 text-[10px] font-mono">
  <span id="sp-parse" class="text-gray-600">parse ·</span>
  <span id="sp-judge" class="text-gray-600">judge ·</span>
  <span id="sp-enrich" class="text-gray-600">enrich ·</span>
  <span id="sp-combat_entry" class="text-gray-600">combat ·</span>
  <span id="sp-curate" class="text-gray-600">curate ·</span>
  <span id="sp-narrate" class="text-gray-600">narrate</span>
</div>
```

- [ ] **Step 4: Register game router in `frontend/server.py`**

```python
from frontend.routers import game
app.include_router(game.router)
```

- [ ] **Step 5: Verify game page renders**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/game')
print(resp.status_code)  # 200
print('game-root' in resp.text)  # True
"
```

Expected: 200, True.

- [ ] **Step 6: Commit**

```bash
git add frontend/routers/game.py frontend/templates/game.html frontend/templates/partials/step-indicator.html frontend/server.py
git commit -m "feat: add game loop — visual-novel layout + WS progress + expandable chat"
```

---

### Task 6: JSON Editor — Lightweight 3-Pane

**Files:**
- Create: `frontend/routers/editor.py`
- Create: `frontend/templates/editor.html`
- Modify: `frontend/server.py`

- [ ] **Step 1: Write `frontend/routers/editor.py`**

```python
"""frontend/routers/editor.py — Lightweight JSON module editor."""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import HTMLResponse, PlainTextResponse

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
```

- [ ] **Step 2: Write `frontend/templates/editor.html`**

```html
{% extends "base.html" %}
{% block title %}TRPG — JSON 编辑器{% endblock %}
{% block body %}
<div class="h-screen flex bg-[#0d0d0d]">
  {# Left: File tree #}
  <div class="w-64 border-r border-gray-800 bg-[#0f0f0f] overflow-y-auto p-3">
    <h2 class="text-sm text-aged-gold font-bold mb-3 tracking-wider">文件浏览</h2>
    <div hx-get="/api/files?dir=data/modules"
         hx-trigger="load"
         hx-swap="innerHTML">
      <p class="text-xs text-gray-600">加载中...</p>
    </div>
    <div class="mt-3">
      <label class="block text-[10px] text-gray-600 mb-1">或手动输入路径</label>
      <div class="flex gap-1">
        <input type="text" id="manual-path" placeholder="data/modules/xxx/l2_test.json"
               class="flex-1 bg-[#0d0d0d] border border-gray-700 rounded px-2 py-1 text-xs text-gray-400">
        <button onclick="loadPath()" class="px-2 py-1 bg-gray-800 rounded text-xs text-gray-400 hover:text-aged-gold">加载</button>
      </div>
    </div>
  </div>

  {# Center: JSON tree #}
  <div class="flex-1 overflow-y-auto p-4" id="json-tree">
    <p class="text-sm text-gray-600">选择左侧 JSON 文件查看内容</p>
  </div>

  {# Right: Validation #}
  <div class="w-56 border-l border-gray-800 bg-[#0f0f0f] p-3">
    <h3 class="text-sm text-gray-500 font-bold mb-2">校验状态</h3>
    <div id="validation-result" class="text-xs text-gray-600">
      加载文件后自动校验
    </div>
  </div>
</div>

<script>
function loadPath() {
  const path = document.getElementById('manual-path').value.trim();
  if (!path) return;
  fetch('/editor/load?path=' + encodeURIComponent(path))
    .then(r => r.text())
    .then(html => { document.getElementById('json-tree').innerHTML = html; });
}
</script>
{% endblock %}
```

- [ ] **Step 3: Register editor router in `frontend/server.py`**

```python
from frontend.routers import editor
app.include_router(editor.router)
```

- [ ] **Step 4: Verify**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from frontend.server import app
from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get('/editor')
print(resp.status_code)
"
```

Expected: 200.

- [ ] **Step 5: Commit**

```bash
git add frontend/routers/editor.py frontend/templates/editor.html frontend/server.py
git commit -m "feat: add JSON editor — lightweight tree view + file browser"
```

---

### Task 7: User Guide Partials

**Files:**
- Create: `frontend/templates/partials/help-game.html`
- Create: `frontend/templates/partials/help-character.html`
- Create: `frontend/templates/partials/help-editor.html`

- [ ] **Step 1: Write `frontend/templates/partials/help-game.html`**

```html
<div class="text-xs text-gray-500 leading-relaxed">
  <b class="text-gray-400">游戏命令</b>
  <div class="mt-1 space-y-1">
    <div><code class="text-gray-600">/help</code> 显示此帮助</div>
    <div><code class="text-gray-600">/scene</code> 查看当前场景详情</div>
    <div><code class="text-gray-600">/char</code> 查看调查员角色卡</div>
    <div><code class="text-gray-600">/flags</code> 已完成实体状态</div>
    <div><code class="text-gray-600">/do &lt;动作名&gt;</code> 直接执行交互</div>
    <div><code class="text-gray-600">/trigger &lt;E1&gt;</code> 手动触发事件</div>
    <div><code class="text-gray-600">/save &lt;槽位&gt;</code> 存档</div>
    <div><code class="text-gray-600">/load &lt;槽位&gt;</code> 读档</div>
    <div><code class="text-gray-600">/reset</code> 重置游戏</div>
  </div>
  <div class="mt-3">
    <b class="text-gray-400">玩法提示</b>
    <p class="mt-1">用自然语言描述你的行动（如"检查手提箱""走向下一节车厢"），
    KP 会解析意图并判定结果。COC 7th D100 检定：骰值 ≤ 技能值即为成功。</p>
  </div>
  <div class="mt-3">
    <b class="text-gray-400">快捷键</b>
    <p class="mt-1">Enter 发送 | ↑ 历史输入</p>
  </div>
</div>
```

- [ ] **Step 2: Write `frontend/templates/partials/help-character.html`**

```html
<div class="text-xs text-gray-500 leading-relaxed">
  <b class="text-gray-400">COC 7th 属性说明</b>
  <div class="mt-1 grid grid-cols-2 gap-1">
    <div>STR 力量 — 物理力量</div>
    <div>CON 体质 — 健康与耐力</div>
    <div>SIZ 体型 — 身高体重</div>
    <div>DEX 敏捷 — 灵活度</div>
    <div>APP 外貌 — 外表魅力</div>
    <div>INT 智力 — 学习能力</div>
    <div>POW 意志 — 精神力量</div>
    <div>EDU 教育 — 知识储备</div>
    <div>LUCK 幸运 — 命运眷顾</div>
  </div>
  <div class="mt-2">
    <b class="text-gray-400">掷骰公式</b>
    <p>3D6*5 = 掷3个6面骰 × 5（范围 15-90）<br>
    2D6+6*5 = (2个6面骰 + 6) × 5（范围 40-90）</p>
  </div>
  <div class="mt-2">
    <b class="text-gray-400">技能点</b>
    <p>职业技能点 = 职业公式值<br>兴趣技能点 = INT × 2<br>信用评级受职业上下限约束</p>
  </div>
</div>
```

- [ ] **Step 3: Write `frontend/templates/partials/help-editor.html`**

```html
<div class="text-xs text-gray-500 leading-relaxed">
  <b class="text-gray-400">JSON 结构</b>
  <p class="mt-1">L1 — 玩家可见层（场景描述、交互结果叙事）<br>
  L2 — KP 守秘人层（entity、AT、side effects、检定）<br>
  L3 — 设计者层（困难等级、怪物约束、结局条件）</p>
  <div class="mt-2">
    <b class="text-gray-400">@markup 系统（7种）</b>
    <p class="mt-1">@spawn_enemy | @grant_weapon | @stat_change<br>
    @item_gain | @consume_item<br>
    @npc_state_change | @npc_follow</p>
  </div>
</div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/templates/partials/help-game.html frontend/templates/partials/help-character.html frontend/templates/partials/help-editor.html
git commit -m "feat: add user guide partials for game, character, editor"
```

---

### Task 8: Wire Up — Game API to game_loop.py

**Files:**
- Modify: `frontend/routers/game.py`

- [ ] **Step 1: Replace placeholder WS with real hooks**

Modify `frontend/routers/game.py` — replace the `game_progress` websocket with the real pipeline that actually calls `run_turn()`, and add the `/api/game/init` endpoint for dynamic module selection.

The core change: the WS `game_progress` handler is a placeholder. In production, step progress should be hooked into the actual Keeper processing pipeline. For the MVP, we add a queue-based approach:

```python
# Replace the game_progress function with:
import queue
import threading

_progress_queues: dict[str, queue.Queue] = {}

@router.websocket("/api/game/progress")
async def game_progress(ws: WebSocket):
    await ws.accept()
    q: queue.Queue = queue.Queue()
    qid = str(id(ws))
    _progress_queues[qid] = q
    try:
        while True:
            try:
                msg = q.get(timeout=30)
                await ws.send_json(msg)
                if msg.get("step") == "complete":
                    break
            except queue.Empty:
                await ws.send_json({"step": "heartbeat"})
    except WebSocketDisconnect:
        pass
    finally:
        _progress_queues.pop(qid, None)


def _push_progress(step: str, status: str):
    """Send progress update to all connected WS clients."""
    msg = {"step": step, "status": status}
    for q in list(_progress_queues.values()):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass
```

Then modify `/api/game/turn` to push progress:

```python
@router.post("/api/game/turn")
async def process_turn(user_input: str = Form(...)):
    from game_loop import run_turn
    game = get_game()

    _push_progress("parse", "running")
    # run_turn internally processes parse→judge→enrich→curate→narrate
    # For MVP, push before and after:
    turn = run_turn(game, user_input)
    _push_progress("parse", "done")
    _push_progress("judge", "done")
    _push_progress("enrich", "done")
    _push_progress("curate", "done")
    _push_progress("narrate", "done")
    _push_progress("complete", "")

    narrative = turn.get("narrative", "") if turn else ""
    brief = turn.get("brief", "") if turn else ""

    narrative_html = ""
    if brief:
        narrative_html += f'<div class="msg-brief px-3 py-2 text-sm text-gray-500 border-l-2 border-gray-600 mb-2">{brief}</div>'
    if narrative:
        narrative_html += f'<div class="msg-narrative px-3 py-2 text-parchment border-l-3 border-aged-gold bg-[#1a1410] narrative-flash">{narrative}</div>'

    return HTMLResponse(narrative_html)
```

- [ ] **Step 2: Add `/api/game/init` endpoint for dynamic module/character selection**

```python
@router.post("/api/game/init")
async def init_game_api(
    l1_path: str = Form(...),
    l2_path: str = Form(...),
    l3_path: str = Form(...),
    start_node: str = Form(...),
    char_path: str = Form(""),
):
    global _game_instance
    import os
    from datetime import datetime
    from game_loop import init_game
    from investigator import load_investigator, Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    from prompts import set_prompt_log_dir
    from llm import set_llm_log_dir

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(PROJECT_ROOT / f"logs/prompt_log_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)

    g = init_game(
        l2_path=str(PROJECT_ROOT / l2_path),
        l1_path=str(PROJECT_ROOT / l1_path),
        l3_path=str(PROJECT_ROOT / l3_path),
        start_node=start_node,
    )

    if char_path and os.path.exists(str(PROJECT_ROOT / char_path)):
        inv = load_investigator(str(PROJECT_ROOT / char_path))
    else:
        inv = Investigator(name="调查员", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)

    g["keeper"].world.set_player(inv)
    _game_instance = g

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("游戏已初始化 ✓")
```

- [ ] **Step 3: Commit**

```bash
git add frontend/routers/game.py
git commit -m "feat: wire game API — WS progress push + dynamic init with file paths"
```

---

### Task 9: Wire Up — Remaining and Cleanup

**Files:**
- Modify: `frontend/routers/character.py` (add LLM description + export)
- Remove: `frontend/server.py` (old), `frontend/game_server.py`, `frontend/character.html`, `frontend/character.css`, `frontend/character.js`, `frontend/game.html`, `frontend/json-editor.html`

- [ ] **Step 1: Add LLM description endpoint to character router**

```python
@router.post("/generate-description")
async def generate_description(type: str = Form(...), prompt: str = Form(...)):
    from llm import call_deepseek
    if type == "appearance":
        system = "你是一个COC 7th TRPG角色外貌描述生成器。根据用户提供的关键词生成一段简洁的外貌描述（150字以内）。仅输出描述文本。"
    else:
        system = "你是一个COC 7th TRPG角色个人描述生成器。根据用户提供的关键词生成一段简洁的角色个人描述（150字以内）。仅输出描述文本。"
    try:
        result = call_deepseek(prompt, json_mode=False, system=system,
                              model="deepseek-v4-flash", thinking=False,
                              max_tokens=300, temperature=0.7, max_retries=1)
        return PlainTextResponse(str(result).strip())
    except Exception as e:
        return PlainTextResponse(f"[生成失败: {e}]", status_code=500)
```

- [ ] **Step 2: Add export endpoint**

```python
@router.post("/export")
async def export_character(
    name: str = Form(""), age: int = Form(20), gender: str = Form(""),
    occupation: str = Form(""), appearance: str = Form(""),
    description: str = Form(""), backstory: str = Form(""),
):
    data = {
        "meta": {"version": "1.0", "created_at": __import__("datetime").datetime.now().isoformat(), "rules_edition": "COC7"},
        "personal": {"name": name, "age": age, "gender": gender, "occupation": occupation,
                     "appearance": appearance, "description": description},
        "backstory": backstory,
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename={name or 'character'}_character.json"})
```

- [ ] **Step 3: Wire pipeline start endpoint in launcher router**

Add to `frontend/routers/launcher.py`:

```python
@router.post("/api/pipeline/start")
async def start_pipeline(
    source: str = Form(...),
    module_name: str = Form(...),
    output_dir: str = Form("data/modules/"),
    start_from: str = Form("step_1a"),
):
    """Launch module generation pipeline. Runs synchronously for MVP."""
    import subprocess
    import sys
    from pathlib import Path

    source_path = PROJECT_ROOT / source
    if not source_path.exists():
        return PlainTextResponse(f"源文件不存在: {source}", status_code=400)

    cmd = [
        sys.executable, str(PROJECT_ROOT / "run_pipeline.py"),
        "--auto",
        "--docx", str(source_path),
        "--module", module_name,
        "--start-from", start_from,
    ]
    # Run in background thread
    import threading
    def run_pipeline():
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return HTMLResponse(
        '<div class="text-sm text-aged-gold mt-4">'
        f'  <p>✓ 管线已启动 — 模组: {module_name}</p>'
        f'  <p class="text-xs text-gray-500 mt-1">输出目录: {output_dir}</p>'
        f'  <p class="text-xs text-gray-500">可在控制台查看进度输出</p>'
        '</div>'
    )
```

- [ ] **Step 4: Delete old files**

```bash
cd C:/Users/micha/PyCharmMiscProject
git rm frontend/server.py frontend/game_server.py
git rm frontend/character.html frontend/character.css frontend/character.js
git rm frontend/game.html frontend/json-editor.html
```

- [ ] **Step 5: Update `run_game.py` to use new FastAPI server**

Read `run_game.py` and replace the server launch section:

```python
# In run_game.py, replace server launch with:
if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import os
    port = 8080
    url = f"http://localhost:{port}"
    print(f"  TRPG Assistant v2.0 → {url}")
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(url)
    uvicorn.run("frontend.server:app", host="127.0.0.1", port=port, log_level="info")
```

- [ ] **Step 6: Commit**

```bash
git add frontend/routers/character.py run_game.py
git commit -m "refactor: wire character API + cleanup old frontend files"
```

---

### Task 10: Tailwind Prod Build + Packaging

**Files:**
- Create: `frontend/static/tailwind.css` (compiled)
- Modify: `frontend/templates/base.html` (prod mode detection)

- [ ] **Step 1: Build Tailwind standalone CSS**

```bash
cd C:/Users/micha/PyCharmMiscProject
npx @tailwindcss/cli -i frontend/templates/base.html -o frontend/static/tailwind.css --minify
```

(If npx not available, download the pre-built CSS from Tailwind CDN.)

- [ ] **Step 2: Add prod mode detection to base.html**

In `base.html`, add a conditional to use the local CSS when available:

```html
<!-- In production (PyInstaller), use local build; in dev, use CDN -->
{% if PROD %}
<link rel="stylesheet" href="/static/tailwind.css">
{% else %}
<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = { /* same config */ };
</script>
{% endif %}
```

- [ ] **Step 3: Update PyInstaller spec**

Update `run_game.py` or create a `.spec` file with `--add-data` for `frontend/static` and `frontend/templates`.

- [ ] **Step 4: Commit**

```bash
git add frontend/static/tailwind.css frontend/templates/base.html
git commit -m "chore: add Tailwind prod build + conditional CDN/local switch"
```

---

## Task Summary

| # | Task | Files Created | Files Modified | Dependencies |
|---|------|--------------|----------------|-------------|
| 1 | Scaffold | `server.py`, `routers/__init__.py`, `base.html` | — | — |
| 2 | File Browser | `routers/files.py`, `partials/file-browser.html` | `server.py` | Task 1 |
| 3 | Launcher | `routers/launcher.py`, `launcher.html`, 2 partials | `server.py` | Task 2 |
| 4 | Character | `routers/character.py`, `character.html`, 3 partials | `server.py` | Task 1 |
| 5 | Game | `routers/game.py`, `game.html`, `step-indicator.html` | `server.py` | Task 1 |
| 6 | Editor | `routers/editor.py`, `editor.html` | `server.py` | Task 2 |
| 7 | Help Panels | 3 help partials | — | Tasks 4–6 |
| 8 | Wire Game | — | `routers/game.py` | Task 5 |
| 9 | Wire Rest + Cleanup | — | `routers/character.py`, delete 7 old files | Tasks 4, 8 |
| 10 | Packaging | `static/tailwind.css` | `base.html` | All |

## Verification

After completing all tasks, run the full server:

```bash
uvicorn frontend.server:app --reload --port 8080
```

Verify each page loads at `http://localhost:8080/`, `/character`, `/game`, `/editor`.
