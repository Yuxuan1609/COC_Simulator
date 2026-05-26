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

## 面向非程序员的 CLI 一键启动模式
- `.bat` 文件封装：检查 Python 环境 → 自动安装缺失依赖 → 检查 API 配置 → 启动服务 + 打开浏览器
- 关键细节：(a) 依赖检查用 `python -c "import X"` 而非 `pip list | grep`，更快且跨平台；(b) 失败时给出可操作的下一步（下载链接、手动命令）；(c) `chcp 65001` 解决 Windows 中文终端乱码
- 前端 server.py 默认自动打开浏览器（`--no-open` 可关闭），省去用户手动访问的步骤
- 适用于任何需要分发给非技术用户的 Python 项目
