# Global Rules

## Language
- Default response body text to Chinese (简体中文). No explicit requirement on Chinese vs English — adapt naturally when context calls for English.
- Keep field names, proper nouns, technical terms, variable names, identifiers, and code comments in their original language. Do not translate them.
- When writing code or configuration, preserve the original casing and naming conventions of all identifiers, API names, library names, and protocol terms.
## Decision Making
- When facing complex design decisions or uncertain situations, prioritize confirming with the user before proceeding. Keep asking until all doubts are resolved.
## Learning & Debug Journals
- 每个项目维护两个 Journal 文件（放在项目根目录）：
  - `LEARNING_JOURNAL.md`（≤2000 字）：本项目中学到的可迁移工程技巧
  - `DEBUG_JOURNAL.md`（≤10000 字）：本项目解决的复杂 Bug 和问题
- 全局 `LEARNING_JOURNAL.md` 位于 `~/.config/opencode/`，汇总跨项目的工程技巧（≤2000 字）
- 每次解决复杂问题后，更新项目的 Debug Journal 和 Learning Journal，并交叉对比两个文件是否有需要同步的内容
- 项目 Learning Journal 有大更新时，与全局 Learning Journal 对比，将可迁移的技巧同步到全局
- 更新原则写在每个 Journal 文件的顶部
- **Learning Journal 写入规则**：每次较大写入前，先与已有内容交叉对比——新技巧可能与已有条目重叠或互补，优先合并而非新增条目
## Journal 使用流程
- **开始工作时**：先读取项目的 `LEARNING_JOURNAL.md` 和 `DEBUG_JOURNAL.md`，了解已知的工程技巧和过往的复杂 Bug，避免重复踩坑
- **解决复杂问题后**：更新 `DEBUG_JOURNAL.md`（症状 → 根因 → 解决方案），同时反思是否有可迁移的工程技巧写入 `LEARNING_JOURNAL.md`
- **项目 Learning Journal 有新增时**：与全局 `~/.config/opencode/LEARNING_JOURNAL.md` 对比，将可迁移的部分同步过去
