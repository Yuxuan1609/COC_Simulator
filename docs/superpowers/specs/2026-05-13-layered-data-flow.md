# 三层信息数据流向与文件关系

**日期**: 2026-05-13
**目的**: 精修前的现状梳理 —— 完整记录 L1/L2/L3 的生成路径、消费路径、文件依赖、已知缺口

---

## 一、全景数据流

```
                              ┌──────────────────────┐
                              │  source.txt / .docx   │
                              │  模组原始文档          │
                              └──────────┬───────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
              parse_l1()           parse_l2()           parse_l3()
              (LLM call 1)         (LLM call 2)         (LLM call 3)
                    │                    │                    │
                    ▼                    ▼                    ▼
             l1_player.json       l2_keeper.json       l3_designer.json
             原始解析结果           原始解析结果           原始解析结果
                    │                    │                    │
                    └────────────────────┼────────────────────┘
                                         │
                            ┌────────────▼────────────┐
                            │   run_pipeline()         │
                            │                          │
                            │  1. validate_all()       │  ← layered_schema.py
                            │     L1 schema ✓/✗        │
                            │     L2 schema ✓/✗        │
                            │     L3 schema ✓/✗        │
                            │                          │
                            │  2. offline_inject()     │  ← ContentInjector
                            │     根据 L3 danger_level │
                            │     填充 encounters/     │
                            │     scene_weapons 槽位   │
                            │                          │
                            │  3. cross_validate()     │  ← 交叉引用检查
                            │     L1→L2 refs           │
                            │     L2→Library refs      │
                            │     L3→L1/L2 scenes      │
                            └────────────┬────────────┘
                                         │
                              ┌──────────▼───────────┐
                              │  data/modules/<模组>/  │
                              │  ├── l1_player.json    │
                              │  ├── l2_keeper.json    │  ← 游戏循环消费此文件
                              │  └── l3_designer.json  │
                              └──────────────────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │  notebook_simplified  │
                              │                      │
                              │  l2_keeper.json       │
                              │    ↓                  │
                              │  scenes → DirectedGraph│
                              │  events → DirectedGraph│
                              │    ↓                  │
                              │  ScenarioWorld        │
                              │    ↓                  │
                              │  handle_user_input()  │
                              │    ↓                  │
                              │  LLM 调用链 + 叙事     │
                              └──────────────────────┘
```

**关键事实**：当前游戏循环 **只消费 L2**（通过 DirectedGraph）。L1 和 L3 仅在 prompt 构建阶段作为上下文注入（`_build_l1l3_context`），不参与游戏逻辑判定。

---

### 提案：四步渐进式解析流程（2026-05-13 设计，待实施）

```
                              ┌──────────────────────────┐
                              │  source.txt / .docx       │
                              │  模组原始文档              │
                              └────────────┬─────────────┘
                                           │
                         Step 1 ──────────▼──────────  (1 call)
                         ┌─────────────────────────────────┐
                         │  输出:                           │
                         │  • module_meta (标题/年代/主题)   │
                         │  • characters: [{name,id}, ...]  │
                         │  • scenes: [{name,id}, ...]     │
                         │  • condensed_text (精简模组)     │
                         │                                 │
                         │  → 名称和 ID 一次性固化          │
                         │  → 精简模组供后续所有步骤使用     │
                         └────────────┬────────────────────┘
                                      │
                         Step 2 ──────┼──────────  (3 calls, 可并行)
                         ┌────────────▼────────────────────┐
                         │  ┌──────────┬──────────┬──────┐ │
                         │  │  L1      │  L2      │ L3   │ │
                         │  │  玩家    │  基础    │ 设计 │ │
                         │  │  可见层  │  事件    │ 者层 │ │
                         │  └──────────┴──────────┴──────┘ │
                         │  均基于精简模组 + 统一场景名      │
                         │  L1: 氛围/感知/NPC外貌           │
                         │  L2: 仅基础 events (非 interactions)│
                         │  L3: 世界规则/基调约束/driving_force│
                         └────────────┬────────────────────┘
                                      │
                         Step 3 ──────▼──────────  (2 calls)
                         ┌─────────────────────────────────┐
                         │  ③a Cross-validate               │
                         │      场景名一致性 / 引用完整性     │
                         │                                  │
                         │  ③b 事件逻辑依赖解析              │
                         │      events → requirement 关系   │
                         │      events → logic_chains 关联  │
                         └────────────┬────────────────────┘
                                      │
                         Step 4 ──────▼──────────  (2 calls)
                         ┌─────────────────────────────────┐
                         │  ④a LLM 辅助 library 匹配        │
                         │      场景 → 敌人/武器 (从库中选择)│
                         │                                  │
                         │  ④b 生成 auto_trigger 事件       │
                         │      刷怪 Hook / 发武器 Hook     │
                         │      reveal_info Hook            │
                         │      (替代 hidden_info)          │
                         └────────────┬────────────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────────────┐
                         │  data/modules/<模组>/             │
                         │  ├── l1_player.json              │
                         │  ├── l2_keeper.json              │
                         │  └── l3_designer.json            │
                         └─────────────────────────────────┘
```

**总 LLM 调用**: 8 次（当前 3 次），但单次 prompt 更短（~800-2000 tokens vs ~4000），总 token 消耗预计持平或更低。Step 2 的三个调用可完全并行。

---

## 二、文件职责与依赖

### 2.1 生成端（离线）

```
src/module_designer/
├── layered_parser.py          ← 入口：parse_module() (当前一次生成)
│   ├── 依赖: data/templates/l1_template.json  (格式参考)
│   ├── 依赖: data/templates/l2_template.json
│   ├── 依赖: data/templates/l3_template.json
│   ├── 依赖: llm.py::call_deepseek  (通过参数 llm_call 传入 —— 泄漏)
│   ├── 输出: l1_player.json, l2_keeper.json, l3_designer.json
│   └── 已知问题:
│       • parse_l1/l2/l3 是顺序调用 (3次串行 LLM, 可并行)
│       • llm_call 作为参数暴露在公共 API 上 (应为封装)
│       • _load_template 每次从磁盘读取 JSON (可加 @lru_cache)
│       • 三个 prompt builder 各自独立, 不共享上下文 (场景名可能不一致)
│       • 一次生成全部 L2 内容 → prompt 极长, LLM 容易遗漏字段
│       • ⚠ 待替代: 四步渐进式流程 (见 §十三) 将重写此模块
│
├── layered_pipeline.py        ← 入口：run_pipeline() (当前一步完成)
│   ├── 依赖: layered_schema.py (validate_all)
│   ├── 依赖: library/injector.py (ContentInjector)
│   ├── 依赖: library/weapons.py, library/enemies.py (交叉引用)
│   ├── 输出: PipelineResult (含验证报告 + 可能修改后的 l2_data)
│   └── 已知问题:
│       • 离线注入仅做槽位预留, 不做智能匹配
│       • 交叉引用只报告不修复
│       • ⚠ 待替代: 渐进式流程中 pipeline 拆为交叉验证 (Step 3a) + library 匹配 (Step 4a)
│         — 交叉验证保留为确定性代码 (非 LLM), 语义修正由后续 LLM 步骤处理
│
├── layered_schema.py          ← 入口：validate_l1/l2/l3/all()
│   ├── 纯验证, 无外部依赖
│   ├── 输出: SchemaReport (errors/warnings + summary)
│   └── 已知问题:
│       • 所有字段 marked required: False — 验证过于宽松
│       • 枚举违规仅 warning, 不会阻止后续流程
│       • SchemaReport 与 CrossRefReport 结构重复 (可提取 ReportBase)
│       • ⚠ L3 模板已修改 (narrative_theme→narrative, required→recommended), schema 待同步
│
├── l1_player.py               ← 数据模型: SceneL1, Perceptible, NPCAppearance
├── l2_keeper.py               ← 数据模型: SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile
│   └── ⚠ HiddenInfo 待废弃, 改为 events 中的 auto_trigger 事件 (见 §十三 Step 4b)
└── l3_designer.py             ← 数据模型: L3Designer + 子结构 (已按新 l3_template 精简)
    └── 三者共同特点:
        • 每个类手写 to_dict() / from_dict() (~500 行样板代码)
        • load_*/save_* 函数手写 JSON I/O (可提取公共 helper)
        • 数据模型与 schema 定义独立维护 (字段变更需同步两处)
```

### 2.2 资源端

```
src/library/
├── weapons.py                 ← WeaponLibrary: load_core / load_extension / search / get
├── enemies.py                 ← EnemyLibrary: 同上结构 (80% 重复代码)
├── judgment.py                ← JudgmentEngine: T1 确定性 + T2 LLM 上下文构建
│   └── 已知: dice 逻辑未复用 utils.roll_dice()
├── injector.py                ← ContentInjector: offline_inject_* + runtime_spawn_*
│   └── 已知: offline_inject_scene 仅做槽位预留, 不做智能匹配
└── __init__.py

data/library/core/
├── weapons.json               ← 10 件核心武器
└── enemies.json               ← 5 个核心敌人 (4 神话生物 + 1 人类)
```

### 2.3 消费端（游戏运行时）

```
notebooks/notebook_simplified.ipynb
│
├── 导入: scenario_core, prompts, game_loop, library, module_designer
├── 加载: data/modules/常暗之厢/l2_keeper.json
│         → l2["scenes"] → DirectedGraph(scenes=...)
│         → l2["events"] → DirectedGraph(events=...)
├── 构建: ScenarioWorld(graph, start_node="6号车厢", ...)
│
├── 每回合调用: handle_user_input(cmd, world, weapon_lib=..., enemy_lib=..., injector=...)
│   ├── 阶段 0: /spawn, /inject 命令检查 (如果输入以 / 开头)
│   ├── 阶段 1: 动作解析 → LLM
│   ├── 阶段 2: 事件判定 → LLM
│   ├── 阶段 3: 叙事生成 → LLM
│   │   └── build_narrative_prompt() ← _build_l1l3_context() 注入 L1/L3 上下文
│   └── 阶段 3.5: _check_deviation() → 永远返回 0.0 (桩)
│
└── L1/L3 数据路径:
    • notebook 中未实际加载 L1 或 L3 JSON
    • handle_user_input 的 l1_data/l3_data 参数默认为 None
    • build_narrative_prompt 的 l1_scene/l3_data 参数默认为 None
    • → L1/L3 上下文实际未生效
```

---

## 三、数据格式与兼容性

### 3.1 L2 JSON → DirectedGraph 的字段映射

| L2 JSON 字段 | DirectedGraph 期望 | 兼容? |
|-------------|-------------------|-------|
| `scenes` (dict) | `DirectedGraph(scenes=dict)` | ✓ |
| `scenes[].description` | `Node.description` | ✓ |
| `scenes[].from_here` | `Edge(target, method)` | ✓ |
| `scenes[].to_here` | `Edge(source, method)` | ✓ |
| `scenes[].interactions[].type` | `Interaction.type` | ✓ |
| `scenes[].interactions[].name` | `Interaction.name` | ✓ |
| `scenes[].interactions[].requirement` | `Requirement(ref_type, ref_scene, ref_name)` | ⚠️ 需 `_normalize_requirement` 容错 |
| `scenes[].interactions[].side_effects` | `_parse_side_effects()` | ✓ (支持全部 6 种类型) |
| `scenes[].interactions[].skill_name` | **Interaction 无此字段** | ✗ 静默丢弃 |
| `scenes[].interactions[].difficulty` | **Interaction 无此字段** | ✗ 静默丢弃 |
| `events` (list) | `DirectedGraph(events=list)` | ✓ |
| `events[].id` | `GameEvent.event_id` | ✓ |
| `events[].irreversible_impact` | `GameEvent.impact` (fallback to `impact`) | ✓ |
| `npc_profiles` (dict) | **不消费** | — (仅存储) |

**关键缺口**: `Interaction` 数据类缺少 `skill_name` 和 `difficulty` 字段。LLM 生成的这两个字段在 `DirectedGraph.load_scenes()` 中被静默丢弃——`Interaction` 构造器不接受它们。这意味着 COC 7th 技能检定逻辑无法从 JSON 声明中自动获取技能名和难度。

### 3.2 L1 / L3 消费路径（当前未接通）

```
handle_user_input()
  ├── l1_data 参数: dict | None   →  notebook 传入 None
  ├── l3_data 参数: object | None →  notebook 传入 None
  └── l1_scene = l1_data.get(world.current_location) if l1_data else None
      → 永远为 None

build_narrative_prompt()
  ├── l1_scene: SceneL1 | None = None
  ├── l3_data: L3Designer | None = None
  └── _build_l1l3_context(l1_scene, l3_data, scene_name)
      → 两个参数均为 None → 返回空字符串
```

**结论**: L1 和 L3 的生成→消费管道代码已写好但 **未接通**。notebook 未加载 L1/L3 JSON，未传递给 handle_user_input。

---

## 四、文件关系图

```
                    ┌─────────────────────────────┐
                    │  data/templates/             │
                    │  l1/l2/l3_template.json      │
                    └──────────────┬──────────────┘
                                   │ 格式参考
                                   ▼
┌──────────────────────┐    ┌──────────────────────┐
│ layered_parser.py    │    │  src/llm.py           │
│  parse_l1/l2/l3()    │───▶│  call_deepseek()      │
│  parse_module()      │    │  (未封装, 直接依赖)    │
│  save_module()       │    └──────────────────────┘
└──────────┬───────────┘
           │ 输出: l1_player.json, l2_keeper.json, l3_designer.json
           ▼
┌──────────────────────┐    ┌──────────────────────┐
│ layered_pipeline.py  │    │  layered_schema.py    │
│  run_pipeline()      │───▶│  validate_all()       │
│  cross_validate()    │    └──────────────────────┘
│  PipelineResult      │    ┌──────────────────────┐
└──────────┬───────────┘    │  library/injector.py  │
           │               │  ContentInjector       │
           │         ┌────▶│  offline_inject_*()    │
           │         │     └──────────────────────┘
           │         │     ┌──────────────────────┐
           │         │     │  library/weapons.py   │
           │         └────▶│  library/enemies.py   │
           │               └──────────────────────┘
           ▼
┌──────────────────────┐
│  data/modules/<模组>/ │
│  l1_player.json       │─── L1: 未接入游戏循环
│  l2_keeper.json       │─── L2: DirectedGraph → ScenarioWorld
│  l3_designer.json     │─── L3: 未接入游戏循环
└──────────┬───────────┘
           │ 仅 L2 被消费
           ▼
┌──────────────────────┐    ┌──────────────────────┐
│ scenario_core.py     │    │  prompts.py           │
│  DirectedGraph       │    │  build_narrative_*()  │
│  ScenarioWorld       │    │  _build_l1l3_context()│
│  Interaction         │◀───│  (L1/L3 上下文未接通) │
│  GameEvent           │    └──────────────────────┘
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ game_loop.py         │
│  handle_user_input() │
│  _handle_spawn_*()   │
│  _check_deviation()  │ ← 永远返回 0.0 (桩)
└──────────────────────┘
```

---

## 五、已知断点与待精修项

### 5.1 生成端

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| G1 | parse_l1/l2/l3 串行调用, 3 次 LLM 总延迟 | `layered_parser.py:275-301` | 等待时间 = t1+t2+t3 |
| G2 | _load_template 每次磁盘 I/O | `layered_parser.py:15-21` | 可以 @lru_cache |
| G3 | 离线注入不做智能匹配, 仅预留槽位 | `injector.py:50-67` | 不会根据 L3 内容推荐敌人/武器 |
| G4 | LLM 生成的 requirement 可能是字符串而非 dict | prompt 未强制结构化 | 依赖 _normalize_requirement 容错 |

### 5.2 消费端

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| C1 | Interaction 缺少 skill_name/difficulty 字段 | `scenario_core.py:47-56` | LLM 生成的技能信息丢弃 |
| C2 | L1/L3 数据未加载到 notebook | `notebook_simplified.ipynb` | _build_l1l3_context 永远返回空 |
| C3 | _check_deviation 桩永远返回 0.0 | `game_loop.py:167-173` | Phase 3.5 未生效 |
| C4 | EncounterAnchor 定义了但未使用 | `scenario_core.py:101-108` | 死代码 |

### 5.3 结构端

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| S1 | WeaponLibrary / EnemyLibrary 80% 重复 | `library/weapons.py` + `enemies.py` | 添加新库类型需复制 |
| S2 | ~15 个数据类手写 to_dict/from_dict | l1_player, l2_keeper, l3_designer 等 | 字段变更需同步三处 |
| S3 | Schema 定义与数据模型独立维护 | `layered_schema.py` vs 数据模型文件 | 可漂移 |
| S4 | llm_call 作为参数泄漏到公共 API | `layered_parser.py:85,158,240` | 调用者必须知道 LLM 签名 |

---

## 六、从生成到消费的完整路径（当前实际）

### 路径 A: 新三层流程（部分接通）

```
1. utils.parse() → content (str)
2. parse_module(content, llm_parse) → {L1, L2, L3}     ← 3 次 LLM 调用
3. save_module(results, MODULE_DIR)                     ← 保存原始结果
4. run_pipeline(L1, L2, L3, injector, wl, el)          ← 验证+注入+交叉引用
   └── 此时 L2 数据可能有 encounters/scene_weapons 槽位
5. 手动复制 L1/L2/L3 到 data/modules/
6. notebook 加载 l2_keeper.json                         ← 仅 L2
   scenes = l2["scenes"]
   events = l2["events"]
   graph = DirectedGraph(scenes, events)
7. 游戏运行
   └── L1/L3 上下文未传递 → prompt 无三层感知
```

### 路径 B: 旧 archive 流程（完整但废弃）

```
1. utils.parse() → content
2. archive/parsers.parse_scenes_from_document() → scene_output.json
3. archive/parsers.parse_events_from_document() → res_event.json
4. archive/pipeline.resolve_requirements() → scene_output_resolved.json
5. archive/pipeline.cross_validate_and_revise() → scene_output_revised.json
6. archive/pipeline.expand_scene_descriptions() → scene_output_expanded.json
7. notebook 加载 scene_output_resolved_revised.json + res_event_resolved_revised.json
```

### 路径 C: 四步渐进式流程（提案，待实施）

```
1. Step 1 (1 LLM call):
   parse_step1(content) → {meta, characters: [{name,id}], scenes: [{name,id}], condensed_text}
   → 固化名称和 ID, 生成精简模组

2. Step 2 (3 LLM calls, 可并行):
   parse_l1(condensed_text, scene_names) → l1_player.json
   parse_l2_events(condensed_text, scene_names) → events (仅基础事件, 不含 interactions)
   parse_l3(condensed_text, scene_names) → l3_designer.json

3. Step 3 (2 LLM calls):
   cross_validate(l1, l2, l3, scene_names) → 一致性检查报告
   resolve_event_dependencies(events, l3.logic_chains) → events with requirement 关系

4. Step 4 (2 LLM calls):
   match_library(scenes, events, l3.scene_intents, library_list) → encounters + scene_weapons
   generate_auto_triggers(scenes, events, encounters) → auto_trigger events (含 spawn/hook)

5. notebook 加载 l2_keeper.json (scenes + events + auto_triggers) + l1_player.json + l3_designer.json
```

---

## 七、精修优先级建议

| 优先级 | 类别 | 项目 | 理由 |
|--------|------|------|------|
| **P0** | 消费端 C1 | Interaction 添加 skill_name/difficulty | 不修则 LLM 生成的技能数据完全浪费 |
| **P0** | 消费端 C2 | 接通 L1/L3 加载路径 | 不修则 _build_l1l3_context 是死代码 |
| **P1** | 结构端 S1 | 提取 LibraryBase | 减少维护负担, 为扩展打基础 |
| **P1** | 结构端 S2 | 统一序列化 | 字段变更不再需要手动同步 |
| **P1** | 消费端 C3 | _check_deviation 实现或移除 | 现在是死代码在热路径上 |
| **P2** | 生成端 G3 | 离线注入智能匹配 | 让 injector 真正发挥作用 |
| **P2** | 生成端 G1 | parse_module 并行化 | 降低等待时间 |
| **P3** | 结构端 S4 | 封装 LLM 抽象 | 提升可测试性 |

P0 = 功能断点, 不修则某条路径完全不通
P1 = 高价值改进
P2 = 效率/功能增强
P3 = 架构卫生

---

## 八～十二、当前实现的详细内容（参考）

> **注意**: 以下第八～十二章记录的是**当前一次生成模式** (`parse_module` → `run_pipeline`) 的实现细节。
> 新设计的四步渐进式流程（§十三）将重写这些内容。以下保留作为重构参考 —— 特别是 prompt 结构、输出示例和已知问题，在新流程设计 prompt 时直接可用。

### 八、L1 解析器详细内容

### 8.1 System Prompt

```
你是一个 TRPG 模组解析助手，专门提取「玩家可见层」信息。
你的任务是：从模组文档中提取每个场景的**初始感知信息**——玩家进入场景时，
无需任何检定即可直接感知的一切。

重要原则：
- 只描述**无条件可见**的内容（外观、声音、气味、氛围）
- 需要检定才能发现的信息 → 不要放在这里（那是 L2 的事）
- NPC 只描述外貌和神态，不写隐藏动机（那是 L2 的事）
- 用沉浸式中文，但保持简洁
- mood 从以下选择：confused / uneasy / tense / terrified / hopeful / desperate
- perceptible type 从以下选择：object / sound / smell / sight / touch / intuition
```

### 8.2 User Prompt 结构

```
根据以下模组文档，提取每个场景的「玩家初始感知信息」（L1 层）。

输出格式参考：
{l1_template.json 的内容}

要求：
1. 每个场景作为一个顶层 key，key 名为场景名称（如"6号车厢"）
2. entry_narrative：玩家进入该场景时的开场叙事（KP 可直接朗读，80-200字）
3. atmosphere：场景氛围一句话总结（如"昏暗封闭、空气中弥漫霉味"）
4. mood：该场景的目标情绪基调
5. perceptible：玩家无需检定即可感知的元素列表：
   - type：感知类型（object/sound/smell/sight/touch/intuition）
   - name：元素名称
   - brief：一句话描述
   - linked_interaction：可选，关联的 L2 互动名称（暂可留空，后续 pipeline 会补充）
6. ambient_hints：微妙的环境线索列表（玩家可感知的"直觉"类信息）
7. npc_appearances：当前场景 NPC 的外貌描述（只写外观，不写隐藏信息）

重要：
- 仅输出 JSON，不要任何解释性文字
- 只写**无条件可见**的感知信息
- 需要检定才能发现的内容留给 L2 层
- 原文未描述的内容可以基于上下文合理推测

模组文档：
"""
{content}
"""
```

### 8.3 实际输出示例（常暗之厢·6号车厢）

```json
{
  "6号车厢": {
    "entry_narrative": "你在昏暗的列车车厢中缓缓醒来。头顶的灯光不定时地闪烁...",
    "atmosphere": "昏暗封闭，灯光闪烁，空气中弥漫着若有若无的铁锈味",
    "mood": "uneasy",
    "perceptible": [
      {
        "type": "object",
        "name": "门扉上的便签",
        "brief": "一张泛黄的纸条贴在车厢门上，正面写着「只管前进吧 已经没有退路了」",
        "linked_interaction": "查看便签正面"
      },
      {
        "type": "object",
        "name": "电车示意地图",
        "brief": "车厢内贴着一张电车线路示意图，标注了各车厢的位置",
        "linked_interaction": "查看电车示意图"
      }
    ],
    "ambient_hints": [
      "窗外一片漆黑，如同在无边的隧道中穿行",
      "后方偶尔传来低沉的震动和金属扭曲声"
    ],
    "npc_appearances": []
  }
}
```

### 8.4 L1 解析的定位边界

| 放入 L1 | 放入 L2 |
|---------|---------|
| 便签正面写着什么 | 便签背面藏着什么（需要翻面或侦查检定） |
| NPC 的外貌和神态 | NPC 的动机、知识和隐藏身份 |
| 车厢内的气味和光线 | 气味来源是什么（需要调查检定） |
| 窗外一片漆黑 | 黑暗中有东西在移动（需要灵感检定） |

---

## 九、L2 解析器详细内容

### 9.1 System Prompt

```
你是一个 TRPG 模组解析助手，专门提取「KP 守秘人层」信息。
你的任务是：从模组文档中提取完整的游戏机制信息——场景功能描述、可执行互动、
敌人遭遇、隐藏信息、NPC 档案。

重要原则：
- 这是 KP 参考层，包含所有游戏机制真相
- interactions 必须包含 side_effects 数组
- encounters 引用 library 中的敌人名（如 Clicker、深潜者 等）
- scene_weapons 只列出**武器**（常规物品如手电筒由 LLM 叙事处理）
- hidden_info 是**被动触发**的信息（暗骰式），与 interaction（玩家主动选择）区分开
- NPC profiles 包含完整 KP 信息（动机、知识、性格）
```

### 9.2 User Prompt 结构（关键字段要求）

```
根据以下模组文档，提取完整的「KP 守秘人层」信息（L2 层）。

输出格式参考：
{l2_template.json 的内容}

要求：
1. scenes：每个场景包含：
   - description：场景功能性描述（KP 用，区别于 L1 的叙事性 entry_narrative）
   - from_here / to_here：移动边
   - interactions：可执行动作列表，每个包含：
     * type：互动类型（调查/鉴定/搜索/对话/决策/使用物品/战斗等）
     * name：互动名称
     * trigger：触发条件描述
     * result：结果描述
     * clue：线索（可选）
     * side_effects：副作用数组，每个元素有 type 字段：
       - flag_set: {"type":"flag_set","key":"标记名","value":true}
       - item_gain: {"type":"item_gain","item_name":"物品名"}
       - spawn_enemy: {"type":"spawn_enemy","enemy_ref":"敌人名","scene":"场景名"}
       - grant_item: {"type":"grant_item","item_ref":"武器名"}
       - npc_state_change: {"type":"npc_state_change","npc_name":"NPC名","new_state":"状态"}
       - stat_change: {"type":"stat_change","stat_name":"SAN","delta":-1}
     * requirement：前置条件数组（结构化: [{"ref_type":"flag","ref_name":"..."}] 或纯字符串）
     * skill_name：关联技能名（可选）
     * difficulty：检定难度（regular/hard/extreme）
   - encounters：预设敌人遭遇（引用 library 敌人名）
   - scene_weapons：场景中可获取的武器（只列武器！）
   - hidden_info：被动触发信息（暗骰式）

2. events：全局不可逆事件列表
   - 每个包含 id（E1,E2...）/ name / trigger / irreversible_impact / requirement

3. npc_profiles：NPC 完整档案
   - 每个包含 name / role / motivation / knowledge / personality / voice_notes

重要：
- 仅输出 JSON，不要任何解释性文字
- 根据原文合理推测补充游戏机制细节
- 隐藏信息与主动互动的区别：hidden_info 是系统被动检测条件后自动揭示的

模组文档：
"""
{content}
"""
```

### 9.3 实际输出示例（常暗之厢·6号车厢，一个带 side_effects 的 interaction）

```json
{
  "type": "调查",
  "name": "查看便签背面",
  "requirement": [],
  "trigger": "撕下便签或主动查看背面",
  "result": "发现背面写着「第三个箱子里有藏着钥匙」。",
  "clue": "钥匙藏在3号车厢",
  "side_effects": [
    {"type": "flag_set", "key": "known_back_of_note", "value": true}
  ],
  "skill_name": "侦查",
  "difficulty": "regular"
}
```

### 9.4 L2 解析的已知问题

| 问题 | 原因 | 实际表现 |
|------|------|---------|
| requirement 可能是字符串而非 dict | prompt 中列出了结构化格式但 LLM 仍可能用简写 | `"found_newspaper"` 而非 `{"ref_type":"flag","ref_name":"found_newspaper"}` |
| 敌人引用不在 library 中 | LLM 不知道 library 内容 | 生成了"虚无者"、"黑影"等自定义名称 |
| linked_interaction 名称不匹配 | L1 和 L2 独立生成，无共享上下文 | L1 引用"检查尸体"但 L2 中叫"医学检查尸体" |
| side_effects 可能格式错误 | LLM 对 side_effect type 枚举理解偏差 | 偶现不存在的 type 值 |

---

## 十、L3 解析器详细内容

### 10.1 System Prompt

```
你是一个 TRPG 模组设计分析师，专门提取「设计者层」信息。
你的任务是：从模组文档中提取模组的设计意图、世界规则、剧情逻辑链、
场景设计目的和基调约束。

重要原则：
- 这是设计者层，描述**为什么**这个模组这样设计，而非**有什么**内容
- world_rules 是世界运行的物理/超自然法则（玩家和 KP 都必须遵守）
- logic_chains 是剧情骨架，不是线性流程——包含分支节点和条件
- scene_intents 描述每个场景的**设计目的**（为什么存在这个场景），而非场景内容
- driving_force 是一切事件的根本驱动力（为什么这一切在发生）
- tone_constraints 是跨场景的叙事护栏
```

### 10.2 User Prompt 结构

```
根据以下模组文档，提取「设计者层」信息（L3 层）。

输出格式参考：
{l3_template.json 的内容}

要求：
1. module_meta：模组元信息（标题、作者、年代、主题、预计时长、玩家人数）

2. world_rules：世界运行规则列表，每个包含：
   - id：规则编号（WR1, WR2...）
   - name：规则名称
   - rule：规则描述（自然语言，LLM 和 KP 都能理解）
   - scope：影响范围（movement/combat/stealth/investigation/dialogue 等）
   - is_absolute：是否为绝对规则（true=不可违反，false=极端情况可打破）

3. logic_chains：剧情逻辑链列表，每个包含：
   - id / name / description / nodes（按顺序的里程碑）
   - branches：分支条件列表，每个包含 condition / effect / next_node
   - is_critical：是否为主线

4. scene_intents：每个场景的设计意图，key 为场景名：
   - purpose：此场景在模组中的作用
   - emotion：目标情绪
   - danger_level：危险等级（safe/low/medium/high/extreme）
   - key_info：此场景必须传达的关键信息
   - key_threat：核心威胁（可选）
   - exit_leads_to：离开后可能前往的场景

5. ending_conditions：结局条件列表
   - 每个包含 id / type（escape/trapped/madness/sacrifice/revelation）/ condition / narrative_theme

6. tone_constraints：全局叙事护栏
   - genre / forbidden / required / narrative_style

7. driving_force：一切事件的底层驱动力——"为什么这一切在发生？"

重要：
- 仅输出 JSON，不要任何解释性文字
- 从原文中推断设计意图，即使原文没有明确声明
- logic_chains 的 nodes 按推进顺序排列
- driving_force 应该是概念层面的，不是具体事件描述

模组文档：
"""
{content}
"""
```

### 10.3 实际输出示例（常暗之厢）

```json
{
  "module_meta": {
    "title": "常暗之厢",
    "era": "1920s",
    "theme": "无路可退的恐怖箱庭——在封闭的电车中逃避不可名状的吞噬"
  },
  "world_rules": [
    {
      "id": "WR1",
      "name": "无路可退",
      "rule": "后方车厢正被大嘴吞噬者逐渐吞噬。一旦车厢被吞噬，无法返回。玩家只能向前方车厢移动。",
      "scope": ["movement"],
      "is_absolute": true
    },
    {
      "id": "WR2",
      "name": "Clicker 盲感",
      "rule": "Clicker 无眼，通过声音定位。玩家若保持安静则不触发战斗；任何大声响会立即吸引其注意。",
      "scope": ["stealth", "combat"],
      "is_absolute": false
    }
  ],
  "logic_chains": [
    {
      "id": "LC1",
      "name": "主线：逃离电车",
      "description": "调查员从6号车厢苏醒，最终到达先头车厢选择加速或减速",
      "nodes": ["苏醒", "发现线索", "获取钥匙", "到达驾驶室", "做出选择"],
      "branches": [
        {"condition": "flag:has_key", "effect": "可以打开驾驶室门", "next_node": "到达驾驶室"}
      ],
      "is_critical": true
    }
  ],
  "scene_intents": {
    "6号车厢": {
      "purpose": "苏醒点——建立初始紧张感和核心规则认知（只能前进）",
      "emotion": "困惑与不安",
      "danger_level": "safe",
      "key_info": ["只能前进不能后退", "钥匙在3号车厢的第三个箱子里"],
      "exit_leads_to": ["5号车厢", "7号车厢"]
    }
  },
  "ending_conditions": [
    {
      "id": "END1",
      "type": "escape",
      "condition": "flag:accelerate AND flag:reached_cockpit",
      "narrative_theme": "加速逃离——电车冲出黑暗，调查员重见光明"
    }
  ],
  "tone_constraints": {
    "genre": "克苏鲁恐怖箱庭",
    "forbidden": ["喜剧元素", "第四面墙打破"],
    "required": ["压迫感", "时间紧迫", "孤立无援"],
    "narrative_style": "第二人称、现在时、感官描写丰富、SAN值侵蚀的渐进描写"
  },
  "driving_force": "电车正被奈亚拉托提普的化身「大嘴吞噬者」从后方吞噬，调查员必须在被吞噬前找到逃离的方法"
}
```

---

## 十一、Pipeline 详细步骤

### 11.1 步骤 1: Schema 验证

**入口**: `validate_all(l1_data, l2_data, l3_data)` → `{L1: SchemaReport, L2: SchemaReport, L3: SchemaReport}`

**验证内容**（以 L2 为例）：

| 检查项 | 规则 | 严重度 |
|--------|------|--------|
| `scenes` 是 dict | isinstance | error |
| `scenes[].interactions` 是 list | isinstance | error |
| `interactions[].type` 必填 | required=True | warning |
| `interactions[].difficulty` 枚举 | values={regular,hard,extreme} | warning |
| `events` 是 list | isinstance | error |
| `events[].id` 必填 | required=True | warning |
| `encounters[].enemy_ref` 必填 | required=True | warning |
| `npc_profiles` 是 dict | isinstance | error |

**关键特点**: 几乎所有字段 marked `required: False` — 验证极为宽松。即使数据大量缺失也不会报 error，只会报 warning。`is_valid` 仅检查是否有 error 级别的违规（主要是类型错误，如本该是 dict 却是 string）。

### 11.2 步骤 2: 离线注入

**入口**: `injector.offline_inject_module(l2_data, l3_data)` → 修改后的 l2_data

**当前逻辑**（确定性规则，不调用 LLM）：

```
for each scene in l2_data.scenes:
    intent = l3_data.scene_intents.get(scene_name)
    if intent and intent.danger_level in ("high", "extreme"):
        scene_data.setdefault("encounters", [])       ← 预留空槽位
        scene_data.setdefault("scene_weapons", [])    ← 预留空槽位
```

**不做的事情**（设计上留待后续）：
- 不根据场景主题匹配敌人类型（如"水中场景 → 深潜者"）
- 不根据场景危险等级推荐具体武器
- 不根据 L3 key_threat 字段查找对应的 library 敌人
- 已有 encounter/weapon 声明不做修改

### 11.3 步骤 3: 交叉引用验证

**入口**: `cross_validate_layers(l1, l2, l3, weapon_lib, enemy_lib)` → CrossRefReport

**四项检查**：

| # | 检查 | 方向 | 严重度 |
|---|------|------|--------|
| 1 | L1 perceptible.linked_interaction 是否在任一 L2 scene 的 interactions[].name 中存在 | L1→L2 | warning |
| 2 | L2 encounters[].enemy_ref 是否在 enemy_lib 中存在 | L2→Library | **error** |
| 3 | L2 scene_weapons[].weapon_ref 是否在 weapon_lib 中存在 | L2→Library | **error** |
| 4 | L3 scene_intents 的 key 集合是否与 L1/L2 的场景名集合一致 | L3→L1/L2 | warning |

**error vs warning 的设计逻辑**：
- Library 引用不匹配是 **error**：游戏运行时 spawn 一个不存在的敌人会崩溃
- L1→L2 引用不匹配是 **warning**：LLM 在两层生成了不同名称的同一互动，pipeline 后续可自动修正
- 场景名不一致是 **warning**：可能是 LLM 漏生成了某个场景的 L3 intent

### 11.4 Pipeline 对数据的修改

```
输入: l1_data (不变), l2_data (可能被 injector 修改), l3_data (不变)

run_pipeline() 返回的 PipelineResult:
  ├── l1_data     ← 原样返回
  ├── l2_data     ← 如果 run_injection=True 且 injector 非 None:
  │                   对 danger_level=high/extreme 的场景添加了空的 encounters/scene_weapons 数组
  ├── l3_data     ← 原样返回
  ├── schema_reports   ← {L1: SchemaReport, L2: SchemaReport, L3: SchemaReport}
  └── cross_ref_report ← CrossRefReport (如有 run_cross_validate)
```

**重要**: pipeline **不会**自动修正任何 LLM 生成的错误。它只报告问题。引用不匹配、格式错误、枚举违规都需要人工审核后手动修改 JSON。

### 11.5 实际运行记录（常暗之厢，2026-05-13）

```
第一次运行:
  L1: 7 场景, Schema PASS (0 errors, 0 warnings)
  L2: 7 场景, 4 事件, Schema PASS
  L3: 8 世界规则, 3 逻辑链, Schema PASS (3 warnings: danger_level 带额外文字)
  交叉引用: 1 error — enemy_ref "虚无者" 不在库中
  注入: 2 encounters 槽位

第二次运行（LLM 随机性导致不同输出）:
  L2: 7 场景, 6 事件
  L3: 6 世界规则, 2 逻辑链
  交叉引用: 4 warnings — 4 个 L1 linked_interaction 名称与 L2 不匹配
  注入: 1 encounter 槽位
```

**观察**：两次 LLM 调用产生不同的输出（事件数、规则数、引用质量不同）。这是 LLM 解析的固有特征——同一 prompt 和 content，不同调用产生不同结果。

---

## 十二、当前各文件实际状态快照

```
已完成 ✓:
  src/library/          weapons.py, enemies.py, judgment.py, injector.py, __init__.py
  src/module_designer/  l1_player.py, l2_keeper.py, l3_designer.py
                        layered_schema.py, layered_parser.py, layered_pipeline.py, __init__.py
  data/library/core/    weapons.json (10), enemies.json (5)
  data/templates/       l1_template.json, l2_template.json, l3_template.json
  data/modules/常暗之厢/ l1_player.json, l2_keeper.json, l3_designer.json (LLM 生成)
  data/output/archive/  旧 pipeline 输出 + 旧 parser.ipynb 快照
  tests/                test_library.py (17), test_module_designer.py (17) — 34 passing
  notebooks/            notebook_simplified.ipynb (已切到 l2_keeper.json)
                        parser_layered.ipynb (新三层解析工作流)

已废弃 (移至 src/archive/):
  src/archive/          parsers.py, pipeline.py

临时文件 (待清理):
  tools/                create_layered_notebook.py, run_layered_parser.py
  notebooks.7z

未实现 (spec 中提及但未做):
  module_designer/      约束接口方法 (get_applicable_rules, validate_spawn 等)
  game_loop.py          deviation_score 实际实现 (当前为桩)
  scenario_core.py      EncounterAnchor 未接入任何运行时逻辑
  prompts.py            L1/L3 上下文未接通 (notebook 未加载 L1/L3 JSON)
  notebooks/            L1/L3 JSON 加载和传递给 handle_user_input
```

---

## 十三、四步渐进式解析流程设计（2026-05-13）

将之前的 7 条修改建议整合为统一的 4 步流程。每条步骤含：输入/输出、LLM 调用数、评估标注。

---

### Step 1: 元信息提取 + 名称固化 + 模组精简

**调用次数**: 1 次 LLM

**输入**: 完整模组文档 (source.txt / .docx)

**输出**:
```json
{
  "module_meta": { "title": "...", "era": "...", "theme": "..." },
  "characters": [
    { "name": "京山人吉", "id": "NPC_1" },
    { "name": "乘务员", "id": "NPC_2" }
  ],
  "scenes": [
    { "name": "6号车厢", "id": "S1" },
    { "name": "7号车厢", "id": "S2" }
  ],
  "condensed_text": "精简后的模组文本（保留关键实体、事件、线索，去除非必要的叙事描写和冗余对话）"
}
```

**评估**: ✓ 合理，是关键改进。一次性固化名称和 ID 彻底解决场景名不一致问题。精简模组降低 Step 2/3 的 token 消耗（原文 ~12K → 估计 2-4K tokens）。

**待确认**: "精简模组"的格式 —— 纯文本摘要还是结构化 JSON？如关键细节被压缩丢失，后续步骤质量连锁下降。建议：结构化，保留所有关键实体和事件但除去冗余叙事。

---

### Step 2: 三层并行解析

**调用次数**: 3 次 LLM（可完全并行，`ThreadPoolExecutor`）

**输入**: Step 1 的 `condensed_text` + `scenes` 名称列表

**L1 — 玩家可见层**（不变）:
```
基于精简模组 + 场景名约束 ["S1:6号车厢", ...]，提取每个场景的初始感知信息。
输出: l1_player.json
```

**L2 — 仅基础事件解析**（范围缩减）:
```
基于精简模组 + 场景名约束，提取每个场景的不可逆事件 (events) 列表。
每个事件包含: id (E1,E2...), name, trigger, irreversible_impact
注意: 不包含 interactions, encounters, scene_weapons, hidden_info
输出: l2_events.json
```

**L3 — 设计者层**（基于新 l3_template.json）:
```
基于精简模组 + 场景名约束，提取设计者信息。
输出: l3_designer.json (world_rules, logic_chains, scene_intents, tone_constraints, driving_force, ending_conditions)
```

**评估**: ✓ 三个调用独立可并行，延迟 = max(t1,t2,t3)。L2 缩减为基础事件降低了单次 prompt 复杂度。

**⚠️ 待确认**: interactions 何时生成？当前方案中 interactions 未在任何 Step 中明确出现。L2 的核心可执行内容（每个场景 5-20 个互动）必须有一个归属步骤。建议：在 Step 3b 之后增加一步生成 interactions，或将其合并到 Step 3b 中。

---

### Step 3: 交叉验证 + 事件依赖解析

**调用次数**: 2 次（建议 1 次确定性代码 + 1 次 LLM）

**③a — Cross-validate**:
- 检查场景名一致性（Step 2 的三层输出是否都使用了 Step 1 的场景名）
- 检查 L1 perceptible.linked_interaction 是否在 L2 的 interactions 中存在（如 interactions 已在某步生成）
- 检查 L3 scene_intents 的 key 是否覆盖了所有场景
- **建议用确定性代码**（非 LLM）：当前 `cross_validate_layers()` 已在做这些检查，几毫秒完成为零 token。LLM 可用于**语义修正**（如 L1 和 L2 中名称稍有不同但指同一互动时自动对齐）。

**③b — 事件逻辑依赖解析**:
```
基于已确定的所有 events (Step 2 L2)，分析事件之间的前置依赖关系。
输出: events with requirement 字段填充
      logic_chains (L3) 的 nodes/branches 与具体 event ID 关联
```

**评估**: ✓ 分解正确。先有事件列表 (what)，再确定依赖关系 (depends on what)，符合渐进原则。Cross-validate 确定性检查 → LLM 语义修正的分工设计合理。

**⚠️ 待确认**: "事件逻辑依赖解析"的输出归属 —— events 的 `requirement` 关系是 L2 的，`logic_chains` 是 L3 的。建议分成两个子输出明确标注层归属。

---

### Step 4: Library 匹配 + Auto-trigger 生成

**调用次数**: 2 次 LLM

**④a — LLM 辅助 library 匹配**:
```
基于场景危险等级 (L3 scene_intents) 和主题，从可用库中选择敌人和武器。
Prompt 注入 library 简要列表:
  可用敌人: Clicker (盲感怪物, 皮厚2点), 深潜者 (两栖, 鳞片1点), 食尸鬼 (食腐), ...
  可用武器: .45自动手枪 (1D10+2, 1920s), 手电筒 (钝器1D3), ...
LLM 必须从给定列表中选择，不允许自创名称。
输出: encounters + scene_weapons (引用 library 中的真实名称)
```

**④b — 生成 auto_trigger 事件**（替代 hidden_info）:
```
基于场景内容和已分配的 encounters/scene_weapons，生成自动触发事件。
事件类型: auto_trigger
效果类型: reveal_info | spawn_enemy | grant_weapon | npc_state_change
触发条件: skill:侦查>=50 OR background:医生 OR flag:entered_7 ...
输出: auto_trigger events 列表
```

示例格式:
```json
{
  "id": "E_AUTO_2",
  "type": "auto_trigger",
  "name": "Clicker 出现",
  "trigger_condition": "flag:entered_7 AND !flag:clicker_defeated AND skill:潜行<30",
  "effect": "spawn_enemy",
  "enemy_ref": "Clicker",
  "quantity": 1,
  "reveal_narrative": "黑暗中传来咔嗒咔嗒的声音...一个无眼的人形生物从角落爬出"
}
```

**评估**: ✓ library 匹配注入列表解决了名称不匹配问题。✓ auto_trigger 统一了 hidden_info 和刷怪/物品机制。

**待确认**: auto_trigger 的 `trigger_condition` 语法需要精确定义。支持的谓词 (`skill:`, `background:`, `flag:`, `item:`, `!`)，比较符 (`>=`, `=`, `<`)，逻辑运算符 (`AND`, `OR`)。需要在 `scenario_core.py` 中实现对应的条件解析器。

---

## 十四、新流程评估与待确认问题

### 14.1 整体评估

| Step | Calls | 可并行 | Token 估算 | 评价 |
|------|-------|--------|-----------|------|
| 1 | 1 | — | ~3000 | ✓ 关键改进，固化名称和 ID |
| 2 | 3 | 是 (t=max) | ~1500×3 | ✓ L1/L3 不变，L2 缩减为基础事件 |
| 3a | 0 (确定性) | — | 0 | ✓ 复用 cross_validate_layers() |
| 3b | 1 | — | ~1500 | ✓ 事件依赖独立成步 |
| 4a | 1 | — | ~1200 | ✓ library 匹配解决名称问题 |
| 4b | 1 | — | ~1500 | ✓ 统一机制替代 hidden_info |
| **总计** | **7 LLM** | 有效并行后 ~5 串行步 | ~10K total | 当前 3 次 ~12K total |

### 14.2 待确认问题

| # | 问题 | 影响 |
|---|------|------|
| Q1 | **精简模组的格式** — 纯文本摘要还是结构化 JSON？太精简丢失关键细节，太详细 token 节省有限 | Step 2 所有依赖 |
| Q2 | **interactions 归属** — 当前流程中没有明确的 interactions 生成步骤。何时生成？建议在 Step 3b 之后新增 Step 3.5 (1-2 LLM calls, 按场景) | L2 最大内容块缺失 |
| Q3 | **Step 3a 用 LLM 还是确定性代码** — 建议确定性代码做结构检查 (零 token) + LLM 做语义修正 (有分歧时) | 成本与准确性平衡 |
| Q4 | **auto_trigger condition 语法** — 支持的谓词、比较符、逻辑运算符需要精确定义，并在 `scenario_core.py` 中实现条件解析器 | Step 4b 可行性 |
| Q5 | **场景级 iterations** — 在渐进式流程中，某些步骤可能需要按场景迭代 (for each scene)。迭代次数 = N_scenes (7-15)，需要评估 token 总量 | 总成本估算 |

### 14.3 影响范围

| 组件 | 变化 | 破坏性 |
|------|------|--------|
| `layered_parser.py` | 核心重写 — parse_module() 改为 4 步入口，新增 parse_step1/step3b/step4a/step4b | **高** |
| `layered_pipeline.py` | cross_validate 保留为确定性步骤 (Step 3a)，其余逻辑移入 parser 各步 | 中 |
| `l2_keeper.py` | `SceneL2.hidden_info` 移除；interactions 可能需要延迟生成 | 中 |
| `l2_template.json` | `hidden_info` 移除；events 新增 `type`/`effect` 字段 | 中 |
| `scenario_core.py` | `GameEvent` 扩展 `type`/`effect`/`trigger_condition` 字段；新增 `OtherEffect` 类型；条件表达式解析器 | **高** |
| `game_loop.py` | `_apply_side_effects` 新增 `OtherEffect` 处理；新增 auto_trigger 被动检测逻辑 | 中 |
| `layered_schema.py` | L3 字段同步 (narrative_theme→narrative, required→recommended) | 低 |
| `data/templates/l3_template.json` | 已由用户修改 ✓ | — |
