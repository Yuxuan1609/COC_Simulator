# Game Loop — 多 Agent 架构变更说明与测试指南

**日期**: 2026-05-16
**分支**: main (已合并)

---

## 变更概览

将单体 `handle_user_input()` 重构为 3-Agent 协同架构：

| Agent | 对应层 | 职责 | 文件 |
|-------|--------|------|------|
| **Keeper (KP)** | L2 | 回合编配：解析 → 判定 → 富化 → 升级 → 策展 | `src/game/agents/keeper.py` |
| **Narrator (叙事者)** | L1 | 唯一面向玩家，生成沉浸式叙事 | `src/game/agents/narrator.py` |
| **Author (作者)** | L3 | 仅 KP 可调用，创建持久 ModulePatch | `src/game/agents/author.py` |

### 新文件 (`src/game/`)

```
src/game/
├── __init__.py
├── messages.py         # 8 个消息 dataclass
├── judge.py            # 确定性闸门 (需求检查 + 技能检定 + @markup)
├── curator.py          # 策展 → NarratorBrief 组装
├── escalation.py       # 可配置升级策略 (LLM 评估)
└── agents/
    ├── __init__.py
    ├── keeper.py       # 回合编配器
    ├── narrator.py     # 叙事生成
    └── author.py       # 动态模组补丁
```

### 修改文件

| 文件 | 变更 |
|------|------|
| `src/scenario_core.py` | 新增 `Entity` (统一实体), `@markup` 解析器, `##GRADED##`/`##END_*` 解析器, `apply_side_effects()`, 更新 `Node`/`DirectedGraph` |
| `src/prompts.py` | 新增 4 个 prompt builder: `build_keeper_parse_prompt`, `build_keeper_enrich_prompt`, `build_narrator_prompt`, `build_author_prompt` |
| `src/game_loop.py` | 重写为薄入口: `init_game()` + `run_turn()` |
| `notebooks/notebook_simplified.ipynb` | 适配新入口 |
| `data/modules/常暗之厢/escalation_config.json` | 新增升级策略配置 |

---

## 每回合执行流

```
玩家输入
    ↓
1. PARSE (LLM) → ActionIntent[]
    ↓
2. DETERMINISTIC JUDGE
   2a. Auto-triggers (简单条件) → 触发
   2b. Interactions (需求 + 技能检定) → 执行
   2c. Events (需求过滤) → 筛出待判定
   2d. 应用 @markup side effects
    ↓
3. LLM ENRICH
   - ##GRADED## → 根据技能检定结果选层
   - Auto-triggers (自然语言条件) → LLM 判定
   - Events → LLM 匹配触发条件
   - 结果富化 + 新 world flags
    ↓
4. ESCALATION CHECK
   - 构建 EscalationContext
   - LLM 评估维度严重度 + 规则触发
   - 若触发 → Author 生成 ModulePatch → 从步骤 2 重新执行
    ↓
5. CURATE → NarratorBrief (KP 策展)
    ↓
6. NARRATE → 沉浸式叙事 (Narrator 使用 L1 数据)
    ↓
玩家看到输出
```

---

## 如何在 Notebook 中测试

### 1. 启动

在 Jupyter 中打开 `notebooks/notebook_simplified.ipynb`，按顺序执行所有 Cell。

### 2. 验证初始化

执行 Cell 3 (`run_game()`) 后应看到：
- 场景数和事件数输出
- 调查员加载信息
- "游戏开始" 提示和场景 HTML
- 开场叙事

### 3. 验证基本指令

| 输入 | 预期行为 |
|------|---------|
| `exit` / `quit` | 退出游戏 |
| `/scene` | 显示当前场景 HTML |
| `/info` | 显示结构化 JSON 状态 |
| `/events` | 显示已触发事件 |
| `/flags` | 显示世界标记 |
| `/char` | 显示调查员信息 |
| `/help` | 显示帮助 |

### 4. 验证核心游戏循环

输入自然语言动作，例如：
- `"环顾四周"` → 应返回场景描述 (search)
- `"去7号车厢"` → 应移动到目标场景 (move)
- `"阅读门上的便签"` → 应执行对应 interaction

验证点：
- 每次输入后有 `结果:` + `沉浸式叙事:` 两段输出
- 叙事文本贴合场景氛围
- 已完成交互不会重复触发
- 技能检定结果会被记录

### 5. 验证日志文件

日志文件路径打印在 Cell 1 输出中 (`../logs/prompt_log_YYYYMMDD_HHMMSS.txt`)。

打开日志文件，验证是否包含以下 section：
- `=== Keeper Parse ===` — 动作解析 prompt
- `=== Keeper Enrich ===` — 富化 prompt (如有待判定 entity)
- `=== Narrator ===` — 叙事生成 prompt
- `--- 技能检定 ---` — 技能检定结果记录
- LLM API 请求/响应日志

### 6. 验证调试命令

| 命令 | 预期 |
|------|------|
| `/spawn enemy Clicker` | 生成 Clicker 敌人 |
| `/spawn weapon 手电筒` | 获得手电筒 |
| `/inject status` | 显示注入状态 |
| `/save test` | 保存存档 |
| `/load test` | 读取存档 |

### 7. 验证升级策略 (高级)

要触发 Author 介入：
1. 执行一个没有对应 interaction 的动作（如 `"尝试跳窗逃跑"`）
2. 若升级阈值达到，Author 将生成新的 entity 并注入到场景中
3. 随后可以执行新注入的动作

升级配置位于 `data/modules/常暗之厢/escalation_config.json`，可调整 `threshold`/`cooldown` 参数控制敏感度。

---

## 运行单元测试

```bash
cd C:/Users/micha/PyCharmMiscProject
python -m pytest tests/ -v --ignore=tests/test_module_designer.py
```

预期: 63 passed (3 个已有 failure 在 test_module_designer.py 中，与本次变更无关)。

---

## 已知限制 (待修复)

| # | 问题 | 说明 |
|---|------|------|
| G1 | Judge 需求检查不完整 | `_evaluate_simple_requirement` 仅支持 `flag:` 前缀，不支持 interaction/event 前置 |
| G2 | `from_dict` 不完整 | 存档加载可能失败 |
| G3 | 升级递归无深度保护 | 极端情况下可能无限循环 |
| G4 | `run_turn` 输出格式 | 使用 `hasattr` 检查，已基本修复 |
| G5 | 结局检测未接入 | `has_ending()` 已实现但入口点不检查 |
| G6 | Keeper 无单元测试 | 需 LLM mocking |
