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
- G1-G8 全部 FIXED 后仍占据"已知缺口"表的一半行数，读者难以快速定位真正活跃的问题
- 清理后"已知缺口"只留 G9/G10，"待优化"只留 O4-O7，并标注优先级
