# 统一可触发实体格式 — 改动总结

**日期**: 2026-05-15
**分支**: master → main
**范围**: `src/module_designer/` — 解析管线；不影响 `game_loop.py`

---

## 设计

将 interaction / auto_trigger / event 统一为共享字段模型，用 `based_on` 标注派生关系：

```
Step 2a: 统一实体列表（interactions 格式）
    ↓
Step 2b: 分类 + 补充派生实体（并行）
    ├─ interaction:  玩家主动触发，有 scene，无 based_on
    ├─ auto_trigger: 系统被动触发，有 scene，based_on → interaction
    └─ event:        全局不可逆，无 scene，based_on → interaction
    ↓
Step 3a: 依赖解析 + side_effects 结构化 + 冲突兜底
Step 4:  Library 匹配（enemy/weapon） + 技能标准化
```

## 统一字段模型

```
id, scene, type, name, requirement, trigger, result, side_effects,
enemy_ref, weapon_ref, difficulty, based_on
```

| 实体 | scene | difficulty | enemy/weapon_ref | based_on |
|------|-------|-----------|-------------------|----------|
| interaction | ✓ | ✓ | ✓ | 空 |
| auto_trigger | ✓ | ✓ | ✓ | → interaction |
| event | ✗ | ✓ | ✗ | → interaction |

- `based_on` 只能指向 interaction（Step 2b 并行，event 和 AT 不可互引）
- 冲突由 Step 3a 兜底解决

## 旧→新字段映射

| 删除的旧字段 | 替代 |
|---|---|
| `interaction.clue` | → `result` |
| `auto_trigger.effect_type` / `effect_ref` | → `enemy_ref` / `weapon_ref` |
| `auto_trigger.reveal_narrative` | → `result` |
| `auto_trigger.trigger_condition` | → `trigger` |
| `event.irreversible_impact` | → `result`（标注不可逆性） |

## 改动文件（6 files, +329/-163 lines）

| 文件 | 内容 |
|---|---|
| `data/templates/l2_template.json` | 统一三个实体的模板格式，新增 `based_on` |
| `src/module_designer/l2_keeper.py` | `AutoTrigger` 重构为新字段，`to_dict`/`from_dict` 同步 |
| `src/module_designer/layered_schema.py` | `L2_AUTO_TRIGGER_SCHEMA` 共享 `L2_INTERACTION_SCHEMA`；`L2_EVENT_SCHEMA` 加 `type`/`difficulty`/`based_on`，去 `irreversible_impact` |
| `src/module_designer/layered_parser.py` | Step 2a 加 `based_on` 字段；Step 2b events/AT prompt 重写为统一格式；Step 3a 重构（side_effect 结构化 + based_on 验证 + 冲突解决，去 flag 统一）；Step 4 扩展到 auto_triggers + 技能标准化 |
| `src/module_designer/layered_pipeline.py` | Step 4 加载 `skill_checks.json` 45 项标准技能，传入 `parse_step4` |
| `tests/test_module_designer.py` | 5 个测试函数更新为新字段名和断言 |

## Step 4 技能标准化

利用 `data/skill_checks.json` 中 45 项 COC 标准技能名，在 Step 4 prompt 中让 LLM 统一 `type` 到标准名称（如 "侦查"→"侦察"），与 `enemy_ref`/`weapon_ref` 库匹配逻辑一致。

## Commits

```
86e9da0 test: fix all tests for unified triggerable entity format
67a488f feat: extend Step 4 to auto_triggers and add skill name standardization
1a2fb00 feat: update Step 3a — side_effects structuring, based_on validation, remove flag unification
0a0b454 feat: rewrite Step 2b AT prompt with unified fields
0150253 feat: rewrite Step 2b events prompt with unified fields
e9b1b5f feat: add based_on field to Step 2a interaction format
2dfe4c5 feat: unify L2 schemas — auto_trigger shares interaction schema, event gains unified fields
9d9fbd4 refactor: unify AutoTrigger fields with interaction model
220f5c0 feat: unify triggerable entity format in L2 template
```

## 测试

44/44 passed on `main`.
