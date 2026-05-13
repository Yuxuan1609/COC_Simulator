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

## 二、文件职责与依赖

### 2.1 生成端（离线）

```
src/module_designer/
├── layered_parser.py          ← 入口：parse_module()
│   ├── 依赖: data/templates/l1_template.json  (格式参考)
│   ├── 依赖: data/templates/l2_template.json
│   ├── 依赖: data/templates/l3_template.json
│   ├── 依赖: llm.py::call_deepseek  (通过参数 llm_call 传入 —— 泄漏)
│   ├── 输出: l1_player.json, l2_keeper.json, l3_designer.json
│   └── 已知问题:
│       • parse_l1/l2/l3 是顺序调用 (3次串行 LLM, 可并行)
│       • llm_call 作为参数暴露在公共 API 上 (应为封装)
│       • _load_template 每次从磁盘读取 JSON (可加 @lru_cache)
│       • 三个 prompt builder 各自独立, 不共享上下文
│
├── layered_pipeline.py        ← 入口：run_pipeline()
│   ├── 依赖: layered_schema.py (validate_all)
│   ├── 依赖: library/injector.py (ContentInjector)
│   ├── 依赖: library/weapons.py, library/enemies.py (交叉引用)
│   ├── 输出: PipelineResult (含验证报告 + 可能修改后的 l2_data)
│   └── 已知问题:
│       • 离线注入仅做槽位预留 (setdefault encounters/scene_weapons 为空数组)
│         — 不根据 L3 内容智能匹配敌人/武器
│       • 交叉引用的 L1→L2 检查仅以 warning 报告, 不自动修复
│       • 交叉引用每调用都重建 L2 interaction 索引 (可缓存)
│
├── layered_schema.py          ← 入口：validate_l1/l2/l3/all()
│   ├── 纯验证, 无外部依赖
│   ├── 输出: SchemaReport (errors/warnings + summary)
│   └── 已知问题:
│       • 所有字段 marked required: False — 验证过于宽松
│       • 枚举违规仅 warning, 不会阻止后续流程
│       • SchemaReport 与 CrossRefReport 结构重复 (可提取 ReportBase)
│
├── l1_player.py               ← 数据模型: SceneL1, Perceptible, NPCAppearance
├── l2_keeper.py               ← 数据模型: SceneL2, Encounter, SceneWeapon, HiddenInfo, NPCProfile
└── l3_designer.py             ← 数据模型: L3Designer + 8 个子结构
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
