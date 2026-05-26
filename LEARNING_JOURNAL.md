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
- 设计→Plan→Subagent-Driven Development 三步：设计文档冻结子系统清单和接口边界；Plan 写出每步的文件路径/精确代码/测试命令；每个 Task 一个独立 subagent（implement→spec review→code quality review）
- 关键决策：RuntimeState 融合回 World 本体而非独立类——本质是对两个 dict 的 CRUD + 依赖查询，拆出去只是多一层间接
- 向后兼容：用 `@property` 代理旧属性名（`world.game_time` → `world.clock.game_time`），给所有调用方预留迁移窗口
- Worktree isolation 保证主分支不受破坏，merge 时仅 `side_effects.py` 一个冲突（新文件 add/add）

## LLM Mock/Patch Wrapper 的 `**kw` 陷阱
- 为日志拦截而写的 `call_deepseek` wrapper 如果有显式默认参数（如 `model=""`），会把空字符串传给真实 API——而 `model=""` 和 `model=None` 语义不同（后者在 `call_deepseek` 内回退到默认模型）
- 正确做法：`def wrapper(prompt, json_mode=True, **kw)`，从 `kw` 中过滤已知合法参数，用 `filtered["json_mode"] = json_mode` 覆盖，其余按原名传递
- 同样影响 mock wrapper——所有替换 `call_deepseek` 的 wrapper 都应遵循此模式

## 测试 Harness 并行隔离模式
- 每个 case 通过 `_init_game_instance()` 创建独立 World/Keeper/Narrator/Author 全套实例，不共用任何可变状态
- `ThreadPoolExecutor` 在 worker 线程内调用 `init_game()`（创建在 worker 而非主线程），避免跨线程共享
- Mock 模式用 `--mock` flag 切换：原 LLM path 保留，mock path 注入 `patch()` 替换所有 `call_deepseek` 调用点
- 必须在 patches 列表中显式覆盖所有 agent 的 `call_deepseek`（keeper/intent_detector/author/narrator/time_agent），因为各 agent 用 `from llm import call_deepseek` 持有模块级引用，`patch("llm.call_deepseek")` 只影响 llm 模块属性，不影响已导入的本地引用
