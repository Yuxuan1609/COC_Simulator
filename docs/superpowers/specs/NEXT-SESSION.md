# Next Session — 当前状态 + 待办

**日期**: 2026-05-19
**分支**: main
**状态**: Game Loop 多 Agent 架构完整 | dependency_graph + runtime_state 已统一 | 前端 Web 界面可用 | 测试文件就绪

---

## 当前架构

```
玩家输入 → Parse(LLM) → Judge(确定) → Enrich(LLM) → Escalate?(LLM) → Curate → Narrate(LLM) → 输出
```

### Agent

| Agent | 数据 | 职责 |
|-------|------|------|
| Keeper | L2 + ScenarioWorld | 回合编配: parse→judge→enrich→curate |
| Narrator | L1 | 唯一面向玩家，沉浸式叙事 |
| Author | L3 | 按 L3 设计意图生成 ModulePatch（仅 escalation 时触发） |

### 关键机制
- **dependency_graph + runtime_state**: 替代 world.flags，静态依赖 + 动态状态两层
- **parse_hard_requirement**: AND/OR 结构化解析，edge AND 兜底
- **@markup**: 5 种（spawn_enemy/grant_weapon/stat_change/item_gain/npc_state_change），运行时解析
- **##GRADED##**: COC 7th D100 四级检定 (failure/regular/hard/extreme)
- **失败惩罚**: 难度升级 → LLM 创意后果
- **特质修正**: trait enhancement sub-agent
- **LLM 错误提示**: 各阶段有玩家可见警告

### 当前使用文件

**测试环境**: `data/modules/常暗之厢/l*_test.json`（测试房间 + 原模组内容）
**正式环境**: `data/modules/常暗之厢/l*_keeper/player/designer.json`

---

## 待实现 / 进行中

### 1. 作者介入机制 (Author Escalation) — 需明确

**当前状态**: 骨架已实现。`_check_escalation` 每回合 LLM 评估，`Author.handle_escalation` 生成 ModulePatch。
**待明确**:
- Escalation 触发条件是否足够精准（目前用 LLM 评估维度 + 阈值）
- ModulePatch 如何回注到 game world（`_integrate_patch` 已预留接口，需验证完整链路）
- 创作者豁免 WR0 如何在实际裁决中体现
**代码位置**: `src/game/agents/keeper.py:154-161`, `src/game/agents/author.py`, `src/game/escalation.py`

### 2. 战斗系统 — TODO

**目标**: COC 7th 回合制战斗
**关键问题**:
- 进入战斗的判定（spawn_enemy 后是否需要自动进入战斗？玩家主动攻击？）
- 战斗回合结构（先攻 → 行动 → 伤害 → 状态）
- 与现有 skill check 系统的衔接（格斗、射击等技能已有 D100 检定能力）
- 敌人 AI（简单规则还是 LLM 辅助？）
**代码位置**: `src/investigator/models.py`（check_skill 已有），`src/library/enemies.py`（敌人数据）

### 3. NPC / 同伴系统 — TODO

**目标**: NPC 主动行为、对话树、状态驱动反应
**当前状态**: L2 有 `npc_profiles`（what_they_can_do, interaction_triggers, personality_notes），`NPCStateChange` 可修改状态。但 NPC 完全被动——仅在玩家触发 interaction 时反应。
**待实现**:
- NPC 主动推进剧情（基于时间/玩家位置/事件触发）
- 对话系统（tree 或 freeform + LLM？）
- 同伴跟随机制（已留下接口 I11 背负乘务员）
- NPC 对玩家行为的情绪/态度变化
**代码位置**: `data/modules/常暗之厢/l2_keeper.json` → `npc_profiles`

### 4. 时间系统 — TODO

设计文档已完成: `docs/superpowers/specs/2026-05-19-time-system-design.md`
**方案**: 两层架构 — 确定性世界时间 + TimeAgent (LLM sub-agent)
**待实现**:
- `ScenarioWorld` 加 `game_time`/`time_of_day`/`time_context`
- `TimeAgent` 类（flash 模型，每 2-3 回合触发）
- L3 `countdowns` 字段
- Entity `extra.time_cost`/`extra.time_gated`
- Prompt 时间上下文注入

### 5. 测试文件说明

当前开发和调试使用 `data/modules/常暗之厢/l*_test.json`：
- **l1_test.json**: 含「测试房间」场景（描述、氛围、感知项）
- **l2_test.json**: 含测试房间的 4 个 interaction (IT1-IT4)、1 个 AT、1 个结局 event (E_TEST_END)，外加原模组完整内容
- **l3_test.json**: 含测试场景 intent + 测试结局条件 + 原模组完整内容

`game_server.py` 和 `run_game.py` 的 `start_node` 已改为「测试房间」。正式发布时切回 `l*_player/keeper/designer.json` + `start_node="6号车厢"`。

---

## 已知缺口 (更新于 2026-05-19)

| # | 问题 | 状态 |
|---|------|------|
| G1 | Judge 需求检查仅 `flag:` 前缀 | FIXED — dependency_graph + runtime_state + parse_hard_requirement |
| G2 | `from_dict` 未更新 Entity 格式 | FIXED — _are_requirements_met 使用 parse_hard_requirement; runtime_state/dependency_graph 纳入 save/load 往返; 移除 dead code _parse_side_effects; Entity 添加 summary() |
| G3 | Escalation 递归无深度保护 | FIXED — MAX_ESCALATION_DEPTH=3 |
| G4 | `run_turn` 输出格式 | FIXED |
| G5 | 结局检测未接入 | FIXED — process_turn 检查所有 outcomes |
| G6 | Keeper 无单元测试 | DONE — game_loop_harness.py 覆盖 7 轮完整流程 (parse→judge→enrich→narrate)，每轮输出详细 prompt/response 日志

## 优化待办

| # | 问题 | 说明 |
|---|------|------|
| O1 | Step 4 Escalation 每回合 LLM 调用 | **当前焦点** — 见 `keeper.py:154` TODO 注释。计划重新设计 escalation 触发机制，改无条件 LLM 评估为启发式/惰性触发 |
| O2 | Step 6 Memory 压缩阻塞 LLM 调用 | 见 `keeper.py:176` TODO 注释 |
| O3 | Move 限制条件未强制执行 | 见 `keeper.py:83-90` TODO 注释 |

## 架构已知问题 & 计划

| # | 问题 | 处置 |
|---|------|------|
| A1 | ScenarioWorld 职责边界模糊化（God object 趋势） | 后续加入新系统（时间/NPC）时拆分为组合模式 |
| A2 | Author ModulePatch 注入无校验 | 与 O1 一起在 escalation 重设计中解决 |
| A3 | 离线管线 requirement 语义一致性依赖生成质量 | 已有 fallback + 多轮渐进 + 人工审计对冲 |

---

## Pipeline 总览 (参考)

```
模组文档 (.docx)
    ↓
Step 1a: 结构化提取 → Step 1b: 精修模组 → chapters
    ↓
Step 2a: Interactions + scene_movements
Step 2b: Events + Auto-triggers (并行)
Step 2c: L1 + L3 (并行)
    ↓
Step 2.5: NPC 行为描述
Step 3a: 去重 + 冲突 + 结局验证
    ↓
组装 L2 → Step 3b: 交叉核对
    ↓
Step 3.5: 依赖图 + Phase 1: 风格预判 (并行)
    ↓
Phase 2: 标准化 (@标记化)
    ↓
最终验证 + 保存 L1/L2/L3 JSON
```

总 LLM 调用: **13 次**

## 特殊标记

| 标记 | 含义 |
|------|------|
| `##GRADED##` | 实际结果在 graded_result 中 |
| `##END_名称:简述##` | 触发游戏结局 |
| `@函数名(参数=值)` | 运行时解析为 side_effect 实例（5种） |
