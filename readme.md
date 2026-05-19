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
│   ├── server.py                            # 本地服务器 + LLM 描述生成 API
│   ├── character.html                       # 5 步车卡向导
│   ├── character.css                        # COC 1920s 美学风格
│   └── character.js                         # 车卡交互逻辑（含 /llm 触发）
├── run_pipeline.py                          # 管线 CLI 入口（配置向导 + 手动/自动模式）
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
| Keeper | L2 | 回合编配：parse → judge → enrich ∥ intent detect → curate | `src/game/agents/keeper.py` |
| Narrator | L1 | 唯一面向玩家，生成沉浸式叙事 | `src/game/agents/narrator.py` |
| Author | L3 | 两级响应：Patch（填缺口）/ StructuralEdit（触发补充管线），WR0 独立可配 | `src/game/agents/author.py` |
| IntentDetector | — | Parse 命中 other 时并行检测是否存在实际叙事意图 | `src/game/intent_detector.py` |

入口：`init_game()` 加载所有 JSON + 初始化三 Agent，`run_turn()` 驱动每回合。
仅 `keeper.world` 暴露 ScenarioWorld，L3 数据内聚在 Author。

设计文档：
- Multi-Agent: `docs/superpowers/specs/2026-05-16-game-loop-multi-agent-design.md`
- Escalation 重设计: `docs/superpowers/specs/2026-05-19-escalation-redesign.md`

测试：
- `tests/game_loop_harness.py` — 7 轮真实 LLM，日志到 `data/debug/test_harness/`
- `tests/test_author_flow.py` + `tests/test_intent_detector.py` — 11 个单元测试（全 mock）
- `tests/test_escalation_harness.py` — 4 个 case（正常/flavor/Patch/Reject），Author 日志到 `data/debug/test_escalation/`

> **注意**：当前使用 `data/modules/常暗之厢/l*_test.json`，`start_node` 已切到「测试房间」。正式需切回正式 JSON。

### 已知缺口

| # | 问题 | 状态 |
|---|------|------|
| G1 | Judge 需求检查仅支持 `flag:` 前缀 | FIXED — dependency_graph + runtime_state + parse_hard_requirement |
| G2 | `DirectedGraph.from_dict` 未更新 Entity 格式 | FIXED — _are_requirements_met 使用 parse_hard_requirement；runtime_state/dependency_graph 纳入 save/load；dead code 移除；Entity 添加 summary() |
| G3 | Escalation 递归无深度保护 | FIXED — MAX_ESCALATION_DEPTH=3 + _process_deterministic_only fallback |
| G4 | `run_turn` 输出格式 | FIXED |
| G5 | `has_ending()` 入口点集成 | FIXED — process_turn 中已检查所有 outcomes |
| G6 | Keeper 无单元测试 | DONE — game_loop_harness.py 覆盖 7 轮完整流程，每轮输出详细 prompt/response 日志 |

### 待优化

| # | 问题 | 说明 |
|---|------|------|
| O1 | Step 4 Escalation 每回合 LLM 调用 | 设计中 — 改为 Parse other → IntentDetect 按需触发。设计文档：`docs/superpowers/specs/2026-05-19-escalation-redesign.md` |
| O2 | Step 6 Memory 压缩阻塞 LLM 调用 | 见 `keeper.py:176` TODO 注释 |
| O3 | Move 限制条件未强制执行 | 见 `keeper.py:83-90` TODO 注释 |

## 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| 作者介入机制 (Escalation) | 实现完成 | Parse other → IntentDetect(并行) → Author (Patch/StructuralEdit/Reject) → 补充管线。O1 已解决。设计文档：`docs/superpowers/specs/2026-05-19-escalation-redesign.md` |
| 战斗系统 | TODO | COC 7th 回合制战斗。需实现：进入战斗判定、先攻→行动→伤害流程、敌人 AI。skill check 已有 D100 能力 |
| NPC / 同伴系统 | TODO | NPC 主动行为、对话系统、同伴跟随。当前仅被动响应 interaction。L2 已有 npc_profiles 预留 |
| 时间系统 | 设计完成 | 设计文档：`docs/superpowers/specs/2026-05-19-time-system-design.md`。两层架构：确定性时间 + TimeAgent (LLM sub-agent)。待实现 |

## Web 前端

```bash
python frontend/game_server.py                    # 启动游戏 Web 服务器
python frontend/game_server.py --port 9000        # 自定义端口
```

浏览器打开 `http://localhost:8080/game.html`。左侧面板显示调查员状态和场景信息，右侧显示结果/叙事。支持全部调试命令（`/scene` `/char` `/flags` `/do` `/trigger` `/spawn` `/save` `/load` 等）。

也可以通过 CLI 运行：`python run_game.py`（需要 IPython 环境）。

## 运行

### 管线 CLI（模组解析）

将 `.docx`/`.pdf`/`.txt` 模组文档转换为 L1/L2/L3 JSON，替代 Jupyter notebook 手动执行。

```bash
# 交互式向导（手动步进，每步可暂停/重试/编辑中间结果/改模型配置）
python run_pipeline.py

# 自动全流程
python run_pipeline.py --auto --docx "常暗之厢.docx" --module 常暗之厢

# 从配置文件运行
python run_pipeline.py --config config.json

# 断点续跑
python run_pipeline.py --config config.json --start-from step_3a
```

详细配置见 `run_pipeline.py` 顶部的 `PipelineConfig` dataclass（18 个可配置字段，含合法值注释）。

### 前端车卡（调查员创建）

一键启动（Windows 用户双击 `.bat` 文件即可）：

```bash
# 方式 1：一键启动（自动打开浏览器）
启动角色卡.bat

# 方式 2：手动启动服务器
python frontend/server.py
# → 浏览器打开 http://localhost:8080/character.html
```

车卡页面内置 LLM 辅助功能：在"外貌描述"或"个人描述"输入关键词后加 `/llm` 即可自动生成 150 字以内的描述。

### 游戏循环

Jupyter 交互：`notebooks/notebook_simplified.ipynb`。
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
- `reasoning_effort`: 推理强度 `"low"/"medium"/"high"/"max"`（默认 `"high"`）
- `json_mode=True`：结构化判定（temperature=0.2）；`json_mode=False`：叙事生成（temperature=0.7）

## 公开发行打包

面向非程序员最终用户的 `.exe` 分发方案。统一入口 Web 界面，集成所有功能。

### 架构

```
单一 exe (launcher.py)
  → 启动本地 HTTP Server (localhost:8080)
  → 自动打开浏览器到入口页面
  → 提供所有子功能:
      ├─ /game.html         游戏循环
      ├─ /character.html    调查员创建 (5步车卡向导)
      ├─ /json-editor.html  JSON 编辑器
      ├─ 未来: /pipeline    模组解析
      └─ 未来: /library     武器/敌人库管理
```

### 推荐方案：PyInstaller

生态最成熟，一条命令出包，无需 C 编译器。

```bash
pip install pyinstaller

pyinstaller -F --noconsole --name "TRPG助手" \
  --add-data "frontend;frontend" \
  --add-data "data;data" \
  --add-data "src;src" \
  --add-data "investigator;investigator" \
  --add-data "logs;logs" \
  --hidden-import openai \
  --hidden-import IPython \
  frontend/launcher.py
```

### 素材文件

图片/视频/音频放 `frontend/assets/` 下，PyInstaller `--add-data` 打包整个目录。前端用相对路径引用。

大素材（视频）建议用 `--onedir` 模式（文件夹分发），方便替换素材无需重新打包。

### 注意事项

- **API Key**：`.env` 不打包，首次启动引导用户在 Web 界面配置
- **杀软误报**：`--onedir`（文件夹分发）误报率低于 `--onefile`
- **体积**：纯代码 ~60 MB，含视频素材可能更大
- **跨平台**：Windows/macOS/Linux 分别需在对应系统打包
- **Nuitka**：反编译难度更高但编译慢（几十分钟）、需 MSVC/GCC。当前阶段 PyInstaller 更实用
