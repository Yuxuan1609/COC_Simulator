# Frontend Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 7 remaining frontend issues: memory leaks, launcher UX, pipeline validation, initial game turn, dual-panel game layout with character card + avatar, skill check/time display.

**Architecture:** Frontend-only overhaul except for 3 minimal backend additions (pipeline validation endpoint, avatar_url field on Investigator, initial game turn auto-fire). No game engine changes.

**Tech Stack:** FastAPI + Jinja2 + HTMX 2.0.4 + Tailwind CSS CDN (to be replaced with static CSS in Task 2), vanilla JS.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `frontend/static/css/tailwind-built.css` | **Create** | Pre-built Tailwind CSS (replace CDN) |
| `frontend/templates/base.html` | **Modify** | Switch from Tailwind CDN to local CSS; fix wsRetry |
| `frontend/templates/launcher.html` | **Modify** | 3-tab nav: 模组生成 / 开始游戏 / 其他工具 |
| `frontend/templates/partials/launcher-module-gen.html` | **Rewrite** | Module gen form + weapon/enemy/boss paths + validation |
| `frontend/templates/partials/launcher-game-start.html` | **Create** | Game start form: L1/L2/L3 + character |
| `frontend/templates/partials/launcher-config.html` | **Modify** | Global settings: model, thinking, etc. |
| `frontend/templates/partials/character-card.html` | **Create** | Expandable character card partial (HTMX-loaded) |
| `frontend/templates/game.html` | **Rewrite** | Dual-panel layout, combat/skill display, char panel |
| `frontend/routers/launcher.py` | **Modify** | Add `POST /api/pipeline/validate` |
| `frontend/routers/game.py` | **Modify** | Add initial turn auto-fire; add `GET /api/game/character-card` |
| `frontend/routers/character.py` | **Modify** | Add avatar upload field in step 1 |
| `src/investigator/models.py` | **Modify** | Add `avatar_url: str = ""` to Investigator |
| `src/investigator/serialization.py` | **Modify** | Serialize/deserialize `avatar_url` |

---

### Task 0: Fix Memory Leaks (3 frontend fixes)

**Files:**
- Modify: `frontend/templates/base.html:8,47`
- Modify: `frontend/templates/game.html:247-260,418-445`

- [ ] **Step 1: Replace Tailwind CDN with pre-built static CSS**
  - Delete the CDN `<script src="https://cdn.tailwindcss.com">` block (base.html lines 8-46)
  - Replace with `<link rel="stylesheet" href="/static/css/tailwind-built.css">`
  - Create `frontend/static/css/tailwind-built.css` containing all custom colors and utility classes used by the project. Include Tailwind's preflight reset + custom color definitions + all utility classes referenced in templates.

- [ ] **Step 2: Cap chatMessages rendering to last 50 DOM nodes**
  In `game.html`, modify `addToHistory()`:
  ```javascript
  // Keep at most 200 messages in array
  if (chatMessages.length > 200) chatMessages = chatMessages.slice(-200);
  // Only render last 50 to DOM for performance
  const chatHistory = document.getElementById('chat-history');
  if (chatHistory && chatMessages.length > 50) {
    chatHistory.innerHTML = chatMessages.slice(-50).join('');
  }
  ```

- [ ] **Step 3: Reset wsRetry on successful WebSocket connection**
  In `game.html`, add to `ws.onopen`:
  ```javascript
  ws.onopen = function() {
    wsRetry = 0;
  };
  ```
  Add this between `ws.onmessage` and `ws.onerror` assignments.

- [ ] **Commit:**
  ```
  git add -A
  git commit -m "fix: memory leaks — CDN→static CSS, chat cap, wsRetry reset"
  ```

---

### Task 1: Launcher Page — 3-Tab Restructure

**Files:**
- Modify: `frontend/templates/launcher.html`
- Rewrite: `frontend/templates/partials/launcher-module-gen.html`
- Create: `frontend/templates/partials/launcher-game-start.html`
- Modify: `frontend/templates/partials/launcher-config.html`

- [ ] **Step 1: Rewrite `launcher.html` nav to 3 tabs**

  Replace current 29-line `launcher.html` with 3-tab layout:
  ```html
  {% extends "base.html" %}
  {% block title %}TRPG 启动{% endblock %}
  {% block body %}
  <div class="h-screen flex bg-[#0d0d0d]">
    <nav class="w-56 border-r border-gray-800 bg-[#0f0f0f] flex flex-col p-4 gap-2">
      <h1 class="text-lg text-aged-gold font-bold tracking-wider border-b border-gray-800 pb-3">TRPG 调查员助手</h1>
      <a href="/" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded"
         hx-get="/launcher/tabs/module-gen" hx-target="#tab-content" hx-swap="innerHTML"
         onclick="document.querySelectorAll('.nav-link').forEach(l=>l.classList.remove('text-aged-gold','bg-[#1a1a1a]'));this.classList.add('text-aged-gold','bg-[#1a1a1a]')"
         class="nav-link text-aged-gold bg-[#1a1a1a]">模组生成</a>
      <a href="/" class="nav-link block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded"
         hx-get="/launcher/tabs/game-start" hx-target="#tab-content" hx-swap="innerHTML"
         onclick="document.querySelectorAll('.nav-link').forEach(l=>l.classList.remove('text-aged-gold','bg-[#1a1a1a]'));this.classList.add('text-aged-gold','bg-[#1a1a1a]')">开始游戏</a>
      <a href="/" class="nav-link block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded"
         hx-get="/launcher/tabs/config" hx-target="#tab-content" hx-swap="innerHTML"
         onclick="document.querySelectorAll('.nav-link').forEach(l=>l.classList.remove('text-aged-gold','bg-[#1a1a1a]'));this.classList.add('text-aged-gold','bg-[#1a1a1a]')">其他工具</a>
      <div class="mt-auto pt-4 border-t border-gray-800">
        <a href="/character" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold rounded">创建调查员</a>
        <a href="/editor" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold rounded">JSON 编辑器</a>
      </div>
    </nav>
    <div class="flex-1 overflow-y-auto p-6" id="tab-content"
         hx-get="/launcher/tabs/module-gen" hx-trigger="load" hx-swap="innerHTML">
      <p class="text-gray-500">加载中...</p>
    </div>
  </div>
  {% endblock %}
  ```

- [ ] **Step 2: Rewrite `launcher-module-gen.html` — Module generation tab with library config**

  Full rewrite (replaces current 80-line file):
  ```html
  <h2 class="text-xl text-aged-gold mb-6 border-b border-gray-800 pb-3">模组生成</h2>
  <form id="pipeline-form" class="space-y-5 max-w-2xl" hx-post="/api/pipeline/start" hx-target="#pipeline-status" hx-swap="innerHTML">

    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">源文件 & 模组</legend>
      <div class="space-y-3">
        <div>
          <label class="block text-xs text-gray-300 mb-1">源文档 (.docx / .txt)</label>
          <div class="flex gap-2">
            <input type="text" name="source" id="pipeline-source" placeholder="data/modules/xxx/module.docx"
                   class="flex-1 bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
            <button type="button" hx-get="/api/files?dir=data/modules&target_input=pipeline-source"
                    hx-target="#file-browser-content" hx-swap="innerHTML"
                    onclick="openFileBrowser()"
                    class="px-3 py-1.5 border border-gray-600 rounded text-xs text-gray-400 hover:text-aged-gold bg-[#1a150c]">浏览</button>
          </div>
        </div>
        <div>
          <label class="block text-xs text-gray-300 mb-1">模组名称</label>
          <input type="text" name="module_name" id="pipeline-module" placeholder="常暗之厢"
                 class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
        </div>
        <div>
          <label class="block text-xs text-gray-300 mb-1">输出目录</label>
          <input type="text" name="output_dir" placeholder="data/modules/"
                 class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
        </div>
      </div>
    </fieldset>

    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">标准库（用于管线的敌人/武器/Boss 模板）</legend>
      <div class="grid grid-cols-3 gap-3">
        {% for label, name, placeholder in [
          ('武器库', 'weapon_path', 'data/library/core/weapons.json'),
          ('敌人库', 'enemy_path', 'data/library/core/enemies.json'),
          ('Boss 库', 'boss_path', 'data/library/core/bosses.json'),
        ] %}
        <div>
          <label class="block text-xs text-gray-300 mb-1">{{ label }}</label>
          <div class="flex gap-1">
            <input type="text" name="{{ name }}" id="pipeline-{{ name }}" placeholder="{{ placeholder }}"
                   class="flex-1 bg-[#1a150c] border border-gray-600 rounded px-2 py-1.5 text-xs text-gray-200 focus:border-aged-gold focus:outline-none">
            <button type="button" hx-get="/api/files?dir=data/library/core&target_input=pipeline-{{ name }}"
                    hx-target="#file-browser-content" hx-swap="innerHTML"
                    onclick="openFileBrowser()"
                    class="px-2 py-1.5 border border-gray-600 rounded text-[10px] text-gray-400 hover:text-aged-gold bg-[#1a150c]">...</button>
          </div>
        </div>
        {% endfor %}
      </div>
    </fieldset>

    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">流水线步骤</legend>
      <select name="start_from" id="pipeline-step" hx-post="/api/pipeline/validate" hx-target="#pipeline-validation"
              hx-swap="innerHTML" hx-include="#pipeline-source,#pipeline-module,#pipeline-output"
              class="bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
        <option value="">完整生成 (Step 1a)</option>
        <option value="step_2a">续跑: 从 Step 2a</option>
        <option value="step_3a">续跑: 从 Step 3a</option>
        <option value="step_3b">仅交叉核对 (Step 3b)</option>
      </select>
      <div id="pipeline-validation" class="mt-2 text-xs"></div>
    </fieldset>

    <div class="flex gap-3">
      <button type="submit" class="px-8 py-2.5 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30 font-bold">
        开始生成
      </button>
      <span id="pipeline-gen-status" class="text-sm text-gray-400 self-center"></span>
    </div>
    <div id="pipeline-status" class="text-sm text-gray-400"></div>
  </form>
  ```

- [ ] **Step 3: Create `launcher-game-start.html` — Game start tab**

  Move the L1/L2/L3 + character selection fields from `game.html`'s setup screen here:
  ```html
  <h2 class="text-xl text-aged-gold mb-6 border-b border-gray-800 pb-3">开始游戏</h2>
  <form id="init-form" class="space-y-5 max-w-2xl" onsubmit="initGame(event)">
    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">模组文件</legend>
      <div class="space-y-3">
        {% for label, id, placeholder in [
          ('L2 KP 守秘人层', 'l2-path', 'data/modules/常暗之厢/l2_test.json'),
          ('L1 玩家可见层', 'l1-path', 'data/modules/常暗之厢/l1_test.json'),
          ('L3 设计者层', 'l3-path', 'data/modules/常暗之厢/l3_test.json'),
        ] %}
        <div>
          <label class="block text-xs text-gray-300 mb-1">{{ label }}</label>
          <div class="flex gap-2">
            <input type="text" id="{{ id }}" name="{{ id.replace('-', '_') }}" placeholder="{{ placeholder }}"
                   class="flex-1 bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
            <button type="button" hx-get="/api/files?dir=data/modules&target_input={{ id }}"
                    hx-target="#file-browser-content" hx-swap="innerHTML"
                    onclick="openFileBrowser()"
                    class="px-3 py-1.5 border border-gray-600 rounded text-xs text-gray-400 hover:text-aged-gold bg-[#1a150c]">浏览</button>
          </div>
        </div>
        {% endfor %}
      </div>
    </fieldset>

    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">调查员角色卡</legend>
      <div class="flex gap-2">
        <input type="text" id="char-path" name="char_path" placeholder="investigator/test_character.json"
               class="flex-1 bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
        <button type="button" hx-get="/api/files?dir=investigator&target_input=char-path"
                hx-target="#file-browser-content" hx-swap="innerHTML"
                onclick="openFileBrowser()"
                class="px-3 py-1.5 border border-gray-600 rounded text-xs text-gray-400 hover:text-aged-gold bg-[#1a150c]">浏览</button>
        <a href="/character" class="px-3 py-1.5 border border-gray-600 rounded text-xs text-gray-400 hover:text-aged-gold bg-[#1a150c]">+ 新建</a>
      </div>
      <p class="text-[10px] text-gray-500 mt-1">留空则自动创建默认调查员</p>
    </fieldset>

    <div class="flex gap-3 items-center">
      <button type="submit" class="px-8 py-2.5 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30 font-bold">
        开始游戏
      </button>
      <span id="init-error" class="text-red-400 text-sm"></span>
    </div>
  </form>
  ```

- [ ] **Step 4: Trim `launcher-config.html` — Other tools tab**

  Keep only global app settings (model, thinking, debug), remove anything moved to module-gen/game-start. Add JSON editor link:
  ```html
  <h2 class="text-xl text-aged-gold mb-6 border-b border-gray-800 pb-3">其他工具 & 设置</h2>
  <div class="space-y-5 max-w-2xl">
    <fieldset class="border border-gray-700 rounded-lg p-4">
      <legend class="text-sm text-aged-gold px-2">工具</legend>
      <a href="/editor" class="text-sm text-gray-300 hover:text-aged-gold">JSON 编辑器 →</a>
    </fieldset>

    <form class="space-y-4" hx-post="/api/config/save" hx-target="#config-status" hx-swap="innerHTML">
      <fieldset class="border border-gray-700 rounded-lg p-4">
        <legend class="text-sm text-aged-gold px-2">LLM 配置</legend>
        <!-- Keep existing model/thinking/flash/timeout fields from current launcher-config.html -->
        {% for label, name, type, placeholder, value in [
          ('主模型', 'model', 'text', 'deepseek-v4-pro', config.get('model','')),
          ('Flash 模型', 'flash_model', 'text', 'deepseek-v4-flash', config.get('flash_model','')),
          ('LLM 超时 (ms)', 'llm_timeout_ms', 'number', '120000', config.get('llm_timeout_ms','')),
        ] %}
        <div class="mb-2">
          <label class="block text-xs text-gray-300 mb-1">{{ label }}</label>
          <input type="{{ type }}" name="{{ name }}" value="{{ value }}" placeholder="{{ placeholder }}"
                 class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200">
        </div>
        {% endfor %}
        <div class="flex gap-4 mt-2">
          <label class="flex items-center gap-1 text-xs text-gray-300">
            <input type="checkbox" name="thinking" {% if config.get('thinking',True) %}checked{% endif %}> Thinking
          </label>
          <label class="flex items-center gap-1 text-xs text-gray-300">
            <input type="checkbox" name="combat_llm_enhancement" {% if config.get('combat_llm_enhancement') %}checked{% endif %}> Combat LLM
          </label>
          <label class="flex items-center gap-1 text-xs text-gray-300">
            <input type="checkbox" name="debug_mode" {% if config.get('debug_mode') %}checked{% endif %}> Debug
          </label>
        </div>
      </fieldset>
      <button type="submit" class="px-4 py-1.5 bg-aged-brown text-parchment text-sm rounded hover:bg-[#7a4a2c] border border-aged-gold/30">保存设置</button>
      <span id="config-status" class="text-xs text-coc-green ml-2"></span>
    </form>
  </div>
  ```

- [ ] **Step 5: Update `launcher.py` to serve `launcher/tabs/game-start`**
  In `frontend/routers/launcher.py`, add the route:
  ```python
  @router.get("/launcher/tabs/game-start", response_class=HTMLResponse)
  async def launcher_tab_game_start(request: Request):
      return templates.TemplateResponse(request, "partials/launcher-game-start.html", {})
  ```

- [ ] **Step 6: Update `game.html` setup screen**
  Since the game setup form moved to the launcher, `game.html` can now go directly to game screen. Remove the `#game-setup` div entirely. The `/game` page will show a loading screen that auto-inits with default paths, or redirects to `/` if no game instance exists.

  Actually, keep the standalone `/game` page working: keep `#game-setup` with minimal fields as fallback, but point users to launcher as primary entry. Reduce setup screen to just show a "go to launcher" link + quick init with defaults.

- [ ] **Step 7: Update `launcher.py` — remove `pipeline_start`'s inline status HTML replacement**
  The pipeline start should use HTMX swap to show status. The `start_pipeline` return already works with the existing form. Just verify the hx-target binding.

- [ ] **Commit:**
  ```
  git add -A
  git commit -m "feat: 3-tab launcher restructure — module gen / game start / tools"
  ```

---

### Task 2: Pipeline Validation Endpoint

**Files:**
- Modify: `frontend/routers/launcher.py`

- [ ] **Step 1: Add `POST /api/pipeline/validate` endpoint**

  Add to `launcher.py`:
  ```python
  @router.post("/api/pipeline/validate")
  async def validate_pipeline(
      source: str = Form(""),
      module_name: str = Form(""),
      output_dir: str = Form(""),
      start_from: str = Form(""),
  ):
      """Validate intermediate files exist for pipeline resume at given step."""
      import os as _os

      if not start_from:
          # Full run — just check source exists
          if source and not _os.path.exists(str(PROJECT_ROOT / source)):
              return HTMLResponse(
                  f'<span class="text-red-400">源文件不存在: {source}</span>'
              )
          return HTMLResponse(
              '<span class="text-coc-green">将从 Step 1a 开始完整生成</span>'
          )

      mod_dir = output_dir or f"data/modules/{module_name}"
      mod_full = PROJECT_ROOT / mod_dir

      # Map step to required files
      required = {
          "step_2a": [f"{mod_dir}/module_step0.txt"],
          "step_3a": [f"{mod_dir}/module_step0.txt", f"{mod_dir}/l2_keeper.json"],
          "step_3b": [f"{mod_dir}/l2_keeper.json", f"{mod_dir}/l1_player.json", f"{mod_dir}/l3_designer.json"],
      }

      files_needed = required.get(start_from, [])
      if not files_needed:
          return HTMLResponse(
              '<span class="text-gray-400">未知步骤</span>'
          )

      missing = [f for f in files_needed if not _os.path.exists(str(PROJECT_ROOT / f))]
      if missing:
          names = ", ".join(missing)
          return HTMLResponse(
              f'<span class="text-red-400">缺少文件: {names}</span>'
          )

      # Also validate JSON is parseable for JSON files
      import json as _json
      for f in files_needed:
          fp = PROJECT_ROOT / f
          if fp.suffix == ".json" and fp.exists():
              try:
                  _json.loads(fp.read_text(encoding="utf-8"))
              except Exception:
                  return HTMLResponse(
                      f'<span class="text-red-400">JSON 格式错误: {f}</span>'
                  )

      return HTMLResponse(
          '<span class="text-coc-green">✓ 所有必需文件已就绪，可以续跑</span>'
      )
  ```

- [ ] **Step 2: Wire HTMX trigger in module-gen form**
  The `#pipeline-step` `<select>` already has `hx-post="/api/pipeline/validate"` in the Task 1 template. Add `hx-include` to also send source/module/output fields:
  ```html
  hx-include="#pipeline-source,#pipeline-module,#pipeline-output"
  ```

- [ ] **Commit:**
  ```
  git add frontend/routers/launcher.py
  git commit -m "feat: pipeline validation endpoint for resume steps"
  ```

---

### Task 3: Initial Game Turn — Auto-fire [游戏开始]

**Files:**
- Modify: `frontend/routers/game.py:287-358`

- [ ] **Step 1: Fire initial turn in `init_game_api`**

  After setting the player and game instance, run one turn with "[游戏开始]":
  ```python
  # Fire initial turn to trigger scene auto_triggers
  try:
      from game_loop import run_turn
      initial = run_turn(g, "[游戏开始]", _weapon_lib, _enemy_lib, _injector)
      initial_brief = initial.get("brief", "") if initial else ""
      initial_narrative = initial.get("narrative", "") if initial else ""
  except Exception:
      initial_brief = ""
      initial_narrative = ""

  return {
      "success": True,
      "location": g["keeper"].world.current_location,
      "hp": inv.derived.HP,
      "san": inv.derived.SAN,
      "name": inv.name,
      "initial_brief": initial_brief,
      "initial_narrative": initial_narrative,
  }
  ```

- [ ] **Step 2: Update frontend `initGame()` to show initial narrative**
  In `game.html`, update the initGame handler to display initial scene text:
  ```javascript
  document.getElementById('compact-narrative').innerHTML =
    '<span class="text-aged-gold">' + data.location + '</span> — 游戏已就绪' +
    (data.initial_brief ? '<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 border-gray-600 mt-2">' + data.initial_brief + '</div>' : '') +
    (data.initial_narrative ? '<div class="msg-narrative px-3 py-2 text-parchment border-l-2 border-aged-gold bg-[#1a1410] narrative-flash mt-2">' + data.initial_narrative + '</div>' : '');
  ```

- [ ] **Commit:**
  ```
  git add frontend/routers/game.py frontend/templates/game.html
  git commit -m "feat: auto-fire initial game turn [游戏开始] on game init"
  ```

---

### Task 4: Investigator Avatar Support

**Files:**
- Modify: `src/investigator/models.py`
- Modify: `src/investigator/serialization.py`
- Modify: `frontend/routers/character.py`
- Modify: `frontend/templates/partials/char-step1.html`

- [ ] **Step 1: Add `avatar_url` to Investigator model**

  In `src/investigator/models.py`, add after `backstory`:
  ```python
  avatar_url: str = ""       # optional avatar image URL (data URI or path)
  ```

- [ ] **Step 2: Serialize/deserialize avatar_url**

  In `src/investigator/serialization.py`, add to `inv_to_dict()`:
  ```python
  "avatar_url": inv.avatar_url,
  ```
  Add to `dict_to_inv()`:
  ```python
  avatar_url=data.get("avatar_url", ""),
  ```

- [ ] **Step 3: Add avatar input to character creation Step 1**

  In `frontend/templates/partials/char-step1.html`, add after the gender field:
  ```html
  <div>
    <label class="block text-xs text-gray-300 mb-1">头像 URL（可选）</label>
    <input type="text" name="avatar_url" placeholder="https://... 或 data:image/..."
           class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
  </div>
  ```

- [ ] **Step 4: Read avatar_url in export_character**

  In `frontend/routers/character.py` `export_character` handler, add:
  ```python
  inv.avatar_url = form_data.get("avatar_url", "").strip()
  ```

- [ ] **Commit:**
  ```
  git add src/investigator/models.py src/investigator/serialization.py frontend/routers/character.py frontend/templates/partials/char-step1.html
  git commit -m "feat: optional avatar_url field on Investigator"
  ```

---

### Task 5: Game Page — Dual-Panel Layout + Character Card + Skill/Time Display

**Files:**
- Modify: `frontend/templates/game.html` (full rewrite)
- Create: `frontend/templates/partials/character-card.html`
- Modify: `frontend/routers/game.py` (add `/api/game/character-card`)

- [ ] **Step 1: Add `GET /api/game/character-card` endpoint**

  In `frontend/routers/game.py`:
  ```python
  @router.get("/api/game/character-card", response_class=HTMLResponse)
  async def character_card():
      game = get_game()
      world = game["keeper"].world
      p = world.player
      if not p:
          return HTMLResponse('<span class="text-gray-500">无调查员</span>')

      skills_html = "".join(
          f'<div class="flex justify-between text-xs py-0.5"><span class="text-gray-400">{s.name}</span><span class="text-gray-300">{s.value}%</span></div>'
          for s in (p.skills.values() if isinstance(p.skills, dict) else p.skills)[:12]
      )
      weapons_html = "".join(
          f'<div class="text-xs text-gray-400">• {w.name} ({w.damage})</div>'
          for w in p.weapons[:5]
      ) or '<span class="text-xs text-gray-500">无</span>'
      items = p.item_manager.describe() if hasattr(p, 'item_manager') and p.item_manager else "无"
      avatar = p.avatar_url or ""
      stats = p.stats
      derived = p.derived

      return HTMLResponse(
          f'<div class="space-y-3">'
          f'<div class="flex items-center gap-3">'
          f'{"<img src=\\"" + avatar + "\\" class=\\"w-12 h-12 rounded border border-gray-600\\" onerror=\\"this.style.display=\\'none\\'\\">" if avatar else "<div class=\\"w-12 h-12 rounded bg-gray-800 flex items-center justify-center text-gray-500 text-xs\\">无</div>"}'
          f'<div>'
          f'<div class="text-sm text-aged-gold">{p.name}</div>'
          f'<div class="text-xs text-gray-500">{p.age}岁 {p.gender} {p.occupation or ""}</div>'
          f'</div></div>'
          f'<div class="text-xs text-gray-400">{p.personal_description or "（无描述）"}</div>'
          f'<div class="grid grid-cols-4 gap-1 text-[11px]">'
          f'{"".join(f"<div class=\\"text-gray-500\\">{k}</div><div class=\\"text-gray-300\\">{getattr(stats,k,0)}</div>" for k in ["STR","CON","SIZ","DEX","APP","INT","POW","EDU","LUCK"])}'
          f'</div>'
          f'<div class="flex gap-3 text-xs">'
          f'<span class="text-coc-green">HP {derived.HP}/{derived.HP_MAX}</span>'
          f'<span class="text-aged-gold">SAN {derived.SAN}</span>'
          f'<span class="text-gray-400">MP {derived.MP}</span>'
          f'<span class="text-gray-500">MOV {derived.MOV}</span>'
          f'</div>'
          f'<div class="border-t border-gray-800 pt-2">'
          f'<div class="text-xs text-gray-500 mb-1">技能</div>{skills_html}'
          f'</div>'
          f'<div class="border-t border-gray-800 pt-2">'
          f'<div class="text-xs text-gray-500 mb-1">武器</div>{weapons_html}'
          f'<div class="text-xs text-gray-500 mt-1 mb-1">物品</div><span class="text-xs text-gray-400">{items}</span>'
          f'</div>'
          f'</div>'
      )
  ```

- [ ] **Step 2: Rewrite `game.html` — dual-panel layout**

  Full rewrite of the game screen section (keep setup screen from Task 1 changes):

  Layout structure:
  ```
  ┌────────────────────────────────────────────┐
  │ 左上: 场景信息     │ 右上: 步骤+时间         │
  ├────────────────────┼───────────────────────┤
  │                    │ 右侧: 角色面板          │
  │ 左侧: 叙事区域      │  - 收起: 头像+HP/SAN    │
  │  - 技能检定        │  - 展开: 完整角色卡     │
  │  - 战斗结果        │                       │
  │  - 叙事文本        │                       │
  │  - 系统消息        │                       │
  │                    │                       │
  │ 底部: 输入框        │                       │
  └────────────────────┴───────────────────────┘
  ```

  ```html
  {% extends "base.html" %}
  {% block title %}TRPG 游戏{% endblock %}
  {% block body %}

  {# ═══════════════════ SETUP SCREEN (fallback) ═══════════════════ #}
  <div id="game-setup" class="h-screen flex bg-[#0d0d0d]">
    <nav class="w-56 border-r border-gray-800 bg-[#0f0f0f] flex flex-col p-4 gap-3">
      <h1 class="text-lg text-aged-gold font-bold tracking-wider border-b border-gray-800 pb-3">游戏设置</h1>
      <a href="/" class="block px-3 py-2 text-sm text-gray-400 hover:text-aged-gold hover:bg-[#1a1a1a] rounded">← 返回启动页</a>
    </nav>
    <div class="flex-1 overflow-y-auto p-6">
      <h2 class="text-xl text-aged-gold mb-6 border-b border-gray-800 pb-3">快速开始</h2>
      <form id="init-form" class="space-y-5 max-w-2xl" onsubmit="initGame(event)">
        <fieldset class="border border-gray-700 rounded-lg p-4">
          <legend class="text-sm text-aged-gold px-2">模组文件</legend>
          <div class="space-y-3">
            {% for label, id, placeholder in [
              ('L2 KP 守秘人层', 'l2-path', 'data/modules/常暗之厢/l2_test.json'),
              ('L1 玩家可见层', 'l1-path', 'data/modules/常暗之厢/l1_test.json'),
              ('L3 设计者层', 'l3-path', 'data/modules/常暗之厢/l3_test.json'),
            ] %}
            <div><label class="block text-xs text-gray-300 mb-1">{{ label }}</label>
              <input type="text" id="{{ id }}" name="{{ id.replace('-', '_') }}" placeholder="{{ placeholder }}"
                     class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
            </div>{% endfor %}
          </div>
        </fieldset>
        <fieldset class="border border-gray-700 rounded-lg p-4">
          <legend class="text-sm text-aged-gold px-2">调查员</legend>
          <input type="text" id="char-path" name="char_path" placeholder="留空使用默认"
                 class="w-full bg-[#1a150c] border border-gray-600 rounded px-3 py-1.5 text-sm text-gray-200 focus:border-aged-gold focus:outline-none">
        </fieldset>
        <button type="submit" class="px-8 py-2.5 bg-aged-brown text-parchment rounded hover:bg-[#7a4a2c] text-sm border border-aged-gold/30 font-bold">开始游戏</button>
        <span id="init-error" class="text-red-400 text-sm"></span>
      </form>
    </div>
  </div>

  {# ═══════════════════ GAME SCREEN — Dual Panel ═══════════════════ #}
  <div id="game-screen" style="display:none" class="h-screen flex bg-[#0d0d0d] overflow-hidden">

    {# ── Left Panel: Scene Info + Narrative + Input ── #}
    <div class="flex-1 flex flex-col min-w-0">

      {# Top bar: scene info + time ── #}
      <div class="flex justify-between items-start px-4 py-3 border-b border-gray-800 bg-[#0f0f0f] shrink-0">
        <div id="hud-scene" class="text-sm font-bold text-aged-brown"></div>
        <div class="flex gap-3 items-center text-[10px]">
          <span id="time-display" class="text-gray-500 font-mono">--:--</span>
          <span id="step-indicator" class="text-gray-500 font-mono"></span>
          <button class="text-gray-500 hover:text-aged-gold" onclick="document.getElementById('help-panel').classList.toggle('hidden')">? 帮助</button>
        </div>
      </div>

      {# Narrative area ── #}
      <div class="flex-1 overflow-y-auto px-4 py-3 space-y-2" id="narrative-area">
        <div id="compact-narrative" class="text-sm text-gray-400">
          游戏就绪。输入 /help 查看命令。
        </div>
        {# Help panel (hidden) ── #}
        <div id="help-panel" class="hidden text-xs text-gray-500 border border-gray-700 rounded p-2 bg-[#0f0f0f]">
          <b class="text-gray-300">命令</b><br>
          /scene | /char | /flags | /events<br>
          /do &lt;动作&gt; | /save &lt;槽位&gt; | /load &lt;槽位&gt;<br>
          /reset | /help
        </div>
        {# Chat history for expanded panel ── #}
        <div id="chat-history" class="hidden space-y-2"></div>
      </div>

      {# Input bar ── #}
      <div class="px-4 py-3 border-t border-gray-800 bg-[#0f0f0f] flex gap-2 shrink-0">
        <input type="text" id="user-input"
               placeholder="输入你的行动..."
               class="flex-1 bg-transparent border-none text-sm text-gray-300 placeholder-gray-600 focus:outline-none"
               autocomplete="off">
        <button onclick="sendTurn()"
                class="px-6 py-1.5 bg-aged-brown text-parchment text-sm rounded hover:bg-[#7a4a2c] border border-aged-gold/30">
          行动
        </button>
        <span class="text-[10px] text-gray-500 self-center cursor-pointer" onclick="togglePanel(true)">▲ 展开</span>
      </div>

      {# Expanded input panel ── #}
      <div id="chat-panel" class="hidden px-4 py-3 border-t-2 border-aged-gold bg-[#0f0f0f] shrink-0" style="height:50%">
        <div class="flex justify-between items-center mb-2 text-xs">
          <span class="text-aged-brown">会话记录</span>
          <button class="text-gray-400 hover:text-gray-200" onclick="togglePanel(false)">▼ 收起</button>
        </div>
        <div class="flex gap-2">
          <input type="text" id="user-input-expanded"
                 placeholder="输入你的行动..."
                 class="flex-1 bg-transparent border-none text-sm text-gray-300 placeholder-gray-600 focus:outline-none"
                 autocomplete="off">
          <button onclick="sendTurn()"
                  class="px-6 py-2 bg-aged-brown text-parchment text-sm rounded hover:bg-[#7a4a2c] border border-aged-gold/30">
            行动
          </button>
        </div>
      </div>
    </div>

    {# ── Right Panel: Character Card ── #}
    <div class="w-72 border-l border-gray-800 bg-[#0f0f0f] flex flex-col overflow-y-auto shrink-0" id="char-panel">
      {# Collapsed state — always visible ── #}
      <div id="char-panel-collapsed" class="p-3 cursor-pointer" onclick="toggleCharCard()">
        <div class="flex items-center gap-3">
          <div id="char-avatar" class="w-10 h-10 rounded bg-gray-800 flex items-center justify-center text-gray-500 text-xs shrink-0">?</div>
          <div class="min-w-0">
            <div id="char-name" class="text-sm text-aged-gold truncate">调查员</div>
            <div class="text-[10px] text-gray-500" id="char-desc">--</div>
            <div class="flex gap-2 mt-1">
              <div class="flex-1 h-1.5 bg-gray-700 rounded overflow-hidden">
                <div id="char-hp-bar" class="h-full bg-coc-green" style="width:100%"></div>
              </div>
              <div class="flex-1 h-1.5 bg-gray-700 rounded overflow-hidden">
                <div id="char-san-bar" class="h-full bg-aged-gold" style="width:100%"></div>
              </div>
            </div>
            <div class="flex justify-between text-[9px] text-gray-500 mt-0.5">
              <span>HP <span id="char-hp-text">?/?</span></span>
              <span>SAN <span id="char-san-text">?</span></span>
            </div>
          </div>
        </div>
      </div>
      {# Expanded state — HTMX loaded ── #}
      <div id="char-panel-expanded" class="hidden p-3 border-t border-gray-800"></div>
    </div>

  </div>

  <script>
    // ── Character panel toggle ──
    function toggleCharCard() {
      const collapsed = document.getElementById('char-panel-collapsed');
      const expanded = document.getElementById('char-panel-expanded');
      if (expanded.classList.contains('hidden')) {
        // Load full card via HTMX
        htmx.ajax('GET', '/api/game/character-card', '#char-panel-expanded');
        expanded.classList.remove('hidden');
      } else {
        expanded.classList.add('hidden');
      }
    }

    // ── Update character panel HUD ──
    function updateCharHUD(data) {
      if (!data) return;
      const hp = data.hp || 0;
      const hpMax = data.hp_max || hp || 10;
      const san = data.san || 0;
      document.getElementById('char-name').textContent = data.name || '调查员';
      document.getElementById('char-hp-text').textContent = hp + '/' + hpMax;
      document.getElementById('char-san-text').textContent = san;
      document.getElementById('char-hp-bar').style.width = (hpMax > 0 ? (hp / hpMax * 100) : 0) + '%';
      document.getElementById('char-san-bar').style.width = (san > 0 ? (san / 99 * 100) : 0) + '%';

      // Load avatar if available (handled by /api/game/character-card on expand)
      if (data.avatar_url) {
        document.getElementById('char-avatar').innerHTML =
          '<img src="' + data.avatar_url + '" class="w-10 h-10 rounded object-cover" onerror="this.parentElement.innerHTML=\\'?\\'">';
      }
    }

    // ── Game init (updated) ──
    async function initGame(e) {
      e.preventDefault();
      const form = document.getElementById('init-form');
      const fd = new FormData(form);
      const errEl = document.getElementById('init-error');
      errEl.textContent = '';
      for (const id of ['l2-path', 'l1-path', 'l3-path']) {
        if (!document.getElementById(id).value.trim()) {
          errEl.textContent = '请填写所有模组文件路径';
          return;
        }
      }
      try {
        const resp = await fetch('/api/game/init', { method: 'POST', body: fd });
        const text = await resp.text();
        if (!resp.ok) { errEl.textContent = '初始化失败: ' + text; return; }
        const data = JSON.parse(text);

        // Populate character panel
        updateCharHUD({
          name: data.name, hp: data.hp, hp_max: data.hp,
          san: data.san, avatar_url: data.avatar_url,
        });
        document.getElementById('hud-scene').textContent = data.location;

        // Switch screens
        document.getElementById('game-setup').style.display = 'none';
        document.getElementById('game-screen').style.display = '';
        document.getElementById('user-input').focus();

        // Show initial narrative
        var initHtml = '<span class="text-aged-gold">' + data.location + '</span> — 游戏已就绪';
        if (data.initial_brief) {
          initHtml += '<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 border-gray-600 mt-2">' + data.initial_brief + '</div>';
        }
        if (data.initial_narrative) {
          initHtml += '<div class="msg-narrative px-3 py-2 text-parchment border-l-2 border-aged-gold bg-[#1a1410] narrative-flash mt-2">' + data.initial_narrative + '</div>';
        }
        document.getElementById('compact-narrative').innerHTML = initHtml;
        connectWS();
      } catch(e) { errEl.textContent = '网络错误: ' + e.message; }
    }

    // ── Panel toggle ──
    function togglePanel(show) {
      const panel = document.getElementById('chat-panel');
      const chatHistory = document.getElementById('chat-history');
      if (show) {
        panel.classList.remove('hidden');
        if (chatHistory) chatHistory.classList.remove('hidden');
      } else {
        panel.classList.add('hidden');
        if (chatHistory) chatHistory.classList.add('hidden');
      }
    }

    // ── Chat history ──
    let chatMessages = [];
    function addToHistory(userMsg, responseHtml) {
      if (userMsg) {
        chatMessages.push('<div class="msg-brief px-3 py-2 text-sm text-gray-500 border-l-2 border-gray-700 mb-2">&gt; ' + userMsg + '</div>');
      }
      if (responseHtml) chatMessages.push(responseHtml);
      if (chatMessages.length > 200) chatMessages = chatMessages.slice(-200);
      const ch = document.getElementById('chat-history');
      if (ch && !ch.classList.contains('hidden')) {
        ch.innerHTML = chatMessages.slice(-50).join('');
        ch.scrollTop = ch.scrollHeight;
      }
    }

    // ── Handle structured turn response ──
    function handleTurnResponse(userText, data) {
      var parts = [];
      if (data.skill_results && data.skill_results.length > 0) {
        for (var i = 0; i < data.skill_results.length; i++) {
          var sr = data.skill_results[i];
          var tierColor = sr.tier === 'extreme' ? 'text-yellow-300' : sr.tier === 'hard' ? 'text-coc-green' : sr.tier === 'regular' ? 'text-gray-300' : 'text-red-400';
          parts.push('<div class="msg-skill px-3 py-1 text-xs ' + (sr.success ? 'text-coc-green' : 'text-coc-red') + ' border-l-2 ' + (sr.success ? 'border-coc-green/50' : 'border-coc-red/50') + ' mb-1">' + (sr.success ? '✓' : '✗') + ' ' + (sr.entity_id || '?') + ' <span class="' + tierColor + '">[' + (sr.tier || 'regular') + ']</span></div>');
        }
      }
      if (data.combat) {
        var outcomeLabel = data.combat.outcome === 'win' ? '胜利' : data.combat.outcome === 'loss' ? '败北' : data.combat.outcome;
        parts.push('<div class="msg-combat px-3 py-2 text-sm border-l-2 border-yellow-600 bg-[#1a1400] mb-2"><span class="text-yellow-400">⚔ 战斗 ' + outcomeLabel + '</span>' + (data.combat.narrative ? '<div class="text-gray-400 text-xs mt-1">' + data.combat.narrative + '</div>' : '') + '</div>');
      }
      if (data.narrative_html) {
        parts.push(data.narrative_html);
      } else {
        if (data.brief) parts.push('<div class="msg-brief px-3 py-2 text-sm text-gray-400 border-l-2 border-gray-600 mb-2">' + data.brief + '</div>');
        if (data.narrative) parts.push('<div class="msg-narrative px-3 py-2 text-parchment border-l-2 border-aged-gold bg-[#1a1410] narrative-flash">' + data.narrative + '</div>');
      }
      // Time display
      if (data.timestamp) {
        document.getElementById('time-display').textContent = data.timestamp;
      }
      var html = parts.join('') || '<div class="msg-brief px-3 py-2 text-sm text-gray-500">（没有返回叙事内容）</div>';
      document.getElementById('compact-narrative').innerHTML = html;
      addToHistory(userText, html);
      if (data.game_over) {
        var endingText = data.ending ? data.ending.name + ': ' + data.ending.narrative : '游戏结束';
        setTimeout(function() {
          document.getElementById('compact-narrative').innerHTML += '<div class="msg-ending px-3 py-3 text-sm text-aged-gold border-l-2 border-aged-gold bg-[#1a1410] mt-3">' + endingText + '</div>';
          document.getElementById('user-input').disabled = true;
          document.getElementById('user-input-expanded').disabled = true;
        }, 500);
      }
    }

    // ── Send turn ──
    async function sendTurn() {
      const compactInput = document.getElementById('user-input');
      const expandedInput = document.getElementById('user-input-expanded');
      const text = (compactInput.value || expandedInput.value).trim();
      if (!text) return;
      const barHidden = document.getElementById('chat-panel').classList.contains('hidden') === false;
      const activeInput = barHidden ? expandedInput : compactInput;
      const inactiveInput = barHidden ? compactInput : expandedInput;
      activeInput.value = ''; inactiveInput.value = '';
      compactInput.disabled = true; expandedInput.disabled = true;
      document.getElementById('step-indicator').innerHTML = 'parse ...';
      document.getElementById('compact-narrative').innerHTML = '<span class="text-gray-500">' + text + '</span>';
      try {
        const fd = new FormData(); fd.append('user_input', text);
        const resp = await fetch('/api/game/turn', { method: 'POST', body: fd });
        const ct = resp.headers.get('content-type') || '';
        if (!resp.ok) {
          const errText = await resp.text();
          document.getElementById('compact-narrative').innerHTML = '<span class="text-red-400">服务器错误 (' + resp.status + '): ' + errText + '</span>';
          throw new Error('Server error: ' + resp.status);
        }
        if (ct.includes('application/json')) {
          handleTurnResponse(text, await resp.json());
        } else {
          const html = await resp.text();
          document.getElementById('compact-narrative').innerHTML = html;
          addToHistory(text, html);
        }
        htmx.ajax('GET', '/api/game/player-status', '#hud-stats');
        htmx.ajax('GET', '/api/game/scene', '#hud-scene');
      } catch(e) {
        document.getElementById('compact-narrative').innerHTML = '<span class="text-red-400">网络错误: ' + e.message + '</span>';
      }
      compactInput.disabled = false; expandedInput.disabled = false;
      activeInput.focus();
    }

    // ── Enter key ──
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && (e.target.id === 'user-input' || e.target.id === 'user-input-expanded')) sendTurn();
    });

    // ── WebSocket ──
    let ws = null, wsRetry = 0;
    function connectWS() {
      if (ws) { try { ws.close(); } catch(e) {} }
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(protocol + '//' + location.host + '/api/game/progress');
      ws.onopen = function() { wsRetry = 0; };
      ws.onmessage = function(e) {
        const data = JSON.parse(e.data);
        const indicator = document.getElementById('step-indicator');
        if (data.step === 'heartbeat') return;
        if (data.step === 'complete') indicator.innerHTML = '<span class="text-aged-gold">完成</span>';
        else indicator.innerHTML = data.step + ' <span class="' + (data.status === 'done' ? 'text-coc-green' : 'text-gray-500') + '">' + (data.status === 'done' ? '✓' : '...') + '</span>';
      };
      ws.onerror = function() {};
      ws.onclose = function() {
        ws = null;
        if (document.getElementById('game-screen').style.display !== 'none') {
          wsRetry++;
          const delay = Math.min(1000 * Math.pow(2, wsRetry), 30000);
          setTimeout(connectWS, delay);
        }
      };
    }
  </script>
  {% endblock %}
  ```

- [ ] **Step 3: Update `player_status` to include avatar_url + max_hp**

  In `frontend/routers/game.py`:
  ```python
  @router.get("/api/game/player-status")
  async def player_status():
      game = get_game()
      world = game["keeper"].world
      p = world.player
      if not p:
          return {"hp": 0, "san": 0, "name": "", "avatar_url": "", "hp_max": 0}
      return {
          "hp": p.derived.HP,
          "hp_max": p.derived.HP_MAX,
          "san": p.derived.SAN,
          "name": p.name,
          "avatar_url": getattr(p, 'avatar_url', ''),
      }
  ```
  And update the HTML response for HTMX compatibility (return JSON now since the frontend parses it). Actually, keep the HTML response for backward compat via HTMX, but also make the JSON available. Add a `?format=json` query param:
  ```python
  @router.get("/api/game/player-status")
  async def player_status(format: str = ""):
      game = get_game()
      world = game["keeper"].world
      p = world.player
      if not p:
          return JSONResponse({"hp": 0, "san": 0, "name": "", "avatar_url": "", "hp_max": 0}) if format == "json" else HTMLResponse('<span class="text-gray-600">未设置调查员</span>')
      hp, san = p.derived.HP, p.derived.SAN
      has_avatar = getattr(p, 'avatar_url', '')
      if format == "json":
          return {"hp": hp, "hp_max": p.derived.HP_MAX, "san": san, "name": p.name, "avatar_url": has_avatar}
      return HTMLResponse(
          f'<div class="text-xs"><span class="text-gray-500">HP </span><span class="text-coc-green">{hp}</span>'
          f'<span class="text-gray-500 ml-2">SAN </span><span class="text-aged-gold">{san}</span></div>'
      )
  ```

- [ ] **Step 4: Update `sendTurn()` to refresh character HUD via JSON**
  In `sendTurn()`, after the turn completes, fetch player-status as JSON and update the char panel:
  ```javascript
  // After turn completes, in sendTurn():
  try {
    const psResp = await fetch('/api/game/player-status?format=json');
    if (psResp.ok) updateCharHUD(await psResp.json());
  } catch(e) {}
  htmx.ajax('GET', '/api/game/scene', '#hud-scene');
  ```

- [ ] **Commit:**
  ```
  git add frontend/templates/game.html frontend/routers/game.py
  git commit -m "feat: dual-panel game layout + character card + skill/time display"
  ```

---

### Task 6: Static Tailwind CSS Generation + Verification

**Files:**
- Create: `frontend/static/css/tailwind-built.css`
- Modify: `frontend/templates/base.html:8-46`

- [ ] **Step 1: Extract all Tailwind classes used in all templates**
  List every utility class used across all HTML files. This can be done by scanning templates:
  - `game.html`: flex, grid, bg-[#...], text-*, border-*, px-*, py-*, etc.
  - All partials: similar patterns
  - Build a comprehensive class list

- [ ] **Step 2: Generate static CSS via Tailwind CLI or manual compilation**
  Use the Tailwind CDN's compiled output after one full page load as a starting point, then add missing classes. Or use `npx tailwindcss` if available.

  For simplicity, create a comprehensive CSS file that includes the preflight reset, all custom color variables as CSS custom properties, and all used utility classes.

  If Tailwind CLI is not available, the alternative is to extract the compiled CSS from the CDN by loading all pages once and saving the generated `<style>` content. Then add any dynamic classes used in HTMX responses.

- [ ] **Step 3: Verify all pages render correctly with static CSS**
  Load launcher, game, character, editor pages. Check for missing styles.

- [ ] **Commit:**
  ```
  git add frontend/static/css/tailwind-built.css frontend/templates/base.html
  git commit -m "fix: replace Tailwind CDN with static compiled CSS"
  ```

---

### Task 7: Final Verification — Full Flow Test

- [ ] **Step 1: Start server**
  ```bash
  uvicorn frontend.server:app --port 8080
  ```

- [ ] **Step 2: Test launcher tabs**
  - Open http://localhost:8080
  - Click through all 3 tabs (模组生成 / 开始游戏 / 其他工具)
  - Verify file browser works in each tab
  - Verify pipeline validation shows status when changing step dropdown
  - Verify config save works

- [ ] **Step 3: Test game flow**
  - Select module files + click 开始游戏
  - Verify initial [游戏开始] turn displays scene description
  - Input several actions, verify each turn shows in narrative area
  - Verify character panel shows HP/SAN bars updating
  - Click character panel to expand — verify full card loads
  - Verify skill check results display with ✓/✗ and tier labels
  - Trigger a combat scenario, verify ⚔ 战斗 胜利 displays
  - Verify game over displays ending message and disables input

- [ ] **Step 4: Verify no memory issues**
  - Play 20+ turns, check browser memory usage stays stable
  - Check server process memory is stable

- [ ] **Commit:**
  ```
  git add -A
  git commit -m "chore: final verification pass"
  ```
