# Frontend Redesign 交叉审计报告

**日期**: 2026-05-25  
**范围**: 设计文档、计划文档 vs 实际后端代码 (`run_game.py` + `src/`)  
**原则**: 不修改 `run_game.py`，仅审计前端代码与后端接口的一致性

---

## 审计概览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 阻断 | 6 | 游戏核心功能无法正常工作 |
| 🟠 高危 | 8 | 功能缺失或数据错误 |
| 🟡 中危 | 12 | 影响用户体验 |
| 🔵 低危 | 6 | 代码质量/规范问题 |

---

## 一、阻断级问题 (Blockers) 🔴

### B1. 武器库/敌人库/注入器未初始化 [game.py / run_game.py]

**位置**: `frontend/routers/game.py:72` (`process_turn`)

`run_game.py` (line 39-45) 正确初始化了三个关键子系统并传递给 `run_turn`:
```python
weapon_lib = WeaponLibrary()
weapon_lib.load_core()
enemy_lib = EnemyLibrary()
enemy_lib.load_core()
injector = ContentInjector(weapon_lib, enemy_lib)
```

但 `frontend/routers/game.py` 调用 `run_turn(game, user_input)` 时**没有传递** `weapon_lib`、`enemy_lib`、`injector` 参数。

**影响**: 战斗系统、敌人生成、武器拾取、内容注入全部失效。`run_turn` 签名: `run_turn(game, user_input, weapon_lib=None, enemy_lib=None, injector=None)`

**修复方向**: 在 `get_game()` 或 `init_game_api()` 中初始化 `WeaponLibrary`, `EnemyLibrary`, `ContentInjector`，并在 `run_turn` 调用时传入。参见 `run_game.py:39-45` 和 `run_game.py:231`。

---

### B2. CLI 命令未适配 Web 前端 [game.py vs run_game.py]

**位置**: `run_game.py:108-167`

`run_game.py` 主循环处理一系列 `/` 命令(`/scene`, `/info`, `/events`, `/flags`, `/char`, `/save`, `/load`, `/help`), 这些在 `game_loop.py` 的 `run_turn()` 内部**不被处理**。`run_turn` 只处理 `/spawn`, `/inject`, `/health` 三类 debug 命令(`game_loop.py:241-244`)。

在 Web 前端，用户输入这些命令会进入 `keeper.process_turn()`，LLM 会尝试将其作为自然语言解析，产生意外结果。`/save` 和 `/load` 完全不可用。

**影响**: 用户无法在 Web 端存/读档、查看角色信息、查看场景详情、查看事件/flag 状态。

**修复方向**: 需要在 `frontend/routers/game.py` 中新增独立的 API 端点来处理这些命令，或创建 wrapper 函数预处理后再调用 `run_turn`。

---

### B3. `/api/game/init` 接收 library 路径但不使用 [game.py]

**位置**: `frontend/routers/game.py:193-202`

`init_game_api` 接收 `weapon_path`, `enemy_path`, `boss_path` 表单参数，但**完全忽略它们**。这些参数被接收后未传递给任何初始化逻辑。

**影响**: UI 上的武器库/敌人库/Boss 库路径选择是假功能，用户自选库文件无效。

---

### B4. 角色导出不包含属性/技能数据 [character.py]

**位置**: `frontend/routers/character.py:135-152`

`export_character` 端点生成的 JSON 仅包含 `meta`, `personal`, `backstory` 三个字段，**缺失**:
- 核心属性 (`STR`, `CON`, `SIZ`, `DEX`, `APP`, `INT`, `POW`, `EDU`, `LUCK`)
- 衍生属性 (`HP`, `SAN`, `MP`, `DB`, `BUILD`, `DODGE`)
- 技能列表及技能值
- 武器列表
- 装备/物品

导出的 JSON 无法被 `investigator/load_investigator()` 或 `Investigator.load()` 正确加载。`src/investigator/serialization.py` 期望完整的 `Stats`, `DerivedStats`, `skills[]` 结构。

**影响**: 角色创建向导产出的 JSON 无法用于游戏，整个 character 创建流程不可用。

---

### B5. 缺少 `/character/skills-list` 端点 [character.py / char-step2.html]

**位置**: `frontend/templates/partials/char-step2.html:7`

模板中 occupation select 触发:
```html
hx-get="/character/skills-list" hx-target="#skills-list" hx-trigger="change"
```

但 `frontend/routers/character.py` 中没有对应的 `/character/skills-list` 路由。用户选择职业后，技能列表区域不会更新。

---

### B6. Tailwind 类名 `text-coc-green` 颜色配置不一致 [base.html / game.html]

**位置**: `frontend/templates/base.html:27`

Tailwind 配置中:
```js
coc: { green: '#3a6b3a' }  // 生成 text-coc-green
```

`frontend/templates/game.html:208` 使用 `text-green-400` (Tailwind 默认绿色), 而 `frontend/routers/game.py:140` 返回的 HTML fragment 使用 `text-coc-green`。两种颜色混用导致 HUD 的 HP 显示颜色不一致（初始值为 `text-green-400`，刷新后变为 `text-coc-green`）。

---

## 二、高危问题 (High) 🟠

### H1. `line-clamp-2` 不是 Tailwind v4 标准类 [game.html]

**位置**: `frontend/templates/game.html:147`

```html
<div class="... line-clamp-2 mb-2">
```

`line-clamp-2` 是 Tailwind v3.3+ 的官方工具类，在 Tailwind CDN v4 配置中**不确定是否可用**。如果不可用，narrative bar 将不会截断到 2 行，导致布局溢出。

---

### H2. Step Indicator 进度推送是假的 [game.py]

**位置**: `frontend/routers/game.py:100-106`

设计文档明确要求 WebSocket 实时推送每步进度，但实现在 `run_turn` 完成后一次性推送所有步骤的 "done" 状态:
```python
_push_progress("parse", "done")
_push_progress("judge", "done")
_push_progress("enrich", "done")
_push_progress("combat_entry", "done")
_push_progress("curate", "done")
_push_progress("narrate", "done")
_push_progress("complete", "")
```

用户看到的进度条会瞬间全部完成，没有实时反馈效果。

---

### H3. `run_turn` 在线程池中执行可能导致线程安全问题 [game.py]

**位置**: `frontend/routers/game.py:91`

```python
turn = await loop.run_in_executor(None, run_turn, game, user_input)
```

`run_turn` 内部大量调用 `call_deepseek()`，这些 LLM 调用可能涉及 asyncio 或全局状态。`run_game.py` 是纯同步 CLI 程序，设计为在单线程下运行。在线程池中执行可能与 LLM 客户端的内部状态冲突。

---

### H4. 角色属性掷骰逻辑重复实现 [character.py vs rules.py]

**位置**: `frontend/routers/character.py:60-114`

`character.py` 中的 `_roll_stat()` 和 `/roll` 端点手动实现了 COC 7th 掷骰逻辑（含 DB/BUILD 查表）。但 `src/investigator/rules.py` 已经提供了正确的:
- `roll_stats()` → 返回 `Stats` 对象
- `calc_derived(stats, age)` → 返回 `DerivedStats` 对象
- `create_skill_list()` → 返回技能列表

前端重复实现可能与后端规则产生偏差，且如果后端规则调整(如 Agent 模型中的特质修正)，前端不会同步更新。

---

### H5. init_game 的 start_node 硬编码问题 [game.py]

**位置**: `frontend/routers/game.py:51`

`get_game()` 硬编码:
```python
start_node="测试房间",
```

而 `init_game_api()` 使用 `_resolve_start_scene()` 正确解析起始场景。如果用户在未调用 `/api/game/init` 的情况下直接在 `/game` 页面发送消息，"测试房间" 可能不在某些模组的场景表中，导致 KeyError。

**额外**: `run_game.py:56` 也硬编码为 `"测试房间"`，但计划文档中提到通过 CLI 启动属于不同路径。

---

### H6. 缺少设计文档中的几个 Game API 端点 [game.py]

设计文档第 6.3 节定义了以下端点，当前 `game.py` 未实现:
- `GET /api/game/state` — 完整游戏状态
- `GET /api/game/npcs` — NPC 列表
- `GET /api/game/current-image` — 当前场景图片
- `POST /api/game/reset` — 重置游戏

**影响**: 前端 UI 无法显示 NPC、无法获取场景图片、无法重置游戏。

---

### H7. Editor 缺少 save/validate 端点 [editor.py]

设计文档第 6.4 节定义了但未实现:
- `POST /api/editor/save` — 保存编辑后的 JSON
- `POST /api/editor/validate` — 校验 JSON

当前 editor 只能查看 JSON 文件，无法编辑或校验。

---

### H8. 设计文档中的图片系统完全不存在 [game.py / 磁盘]

设计文档 §4.3 描述了 "Full-screen atmospheric image" 系统和 `data/images/` 目录。

**实际情况**:
- `data/images/` 目录不存在
- `GET /api/game/current-image` 端点未实现
- `game.html` 中的 background image 只是纯 CSS 渐变: `bg-gradient-to-b from-[#1a1410] via-[#2a1a0a] to-[#1a1410]`

这不是立即阻断，但游戏体验的核心视觉元素缺失。

---

## 三、中危问题 (Medium) 🟡

### M1. 前端 server.py 中 `webbrowser.open(url)` 不匹配设计

**位置**: `frontend/server.py:70`

```python
webbrowser.open(url)  # 打开 localhost:8080
```

设计文档和计划文档中: `webbrowser.open(url + "/launcher")`。当前实现打开根路径 `/`（即 launcher 页），实际上效果相同，但与设计不一致。

---

### M2. `file-browser.html` 是死代码

**位置**: `frontend/templates/partials/file-browser.html`

这个文件包含一个自引用的 Jinja2 模板片段（检查 `listing is defined`），但实际渲染使用的是 `file-listing.html`。`file-browser.html` 从未被任何路由使用，应删除或合并。

---

### M3. WebSocket 重连非指数退避 [game.html]

**位置**: `frontend/templates/game.html:353-357`

```javascript
ws.onclose = function() {
    ws = null;
    if (document.getElementById('game-screen').style.display !== 'none') {
        setTimeout(connectWS, 10000);  // 固定 10s
    }
};
```

设计文档 §11 指定"exponential backoff"，但实现使用固定 10 秒重连。

---

### M4. 设计文档要求 4 种 `reasoning_effort` 选项但实际可能不兼容

**位置**: `frontend/templates/partials/launcher-config.html:35-37`

配置中 reasoning_effort 选项包括 `max`。需要确认当前 `config_llm.py` 的 LLM 客户端是否支持 `max` 值。如果 API 不接受 `max`，会导致 LLM 调用失败。

---

### M5. 角色创建向导步骤间数据不持久 [character.py / char-step*.html]

三个步骤各自独立，使用 HTMX 加载不同 partial，但步骤 1 的姓名/属性/外貌、步骤 2 的技能选择、步骤 3 的武器/背景之间**没有数据传递机制**。用户在步骤 1 掷骰后用 `hx-get` 跳转到步骤 2，步骤 1 输入的数据全部丢失。

需要 session 或隐藏 form 来跨步骤保存数据。

---

### M6. game.html 中 `function openFileBrowser()` 重复定义

**位置**: `frontend/templates/base.html:70-72` 和 `frontend/templates/game.html:187-189`

base.html 定义了 `openFileBrowser()`（含安全检查），game.html 在底部 script 中重新定义了它（无安全检查，但功能相同）。base.html 的版本被覆盖。

---

### M7. `/api/game/scene` 端点返回冗余的全量场景描述 [game.py]

**位置**: `frontend/routers/game.py:146-159`

`scene_info()` 把场景描述 + 出口全部塞入 HUD 的 `#hud-scene` 区域。但设计文档中 HUD 应该只显示简洁的场景名 + HP/SAN。场景描述和出口信息应该在展开面板中显示。当前 HUD 可能信息过量。

---

### M8. `get_game()` 被多次调用时的 game 初始化竞态 [game.py]

**位置**: `frontend/routers/game.py:26-63`

`get_game()` 没有加锁。如果 `/api/game/turn` 和 `/api/game/player-status` 同时第一次调用，可能触发两次 `init_game()` (虽然第二次会因 `_game_instance is not None` 短路，但在 `_game_instance` 赋值前有窗口期)。

---

### M9. `_safe_dir` 路径分隔符问题 [files.py]

**位置**: `frontend/routers/files.py:37-38, 48`

`Path.relative_to().as_posix()` 在 Windows 上返回正斜杠路径（如 `data/modules/常暗之厢`），而 Windows 原生路径使用反斜杠。虽然 as_posix 在 Web 语境下通常是正确的，但在 Windows 系统上与 `os.path` 操作混用时可能出现不一致。

---

### M10. 游戏初始化 loading 时缺少错误边界 [game.py]

`get_game()` 中文件不存在（如 `常暗之厢/l2_test.json` 不存在）时会直接抛出 `FileNotFoundError`。`/api/game/turn` 端点有 try/except 但只捕获 `Exception` 后返回 HTML，不会给用户有意义的错误提示。

---

### M11. game.html form 提交前未做客户端校验

init form 允许所有字段为空。如果用户不填 L2/L1/L3 路径直接点"开始游戏"，会 fallback 到默认模块（常暗之厢），这可能不是用户期望的行为。应该至少对三个模组路径做非空校验。

---

### M12. char-step1.html 中 `/llm` 触发未实现

**位置**: `frontend/templates/partials/char-step1.html:5`

模板提示 `输入 /llm 自动生成`，但 JS 中没有实现检测 `/llm` 后缀并触发 `/character/generate-description` 的逻辑。

---

## 四、低危问题 (Low) 🔵

### L1. 颜色方案不一致

- 设计文档定义 `background: #0d0d0d`，但 `base.html` body 使用 `#111110`
- 设计文档定义 `color: #c8c0b8`，但 `base.html` body 使用 `#c8c4bc`
- `dk` 颜色集（`dk.bg`, `dk.panel` 等）在 base.html 定义但在模板中使用不一致

### L2. `requirements-dev.txt` 未创建

计划文档 Task 1 Step 1 要求创建 `requirements-dev.txt`，但当前目录中未找到此文件。

### L3. `static/fonts/` 目录无字体文件

设计文档 §12 决定捆绑 Noto Serif SC woff2 (~5MB)，但 `static/fonts/` 目录为空。

### L4. design 中的 `line-clamp-3` class

`frontend/routers/game.py:120` 使用了 Tailwind 的 `border-l-3` 类 — 这在 Tailwind 中是非标准值。标准 border 宽度是 `border-l-2`, `border-l-4`。`border-l-3` 不会生效。

### L5. editor.html 的 `loadPath()` 函数没有 HTMX 触发

`frontend/templates/editor.html:26` 使用原生 `fetch()` 而非 HTMX。应该用 `hx-get` 或 `htmx.ajax()` 以保持一致风格。

### L6. `static/tailwind.css` 未构建

计划 Task 10 要求构建独立的 Tailwind CSS 文件用于 PyInstaller 打包，当前不存在。

---

## 五、设计文档与计划文档交叉问题

### D1. 计划文档引用不存在的路径

计划文档中的验证命令使用 `C:/Users/micha/PyCharmMiscProject` 路径，但实际项目路径是 `D:\COC simulator`。

### D2. 计划 Task 9 Step 4/5 引用不存在的旧文件

计划要求删除 `frontend/server.py`, `frontend/game_server.py` 等旧文件。但这些文件可能已经不在计划声明的路径中，且当前 `frontend/` 目录已被新 FastAPI 代码占据。

### D3. 设计文档中 "launcher -> /launcher" 路由不匹配

设计文档 §4.1 说 Launcher 在 `/`，`frontend/server.py` 中 `webbrowser.open(url)`（即 `/` → launcher），但 plan Task 1 Step 3 的代码示例用了 `webbrowser.open(url + "/launcher")`。实际在 server.py 中没有 `/launcher` 路由，`/` 就是 launcher 页。**routers/launcher.py 正确注册了 `@router.get("/")`**。

---

## 六、总结与修复优先级

### 必须修复（游戏无法运行）
1. **B1**: 初始化 WeaponLibrary / EnemyLibrary / ContentInjector
2. **B2**: 实现 CLI 命令的 Web API 对应端点
3. **B4**: 角色导出包含完整数据
4. **B5**: 添加 `/character/skills-list` 端点

### 强烈建议（功能严重受限）
5. **B3**: 使用 library 路径参数
6. **H4**: 使用 rules.py 而非重复逻辑
7. **H5**: 修复 start_node 硬编码
8. **H6**: 实现缺失的 Game API 端点
9. **H7**: 实现 editor save/validate
10. **M5**: 角色创建跨步骤数据持久化

### 改善体验
11. **H1**: 修复 line-clamp 兼容性
12. **H2**: 实现真正的实时进度推送
13. **B6**: 统一颜色类名
14. **M6-M12**: 各种前端小问题

---

## 七、run_game.py 与前端接口对照表

| run_game.py 功能 | 前端实现状态 | 备注 |
|---|---|---|
| 模块加载 (L1/L2/L3) | ✅ `init_game_api` | `get_game()` 硬编码默认值 |
| 角色加载/创建 | ✅ `get_game()` + `init_game_api` | 正确使用 `load_investigator` |
| 武器库初始化 | ❌ 未实现 | B1 |
| 敌人库初始化 | ❌ 未实现 | B1 |
| ContentInjector | ❌ 未实现 | B1 |
| TurnLogger | ✅ 已设置 | |
| Log 目录 | ✅ 自动创建 | |
| `/help` 命令 | ❌ 未适配 | B2 |
| `/scene` 命令 | ⚠️ 部分(有 scene endpoint) | 格式不同 |
| `/info` 命令 | ⚠️ 部分 | 需新 endpoint |
| `/events` 命令 | ❌ 未适配 | B2 |
| `/flags` 命令 | ❌ 未适配 | B2 |
| `/char` 命令 | ⚠️ 部分(player-status) | 信息不同 |
| `/save` 命令 | ❌ 未适配 | B2 |
| `/load` 命令 | ❌ 未适配 | B2 |
| `/trigger` 命令 | ❌ 未适配 | B2 |
| `/spawn` 命令 | ⚠️ run_turn 内部处理 | 但 library 未加载 |
| `/inject` 命令 | ⚠️ run_turn 内部处理 | 但 injector 未初始化 |
| `/health` 命令 | ⚠️ run_turn 内部处理 | 但 sensor 未初始化 |
| 战斗系统 | ❌ 未初始化依赖 | B1 |
| 回合处理 | ✅ `run_turn` in executor | H3 线程安全待验证 |
| 开场叙事 | ❌ 未实现 | run_game.py 有 initial turn |
| 结局处理 | ✅ run_turn 返回 ending | 前端未展示结局弹窗 |
| 技能检定展示 | ⚠️ run_turn 返回 skill_results | 前端未渲染 |
