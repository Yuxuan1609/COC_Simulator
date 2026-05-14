# Next Session — Parser 流程精修

**上次会话**: 2026-05-13
**分支**: master
**状态**: 架构就绪，核心待重写（layered_parser + layered_pipeline）

---

## 会话背景（按轮次）

### 第一轮：Brainstorming → 设计

从 "parser 修改 briefing" 出发，经过 30+ 轮对话，产出完整架构设计：

- **三层信息模型**: L1 玩家可见（无条件感知）、L2 KP 守秘人（游戏机制真相）、L3 设计者（世界逻辑，运行时不可变）
- **武器/敌人库**: 精简核心库（~10 武器 + ~5 敌人）+ 用户 JSON 扩展包
- **双层判定**: T1 确定性掷骰（始终开启）+ T2 LLM 增强（可开关）
- **内容注入**: 离线预填充（module build）+ 运行时动态注入（deviation detection 触发）
- **Game Loop 适配**: Phase 3.5 偏离注入、Phase 5 L3 感知叙事、`/spawn` 调试命令

**产出**: 设计文档 ×3、实现计划 ×1、日志文件 ×1

### 第二轮：实施（Tasks 1-10）

按计划顺序实施全部 10 个任务。9 次 commit，22 测试。

```
✓ library/          weapons.py, enemies.py, judgment.py, injector.py
✓ module_designer/  l1_player.py, l2_keeper.py, l3_designer.py
✓ scenario_core.py  +SpawnEnemy, GrantItem, EncounterAnchor, NPCStateChange, npc_states
✓ prompts.py        +_build_l1l3_context (L1/L3 感知上下文)
✓ game_loop.py      +_handle_spawn_command, _check_deviation, _apply_side_effects 扩展
✓ archive/          旧 parsers.py, pipeline.py 归档
✓ notebooks/        notebook_simplified 切到 l2_keeper.json, parser_layered 新建
```

### 第三轮：补缺（layered_* 三文件）

实施计划中标注但未创建的三文件：

```
✓ layered_schema.py     JSON Schema 定义 + validate_l1/l2/l3/all()
✓ layered_parser.py     LLM 一键解析 parse_module() → L1+L2+L3
✓ layered_pipeline.py   run_pipeline() → schema 验证 → 离线注入 → 交叉引用
```

实际运行：`parse_module()` 对常暗之厢生成真实的 L1/L2/L3 JSON（3 次 LLM 调用，~7 场景 + 6 事件 + 6 规则 + 2 逻辑链）。Schema 验证全部 PASS。发现 LLM 生成 requirement 为字符串而非结构化 dict → 在 scenario_core 中添加 `_normalize_requirement` 容错。

**最终测试**: 34 passing

### 第四轮：代码审查（/simplify）

三个 Agent 并行审查所有变更。识别出 11 个简化项，按优先级创建 to-do 列表。**尚未实施**。

核心发现：
- `WeaponLibrary` / `EnemyLibrary` 80% 重复 → 提取 `LibraryBase`
- 15+ 数据类手动 `to_dict`/`from_dict` → 统一序列化 mixin
- `llm_call` 泄漏到公共 API → 封装 LLM 抽象
- 大量 stringly-typed 域值 → `StrEnum` 常量化

### 第五轮：流程精修设计

基于实际运行经验和审查发现，用户提出 7 条修改建议 → 整合为**四步渐进式解析流程**。

---

## 当前架构总览

### 已实现的文件

```
src/
├── library/                    ✓ 完成
│   ├── weapons.py              LibraryWeapon + WeaponLibrary (load/search/get)
│   ├── enemies.py              LibraryEnemy + EnemyLibrary
│   ├── judgment.py             JudgmentEngine (T1 deterministic + T2 context builder)
│   └── injector.py             ContentInjector (offline + runtime injection)
│
├── module_designer/            ⚠ 核心待重写 (layered_parser + layered_pipeline)
│   ├── l1_player.py            ✓ SceneL1, Perceptible, NPCAppearance
│   ├── l2_keeper.py            ⚠ SceneL2 (HiddenInfo 待废弃 → auto_trigger events)
│   ├── l3_designer.py          ⚠ 待同步新 l3_template.json
│   ├── layered_schema.py       ⚠ 待同步新 L3 字段
│   ├── layered_parser.py       ✗ 待重写 (一次生成 → 四步渐进式)
│   └── layered_pipeline.py     ✗ 待重写 (拆入 parser 各步)
│
├── scenario_core.py            ⚠ Interaction 缺 skill_name/difficulty,
│                                  GameEvent 待扩展 type/effect 字段,
│                                  HiddenInfo 待废弃, auto_trigger 条件解析器待实现
│
├── prompts.py                  ⚠ _build_l1l3_context 代码已写但未接通
│
├── game_loop.py                ⚠ _check_deviation 桩, auto_trigger 检测未实现
│
└── archive/                    ✓ 旧代码已归档
    ├── parsers.py
    └── pipeline.py
```

### 数据流（当前实际）

```
source.docx
  → layered_parser.parse_module()     [3 LLM calls, 一次生成]
  → l1_player.json + l2_keeper.json + l3_designer.json
  → layered_pipeline.run_pipeline()   [验证 + 槽位预留 + 交叉引用]
  → notebook 仅加载 l2_keeper.json   [L1/L3 未接通]
  → DirectedGraph → ScenarioWorld → handle_user_input()
```

---

## 核心待办：四步渐进式解析流程

> 详细设计见 `2026-05-13-layered-data-flow.md` §十三～十四

### 为什么需要重写

当前 `parse_module()` 一次生成三层所有内容：
- L2 prompt 极长（2000+ tokens），LLM 遗漏字段、生成不一致
- L1/L2/L3 独立调用，场景名可能不同（"6号车厢" vs "六号车厢"）
- 敌人引用是猜测的（"虚无者" 不在库中）
- `hidden_info` 触发逻辑未实现

### 新流程（4 步，~7 LLM calls）

```
Step 1 (1 call)
  输入: 完整模组文档
  输出: meta + characters[{name,id}] + scenes[{name,id}] + condensed_text
  作用: 固化名称和 ID，生成精简模组供后续使用

Step 2 (3 calls，可并行)
  输入: condensed_text + scene_names
  L1: 玩家感知信息 (不变)
  L2: 仅基础事件解析 (不含 interactions/encounters/weapons/hidden_info)
  L3: 设计者层 (基于新 l3_template.json)

Step 3 (2 calls)
  ③a Cross-validate: 确定性代码做结构检查 + LLM 做语义修正
  ③b 事件逻辑依赖解析: events → requirement 关系

Step 4 (2 calls)
  ④a LLM 辅助 library 匹配: prompt 注入库列表，LLM 从列表中选择敌人/武器
  ④b Auto-trigger 事件生成: 替代 hidden_info，统一刷怪/发武器/reveal_info 机制

输出: l1_player.json + l2_keeper.json (含 auto_trigger events) + l3_designer.json
```

### 评估要点

| 项目 | 评价 |
|------|------|
| Step 1 | ✓ 关键改进 — 名称固化 + 精简模组降低后续 token |
| Step 2 | ✓ 可并行 — 但 ⚠️ interactions 归属待确认 |
| Step 3a | ✓ 确定性代码 + LLM 修正的分工合理 |
| Step 4b | ✓ 统一 hidden_info + spawn 机制 — 但 ⚠️ condition 语法待精确定义 |

### 5 个待确认问题

| # | 问题 |
|---|------|
| Q1 | 精简模组的格式 — 纯文本摘要还是结构化 JSON？ |
| Q2 | interactions 何时生成？建议 Step 3b 之后新增一步 |
| Q3 | Step 3a cross-validate 用 LLM 还是确定性代码？建议分工 |
| Q4 | auto_trigger condition 表达式语法需精确定义（谓词/比较符/逻辑运算符）|
| Q5 | 按场景迭代的步骤 (interactions, auto_triggers) 总 token 估算 |

---

## 文档导航

### 按关注点拆分

| 领域 | 索引 | 核心文档 |
|------|------|---------|
| **模组生成** (parser/pipeline/library) | [`module-generation/README.md`](module-generation/README.md) | `2026-05-13-layered-data-flow.md`, `2026-05-13-parser-system-overhaul-design.md`, `2026-05-13-three-layer-schema-overview.md` |
| **模组运行** (game loop/scenario/prompts) | [`module-runtime/README.md`](module-runtime/README.md) | 早期设计文档 ×10 (requirement system, game loop refactor, skill check overhaul, etc.) |

### 关键文件速查

| 想了解... | 阅读... |
|-----------|--------|
| 为什么要三层？怎么分层？ | `2026-05-13-parser-system-overhaul-design.md` |
| 每层有哪些字段？字段间的引用关系？ | `2026-05-13-three-layer-schema-overview.md` |
| 当前代码怎么跑的？断点在哪里？ | `2026-05-13-layered-data-flow.md` §§一～七, 十二 |
| 新流程怎么设计？有哪些待确认？ | `2026-05-13-layered-data-flow.md` §§十三～十四 |
| 代码质量有什么问题？ | 34 个 simplify tasks (#26-#36) |
| 做过哪些 commit？ | `../journal/2026-05-13-parser-overhaul-journal.md` |
| 全局 changelog | 项目根 `CHANGELOG_parser_overhaul.md` |

---

## 建议的起始顺序

1. **确认 Q1-Q5** — 读完 `layered-data-flow.md` §十三～十四 后逐一回答
2. **同步 L3** — `l3_template.json` 已改，同步 `l3_designer.py` 和 `layered_schema.py`
3. **修复 P0 消费端断点** — `Interaction` 加字段、接通 L1/L3 加载（改动小，效果立竿见影）
4. **实施 Step 1** — 最独立的一步，可先行验证精简模组质量
5. **实施 Step 2-4** — 核心重写

---

## 测试状态

```
tests/test_library.py ............. 17 passed
tests/test_module_designer.py ..... 17 passed
Total: 34 passed

运行: python -m pytest tests/ -v
```
