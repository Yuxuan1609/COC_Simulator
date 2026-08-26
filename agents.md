# AGENTS.md — 项目协作规则

## 通用规则

- 每次进行文件修改后，同步更新 `MAINTENANCE.md`（函数/文件的功能记录、行号、调用关系），保持维护文档与代码一致。

## 测试验证约定

- 每个任务收口默认只跑 `pytest tests/ -q`（已排除 real_llm，零 API）
- 禁止在单任务后跑全量 `pytest -m real_llm`
- 改了 prompt / parse / narrator / keeper 主路径，或一个阶段全部代码完成后，跑 `pytest -m real_llm_smoke`
- 全量 `pytest -m real_llm` 仅用户明确要求时执行
