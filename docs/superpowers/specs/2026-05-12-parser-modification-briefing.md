# Parser 修改 Briefing：side_effects + difficulty/skill_name 集成

**日期**: 2026-05-12
**用途**: 新 session 启动时阅读，了解当前状态和待修改项
**前置阅读**: `docs/superpowers/specs/2026-05-11-optimization-analysis.md`

---

## 一、本轮对话已完成的改动（影响 parser 的上下文）

### 1.1 `Interaction` 数据类新增字段

`src/scenario_core.py` 的 `Interaction` 新增：

```python
side_effects: list = field(default_factory=list)  # FlagSet | ItemGain | StatChange
```

对应的副作用类型（同文件）：

| 类型 | 字段 | 用途 |
|------|------|------|
| `FlagSet` | `key: str`, `value: bool` | 设置世界标记 |
| `ItemGain` | `item_name: str` | 获得关键物品 |
| `StatChange` | `stat_name: str`, `delta: int` | 属性变化（预留） |

JSON 模板已更新（`data/templates/scene.json`），示例：
```json
"side_effects": [
  {"type": "flag_set", "key": "示例标记", "value": true},
  {"type": "item_gain", "item_name": "示例物品"},
  {"type": "stat_change", "stat_name": "SAN", "delta": -1}
]
```

### 1.2 `DirectedGraph.load_scenes` 已解析 `side_effects`

```python
side_effects=_parse_side_effects(inter.get("side_effects", [])),
```

如果 JSON 中有 `side_effects` 字段，load_scenes 会正确解析。如果字段不存在（当前数据文件的情况），默认为 `[]`。

### 1.3 game_loop 已消费 `side_effects`

`_apply_side_effects(world, side_effects)` 在三个路径调用：场景交互、移动、事件触发。因此只要 parser 产出的 JSON 包含 `side_effects`，游戏循环就会自动消费。

### 1.4 当前数据的实际状态

`data/output/scene_output_resolved_revised.json` 中所有 26 个 interaction 的 `side_effects` 都是 `[]`（空），因为 parser 还没有产出这个字段。

---

## 二、Parser 管线现状

### 2.1 数据流

```
模组文档 (.docx/.pdf)
    ↓ parsers.py (LLM: 解析场景 + 事件结构)
scene_output.json + res_event.json
    ↓ pipeline.py: resolve_requirements (LLM: 前置条件精确匹配)
scene_output_resolved.json + res_event_resolved.json
    ↓ pipeline.py: cross_validate_and_revise (LLM: 交叉验证 + 修订)
scene_output_revised.json + res_event_revised.json
    ↓ pipeline.py: expand_scene_descriptions (LLM: 文学性扩充)
scene_output_expanded.json
    ↓ (手工选择 expanded 或 revised)
    ↓ notebook_simplified.ipynb 加载
DirectedGraph → ScenarioWorld → game_loop
```

### 2.2 `parsers.py` — 两个 LLM 调用

**`parse_scenes_from_document(content)`**：
- 从 `data/templates/scene.json` 读格式参考
- 构建 prompt，让 LLM 从文档中提取场景 JSON
- `format_example` 硬编码在代码中（第 16-43 行），**未包含 `side_effects` 字段**
- 返回场景 dict（key=场景名）

**`parse_events_from_document(content)`**：
- 从 `data/templates/event.json` 读格式参考
- 让 LLM 按时间线提取不可逆事件
- 返回事件数组

### 2.3 `pipeline.py` — 三个 LLM 后处理阶段

**`resolve_requirements`**：
- 将场景和事件的 requirement 引用精确匹配
- Prompt 中包含完整的场景/事件数据
- 输出格式与输入一致（保留所有字段）
- 约束："严格保持 JSON 结构不变"（因此新增字段会被保留）

**`cross_validate_and_revise`**：
- 交叉验证场景和事件的一致性，发现问题后修订
- Prompt 包含完整数据 + 原文
- 约束："保持 JSON 结构与修订前一致（字段名、层级不变）"
- 修订输出可能丢失 LLM 不知道的新增字段

**`expand_scene_descriptions`**：
- 将功能性描述扩展为沉浸式叙事
- 约束明确："不可新增或删除任何 interactions 数组中的元素"
- 有结构验证（检查场景数、interaction 数不变）

### 2.4 `parser.ipynb` — Notebook 编排

按顺序执行：
1. 加载文档 → Token 预估
2. `parse_scenes_from_document` → 保存 `scene_output.json`
3. `parse_events_from_document` → 保存 `res_event.json`
4. `call_deepseek_summarize` → 保存背景摘要
5. `resolve_requirements` → 保存 `_resolved.json`
6. `cross_validate_and_revise` → 保存 `_revised.json`
7. `expand_scene_descriptions` → 保存 `_expanded.json`

---

## 三、需要修改的内容

### 3.1 必须改：让 parser 产出 `side_effects`

**涉及文件：**

| 文件 | 改动 |
|------|------|
| `src/parsers.py` | `parse_scenes_from_document` 的 `format_example` 需要包含 `side_effects` 字段；prompt 文本需增加对 side_effects 的说明 |
| `src/pipeline.py` | 三个阶段的 prompt 格式示例中需出现 `side_effects`，确保 LLM 不会丢弃该字段 |
| `data/templates/event.json` | （可选）事件模板是否也需要 `side_effects`？当前 `GameEvent` 数据类没有此字段 |

**parsers.py 的 `format_example` 当前缺失：**

```python
# 当前 interaction 示例中没有这一行：
"side_effects": [
    {"type": "flag_set", "key": "示例", "value": true}
],
```

需要在 `requirement` 数组之后、`trigger` 之前插入 `side_effects`。

**pipeline.py 需要注意：**
- `resolve_requirements` 的 prompt 中包含完整 JSON 数据——输入已含 `side_effects`（即使是空数组），LLM 理应保留。但如果 LLM 在修订时重新生成 interaction，可能丢失字段。
- `cross_validate_and_revise` 同理—修订输出的 interaction 必须保留 `side_effects`。
- `expand_scene_descriptions` 约束最严格（不新增/删除 interaction），相对安全。

### 3.2 建议改：`difficulty` 和 `skill_name` 结构化字段

来自 optimization-analysis #5：

> `Interaction` 增加 `difficulty` 字段和 `skill_name` 字段。
> LLM 在动作解析时直接引用结构化字段，不再从自然语言 trigger 中推测技能名和难度。

**当前状态：**
- `trigger` 字段是自然语言描述，如 `"对7号车厢深处使用《侦查》"`
- `check_skill(difficulty)` 预留了 `hard`/`extreme` 但未被 prompt 或场景数据使用
- LLM（build_action_prompt）需要从自然语言中推测技能名和难度

**建议新增字段（`Interaction`）：**
```python
skill_name: Optional[str] = None   # 关联技能名，如 "侦查"
difficulty: str = "regular"        # regular / hard / extreme
```

**JSON 格式：**
```json
{
  "name": "侦查车厢深处",
  "type": "调查",
  "skill_name": "侦查",
  "difficulty": "regular",
  "trigger": "对7号车厢深处使用《侦查》",
  "result": "成功：看到巨大嘴巴啃噬车厢..."
}
```

**涉及改动：**
- `src/scenario_core.py`: `Interaction` 加两个字段
- `data/templates/scene.json`: 模板加字段
- `src/parsers.py`: prompt format_example 加字段
- `src/pipeline.py`: 各阶段 prompt 保留字段
- `src/prompts.py:build_action_prompt`: 可直接引用 `skill_name` / `difficulty`（后续改动）
- `src/game_loop.py`: skill_checks 可优先使用 JSON 声明的 skill_name（后续改动）

### 3.3 验证方法

修改 parser 后，重新运行 `parser.ipynb` 全流程，检查：
1. 产出的 JSON 中每个 interaction 是否有 `side_effects`（至少是 `[]`）
2. 如果有 `difficulty` / `skill_name`，是否被正确保留
3. 用 `notebook_simplified.ipynb` 加载新数据，`/do` 命令执行交互后确认 `_apply_side_effects` 能触发

---

## 四、相关文件索引

| 路径 | 作用 |
|------|------|
| `src/parsers.py` | LLM prompt 构建——解析场景和事件 |
| `src/pipeline.py` | 后处理管线——需求匹配、交叉验证、文学扩充 |
| `notebooks/parser.ipynb` | 解析工作流编排 |
| `src/scenario_core.py` | `Interaction`、`ActionResult`、`FlagSet` 等数据类 |
| `src/game_loop.py` | `_apply_side_effects`、事件闸门 |
| `src/prompts.py` | 游戏内 LLM prompt（`build_action_prompt` 等） |
| `data/templates/scene.json` | 场景 JSON 模板（已含 `side_effects`） |
| `data/templates/event.json` | 事件 JSON 模板 |
| `data/output/` | 当前数据文件 |
| `docs/superpowers/specs/2026-05-11-optimization-analysis.md` | #4（交互结果）、#5（难度等级） |
| `docs/superpowers/specs/2026-05-12-interaction-event-serialization-design.md` | ActionResult/side_effects 设计 |
| `docs/superpowers/specs/2026-05-12-modification-summary.md` | 本轮改动汇总 |
