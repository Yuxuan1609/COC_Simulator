# Project To-Do

**更新日期**: 2026-05-14
**上轮完成**: 四步渐进式解析器重写（10 commits, 44 tests）

---

## P0 — 消费端断点（运行时）

| # | 任务 | 位置 | 说明 |
|---|------|------|------|
| C1 | Interaction 添加 `skill_name`/`difficulty` 字段 | `scenario_core.py` | 两个可选字段，让 LLM 生成的技能数据不被丢弃 |
| C2 | 接通 L1/L3 加载路径 | `notebook_simplified.ipynb` | 加载 L1/L3 JSON，传入 `handle_user_input()` |
| C3 | `_check_deviation` 实现或移除 | `game_loop.py` | 当前为桩（返回 0.0），要么实现偏离检测要么清理 |
| C4 | `EncounterAnchor` 接入或移除 | `scenario_core.py` | 定义但未使用 |
| C5 | auto_trigger 运行时条件解析 | `game_loop.py` | 解析自然语言 condition 并触发 reveal/spawn/grant |

---

## P1 — 结构改进

| # | 任务 | 位置 | 说明 |
|---|------|------|------|
| S1 | 提取 `LibraryBase` | `library/weapons.py` + `enemies.py` | WeaponLibrary / EnemyLibrary 80% 重复 |
| S2 | 统一序列化 mixin | l1_player, l2_keeper, l3_designer | ~15 数据类手写 to_dict/from_dict |
| S3 | Schema 与数据模型统一 | `layered_schema.py` vs 数据模型 | 字段变更时需同步两处 |
| S4 | 封装 LLM 抽象 | `layered_parser.py` | `llm_call` 参数泄漏到所有 parse 函数 |

---

## P2 — 功能增强

| # | 任务 | 位置 | 说明 |
|---|------|------|------|
| F1 | `_load_template` 缓存 | `layered_parser.py` | 每次从磁盘读取，加 `@lru_cache` |
| F2 | `_safe_parse_json` / `_clean_json` 集成 | `layered_parser.py` | 已定义但 parse 函数未使用（llm_json 内部已处理） |
| F3 | Step 4 `l2_descriptions` 丰富化 | `layered_pipeline.py` | 当前从 L1 提取基础描述，可加入 condensed_text 摘要 |
| F4 | 管线超时机制 | `layered_pipeline.py` | LLM 调用和 ThreadPoolExecutor 无 timeout |
| F5 | `ThreadPoolExecutor` import 提到模块顶部 | `layered_pipeline.py` | 当前在函数体内 import |

---

## P3 — 文档与测试

| # | 任务 | 说明 |
|---|------|------|
| D1 | parse 函数集成测试 | 以 mock llm_call 测试 parse 函数被正确调用 |
| D2 | `_with_fallback` 边界测试 | max_retries=0、required_keys=[] 等边界情况 |
| D3 | 实际运行验证 | 在 notebook 中完整运行 pipeline，检查 LLM 输出质量 |
| D4 | Step 1 内容关细化 | 运行后根据实际 LLM 输出质量定义更精确的 condensed_text 校验 |

---

## 已完成（本轮）

| 日期 | 内容 | Commits | Tests |
|------|------|---------|-------|
| 2026-05-13 | 三层信息模型 + 武器/敌人库 + 双层判定 + 内容注入 | 9 | 34 |
| 2026-05-14 | 四步渐进式解析器重写 + 保底策略 | 11 | 44 |
| 2026-05-14 | 文档更新：CHANGELOG, README, NEXT-SESSION, spec indexes, schema overview | 2 | — |

---

## 核心文档快速导航

| 想了解... | 阅读... |
|-----------|--------|
| 当前架构全貌 + 下一步 | `docs/superpowers/specs/NEXT-SESSION.md` |
| 四步渐进式解析设计 | `docs/superpowers/specs/2026-05-14-progressive-parser-design.md` |
| 三层 Schema 字段定义 | `docs/superpowers/specs/2026-05-13-three-layer-schema-overview.md` |
| 数据流向（历史 + 提案） | `docs/superpowers/specs/2026-05-13-layered-data-flow.md` |
| 本轮 changelog | `CHANGELOG_parser_overhaul.md` |
| 模组生成 spec 索引 | `docs/superpowers/specs/module-generation/README.md` |
| 模组运行 spec 索引 | `docs/superpowers/specs/module-runtime/README.md` |
