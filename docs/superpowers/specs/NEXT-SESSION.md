# Next Session — P0 消费端断点修复 + Runtime 接通

**上次会话**: 2026-05-14
**分支**: master
**状态**: 模组生成端完成，消费端待修复

---

## 会话背景

### 本轮：四步渐进式解析器实施

基于 2026-05-13 的设计和 brainstorming session 确认的 Q1-Q5，完整实施四步渐进式解析流程：

- **Q1**: condensed_text 采用半结构化 markdown，完整叙事行文，不压缩信息量
- **Q2**: interactions 在 Step 2 先跑以固化 flag 名称 → events + auto_triggers 并行
- **Q3**: LLM 做生成式 cross-validate + 依赖补全，确定性代码做最终验证
- **Q4**: auto_trigger condition 使用自然语言
- **Q5**: 10 LLM calls / 6 串行步，一次性生成成本可接受

**产出**: 设计文档 ×1、实现计划 ×1、10 commits、44 tests

**核心变更**:
- `l2_keeper.py`: HiddenInfo → AutoTrigger
- `l3_designer.py`: 字段同步 + LogicChain/Branch 移除 + SceneIntent 精简
- `layered_parser.py`: 完整重写 (10 prompt builders + 保底策略)
- `layered_pipeline.py`: 重写为并行编排层
- `layered_schema.py` / `l2_template.json`: 同步

详细 changelog: `CHANGELOG_parser_overhaul.md`

---

## 当前架构总览

### 已实现的文件

```
src/
├── library/                    ✓ 完成
│   ├── weapons.py              LibraryWeapon + WeaponLibrary
│   ├── enemies.py              LibraryEnemy + EnemyLibrary
│   ├── judgment.py             JudgmentEngine (T1 deterministic + T2 context builder)
│   └── injector.py             ContentInjector (offline + runtime injection)

├── module_designer/            ✓ 完成 (生成端)
│   ├── l1_player.py            ✓ SceneL1, Perceptible, NPCAppearance
│   ├── l2_keeper.py            ✓ SceneL2 (含 AutoTrigger, HiddenInfo 已移除)
│   ├── l3_designer.py          ✓ 已同步新 l3_template.json
│   ├── layered_schema.py       ✓ 已同步 L2 (auto_triggers) + L3
│   ├── layered_parser.py       ✓ 四步渐进式 (10 prompt builders + _with_fallback)
│   └── layered_pipeline.py     ✓ 并行编排 + retry/fallback

├── scenario_core.py            ⚠ Interaction 缺 skill_name/difficulty
│                                  GameEvent 待扩展 type/effect 字段
│                                  EncounterAnchor 定义但未使用
│                                  auto_trigger 条件解析器未实现

├── prompts.py                  ⚠ _build_l1l3_context 代码已写但未接通

├── game_loop.py                ⚠ _check_deviation 桩, auto_trigger 检测未实现
│    notebook_simplified.ipynb  ⚠ L1/L3 未加载

└── archive/                    ✓ 旧代码已归档
    ├── parsers.py
    └── pipeline.py
```

---

## P0 待办：消费端断点修复

| # | 问题 | 位置 | 修复内容 |
|---|------|------|---------|
| C1 | `Interaction` 缺少 `skill_name`/`difficulty` 字段 | `scenario_core.py:47-56` | 添加两个可选字段，LLM 生成的技能信息不再被丢弃 |
| C2 | L1/L3 数据未加载到 notebook | `notebook_simplified.ipynb` | 加载 L1/L3 JSON，传入 `handle_user_input()` 的 `l1_data`/`l3_data` 参数 |
| C3 | `_check_deviation` 桩永远返回 0.0 | `game_loop.py` | 实现或移除桩 |
| C4 | `EncounterAnchor` 定义但未使用 | `scenario_core.py:101-108` | 接入或移除死代码 |
| C5 | auto_trigger 被动检测逻辑未实现 | `game_loop.py`, `scenario_core.py` | 运行时解析 auto_trigger 的 condition 并触发 |

---

## 建议的起始顺序

1. **C1** — 改动最小，效果最明显（LLM 生成的数据终于能被消费）
2. **C2** — 接通 L1/L3，让叙事真正有"三层感知"
3. **C3 + C4** — 清理死代码或实现桩逻辑
4. **C5** — auto_trigger 运行时解析（依赖 C2 完成后有完整 L2 数据）

---

## 文档导航

| 想了解... | 阅读... |
|-----------|--------|
| 4 步渐进式解析流程 | `docs/superpowers/specs/2026-05-14-progressive-parser-design.md` |
| 实现计划 | `docs/superpowers/plans/2026-05-14-progressive-parser-plan.md` |
| 本轮 changelog | `CHANGELOG_parser_overhaul.md` |
| 消费端断点 | `docs/superpowers/specs/module-runtime/README.md` |
| 全局架构 | `docs/superpowers/specs/2026-05-13-layered-data-flow.md` |

---

## 测试状态

```
tests/test_library.py ............. 17 passed
tests/test_module_designer.py ..... 27 passed
Total: 44 passed

运行: python -m pytest tests/ -v
```
