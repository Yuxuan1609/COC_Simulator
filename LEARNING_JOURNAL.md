# Learning Journal — COC Simulator

> 更新原则：每次解决复杂问题后，检查是否有可迁移的工程技巧。与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 交叉对比，将有价值的技巧同步到全局。保持 ≤2000 字。

---

## Entity 生成端与运行端解耦
- 生成端（pipeline Step 2a/2b）定义 entity 的结构和依赖，运行端（keeper）负责解析和触发
- Entity 的 `bound_interactions`/`bound_auto_triggers` 属于 NPC 后，随 NPC 移动；通过 `_inject_npc_at()` 在运行时注入到当前 scene，确保 NPC 可交互内容跟随 NPC 位置
- NPC 对话路由从独立 `process_npc_turn` 改为 parse 层 `npc_interact` 类型，统一走主 parse 管线

## LLM 调用日志的独立写入
- `_show_prompt` 设置全局 label → `_log_response` 读全局 label 的模式在并行场景下必然出问题
- 改为每个 agent 自己写 response 文件：`self._log_response(content, filename)` 绕过全局状态
- 日志的 system prompt 也写到同一个文件，方便调试时还原完整上下文

## 端到端测试优先
- 单元测试在 LLM 驱动的项目中意义有限——关键行为由 LLM 输出决定，mock 无法还原
- 使用 `test_harness_stability.py` 做真实 LLM 调用的端到端验证，每次修改后必跑
- 测试 harness 的 `_logging_wrapper` 是并行安全的——因为 `_REAL_CALL` 在闭包中捕获，不依赖全局 label
