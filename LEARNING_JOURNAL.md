# Learning Journal — COC Simulator

> 更新原则：每次完成非平凡重构或解决复杂问题后，反思是否有可迁移的工程习惯/方法论。保持 ≤5000 字。
> **写入前**：与已有内容交叉对比——新条目可能与已有条目重叠或互补，优先合并而非新增。
> **写入时**：与 `~/.config/opencode/LEARNING_JOURNAL.md` 对比，将可迁移的技巧同步到全局。

---

## 重构前审计完整数据流
- 修改跨多个文件的共享状态前，先 grep 所有引用（`self.boss_manager`/`self.npc_manager`/`game["boss_manager"]`），确认调用方、消费者、序列化路径
- 本 session 的 Keeper 去重（Phase 1）是典型案例：移除 6 个 Keeper 属性前先用 grep 扫描了 `keeper.py`、`game_loop.py`、`scenario_core.py` 的全部引用，发现 `dependency_graph` 和 `npc_profiles` 已是死代码，`boss_manager` 被 `run_turn` 独立引用
- 与"修改后追溯上下游"互补——前者是改后检查，这个是改前摸底

## 统一数据源替代碎片化构建
- 7 个 `_build_*` 函数各自从 World 组装部分状态，字段名不一致、覆盖不完整 → 替换为单一 `world.build_snapshot()`，每个 prompt builder 按需取切片
- 收益：(a) 新增字段（HP/SAN/武器/敌人/NPC/时间）对所有 prompt 自动生效；(b) 字段名统一，消除"这个 prompt 的 NPC 字段叫 npc_states 还是 npcs_in_scene"问题
- 代价：snapshot 方法必须保持纯数据组装，不引入任何 LLM 或格式化逻辑

## 集中式时间管理替代分散式判定
- `_resolve_time_delta` 散落在 entity/move/search/other 四个分支中，各走不同的规则 → 收集所有 action 摘要，单次 TimeAgent 调用统一评估
- 额外收益：TA 可以与 enrich 并行（两者都不依赖对方的结果），不增加每轮延迟
- 适用场景：当一种判定（时间/难度/奖励）需要在多个不同上下文中执行，且 LLM 评估质量优于硬编码规则时

## README 作为活文档
- 已完成项目不应留在"待实现"列表里——要么删除，要么移入架构文档
- 清理后"已知缺口"只留 G9/G10，"待优化"只留 O4-O7，并标注优先级

## God Object 拆分的执行模式
- 设计→Plan→Subagent-Driven Development 三步。关键教训：Plan 必须包含 notebook 和 pipeline wiring 的同步 Task——subagent 天然聚焦源文件，跨文件调用链（如 10+ 个 `parse_step*` 的 pipeline wiring）最容易遗漏

## 字段合并的渐进收敛模式
- 识别语义重叠 → 合并到信息更丰富的字段 → 更新全部 prompt/consumer → 删除空字段。本 session 合并了 5 个字段（clue/effect_type/irreversible_impact/reveal_narrative/enemy_ref→result/side_effects），数据模型从 13→11 字段
- 适用于 LLM 生成层中多字段承载重叠信息且消费者无需区分来源的场景

## 特殊字符标记作为 LLM 跨步骤通信协议
- `##GRADED##`/`##END_名称:简述##` 嵌入 entity.result——Step 2 写入→Step 3a 验证→game_loop 解析。无需新增 schema 字段即可传递可选元数据
- 代价：下游需正则扫描；标记格式变更需同步所有 producer/consumer

## LLM Mock/Patch Wrapper 的 `**kw` 陷阱
- 为日志拦截而写的 `call_deepseek` wrapper 如果有显式默认参数（如 `model=""`），会把空字符串传给真实 API——而 `model=""` 和 `model=None` 语义不同（后者在 `call_deepseek` 内回退到默认模型）
- 正确做法：`def wrapper(prompt, json_mode=True, **kw)`，从 `kw` 中过滤已知合法参数，用 `filtered["json_mode"] = json_mode` 覆盖，其余按原名传递
- 同样影响 mock wrapper——所有替换 `call_deepseek` 的 wrapper 都应遵循此模式

## 测试 Harness 并行隔离模式
- 每个 case 通过 `_init_game_instance()` 创建独立 World/Keeper/Narrator/Author 全套实例，不共用任何可变状态
- `ThreadPoolExecutor` 在 worker 线程内调用 `init_game()`（创建在 worker 而非主线程），避免跨线程共享
- Mock 模式用 `--mock` flag 切换：原 LLM path 保留，mock path 注入 `patch()` 替换所有 `call_deepseek` 调用点
- 必须在 patches 列表中显式覆盖所有 agent 的 `call_deepseek`（keeper/intent_detector/author/narrator/time_agent），因为各 agent 用 `from llm import call_deepseek` 持有模块级引用，`patch("llm.call_deepseek")` 只影响 llm 模块属性，不影响已导入的本地引用

## 两层状态模型（静态骨架 + 动态叠加层）
- 将实体状态追踪拆为两层：`dependency_graph`（L2 定义的只读骨架，nodes + edges）和 `runtime_state`（运行时填充的动态叠加层，key = entity_id, value = {completed, result_tier, retries}）
- 依赖解析走 graph edges（AND 语义），运行状态写 runtime_state（常规操作轻量），Author 介入改 graph（稀有操作重量）。graph 始终保持 L2 纯净性
- 适用场景：任何需要"预定义结构 + 运行时动态状态"的场景——静态结构不随运行改变，动态状态频繁读写但不改变结构
- 本 session 将旧 world.flags 字典（任意 key-value）全部迁移到此模式

## NotImplementedError 作为可插拔系统接口
- 预留函数直接抛 `NotImplementedError` 而非空函数——调用方明确知道"此处有接口但未实现"，避免静默跳过
- 接口设计：先定 Input/Output 消息类型（dataclass），实现方消费标准输入返回标准输出，不感知上游来源
- 战斗系统用了此模式：`CombatSystem.run_combat(CombatInit) → CombatResult`——上游主循环只传 CombatInit，不关心战斗内部回合逻辑

## 子系统的并行合约
- 多进程协作时，先定 data class 作为合约（CombatInit/CombatResult/EnemyInstance），各自独立实现，接口对齐即可合流
- 战斗进入判定进程定义 CombatInit 输出，战斗机制进程定义 CombatInit 消费——两方只依赖消息类型，不直接引用对方的模块
- 与"单一数据源"互补：合约是跨进程的共享数据格式，单一数据源是进程内的共享状态

## NotebookEdit 脆弱性 — 优先 .py
- NotebookEdit 在多次编辑后 cell id 会被 Jupyter 自动重生成，导致新内容覆盖错误 cell
- 多次编辑的 notebook 应转为 .py 文件作为主入口，notebook 退化为调试辅助
- 跨项目适用：任何 notebook 经 3+ 次编辑后应迁移到 .py
- 本 session 将 parser_test.ipynb 的管线编排逻辑完整迁移到 run_pipeline.py（CLI 入口），notebook 退化为调试辅助

## 布尔表达式作为 LLM 产出格式约束
- 将 requirement 字段的硬性条件从自然语言（"I3 已完成, I1 已完成"）改为 `entity_id + AND/OR/()` 表达式（如 `I1 AND I2`、`(I1 OR I2) AND I3`）
- 收益：(a) LLM 产出格式统一，解析端只需处理 entity ID + 逻辑运算符；(b) 裸 entity ID 语义固定（= 成功完成），不需 "已完成/已触发/已成功" 等变体；(c) 特殊条件（失败/未触发）放 `||` 后的软性条件，自然语言交给 LLM 运行时评估
- 代价：所有涉及 requirement 的提示词（Step 2a/2b/3.5 × 7 处）需同步更新；依赖图提取逻辑（Step 3.5）需适配新格式
- 适用场景：任何需要 LLM 在受限文本字段中表达复合逻辑的场景 — 定义清晰的原子 token（entity ID）和逻辑运算符，让 LLM 像写布尔表达式一样组合

## LLM Pipeline 步骤的确定性替代判定框架
- 不是所有 LLM 调用都能换成确定性逻辑。判定标准：**输入是否以自然语言为主要信息载体**。
- **可确定性化**（正则/查表/fuzzy match）：
  - 引用校验：L1 linked_interaction 是否指向 L2 中存在的名称 → 集合查找
  - 覆盖检查：所有场景是否都有 L3 scene_intents → key diff
  - 名称一致性：L1/L2/L3 场景名/角色名统一 → 字符串匹配
  - 输出格式固定、输入高度结构化的场景
- **不可确定性化**（必须 LLM）：
  - 依赖图（Step 3.5）：requirement/trigger 中文文本中 30-40% 的依赖信息藏在自然语言里（软条件、反向依赖、跨文本引用），正则只能覆盖 60%
  - @markup 标准化（Phase 2）：同一语义在中文中有 10+ 种表达（"搜查/观察/翻找"→"侦查"、"一阵眩晕"→SAN-1），规则覆盖常见模式（~60%），边缘 case 需语义理解
- Step 3b 是混合案例：7 个检查中 6 个可确定性，仅 linked_interaction 补全需 LLM → 拆分后 prompt 从 40K token 降到 ~2K
- 与"统一数据源"互补：确定性逻辑依赖结构化数据质量；LLM 负责将非结构化输入转为结构化输出

## 压力测试中子系统短路策略
- 自动化测试非目标系统时，短路阻塞子系统而非修它——`llm_player.py` 用 monkey-patch 让 CombatSystem 自动胜利，避免了 Boss 护甲 10 导致的死循环。战斗系统独立测试即可
- 关键：短路要保留接口——返回合法的 `CombatResult`，下游 EnemyManager/BossManager 仍能正常处理
- 适用场景：任何多子系统集成测试中，个别系统未就绪或会阻塞全局时

## LLM API 超时是生产必备
- `OpenAI()` 客户端默认超时 600s，API 挂住会卡死整个进程。`call_deepseek` 加 `timeout` 参数（重任务 180s，flash 60s）后所有调用点统一受控
- `str.format()` 中中文花括号 `{关键行动}` 被误解析为 format key → 全部转义为 `{{关键行动}}`
- 适用场景：任何调用外部 API 的生产代码——超时不是优化，是必须

## 审计的 overfetch-and-filter 数据增强模式
- 增强审计覆盖不需要改核心逻辑——`run_turn()` 已经返回了 `time_agent`/`npcs_visible`/`combat` 等字段，只需在日志收集端（`llm_player.py` 的 `summary_log`）多捕获几个已有返回值，审计端（`audit_player_log.py`）按需读取
- 关键教训：time_state 是 post-turn 快照，跨回合 span 不能用 `last - first`，应改用 `sum(time_agent.time_delta)` 累加真实推进量
- 与"统一数据源"互补——后者是减少碎片化构建，这个是利用已存在但未收集的数据

## LLM 判定 prompt 中计算链路的显式化
- 技能检定的 trait enhancement prompt 原写法"思考骰子调整量→映射到等级"过于跳跃，LLM 容易跳过数值步骤直接选等级
- 改进为显式三步：**确定虚拟骰子 = 原始 ± 调整量 → 代入 COC 公式映射 → 得出等级**，配合带具体数字的计算示例（`D100=20−15=5≤25→hard`）
- 通用模式：任何需要 LLM 执行多步数值推演的 prompt，把中间步骤写成显式公式链，并在示例中展示完整计算过程，避免 LLM 跳过中间步骤直跳结论
- 适用场景：骰子修正、时间推进估算、伤害计算等任何需要 LLM 从原始值→调整→结果值→终态映射的场景
- 审计报告按严重度（阻断/高危/中危/低危）分级，每级明确文件路径 + 影响 + 修复方向，可落地为 `todowrite` 列表逐个击破
- 模板类修复批量进行（base.html 统一 CSS → game.html JS 逻辑 → partials），Pydantic 路由类需要精确匹配 starlette/fastapi 版本签名
- 一次性批量修改多个 `TemplateResponse` 签名时，用 `grep` 列出全部 10 个调用点后统一修正，避免遗漏

## 升级依赖后检查 API 签名兼容性
- Starlette 1.1.0 将 `TemplateResponse` 签名从 `(name, context)` 改为 `(request, name, context)`，旧签名导致 Jinja2 收到 dict 作为模板名 → `AttributeError: 'dict' object has no attribute 'split'`
- `pip install` 新包时可能同时升级间接依赖（如安装 uvicorn/jinja2 带动 starlette 升级），事后应运行全量 smoke test 而非仅 health check
- 快速检测：`python -c "from starlette.templating import Jinja2Templates; import inspect; print(inspect.signature(Jinja2Templates.TemplateResponse))"` 对比 git 历史中的调用方式

## 面向非程序员的 CLI 一键启动模式
- `.bat` 文件封装：检查 Python 环境 → 自动安装缺失依赖 → 检查 API 配置 → 启动服务 + 打开浏览器
- 关键细节：(a) 依赖检查用 `python -c "import X"` 而非 `pip list | grep`，更快且跨平台；(b) 失败时给出可操作的下一步（下载链接、手动命令）；(c) `chcp 65001` 解决 Windows 中文终端乱码
- 前端 server.py 默认自动打开浏览器（`--no-open` 可关闭），省去用户手动访问的步骤
- 适用于任何需要分发给非技术用户的 Python 项目

## Pipeline 字段新增模式：先验运行时后补管线
- 新增跨层字段（如 time_condition）时，先检查运行时是否已就绪（clock 已注入 day:X/time:X flags，judge flag: 处理器已就绪），再补管线生成端（prompt schema + Phase 2 透传 + 模板）
- 关键发现：运行时基础设施完整但管线零支持 → 字段天然容易实现，只因"没人告诉 LLM 可以输出这个"
- 与"统一数据源"互补——运行时通过 snapshot/build_snapshot 暴露能力，管线通过 prompt 约束让 LLM 按格式产出

## 确定性检查的放置顺序影响下游 LLM 调用
- Boss "at" 检查原在 enrich 之前，触发时直接 return → enrich 被跳过，outcomes 无润色
- 将此类检查移到 enrich 之后、combat_entry 之前：enrich 正常执行，Boss 触发仍可 early return 但润色已完成
- 通用规则：确定性短路检查应放在所有并行 LLM 步骤的 result 收集之后、最终 curate 之前

## 战斗结果信号分流 — 不在战斗层处理死亡
- Boss loss vs 普通 loss 返回不同布尔信号（combat_boss_loss / combat_death），由 game_loop 消费
- 战斗层只产出 CombatResult（纯数据），裁决层（game_loop）决定 game_over。两层都不直接"毙角色"
- 与"子系统并行合约"互补——CombatResult 是合约，信号分流是消费端的裁决逻辑

## LLM 日志审计的双层架构
- 确定性层：统计计数（技能通过率、战斗次数、实体覆盖）+ 基于阈值的异常检测（连续失败、降级次数）
- LLM 层：读完整回合摘要 + agent 日志（parse/enrich/narrator），输出结构化 findings（severity/turn/category/detail/suggestion）
- 两层互补：确定性覆盖"是什么"，LLM 覆盖"为什么异常"和"怎么修"
- 适用场景：任何需要从大量运行日志中提取可操作洞察的 LLM 应用测试

## LLM 管线消歧网关（Pre-parse Gate）
- 在重 LLM 处理（Parse）前插入轻量 flash 消歧网关，单职责：判断输入清晰度 + 模糊时生成引导反问
- 跨 turn 上下文整合：缓存上轮模糊意图+反问，下轮输入到达时尝试整合为完整行动（"搜一下"+"抽屉"→"搜查抽屉"），通过 `resolved_text` 传递给下游
- 兜底机制：连续 2 次模糊后第 3 次强制 clear，避免死循环
- **元命令白名单**：消歧网关必须排除斜杠命令（`/help`、`/scene` 等）——在 LLM 调用前就拦截，否则会被消歧 LLM 误判为模糊输入返回反问文本
- 适用场景：任何接受用户自然语言输入并需要精确 action/matching 的 LLM 系统——消歧放在输入端比放在匹配端更有效

## Tailwind CDN + HTMX 动态页面的内存泄漏
- Tailwind CDN 在浏览器运行时动态编译：HTMX 每次 swap 新 HTML 片段（含新 class）→ CDN 增量追加 `<style>` → 样式表无限增长，最终浏览器 OOM
- 解决方案：预编译静态 CSS 文件，包含项目中所有使用到的 utility class。长远考虑用 Tailwind CLI（`npx tailwindcss -i input.css -o output.css`）基于模板自动生成
- 同样触发条件：任何 CDN 运行时编译方案 + 长生命周期单页应用（HTMX/Turbo/Unpoly/LiveView）都会遇到

## Jinja2 extends 中的共享 UI 组件——放在 base.html 而非页面模板
- 跨页面共享的 UI 组件（文件浏览器模态框、通知弹窗）应放在 `base.html` 的 `{% block body %}{% endblock %}` 之后，避免页面重写时被删除
- JavaScript 函数（`openFileBrowser()`、`closeFileModal()`）也放在 base.html 中，与 DOM 元素同层
- 反例：本 session 重写 `launcher.html` 和 `game.html` 时意外删除了两处的 `#file-modal`，因为模态框是页面模板的一部分而非共享组件

## HTMX Partial 加载中的 JS 跨页面作用域
- HTMX 通过 `hx-get` 加载 HTML partial 时，partial 内的 `onsubmit="fn()"` 引用函数必须在**当前页面的全局作用域**中定义——函数只存在于定义它的模板所 extend 的页面中
- 本 session 案例：Launcher 页通过 HTMX 加载 `launcher-game-start.html` partial，其中调用 `initGame()`，但该函数定义在 `game.html` 的 `<script>` 块中，launcher 页面不可见
- 解决：在 partial 文件末尾内联所需 JS 函数；或把跨页面共享的函数提升到 `base.html`

## Subagent 批量前端重写的回归风险
- 大规模 HTML 模板重写（本 session 重写了 `game.html`、`launcher.html` 及 3 个 partials）后，交互功能（按钮、模态框、表单提交）极容易断裂
- 每次重写后应执行的功能回归检查清单：(a) 所有按钮 onclick/hx-post 是否触发 (b) 共享 DOM 元素（模态框）是否仍存在 (c) JS 函数是否在正确的页面作用域内 (d) CSS 静态文件中是否遗漏了新页面使用的 class
- Subagent 天然不感知"页面 B 的某个功能依赖页面 A 中的某个 DOM 元素"——Plan 必须在 Task 末尾显式列出回归检查项

## 项目死代码周期性审计
- 多维度系统性扫描：git 跟踪的临时备份（tmp_*）、stale worktree（`git worktree list`）、无引用源文件（grep import 全项目）、根目录过期文档（TODO/CHANGELOG）、IDE 生成文件（.iml）
- 与"修改前后双向审计"互补：后者是改前改后检查，这个是全局垃圾回收
- 最佳时机：完成一组非平凡改动后、或合并前——避免积累到不可管理的规模

## HTMX 多步骤向导的跨步骤数据持久化

- **问题**：HTMX `hx-get` + `hx-swap="innerHTML"` 在步骤切换时会销毁前一步的全部 DOM 元素（包括用户已填写的 input/textarea/select）。当步骤 3 的导出函数尝试读取步骤 1 的姓名/年龄/性别时，这些元素早已不存在
- **模式**：在向导容器**外部**放置一个全局 `<form id="char-form" style="display:none">` 包含所有步骤的 hidden input，每次步骤切换前调用 `syncAll()` 从当前步骤 DOM 同步到隐藏表单。导出和预览从隐藏表单读取，不依赖 DOM 存在性
- **关键细节**：(a) 隐藏表单用 `name` 属性匹配后端 Form 参数名，导出时直接 `fd.append(el.name, el.value)` 无需映射；(b) 返回上一步时从隐藏表单恢复字段值（`char-name` → `input[name="name"]`）；(c) 统计量的同步函数（`charStoreStats`/`charStoreSkills`）在新步骤找不到对应 DOM 时**不覆盖**隐藏表单已有值（见下一条）
- 适用：任何 HTMX/Unpoly/Turbo 驱动的多步骤表单向导

## Store 函数的安全回退：找不到源数据时不覆盖

- **反模式**：`charStoreSkills()` 从 `#skills-list .skill-input` 读数据 → 写入 `skills-json`。在步骤 3 被调用时 `#skills-list` 不存在 → 找到 0 个输入 → 执行 `skills-json.value = ''` → **清空了步骤 2 已保存的数据**
- **安全模式**：在数据收集函数顶部加早期返回 `if (inputs.length === 0) return;`——找不到源 DOM 元素时不做任何操作，保留已有值
- **泛化**：任何从动态 DOM 收集数据并写入持久存储的函数都应遵循此模式——"我能读就写，读不到就当我不存在"。这比"读不到就清空"安全得多，也避免了调用方需要判断上下文（"现在是在步骤 2 还是步骤 3"）
- 与"管道中的数据不应被后续步骤覆盖"互补——后者管管道步骤间，这个管前端状态管理

## 并行 session 后验证自己的修改未被覆盖

- 当知道有另一个 session 并行工作时，在对方 commit 之后必须做完整 diff 验证：`git diff <my-commit> HEAD -- <edited-files>`，逐行确认自己的每一处关键修改仍在最终版本中
- 高危区域：(a) 多行字符串/heredoc 中的变量引用——git 的上下文 diff 可能将删除误判为"格式调整"；(b) 同一函数的相邻行被双方分别修改时
- 不要依赖 `python -m py_compile` 通过就认为没问题——f-string 缺变量不报语法错，只是运行时输出空白
- 本 session 案例：并行 session 在 `build_step2b_combined_prompt` 误删了 f-string 中的 `{scene_list}`，编译通过但 prompt 中场景列表为空
- 与"修改后追溯上下游"互补——后者是改自己的下游影响，这个是防别人的并行修改覆盖自己的改动

## 序列化边界上的键名校对：dict.get 的无声失败陷阱

- **问题**：`clock.to_dict()` 返回 `{"game_time": 120}`，但三个消费者（Python 后端、JS 前端、CLI）都按 docstring 写的 `{"day": 1, "time_of_day": "夜间", "game_time_minutes": 120}` 去读取。`dict.get("day")` 返回 `None`，`if None:` 自然跳过——不报错、不崩溃、不出异常，输出只是**静默丢失**
- **根因**：dataclass 注释（"这个字段的格式是 {day:...}"）与数据源函数（`clock.to_dict()`）的返回值没有交叉验证。注释是人的猜测，to_dict() 是机器的事实——当两者不一致时，所有消费者都会被误导
- **模式**：序列化边界上使用 `dict.get()` + falsy guard 的组合（`if t.get("day"):`）极易产生无声失败。防御措施：
  1. 在**数据源侧**写 docstring 时必须与实际返回值逐键对照（不能凭记忆）
  2. 在**消费者侧**新增字段消费时，从实际响应中抓一条 JSON 检查每个键是否存在
  3. 如果架构允许，用 dataclass/typed dict 替代裸 dict 做数据合约——字段缺失在构造时即报错，而非静默跳过
- 适用：任何跨语言/Python→JS/后端→前端的 dict 序列化边界

## async 函数中同步阻塞调用 = 冻结整个事件循环

- **问题**：`queue.Queue.get(timeout=30)` 在 async WebSocket handler 中阻塞了整个 asyncio 事件循环线程，所有 HTTP 请求排队最长 30 秒
- **症状**：前端显示"加载中..."无限等待；后端不生成任何 log（请求排不进事件循环）；已有 WebSocket 连接仍然活跃；网络层面看起来一切正常——这是最难排查的一类 bug
- **根因**：async 函数内的同步阻塞调用（`queue.Queue.get`、`time.sleep`、`threading.Lock.acquire` 等）会冻住事件循环，其他所有 async task（包括 HTTP 请求处理）全部待机
- **解决**：`queue.Queue` → `asyncio.Queue`（`put`/`get` 都是 awaitable）；`time.sleep` → `await asyncio.sleep`；同步 IO → `await loop.run_in_executor(None, blocking_fn)`
- **排查技巧**："请求发出去但收不到响应 + 后端无任何 log" → 检查 WebSocket handler 或 background task 中是否有同步阻塞调用
- 适用：任何 asyncio + HTTP + WebSocket 混合应用

## @markup 的处理顺序：先提取再清理
- `judge.py` 的 `@item_gain` 全部失效是因为先 `_MARKUP_STRIP_RE.sub()` 剥离标记，后才解析 `entity.side_effects`。`result` / `graded_result` 中的 @markup 在解析前已被删
- 正确顺序：parse 收集 → merge 到 side_effects → 再 strip 供 narrator
- 泛化：任何"文本中含元数据标记"的管道——解析总是在清理之前。清理后再解析 = 信息已销毁
- 与"管道中的数据不应被后续步骤覆盖"互补：前者管步骤间的累积，这个管同一步骤内的操作顺序

## 多管道提示词中特殊约定的同步传播
- `@grant_weapon` 的 `scene=""`（直接授予）是运行时和生成端的共同约定，涉及 4 个 prompt 源：Phase 2 STEP4 + STEP2B、Supplement Pipeline、Author Patch
- 新增约定时必须 grep 所有相关 system prompt 并同步更新，否则 LLM 生成端和运行时消费端脱节
- 适用：任何 LLM pipeline 中有自定义语法/标记，且该标记被多个独立 prompt 引用时

## 等价事件共享同一抽象（而非复制代码）
- 搜索发现武器与 `GrantWeapon(scene="")` 直接授予最终走同一条 `_weapon_offer` 路径——短接确认、正则匹配、不跳回合
- 两者触发条件不同但结果等价 → 共享同一个 pending-offer 机制而非各自实现
- 适用：多条路径到达同一终态时，让它们汇入同一处理函数，而非在各分支复制粘贴

## 困在局部最优时，退一步换思路

- **反模式**：`choose_enemies` 的 `1x2` 格式解析遇到 `×`/`X`/`，` 等字符差异，不断追加 `replace("，",",")` / `replace("×","x")` / 正则匹配——每修一个 case 发现下一个
- **正确做法**：放弃字符串解析，改为逐步交互式输入（先选类型 → 再选数量 → 空行确认），零格式风险
- **判断信号**：当你发现自己在同一个函数里反复追加边界条件、特殊字符替换、try/except 守卫时，不是在"完善"——是在对抗一个**有根本缺陷的设计选型**。此时应该退一步问："有没有一个不需要解析这些的输入方式？"
- **代价比较**：字符串解析方案总复杂度 = 解析逻辑 + N 个边界条件 + 未来未知字符的维护。交互式方案总复杂度 = 空行确认。两者的长期维护成本差一个数量级
- 泛化：任何"用户自由文本 → 结构化数据"的解析任务——如果自由文本格式**不是**用户需求的一部分（即用户不关心用什么格式，只要能选就行），就用结构化交互替代文本解析

## JSON 配置库与运行时的字段传播链

- **反模式**：改了 JSON 库的字段（如 damage 字符串→dict、新增 special_rules），只更新了 library dataclass 的 `from_dict`，忘记了消费端（Weapon 类、EnemyManager.spawn()、combat._any_special_rules）也需要同步。本 session 的 5 个连锁 bug 都源于此：
  1. `damage` 改为 dict → `Weapon.damage: str` 仍期望字符串 → 拾取后 combat 读伤害 crash
  2. `EnemyAttack` 新增 `weight/skill_name/skill_value` → combat 中 `attack.get()` 拿不到这些字段（EnemyAttack 是 dataclass 不是 dict）
  3. `LibraryEnemy` 未设 `status` → `EnemyInstance` 默认 `"neutral"` → 战斗判定看到中立敌人不触发
  4. Boss 攻击 `dice_n:0` 无 `special_rules` → 伤害永远 0，LLM 修正从不触发
  5. `Weapon` 无 `special_rules/damage_type` 字段 → 拾取时只存了 name+skill+damage → `_any_special_rules` 永远 False
- **检查清单**：JSON 字段变更后，必须逐层审计：
  1. Library dataclass (`from_dict`/`to_dict`) ✓
  2. 运行时桥接对象（`EnemyInstance`、`Weapon`）
  3. 桥接代码（`spawn()`、`build_combat_init()`、拾取代码）
  4. 消费端（`_any_special_rules`、`_get_player_actions`、`_roll_damage`）
- **检测信号**：运行时某个功能"看起来配置了但不生效"——99% 是字段在某一层断了
- 与"修改后追溯上下游"互补：前者是改功能代码后的影响面检查，这个是改数据格式后每个消费层是否都收到了新字段

## LLM 只做布尔决策，确定性代码做数据查找

- **反模式**：让 LLM 返回精确的 `instance_id`（如 `Clicker_bdef558a`），然后确定性代码用 `get_by_id()` 查找。LLM 编造 ID（`Clicker_1`）→ 查找失败 → 战斗永不触发。
- **正确模式**：LLM 只回答布尔问题（`enter_combat: true/false`），确定性代码从已有数据结构中直接收集匹配项（`get_active_in_scene()`）。
- **原则**：LLM 的职责边界是语义判断（"是否应该战斗"），不是数据精确匹配（"哪个 ID 的敌人"）。后者永远比 LLM 可靠，因为数据已经在内存里了。
- **泛化**：任何"LLM 判断 → 确定性查找"的流水线——LLM 只输出布尔/分类标签，确定代码负责从结构化数据中按标签筛选。不要让 LLM 通过生成字符串去"引用"确定性侧的对象。
