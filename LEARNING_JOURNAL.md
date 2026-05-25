# Learning Journal — COC Simulator

> 更新原则：每次解决复杂问题后，提取可迁移的工程习惯/方法论。保持 ≤2000 字。
> **写入前**：与已有内容交叉对比——新条目可能与已有条目重叠或互补，优先合并而非新增。
> **同步**：大更新时与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 对比，将可迁移的内容同步过去。

---

## LLM Pipeline：生成端到运行端的数据契约
- 生成端（pipeline）产出的 JSON 字段，运行端（game loop）的 dataclass 必须一一对齐
- 缺失数据应在生成端修复，不在运行端补丁；否则下次重新生成又会丢失

## 端到端测试作为唯一验收
- LLM 驱动的项目，单元测试因 mock 无法还原 LLM 行为而基本无效
- 每次修改后必跑真实 LLM 调用的 harness；测试输入应覆盖完整交互链，不测孤立操作

## 管道并行编排
- 多步 LLM 调用中，用依赖图确定哪些可并行 → ThreadPoolExecutor 一次提交 → 合并结果
- 并行后处理（merge/dedup）保持串行，避免竞态
