# Learning Journal — COC Simulator

> 更新原则：每次解决复杂问题后，提取可迁移的工程习惯/方法论。保持 ≤2000 字。
> **写入前**：与已有内容交叉对比——新条目可能与已有条目重叠或互补，优先合并而非新增。
> **同步**：大更新时与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 对比，将可迁移的内容同步过去。

---

## LLM Pipeline 的 System Prompt 与 User Prompt 分离
- System prompt = 任务定义 + 格式约束 + 硬性规则（不随输入变化）
- User prompt = 动态数据（源文本、库列表、已知场景/角色等）
- 反面教训：`STEP2B_AT_SYSTEM` 提到 @标记 名称但没给精确语法 → LLM 自创格式 → `@spawn_enemy: Clicker in 2号车厢` 不可解析。函数签名/示例必须写在 system prompt 中

## LLM 需要白名单时不要依赖"常识"
- Type 字段需要 COC 技能名 → 不能假设 LLM 知道 46 个标准技能名 vs 属性名（灵感/幸运）的区别
- 每次需要从固定集合中选择时，把完整列表注入 prompt

## LLM 无法理解否定语义的依赖
- `||乘务员未被带走（I7 检定失败）` → LLM 会把 I7 当作正向依赖提取
- 解析关系时必须显式区分 "完成/成功 → 正向依赖" 和 "失败/未做 → 不计入依赖"

## 同名变量导致静默 Bug
- `phase1_result` 从未定义但 Python 不报错（运行时 NameError 才爆）→ `layered_pipeline.py:830` 应为 `phase1_clean`
- 变量命名要与赋值保持一致；IDE 的 "未定义变量" 检查很关键

## 双代码路径是 Bug 温床
- `run_auto` 和 `run_interactive` 各走一套完全不同的 `run_pipeline` / `_do_step*` 逻辑 → 自动模式无 step 目录、无中间产物
- 尽早统一代码路径，不要在第二套实现中复制逻辑

## git stash pop 后验证文件完整性
- `git checkout -- file` → `git stash pop` 恢复的可能是旧快照，部分编辑丢失
- 恢复后必须比对预期状态（grep 关键修改是否还在，import 是否通过）
