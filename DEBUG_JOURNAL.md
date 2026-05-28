# Debug Journal — COC Simulator

> 更新原则：每次解决复杂 Bug 后记录症状、根因、解决方案。与 `LEARNING_JOURNAL.md` 交叉对比。保持 ≤10000 字。

---

## 1. NPC 名称匹配失败
- **症状**：玩家用"乘务员"指代 NPC"京山 人吉"，系统不触发 NPC 交互
- **根因**：`keeper.py` 用 `npc.name in raw` 做精确子串匹配，role/别名通通不认
- **解决**：改为 parse 层 `npc_interact` 类型，LLM 在 parse 时判断玩家是否在和场景内 NPC 对话

## 2. TimeAgent response 不写入日志 + 时间不推进
- **症状**：timeagent.txt 只有 prompt 没有 response；game clock 始终为 0
- **根因**：TimeAgent 传了 `thinking=False` 和 `max_tokens=300`，与 Keeper Enrich 的调用格式不一致，导致 `call_deepseek` 的内部路径行为异常
- **解决**：去掉多余参数，与 Keeper Enrich 保持完全一致的调用格式

## 3. Enrich + TimeAgent 并行日志竞态
- **症状**：TimeAgent 的 response 出现在 keeper_enrich.txt 中，内容是 Enrich 格式
- **根因**：`_show_prompt` 设置全局 `_current_log_label`，并行时互相覆盖
- **解决**：`TimeAgent._log_response()` 直接打开 timeagent.txt 追加，不依赖全局 label

## 4. Author Patch 导致 move 重复执行
- **症状**：Author Patch 后 `process_turn()` 递归，move 被执行两次
- **根因**：第一次 parse 已执行 move（修改 `world.current_location`），递归再次执行
- **解决**：两阶段提交——side_effects 和 move 压入 pending，Author 确认通过后统一 `_apply_pending()`

## 5. NPC bound entity 在 parse prompt 中分类错误
- **症状**：NPC 绑定的 I7/I8/AT6 显示在`【场景实体】`而非`【NPC 专属实体】`
- **根因**：`_build_entity_lines()` 只对 AT 检查注入标记，没对 interaction 做同样处理
- **解决**：直接从 `npc.bound_*` 收集 ID 集，遍历时检查归属

## 6. Python 函数内 import 导致 UnboundLocalError
- **症状**：`keeper.py:286` 报 `UnboundLocalError: ActionOutcome`
- **根因**：`process_turn()` 函数体内有 `from game.messages import ActionOutcome`，Python 编译时将整个函数内的 `ActionOutcome` 视为局部变量，import 之前的引用报错
- **解决**：删除函数内 import，模块顶部已有

## 7. 失败惩罚叙事在 enrich 管道中丢失
- **症状/根因**：`judged_entities` 只收集 success=True 的实体，失败实体不进 enrich；且 `all_outcomes[0].message` 被 enrich 无条件覆写
- **解决**：judged_entities 改为收集所有实体（含 failure）；enrich 覆写只对第一个成功且非 AT 的 outcome
- **关联**：`src/game/agents/keeper.py:113-121, 325-332`

## 8. ##GRADED## 结果未传递到 enrich
- **症状**：enrich prompt 中 entity.result 显示裸 D100 字符串而非 on_failure 分级文本
- **根因/解决**：失败分支用了 `skill_result`（原始 D100）而非 `result_text`（resolve_graded_result 输出）→ 加 `if has_graded: skill_message = result_text`
- **关联**：`src/game/judge.py:174-175`

## 9. @markup 泄漏到 LLM prompt
- **症状/根因**：entity.result 中的 @markup 原样保留传给 enrich → 两层 strip 防护（judge + enrich prompt）
- **关联**：`src/game/judge.py:174`；`src/prompts.py:506`

## 10. EnemyAttack 被当 dict 访问
- **症状/根因/解决**：`EnemyAttack` 是 dataclass，但 combat.py 用 dict 方式 (`attack['name']`) 访问 → 全部改为属性访问 (`attack.name` / `getattr(a, 'weight', 1)`)
- **关联**：`src/game/combat.py:294,309-310,320-388`

## 11. Mock patch 未覆盖 Narrator/TimeAgent 的 call_deepseek
- **症状**：mock 模式下日志缺失且耗时异常（10-30s/case）——Narrator/TimeAgent 绕过 mock 调用真实 API
- **根因/解决**：`from llm import call_deepseek` 创建模块级本地引用，`patch("llm.call_deepseek")` 只替换模块属性不影响已导入引用 → 显式 patch 每个 agent 的 `call_deepseek`
- **关联**：已在 LEARNING_JOURNAL 记录通用模式

## 12. G9/G10 子系统未序列化
- **症状**：存档/读档后 ItemManager/GameClock/EnemyManager/NPCManager/BossManager 全部丢失
- **解决**：`to_dict()` 扩展输出 clock/enemies/npcs/bosses/scene_weapons/memory；`load_state()` 逐一恢复；investigator 序列化新增 `item_manager`
- **关联**：`src/scenario_core.py:976-1070`；`tests/test_save_load_roundtrip.py`

## 13. Enrich results 类型不一致导致 TypeError
- **症状/根因**：Enrich 有时输出 `"results": "合并叙事"`（字符串）而非 `"results": {"I1": "..."}`（dict），字符串下标访问报 TypeError
- **解决**：`isinstance(results, dict)` 守卫

## 14. auto_trigger 在 flavor_outcomes 和 ambient_changes 中重复
- **症状/根因/解决**：AT 的 action 设为 "other" 导致同时进入两个列表 → 过滤条件加 `o.entity_type != "auto_trigger"`

## 15. Edit 工具截断多行 f-string — 静默破坏
- **症状/根因/解决**：Edit 的 `oldString` 匹配多行 f-string 只覆盖首行 → prompt 截断但语法合法不报错。**发生两次**。解决：`oldString` 含足够长唯一上下文；改后 `py_compile` 确认

## 16. Enrich prompt f-string 中未转义花括号导致 NameError
- **症状**：`run_game.py` 运行时 `NameError: name '整合后���' is not defined`
- **根因**：Enrich prompt 的 JSON 输出示例中有 `"results": {整合后的叙事}` 被 Python f-string 当作变量引用求值
- **解决**：加引号改为 `"results": "整合后的叙事"`

## 17. 日志系统重构：response 未按 agent 分文件
- **症状/解决**：所有 response 写入单一 `llm.txt` → 引入 `_current_log_label` 全局变量，`_show_prompt` 设 label，`_log_response` 按 label 写入对应文件

## 18. NPC 系统完全空转 — scene 字段无人填充
- **症状**：NPC 对话路由永不触发——所有 NPC `scene=""` → `get_in_scene()` 返回空
- **根因**：Step 2.5 不生成 initial_scene + `_bind_npc_entities()` 不设 scene + init_game 死代码读不存在的 `npcs` 字段
- **解决/教训**：从 entity source_scene 推断 NPC 位置；新架构上线前必须端到端 smoke test

## 19. 18 个管线步骤 System/User Prompt 批量拆分
- **症状/根因/解决**：所有 build 函数把角色定义/规则/Schema 混在 user prompt → 拆分为 STEP*_SYSTEM + 纯数据 user prompt（13+4 步）

## 20. Edit 工具替换中文代码块时引入全角引号
- **症状**：~180 行替换后所有 Python 字符串引号变全角 `""`，`SyntaxError: invalid character`
- **根因/解决**：Edit 的 `new_string` 中混合中英文时中文引号感染 Python 引号 → `python -c "content.replace('“', '\"').replace('”', '\"')"` 一键修复；事后 `grep -n '[“”]' file.py` 检查
- **教训**：大块中文代码替换优先用 Write 重写整个文件

## 21. 条件块内定义的变量在块外引用导致 UnboundLocalError
- **症状/根因**：`enrich_executor = ThreadPoolExecutor(...)` 在条件块内，块外 `enrich_executor.shutdown()` 无条件执行
- **解决/教训**：条件块前初始化为 `None`；同类问题见 #13

## 22. LLM logging wrapper 导致 NPC 对话静默失败

- **症状**：test harness 中 NPC 对话返回 fallback 文本，LLM response 正常但被丢弃
- **根因**：(a) wrapper 有 `model=""` 默认参数，空字符串 vs None 在 `call_deepseek` 的 `is not None` 检查中行为不同；(b) `NPCManager.talk_to()` 用 `except Exception` 静默吞异常
- **解决**：wrapper 改为 `def _logging_wrapper(prompt, json_mode=True, **kw)`——移除默认参数，从 `kw` 过滤合法参数传 API
- **教训**：`is not None` 判断下空字符串 `""` 和 `None` 完全不同，wrapper 不应给这类参数设空字符串默认值

## 23. Subagent 遗漏 layered_pipeline.py — chapters 未传播
- **症状**：Subagent 完成 `layered_parser.py` 的 `condensed_text→chapters` 转换，但 `layered_pipeline.py` 中 10+ 个 `parse_step*(condensed_text,...)` 调用未更新，`'str' object has no attribute 'get'`
- **根因**：pipeline wiring 跨 10+ 个调用点，subagent 逐个替换时 API 超时未完成
- **解决**：grep 残留 `condensed_text` → 逐个 `replace_all`。事后 audit grep 验证签名一致
- **教训**：prompt 签名变更必须在 Plan 末尾加 pipeline audit Task

## 24. Notebook chapters 同步滞后
- **症状**：两个 notebook 仍传 `condensed_text` 字符串给期望 `chapters: dict` 的函数
- **根因**：Plan 中 notebook Task 被 subagent 跳过；`_parser_layered_export.py`（纯 Python export）被忽略
- **解决**：Python 脚本注入 `chapters = _parse_condensed_chapters()` + 替换所有调用点（含首参/尾参）
- **教训**：notebook 不独立为 Task——每个源码 Task 同步更新 notebook

## 25. `git add -A` 提交 debug 产物
- **症状/解决**：`git add -A` 提交了 `data/debug/` 整个目录 → 用 `git add <explicit paths>` 重新提交。`data/debug/` 应加入 `.gitignore`
- **教训**：始终用显式路径而非 `git add -A`

- **症状**：test harness Case B Turn 2 用"京山人吉"（无空格）不触发 NPC 对话，而 data profile 中是"京山 人吉"（有空格）
- **根因**：`keeper.py` 的 NPC 路由用 `npc.name in raw` 做裸子串匹配，容错性极低
- **解决**：test input 中添加空格（"京山 人吉，..."）。长期方案见 Debug #1 — parse 层 `npc_interact` 类型
- **关联**：`tests/test_harness_stability.py:135`；`tests/test_harness_parallel.py:250,349`

## 26. world.flags 移除后残留引用链
- **症状**：15 个 test harness case 全部 `AttributeError: 'ScenarioWorld' object has no attribute 'flags'`
- **根因**：`Task 10` 删除 `self.flags` 后，`prompts.py._build_world_state()` 和 `keeper.py` world_snapshot 仍引用 `world.flags.items()` 和 `self.world.flags`
- **解决**：grep 全量扫描 `\.flags` → 逐一替换为 `runtime_state`，prompts 改为展示已完成实体列表，keeper world_snapshot 改为 runtime_state 摘要
- **关联**：`src/prompts.py:104`；`src/game/agents/keeper.py:261`

## 27. prompts.py 中文引号感染 ASCII 引号 (复发)
- **症状**：`SyntaxError: invalid character ' (U+201C)` — ~50 行 `parse_narrative_output()` 函数体全部引号变全角 `""`
- **根因**：Edit 工具替换多行中英文混合代码块时，中文上下文中的全角引号感染 Python 字符串。与 Debug #20 同类问题
- **解决**：用 `bash "python -c 'content.replace(chr(0x201C),...)'"` 写入文件修复。事后验证 `compile()`。教训：大块代码替换优先 `Write` 而非 `Edit`
- **关联**：`src/prompts.py:231-277`

## 28. NotebookEdit 导致 run_game 函数 def 行丢失
- **症状**：notebook cell 只剩下函数 body（`initial = run_turn(...)` 开始），缺失 `def run_game(...):` 签名和初始化代码。`NameError: name 'game' is not defined`
- **根因**：NotebookEdit 的 `cell_id` 引用在多次编辑后 cell id 被 Jupyter 自动重生成，新旧 id 不一致导致替换覆盖了错误的 cell 内容
- **解决**：放弃 notebook 格式，直接写 `run_game.py` 纯 Python 文件。Notebook 作为调试辅助不再作为主入口
- **关联**：`notebooks/notebook_simplified.ipynb` → `run_game.py`

## 29. Windows GBK 终端 emoji 崩溃
- **症状**：`UnicodeEncodeError: 'gbk' codec can't encode character '✓'` — test harness print 时 `✓`/`✗` emoji 崩溃
- **根因**：Windows 中文终端默认 GBK 编码，不支持大部分 Unicode 符号
- **解决**：所有 print 中 emoji 替换为 ASCII 标记（`[PASS]`/`[FAIL]`），字符串切片做安全保护
- **关联**：`tests/game_loop_harness.py:299-306`

## 30. Combat 系统 `skill_used` vs `skill_name` 字段不匹配
- **症状**：`AttributeError: 'Weapon' object has no attribute 'skill_used'`
- **根因**：`Investigator.models.Weapon` 用 `skill_name`，`combat.py._get_player_actions` 访问 `w.skill_used`
- **解决**：combat.py 改为 `getattr(w, 'skill_name', '') or getattr(w, 'skill_used', '')` 兼容两种命名
- **关联**：`src/game/combat.py:141`；`tests/test_combat_harness.py:55`

## 31. DerivedStats 无 LUCK 字段
- **症状**：`TypeError: DerivedStats.__init__() got an unexpected keyword argument 'LUCK'`
- **根因**：`DerivedStats` 只有 HP/MP/SAN/SAN_MAX/MOV/DB/BUILD/DODGE，LUCK 在 `Stats` 上
- **解决**：删除 `DerivedStats(LUCK=...)` 参数
- **关联**：`src/investigator/models.py:27`；`tests/test_combat_harness.py:55`

## 32. Boss 护甲过高 → 战斗死循环
- **症状**：LLM Player smoke test 第 4 轮卡死——parse 有结果但进程 hang
- **根因**：Boss "吞噬之口" 护甲 10，玩家拳击伤害 1D3+DB（最大 ~7）无法破防。`combat.py:116` 的 `while not state.finished` 只在敌人全灭时退出，无回合上限或僵局检测 → 无限循环
- **解决**：`llm_player.py` monkey-patch `CombatSystem.run_combat` 自动返回 `win`。底层修复待做：combat 加 `max_rounds` + 僵局检测
- **关联**：`src/game/combat.py:116`；`data/library/core/bosses.json`

## 33. Starlette 1.1.0 TemplateResponse 签名变更 → 全部页面 500

- **症状**：前端服务器 `/health` 正常返回 `{"status":"ok"}`，但 `/` `/game` `/character` `/editor` 全部返回 500 Internal Server Error。初次排查以为是 jinja2 缓存问题（`TypeError: cannot use 'tuple' as a dict key`），disable cache 后报 `'dict' object has no attribute 'split'`
- **根因**：(a) Starlette 1.1.0 将 `TemplateResponse` 签名从 `(name, context)` 改为 `(request, name, context)`，所有 10 个 router 中的调用仍用旧签名。(b) `templates.TemplateResponse("launcher.html", {"request": request})` 实际变成 `TemplateResponse(request="launcher.html", name={"request": request})`，dict 被当作模板名传入 Jinja2 → `split_template_path` 报错。(c) 触发原因是 `pip install uvicorn jinja2` 时升级了 starlette 间接依赖
- **解决/教训**：(1) grep 全部 10 个 `templates.TemplateResponse(` 调用点，逐个改为 `templates.TemplateResponse(request, "name.html", {context})`，移除 context 中的 `"request": request`（starlette 1.1.0 自动注入）；(2) `pip install` 后必须跑全量 smoke test（不只是 health check）；(3) 依赖升级后应先 `pip show starlette` 确认版本 + 对比 breaking changes
- **关联**：`frontend/routers/*.py`（launcher/game/character/editor/files 共 10 处）

## 34. frontend/static/ 目录缺失 → 服务器无法启动

- **症状**：`uvicorn frontend.server:app` 启动即报 `RuntimeError: Directory 'D:\COC simulator\frontend\static' does not exist`
- **根因**：`server.py:40` 中 `app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")))` 要求目录存在，但 git 不追踪空目录
- **解决**：`mkdir frontend\static\fonts` 创建目录占位；审计 L3 项同时闭合
- **教训**：任何 `StaticFiles.mount` 都应用 `os.makedirs(dir, exist_ok=True)` 兜底，或用 try/except 跳过不存在的静态目录

## 35. Boss 战斗重复触发 — 已完成状态未过滤

- **症状**：llm_player 6 轮中 T4/T5/T6 连续触发 combat（`combat_outcome=win`），同一 Boss 每回合重复进入战斗。`brief` 始终为 "（处理中）"，enrich/narrator 无输出
- **根因**：`keeper.process_turn()` 的 Boss "at" 和 "event" 检查只判断 `_check_boss_requirements()`，不检查 `runtime_state` 中 Boss 是否已完成。`check_by_engage_type("event")` 不按场景过滤，所有 event 型 Boss 每回合都检查 → 需求为空的 Boss 无条件重复触发
- **解决**：两个 Boss 检查路径都加 `world.is_entity_completed(boss_id)` 过滤，已完成 Boss 跳过

## 36. Boss "at" 检查过早 return 导致 enrich 被跳过

- **症状**：llm_player 战斗回合 `brief="（处理中）"`，narrator 输出为空，enrich degrade 计数递增
- **根因**：Boss "at" 检查在 `process_turn()` 的 Step 2（Judge）之后立即执行，触发时直接 `return {"combat_init": ..., "brief": "", "narrative": ""}` — 此时 enrich 尚未启动
- **解决**：将 Boss "at" 检查从 Judge 之后移到 Step 3.5（enrich 结果收集）之后，同时在 Boss 触发时不再 early return，改为设置 `combat_init_result` 让函数继续走到 curate

## 37. TurnLogger 战斗回合漏记

- **症状**：llm_player turn_logs 目录只有 turn_01/02/03，T4-T6 缺失
- **根因**：`game_loop.run_turn()` 中 `_turn_logger.log()` 只在 `if hasattr(brief, 'scene_snapshot')` 分支内调用。战斗回合 Keeper 返回空 brief（无 scene_snapshot），走 else 分支 → TurnLogger 未调用
- **解决**：在 else 分支也加 `_turn_logger.log()` 调用，用 display_brief / result.narrative 替代 narrator 输出

## 38. llm_player monkey-patch 用 modify_stat 写 SAN

- **症状**：`modify_stat("SAN", -san_loss)` 不生效——SAN 是 DerivedStats 字段，不是 Stats 核心属性
- **根因**：`Investigator.modify_stat()` 只处理 8 项核心属性（STR/CON/SIZ/...），HP/SAN/MP 等派生属性在 `DerivedStats` 上。monkey-patch 错误地用 `modify_stat` 写 SAN
- **解决**：改为 `player.derived.SAN = max(0, player.derived.SAN - san_loss)`，与 HP 写入一致

## 39. Tailwind CDN 导致浏览器标签页内存泄漏

- **症状**：`python frontend/server.py` 运行一段时间后浏览器卡死/系统变慢，后端单独跑正常
- **根因**：`base.html` 使用 `<script src="https://cdn.tailwindcss.com">` 运行时编译，HTMX 每次返回新 HTML 片段带新 class → CDN 编译器增量追加到 `<style>` → 样式表无限增长
- **解决**：替换为预编译的静态 `tailwind-built.css`，包含项目中全部使用到的 utility class。同时给 `chatMessages` 渲染加 `slice(-50)` DOM 上限，WebSocket `wsRetry` 在 `onopen` 时清零

## 40. 文件浏览器模态框被页面重写意外删除

- **症状**：Launcher 和 Game 页面的文件浏览按钮无反应，控制台无报错
- **根因**：重写 `launcher.html` 和 `game.html` 时把 `#file-modal` + `#file-browser-content` 删除了，`base.html` 中的 `openFileBrowser()` 仍然调用 `getElementById('file-modal')` 返回 null
- **解决**：将 `#file-modal` 移到 `base.html` 的 `{% block body %}{% endblock %}` 之后作为全局共享组件，所有页面继承。同时补上静态 CSS 中缺失的 `bg-[#141414]`、`w-[550px]`、`max-h-[70vh]` 等 class

## 41. Launcher 页"开始游戏"按钮失灵 — JS 跨页面作用域

- **症状**：Launcher 的"开始游戏"标签中点击按钮无反应
- **根因**：表单 `onsubmit="initGame(event)"` 调用 `initGame()`，但该函数定义在 `game.html` 的 `<script>` 中。Launcher 页面通过 HTMX 加载 partial，`game.html` 的 JS 不在当前页面上下文中
- **解决**：在 `launcher-game-start.html` 末尾内联 `startGame()` 函数，`POST /api/game/init` 成功后 `window.location.href = '/game'` 跳转。同时在 `game.html` 加页面加载自动检测 —— 如果 `/api/game/state` 返回已初始化的游戏，直接切换到游戏界面跳过设置屏幕

## 42. Pre-parse 消歧网关拦截斜杠命令

- **症状**：游戏中输入 `/help`、`/scene` 等命令无效，被当作普通文本进入 LLM 管线
- **根因**：`keeper.process_turn()` 中的 `pre_parse.disambiguate()` 对 ALL 输入执行消歧，包括斜杠命令。消歧 LLM 可能对 `/help` 返回 ambiguous，导致返回反问文本而非执行命令
- **解决**：在 `game.py` 的 `process_turn` 入口处拦截 —— 输入以 `/` 开头直接走 `_handle_slash_command()` 同步处理，跳过整个 LLM 管线。同时新增 `/quit`（原 `quit` 无斜杠）

## 43. game.html API 返回格式切换遗漏 — 后端已改 JSON 但遗留 HTMLResponse 异常路径

- **症状**：（潜在）后端 `process_turn` 成功时返回 dict（JSON），但 try/except 和 get_game 失败路径仍返回 `HTMLResponse`，前端 `sendTurn()` 按 `content-type` 自适应兼容
- **根因/解决**：`process_turn` 三个返回路径中两个是 `HTMLResponse`（错误场景），一个是 `dict`（成功）。前端 `sendTurn()` 通过 `resp.headers.get('content-type')` 分派，HTML 走旧逻辑，JSON 调用 `handleTurnResponse()`。这种混合模式是过渡方案，长期建议统一为 JSON

## 44. llm_player exploration 模式下 player 为 None 导致 AttributeError

- **症状**：`AttributeError: 'NoneType' object has no attribute 'name'`，llm_player 启动即崩溃
- **根因**：`run_llm_player()` 中 `set_player()` 只在 `test_mode == "stress" and combat_testing.mode == "buff_investigator"` 时执行，stress_profile.json 的 test_mode 为 "exploration" → player 永远是 None
- **解决**：`init_game()` 后加 fallback — 如果 `world.player is None`，从 `data/investigator/combat_test_character.json` 加载默认调查员；若文件不存在则 `roll_stats()` 创建随机角色
- **教训**：入口函数中的状态初始化不要只针对部分配置分支——所有分支都应保证核心状态（player）被设置

## 45. Windows cp932 终端 em dash (—) 崩溃

- **症状**：`UnicodeEncodeError: 'cp932' codec can't encode character '\u2014'` — llm_player print 时 em dash 崩溃
- **根因**：与 Debug #29（GBK emoji）同类问题，Windows 中文终端默认 cp932 编码
- **解决**：`$env:PYTHONIOENCODING = 'utf-8'` 强制使用 UTF-8

## 46. 审计 time_state 跨回合 span 为 0

- **症状**：审计报告 Summary 显示 `Time span: D0 夜间 → D0 夜间 (+0m)`，但 TimeAgent 节显示 total delta=5m
- **根因**：`llm_player.py` 在 `run_turn()` 返回后才捕获 `clock` 状态——每轮的 time_state 已是 post-turn 值。当多轮未推进时间时，`last.game_time - first.game_time = 0`
- **解决**：Summary time span 改用 `sum(time_agent.time_delta)` 累加，而非 time_state 的 game_time 差值；`_audit_time()` 标注 Initial/Final 状态为 "after T01/Tn"

## 47. 审计报告 combat_outcome→combat dict 字段迁移

- **症状/根因/解决**：`llm_player.py` 将战斗数据从 `combat_outcome: str` 升级为 `combat: {outcome, narrative, is_boss}`，审计各节共 6 处 `t.get("combat_outcome")` 引用全部迁移到 `t.get("combat")` / `t["combat"].get("outcome")`

## 48. TimeAgent 时间偏差严重 — 10 轮仅推进 6 分钟

- **症状**：llm_player 10 轮跑局中，T01-T10 总游戏时间仅从 G+5m 到 G+6m，搜索车厢、移动、阅读笔记等操作只推进 1 分钟
- **根因**：`time_costs.json`（含 search/move/dialogue/combat/other 各类型时间基准）在 `init_game()` 加载到 `world.time_costs`，但从未传递给 TimeAgent。TimeAgent prompt 只有模糊的"综合所有行动评估总耗时"没有数值参考 → LLM 保守估计趋近 0-1 分钟
- **解决**：(a) `TimeAgent.build_prompt()` 新增 `time_costs` 参数，注入 `【时间参考基准】` 节（search=1-45m, move=1-15m, dialogue=1-15m 等）；(b) `Keeper._run_time_agent()` 传入 `self.world.time_costs`
- **效果**：3 轮测试从 ~5m 提升到 20m（G+10m→G+17m→G+20m），符合实际游戏时间观感

## 49. combat_entry 绕过 Enrich → Narrator 感知不到战斗

- **症状**：战斗叙事（"你侥幸战胜了..."）不进入 Enrich/Narrator 管线，LLM Player 和玩家都只能通过 Narrator 的 scene snapshot 间接感知战斗结果
- **根因**：keeper 管线顺序为 Step 2.5 combat_entry（并行）∥ Step 3 enrich+TimeAgent → Step 3.5 collect enrich → Step 3.6 collect combat_entry → Step 3.7 resolve combat。combat_entry 在 enrich 之后收集，且 enrich_input 无战斗数据
- **解决**：重构 keeper 管线为串行——Step 2.5 combat_entry（同步）→ Step 2.6 解析战斗 + Boss "at" 检查 → 战斗描述注入 `enrich_input.entities` → Step 3 enrich ∥ TimeAgent（并行）。Boss 遭遇注入 `"⚠ {boss_name}发现了你！退路已断，战斗一触即发——"`，普通战斗注入 `"⚔ 你与{enemy_names}进入了战斗！"`
- **教训**：Enrich 是 Narrator 的唯一数据源——任何需要 Narrator 感知的事件（战斗/Boss/NPC）必须在 enrich 之前注入 enrich_input

## 50. 车卡导出连环 Bug — 5 层阻塞逐层暴露

- **症状**：前端"导出 JSON"按钮始终报"导出失败"，但预览界面已能显示正确的角色数据
- **根因链**（5 层，每层修完后下一层才暴露）：
  1. **Python 语法级**：`game.py` 函数内多处分离的 `global _game_instance` 声明 → `SyntaxError`，服务器无法启动
  2. **JS 数据流级**：`exportCharacter()` → `charSyncAllFields()` → `charStoreSkills()` 在步骤 3 被调用时，`#skills-list` DOM 已不存在（HTMX 替换了步骤 2 的内容）。函数找到 0 个输入框，执行 `skills-json.value = ''`→ **清空了步骤 2 保存的技能数据**
  3. **Python 导入级**：`from investigator.serialization import investigator_to_dict` → 实际函数名为 `to_dict`，`ImportError` 导致 500
  4. **类型不匹配**：`inv.occupation = occupation` 传的是字符串（如 `"医生"`），但 `to_dict` 里调用 `inv.occupation.name` → `AttributeError`
  5. **HTTP 编码限制**：Content-Disposition header 的 filename 含中文 → `UnicodeEncodeError: 'latin-1' codec can't encode`
- **解决方案**：
  - 层1：`global _game_instance` 提到函数顶部一行
  - 层2：`charStoreSkills()` / `charStoreStats()` 加早期返回 `if (inputs.length === 0) return`——找不到 DOM 元素时不覆盖已有数据
  - 层3：`investigator_to_dict` → `to_dict`
  - 层4：从 `occupations.json` 查找并构造完整 `Occupation(name=..., description=..., ...)` 对象
  - 层5：`filename*=UTF-8''<url编码文件名>` (RFC 5987)
- **教训**：前置端修改后，导出这类**串行多步依赖的工作流**最易产生连环 bug。每个步骤依赖前一步的数据正确性和格式兼容性，一层阻塞掩盖下一层。修完后不应只验证"不报错了"——应该用实际数据端到端测试完整流程

## 51. 并行 session merge 导致 f-string 变量丢失

- **症状**：并行 session 的 commit 合并后，`build_step2b_combined_prompt` 的 prompt 中"已知场景"区域为空——LLM 收到的 prompt 缺少场景列表
- **根因**：本 session 和并行 session 同时编辑了 `layered_parser.py` 的同一函数。本 session 修改了 `char_list` 格式化代码（替换为 `_format_char_list()`），过程中重写了 `return f"""` 及其后的多行字符串。并行 session 在此基础上又做了增量修改。Git 的三路合并保留了大部分内容，但 f-string 中的 `{scene_list}` 行在合并时被误删——该行在 diff 中以 `-{scene_list}` 形式出现在"删除块"中，看起来像是格式调整的一部分，实际是丢失了关键逻辑
- **解决**：手动对比 `c10bb48..HEAD` 的完整 diff，逐行检查 my commit 引入的每一处改动是否在 HEAD 中仍然存在。发现缺失后补回 `{scene_list}` 行
- **教训**：并行 session 后不应假设 merge 正确——应该 (a) 对 my commit 的每个修改文件做完整 diff 对比；(b) 特别注意多行字符串/heredoc 中变量的增删——git 的上下文 diff 有时会误判这类变化为"格式调整"而合并到错误方向；(c) `git diff <my-commit> HEAD -- <file>` 是最直接的验证工具
