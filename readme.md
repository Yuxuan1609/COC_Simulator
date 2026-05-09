# TRPG 调查员助手

基于 LLM 的 TRPG（桌上角色扮演游戏）KP 助手，以《常暗之厢》模组为测试用例，实现从玩家输入到沉浸式叙事生成的完整调用链。

## 项目结构

```
.
├── data/
│   ├── abstract.txt                    # 模组背景设定（供叙事参考）
│   ├── occupations.json                # COC 7th 标准职业数据
│   ├── templates/                      # JSON 格式模板
│   │   ├── scene.json
│   │   └── event.json
│   └── output/                         # 解析后的模组数据
│       ├── scene_output.json           # 原始场景解析
│       ├── res_event.json              # 原始事件解析
│       ├── scene_output_resolved.json  # 需求匹配后的场景
│       ├── scene_output_resolved_revised.json  # 交叉验证修订后的场景
│       ├── res_event_resolved_revised.json     # 交叉验证修订后的事件
│       └── summary.txt                 # 模组概述
├── src/
│   ├── scenario_core.py                # 数据类、有向图、世界状态、记忆管理
│   ├── llm.py                          # DeepSeek API 封装
│   ├── parsers.py                      # 从模组文档解析场景和事件
│   ├── pipeline.py                     # 后处理管线（需求匹配、交叉验证、文学性扩充）
│   ├── trpg_display.py                 # Notebook UI 显示组件
│   ├── utils.py                        # 文档解析、Token 估算、掷骰
│   └── investigator/                   # COC 7th 调查员车卡系统
│       ├── __init__.py                 # 公开 API
│       ├── models.py                   # 数据类（Stats, Skill, Investigator 等）
│       ├── rules.py                    # COC 7th 规则引擎（纯函数）
│       └── serialization.py            # JSON 序列化 / 反序列化
├── frontend/                           # 车卡前端页面
│   ├── character.html                  # 5 步车卡向导
│   ├── character.css                   # COC 1920s 美学风格
│   └── character.js                    # 车卡交互逻辑
├── notebooks/
│   └── notebook_simplified.ipynb       # 主游戏循环（导入 src/ 模块）
├── docs/
│   └── superpowers/
│       ├── specs/                      # 设计文档
│       └── plans/                      # 实现计划
└── logs/                               # Prompt 日志（每次运行生成）
```

## 核心模块

### `scenario_core.py`

纯 Python 数据模块，不依赖 LLM 或 UI。

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Interaction`（可执行动作）、`GameEvent`（不可逆事件）、`Requirement`（前置条件）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态管理器 —— 当前位置、已触发事件、已完成交互、世界标记、记忆管理
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪
- **RequirementResolver**：前置条件检查
- **SkillSystem**：技能鉴定（当前为占位实现）

### 主游戏循环（Notebook）

三阶段 LLM 调用链：

1. **动作解析**（`build_action_prompt`）—— 基于场景 JSON 和玩家输入，让 LLM 判断意图（移动/交互/搜索等），支持多动作识别
2. **事件判定**（`build_event_prompt`）—— 独立判断哪些不可逆事件的触发条件被满足
3. **叙事生成**（`build_narrative_prompt`）—— 综合所有结果生成沉浸式 KP 叙事

阶段 1 和 2 并行调用。每次交互后通过 LLM 更新场景描述和背景设定（世界更新机制）。

### Pipeline（离线处理）

`parsers.py` → `pipeline.py` 的数据处理链：

1. 从 Word/PDF 模组文档解析场景和事件
2. 结构化需求匹配（requirement 字段精确匹配）
3. 交叉验证与修订（合理性优先）
4. 文学性扩充（功能性描述 → 沉浸式恐怖叙事）

### `src/investigator/` — COC 7th 调查员车卡系统

基于《克苏鲁的呼唤》第 7 版规则书，从旧 `Player` 桩类重构而来。完全解耦，通过 JSON 文件与游戏循环交互。

- **`models.py`**：数据类 —— `Stats`（8 项核心属性 + LUCK）、`DerivedStats`（HP/MP/SAN/MOV/DB/BUILD/DODGE）、`Skill`（45 项 COC 标准技能）、`Occupation`（职业定义）、`Weapon`（武器）、`Investigator`（主类，替代旧 `Player`）
- **`rules.py`**：纯函数规则引擎 —— 掷骰生成、衍生属性计算、技能点分配、年龄修正、信用评级、战斗基础
- **`serialization.py`**：JSON 序列化/反序列化 —— `to_json` / `from_json` / `to_dict` / `from_dict`
- **`utils.py`**：新增 `roll_dice()` / `roll_d6()` 公用掷骰函数，供车卡和主循环共享

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
world.set_player(inv)  # 或 world.load_player(path)
    ↓
主游戏循环（notebook_simplified.ipynb）
```

## 环境配置

```bash
pip install openai python-docx PyPDF2 ipython
```

设置 DeepSeek API Key：

```bash
export DEEPSEEK_API_KEY="your-key"
```

## 运行

在 Jupyter 中打开 `notebooks/notebook_simplified.ipynb`，按顺序执行所有 Cell。主循环启动后可直接输入玩家行动。

### 调试命令

| 命令 | 作用 |
|------|------|
| `/scene` | 查看当前场景完整信息 |
| `/info` | 查看结构化 JSON 状态 |
| `/events` | 查看已触发事件 |
| `/flags` | 查看世界标记 |
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
DirectedGraph → ScenarioWorld → LLM 调用链 → 沉浸式叙事
```
