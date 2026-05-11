# TRPG 调查员助手

基于 LLM 的 TRPG（桌上角色扮演游戏）KP 助手，以《常暗之厢》模组为测试用例，实现从玩家输入到沉浸式叙事生成的完整调用链。COC 7th 规则。

## 项目结构

```
.
├── data/
│   ├── abstract.txt                         # 模组背景设定（供叙事参考）
│   ├── occupations.json                     # COC 7th 标准职业数据
│   ├── skill_checks.json                    # COC 7th 45 项技能定义（名称、关联属性、基础值、分类）
│   ├── templates/
│   │   ├── scene.json                       # 场景 JSON 模板
│   │   └── event.json                       # 事件 JSON 模板
│   └── output/
│       ├── scene_output.json                # 原始场景解析
│       ├── res_event.json                   # 原始事件解析
│       ├── scene_output_resolved.json       # 需求匹配后的场景
│       ├── scene_output_resolved_revised.json # 交叉验证修订后的场景
│       └── res_event_resolved_revised.json  # 交叉验证修订后的事件
├── src/
│   ├── scenario_core.py                     # 数据类、有向图、世界状态、记忆管理
│   ├── llm.py                               # DeepSeek API 封装（可配置模型、思考模式）
│   ├── parsers.py                           # 从模组文档解析场景和事件
│   ├── pipeline.py                          # 后处理管线（需求匹配、交叉验证、文学性扩充）
│   ├── trpg_display.py                      # Notebook UI 显示组件
│   ├── utils.py                             # 文件解析、Token 估算、掷骰、技能定义加载
│   ├── prompts.py                           # LLM Prompt 构建器 + 叙事输出解析
│   ├── game_loop.py                         # 主循环：动作执行 + LLM 调用链编排 + 技能闸门
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
│   └── notebook_simplified.ipynb            # 主游戏循环（导入 src/ 模块）
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

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Interaction`（可执行动作）、`GameEvent`（不可逆事件）、`Requirement`（前置条件）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态管理器 —— 当前位置、已触发事件、已完成交互、世界标记、记忆管理
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪（仅记录简要结果，不记录完整叙事）
- **RequirementResolver**：前置条件检查

### `prompts.py`

Prompt 构建器 + 叙事输出解析。所有 `build_*` 函数只构造 prompt 字符串。`parse_narrative_output()` 按 `结果 / 沉浸式叙事` 两部分拆解 LLM 输出。`log_skill_result()` 将技能检定写入日志。

### `game_loop.py` — 主游戏循环

三阶段 LLM 调用链 + 技能闸门：

1. **动作解析** — 基于场景 JSON 和玩家输入，LLM 判断意图（move/interact/search），支持多动作识别
2. **事件判定** — 独立判断哪些不可逆事件的触发条件被满足
3. **叙事生成** — 输出拆解为简要结果（记录到 memory）+ 沉浸式叙事（显示用）

阶段 1 和 2 并行调用。每个动作执行前经过统一闸门（condition 检查 + COC 7th D100 技能检定），闸门失败则跳过该动作并继续执行后续动作。动作世界更新和事件世界更新仅在实际执行/触发后发生。

### Pipeline（离线处理）

`parsers.py` → `pipeline.py` 的数据处理链：

1. 从 Word/PDF 模组文档解析场景和事件
2. 结构化需求匹配（requirement 字段精确匹配）
3. 交叉验证与修订（合理性优先）
4. 文学性扩充（功能性描述 → 沉浸式恐怖叙事）

### `src/investigator/` — COC 7th 调查员车卡系统

基于《克苏鲁的呼唤》第 7 版规则书。完全解耦，通过 JSON 文件与游戏循环交互。

- **`models.py`**：数据类 —— `Stats`（8 项核心属性 + LUCK）、`DerivedStats`、`Skill`（45 项 COC 标准技能）、`Occupation`、`Weapon`、`Investigator`（主类）。`Investigator` 集成 `check_skill()` / `check_skills()` COC 7th D100 检定，`combat_check()` / `damage_roll()` 预留战斗接口
- **`rules.py`**：纯函数规则引擎 —— 掷骰生成、衍生属性计算、技能点分配、年龄修正、信用评级
- **`serialization.py`**：JSON 序列化/反序列化
- **`utils.py`**：`roll_dice()` / `roll_d6()` 公用掷骰函数，`load_skill_checks()` 加载技能定义

### 前端车卡（`frontend/`）

纯静态 HTML/CSS/JS，无框架依赖。5 步向导创建调查员后导出 JSON：

1. 基本信息（姓名、年龄、性别、外貌）
2. 属性生成（掷骰/手动，实时预览衍生属性）
3. 职业与技能（职业选择、技能点交互式分配）
4. 战斗与装备（武器编辑、随身物品）
5. 预览 & 导出 JSON

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

## 运行

在 Jupyter 中打开 `notebooks/notebook_simplified.ipynb`，按顺序执行所有 Cell。主循环启动后可直接输入玩家行动。

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
| `/help` | 帮助 |
| `exit` / `quit` | 退出游戏 |

## 数据流向

```
模组文档 (.docx/.pdf)
    ↓ parsers.py
scene_output.json + res_event.json
    ↓ pipeline.py (resolve → validate → expand)
scene_output_resolved_revised.json + res_event_resolved_revised.json
    ↓ notebook
DirectedGraph → ScenarioWorld → LLM 调用链 + COC 7th 技能闸门 → 拆分叙事输出
```

## 核心 LLM 调用

`call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort)`

- `model`: 模型名称（默认 `deepseek-v4-pro`）
- `thinking`: 思考模式开关（默认 True）
- `reasoning_effort`: 推理强度 `"low"/"medium"/"high"`（默认 `"high"`）
- `json_mode=True`：结构化判定（temperature=0.2）；`json_mode=False`：叙事生成（temperature=0.7）
