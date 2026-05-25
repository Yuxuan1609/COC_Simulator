# Learning Journal — COC Simulator

> 更新原则：每次解决复杂问题后，提取可迁移的工程习惯/方法论。保持 ≤2000 字。
> **写入前**：与已有内容交叉对比——新条目可能与已有条目重叠或互补，优先合并而非新增。
> **同步**：大更新时与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 对比，将可迁移的内容同步过去。

---

## 端到端测试作为唯一验收
- LLM 驱动的项目，单元测试因 mock 无法还原 LLM 行为而基本无效
- 每次修改后必跑真实 LLM 调用的 harness；测试输入应覆盖完整交互链，不测孤立操作

## 生成端与运行端的数据契约
- 生成端产出的 schema 决定了运行端能消费什么；数据缺失应追溯到生成端修复，不在运行端打补丁
- 新增字段时两端同步确认，避免一方改了另一方不知道
- **本 Session 延伸**：`##GRADED##` 在运行端被正确解析（`resolve_graded_result`），但产物文本被 D100 裸字符串覆盖——属于运行端"解析了但没使用"的契约断裂

## 数据管道中关键输出不可被后续步骤覆盖
- Enrich 管道中 `all_outcomes[0].message` 被无条件覆写，下游步骤（Narrator）拿不到上游（Judge/Penalty）生成的原始信息
- 解决：覆写逻辑应做类型判断——只覆盖同类输出（成功+成功），不跨类型覆盖（成功→覆盖失败）
- 通用模式：管道的每一步应该是**累积式**而非**替换式**；若必须替换，需显式声明"哪些类型可被替换"

## `from X import Y` 的 mock patch 陷阱
- `patch("llm.call_deepseek", mock)` 只替换模块属性，不影响已通过 `from llm import call_deepseek` 绑定到其他模块本地命名空间中的引用
- 每个使用 `from X import Y` 的模块都需要单独的 `patch("module.call_deepseek", mock)`
- Audit 方法：grep `from llm import call_deepseek` 找出所有调用方，逐个检查是否在 patches 列表中

## @markup 作为确定性指令与叙事文本的分离
- @markup 是给 parser 的确定性指令（刷怪/扣血/给物品），不应暴露给 LLM
- 实现：两层防御——源头（judge 输出前 strip）+ 消费端（enrich prompt 构建时 strip）
- 通用原则：管道中面向机器的标记语言和面向 LLM 的自然语言应在进入 LLM 视野前完成分离

## edit 工具对多行 f-string 的截断风险
- 当 `oldString` 只匹配多行 f-string 的第一行（含闭合 `"""` 之前的部分），替换后整个字面量被截断，剩余行被删除
- 更危险的是：截断后的 f-string 语法仍然合法，Python 不会报 SyntaxError——是一种静默的数据丢失
- **对策**：对包含 `f"""..."""` 或 `"""..."""` 多行字面量的文件，`oldString` 必须包含 3 行以上的唯一上下文；修改后立即 `py_compile` + 读文件相关段确认完整

## LLM prompt 的身份框架效应
- "你是格式转换者"和"你是原文作者在做二创"这两种 prompt 产生完全不同的输出质量——前者趋于机械、压缩信息，后者趋于创造、保留细节并自然衍生分支
- 当要求 LLM 从一种格式转到另一种格式时，给它一个**创作者身份**而非**转换工具身份**，输出中的信息保留度和创造性都会显著提升
- 适用于任何"格式转换 + 内容增强"的 prompt 设计场景

## DeepSeek JSON 模式的正确用法
- 官方要求：`response_format={'type': 'json_object'}` + prompt 中包含 `json` 字样 + 合理 `max_tokens` 防截断
- 很多项目只依赖 prompt 约束（"请输出 JSON"）而不传 `response_format`，导致偶尔返回 markdown 包裹的 JSON 或非纯 JSON 文本，需要额外 ` ```json ``` ` 剥离逻辑
- 加上 `response_format` 后模型严格输出合法 JSON，可以去掉 markdown 剥离代码
- 官方提示 API 可能返回空 content——需要加空值重试逻辑
