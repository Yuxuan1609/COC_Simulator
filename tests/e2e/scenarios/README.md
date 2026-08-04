# E2E 场景定义（步骤 3：场景化 llm_player）

场景 = 初始状态种子 + 玩家目标（goal）+ 三层判定（invariants / predicates / judging）+ 回合预算。
由 `tests/e2e/run_scenario.py` 驱动，真实 LLM，on-demand 运行，不进默认 pytest 套件。

## 运行

```bash
python tests/e2e/run_scenario.py tests/e2e/scenarios/standoff_avoid.yaml
```

退出码 0 = PASS，1 = FAIL。日志与判定产物输出到
`data/debug/e2e_scenarios/<timestamp>_<name>/`（llm_player 日志 + `profile.json` +
`judge_llm.txt` + `verdict.json`）。

## YAML 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | 场景名（用于日志目录命名） |
| `description` | 否 | 场景简述 |
| `module` | 是 | `data/modules/<name>/` 模块名（机制测试用 `e2e_testbed`） |
| `seed` | 否 | 命令式播种，仅用于模块 JSON 表达不了的初始状态（见下） |
| `goal` | 是 | 玩家指引文本，注入玩家 LLM 的 prompt（goal 模式） |
| `judging` | 是 | 审计 rubric 文本，judge LLM 逐项判定并给证据 |
| `predicates` | 否 | 机器谓词 `{谓词名: 期望值(true/false)}` |
| `success_checks` | 否 | 提前终止谓词列表，显式覆盖默认派生（见下） |
| `max_turns` | 否 | 回合预算，默认 10 |
| `max_duration_s` | 否 | 时长预算，默认 900 |
| `player_model` | 否 | 玩家 LLM 模型，默认 deepseek-v4-flash |

### seed 可用值

```yaml
seed:
  enemy: {name: 深潜者, scene: 测试房间A, avoidable: true, qty: 1}
  player_skills: {潜行: 95, 话术: 95}
```

- `enemy`：`world.enemies.spawn(name, scene, qty)` 命令式播种；`avoidable: true` 时
  追加 `avoidable` flag（`@spawn_enemy` 标记不支持 flags，可回避敌人只能这样播种）。
- `player_skills`：覆盖/新增玩家技能值。

### predicates 可用值

谓词实现在 `tests/e2e/scenario_predicates.py`（输入为每回合 summary 日志条目）：

| 谓词 | 语义 |
|------|------|
| `combat_occurred` | 任意回合发生了战斗结算 |
| `standoff_occurred` | 任意回合触发了对峙（pending kind=standoff） |
| `weapon_picked_up` | 玩家武器数相对首回合基线有增长 |
| `npc_following` | 任意回合有 NPC 处于跟随状态 |
| `game_over` | 任意回合触发了结局 |
| `player_alive` | 末回合玩家存活 |

期望为 `true` 的谓词默认作为 `success_checks` 注入 profile——每回合结束后全部满足
则提前终止并记录 `goal_achieved: true`；期望为 `false` 的谓词是全程不变量，只在终局判定。
若场景需要观察谓词触发之后的回合（如 standoff 触发后的回避过程），用 `success_checks: []`
显式置空，禁用提前终止。

## 三层判定语义

| 层 | 内容 | 性质 |
|----|------|------|
| invariants | 每回合日志契约结构（必填字段/类型/pending 合法值） | 机器硬断言 |
| predicates | 上表机器谓词逐项比对期望值 | 机器硬断言 |
| judging | 场景 rubric 由 judge LLM（pro 模型）逐项判定给证据；机器复核：逐项全 pass 才 PASS | LLM 审计 |

最终 `verdict = invariants AND predicates AND judging`，结果写入 `verdict.json` 并打印报告。
judge 的原始 prompt/response 落盘 `judge_llm.txt`，判定证据可溯源。
