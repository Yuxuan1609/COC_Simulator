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
