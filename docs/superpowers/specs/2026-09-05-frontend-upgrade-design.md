# 前端专项设计：结构重构 + 布局修正 + Debug Panel + 体验批（2026-09-05）

> 来源：2026-09-05 session 拍板。前置：前端调研报告（34 端点 / game.py 1191 行 / game.html 内联 JS ~1148 行 / 测试仅 14 例）。
> 原则：**结构重构走方案 B（模块化）**；契约测试先行做安全网；**重构保持 URL 不变，响应形状仅角色卡与 slash 输出在 §3 显式变更**（2026-09-06 审查修订 R10）；debug panel 最大化复用现有日志 infra。
> **2026-09-06 审查吸收**：R1–R21 修订见 plan 审查记录。拍板——F40 战斗场次原子化 + **方案 A 战前快照回滚**（不做 CombatState 持久化；刷新/丢会话时回滚到 combat/start 前并清会话）；DEBUG 开关合并为一个（沿用 `trpg_debug`，不再整页 reload）；F39 history 面板替换内联对话记录区。
> **战斗系统后续重置**：F40 回滚只求「刷新不卡在战斗 UI / 不丢整局」；快照粒度与边角（目睹 SAN、`san_seen_sources`、敌人 HP 镜像等）允许不完美，不在本轮打磨。实现时在 combat 模块注释标明。

## 0. 范围

**做**（六阶段）：
1. §1 契约测试防护网 + B19
2. §2 后端拆分（routers/game.py → 包）
3. §3 JS 模块化 + 服务端 HTML→JSON 收敛（只收敛被触到的）
4. §4 布局修正（panel 可调 / 输入栏 / 按钮态）
5. §5 Debug panel（复用 TurnLogger/prompt log + 轻量 turn_trace 埋点）
6. §6 F39 历史回看 / F42 真实进度 / F40 会话恢复（战斗原子化 + 战前快照回滚）

**不做**：整体美观翻新（下轮）、F36 管线进度、F43 角色卡导入、F37 undo、F38 存档 UI、F33/F35 前端余项、B23（待拍板）、F22 notebook 呈现（有意缩小，非漏做）、完整 CombatState 入档/战斗中途续打。

**顺序理由**：§1 防护网 → §2/§3 结构（后续功能都落在新结构上）→ §4/§5/§6 功能（顺序可调，§4 最小可穿插）。

## 1. 契约测试防护网 + B19

- 34 端点（调研 §2 地图为准，不含 `/health` 则 34、含则 35）全部补 TestClient 契约测试：状态码 + 响应形状（关键键存在性 + 类型），**锁定现状行为**——包括现有的丑（服务端拼 HTML 的端点只断言 HTML 片段含关键标记，不断言全文）。
- 放 `tests/test_frontend_contract.py` 扩编；按 router 分 class。
- **副作用分级**（禁止契约测试 happy-path 真跑 LLM/进程/写盘）：
  - 只测失败路径：`/api/game/init`、`/api/step0/start`、`/api/pipeline/start`、`/editor/save`、`/character/generate-description`、`POST /character/upload-avatar`
  - 游戏端点必须 patch `get_game`（空实例会真 `init_game`）
  - `/api/config/save` 必须 monkeypatch 配置路径（默认写仓库根 `config.json`）
- **B19**：两处兜底不对称，合一为 `_load_character_or_default() → (inv, warning|None)`。
  - `init_game_api`：加载抛错现静默默认卡 → 改为 JSON `warning` + toast「角色卡加载失败，已使用默认卡」
  - `get_game` lazy：文件不存在才内联建卡（名「调查员A」）；加载抛错会外抛 → 合并后与 init 同语义（抛错 → 默认卡 + warning）。默认卡名称统一为 `_make_default_inv`（「调查员」）。
  - B19 的 init 测试必须同时 stub `init_game` / `run_turn`，只 patch `load_investigator` 会打到真 LLM。

## 2. 后端拆分（game.py → routers/game/ 包）

| 新模块 | 内容（现状行号） |
|---|---|
| `session.py` | 全局态（:20-31）、`_init_libraries`、`get_game`（:105-165）、`init_game_api`（:769-859）、`_resolve_start_scene` / `_make_default_inv`（:1138-1191） |
| `turn.py` | `process_turn`（:253-501）+ `_push_progress` + WS（:737-766）。**本阶段纯搬迁**，内部拆函数放到 F42（plan Task 11） |
| `combat.py` | combat 序列化（:34-102）+ `/api/combat/start\|round`（:892-1135） |
| `charcard.py` | 角色卡渲染（:514-678）+ `_known_spell_names` |
| `slash.py` | `_handle_slash_command`（:173-250）+ `game_command` |
| `views.py` | `game_page`、`player_status`、`scene_info`、`game_state`、`autowin` |
| `__init__.py` | router 聚合，URL 不变；**不做 re-export** |

- 各模块一律 `from . import session` 后 `session.get_game()` 属性查找；测试 patch 目标改为 `frontend.routers.game.session.get_game`。session↔combat、session↔charcard 用函数内懒导入打破环。
- 消重：init 兜底角色两份合一（见 §1 B19）；函数体内反复 import 收敛到模块顶。
- 验收：§1 契约测试全绿 = 行为等价证明。

## 3. JS 模块化 + HTML→JSON 收敛

- `game.html` 内联 JS（~1148 行）→ `static/js/` ES modules（无构建步骤）：
  `api.js`、`state.js`、`scene.js`、`combat.js`、`charcard.js`、`debug.js`（§5）、`history.js`（§6）、`layout.js`（§4）、`ws.js`
- game.html 瘦身为 markup + `<script type="module">` 入口。**`type="module"` 不挂 `window`**：入口须显式 `window.sendTurn = sendTurn` 等桥接全部内联 `onclick`（含 JS 动态拼接处），或改为 `addEventListener`。推荐先桥后渐进。
- `api.js`：`/api/game/turn`、`/init`、`/command` 走 **FormData**；响应按 `content-type` 分支（JSON / 200+HTML）。禁止默认 `JSON.stringify` + `resp.json()`。
- `state.js` 开关：debug 沿用键 `trpg_debug`；`setSwitch` 与该键单一写入，不另造 `localStorage.DEBUG`。
- **收敛范围（YAGNI，只动被触到的）**：角色卡（服务端 f-string → JSON + charcard.js；同一变更去掉 `htmx.ajax('GET', '/api/game/character-card', …)`）；slash 输出结构化（`narrative_html` → `{text, html?}`，服务端不再拼展示 HTML）。**不动**：launcher/editor/character 向导页。
- XSS：所有进 `innerHTML` 的玩家/LLM 文本走 `escapeHtml`（brief / narrative / combat.narrative / init 开场 / ending / 服务端 `narrative_html`）。
- htmx CDN（base.html:9 unpkg）本地化为 `static/js/vendor/htmx.min.js`。

## 4. 布局修正（用户痛点 1）

- 场景/角色面板：拖拽调整大小（splitter，尺寸存 localStorage）。**默认宽度保持现状**（场景 `w-64`=256px / 角色卡 `w-96`=384px），只加可调，不加宽。左栏 `startW+(clientX-startX)`，右栏符号相反。
- 输入栏：视觉加强（聚焦态描边/发光、发送按钮主色）。
- on/off 类控件（DEBUG、AUTO_WIN）：统一 switch 组件 + 文字标签 + 状态色；与 `trpg_debug` / `trpg_autowin` 单一存储。
- 按钮视觉反馈：hover/active/禁用三态明确。
- 纯 CSS + 少量 JS（splitter），不动布局骨架（三栏结构保留）。

## 5. Debug panel（用户痛点 2）

**复用优先**（2026-09-05 拍板）：现有 infra 已覆盖 LLM 记录，新代码只补「实体判定流水」。

- **后端**：
  - 新增 `GET /api/game/debug?turns=N`：聚合 ① TurnLogger 最近 N 回合 ② prompt/LLM 日志摘要 ③ 实时状态快照（world 直读：HP/SAN/位置/flags/NPC 态度值/活跃 timed_effects/scene_items 余量）。
  - **日志目录**：实际是 `setup_logging()` 的 `logs/prompt_log_<ts>/`（turn 与 prompt/LLM 同目录）。端点读当前 `_turn_logger.log_dir` / prompt log getter，**禁止写死** `data/debug/turn_logs/`。
  - **唯一新埋点** `turn_trace`：全链路 `Form(debug)` → `run_turn(..., debug=)` → `TurnContext.trace = [] if debug else None` → judge/keeper 只读 append → **`PlayerTurnResult.debug`** → JSON `debug` 键。常态仅 `if ctx.trace is not None`。不改判定逻辑。
  - 场景实体可用性不由埋点产出：debug 端点实时重算；**只用** `_evaluate_requirement` 类纯检查，**禁止** `check_auto_triggers` / `_execute_entity`。
- **前端** `debug.js`：与现有 `trpg_debug` **合并为一个开关**（不再整页 reload）。原 DBG 敌人详情/潜在威胁在 debug 开时仍可用，同时打开四节折叠面板：
  1. 当回合触发流水（turn_trace）
  2. 场景实体可用性
  3. 检定/骰子明细（skill_results 增强展示）
  4. LLM 记录（enrich/narrator + prompt 摘要，可展开全文）
- 开启时 turn 请求 FormData 带 `debug=1`。

## 6. F39 / F42 / F40

- **F39 历史回看**：Chronicle `events` 仍只服务 Author（窗口 15、无叙事全文）。新增 `narrative_log` deque maxlen=200：在 **`narrator.narrate` 成功之后** 调 `chronicle.record_narrative(...)`（截断 2000 字）。**不后移** `record_turn`（会改 Author 编年时序）；**`narrative_log` 不进 `render_for_author`**。`GET /api/game/history?before_turn=N&limit=20` + history.js 面板替换现有内存 `chatMessages` 内联「对话记录」；刷新后从 chronicle 重建。旧档缺键 additive 空列表。F22 notebook 不在本轮。

- **F42 真实进度**：删除 `process_turn` 假进度（现网 game.py:327-333 一次推完）。对外 WS 步名**保持现网**：`parse / judge / enrich / combat_entry / curate / narrate / complete`。
  - `TurnRunner.execute` 的 `on_phase`（内部名）：understand→parse，adjudicate→judge，encounter→combat_entry，enrich→enrich，**finalize→curate**（curate 在 finalize 内）。
  - **`narrator.narrate` 在 `execute` 返回之后**（`game_loop.run_turn`）：由 **run_turn 在 narrate 前后单独推 `narrate`**，最后推 `complete`。不可把 finalize 映射成 narrate。
  - 进度发生在 `run_in_executor` 工作线程 → `loop.call_soon_threadsafe`（或 `queue.Queue`）。Restart 允许相位重复推；Early/SUSPENDED 只推已执行相位且**必须**最终 `complete`。

- **F40 会话恢复（战斗原子化 + 方案 A，2026-09-06）**：
  - 页面 bootstrap：`DOMContentLoaded` 打 `GET /api/game/state`。`_game_instance is None` 时返回 `{in_game: false}`，**禁止**经 `get_game()` lazy 建局。已有对局 → 跳过 setup 进游戏屏。
  - **不做** CombatState 入档、不返回 `active_combat`、不续打中途战斗。
  - **方案 A**：`/api/combat/start` 先拍一份「战斗前」world 快照写入 `_combat_sessions` 元信息（HP/SAN/MP、当前场景敌人 HP/状态、`san_seen_sources` 拷贝——求够用不求完备）。同进程刷新 / 会话丢失 / bootstrap 发现残留会话时：**回滚快照 + 清空 `_combat_sessions`**，前端回探索态。
  - `/api/combat/round` 无会话：现网已是 400；本轮改为 409 + `{"error": "combat_session_lost"}`（契约测试同步改），前端 `finishCombat(silent)`。
  - **战斗系统后续会重置**；本回滚允许边角不准（例如目睹 SAN、部分镜像字段）。注释标明，不单开打磨任务。

## 7. 测试策略

- §1 契约测试是全体安全网；§2/§3 后必须全绿。副作用端点只测失败路径（见 §1）。
- 新端点（debug/history）各有契约 + 行为测试（stub world/chronicle）。debug 断言日志目录来自当前 logger，不依赖 `data/debug/turn_logs/`。
- F42：runner `on_phase` 按内部名顺序；另测 run_turn 在 narrate 前后推对外步名 `narrate`，早退仍 `complete`。不跑真 WS。
- F40：state 空实例 `in_game=false` 且不调用 `init_game`；combat/start 后 round 无会话 → 409；有快照时丢弃会话后 HUD/敌人回到 start 前（允许测主路径 HP，不锁全部边角）。**不**断言 `active_combat`。
- turn_trace：stub 场景断言评估记录 + 失败原因；debug 关闭时 trace 为空。
- 默认收口 `pytest tests/ -q`；涉及 keeper/judge 主路径埋点后跑 `pytest -m real_llm_smoke`。

## 8. 验收标准

1. `pytest tests/ -q` 全绿（含 34 端点契约；副作用端点无真 LLM/真管线）。
2. game.html 无内联业务 JS（仅 module 入口 + 如采用的 `window.*` 桥）；game.py 拆包后无 >300 行函数（process_turn 内部拆在 F42 完成）。
3. debug panel 四节数据真实可用：新开一局 → 开 debug（不整页 reload）→ 输一个行动 → 面板显示触发流水 + 实体可用性 + LLM 记录。
4. 面板可拖且刷新后尺寸保持（默认宽度仍约 256/384）；输入栏/开关视觉态明显（手测确认）。
5. F39：刷新页面后历史仍在（history 面板，非旧内联 chatMessages）。F42：回合进行中 step-indicator 按 parse→…→curate→**narrate（在真正 narrate 期间）**→complete 变化。F40：战斗中刷新 → 回探索态、不卡战斗 UI；同进程有对局则 bootstrap 跳过 setup；不恢复战斗面板。
6. ISSUES §5 收口 F39/F40/F42/B19；F22 注明「F39 批次有意缩小未含 notebook」；MAINTENANCE.md 同步。
