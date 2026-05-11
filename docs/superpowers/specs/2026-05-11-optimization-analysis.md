# 项目后续优化分析（设计侧重）

**日期**: 2026-05-11  
**范围**: 架构设计层面，不涉及具体实现细节

---

## 一、架构层

### 1. 游戏循环显式状态机化

**现状**: `handle_user_input` 内含 7 个阶段，通过顺序代码块隐式编排。阶段间数据传递依赖局部变量（`action_results`、`events_result`），异常处理分散在各阶段 try/except 中。

**优化方向**: 将 7 个阶段抽象为显式 Pipeline，每个阶段是独立可测试的单元：

```
Pipeline = [
    ActionParseStage,
    EventJudgeStage,      # 与 ActionParse 并行
    SceneActionStage,     # 含 skill gate
    ActionWorldUpdateStage,
    MoveActionStage,
    EventExecutionStage,
    EventWorldUpdateStage,
    NarrativeStage,       # 含输出解析
]
```

每个 Stage 接收 `PipelineContext`（world, user_input, 前序阶段输出），返回 `StageResult`。阶段失败不中断整条管线（除了致命错误）。

**收益**: 新增阶段（如战斗阶段、SAN 检定阶段）只需实现 Stage 接口并插入管线。调试时可以单独启用/禁用阶段。

### 2. 事件触发：确定性 + LLM 混合

**现状**: 事件触发完全依赖 LLM（`build_event_prompt`）。交互系统已实现确定性的可触发/不可触发分类（`_categorize_interactions`），事件系统应该对标。

**优化方向**: 事件也做确定性的条件检查（`RequirementResolver` 已就绪），LLM 只负责判断"玩家输入中的隐含触发意图"。最终触发 = 条件满足（确定性）AND 玩家意图匹配（LLM）。

**收益**: 减少 LLM 幻觉导致的误触发/漏触发，事件触发逻辑可审计。

### 3. 配置系统集中化

**现状**: 配置散落在各处 —— 模型名在 `llm.py` 函数参数默认值，记忆压缩阈值在 `scenario_core.py`，技能基础值在 `rules.py` 和 `skill_checks.json` 两处。

**优化方向**: 设计 `GameConfig` 数据类，集中管理：

```
GameConfig
├── LLMConfig (model, temperature, max_tokens, thinking, reasoning_effort)
├── RuleConfig (skill_base_values, difficulty thresholds, SAN loss tables)
├── MemoryConfig (max_raw_records, compression_threshold, context_window)
└── ScenarioConfig (start_node, background_path, data_paths)
```

从 YAML/JSON 文件加载，环境变量覆盖。`skill_checks.json` 和 `rules.py:SKILL_BASE_VALUES` 合并为一处数据源。

---

## 二、数据模型层

### 4. 交互结果模型丰富化

**现状**: `execute_interaction` 返回 `(bool, str)`。交互的副作用（获得物品、属性变化、标记更新）需要调用方手动处理。

**优化方向**: 设计 `ActionResult` 数据类：

```python
@dataclass
class ActionResult:
    success: bool
    message: str
    side_effects: list[SideEffect]  # ItemGain, StatChange, FlagSet, EventTrigger
    skill_checks: list[SkillCheckResult]
```

交互 JSON 的 `result` 字段可以声明期望的副作用（如 `{"type": "item_gain", "item": "手电筒"}`），游戏循环自动执行。

**收益**: 复杂谜题（获得钥匙 → 打开门 → 触发事件）可以声明式编写，不需要代码。

### 5. 难度等级与场景数据打通

**现状**: `check_skill(difficulty)` 预留了 hard/extreme 但未被 prompt 或场景数据使用。每个 `Interaction` 的 `trigger` 字段是自然语言描述。

**优化方向**: `Interaction` 增加 `difficulty` 字段和 `skill_name` 字段：

```json
{
  "name": "仔细搜查桌面",
  "type": "调查",
  "skill_name": "侦查",
  "difficulty": "regular",
  "trigger": "在桌面上寻找线索",
  "result": "发现一张褪色的纸条"
}
```

LLM 在动作解析时直接引用结构化字段，不再从自然语言 trigger 中推测技能名和难度。

**收益**: 减少 LLM 推测误差，难度数据可以被后续的难度曲线分析消费。

### 6. 世界状态可序列化/反序列化

**现状**: `ScenarioWorld` 的状态（位置、已触发事件、已交互列表、flags、memory）存在于内存中，无法存档。

**优化方向**: `ScenarioWorld` 实现 `to_dict()` / `from_dict()`，支持存档/读档。记忆压缩摘要可序列化。

**收益**: 存档功能、多分支回溯、调试重现。

---

## 三、记忆与叙事层

### 7. 记忆的多粒度摘要

**现状**: `MemoryManager` 压缩时将所有旧记录送入 LLM 生成一段摘要。随着游戏进程增长，摘要本身也会膨胀。

**优化方向**: 分层摘要 —— 近期（5 条原始记录）、中期（场景级摘要，按位置聚合）、远期（模组级摘要，核心情节线）。压缩时只合并近期到中期，中期到远期以更低频率触发。

**收益**: 长期游戏中记忆上下文保持紧凑，减少 LLM token 消耗。

### 8. 叙事输出结构化再进一步

**现状**: 叙事输出已拆分为 `结果` + `沉浸式叙事`。但仍然依赖 LLM 遵循格式约定。

**优化方向**: 叙事生成也走 `json_mode=True`，返回结构化 JSON：

```json
{
  "brief": "推开6号车厢门",
  "narrative": "锈蚀的车门...",
  "mood": "紧张",
  "npc_reactions": [],
  "hints": ["车厢深处有微弱的呼吸声"]
}
```

解析不再依赖文本分割，字段语义明确。`hints` 可以自动注入到下一次的场景上下文中。

---

## 四、可扩展性

### 9. 模组数据与代码分离

**现状**: 模组数据以 JSON 文件形式存在于 `data/output/`，是解析器的一次性产物。场景名（"6号车厢"）硬编码在 notebook 中。

**优化方向**: 设计 `ScenarioLoader` 接口，支持从目录加载模组。每个模组是独立目录：

```
scenarios/
  └── 常暗之厢/
      ├── source.txt          # 原始模组文本
      ├── scenes.json         # 解析后的场景
      ├── events.json         # 解析后的事件
      ├── background.txt      # 背景设定
      └── meta.json           # 模组元信息
```

Notebook 选择模组目录即可启动，不再硬编码场景名。

**收益**: 同一套引擎运行不同模组。社区可贡献模组数据。

### 10. 战斗系统集成点完善

**现状**: `combat_check` / `damage_roll` 为 `NotImplementedError` stub。武器数据、伤害公式已建模但未消费。

**优化方向**: 设计战斗回合管线，插入到游戏主循环的阶段间：

```
SceneActionStage → [CombatRoundStage?] → ActionWorldUpdateStage
```

触发条件：任何 action 或事件标记 `combat: true` 时激活。战斗阶段消费 `Weapon.skill_name`、`Weapon.damage`、`DerivedStats.DB`、`DerivedStats.DODGE`。

**收益**: 战斗是 COC 核心玩法一环，架构预留已就绪，实现路径清晰。

---

## 优先级建议

| 优先级 | 优化项 | 理由 |
|--------|--------|------|
| **高** | 配置系统集中化 | 消除当前最分散的技术债，后续所有优化受益 |
| **高** | 交互结果模型丰富化 | 解锁声明式谜题设计，减少硬编码 |
| **中** | 事件触发混合模式 | 提高游戏逻辑可靠性 |
| **中** | 难度等级与场景打通 | 提升技能检定精度 |
| **中** | 世界状态可序列化 | 存档刚需，且调试价值高 |
| **低** | 游戏循环状态机化 | 重构成本高，当前规模尚可维护 |
| **低** | 记忆多粒度摘要 | 当前游戏长度尚不需要 |
| **低** | 模组数据分离 | 单模组够用，多模组后再做 |
| **预留** | 战斗系统 | 架构已预留，需求明确后再实现 |
