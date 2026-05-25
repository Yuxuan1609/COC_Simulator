# Project Notes

- 所有 log 文件默认生成在当前项目根目录（`D:\COC simulator\data\debug\`）下，除非专门指定，不要放到子目录（如 `.claude/`、`docs/` 等 branch 路径）
- git branch 可以在此文件夹下建专属目录，但 log/prompt 输出仍推荐放在项目目录
- 测试 harness 输出路径：`data/debug/test_harness/<timestamp>/`
- prompt 日志路径：`logs/` 或 test harness 的 `_prompt_log.txt`
- 测试输出的 log 文件不入 git 版本管理
- **测试策略**：不做单元测试。只保留端到端测试（test_harness_stability.py、test_escalation_real.py、test_harness_parallel.py）和局部端到端测试。以真实 LLM 调用结果为准，不以单元测试为基准
- **修改规则**：同一个问题如果改到第 2 次还没解决，必须停下来。不要继续之前的思路，不要想当然。要一步一步地测试，必要时添加 prompt 或中间输出文件来定位问题，同时审视之前的思路是否正确
