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
