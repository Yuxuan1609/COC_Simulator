# llm_player 3 轮快速验证指南

## 命令

```bash
python src/llm_player.py --turns 3 --module 常暗之厢_0531
```

## 输出位置

`logs/llm_player/<YYYYMMDD_hhmmss>/`

## 检查文件

| 文件 | 内容 | 检查点 |
|------|------|--------|
| `_summary.json` | 每轮汇总（player_input / brief / narrative / skill_results / combat） | 结尾无 error 字段 |
| `player_llm.txt` | 每轮 LLM system + user + response | 格式完整，无 "fallback" 连续出现 |
| `turn_logs/` | TurnLogger 写入的回合日志 | 每个 turn 应有 jsonl 条目 |
| `logs/prompt_log_*/` | Keeper/Enrich/Narrator 等 prompt log | 并行竞态（自 DEBUG_JOURNAL #3 修复后已 OK） |
| `logs/prompt_log_*/turn_*.json` | 每轮 JSON | 检查 combat_init.enemies 数量是否正确 |

## 常见失败检查

1. `FileNotFoundError: l2_keeper_test.json` → 模组缺文件，检查 `l2_name` 逻辑
2. `NameError: name 'Entity' is not defined` → scenario_core.py 中 Entity 类丢失
3. `NameError: name 'format_turn_dynamic' is not defined` → llm_player 缺 import
4. `TypeError: /: 'str' and 'str'` → log_dir 是 str 不能直接用 `/`
5. `[WARN] build_player_prompt failed` → Player prompt 构建函数缺依赖
6. LLM 返回 "环顾四周"（fallback）连续 2+ 次 → parse 匹配失败，检查 prompt log

## 关键引用的 Journal 条目

- **DEBUG #3**: Enrich + TimeAgent 并行日志竞态
- **DEBUG #17**: World AT item_gain 静默丢弃
- **LEARNING**: 重构前审计完整数据流（grep 所有引用）
