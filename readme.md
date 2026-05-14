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
│   │   ├── scene.json                       # 场景 JSON 模板（已有）
│   │   ├── event.json                       # 事件 JSON 模板（已有）
│   │   ├── l1_template.json                 # L1 玩家可见层模板（新增）
│   │   ├── l2_template.json                 # L2 KP 守秘人层模板 (含 auto_triggers)
│   │   └── l3_template.json                 # L3 设计者层模板 (已精简)
│   ├── modules/
│   │   └── 常暗之厢/
│   │       ├── l1_player.json               # L1 玩家可见层（LLM 生成）
│   │       ├── l2_keeper.json               # L2 KP 守秘人层（LLM 生成，游戏循环直接消费）
│   │       └── l3_designer.json             # L3 设计者层（LLM 生成）
│   └── output/
│       └── archive/                         # 旧 pipeline 输出存档
├── src/
│   ├── scenario_core.py                     # 数据类、有向图、世界状态、记忆管理
│   ├── llm.py                               # DeepSeek API 封装（可配置模型、思考模式）
│   ├── trpg_display.py                      # Notebook UI 显示组件
│   ├── utils.py                             # 文件解析、Token 估算、掷骰、技能定义加载
│   ├── prompts.py                           # LLM Prompt 构建器 + 叙事输出解析（L1/L3 感知）
│   ├── game_loop.py                         # 主循环：动作执行 + LLM 调用链编排 + /spawn 命令
│   ├── library/                             # 武器/敌人资源库（新增）
│   │   ├── weapons.py                       #   LibraryWeapon + WeaponLibrary
│   │   ├── enemies.py                       #   LibraryEnemy + EnemyLibrary
│   │   ├── judgment.py                      #   双层判定引擎（T1 确定性 + T2 LLM 增强）
│   │   └── injector.py                      #   内容注入（离线预填充 + 运行时动态注入）
│   ├── module_designer/                     # 三层信息引擎
│   │   ├── l1_player.py                     #   L1 玩家可见层数据模型
│   │   ├── l2_keeper.py                     #   L2 KP 守秘人层数据模型 (含 AutoTrigger)
│   │   ├── l3_designer.py                   #   L3 设计者层数据模型 (已精简)
│   │   ├── layered_schema.py                #   JSON Schema 定义 + 三层验证
│   │   ├── layered_parser.py                #   四步渐进式解析 (10 prompt builders + 保底)
│   │   └── layered_pipeline.py              #   管线编排 (并行 + retry/fallback + 最终验证)
│   ├── archive/                             # 已废弃模块
│   │   ├── parsers.py                       #   旧场景/事件解析器
│   │   └── pipeline.py                      #   旧后处理管线
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

- **数据类**：`Node`（场景节点）、`Edge`（连接边）、`Interaction`（可执行动作）、`GameEvent`（不可逆事件）、`Requirement`（前置条件）、`ActionResult`（统一返回类型）
- **Side Effects**：`FlagSet`（设置世界标记）、`ItemGain`（获得关键物品）、`StatChange`（属性变化）、`SpawnEnemy`（生成敌人遭遇）、`GrantItem`（授予武器/物品）、`NPCStateChange`（NPC 状态变化）
- **DirectedGraph**：管理所有场景节点、连接关系和全局事件
- **ScenarioWorld**：运行时状态管理器 —— 当前位置、已触发事件、已完成交互、世界标记、NPC 运行时状态、记忆管理
- **MemoryManager**：分层记忆 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪（仅记录简要结果，不记录完整叙事）
- **RequirementResolver**：前置条件检查

### `src/library/` — 武器/敌人资源库

独立包，零外部依赖。提供结构化武器和敌人数据、双层判定引擎和内容注入。

- **WeaponLibrary / EnemyLibrary**：加载核心库 + 用户扩展 JSON，支持按年代/稀有度/类型/关键词搜索
- **JudgmentEngine**：T1 确定性检定（D100 技能检定、伤害公式掷骰、SAN 损失计算）+ T2 LLM 增强上下文构建（可开关）
- **ContentInjector**：离线注入（模组构建时根据 L3 危险等级自动填充 encounter/weapon 槽位）+ 运行时动态注入（LLM 偏离触发时 spawn enemy / grant weapon）

### `src/module_designer/` — 三层信息引擎

- **L1 玩家可见层**（`SceneL1`）：入场叙事、氛围、情绪基调、无条件可感知元素、NPC 外貌
- **L2 KP 守秘人层**（`SceneL2`）：场景描述、可执行交互、敌人遭遇声明、场景武器、NPC 完整档案、auto_trigger 自动触发事件
- **L3 设计者层**（`L3Designer`）：模组元信息、世界规则、场景设计意图、结局条件、基调约束、核心驱动力

所有数据类支持 JSON 往返序列化（`to_dict` / `from_dict` + `load_*` / `save_*`）。层间通过 ID 引用关联（L1 → L2 interaction name, L2 → library weapon/enemy name, L3 → flags/events）。

**四步渐进式解析流程**（`layered_parser.py` + `layered_pipeline.py`）：
1. **Step 1** — 名称固化 + 精修模组：并行提取场景/NPC ID + 生成半结构化叙事文本
2. **Step 2** — 内容生成：interactions 先跑以固化 flag 名称 → events + auto_triggers + L1 + L3 并行
3. **Step 3** — 依赖解析 + 交叉核对：LLM 统一 flag 名称、补全 requirement 引用 → L1 ↔ L2 交叉校对
4. **Step 4** — Library 匹配：从武器/敌人库中选择填入占位符

每步含 `_with_fallback` 保底策略（重试 → 降级输出），总 10 次 LLM 调用 / 6 串行步。

### `prompts.py`

Prompt 构建器 + 叙事输出解析。所有 `build_*` 函数只构造 prompt 字符串。`parse_narrative_output()` 按 `结果 / 沉浸式叙事` 两部分拆解 LLM 输出。`log_skill_result()` 将技能检定写入日志。`_build_l1l3_context()` 从 L1/L3 数据构建基调约束和场景感知上下文，供叙事/即兴 prompt 使用。

### `game_loop.py` — 主游戏循环

三阶段 LLM 调用链 + 技能闸门 + 调试命令：

1. **动作解析** — 基于场景 JSON 和玩家输入，LLM 判断意图（move/interact/search），支持多动作识别
2. **事件判定** — 独立判断哪些不可逆事件的触发条件被满足
3. **叙事生成** — 输出拆解为简要结果（记录到 memory）+ 沉浸式叙事（显示用），融入 L1/L3 语境
3.5. **偏离检测**（预留）— 检测玩家行为是否偏离 L3 预期路径，触发运行时内容注入

阶段 1 和 2 并行调用。每个动作执行前经过统一闸门（condition 检查 + COC 7th D100 技能检定），闸门失败则跳过该动作并继续执行后续动作。动作世界更新和事件世界更新仅在实际执行/触发后发生。

### Pipeline（离线处理）

已废弃 `parsers.py` / `pipeline.py`，移至 `src/archive/`。

**新流程**（`module_designer/layered_parser.py` + `layered_pipeline.py`）：
1. `run_pipeline(content, llm_json, llm_text)` — 编排四步渐进式解析，每步含 `_with_fallback` 保底策略
2. `save_pipeline_result(result, module_dir)` — 保存 L1/L2/L3 至 `data/modules/<模组名>/`

旧 archive 模块仍可用作 fallback。

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
│  离线：四步渐进式解析（当前）                           │
│                                                      │
│  source.txt / .docx                                  │
│      ↓ Step 1: 名称固化 + 精修模组 (2 calls 并行)      │
│  condensed_text + scenes[{name,id}]                   │
│      ↓ Step 2: 内容生成                               │
│  interactions → events + auto_triggers + L1 + L3     │
│      ↓ Step 3: 依赖解析 + 交叉核对 (2 calls 串行)      │
│  依赖补全 + 场景名对齐                                 │
│      ↓ Step 4: Library 匹配 (1 call)                  │
│  enemy_ref / weapon_ref / effect_ref 填入             │
│      ↓ layered_pipeline.run_pipeline()               │
│  l1_player.json + l2_keeper.json + l3_designer.json  │
│      ↓ notebook                                      │
│  l2_keeper.json → DirectedGraph → ScenarioWorld      │
│      ↓ LLM 调用链 + L1/L3 感知叙事                    │
│  沉浸式叙事输出                                        │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  离线：旧流程（已废弃，仍可用）                          │
│                                                      │
│  模组文档 (.docx/.pdf)                                │
│      ↓ archive/parsers.py (已废弃)                    │
│  scene_output.json + res_event.json                  │
│      ↓ archive/pipeline.py (已废弃)                   │
│  scene_output_resolved_revised.json                  │
│      ↓ notebook                                      │
│  DirectedGraph → ScenarioWorld                       │
└─────────────────────────────────────────────────────┘
```

## 核心 LLM 调用

`call_deepseek(prompt, *, json_mode, system, model, thinking, reasoning_effort)`

- `model`: 模型名称（默认 `deepseek-v4-pro`）
- `thinking`: 思考模式开关（默认 True）
- `reasoning_effort`: 推理强度 `"low"/"medium"/"high"`（默认 `"high"`）
- `json_mode=True`：结构化判定（temperature=0.2）；`json_mode=False`：叙事生成（temperature=0.7）
