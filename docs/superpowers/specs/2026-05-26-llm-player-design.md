# LLM Player + Audit Script Design

## Overview

LLM-driven TRPG 玩家脚本，模拟真实玩家行为探索模组。配合审核脚本自动评估 gameplay 质量。

## Architecture

```
llm_player.py          — LLM 玩家驱动
audit_player_log.py    — 日志审核报告
stress_profile.json    — 共享配置（策略 + 审核重点）
```

两个脚本读同一份 `stress_profile.json`，无需重复配置。

## LLM Player (`llm_player.py`)

### Flow

```
初始化: init_game(模组路径) + set_turn_logger + load stress_profile
循环:
  1. snapshot = world.build_snapshot()
  2. narrative = 上一轮 run_turn 的 brief + narrative
  3. build_player_prompt(snapshot, narrative, short_history, long_memory, stress_profile)
  4. action = call_deepseek(flash, prompt) → {"action": "...", "reasoning": "..."}
  5. result = run_turn(game, action)
  6. short_history.append({action, narrative, parse_matches, ...})
  7. 每 5 轮: compress_history() → long_memory
终止: result.game_over || turn >= max_turns || elapsed >= max_duration
输出: logs/llm_player/<ts>/  (TurnLogger + prompt logs)
```

### System Prompt

```
你是 COC 7th TRPG 玩家 AI。目标：推进剧情、扮演角色、探索世界。

行动优先级:
1. 与场景中的 NPC 互动（对话、跟随、请求帮助）
2. 检查场景中提到的物品、线索和异常
3. 向有意义的场景移动
4. 尝试明显的技能检定
5. 当 stuck 时尝试非直接方案

[压力测试模式]
当前焦点系统: {focus_systems}
- NPC: 积极与 NPC 对话、尝试跟随、测试态度变化边界
- Enemy: 尝试进入/退出战斗、对峙、逃跑等路径
- TimeAgent: 尝试等待、休息、rush 等时间操作
- Author: 尝试出人意料的动作、边界输入（空输入、不合理动作）

角色扮演要求:
- 行动符合调查员性格和当前 SAN 状态
- 危险时表现恐惧、犹豫
- 用自然语言输入，不使用游戏命令格式
```

### User Prompt

```
【调查员】
HP={hp}/{max_hp} SAN={san} MP={mp}
武器: {weapons}
物品: {inventory}

【当前场景】
{location}: {description}
NPC: {npcs}

【本轮叙事】
{brief}
{narrative}

【最近行动】
{short_history 最近 5 轮}

【长期记忆】
{long_memory}

请选择下一步行动。返回 JSON：
{"action": "玩家输入文本", "reasoning": "策略说明（20字以内）"}
```

### Memory Compression

每 5 轮：将 `short_history` 喂给 flash LLM 压缩为一段摘要追加到 `long_memory`。

```
将以下游戏记录压缩为一段摘要（100字以内），保留关键决策和结果:

{short_history}

格式: "第N-N轮：在{场景}做了{关键行动}，结果{结果}。发现{信息}。"
```

### Termination

- `result.ending.game_over == true` — 结局触发
- `turn >= max_turns` (default 60)
- `elapsed >= max_duration_s` (default 3600)

### CLI

```
python llm_player.py                          # 默认 更新模组0526v2
python llm_player.py --module 更新0526        # 指定模组
python llm_player.py --turns 30               # 限制轮数
python llm_player.py --profile stress_npc.json # 自定义 stress profile
```

## Audit Script (`audit_player_log.py`)

### Input

`logs/llm_player/<ts>/` — TurnLogger 输出 + prompt logs

### Output

`audit_report.md` — Markdown 报告

### Report Structure

```
# LLM Player Audit Report
## Summary
- 总轮数 / 耗时 / game_over 状态
- Entity 覆盖率: X/Y interactions, X/Y ATs, X/Y events
- 检定通过率: X/Y (XX%)

## Per-Turn Detail
| # | 输入 | Parse | Judge | Enrich | Narrative | 耗时 | 标记 |
|---|---|---|---|---|---|---|---|
| 1 | 环顾四周 | I1,I2 | ✓✓ | OK | "你环顾..." | 12s | |
| 2 | 检查便签 | other | - | skip | "你没有..." | 8s | ⚠ other |

## Subsystem Stress Check
### NPC
- talk_to 调用: 5 次
- 跟随触发: 2 次（Turn 4, 15）
- 态度变化: neutral→friendly (Turn 12)
- 异常: 无

### Enemy
- spawn: 1 次 (Turn 20)
- combat_entry: 1 次 (Turn 21, win)
- 对峙: 0 次
- 异常: 无

### Boss
- 未触发（模组预设 boss_encounter 未满足条件）

### TimeAgent
- 时间推进: 0m → 45m
- pressure 激活: Turn 25
- 异常: 无

### Author
- Patch 触发: 1 次 (Turn 8)
- StructuralEdit: 0 次
- 异常: Patch 内容与已有 entity 重叠

## Anomalies
| 轮次 | 类型 | 详情 |
|------|------|------|
| 2 | other_unmatched | "检查便签" 未匹配实体 |
| 8 | author_patch_overlap | Author Patch 与 I3 内容重叠 |
| 11-13 | consecutive_fail | I5 检定连续 3 次失败 |
| 25 | enrich_degrade | Enrich 降级跳过 |

## Recommendations
- Turn 2: 检查 parse prompt 是否遗漏 entity
- Turn 8: 检查 Author 去重规则
- Turn 11-13: 检定难度可能过高，考虑调整 difficulty
```

## Stress Profile (`stress_profile.json`)

```json
{
  "focus_systems": ["NPC", "Enemy", "TimeAgent"],
  "player_config": {
    "max_turns": 60,
    "max_duration_s": 3600,
    "memory_compress_interval": 5,
    "model": "deepseek-v4-flash",
    "reasoning_effort": "low"
  },
  "audit_config": {
    "anomaly_thresholds": {
      "other_rate_max": 0.3,
      "enrich_degrade_max": 2,
      "consecutive_fail_alert": 3,
      "combat_max_duration_turns": 10
    }
  }
}
```

## Error Handling

- LLM 调用失败 → 重试 3 次 → fallback: "环顾四周"
- run_turn 返回异常 → 记录错误 + 跳过本轮 + 用 "继续前进" 重试
- game.crashed → 保存当前日志 + 异常退出，audit 脚本可部分读取

## File Layout

```
src/
  llm_player.py           # LLM 玩家驱动
  audit_player_log.py     # 日志审核脚本
data/
  stress_profile.json     # 默认压力测试配置
logs/llm_player/<ts>/
  _summary.json           # 逐轮摘要
  turn_logs/              # TurnLogger 输出
  _llm_calls/             # prompt/response 日志
  audit_report.md         # 审核报告（audit 脚本输出）
```

## Out of Scope

- 前端集成 — 纯后端脚本，下个 session 单独做
- WebSocket 玩家连接 — 不需要
- 多调查员/多人模式
