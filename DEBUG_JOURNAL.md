# Debug Journal — COC Simulator

> 更新原则：每次解决复杂问题后记录。与 `LEARNING_JOURNAL.md` 交叉对比，确认是否有可迁移的工程技巧。保持 ≤10000 字。

---

## 1. NPC 名称匹配失败 — 玩家用"乘务员"指代 NPC "京山 人吉"
**日期**：2026-05-25
**症状**：玩家输入 "和乘务员对话"，系统不触发 NPC 交互，走主 parse 当 `other` 处理
**根因**：`keeper.py:95` 用 `npc.name in raw` 做精确子串匹配，"京山 人吉" 不在 "乘务员" 中
**解决**：改为 parse 层 `npc_interact` 类型——LLM 在 parse 时判断玩家是否在和当前场景 NPC 对话，不再依赖字符串匹配

## 2. TimeAgent response 不写入日志
**日期**：2026-05-25
**症状**：TimeAgent 的 prompt 有日志，system 有日志，但 response 缺失；timing 文件也没有 TimeAgent 条目
**根因**：TimeAgent 调用 `call_deepseek` 时传了 `thinking=False`，该参数导致 `call_deepseek` 在测试 harness 的 `_logging_wrapper` 中因为 kwargs 过滤而行为异常（`thinking=False` 和默认 `thinking=None` 输出格式不同）
**解决**：去掉 `max_tokens=300` 和 `thinking=False`，与 Keeper Enrich 保持一致的调用格式

## 3. Enrich + TimeAgent 并行日志竞态
**日期**：2026-05-25
**症状**：TimeAgent 的 response 出现在 keeper_enrich.txt 中，格式是 Enrich 的 `results/reasoning/emphasis_hint` 而非 TimeAgent 的 `time_delta/narrative_hint`
**根因**：`_show_prompt` 设置全局 `_current_log_label`，Enrich 和 TimeAgent 并行时互相覆盖，导致 `_log_response` 写入错误文件
**解决**：各 agent 自己写 response（`TimeAgent._log_response()` 直接打开 timeagent.txt 追加），不再依赖全局 label

## 4. Author Patch 导致 move 重复执行
**日期**：2026-05-25
**症状**：Author 对模组做 Patch 后，`process_turn()` 递归调用导致 move 被执行两次，玩家往前走两个场景
**根因**：第一次 parse 时 move 已被执行（修改了 `world.current_location`），递归时再次 parse 又执行一次 move
**解决**：改为两阶段提交——parse + judge 时 side_effects 和 move 全部压入 `_pending`，Author 确认无 Patch 后 `_apply_pending()` 统一执行；如果 Author 有 Patch，递归时 `clear()` 丢弃 pending

## 5. NPC bound entity 在 parse prompt 中分类错误
**日期**：2026-05-25
**症状**：4号车厢 parse prompt 中，NPC 绑定的 I7/I8/AT6 显示在 `【场景实体】` 而非 `【NPC 专属实体】`
**根因**：`_build_entity_lines()` 只对 AT 检查 `_npc_injected_at_ids`，没对 interaction 做同样处理，且注入跟踪不可靠
**解决**：直接从 `npc.bound_interactions` / `npc.bound_auto_triggers` 收集 ID 集，在遍历 node 实体时检查归属
