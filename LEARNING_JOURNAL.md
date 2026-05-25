# Learning Journal — COC Simulator

> 更新原则：每次解决复杂问题后，提取可迁移的工程技巧。与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 交叉对比，向上同步通用技巧。保持 ≤2000 字。

---

## LLM Pipeline 设计：生成端与运行端的数据契约
- 生成端（pipeline）产出的 JSON schema 应与运行端（game loop）的 dataclass 字段一一对齐
- 新增字段时先在生成端 prompt 中定义输出格式，运行端同步消费；字段名和类型必须一致
- 运行端不应补全生成端缺失的数据——缺失应追溯到生成端修复

## 两阶段提交在游戏回合中的应用
- 一个回合内 parse + judge 先收集所有 outcomes 和 side effects，暂不执行
- 等异步确认（如 Author Patch）通过后，一次性 apply；如确认触发重试，则清空 pending 重新收集
- 避免了"先执行再回滚"的复杂性和遗漏风险

## 端到端测试作为唯一验收标准
- LLM 驱动项目中，单元测试因 mock 无法还原 LLM 行为而意义有限
- 以真实 LLM 调用的端到端 harness 为唯一验证方式；每次修改后必跑
- 测试输入应与实际游玩场景对齐，覆盖交互链而非孤立操作

## 日志并行写入的正确姿势
- 多个 LLM 调用并行时，不应共享全局日志标签；每个调用应各自写入独立文件
- 最简方案：每个 agent 在自己的方法内打开专属文件 append 写入，不依赖全局状态
