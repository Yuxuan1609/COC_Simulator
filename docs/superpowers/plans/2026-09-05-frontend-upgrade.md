# 前端专项 Implementation Plan（2026-09-05）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端结构重构（方案 B 模块化）+ 契约测试防护网 + 布局修正 + debug panel + F39/F42/F40。

**Architecture:** 六阶段递进，§1 契约测试先行锁行为，§2/§3 结构迁移（URL/响应形状不变），§4-§6 功能落在新结构上。

**Spec:** `docs/superpowers/specs/2026-09-05-frontend-upgrade-design.md`（范围/不做项以此为准）

**已知事实（勿重复探索）：**
- 栈：FastAPI + Jinja2 + htmx 2.0.4（CDN base.html:9，需本地化）+ 无构建步骤。34 端点地图见调研（已附相关行号于各 Task）。
- `game.py` 行号分区：全局态 :20-31 / 战斗序列化 :34-102 / 库与 get_game :105-165 / slash :173-250 / process_turn :253-501 / charcard :514-678 / 状态小接口 :681-735 / WS :737-766 / init :769-859 / combat 端点 :892-1135 / 工具 :1138-1191。
- `game.html` 1444 行，内联 JS ~1148 行（:293-1443）；全局裸奔变量 combatSession/combatSelections/DEBUG/chatMessages（:640,:1024-1025）。
- TurnLogger 实际目录：**`setup_logging()`（game_loop.py:28）统一给 `logs/prompt_log_<ts>/`，turn 与 prompt/LLM 日志同目录**；turn_logger.py 类默认的 `data/debug/turn_logs/` 不是运行路径。debug 端点必须读当前 `_turn_logger.log_dir` / prompt log getter，禁止写死路径；init 须把 log_dir 留在可查询处。
- 回合五宏阶段：`src/game/turn/runner.py` **`TurnRunner.execute`（非 run）** 编排 phase_a_understand → phase_b_adjudicate → phase_c_encounter → phase_d_enrich → phase_e_finalize；含 Restart 重跑循环与 Early/SUSPENDED 早退。
- **WS 对外步名（现网，F42 保持不变）**：`parse/judge/enrich/combat_entry/curate/narrate/complete`（game.py:310-333）。runner 内部相位名（understand/…）只作映射来源，不外泄。进度推送发生在 `run_in_executor` 工作线程 → **必须 `loop.call_soon_threadsafe` 或 `queue.Queue`**，`asyncio.Queue.put_nowait` 跨线程不安全。
- WorldChronicle（scenario_core.py:1901）：events deque maxlen=**15**、只存截断 input(60字)+intent/实体结果，**不存叙事全文** → F39 需扩存储（见 Task 10）。**`record_turn`（game_loop.py:375）在 `narrator.narrate`（:472）之前调用，record 时叙事字符串不存在** → narrative_log 必须在 narrate 之后另行写入，且**不进 `render_for_author`**。
- Chronicle 已入档（随 save/load）；record_turn 由 game_loop.py:373-377 调用。
- 战斗序列化已有：game.py:34-102 `_serialize_combat_state_for_frontend` 等（契约测试 test_frontend_contract.py:118-124 已锁）。
- `_combat_sessions`（game.py:30）进程内存 dict；前端 combatSession 亦内存（game.html:1024）。
- 现有前端测试范式：TestClient + `patch("frontend.routers.game.get_game", ...)` + SimpleNamespace 假 game（test_frontend_contract.py 全文为范）。**patch 有效是因为同模块查找；拆包后 `turn.py` 若 `from .session import get_game` 会绑死原函数，patch 包 re-export 无效** → 拆分后一律 `session.get_game()` 属性查找，patch 目标改为 `frontend.routers.game.session.get_game`（Task 3 同步改全部既有测试的 patch 目标）。
- **F40 拍板（2026-09-06）：战斗场次原子化**——不做战斗过程持久化；刷新/读档丢弃进行中战斗，恢复到战斗前状态。Task 12 按此重写。
- **DEBUG 拍板（2026-09-06）**：现有 `trpg_debug`（整页 reload/敌人详情）与新 debug panel **合并为一个开关**，panel 涵盖原 DBG 信息。
- **历史拍板（2026-09-06）**：F39 history 面板**替换**现有内存 chatMessages 内联记录区；刷新后从 chronicle 重建。
- **响应形状原则修订（R10）**：「URL 不变」为准；**角色卡（及已声明的 slash 输出）形状在 §3 显式破坏**，同一 Task 内同步改前端加载与契约断言。
- 拆分后 import 路径变化会破坏现有 patch 目标——见上条，**不指望 re-export**。

---

## §1 契约测试防护网 + B19

### Task 1: 34 端点契约测试扩编

**Files:**
- Modify: `tests/test_frontend_contract.py`（现有 9 例保留，新增按 router 分 class）

- [ ] **Step 1: 写契约测试（先红不红皆可——大部分是补锁，预期直接绿；个别发现坏行为则 xfail 记录不修）**

**端点安全分级（R9，必须先遵守再写）**：
- **只测失败路径的副作用端点**（禁止 happy-path，会真跑 LLM/起进程/写盘）：`/api/game/init`（内部 `run_turn("[游戏开始]")` 调 LLM）、`/api/step0/start`、`/api/pipeline/start`（后台进程）、`/editor/save`（写盘）、`/character/generate-description`（LLM）——只断言 422/400/校验失败分支。
- **必须 patch `get_game` 的游戏端点**：`/api/game/turn`、`/api/game/state`、`/api/game/player-status`、`/api/game/character-card`、`/api/game/scene`、`/api/game/command`、`/api/game/autowin`、`/api/combat/start`、`/api/combat/round`——get_game 空实例会真 init_game。
- **安全直接打**：`/health`、`/`、`/game`、`/character`、`/editor`、`/launcher/tabs/{tab}`（4 个）、`/character/step/{n}`（3 个）、`/api/config/save|load`（tmp_path 隔离）、`/api/files`、`/api/assets/list|random`、`/editor/load`、`/character/roll`、`/character/skills-list`、`/character/export`（GET）、`/editor/validate`。

范式沿用现有 fixture（TestClient + patch get_game）。34 端点全表以调研 §2 为准（不含 /health 则 33+1），逐一端点 ≥1 例（状态码 + 关键键/标记）。示例如下（**先读对应 router 函数现状再写断言，端点行为以代码为准**）：

```python
class TestEditorContract:
    def test_editor_page(self, client): ...

    def test_validate_current_behavior(self, client):
        """锁定现状：validate 是 Form(path, content)；空 scenes 返回
        {"valid": true, "warnings": [...]}（不 reject）。F33 余项本轮不修。"""
        r = client.post("/editor/validate",
                        data={"path": "x.json", "content": '{"scenes": {}}'})
        assert r.status_code == 200
        assert r.json()["valid"] is True  # 现状：只警告不拒绝
```

要点：
- 服务端拼 HTML 的端点（character-card、skills-list、slash 输出）只断言「含关键标记子串」，不断言全文（§3 会把它们换成 JSON，届时同步改断言）。
- 发现现状坏行为（如某端点 500）**不修**，在测试里 `pytest.xfail` 标注并记入交付说明。
- WS 端点用 TestClient 的 `websocket_connect` 锁「能连、首条消息形状」即可。

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/test_frontend_contract.py -q`
Expected: 全绿或仅 xfail

### Task 2: B19 角色卡加载失败透出

**Files:**
- Modify: `frontend/routers/game.py`（:152-158 与 :817-829 两处兜底合一；init 响应加 warning）
- Modify: `frontend/templates/game.html`（toast 提示）
- Test: `tests/test_frontend_contract.py` 追加

- [ ] **Step 1: 失败测试**

```python
def test_init_char_load_failure_surfaces_warning(client, monkeypatch):
    """B19：角色卡加载失败不再静默——init 响应带 warning。"""
    # patch 使角色卡加载抛异常，断言 init 响应含 warning 字段且含「默认」
```

- [ ] **Step 2: 跑确认红 → 实现**：合并为 `_load_character_or_default()` 返回 `(inv, warning|None)`。**两处现状不对称（R12），合并语义如下**：
  - `init_game_api:817-823`：`load_investigator` 抛异常 → 静默 `_make_default_inv()` —— 改为透出 warning（init JSON 加 `warning` 键）。
  - `get_game:152-158`：文件**不存在**时才内联建卡（名「调查员A」，与 `_make_default_inv` 的「调查员」不一致——统一收编）；加载**抛错会外抛**——合并后统一为「抛错 → 默认卡 + warning」。lazy `get_game` 路径同样带 warning（经 `_game_instance` 上挂属性，init/state 响应透出）。
  - **勿写成「两处都静默」**——只有 init_game_api 原本静默。

- [ ] **Step 3: 前端 toast**：game.html 收到 init 响应 `warning` 时显示 3s 提示条（内联 JS 现状下先加最小实现，§3 迁移时进 api.js）。

- [ ] **Step 4: 提交**

```bash
git add tests/test_frontend_contract.py frontend/routers/game.py frontend/templates/game.html MAINTENANCE.md
git commit -m "test: 前端 34 端点契约防护网 + fix B19 角色卡加载失败透出 warning"
```

---

## §2 后端拆分（game.py → routers/game/ 包）

### Task 3: 机械拆分 + 等价验证

**Files:**
- Create: `frontend/routers/game/__init__.py`（router 聚合，URL 不变；无 re-export）
- Create: `frontend/routers/game/session.py` / `turn.py` / `combat.py` / `charcard.py` / `slash.py` / `views.py`
- Delete: `frontend/routers/game.py`

- [ ] **Step 1: 按下表搬迁（逐行移动，不改逻辑；R21：本 Task 纯搬迁，process_turn 拆函数并入 Task 11）**

| 目标文件 | 内容（现行号） |
|---|---|
| session.py | 全局态 :20-31、`_init_libraries`/`get_game` :105-165、`init_game_api` :769-859、`_resolve_start_scene`/`_make_default_inv` :1138-1191 |
| turn.py | `process_turn` :253-501（含进度推送、autosave 调用）、`_push_progress` + WS :737-766 |
| combat.py | 序列化 :34-102、`/api/combat/start|round` :892-1135 |
| charcard.py | `character_card` :514-678、`_known_spell_names` |
| slash.py | `_handle_slash_command` :173-250、`game_command` |
| views.py | `game_page`、`player_status`、`scene_info`、`game_state`、`autowin` |
| `__init__.py` | `APIRouter` 聚合（URL 不变）；**不做 re-export 兼容层** |

- **R7 patch 机制**：各模块内一律 `from . import session` 后 `session.get_game()` 属性查找（不写 `from .session import get_game` 绑死）；**同步修改全部既有测试 patch 目标** `frontend.routers.game.get_game` → `frontend.routers.game.session.get_game`。
- **R7 循环导入**：session ↔ combat（combat 需要 get_game）用函数内懒导入打破。
- init 兜底两份合一在 Task 2 已做；此处确认无残留重复。
- server.py 的 router 挂载改 import 包（`from frontend.routers.game import router`）。

- [ ] **Step 2: 等价验证**

Run: `python -m pytest tests/test_frontend_contract.py tests/test_frontend_character.py -q`
Expected: 全绿（契约测试证明行为等价）

- [ ] **Step 3: 全量 + 提交**

Run: `python -m pytest tests/ -q`

```bash
git add frontend/ tests/ MAINTENANCE.md
git commit -m "refactor: game.py 1191 行拆为 routers/game/ 包（session/turn/combat/charcard/slash），URL 与响应不变"
```

---

## §3 JS 模块化 + HTML→JSON 收敛

### Task 4: static/js/ 按域拆分

**Files:**
- Create: `frontend/static/js/api.js` / `state.js` / `scene.js` / `combat.js` / `charcard.js` / `ws.js`
- Modify: `frontend/templates/game.html`（瘦身为 markup + module 入口）
- Modify: `frontend/templates/base.html`（htmx 本地化）

- [ ] **Step 1: api.js / state.js（新写）**

**R1 警告（阻塞级）**：game.html 有 **21 处内联 `onclick`**（sendTurn/initGame/executeCombatRound 等）+ JS 动态拼的 onclick。`type="module"` 的作用域**不挂 window**——直接模块化会让所有按钮 `ReferenceError`。处置（二选一，写进实现说明）：① 入口模块显式 `window.sendTurn = sendTurn; …` 桥（搬迁期最快）；② 全部改 `addEventListener`（含动态拼接处，工作量大）。**推荐先 ① 后渐进 ②**；交付时 21 处逐一核对无遗漏。

**R8 警告**：`/api/game/turn`、`/api/game/init`、`/api/game/command` 都是 **`Form(...)`** 端点，现网 sendTurn/initGame 用 FormData；且 `process_turn` 引擎异常时返回 **200 + HTMLResponse**（非 JSON）。api 封装必须：这三端点走 FormData；响应按 `content-type` 分支（json / text 双通道），禁止默认 `JSON.stringify` + `resp.json()`。

```javascript
// api.js — fetch 封装：FormData/JSON 双通道 + content-type 分支
export async function postForm(url, formData) {
  const resp = await fetch(url, { method: "POST", body: formData });
  if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json()
       : { html: await resp.text() };   // 引擎异常的 200+HTML 兜底
}
export async function postJSON(url, data) { /* JSON 端点专用 */ }
export async function get(url) { /* 同上 content-type 分支 */ }

// state.js — 客户端状态单点（收 combatSession/chatMessages/开关）
// R15 拍板：DEBUG 合并为一个开关，键名统一 "trpg_debug"（沿用现网键，
// 原 trpg_autowin 等一并收编进 switches）
export const state = {
  combatSession: null,
  debug: localStorage.getItem("trpg_debug") === "1",
  chatMessages: [],
  switches: JSON.parse(localStorage.getItem("switches") || "{}"),
};
export function setSwitch(k, v) {
  state.switches[k] = v;
  localStorage.setItem("switches", JSON.stringify(state.switches));
}
```

- [ ] **Step 2: 搬迁映射（逐段移动，行为不变）**

| 目标 | game.html 内联段 |
|---|---|
| scene.js | sendTurn/sendTurnAction（**合并消重** :880-971 两份近同）/handleTurnResponse/updateSceneCard/renderTurnDynamic/renderSkillChips（:654-971） |
| combat.js | enterCombatMode/renderCombatPanel/executeCombatRound/handleCombatRoundResponse/finishCombat（:1024-1400） |
| charcard.js | 角色卡拉出/渲染逻辑 |
| ws.js | connectWS + step-indicator 更新（:980-990） |
| game.html | 仅保留 markup + `<script type="module">import ...</script>` 入口 |

- [ ] **Step 3: htmx 本地化**：下载 htmx 2.0.4 min 到 `frontend/static/js/vendor/htmx.min.js`，base.html:9 改本地引用。（离线脆弱点修复）

- [ ] **Step 4: escapeHtml 统一（R20 全量范围）**：api.js 或 util 导出 `escapeHtml`。**范围 = 所有进 `innerHTML` 的玩家/LLM 文本**，不止 :826 一处——已清点：`:826 data.brief`、`:830 narrative`、`:814 combat.narrative`、`:604-608` init brief/narrative、`:867` ending；服务端拼的 `narrative_html` 同样未转义（Task 5 结构化时一并处理）。

- [ ] **Step 5: 验证 + 提交**——前端无单测框架，验证 = 契约测试全绿 + 手动冒烟清单（写进 commit message）：开一局→发一句话→HUD 更新→战斗一轮→角色卡展开。

```bash
git add frontend/ MAINTENANCE.md
git commit -m "refactor: game.html 内联 JS 1148 行拆为 static/js 域模块；htmx 本地化；escapeHtml 统一"
```

### Task 5: 角色卡 + slash 输出 JSON 收敛（同一 Task 改前端加载，R10/R11）

**Files:**
- Modify: `frontend/routers/game/charcard.py`（:514-678 f-string → 返回 JSON）
- Modify: `frontend/routers/game/slash.py`（命令输出结构化：`narrative_html` → `{text, html?}`，服务端不再拼展示 HTML）
- Modify: `frontend/static/js/charcard.js` / `scene.js`（前端渲染 JSON；原 `htmx.ajax('GET','/api/game/character-card',…)` 会把 JSON 原文 dump 进面板，**必须同一 commit 改掉**）
- Modify: `tests/test_frontend_contract.py`（同步断言改 JSON 键）

- [ ] **Step 1: 改测试断言（红）**：character-card 断言从 HTML 子串改 JSON 键（name/hp/san/san_max/mp/mp_max/spells/skills/…）。
- [ ] **Step 2: 实现**：`/api/game/character-card` 返回结构化 JSON；charcard.js 模板渲染。绿。
- [ ] **Step 3: 提交**

---

## §4 布局修正

### Task 6: 面板可调 + 输入栏 + 开关组件

**Files:**
- Modify: `frontend/templates/game.html`（splitter 把手、输入栏、开关区 markup）
- Modify: `frontend/static/css/tailwind-built.css`（新增工具类）
- Create: `frontend/static/js/layout.js`

- [ ] **Step 1: layout.js**

```javascript
// 拖拽 splitter：side 决定符号（左栏拖右加宽；右栏拖左加宽）
export function initSplitter(handleEl, panelEl, storageKey,
                             {min = 200, max = 800, side = "left"} = {}) {
  const saved = localStorage.getItem(storageKey);
  if (saved) panelEl.style.width = saved + "px";
  handleEl.addEventListener("pointerdown", (e) => {
    const startX = e.clientX, startW = panelEl.offsetWidth;
    const sign = side === "left" ? 1 : -1;
    const move = (ev) => {
      const w = Math.min(max, Math.max(min, startW + sign * (ev.clientX - startX)));
      panelEl.style.width = w + "px";
    };
    const up = () => {
      localStorage.setItem(storageKey, String(panelEl.offsetWidth));
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  });
}
```

- [ ] **Step 2: 场景/角色面板加把手**（markup 加 `<div class="splitter">`）。**R19 修正**：现状场景 `w-64`（256px）/ 角色卡 `w-96`（384px）——**保持现默认不加宽**，只加可调能力（min 200 / max 800）；原 plan 的 320/380 是把场景加宽，废弃。**splitter 方向**：左侧栏（场景）拖右=加宽 `startW+(clientX-startX)`；**右侧栏（角色卡）符号相反** `startW-(clientX-startX)`——两套符号，实现时按栏位参数化（`initSplitter(..., {side: "left"|"right"})`）。
- [ ] **Step 3: 输入栏**：聚焦态描边+微发光（CSS `:focus-within`），发送按钮主色填充。
- [ ] **Step 4: 开关组件**：`.switch` CSS（轨道+滑块+文字标签+开/关两态色），DEBUG/AUTO_WIN 等统一接入 state.js `setSwitch`。
- [ ] **Step 5: 手动验证 + 提交**（无自动化：CSS/布局手测，勾选项写 commit message）

---

## §5 Debug panel

### Task 7: turn_trace 埋点（judge/keeper 只读记录）

**Files:**
- Modify: `src/game/judge.py`（实体评估处追加 trace 记录）
- Modify: `src/game/agents/keeper.py`（输入匹配结论记录）
- Modify: `src/game/messages.py`（TurnResult 可选 debug 键）
- Test: `tests/test_turn_trace.py`（新建）

- [ ] **Step 1: 失败测试**

```python
"""turn_trace：实体判定流水埋点（不改判定行为）。"""

class TestTurnTrace:
    def test_evaluated_entities_recorded(self):
        """回合后 trace 含：评估过的实体 + 各卡在哪（requirement/attitude/time/once）。"""
        # make_world + 实体 requirement 不满足 → trace 里该实体 available=False, reason 含缺失 requirement
    def test_matched_entity_recorded(self):
        """玩家输入匹配到实体 → trace.matched 含实体 id 与判定结论。"""
    def test_trace_off_by_default_zero_overhead(self):
        """不开 debug 时 trace 为空列表（零负载约定）。"""
```

- [ ] **Step 2: 实现（R18 全链路，只改一环不够）**——链路为：`Form(debug)`（turn.py 端点签名加 `debug: int = Form(0)`）→ `run_turn(..., debug=bool)`（game_loop 透传）→ `TurnContext.trace = [] if debug else None`（runner ctx）→ judge/keeper 埋点 → `PlayerTurnResult.debug`（messages.py 加可选键）→ JSON 响应 `debug` 键。
  - **零负载约定**：默认每回合仅 `if ctx.trace is not None` 一次判断；debug 端点的场景实体重算只在被调用时发生。
  - **只读红线**：场景实体可用性重算只用 `_evaluate_requirement` 类纯检查函数；**禁止调 `check_auto_triggers` / `_execute_entity`**（有副作用）。
  - judge `check_auto_triggers` / requirement 检查处 `if ctx.trace is not None: ctx.trace.append({...})`；keeper 匹配结论同。
- [ ] **Step 3: 绿 + real_llm_smoke**（动了 keeper/judge 主路径）

### Task 8: debug 聚合端点

**Files:**
- Create: `frontend/routers/game/debug.py`（`GET /api/game/debug?turns=N`）
- Test: `tests/test_frontend_contract.py` 追加

- [ ] **Step 1: 失败测试**

```python
def test_debug_endpoint_aggregates(client, monkeypatch, tmp_path):
    """debug 端点 = turn_logs 回放 + 状态快照 + 场景实体可用性。"""
    # 假 world（chronicle/current_location/player.derived/scene entities）
    # 断言响应四键：recent_turns / state_snapshot / scene_entities / llm_records
```

- [ ] **Step 2: 实现**

```python
@router.get("/api/game/debug")
def game_debug(turns: int = 5):
    from . import session
    game = session.get_game()
    world = game["keeper"].world
    return {
        # 复用：当前会话 TurnLogger 落盘的 jsonl 读最近 N 行
        # R6：目录从 game_loop._turn_logger.log_dir 取（setup_logging 实际值），
        #     禁止写死 data/debug/turn_logs/
        "recent_turns": _read_recent_turn_logs(turns),
        # 实时：world 直读
        "state_snapshot": _snapshot(world),
        # 只读重算：当前场景全实体 available + 原因（只用 _evaluate_requirement 纯检查）
        "scene_entities": _entity_availability(world),
        # 复用：prompt log 目录最近文件摘要（目录来源同 R6）
        "llm_records": _recent_llm_logs(turns),
    }
```

`_entity_availability` 遍历当前场景 interactions/auto_triggers，对每个调既有 requirement 检查函数（judge 侧 `_evaluate_requirement`）取通过/失败原因——**只读，不触发任何副作用**。

- [ ] **Step 3: 绿 + 提交**

### Task 9: debug.js 面板

**Files:**
- Create: `frontend/static/js/debug.js`
- Modify: `frontend/templates/game.html`（工具栏 bug 开关 + 面板容器）

- [ ] **Step 1: 实现**——四节折叠（触发流水/实体可用性/检定明细/LLM 记录）；开关走 §4 switch 组件（**R15 拍板：与现有 `trpg_debug` 合并为一个开关**——原 DBG 的敌人详情/整页 reload 信息收编为 panel 一节或保留其行为但共用开关状态，实现时二选一并写明）；开启时 turn 请求 FormData 带 `debug=1` 并把响应 `debug` 键渲染进「当回合触发流水」。
- [ ] **Step 2: 手动验证**（spec §8.3 场景：开一局→开 debug→输行动→四节有数据）+ 提交

---

## §6 F39 / F42 / F40

### Task 10: F39 历史回看

**Files:**
- Modify: `src/scenario_core.py` WorldChronicle（:1901 加 `narrative_log` deque maxlen=200；入档 to_dict/from_dict 加键，旧档 additive-default 空列表）
- Modify: `src/game_loop.py`（**R5：`record_turn`（:375）在 `narrator.narrate`（:472）之前，record 时叙事不存在**——在 narrate 成功之后单独 `chronicle.record_narrative(turn_number, brief, narrative)`；**不后移 record_turn**（会改 Author 编年时序）；`narrative_log` **不进 `render_for_author`**）
- Modify: `frontend/routers/game/views.py`（`GET /api/game/history?before_turn=N&limit=20`）
- Create: `frontend/static/js/history.js`
- Modify: `frontend/templates/game.html`（**R16 拍板：删除内联 chatMessages「对话记录」区**，由 history 面板替换；刷新后从 chronicle 重建最近 N 条）
- Test: `tests/test_chronicle.py` 扩 + 契约测试

- [ ] **Step 1: 失败测试**——narrate 后 record_narrative 使 narrative_log 含叙事全文（截断 2000 字）；save→load 后仍在；`render_for_author` 输出**不含** narrative_log 内容；端点分页形状；旧档（无此键）load 默认空列表。
- [ ] **Step 2: 实现**（deque 入档：to_dict/from_dict 加键，v 旧档 additive-default 空列表）。
- [ ] **Step 3: history.js 面板**（倒序、滚动到底加载更早；入口按钮放工具栏）。绿 + 提交。

### Task 11: F42 真实进度

**Files:**
- Modify: `src/game/turn/runner.py`（**`TurnRunner.execute`** 加 `on_phase` 回调）
- Modify: `src/game_loop.py`（run_turn 传回调 → 推 progress queue）
- Modify: `frontend/routers/game/turn.py`（删假进度推送 game.py 原 :327-333；process_turn 拆内部函数从 Task 3 移来此处做）
- Test: `tests/test_turn_runner_progress.py`（新建）

**R4 约束（阻塞项，先读再写）：**
- **对外 WS 步名保持现网**：`parse/judge/enrich/combat_entry/curate/narrate/complete`。runner 相位 → 对外步名映射表（写入实现注释）：understand→parse、adjudicate→judge、encounter→combat_entry、enrich→enrich、finalize→narrate（finalize 内含 narrate 后处理；curate 如对应独立环节单独推）。
- **线程安全**：进度推送发生在 `run_in_executor` 工作线程 → 回调内用 `loop.call_soon_threadsafe(queue.put_nowait, msg)` 或改 `queue.Queue`；禁止直接 `asyncio.Queue.put_nowait`。
- **边界**：Restart 重跑时相位会重复推（允许，前端按最新状态覆盖）；Early/SUSPENDED 早退时只推已执行相位 + 必须最终推 `complete`（前端在 `complete` 关闭进度条，现网 game.py:748 依此）。

- [ ] **Step 1: 失败测试**

```python
def test_phase_callbacks_fire_in_order():
    """on_phase 按 understand→adjudicate→encounter→enrich→finalize 顺序触发（runner 内部名）。"""
    seen = []
    # runner.execute(..., on_phase=lambda name, status: seen.append((name, status)))
    names = [s[0] for s in seen if s[1] == "done"]
    assert names == ["understand", "adjudicate", "encounter", "enrich", "finalize"]

def test_early_exit_still_completes():
    """Early/SUSPENDED 早退：只推已执行相位，且 run_turn 层最终推 complete。"""
```

- [ ] **Step 2: 实现**——`execute` 每相位前后调 `on_phase(name, "start"|"done")`；run_turn 注入回调（内部名→对外步名映射 + `call_soon_threadsafe` 推队列 + 保证 `complete`）；turn.py 删假推送。
- [ ] **Step 3: 绿 + real_llm_smoke + 提交**

### Task 12: F40 会话恢复（**2026-09-06 拍板：战斗场次原子化**）

**语义**：不做战斗过程持久化（难度大意义小）。战斗中刷新/读档 = 丢弃进行中战斗，世界恢复到**战斗前**状态（战斗未 resolve_outcome 则 world 未结算）；战斗中 autosave 若发生，写盘的是战斗前 world + 不写 active_combat。

**Files:**
- Modify: `frontend/templates/game.html` / `static/js/scene.js`（**R2 页面 bootstrap**：`DOMContentLoaded` 时 GET `/api/game/state`；已有对局（world 有 player）→ 跳过 `#game-setup` 直接显示 `#game-screen` 并渲染当前状态；无对局 → 维持 setup 页）
- Modify: `frontend/routers/game/views.py`（`/api/game/state` 响应足以支撑 bootstrap：scene 描述/HUD/是否游戏中；**不返回 active_combat**）
- Modify: `frontend/routers/game/combat.py`（combat/start 时把「战斗前快照」标记写入 `_combat_sessions` 元信息；**会话丢失（进程重启/刷新后服务端 dict 清空）时 `/api/combat/round` 返回明确错误码而非 500**，前端收到后退出战斗模式回到探索态）
- Test: `tests/test_frontend_contract.py` 追加

- [ ] **Step 1: 失败测试**

```python
def test_state_supports_bootstrap(client):
    """state 响应含 bootstrap 所需：in_game/scene/HUD（无 active_combat 键）。"""

def test_combat_round_without_session_clean_error(client):
    """会话丢失后 /api/combat/round 返回 409/410 + 明确错误（不 500）。"""
```

- [ ] **Step 2: 实现**——bootstrap JS；state 响应补 `in_game`；combat/round 会话缺失改返回 `JSONResponse({"error": "combat_session_lost"}, status_code=409)`；combat.js 收到 409 → `finishCombat(silent)` 回探索态。
- [ ] **Step 3: 绿 + 手动验收（区分两种场景）**：① 同进程刷新：bootstrap 直接回游戏屏；② 战斗中刷新：回到探索态无报错；③ 新进程读档（slash /load）：正常恢复非战斗状态。

**R3 原方案（完整 CombatState 序列化入档）废弃**，原因：拍板战斗原子化。若日后反悔，依据为 R3 事实清单（缺 temporary_effects/san_log/flags/log/_boss_current_phase）。

---

## 收口

### Task 13: 文档 + 最终验证

- [ ] ISSUES §5 收口：F39/F40/F42/B19；§2 移除对应行；**F22 notebook 呈现保留挂「前端后续批次」并注明「F39 批次有意缩小未含 notebook，非漏做」（R13）**
- [ ] MAINTENANCE.md 同步（新包结构/新端点/新 js 模块/新测试文件）
- [ ] `python -m pytest tests/ -q` 全绿 + real_llm_smoke（§5/§6 动过主路径）
- [ ] push（含此前未推的 spec commit）

---

## Self-Review 记录

- Spec 覆盖：§1→Task1-2；§2→Task3；§3→Task4-5；§4→Task6；§5→Task7-9；§6→Task10-12；§7 测试策略→各 Task 内嵌 + Task13；§8 验收→Task 6/9/13 手测清单。
- 占位符扫描：Task 1 清单中 `...` 处为「按现行实现读写临时路径」类指示——实现者需先读对应 router 函数现状再写断言（端点行为以代码为准，非占位）。
- 类型一致性：`state.js` 的 `state`/`setSwitch`、debug 响应四键、TurnResult.debug、Chronicle.narrative_log 全文一致。
- 风险：Task 4（JS 大搬迁）无自动化测试兜底，依赖手动冒烟——已在 Task 4 Step 5 明示；若冒烟发现问题按 systematic-debugging 处理。

---

## 审查记录（2026-09-06）

> 对照 spec `2026-09-05-frontend-upgrade-design.md`、本 plan、以及当时 HEAD 代码（`frontend/routers/game.py`、`game.html`、`TurnRunner`、`WorldChronicle`、`save_game`、`tests/test_frontend_contract.py`）。
> **状态（2026-09-06 更新）：R1-R21 已全部吸收进正文；三项拍板落定（F40 战斗原子化 / DEBUG 合并 / history 替换内联）。可按正文开工。**

### 阻塞（按现在写会做错或验收对不上）

| # | 项 | 事实 | 处置（执行前写入正文） |
|---|---|---|---|
| R1 | Task 4 ES module vs `onclick` | `game.html` ≥20 处内联 `onclick`（`sendTurn` / `initGame` / `executeCombatRound` 等）+ JS 动态拼的 `onclick`。`type="module"` 导出不挂 `window`。 | 入口显式 `window.sendTurn = …` 桥，或改 `addEventListener`。漏则按钮全 `ReferenceError`；无前端单测兜底。 |
| R2 | F40 验收「刷新」vs 测试「存档读档」 | `/game` 默认 `#game-setup` 可见、`#game-screen` `display:none`；无 onload 拉 `/api/game/state`；点开始走 `/api/game/init` **整局重开**。同进程刷新也会停在设置页。 | 补页面 bootstrap：已有对局则跳过 setup、拉 state、有 `active_combat` 则重建面板。slash `/load` 回填 `_combat_sessions`。验收区分「同进程刷新」和「新进程读档」。 |
| R3 | F40 序列化不是 CombatState 往返 | `_serialize_combat_state_for_frontend` 是 UI 子集；`_deserialize_enemies_for_combat` 只还原敌人给 `CombatInit`。缺 `temporary_effects` / `san_log` / `_player_dodging|_concealed|_aim_counter` / `log` / `_boss_current_phase` 等。`save_game` 只写 `turn_number`+`session_state`，战斗在 frontend 进程 dict。 | 先拍板：只恢复外观 vs 可继续战斗。后者需完整 `CombatState` 序列化 + `extra_meta["active_combat"]`（或等价注入）；CLI 无战斗会话时 additive 兼容。 |
| R4 | F42 三套相位名 + 线程 | 现网 WS：`parse/judge/enrich/combat_entry/curate/narrate/complete`。spec：`parse/judge/enrich/narrate`。plan：`understand/adjudicate/encounter/enrich/finalize`。`TurnRunner.execute`（不是 `run`）。进度在 `run_in_executor` 工作线程；`asyncio.Queue.put_nowait` 非线程安全。现假进度在 async 协程、LLM 返回后才推。 | 对外步名对照表（建议继续 `parse/judge/…`）。回调用 `call_soon_threadsafe`（或 `queue.Queue`）。写清 `Restart` 重跑、`Early`/`SUSPENDED`、以及必须推 `complete`。 |
| R5 | F39 写入点尚无叙事 | `chronicle.record_turn` 在 `narrator.narrate` **之前**，入参是 keeper `TurnResult`（`brief` 为 `NarratorBrief`）。玩家 `narrative` 字符串此时不存在。 | 在 `narrate` 之后写 `narrative_log`（或后移 `record_turn`，但会改 Author 编年时序）。`narrative_log` **不进** `render_for_author`。 |
| R6 | TurnLogger 路径 | 类默认 `data/debug/turn_logs/<ts>/`；前端/CLI 实际 `setup_logging()` → `logs/prompt_log_<ts>/`，turn 与 prompt/LLM 同目录。 | debug 端点读当前 `_turn_logger.log_dir` / prompt log getter，禁止写死 `data/debug/turn_logs/`。init 须把 `log_dir` 留在可查询处。 |
| R7 | re-export 救不了 patch | 测试 `patch("frontend.routers.game.get_game")` 有效是因为同模块查找。`turn.py` `from .session import get_game` 绑死后 patch 包 re-export 无效。另：session ↔ combat 循环导入。 | 用 `session.get_game()` 属性查找，patch 目标改为 `frontend.routers.game.session.get_game`；或抽 `_state.py`。函数内懒导入打破环。 |
| R8 | `api.js` JSON vs Form | turn / init / command 均为 `Form(...)`。现网 `sendTurn`/`initGame` 用 `FormData`。`process_turn` 引擎异常返回 **200 + HTMLResponse**。 | `api.post` 对上述端点走 FormData；保留 HTML/JSON `content-type` 分支。勿默认 `JSON.stringify` + `resp.json()`。 |
| R9 | 34 端点契约误打真管线 | `get_game()` 空实例会真 `init_game`；`/api/game/init` 再 `run_turn("[游戏开始]")`（LLM）；`step0/start`、`pipeline/start` 起后台进程；`/editor/save` 写盘；`generate-description` 也是 LLM。 | 副作用端点只测校验失败（422/400），禁止 happy-path。游戏端点必须 patch `get_game`。附 34 端点全表（不含 `/health`）。 |

### spec / plan / 代码不一致

| # | 项 | 说明 |
|---|---|---|
| R10 | 「不改响应形状」vs §3 JSON | spec 开头 vs Task 5 把 `character-card` HTML→JSON。现网 `htmx.ajax('GET', '/api/game/character-card', …)` 会把 JSON 原文 dump 进面板。原则改为：URL 不变；角色卡（及已声明的 slash）形状在 §3 显式破坏，同一 Task 改前端加载。Task 1 锁 HTML、Task 5 改断言。 |
| R11 | slash 结构化无 Task | spec §3「slash 命令输出结构化」；现网 JSON 内 `narrative_html`。并进 Task 5 或写入不做项。 |
| R12 | B19 两处不对称 | 静默吞异常只在 `init_game_api:817-823` → `_make_default_inv()`。`get_game:152-158`：文件不存在才内联建卡（名「调查员A」≠ `_make_default_inv` 的「调查员」）；加载抛错会外抛。合一是对的，勿写成两处都静默。lazy `get_game` 是否也带 `warning` 写清。 |
| R13 | F22 vs F39 | ISSUES：F22 notebook「随 F39 批次」。spec/plan：本轮不做。Task 13 更新 ISSUES 时注明有意缩小，避免下轮当漏做。 |
| R14 | Task 1 编辑器示例写错 | `/editor/validate` 是 `Form(path, content)`，不是 `json={scenes, entities}`（会 422）。空 scenes 现行为 `{"valid": true, "warnings": [...]}`，不 reject。测试名 `test_validate_rejects_empty` 会诱使去「修」F33 余项。断言现状即可。 |

### 不明确（不写死会各写各的）

| # | 项 | 问的是什么 |
|---|---|---|
| R15 | 两套 DEBUG | 现网 `DBG`：`trpg_debug` / `?debug=1` / 整页 reload / 敌人详情。新 panel：turn 带 `debug=1`、四节折叠。`state.js` 示例 `localStorage.DEBUG` 与 `trpg_debug`/`trpg_autowin` 都对不上。合并还是两个开关。 |
| R16 | 历史 UI 双轨 | 已有 `#chat-history-inline` + `chatMessages`（≤200 HTML，刷新即丢）。F39 再加 `history.js`。替换还是两入口。刷新后内联仍空会被当成「对话记录」坏了。 |
| R17 | Task 3 模块表漏约 400 行 | 未分配：`game_page`、`player_status`、`game_command`、`scene_info`、WS + `_push_progress`、`game_state`、`autowin`、`_known_spell_names`。 |
| R18 | `debug` 全链路 | 应：`Form(debug)` → `run_turn(..., debug=)` → `TurnContext.trace=[]` → `PlayerTurnResult.debug` → JSON。只改 `TurnResult` / keeper/judge 不够。零负载 = 每回合 `if ctx.trace is not None`；端点重算是 debug 开销。只用 `_evaluate_requirement` 只读，禁止 `check_auto_triggers` / `_execute_entity`。 |
| R19 | 布局默认宽度 vs 收窄 | 场景现 `w-64`（256px）、角色卡 `w-96`（384px）。plan 320/380 是场景加宽。右侧 splitter `startW+(clientX-startX)` 方向反了，左右栏两套符号。 |
| R20 | XSS 范围 | plan 只点 `:826 data.brief`。同类直插：`:830 narrative`、`:814 combat.narrative`、`:604-608` init brief/narrative、`:867` ending；服务端 `narrative_html` 同样未转义。范围 = 所有进 `innerHTML` 的玩家/LLM 文本。 |
| R21 | Task 3「顺势拆 3 个私有函数」 | 与「逐行移动、不改逻辑」冲突；假进度又在 Task 11 删除。建议 Task 3 纯搬迁，拆函数并入 Task 11。 |

### 相对扎实（可保留）

- 阶段顺序：契约网 → 拆后端 → 拆 JS → 再叠功能。
- 角色卡 JSON 放在 JS 模块化之后，避免 htmx 半残。
- Chronicle `events` 窗口 15、不存叙事全文，与代码一致；`narrative_log` additive 键正确（写入点见 R5）。
- `_evaluate_requirement` 只读，适合可用性重算。
- htmx 本地化确实需要（launcher/character/editor 的 `hx-*` + 游戏页 `htmx.ajax`）。
- B19 init 加 `warning` 为 additive。
- Task 4 手测清单（开局→一句话→HUD→战斗一轮→角色卡）覆盖无前端单测的缺口。

### 执行前决策清单（写入正文后再开工）

1. Task 4：`window.*` 桥或去掉全部 `onclick`；turn/init/command 走 FormData；保留双 content-type。
2. F40：页面 onload 恢复会话；完整 `CombatState` 入档；验收区分同进程刷新 / 新进程读档。
3. F42：WS 步名对照表；`call_soon_threadsafe`；SUSPENDED/Restart/`complete` 规则。
4. F39：`narrate` 之后写 `narrative_log`；不进 Author render；与内联「对话记录」的关系。
5. Debug：读 `setup_logging()` 当前 `log_dir`；DBG vs panel；HTTP `debug` → `PlayerTurnResult.debug`。
6. Task 3：补模块归属表；属性查找 + 改 patch；不指望 re-export。
7. Task 1：34 端点全表 + 副作用只测失败路径。
8. spec 原则：「URL 不变；响应形状仅角色卡（及已声明 slash）在 §3 变更」。
