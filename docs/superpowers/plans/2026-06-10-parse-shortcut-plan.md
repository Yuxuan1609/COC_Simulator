# Parse 阶段快捷路径 — 移动 & 搜索快速通道

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将"场景移动"和"搜索当前场景"从前端 UI 摘出为快捷按钮，点击后直接构造 parse 结果，跳过 LLM parse 调用，省下 ~2-5s 每次。

**Architecture:** 后端 `TurnInput` 新增 `action_type` / `action_target` 字段。`process_turn()` 在 Step 1 parse 前检查 action_type——若为 `"move"` 或 `"search"`，直接构造 `parse_result` 列表（格式与 LLM parse 返回值完全一致），不经 LLM，进入现有 Step 2 Judge 循环处理。前端在输入栏上方增加方向按钮（来自 `player_snapshot.exits`）和搜索按钮；纯文本输入行为不变。

**Tech Stack:** Python dataclasses, HTML/JS (vanilla), FastAPI Form params。

**设计要点:**
- 搜索的产物（可用交互列表、场景武器发现、技能检定结果）完全由后端 `process_turn()` 中已有的确定性逻辑产出，前端不新增展示
- 移动的目标由前端 `player_snapshot.exits` 提供，无需额外 API

---

## File Map

| 文件 | 改动 |
|------|------|
| `src/game/messages.py:89-92` | `TurnInput` 新增 `action_type` / `action_target` |
| `src/game_loop.py:315` | `run_turn()` 传递新字段到 `TurnInput` |
| `src/game/agents/keeper.py:133-187` | `process_turn()` 前置 dispatch：move/search 直接构造 parse_result |
| `frontend/routers/game.py:238-239` | `/api/game/turn` 接收 `action_type` / `action_target` Form 参数 |
| `frontend/templates/game.html:191-199` | 输入栏上方增加快捷按钮组 + `sendTurnAction()` JS |

---

### Task 1: 扩展 TurnInput dataclass

**Files:** Modify `src/game/messages.py:89-92`

- [ ] **Step 1: 新增两个可选字段**

```python
@dataclass
class TurnInput:
    """Entry point input."""
    raw_text: str = ""
    player: Any | None = None  # Investigator | None
    action_type: str = ""       # "move" | "search" | "" (text) — 不为空则跳过 parse
    action_target: str = ""     # 仅 action_type="move" 时有效
```

- [ ] **Step 2: Commit**

```bash
git add src/game/messages.py
git commit -m "feat: add action_type/action_target to TurnInput for parse shortcut"
```

---

### Task 2: game_loop 透传新字段

**Files:** Modify `src/game_loop.py:315`

- [ ] **Step 1: `run_turn()` 签名新增参数，构建 TurnInput 时传入**

修改 `run_turn()` 签名：

```python
def run_turn(game: dict, user_input: str,
             weapon_lib=None, enemy_lib=None, injector=None,
             action_type: str = "", action_target: str = "") -> dict:
```

修改 TurnInput 构造：

```python
    turn_input = TurnInput(
        raw_text=user_input,
        player=world.player,
        action_type=action_type,
        action_target=action_target,
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: pass action_type/action_target through run_turn"
```

---

### Task 3: Keeper 前置 dispatch — 跳过 parse

**Files:** Modify `src/game/agents/keeper.py:133-187`

- [ ] **Step 1: 在 process_turn() 中，Step 0 pre-parse 之前插入 dispatch 逻辑**

定位：`pre_parse.disambiguate()` 调用之前（约 line 175-176）。

```python
        # ── Pre-parse shortcut: move/search bypass LLM parse entirely ──
        at = turn_input.action_type
        if at == "move":
            target = turn_input.action_target.strip()
            if not target:
                return {"brief": "（移动目标未指定。）", "narrative": "（移动目标未指定。）",
                        "npc_events": []}
            # Validate target is a valid exit
            exits = self.world.get_possible_exits()
            valid_targets = {e.target for e in exits}
            if target not in valid_targets:
                return {"brief": f"（无法移动到「{target}」。）", "narrative": f"（无法移动到「{target}」。）",
                        "npc_events": []}
            raw = f"移动到{target}"
            parse_result = [{"type": "move", "target": target}]
        elif at == "search":
            raw = "搜索"
            parse_result = [{"type": "search"}]
        else:
            # Normal path: pre-parse + LLM parse
```

**关键**：`raw` 变量用于后续 `talk_to()` 和 `_has_follow_request()` 的输入文本。move 时填入描述性文本，search 时填入 `"搜索"`。

**现有代码位置参考**：当前 `raw = turn_input.raw_text` 在 line 135。上述 dispatch 后 `parse_result` 已就绪，跳过 line 175-192 的 pre-parse + LLM parse 全段。

需要重排的结构如下（用 edit 调整 line 133-192）：

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse → judge → enrich → curate."""
        raw = turn_input.raw_text

        # Pending weapon offer check ... (保持不变)
```

将 line 134-135 改为：

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse → judge → enrich → curate."""
        raw = turn_input.raw_text
        at = turn_input.action_type

        # Pending weapon offer check ... (保持不变)
```

在 `# Step 0: Pre-parse` 行（约 line 175）之前插入 dispatch 块。当前这一段代码的结构是：

```
line 133: def process_turn(...)
line 135:   raw = turn_input.raw_text
line 137-161: weapon offer check
line 163-170: escalation guard + clear state
line 172-173: _inject_npc_at()
line 175:   # Step 0: Pre-parse — disambiguation gate
line 176-185: pre-parse
line 187-192: Step 1 parse try/except
```

修改后：在 line 174（`_inject_npc_at()` 之后，`# Step 0` 之前）插入 dispatch 块，并用条件包裹 pre-parse + parse 段：

```python
        self._inject_npc_at()

        # ── Pre-parse shortcut: move/search bypass LLM parse entirely ──
        if at == "move":
            target = (turn_input.action_target or "").strip()
            if not target:
                return {"brief": "（移动目标未指定。）", "narrative": "（移动目标未指定。）",
                        "npc_events": list(self._npc_events)}
            exits = self.world.get_possible_exits()
            valid_targets = {e.target for e in exits}
            if target not in valid_targets:
                return {"brief": f"（无法移动到「{target}」。）",
                        "narrative": f"（无法移动到「{target}」。）",
                        "npc_events": list(self._npc_events)}
            raw = f"移动到{target}"
            parse_result = [{"type": "move", "target": target}]
        elif at == "search":
            raw = "搜索"
            parse_result = [{"type": "search"}]
        else:
            # Step 0: Pre-parse — disambiguation gate
            pre_result = self.pre_parse.disambiguate(raw, self._build_world_brief())
            if pre_result.clarity == "ambiguous":
                return {
                    "brief": pre_result.question,
                    "narrative": pre_result.question,
                    "pre_parse_ambiguous": True,
                }
            if pre_result.resolved_text:
                raw = pre_result.resolved_text

            # Step 1: Parse (LLM) — entity matching + NL requirement evaluation
            try:
                parse_result = self.turn_monitor.execute_step(
                    "parse", lambda: self._parse(raw), is_critical=True)
            except TurnFrozenError as e:
                return self._build_frozen_response(e)
```

**注意**：`"npc_events"` 在 move/search 的 early return 中需要包含（`_npc_events` 已在 line 168 清空），否则 `game_loop.py:403` 的 `result.get("npc_events", [])` 能正常工作但返回值缺少该键。加 `list(self._npc_events)` 保证接口一致性。

- [ ] **Step 2: 验证编译**

```bash
cd "D:\COC simulator"; python -m py_compile src/game/agents/keeper.py
```

- [ ] **Step 3: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: add move/search parse shortcut — skip LLM parse when action_type is set"
```

---

### Task 4: 前端 API 接收新参数

**Files:** Modify `frontend/routers/game.py:238-239`

- [ ] **Step 1: `process_turn` endpoint 新增可选 Form 参数**

```python
@router.post("/api/game/turn")
async def process_turn(
    user_input: str = Form(""),
    action_type: str = Form(""),
    action_target: str = Form(""),
):
```

- [ ] **Step 2: 调用 run_turn 时传入**

定位 `run_turn` 调用（约 line 296）：

```python
        turn = await loop.run_in_executor(
            None, run_turn, game, user_input, _weapon_lib, _enemy_lib, _injector,
            action_type, action_target,
        )
```

- [ ] **Step 3: 确保兼容性**——`user_input` 改为可选（默认 `""`），旧前端仍可工作。斜杠命令检查逻辑不变（仍用 `user_input`）。

- [ ] **Step 4: Commit**

```bash
git add frontend/routers/game.py
git commit -m "feat: accept action_type/action_target in /api/game/turn"
```

---

### Task 5: 前端快捷按钮组

**Files:** Modify `frontend/templates/game.html:191-199`（输入栏区域）+ JS 区

- [ ] **Step 1: 输入栏上方新增快捷按钮组**

在当前 `<div id="input-bar" ...>` 之前插入：

```html
    {# Quick action bar — move directions + search #}
    <div id="quick-actions" class="px-4 pt-2 flex flex-wrap items-center gap-1.5 border-t border-gray-800/60 bg-[#0f0f0f]/80 shrink-0">
      <span class="text-[10px] text-gray-600 mr-1">快捷：</span>
      <span id="qa-exits" class="flex flex-wrap items-center gap-1">
        <!-- populated by JS from player_snapshot.exits -->
      </span>
      <span class="text-gray-700 mx-1">|</span>
      <button onclick="sendTurnAction('search')" class="px-2.5 py-1 text-[10px] bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-aged-gold rounded border border-gray-700 hover:border-aged-gold/50 transition-colors">
        搜索当前场景
      </button>
    </div>
```

- [ ] **Step 2: 新增 JS 函数 `sendTurnAction()`**

在 `sendTurn()` 函数附近（约 line 638）之后添加：

```javascript
  async function sendTurnAction(actionType, actionTarget) {
    const input = document.getElementById('user-input');
    input.disabled = true;
    document.getElementById('step-indicator').innerHTML = '<span class="text-gray-500">思考中...</span>';
    var displayText = '';
    try {
      const fd = new FormData();
      fd.append('action_type', actionType);
      fd.append('user_input', '');  // optional, for backward compat
      if (actionTarget) {
        fd.append('action_target', actionTarget);
        displayText = '移动到 ' + actionTarget;
      } else {
        displayText = '搜索当前场景';
      }
      const resp = await fetch('/api/game/turn', { method: 'POST', body: fd });
      const ct = resp.headers.get('content-type') || '';
      if (!resp.ok) throw new Error('Server error: ' + resp.status);
      if (ct.includes('application/json')) {
        handleTurnResponse(displayText, await resp.json());
      } else {
        const html = await resp.text();
        document.getElementById('turn-output').innerHTML =
          '<div class="turn-card pb-3 border-b border-gray-800/40">' + html + '</div>';
        addToHistory(displayText, html);
      }
      try {
        const psResp = await fetch('/api/game/player-status?format=json');
        if (psResp.ok) updateCharHUD(await psResp.json());
      } catch(e) {}
    } catch(e) {
      document.getElementById('turn-output').innerHTML =
        '<div class="turn-error px-3 py-2 text-sm text-red-400 border-l-2 border-red-500 bg-[#1a0a0a]/80">网络错误: ' + e.message + '</div>';
    }
    document.getElementById('step-indicator').innerHTML = '';
    input.disabled = false;
    input.focus();
  }
```

- [ ] **Step 3: 更新 `updateSceneCard()` — 出口标签改为可点击按钮**

修改 `game.html` 中 `updateSceneCard()` 的 exits 渲染部分（约 line 293-298），将纯展示标签改为可点击按钮：

```javascript
    // Exits
    var exitsWrap = document.getElementById('scene-card-exits-wrap');
    var exitsEl = document.getElementById('scene-card-exits');
    var exits = snap.exits || [];
    if (exits.length > 0) {
      exitsWrap.classList.remove('hidden');
      exitsEl.innerHTML = exits.map(function(e) {
        return '<button onclick="sendTurnAction(\'move\', \'' + (e.target || '').replace(/'/g, "\\'") + '\')" '
          + 'class="text-[10px] px-1.5 py-0.5 bg-gray-800 hover:bg-aged-brown rounded text-gray-400 hover:text-parchment border border-gray-700 hover:border-aged-gold/50 transition-colors cursor-pointer">'
          + (e.target || '?') + '<span class="text-gray-600 ml-0.5">· ' + (e.method || '?') + '</span></button>';
      }).join('');
    } else {
```

- [ ] **Step 4: 同步更新快捷栏的出口按钮**

在 `updateSceneCard()` 末尾（约 line 315 之前），新增对 `#qa-exits` 的更新：

```javascript
    // Quick-action exit buttons
    var qaExits = document.getElementById('qa-exits');
    if (qaExits && exits.length > 0) {
      qaExits.innerHTML = exits.map(function(e) {
        return '<button onclick="sendTurnAction(\'move\', \'' + (e.target || '').replace(/'/g, "\\'") + '\')" '
          + 'class="px-2 py-0.5 text-[10px] bg-gray-800 hover:bg-aged-brown text-gray-400 hover:text-parchment rounded border border-gray-700 hover:border-aged-gold/50 transition-colors">'
          + '→ ' + (e.target || '?') + '</button>';
      }).join('');
    }
```

- [ ] **Step 5: 初始加载时首次填充快捷按钮**

在 `initGame()` 的成功回调中（约 line 399 `document.getElementById('user-input').focus();` 之后），从初始 `player_snapshot` 中填充快捷按钮。但目前 `initGame` 返回的 JSON 中也包含 `player_snapshot`，只需调用 `updateSceneCard()` 即可。确认 `updateSceneCard()` 已在 `initGame` 流程中被调用（check line ~400-410）。

实际上当前 `initGame()` 直接构造 HTML，不调用 `updateSceneCard()`。需要在 `initGame` 回调中补充调用。

在 `initGame()` 函数中，`document.getElementById('user-input').focus();`（line 399）之后添加：

```javascript
      // Populate quick-action buttons from initial snapshot
      if (data.player_snapshot) {
        updateSceneCard(data.player_snapshot);
      }
```

- [ ] **Step 6: 启动验证**

```bash
# 前端启动
cd "D:\COC simulator"; uvicorn frontend.server:app --reload
```

手动测试：
1. 进入游戏后确认快捷栏有方向按钮 + 搜索按钮
2. 点击方向按钮 → 场景切换，移动结果正常显示
3. 点击搜索 → 侦查检定执行，结果正常显示
4. 文本输入自由输入 → 正常走 LLM parse，无回归

- [ ] **Step 7: Commit**

```bash
git add frontend/templates/game.html
git commit -m "feat: add quick-action buttons for move/search to skip LLM parse"
```

---

### Task 6: 回归验证

- [ ] **Step 1: 运行已有测试确保无回归**

```bash
cd "D:\COC simulator"; python -m pytest tests/test_npc_manager.py tests/test_enemy_manager.py tests/test_combat.py -v --tb=short
```

- [ ] **Step 2: 可选 — 写一个简单单元测试验证 TurnInput 新字段**

```python
# tests/test_turn_input.py
from game.messages import TurnInput

def test_turn_input_move_action():
    ti = TurnInput(raw_text="", action_type="move", action_target="7号车厢")
    assert ti.action_type == "move"
    assert ti.action_target == "7号车厢"

def test_turn_input_text_default():
    ti = TurnInput(raw_text="搜索")
    assert ti.action_type == ""
    assert ti.action_target == ""
```

```bash
cd "D:\COC simulator"; python -m pytest tests/test_turn_input.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_turn_input.py
git commit -m "test: add TurnInput action_type/action_target tests"
```

---

### Task 7: cookbook 更新

**Files:** Modify `docs/superpowers/guides/cookbook.md`

- [ ] **Step 1: 在 Section 2 (Keeper 回合编配) 的 `process_turn()` 描述中补充快捷路径**

在 `_inject_npc_at()` 条目之后添加：

```
| `_dispatch_shortcut(turn_input)` → parse_result | **前置 dispatch**：检查 TurnInput.action_type。move → 构造 `[{type:"move", target}]`；search → 构造 `[{type:"search"}]`。非空 → 跳过 pre-parse + LLM parse，直接进入 Step 2 Judge。 |
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/guides/cookbook.md
git commit -m "docs: add parse shortcut dispatch to cookbook"
```

---
