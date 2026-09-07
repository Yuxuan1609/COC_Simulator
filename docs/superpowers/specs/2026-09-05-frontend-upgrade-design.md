# 前端专项设计：结构重构 + 布局修正 + Debug Panel + 体验批（2026-09-05）

> 来源：2026-09-05 session 拍板。前置：前端调研报告（34 端点 / game.py 1191 行 / game.html 内联 JS ~1148 行 / 测试仅 14 例）。
> 原则：**结构重构走方案 B（模块化）**；契约测试先行做安全网；**重构保持 URL 不变，响应形状仅角色卡与 slash 输出在 §3 显式变更**（2026-09-06 审查修订 R10）；debug panel 最大化复用现有日志 infra。
> **2026-09-06 审查吸收**：R1-R21 修订见 plan 审查记录；三项拍板——F40 战斗场次原子化（不做战斗过程持久化，刷新/读档恢复战斗前状态）、DEBUG 开关合并为一个（沿用 trpg_debug）、F39 history 面板替换内联对话记录区。

## 0. 范围

**做**（六阶段）：
1. §1 契约测试防护网 + B19
2. §2 后端拆分（routers/game.py → 包）
3. §3 JS 模块化 + 服务端 HTML→JSON 收敛（只收敛被触到的）
4. §4 布局修正（panel 可调 / 输入栏 / 按钮态）
5. §5 Debug panel（复用 TurnLogger/prompt log + 轻量 turn_trace 埋点）
6. §6 F39 历史回看 / F42 真实进度 / F40 战斗刷新恢复

**不做**：整体美观翻新（下轮）、F36 管线进度、F43 角色卡导入、F37 undo、F38 存档 UI、F33/F35 前端余项、B23（待拍板）。

**顺序理由**：§1 防护网 → §2/§3 结构（后续功能都落在新结构上）→ §4/§5/§6 功能（顺序可调，§4 最小可穿插）。

## 1. 契约测试防护网 + B19

- 34 端点（调研 §2 地图为准）全部补 TestClient 契约测试：状态码 + 响应形状（关键键存在性 + 类型），**锁定现状行为**——包括现有的丑（服务端拼 HTML 的端点只断言 HTML 片段含关键标记，不断言全文）。
- 放 `tests/test_frontend_contract.py` 扩编；按 router 分 class。
- **B19**：`init` 角色卡加载失败（game.py:152-158 / :817-823 两处重复兜底合并为一处）→ 响应带 `warning` 字段 + 前端 toast 提示「角色卡加载失败，已使用默认卡」。测试断言 warning 透出。

## 2. 后端拆分（game.py → routers/game/ 包）

| 新模块 | 内容（现状行号） |
|---|---|
| `session.py` | 8 个全局态（:20-31）、`_init_libraries`、`get_game`（:105-165）、`init_game_api`（:769-859） |
| `turn.py` | `process_turn`（:253-501，249 行混杂函数顺势按职责拆内部函数） |
| `combat.py` | combat 序列化（:34-102）+ `/api/combat/start|round`（:892-1135） |
| `charcard.py` | 角色卡 HTML 渲染（:514-678） |
| `slash.py` | 斜杠命令分发（:173-250） |
| `__init__.py` | router 聚合，URL 不变 |

- 消重：init 兜底角色两份（:152-158 ≈ :817-829）合一；函数体内反复 import 收敛到模块顶。
- 验收：§1 契约测试全绿 = 行为等价证明。

## 3. JS 模块化 + HTML→JSON 收敛

- `game.html` 内联 JS（~1148 行）→ `static/js/` ES modules（无构建步骤）：
  `api.js`（fetch 封装 + 错误统一）、`state.js`（客户端状态单点，收 combatSession/DEBUG 等裸奔全局）、`scene.js`、`combat.js`、`charcard.js`、`debug.js`（§5）、`history.js`（§6）
- game.html 瘦身为 markup + `<script type="module">` 入口。
- **收敛范围（YAGNI，只动被触到的）**：角色卡渲染（game.py:514-678 服务端 f-string → JSON + charcard.js 渲染）；slash 命令输出结构化。**不动**：launcher/editor/character 向导页（htmx 低频页保持现状）。
- XSS 转义统一走 `escapeHtml`（修 game.html:826 `data.brief` 直插）。
- htmx CDN（base.html:9 unpkg）本地化为 static/ 资源（调研发现的离线脆弱点，顺手）。

## 4. 布局修正（用户痛点 1）

- 场景/角色面板：拖拽调整大小（splitter，尺寸存 localStorage 持久），默认收窄。
- 输入栏：视觉加强（聚焦态描边/发光、发送按钮主色）。
- on/off 类控件（DEBUG、AUTO_WIN 等散落 localStorage 的开关）：统一 switch 组件 + 文字标签 + 状态色。
- 按钮视觉反馈：hover/active/禁用三态明确。
- 纯 CSS + 少量 JS（splitter），不动布局骨架（三栏结构保留）。

## 5. Debug panel（用户痛点 2）

**复用优先**（2026-09-05 拍板）：现有 infra 已覆盖 LLM 记录，新代码只补「实体判定流水」。

- **后端**：
  - 新增 `GET /api/game/debug?turns=N`：聚合 ① TurnLogger 最近 N 回合（`data/debug/turn_logs/<ts>/turn_log.jsonl`，复用）② prompt/LLM 日志目录最近记录（复用 `prompts`/`llm` 的 log dir）③ 实时状态快照（world 直读：HP/SAN/位置/flags/NPC 态度值/活跃 timed_effects/scene_items 余量）。
  - **唯一新埋点** `turn_trace`：judge/keeper 判定路径追加轻量内存记录——本回合评估了哪些实体、各卡在哪（requirement 缺哪条 / attitude_min 差多少 / time_condition 不符 / one-shot 已完成）、玩家输入匹配结论、检定明细（技能值/难度/骰面/修正来源）。挂在 turn result 的 `debug` 键（仅前端开关开启时组装，常态零负载）。不改判定逻辑本身。
  - 场景实体可用性不由埋点产出：debug 端点实时重算当前场景全部 interaction/AT 的 `available` + 原因（复用 judge 的 requirement 检查函数，只读）。
- **前端** `debug.js`：工具栏 bug 图标开关（状态可见，§4 switch 组件），面板四节折叠：
  1. 当回合触发流水（turn_trace）
  2. 场景实体可用性（哪些能触发/为什么不能）
  3. 检定/骰子明细（skill_results 增强展示）
  4. LLM 记录（enrich/narrator + prompt 摘要，可展开全文）
- 开关状态存 localStorage；开启时 turn 请求带 `debug=1`。

## 6. F39 / F42 / F40

- **F39 历史回看**：`GET /api/game/history?before_turn=N`（读 `world.chronicle` 已入档数据，game_loop.py:373-377 已在 record_turn）+ history.js 面板（倒序分页/滚动加载）；刷新不丢（Chronicle 随存档）。F22 notebook 呈现不在本轮（仍随前端后续批次）。
- **F42 真实进度**：run_turn 管线相位（parse/judge/enrich/narrate）埋回调 → 每相位完成即推 WS 进度（game.py:327-333 假进度删除）；前端 step-indicator 实时更新。相位列表从 keeper/TurnRunner 现有阶段结构取，不新造概念。
- **F40 会话恢复（战斗原子化，2026-09-06 拍板修订）**：页面 bootstrap——刷新时 GET `/api/game/state`，已有对局则跳过 setup 直接进游戏屏；**战斗中刷新/读档 = 丢弃进行中战斗，恢复战斗前状态**（不做 CombatState 持久化）；combat 会话丢失时 `/api/combat/round` 返回 409 明确错误，前端退回探索态。

## 7. 测试策略

- §1 契约测试是全体安全网；§2/§3 后必须全绿。
- 新端点（debug/history）各有契约 + 行为测试（stub world/chronicle）。
- F42：测试断言相位回调按序触发（不跑真 WS，测推送队列内容）。
- F40：测试 save→模拟刷新（新会话）→load→state 含 active_combat。
- turn_trace 埋点：stub 场景断言「评估记录 + 失败原因」内容正确。
- 默认收口 `pytest tests/ -q`；涉及 keeper/judge 主路径埋点后跑 `pytest -m real_llm_smoke`。

## 8. 验收标准

1. `pytest tests/ -q` 全绿（含 34 端点契约）。
2. game.html 无内联业务 JS（仅 module 入口）；game.py 拆包后无 >300 行函数。
3. debug panel 四节数据真实可用：新开一局 → 开 debug → 输一个行动 → 面板显示触发流水 + 实体可用性 + LLM 记录。
4. 面板可拖且刷新后尺寸保持；输入栏/开关视觉态明显（手测确认）。
5. F39：刷新页面后历史仍在；F42：回合进行中 step-indicator 逐相位变化；F40：战斗中刷新页面面板恢复。
6. ISSUES §5 收口 F39/F40/F42/B19；MAINTENANCE.md 同步。
