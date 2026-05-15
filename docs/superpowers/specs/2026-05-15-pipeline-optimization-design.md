# 解析管线优化四则

**日期**: 2026-05-15
**状态**: 设计中
**范围**: `src/module_designer/` — 解析管线；不影响 `game_loop.py`

---

## 1. 去除 enemy_ref / weapon_ref 顶层字段

### 1.1 动机

敌人/武器信息已由以下字段承接，顶层 `enemy_ref`/`weapon_ref` 是冗余的：
- `side_effects` → `spawn_enemy.enemy_ref`
- `side_effects` → `grant_item.item_ref`
- `result` 和场景描述中的自然语言

### 1.2 改动

- 统一实体字段模型删除 `enemy_ref` 和 `weapon_ref`
- Step 4 的 library 匹配逻辑不变——匹配结果写入 side_effects 的结构化对象内
- `AutoTrigger` dataclass 删除对应字段
- Schema 同步删除
- Prompt 格式同步删除

### 1.3 影响

`l2_keeper.py`, `layered_parser.py`, `layered_schema.py`, `l2_template.json`, `layered_pipeline.py`, notebook

---

## 2. Condensed_text 按章节拆分

### 2.1 动机

当前所有下游 prompt 都塞入完整的 `condensed_text`（数千字），大量无关章节占据 token。按 `## ` 标题拆分为 dict 后，各 prompt builder 按需取用。

### 2.2 实现

`parse_step1b` 输出不变（仍为完整 markdown）。新增工具函数：

```python
def _parse_condensed_chapters(markdown_text: str) -> dict[str, str]:
    """按 ## 标题拆分为章节 dict。key 为标题名（去掉 ## 前缀）。"""
```

返回章节 dict，key 为当前 Step 1b prompt 中的固定章节名：
`module_overview`, `scenes`, `npcs`, `enemies`, `clues_and_items`, `events_summary`, `locations_and_map`

### 2.3 下游使用

| Step | 主要使用的章节 |
|------|-------------|
| Step 2a (interactions + movements) | `scenes`, `locations_and_map` |
| Step 2b events | `scenes`, `events_summary` |
| Step 2b AT | `scenes` |
| Step 2c L1 | `scenes` |
| Step 2c L3 | `module_overview`, `events_summary` |
| Step 3a | 全部（去重/冲突参考） |
| Step 3b | 全部（交叉核对参考） |
| Step 3.5 | 全部（依赖解析参考） |
| Step 4 | 全部（标准化参考） |

### 2.4 函数签名变更

所有 `parse_step*` 和 `build_step*` 的 `condensed_text: str` 参数改为 `chapters: dict[str, str]`。

### 2.5 影响

`layered_parser.py` (新增 `_parse_condensed_chapters` + 全部 prompt builder 重构参数), `layered_pipeline.py`, notebook

---

## 3. 场景引用统一使用中文名

### 3.1 动机

当前 scene ID（S1, S2...）需要额外的 name→id 映射。直接用中文名（6号车厢, 7号车厢...）提示词更自然，LLM 不需要额外学习 ID 体系。

### 3.2 改动

- `build_step1a_prompt`: scenes 输出删除 `id` 字段，只保留 `name`
- 所有实体（interaction/event/auto_trigger）的 `scene` 字段值从 ID 改为中文名
- `scene_movements` 的 key 从 ID 改为中文名
- Step 1a 的 `scenes` 列表从 `[{name, id}]` 变为 `[name, ...]`（纯字符串列表）
- `l2_template.json` L2 scenes key 已是中文名，无需改动
- `l2_keeper.py` `SceneL2.scene_name` 已是中文名，无需改动

### 3.3 不变的

- 实体 ID（I1, E1, AT1）保持不变——实体级别的唯一标识
- `based_on` 仍然指向 interaction ID，不涉及 scene 引用
- `DependencyGraph` 节点 ID 不变

### 3.4 影响

`layered_parser.py`（Step 1a prompt + 所有 scene 相关格式）, `layered_pipeline.py`（去掉 name_to_id 映射逻辑 + scenes_by_sid 改为 scenes_by_name）, notebook

---

## 4. Step 3a 后组装 L2 结构

### 4.1 动机

当前 L2 的 scenes 分组在管线末尾（`save_pipeline_result`）才完成。提前到 Step 3a 后，后续步骤消费的是完整的 L2 结构而非平面列表。

### 4.2 组装内容

```python
def _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data) -> dict:
    scenes = {}
    # 按 scene 分组 interactions + auto_triggers
    for inter in interactions:
        sname = inter.get("scene", "")
        scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                   "encounters": [], "scene_weapons": [], "extra": {}})
        scenes[sname]["interactions"].append(inter)
    for at in auto_triggers:
        sname = at.get("scene", "")
        scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                   "encounters": [], "scene_weapons": [], "extra": {}})
        scenes[sname]["auto_triggers"].append(at)
    # 注入 scene_movements
    for sname, movement in scene_movements.items():
        scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                   "encounters": [], "scene_weapons": [], "extra": {}})
        scenes[sname]["from_here"] = movement.get("from_here", [])
        scenes[sname]["to_here"] = movement.get("to_here", [])
    # 注入 L1 scene description
    for sname in scenes:
        l1_scene = l1_data.get(sname, {})
        scenes[sname]["description"] = l1_scene.get("entry_narrative", "") or l1_scene.get("atmosphere", "")
    return {
        "scenes": scenes,
        "events": events,
        "npc_profiles": {},
    }
```

### 4.3 管线流程调整

```
Step 3a → _assemble_l2() → Step 3b → Step 3.5 + Step 4 (并行)
```

- `save_pipeline_result` 简化——不再做分组，直接序列化 `result.l2_data`
- `cross_validate_layers` 输入不变（已是 scenes dict）
- Step 3b/3.5/4 的输入从 list-of-dicts 改为 assembled dict

### 4.4 影响

`layered_pipeline.py`（新增 `_assemble_l2` + 调整步骤顺序）, `save_pipeline_result` 简化, notebook

---

## 5. 变更范围总览

| 文件 | 改动 |
|------|------|
| `l2_keeper.py` | AutoTrigger 删除 enemy_ref/weapon_ref |
| `layered_schema.py` | 删除 enemy_ref/weapon_ref |
| `l2_template.json` | 交互/AT 格式删除 enemy_ref/weapon_ref |
| `layered_parser.py` | 新增 `_parse_condensed_chapters`；全部 prompt builder 的 `condensed_text`→`chapters`；删除 enemy_ref/weapon_ref 格式；scene ID→中文名 |
| `layered_pipeline.py` | 新增 `_assemble_l2`；调整流程；chapters 传递；删除 name_to_id 映射 |
| notebook 两个 | 同步所有变更 |

**不变的**：
- `l1_player.py`, `l3_designer.py`, `dependency_graph.py`
- `scenario_core.py`（运行时）
- `skill_checks.json` 等数据文件
