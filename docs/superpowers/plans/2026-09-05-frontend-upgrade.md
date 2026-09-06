# 前端专项 Implementation Plan（2026-09-05）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端结构重构（方案 B 模块化）+ 契约测试防护网 + 布局修正 + debug panel + F39/F42/F40。

**Architecture:** 六阶段递进，§1 契约测试先行锁行为，§2/§3 结构迁移（URL/响应形状不变），§4-§6 功能落在新结构上。

**Spec:** `docs/superpowers/specs/2026-09-05-frontend-upgrade-design.md`（范围/不做项以此为准）

**已知事实（勿重复探索）：**
- 栈：FastAPI + Jinja2 + htmx 2.0.4（CDN base.html:9，需本地化）+ 无构建步骤。34 端点地图见调研（已附相关行号于各 Task）。
- `game.py` 行号分区：全局态 :20-31 / 战斗序列化 :34-102 / 库与 get_game :105-165 / slash :173-250 / process_turn :253-501 / charcard :514-678 / 状态小接口 :681-735 / WS :737-766 / init :769-859 / combat 端点 :892-1135 / 工具 :1138-1191。
- `game.html` 1444 行，内联 JS ~1148 行（:293-1443）；全局裸奔变量 combatSession/combatSelections/DEBUG/chatMessages（:640,:1024-1025）。
- TurnLogger（src/game/turn_logger.py）：`data/debug/turn_logs/<ts>/turn_log.jsonl`，记录 input+enrich+narrator。prompt/LLM 全文日志经 `prompts.set_prompt_log_dir` / `llm.set_llm_log_dir`。
- 回合五宏阶段：`src/game/turn/runner.py` TurnRunner 编排 phase_a_understand → phase_b_adjudicate → phase_c_encounter → phase_d_enrich → phase_e_finalize（各在 src/game/turn/ 同名文件）。
- WorldChronicle（scenario_core.py:1901）：events deque maxlen=**15**、只存截断 input(60字)+intent/实体结果，**不存叙事全文** → F39 需扩存储（见 Task 9）。
- Chronicle 已入档（随 save/load）；record_turn 由 game_loop.py:373-377 调用。
- 战斗序列化已有：game.py:34-102 `_serialize_combat_state_for_frontend` 等（契约测试 test_frontend_contract.py:118-124 已锁）。
- `_combat_sessions`（game.py:30）进程内存 dict；前端 combatSession 亦内存（game.html:1024）。
- 现有前端测试范式：TestClient + `patch("frontend.routers.game.get_game", ...)` + SimpleNamespace 假 game（test_frontend_contract.py 全文为范）。
- WS：`/api/game/progress`（game.py:737-766）队列广播；假进度根因 game.py:327-333（跑完一次性推 done）。
- 拆分后 import 路径变化会破坏现有 patch 目标（`frontend.routers.game.get_game`）——§2 拆分时**保留 re-export 别名**，旧 patch 路径继续有效。

---

## §1 契约测试防护网 + B19

### Task 1: 34 端点契约测试扩编

**Files:**
- Modify: `tests/test_frontend_contract.py`（现有 9 例保留，新增按 router 分 class）

- [ ] **Step 1: 写契约测试（先红不红皆可——大部分是补锁，预期直接绿；个别发现坏行为则记录不修）**

范式沿用现有 fixture（TestClient + patch get_game）。覆盖清单（每端点至少 1 例：状态码 + 关键键/标记）：

```python
class TestLauncherContract:
    def test_launcher_page(self, client):
        assert client.get("/").status_code == 200

    def test_tabs(self, client):
        for tab in ("config", "step0", "game-start", "module-gen"):
            r = client.get(f"/launcher/tabs/{tab}")
            assert r.status_code == 200

    def test_config_roundtrip(self, client, tmp_path):
        # POST /api/config/save → GET /api/config/load 键集合一致
        ...  # 按 launcher.py:69-97 实际实现读写临时路径

    def test_pipeline_validate(self, client):
        r = client.post("/api/pipeline/validate", data={...})
        assert r.status_code == 200


class TestCharacterContract:
    def test_character_page(self, client): ...
    def test_steps_1_to_3(self, client): ...
    def test_roll_returns_html(self, client):
        r = client.post("/character/roll", data={...})
        assert r.status_code == 200 and "<" in r.text
    def test_skills_list(self, client): ...
    def test_export_get_page(self, client): ...


class TestEditorContract:
    def test_editor_page(self, client): ...
    def test_validate_rejects_empty(self, client):
        r = client.post("/editor/validate", json={"scenes": {}, "entities": []})
        assert r.status_code == 200  # 按 editor.py:87-102 实际响应形状断言


class TestFilesAssetsContract:
    def test_files_listing(self, client): ...
    def test_assets_random(self, client): ...


class TestGameContract:
    def test_game_page(self, client):
        assert client.get("/game").status_code == 200

    def test_turn_contract(self, client):
        # 现有 test_turn_endpoint_forwards_pending_interaction 已覆盖，此处补
        # 响应固定键集合：brief/narrative/turn_dynamic_text/player_snapshot/
        # skill_results/combat_init/pending_interaction/game_over/ending
        ...

    def test_state_shape(self, client): ...   # /api/game/state 固定键
    def test_scene_and_command(self, client): ...  # /api/game/scene、/api/game/command
    def test_autowin_toggle(self, client): ...
    def test_combat_start_requires_session(self, client):
        # /api/combat/start 无初始化游戏时的行为锁定
        ...
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

- [ ] **Step 2: 跑确认红 → 实现（两处兜底合并为一个 `_load_character_or_default()` 返回 `(inv, warning|None)`；init JSON 加 `warning` 键）→ 绿**

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
- Create: `frontend/routers/game/__init__.py`（router 聚合 + **re-export**：`get_game`、`process_turn`、`_serialize_combat_state_for_frontend` 等现有 patch/测试引用名）
- Create: `frontend/routers/game/session.py` / `turn.py` / `combat.py` / `charcard.py` / `slash.py`
- Delete: `frontend/routers/game.py`

- [ ] **Step 1: 按下表搬迁（逐行移动，不改逻辑）**

| 目标文件 | 内容（现行号） |
|---|---|
| session.py | 全局态 :20-31、`_init_libraries`/`get_game` :105-165、`init_game_api` :769-859、`_make_default_inv` 等工具 :1138-1191 |
| turn.py | `process_turn` :253-501（含进度推送、autosave 调用） |
| combat.py | 序列化 :34-102、`/api/combat/start|round` :892-1135 |
| charcard.py | `character_card` :514-678 |
| slash.py | `_handle_slash_command` :173-250 |
| `__init__.py` | `APIRouter` 聚合 + re-export 兼容层 |

- process_turn 内部顺势拆 3 个私有函数（_run_pipeline / _push_all_progress / _build_response），**行为不变**。
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

```javascript
// api.js — fetch 封装：统一错误处理 + JSON
export async function post(url, data) {
  const resp = await fetch(url, { method: "POST",
    body: data instanceof FormData ? data : JSON.stringify(data),
    headers: data instanceof FormData ? {} : {"Content-Type": "application/json"} });
  if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
  return resp.json();
}
export async function get(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} → ${resp.status}`);
  return resp.json();
}

// state.js — 客户端状态单点（收 combatSession/DEBUG/chatMessages）
export const state = {
  combatSession: null,
  debug: localStorage.getItem("DEBUG") === "1",
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

- [ ] **Step 4: escapeHtml 统一**：api.js 或新 util 导出 `escapeHtml`，scene.js 渲染处（原 :826 `data.brief` 直插）全部走转义。

- [ ] **Step 5: 验证 + 提交**——前端无单测框架，验证 = 契约测试全绿 + 手动冒烟清单（写进 commit message）：开一局→发一句话→HUD 更新→战斗一轮→角色卡展开。

```bash
git add frontend/ MAINTENANCE.md
git commit -m "refactor: game.html 内联 JS 1148 行拆为 static/js 域模块；htmx 本地化；escapeHtml 统一"
```

### Task 5: 角色卡 HTML→JSON 收敛

**Files:**
- Modify: `frontend/routers/game/charcard.py`（:514-678 f-string → 返回 JSON）
- Modify: `frontend/static/js/charcard.js`（前端渲染）
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
// 拖拽 splitter：pointerdown 记起点 → pointermove 改宽度 → pointerup 存 localStorage
export function initSplitter(handleEl, panelEl, storageKey, {min = 200, max = 800} = {}) {
  const saved = localStorage.getItem(storageKey);
  if (saved) panelEl.style.width = saved + "px";
  handleEl.addEventListener("pointerdown", (e) => {
    const startX = e.clientX, startW = panelEl.offsetWidth;
    const move = (ev) => {
      const w = Math.min(max, Math.max(min, startW + (ev.clientX - startX)));
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

- [ ] **Step 2: 场景/角色面板加把手**（markup 加 `<div class="splitter">`），默认宽度收窄（具体像素手测定，初值场景 320px / 角色卡 380px）。
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

- [ ] **Step 2: 实现**——`TurnRunner` 的 ctx 挂 `trace: list | None`（默认 None=零负载）；judge `check_auto_triggers` / requirement 检查处 `if ctx.trace is not None: ctx.trace.append({...})`。keeper 匹配结论同。`frontend` 请求带 debug=1 时 keeper 开启 trace 并把结果放进响应 `debug` 键。
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
    game = get_game()
    world = game["keeper"].world
    return {
        # 复用：TurnLogger 落盘的 jsonl 读最近 N 行
        "recent_turns": _read_recent_turn_logs(turns),
        # 实时：world 直读
        "state_snapshot": _snapshot(world),
        # 只读重算：当前场景全实体 available + 原因（复用 judge requirement 检查）
        "scene_entities": _entity_availability(world),
        # 复用：prompt log 目录最近文件摘要
        "llm_records": _recent_llm_logs(turns),
    }
```

`_entity_availability` 遍历当前场景 interactions/auto_triggers，对每个调既有 requirement 检查函数（judge 侧）取通过/失败原因——**只读，不触发任何副作用**。

- [ ] **Step 3: 绿 + 提交**

### Task 9: debug.js 面板

**Files:**
- Create: `frontend/static/js/debug.js`
- Modify: `frontend/templates/game.html`（工具栏 bug 开关 + 面板容器）

- [ ] **Step 1: 实现**——四节折叠（触发流水/实体可用性/检定明细/LLM 记录）；开关走 §4 switch 组件；开启时 turn 请求带 `debug=1` 并把响应 `debug` 键渲染进「当回合触发流水」。
- [ ] **Step 2: 手动验证**（spec §8.3 场景：开一局→开 debug→输行动→四节有数据）+ 提交

---

## §6 F39 / F42 / F40

### Task 10: F39 历史回看

**Files:**
- Modify: `src/scenario_core.py` WorldChronicle（:1901 加 `narrative_log` deque maxlen=200，record_turn 存 turn/input/brief/narrative 截断 2000 字；入档）
- Modify: `frontend/routers/game/`（`GET /api/game/history?before_turn=N&limit=20`）
- Create: `frontend/static/js/history.js`
- Test: `tests/test_chronicle.py` 扩 + 契约测试

- [ ] **Step 1: 失败测试**——record_turn 后 narrative_log 含叙事全文；save→load 后仍在；端点分页形状。
- [ ] **Step 2: 实现**（deque 入档：to_dict/from_dict 加键，v 旧档 additive-default 空列表）。
- [ ] **Step 3: history.js 面板**（倒序、滚动到底加载更早；入口按钮放工具栏）。绿 + 提交。

### Task 11: F42 真实进度

**Files:**
- Modify: `src/game/turn/runner.py`（TurnRunner 加 `on_phase` 回调，五相位各调一次）
- Modify: `src/game_loop.py`（run_turn 传回调 → 推 progress queue）
- Modify: `frontend/routers/game/turn.py`（删假进度推送 game.py 原 :327-333）
- Test: `tests/test_turn_runner_progress.py`（新建）

- [ ] **Step 1: 失败测试**

```python
def test_phase_callbacks_fire_in_order():
    """on_phase 按 understand→adjudicate→encounter→enrich→finalize 顺序触发。"""
    seen = []
    # runner.run(..., on_phase=lambda name, status: seen.append((name, status)))
    assert [s[0] for s in seen] == ["understand", "adjudicate", "encounter",
                                    "enrich", "finalize"]
```

- [ ] **Step 2: 实现**——TurnRunner 每相位前后调 `on_phase(name, "start"|"done")`；run_turn 注入回调推 `_progress_queues`；turn.py 删假推送。
- [ ] **Step 3: 绿 + real_llm_smoke + 提交**

### Task 12: F40 战斗刷新恢复

**Files:**
- Modify: `frontend/routers/game/combat.py`（_combat_sessions 快照入 save_game/autosave 链）
- Modify: `src/game_loop.py`（save/load 增 active combat 快照键）
- Modify: `frontend/routers/game/session.py`（`/api/game/state` 响应加 `active_combat`）
- Modify: `frontend/static/js/combat.js`（state 含活跃战斗 → 重建面板）
- Test: `tests/test_frontend_contract.py` + `tests/test_save_load.py` 追加

- [ ] **Step 1: 失败测试**

```python
def test_combat_session_survives_save_load(client, tmp_path):
    """战斗中存档 → 新进程读档 → /api/game/state 含 active_combat 当前轮次。"""
```

- [ ] **Step 2: 实现**——combat 会话用既有 `_serialize_combat_state_for_frontend` 的逆函数（战斗序列化 :34-102 已有双向，缺则补 `deserialize`）；save_game 加 `active_combat` 键；load 后回填 `_combat_sessions`。
- [ ] **Step 3: 绿 + 提交**

---

## 收口

### Task 13: 文档 + 最终验证

- [ ] ISSUES §5 收口：F39/F40/F42/B19；§2 移除对应行；F22 notebook 呈现保留挂「前端后续批次」
- [ ] MAINTENANCE.md 同步（新包结构/新端点/新 js 模块/新测试文件）
- [ ] `python -m pytest tests/ -q` 全绿 + real_llm_smoke（§5/§6 动过主路径）
- [ ] push（含此前未推的 spec commit）

---

## Self-Review 记录

- Spec 覆盖：§1→Task1-2；§2→Task3；§3→Task4-5；§4→Task6；§5→Task7-9；§6→Task10-12；§7 测试策略→各 Task 内嵌 + Task13；§8 验收→Task 6/9/13 手测清单。
- 占位符扫描：Task 1 清单中 `...` 处为「按现行实现读写临时路径」类指示——实现者需先读对应 router 函数现状再写断言（端点行为以代码为准，非占位）。
- 类型一致性：`state.js` 的 `state`/`setSwitch`、debug 响应四键、TurnResult.debug、Chronicle.narrative_log 全文一致。
- 风险：Task 4（JS 大搬迁）无自动化测试兜底，依赖手动冒烟——已在 Task 4 Step 5 明示；若冒烟发现问题按 systematic-debugging 处理。
