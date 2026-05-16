# TRPG 调查员助手

基于 LLM 的 TRPG（桌上角色扮演游戏）KP 助手，以《常暗之厢》模组为测试用例，实现从玩家输入到沉浸式叙事生成的完整调用链。COC 7th 规则。

## 项目结构

```
.
├── data/
│   ├── abstract.txt                         # 模组背景设定（供叙事参考）
│   ├── occupations.json                     # COC 7th 标准职业数据
│   ├── skill_checks.json                    # COC 7th 45 项技能定义（名称、关联属性、基础值、分类）
│   ├── library/
│   │   ├── core/
│   │   │   ├── weapons.json                 # 核心武器库（10 件）
│   │   │   └── enemies.json                 # 核心敌人库（5 种神话生物/人类）
│   │   └── extensions/                      # 用户自定义武器/敌人扩展包
│   ├── templates/
│   │   ├── l1_template.json                 # L1 玩家可见层模板
│   │   ├── l2_template.json                 # L2 KP 守秘人层模板
│   │   └── l3_template.json                 # L3 设计者层模板
│   ├── modules/
│   │   └── 常暗之厢/
│   │       ├── l1_player.json               # L1 玩家可见层（LLM 生成）
│   │       ├── l2_keeper.json               # L2 KP 守秘人层（LLM 生成，游戏循环直接消费）
│   │       └── l3_designer.json             # L3 设计者层（LLM 生成）
│   └── output/
│       └── archive/                         # 旧 pipeline 输出存档
├── src/
│   ├── scenario_core.py                     # 数据类、有向图、世界状态、记忆管理、Entity/@markup
│   ├── llm.py                               # DeepSeek API 封装（可配置模型、思考模式）
│   ├── trpg_display.py                      # Notebook UI 显示组件
│   ├── utils.py                             # 文件解析、Token 估算、掷骰、技能定义加载
│   ├── prompts.py                           # LLM Prompt 构建器（Keeper/Narrator/Author 各自 prompt）
│   ├── game_loop.py                         # 多 Agent 入口：init_game() + run_turn()
│   ├── game/                                # Multi-Agent 游戏循环
│   │   ├── messages.py                      #   8 个消息 dataclass（NarratorBrief, EscalationRequest 等）
│   │   ├── judge.py                         #   确定性闸门（需求 + 技能检定 + @markup + ##GRADED##）
│   │   ├── curator.py                       #   策展器：outcomes → NarratorBrief
│   │   ├── escalation.py                    #   可配置升级策略（LLM 评估维度 + 自然语言规则）
│   │   └── agents/
│   │       ├── keeper.py                    #   KP 守秘人（回合编配：parse → judge → enrich → curate）
│   │       ├── narrator.py                  #   叙事者（唯一面向玩家，L1 + NarratorBrief → 叙事）
│   │       └── author.py                    #   作者（L3 + EscalationRequest → ModulePatch）
│   ├── library/                             # 武器/敌人资源库
│   │   ├── weapons.py                       #   LibraryWeapon + WeaponLibrary
│   │   ├── enemies.py                       #   LibraryEnemy + EnemyLibrary
│   │   ├── judgment.py                      #   双层判定引擎（T1 确定性 + T2 LLM 增强）
│   │   └── injector.py                      #   内容注入（离线预填充 + 运行时动态注入）
│   ├── module_designer/                     # 三层信息引擎
│   │   ├── l1_player.py                     #   L1 玩家可见层数据模型
│   │   ├── l2_keeper.py                     #   L2 KP 守秘人层数据模型 (含 AutoTrigger)
│   │   ├── l3_designer.py                   #   L3 设计者层数据模型
│   │   ├── layered_schema.py                #   JSON Schema 定义 + 三层验证
│   │   ├── layered_parser.py                #   渐进式解析 (prompt builders + system prompts)
│   │   ├── layered_pipeline.py              #   管线编排 (并行 + retry/fallback + 最终验证)
│   │   └── dependency_graph.py              #   依赖有向图 (构建 + 循环检测)
│   └── investigator/                        # COC 7th 调查员车卡系统
│       ├── __init__.py                      # 公开 API
│       ├── models.py                        # 数据类 + 技能检定 + 战斗预留
│       ├── rules.py                         # COC 7th 规则引擎（纯函数）
│       └── serialization.py                 # JSON 序列化 / 反序列化
├── frontend/                                # 车卡前端页面
│   ├── character.html                       # 5 步车卡向导
│   ├── character.css                        # COC 1920s 美学风格
│   └── character.js                         # 车卡交互逻辑
├── notebooks/
│   ├── notebook_simplified.ipynb            # 主游戏循环（导入 src/ 模块）
│   └── parser_test.ipynb                    # 管线驱动与测试
├── docs/
│   └── superpowers/
│       ├── specs/                           # 设计文档
│       └── plans/                           # 实现计划
├── logs/                                    # Prompt 日志（每次运行生成，含技能检定记录）
└── .env                                     # DeepSeek API Key（不纳入版本控制）
```

## 核心模块

### `scenario_core.py`

纯 Python 数据模块，不依赖 LLM 或 UI。

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Interaction`（可执行动作）、`GameEvent`（不可逆事件）、`Requirement`（前置条件）、`ActionResult`（统一返回类型）
- **Side Effects**：`ItemGain`（获得物品）、`StatChange`（属性/状态变化，含 narrative 字段）、`SpawnEnemy`（生成敌人遭遇）、`GrantWeapon`（授予标准化武器）、`NPCStateChange`（NPC 状态变化）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态管理器 —— 当前位置、已触发事件、已完成交互、世界标记、NPC 运行时状态、记忆管理
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪

### `src/library/` — 武器/敌人资源库

独立包，零外部依赖。提供结构化武器和敌人数据、双层判定引擎和内容注入。

- **WeaponLibrary / EnemyLibrary**：加载核心库 + 用户扩展 JSON，支持按年代/稀有度/类型/关键词搜索
- **JudgmentEngine**：T1 确定性检定（D100 技能检定、伤害公式掷骰、SAN 损失计算）+ T2 LLM 增强上下文构建（可开关）
- **ContentInjector**：离线注入（模组构建时根据 L3 危险等级自动填充 encounter/weapon 槽位）+ 运行时动态注入

### `src/module_designer/` — 三层信息引擎

- **L1 玩家可见层**（`SceneL1`）：场景描述、氛围、情绪基调、无条件可感知元素、NPC 外貌
- **L2 KP 守秘人层**（`SceneL2`）：场景描述、通行路径、interactions/auto_triggers/events（统称 entity）、NPC 完整档案、依赖图、Phase 1 约束
- **L3 设计者层**（`L3Designer`）：模组元信息、世界规则、场景设计意图、结局条件、基调约束、核心驱动力

所有数据类支持 JSON 往返序列化。层间通过 ID 引用关联（L1 → L2 interaction name, L2 → library weapon/enemy name, L3 → NPC/events）。

**渐进式解析流程**（`layered_parser.py` + `layered_pipeline.py`）：

1. **Step 1a/1b** — 结构化提取（meta + scenes + characters）+ 精修模组 → chapters dict
2. **Step 2a** — interactions + scene_movements（based_on 留空）
3. **Step 2b/2c** — events + auto_triggers + L1 + L3 并行生成
4. **Step 3a** — 去重 + 冲突解决 + 结局验证
5. **组装 L2 结构**（`_assemble_l2`）→ 按场景分组 entity + 注入通行路径和描述
6. **Step 3b** — L1 ↔ L2 ↔ L3 交叉核对
7. **Step 3.5 + Phase 1 并行** — 依赖图构建 + 风格预判（enemy/weapon 类型和数量范围）
8. **Phase 2** — 精简标准化：type 对齐标准技能名，side_effects → `@函数(参数)` 标记语法

每步含 `_with_fallback` 保底策略（重试 → 降级输出），总计 **12 次 LLM 调用**。

### `prompts.py`

Prompt 构建器 + 叙事输出解析。`parse_narrative_output()` 按 `结果 / 沉浸式叙事` 两部分拆解 LLM 输出。`log_skill_result()` 将技能检定写入日志。`_build_l1l3_context()` 从 L1/L3 数据构建基调约束和场景感知上下文。

### `game_loop.py` — 主游戏循环

三阶段 LLM 调用链 + 技能闸门 + 调试命令：

1. **动作解析** — 基于场景 JSON 和玩家输入，LLM 判断意图（move/interact/search），支持多动作识别
2. **事件判定** — 独立判断哪些不可逆事件的触发条件被满足
3. **叙事生成** — 输出拆解为简要结果（记录到 memory）+ 沉浸式叙事（显示用），融入 L1/L3 语境
3.5. **偏离检测**（预留）— 检测玩家行为是否偏离 L3 预期路径，触发运行时内容注入

阶段 1 和 2 并行调用。每个动作执行前经过统一闸门（condition 检查 + COC 7th D100 技能检定）。`@` 标记字符串由 `_parse_side_effect()` 在运行时解析为对应 dataclass 实例。

### `src/investigator/` — COC 7th 调查员车卡系统

基于《克苏鲁的呼唤》第 7 版规则书。完全解耦，通过 JSON 文件与游戏循环交互。

- **`models.py`**：数据类 —— `Stats`（8 项核心属性 + LUCK）、`DerivedStats`、`Skill`（45 项 COC 标准技能）、`Occupation`、`Weapon`、`Investigator`（主类）。`Investigator` 集成 `check_skill()` / `check_skills()` COC 7th D100 检定
- **`rules.py`**：纯函数规则引擎 —— 掷骰生成、衍生属性计算、技能点分配、年龄修正、信用评级
- **`serialization.py`**：JSON 序列化/反序列化

### 前端车卡（`frontend/`）

纯静态 HTML/CSS/JS，无框架依赖。5 步向导创建调查员后导出 JSON。

### 使用流程

```
frontend/character.html（浏览器）→ 导出 character.json
    ↓
from investigator import load_investigator
inv = load_investigator("character.json")
world.set_player(inv)
    ↓
主游戏循环（notebook_simplified.ipynb）
```

## 环境配置

```bash
pip install openai python-docx PyPDF2 ipython
```

在项目根目录创建 `.env` 文件（已纳入 .gitignore）：

```
DEEPSEEK_API_KEY=your-key
```

`src/llm.py` 启动时自动加载 `.env`，无需手动 export。

## Multi-Agent 游戏循环

2026-05-16 重构。3-Agent 架构替代单体 `handle_user_input()`：

| Agent | 层 | 职责 | 文件 |
|-------|----|------|------|
| Keeper | L2 | 回合编配：parse → judge → enrich → escalate → curate | `src/game/agents/keeper.py` |
| Narrator | L1 | 唯一面向玩家，生成沉浸式叙事 | `src/game/agents/narrator.py` |
| Author | L3 | 仅 KP 调用，按 L3 设计意图生成 ModulePatch | `src/game/agents/author.py` |

入口：`init_game()` 加载所有 JSON + 初始化三 Agent，`run_turn()` 驱动每回合。
仅 `keeper.world` 暴露 ScenarioWorld，L3 数据内聚在 Author。

设计文档：`docs/superpowers/specs/2026-05-16-game-loop-multi-agent-design.md`
测试 Harness：`tests/game_loop_harness.py`（15 案例，日志输出到 `data/debug/test_harness/`）

### 已知缺口

| # | 问题 | 状态 |
|---|------|------|
| G1 | Judge 需求检查仅支持 `flag:` 前缀，不支持 interaction/event 前置 | TODO |
| G2 | `DirectedGraph.from_dict` 未更新 Entity 格式 | TODO |
| G3 | Escalation 递归无深度保护 | TODO |
| G4 | `run_turn` 输出格式（`hasattr` 基本可用） | FIXED |
| G5 | `has_ending()` 已实现但入口点不检查 `##END_*` | TODO |
| G6 | Keeper.process_turn 无单元测试 | TODO |

## 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 战斗系统 | TODO | COC 7th 回合制战斗 |
| 同伴机制 | TODO | 复数调查员/同伴 NPC 的行动协同与 AI 行为 |

## 运行

管道测试：在 Jupyter 中打开 `notebooks/parser_test.ipynb`，按顺序执行所有 Cell。

主游戏循环：`notebooks/notebook_simplified.ipynb`。
测试 Harness：`cd tests && python game_loop_harness.py`（需 API Key，约 40-50 次 LLM 调用）。

### 调试命令

| 命令 | 作用 |
|------|------|
| `/scene` | 查看当前场景完整信息 |
| `/info` | 查看结构化 JSON 状态 |
| `/events` | 查看已触发事件 |
| `/flags` | 查看世界标记 |
| `/char` | 查看当前调查员角色卡 |
| `/do <动作名>` | 直接执行交互（跳过 LLM） |
| `/trigger <E1>` | 手动触发事件 |
| `/save <槽位>` | 临时存档 |
| `/load <槽位>` | 读档 |
| `/charsave` | 保存调查员长期存档 |
| `/charload` | 加载调查员长期存档 |
| `/spawn enemy <名称>` | 从敌人库生成敌人 |
| `/spawn weapon <名称>` | 从武器库分发武器 |
| `/inject [toggle\|status]` | 查看/切换运行时注入状态 |
| `/help` | 帮助 |
| `exit` / `quit` | 退出游戏 |

## 数据流向

```
┌─────────────────────────────────────────────────────┐
│  离线：渐进式解析管线（12 次 LLM 调用）                │
│                                                      │
│  source.docx                                         │
│      ↓ Step 1a+1b: 结构化提取 + 精修模组 (2 并行)     │
│  scenes + characters + chapters dict                 │
│      ↓ Step 2a: Interactions + scene_movements       │
│  interactions[{name,scene,type,result,side_effects}] │
│      ↓ Step 2b+2c: events+AT | L1+L3 (4 并行)       │
│  events + auto_triggers + l1_data + l3_data          │
│      ↓ Step 3a: 去重 + 冲突 + 结局验证                │
│      ↓ _assemble_l2: 场景分组 + 通行路径注入          │
│  l2_assembled {scenes, events, npc_profiles}         │
│      ↓ Step 3b: L1↔L2↔L3 交叉核对                    │
│      ↓ Step 3.5 ∥ Phase 1: 依赖图 + 风格预判 (2 并行) │
│  dependency_graph + phase1_constraints               │
│      ↓ Phase 2: type标准化 + side_effect @标记化      │
│  l1_player.json + l2_keeper.json + l3_designer.json  │
│      ↓ notebook                                      │
│  l2_keeper.json → DirectedGraph → ScenarioWorld      │
│      ↓ LLM 调用链 + L1/L3 感知叙事 + @标记解析         │
│  沉浸式叙事输出                                        │
└─────────────────────────────────────────────────────┘
```

## 最终输出格式

管线产出 3 个 JSON 文件。详细字段参考见 `docs/superpowers/specs/NEXT-SESSION.md`。

### L1 — 玩家可见层
`{ "场景中文名": { "description", "atmosphere", "mood", "perceptible", "ambient_hints", "npc_appearances" } }`

### L2 — KP 守秘人层（游戏循环直接消费）
`{ "scenes", "events", "npc_profiles", "dependency_graph", "_phase1" }`

Entity（interaction / auto_trigger / event）统一保留字段：`name`, `scene`, `type`, `result`, `side_effects`, `graded_result`。Side_effect 使用 `@函数(参数=值)` 标记语法，运行时解析为 dataclass 实例。

### L3 — 设计者层
`{ "module_meta", "world_rules", "scene_intents", "ending_conditions", "tone_constraints", "characters", "driving_force" }`

## 核心 LLM 调用

`call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort)`

- `model`: 模型名称（默认 `deepseek-v4-pro`）
- `thinking`: 思考模式开关（默认 True）
- `reasoning_effort`: 推理强度 `"low"/"medium"/"high"`（默认 `"high"`）
- `json_mode=True`：结构化判定（temperature=0.2）；`json_mode=False`：叙事生成（temperature=0.7）
