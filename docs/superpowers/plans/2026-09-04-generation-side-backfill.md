# 生成端回填专项 Implementation Plan

> **For agentic workers:** 任务相互依赖（schema → fixture → lint），在同一工作区按 TDD 顺序执行。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成端 schema 修补 + 样例模组补全 + prompt 最小回填 + `_assemble_l2` 透传 + lint/graph 工具（F33 CLI / F35 CLI）+ 消费端测试盘点补缺，全部确定性测试收口。

**Architecture:** 方案 A 三阶段递进。P1 schema（地基，含中值单一事实源）→ 样例模组 → 契约测试 + scheduled_events 加载桥；P2 prompt 最小回填（STEP2A/STEP4/STEP25）+ `_assemble_l2` 透传；P3 工具（`--strict` 只升 schema、mermaid）。贯穿消费端测试盘点。以 schema 正确为核心，不做真实端到端生成验证。

**Tech Stack:** Python 3.13 / pytest；`src/module_designer/`（layered_schema / layered_parser / lint / dependency_graph / layered_pipeline）；fixture `data/modules/e2e_testbed/`。

**Spec:** `docs/superpowers/specs/2026-09-04-generation-side-backfill-design.md`（2026-09-04 review 修订版）

**已知事实（实现时直接引用，勿重复探索）：**
- 态度档位单一事实源：`src/investigator/rules.py` `_GAME_CONFIG_DEFAULTS["npc_attitude_tiers"]` 与 `data/game_config.json`（`test_shipped_json_matches_defaults` 要求二者全等）。现有行 `{max, label, key}`；本期加 `mid`。`attitude_tier(value)` 已读 `max/key/label`。`npc_manager._ATTITUDE_MIDPOINTS` 是第二份中值表，删除后改读 `mid`。
- 运行时 NPC 档案加载已读 `attitude_value`（npc_manager.py `_resolve_profile_attitude_value`），schema 只是没声明。落盘字段：`scene` / `all_scenes` / `bound_interactions` / `bound_auto_triggers`。STEP25 中间名 `bound_entities` 由 `_extract_entity_bindings` pop。
- `scene_items`：`[{"kind": "item"|"weapon", "ref": str, "quantity": int, "hidden": bool}]`。
- `environment` 合法值：`lighting ∈ {dark, dim, normal}`，`noise ∈ {quiet, noisy}`（默认 quiet；**没有** noise=normal）。`scenario_core.py` EnvChange legal 集为准。
- `attitude_min`：int，interaction 顶层（keeper 先读顶层，extra 兜底）。
- `npc_dead:` requirement 语法：`npc_dead:NPC名`。
- `scheduled_events`：`[{"id", "at_minutes", "markup", "description"}]`；**init_game 当前不读 l2 该键**。
- timed_effects 无模组 JSON 字段，不进 fixture。
- e2e_testbed 现有：测试房间A/B、NPC 测试乘务员、IT_SEARCH/IT_END/AT_ATMO/AT_SPAWN_WANDERER、scene_weapons 小刀、ending END_TEST、boss_encounters、dependency_graph。`IT_END.difficulty=""` 已是 schema warning。
- `validate_l2` 现只校验 scenes/events/npc_profiles/boss_encounters；未知字段静默。`_validate_object` 不报多余键。
- `init_game` 返回 `{"keeper", "narrator", "author", "pending_world_items"}`，世界在 `game["keeper"].world`；默认 `start_node="6号车厢"`。
- lint `run_lint(module_dir) -> int` 已调 `validate_all`；exit 1 仅 error。`python -m module_designer` 走 `__main__.py`，与 `lint.py __main__` 都要接 `--strict`/`--graph`。
- `DependencyGraph.detect_cycles()` 已存在，mermaid 复用，不另写 DFS。
- `_assemble_l2` 只把 `scene_movements` 的 from_here/to_here 写入 scene，丢 scene_items/environment。

---

## P1 — Schema 修补 + 样例模组补全

### Task 1: 生成端 schema 契约测试（先写，红）

**Files:**
- Create: `tests/test_generation_schema.py`

- [ ] **Step 1: 写失败测试**

```python
"""生成端 schema 契约：NPC 态度字段 + 枚举/中值单一事实源 + 场景嵌套（spec §1.1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _attitude_rows():
    from investigator.rules import get_game_config
    return get_game_config()["npc_attitude_tiers"]


class TestNpcProfileSchema:
    def test_attitude_value_field_accepted(self):
        """attitude_value 合法值不产生违规。未知字段静默时本测可能已绿，作锁测。"""
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": -75}}}
        report = validate_l2(data)
        assert not [v for v in report.violations if "attitude_value" in v.path]

    def test_attitude_value_out_of_range_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": 150}}}
        report = validate_l2(data)
        assert any("attitude_value" in v.path and v.severity == "warning"
                   for v in report.violations)

    def test_initial_attitude_enum_aligned_with_runtime(self):
        from module_designer.layered_schema import validate_l2
        keys = [t["key"] for t in _attitude_rows()]
        assert set(keys) == {"hostile", "wary", "neutral", "friendly", "devoted"}
        good = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "devoted"}}}
        assert not [v for v in validate_l2(good).violations
                    if "initial_attitude" in v.path]
        bad = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "allied"}}}
        assert any("initial_attitude" in v.path
                   for v in validate_l2(bad).violations)

    def test_runtime_known_profile_fields_accepted(self):
        from module_designer.layered_schema import L2_NPC_PROFILE_SCHEMA
        for f in ("attitude_value", "scene", "all_scenes",
                  "bound_interactions", "bound_auto_triggers"):
            assert f in L2_NPC_PROFILE_SCHEMA, f"schema 缺字段 {f}"

    def test_attitude_midpoints_single_source(self):
        """中值只来自 game_config.mid；npc_manager 无私有表。"""
        from game.npc_manager import _attitude_value_from_key
        import game.npc_manager as nm
        expected = {"hostile": -75, "wary": -30, "neutral": 0,
                    "friendly": 30, "devoted": 75}
        for row in _attitude_rows():
            assert row["mid"] == expected[row["key"]], row
            assert _attitude_value_from_key(row["key"]) == row["mid"]
        assert not hasattr(nm, "_ATTITUDE_MIDPOINTS")


class TestSceneNestedSchema:
    def test_illegal_noise_value_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"scenes": {"A": {"environment": {"noise": "normal"}}}}
        report = validate_l2(data)
        assert any("noise" in v.path for v in report.violations)

    def test_illegal_scene_item_kind_warns(self):
        from module_designer.layered_schema import validate_l2
        data = {"scenes": {"A": {"scene_items": [
            {"kind": "food", "ref": "面包", "quantity": 1, "hidden": False}]}}}
        report = validate_l2(data)
        assert any("kind" in v.path for v in report.violations)
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_generation_schema.py -q`
Expected: FAIL（无 min/max、无枚举、无 mid、`_ATTITUDE_MIDPOINTS` 仍在、environment/scene_items 无嵌套）

### Task 2: Schema 实现 + 中值单一事实源（转绿）

**Files:**
- Modify: `src/module_designer/layered_schema.py`
- Modify: `src/investigator/rules.py`（`npc_attitude_tiers` 加 `mid`）
- Modify: `data/game_config.json`（与 defaults 全等）
- Modify: `src/game/npc_manager.py`（删 `_ATTITUDE_MIDPOINTS`，读 `mid`）
- Test: `tests/test_generation_schema.py`

- [ ] **Step 1: `_validate_value` 加 min/max（warning 级）**

在枚举值检查块之后插入：

```python
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in rules and value < rules["min"]:
            report.add(f"{path}.{field}",
                       f"值 {value} 低于下限 {rules['min']}", "warning")
        if "max" in rules and value > rules["max"]:
            report.add(f"{path}.{field}",
                       f"值 {value} 高于上限 {rules['max']}", "warning")
```

- [ ] **Step 2: 态度档位从运行时配置派生 + NPC / scene / scheduled schema**

```python
def _attitude_keys() -> tuple:
    from investigator.rules import get_game_config
    return tuple(t["key"] for t in get_game_config()["npc_attitude_tiers"])
```

`L2_NPC_PROFILE_SCHEMA` 补 `initial_attitude.values=_attitude_keys()`、`attitude_value min/max`、`scene`/`all_scenes`/`bound_interactions`/`bound_auto_triggers`。

`L2_SCENE_SCHEMA`：

```python
"scene_items": {"required": False, "list_of": {
    "kind": {"required": False, "values": ["item", "weapon"]},
    "ref": {"required": False},
    "quantity": {"required": False},
    "hidden": {"required": False},
}},
"environment": {"required": False, "nested": {
    "lighting": {"required": False, "values": ["dark", "dim", "normal"]},
    "noise": {"required": False, "values": ["quiet", "noisy"]},
}},
```

`L2_SCHEDULED_EVENT_SCHEMA` + `validate_l2` 校验顶层 `scheduled_events`。`L3_ENDING_CONDITION_SCHEMA` 加 optional `name`。

- [ ] **Step 3: game_config 加 mid；npc_manager 改读 mid**

defaults 与 `data/game_config.json` 同步：

```json
{"max": -50, "label": "敌意", "key": "hostile", "mid": -75}
```

（其余档同：wary -30 / neutral 0 / friendly 30 / devoted 75；devoted 的 max 仍为 null/None。）

```python
def _attitude_value_from_key(key: str | None) -> int:
    if not key:
        return 0
    from investigator.rules import get_game_config
    for row in get_game_config()["npc_attitude_tiers"]:
        if row.get("key") == key:
            return int(row.get("mid", 0) or 0)
    return 0
```

删除 `_ATTITUDE_MIDPOINTS`。

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest tests/test_generation_schema.py tests/test_game_config.py tests/test_npc_attitude.py -q`
Expected: 全绿

### Task 3: 样例模组完备性防漂移测试（先写，红）

**Files:**
- Create: `tests/test_fixture_completeness.py`

- [ ] **Step 1: 写失败测试**

覆盖 spec §1.2：scene_items hidden+exposed、environment 两轴、attitude_value、attitude_min、repeatable、npc_dead、scheduled_events、player_goal、多结局≥2、存量 boss/time_condition/scene_weapons/graded_result/多场景移动。timed_effects 不在此列。

`_all_entities` 扫 scenes 的 interactions/auto_triggers + 顶层 events。

存量断言：
- `any(s.get("scene_weapons") for s in scenes.values())`
- `any(e.get("graded_result") for e in _all_entities(l2))`
- `len(l2["scenes"]) >= 2` 且存在 from_here 跨场景

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_fixture_completeness.py -q`
Expected: 新元素 FAIL；存量可能已绿

### Task 4: e2e_testbed 补全（转绿）

**Files:**
- Modify: `data/modules/e2e_testbed/l2_keeper.json`
- Modify: `data/modules/e2e_testbed/l3_designer.json`

- [ ] **Step 1: l2 增补**

`测试房间A`：
```json
"scene_items": [
  {"kind": "item", "ref": "一页撕碎的笔记", "quantity": 1, "hidden": true},
  {"kind": "item", "ref": "蜡烛", "quantity": 1, "hidden": false}
],
"environment": {"lighting": "dim"}
```
（蜡烛与 L1 描写呼应；hidden 不用第二把钥匙，避免和 IT_SEARCH「测试钥匙」撞车。）

`测试房间B`：`"environment": {"noise": "noisy"}`（呼吸声）。

`IT_END.difficulty` 改为 `"None"`。

interactions 追加：
- `IT_RECHECK`：type **侦查**，`repeatable: true`
- `IT_ASK_REPORT`：type 话术，`attitude_min: -30`，graded_result 四级

`测试房间B` auto_triggers 追加 `AT_CORPSE_REACT`，`requirement: "npc_dead:测试乘务员"`。

顶层 `scheduled_events`：`SE_NIGHT_CHILL` at_minutes=60，markup `@stat_change(stat_name="SAN", delta=-1)`。

`npc_profiles.测试乘务员` 加 `"attitude_value": 10`。

**新增实体不进 dependency_graph**（可选行动；避免实体不可达 warning）。

- [ ] **Step 2: l3 增补**

`module_meta.player_goal`；`ending_conditions` 追加 `END_DEATH`。

- [ ] **Step 3: 完备性测试绿 + 回归**

Run: `python -m pytest tests/test_fixture_completeness.py -q`
Expected: 全绿

Run: `python -m pytest tests/ -q -k "save_load or scene_items or environment or npc_attitude or lint or scheduled"`
Expected: 全绿

### Task 5: scheduled_events 加载桥（断链修复，TDD）

**Files:**
- Modify: `src/game_loop.py`（`world.load_dependency_graph` 之后）
- Test: `tests/test_scheduled_events.py` 追加

- [ ] **Step 1: 写失败测试**

`init_game` 返回 dict。必须传 `start_node="测试房间A"`。

```python
class TestScheduledEventsModuleLoad:
    def test_init_game_loads_scheduled_events(self, tmp_path):
        import json, shutil, os
        src_dir = os.path.join(os.path.dirname(__file__), '..', 'data',
                               'modules', 'e2e_testbed')
        mod = tmp_path / "mod"
        shutil.copytree(src_dir, mod)
        l2p = mod / "l2_keeper.json"
        l2 = json.loads(l2p.read_text(encoding='utf-8'))
        assert l2.get("scheduled_events"), "fixture 应先含 scheduled_events（Task 4）"
        from game_loop import init_game
        game = init_game(str(l2p), str(mod / "l1_player.json"),
                         str(mod / "l3_designer.json"),
                         start_node="测试房间A")
        world = game["keeper"].world
        assert any(e.get("id") == "SE_NIGHT_CHILL" for e in world.scheduled_events)
```

- [ ] **Step 2: 跑测试确认红** → **Step 3: 加载桥**

```python
    world.scheduled_events = [dict(e) for e in l2.get("scheduled_events", [])
                              if isinstance(e, dict)]
```

- [ ] **Step 4: 绿** `python -m pytest tests/test_scheduled_events.py -q`

- [ ] **Step 5: P1 收口提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿

```bash
git add src/module_designer/layered_schema.py src/investigator/rules.py \
        data/game_config.json src/game/npc_manager.py \
        tests/test_generation_schema.py tests/test_fixture_completeness.py \
        data/modules/e2e_testbed/ src/game_loop.py tests/test_scheduled_events.py \
        MAINTENANCE.md docs/superpowers/specs/2026-09-04-generation-side-backfill-design.md \
        docs/superpowers/plans/2026-09-04-generation-side-backfill.md
git commit -m "feat: P1 生成端 schema 修补 + e2e_testbed 全元素补全 + scheduled_events 加载桥"
```

---

## P2 — Prompt 最小回填

### Task 6: Prompt 防回退断言测试（先写，红）

**Files:**
- Create: `tests/test_generation_prompts.py`

- [ ] **Step 1: 写失败测试**

STEP2A：`scene_items` / `environment` / `hidden` / （半数|半值） / （1/5|五分之一） / `repeatable`；且含 `quiet`（noise 合法值）。
STEP4：`@attitude_change` / `@env_change` / `npc_dead:` / `克苏鲁神话`；`@env_change` 说明含 `quiet`。
STEP25：`attitude_value` / `devoted` / `allied not in`。
另：`TestAssembleL2.test_passthrough_scene_items_and_environment` 调 `_assemble_l2`，scene_movements 内带 scene_items+environment，断言进入 `l2["scenes"][name]`。

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_generation_prompts.py -q`

### Task 7: STEP2A 回填 + `_assemble_l2` 透传（转绿）

**Files:**
- Modify: `src/module_designer/layered_parser.py` STEP2A_SYSTEM
- Modify: `src/module_designer/layered_pipeline.py` `_assemble_l2`

- [ ] **Step 1: 原则区追加**（NPC 跟随行之后）

```
- scene_items：场景中可拾取/可发现的物品列表，写在该场景 scene_movements 对象内。[{"kind":"item"|"weapon","ref":"物品名","quantity":1,"hidden":true|false}]。hidden=true 表示需搜索类互动成功后暴露；模组中「最初看不见但可找到」的物品必须 hidden=true
- environment：场景环境状态，写在该场景 scene_movements 对象内。{"lighting":"dark|dim|normal","noise":"quiet|noisy"}，只填非默认轴（默认 lighting=normal、noise=quiet）。黑暗/昏暗会影响搜索类检定
- difficulty 语义：regular=满技能值、hard=技能值半数、extreme=技能值 1/5（运行时真实生效）。仅靠运气或专业训练才能成功的行动应标 hard/extreme，不要全用 regular
- repeatable：默认 once。玩家有合理理由重复执行且重复有意义的实体标 "repeatable": true
```

- [ ] **Step 2: 输出格式** — 示例 interaction 加 `"repeatable": false`；`scene_movements` **每个场景对象内**加：

```
      "scene_items": [{"kind": "item", "ref": "物品名", "quantity": 1, "hidden": true}],
      "environment": {"lighting": "dim"}
```

不要把这两键放在与 scene_movements 同级的全局位置。

- [ ] **Step 3: `_assemble_l2` 透传**

在写入 from_here/to_here 之后：

```python
        if movement.get("scene_items"):
            scenes[sname]["scene_items"] = movement["scene_items"]
        if movement.get("environment"):
            scenes[sname]["environment"] = movement["environment"]
```

- [ ] **Step 4: 跑** `python -m pytest tests/test_generation_prompts.py::TestStep2APrompt tests/test_generation_prompts.py::TestAssembleL2 -q`

### Task 8: STEP4 回填

在 `@npc_follow` 后插入 `@attitude_change` / `@env_change`（明确 lighting∈dark|dim|normal，noise∈quiet|noisy）。time_condition 条之后加 npc_dead 语法 + F8 克苏鲁神话模式。

Run: `python -m pytest tests/test_generation_prompts.py::TestStep4Prompt -q`

### Task 9: STEP25 回填

枚举改为 devoted；`attitude_value` 说明中的中值用 `game_config.npc_attitude_tiers[].mid` 派生（模块加载期拼进 `STEP25_COMBINED_SYSTEM`，JSON 示例里的 `{` `}` 禁止用 str.format，用占位符 replace）。输出格式加 `"attitude_value": 0`。

- [ ] **Step 2: P2 测试 + 全量回归**

Run: `python -m pytest tests/test_generation_prompts.py -q`
Run: `python -m pytest tests/ -q`

- [ ] **Step 3: real_llm_smoke**（402 记录不阻塞）

- [ ] **Step 4: P2 提交**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py \
        tests/test_generation_prompts.py MAINTENANCE.md
git commit -m "feat: P2 生成 prompt 最小回填 + assemble 透传 scene_items/environment"
```

---

## P3 — 工具（F33 CLI / F35 CLI）

### Task 10: F33 lint `--strict`（只升 schema warning）

**Files:**
- Modify: `src/module_designer/lint.py`
- Modify: `src/module_designer/__main__.py`
- Test: `tests/test_module_lint.py` 追加 `TestLintStrict`

- [ ] **Step 1: 失败测试**

`run_lint(mod)` 对 `initial_attitude: allied` → exit 0。
`run_lint(mod, strict=True)` → exit 1。
`run_lint(e2e_testbed, strict=True)` → 0。
另：构造只有「实体不可达」warning、无 schema 问题的模组，`strict=True` 仍 exit 0（锁「strict 不升图 warning」）。

- [ ] **Step 2: 实现**

`run_lint(module_dir: str, strict: bool = False)`：把 `validate_all` 的 warning 在 strict 下以 error 计入（`_add("error", ...)`），cross_validate 与可达性 warning 不动。`return 1 if n_error else 0`。

抽出 `cli_main(argv)`：`--graph` 打印 mermaid 后 exit 0；否则 `run_lint(..., strict="--strict" in flags)`。`lint.py __main__` 与 `module_designer/__main__.py` 都调它。

- [ ] **Step 3: 绿** `python -m pytest tests/test_module_lint.py -q`

### Task 11: F35 mermaid

**Files:**
- Modify: `src/module_designer/dependency_graph.py`（`to_mermaid`，复用 `detect_cycles`）
- Test: `tests/test_dependency_graph.py`

- [ ] **Step 1: 失败测试**

`startswith("flowchart TD")`；节点名在图里；`AT2 --> I1`；结局高亮断言 **`classDef` in m**（不要 `:::`/`style`）；环图 `"环" in m`。

- [ ] **Step 2: 实现 `to_mermaid`**

结局节点 stadium `id(["name"])` + `classDef ending` + `class id ending`。环：`for cyc in self.detect_cycles(): lines.append(f"    %% 环: {' -> '.join(cyc)}")`。

`--graph`：读 l2 `dependency_graph`，有 nodes 则 `from_dict`，否则 `_scene_graph`。

- [ ] **Step 3: 绿 + P3 提交**

Run: `python -m pytest tests/test_dependency_graph.py tests/test_module_lint.py -q`

手测：`python -m module_designer.lint data/modules/e2e_testbed --graph` 与 `python -m module_designer --graph data/modules/e2e_testbed`（入口顺序以 cli_main 解析为准：非 -- 参数为 module_dir）。

```bash
git add src/module_designer/lint.py src/module_designer/__main__.py \
        src/module_designer/dependency_graph.py \
        tests/test_module_lint.py tests/test_dependency_graph.py MAINTENANCE.md
git commit -m "feat: P3 lint --strict 只升 schema + 依赖图 mermaid 导出"
```

---

## P4 — 消费端测试盘点 + 收尾

### Task 12: 消费端测试盘点 → 缺口清单

对照：F17 test_scene_items（含入档）/ F19 test_environment（含入档）/ F23 test_repeatable（含存档往返）/ F18 test_scheduled_events（Task 5 后含模组加载）/ F10 test_periodic_effects / F5 test_insanity / F27/N1 test_npc_attitude / N3 talk_to / N4 npc_dead / B21 TestCombatHpSingleTrack / LLM fallback / F14 / F25 / F31/F32。另核 `run_game.py` 交互路径是否有专测——没有则 ISSUES 登记，不硬造 e2e。

若 test_save_load 缺 scene_items+environment_overrides+scheduled 综合往返，补 `TestNewFieldsSaveRoundtrip`（`make_world`/`make_scene`/`SceneItem` 签名以 helpers 与 side_effects 为准）。attitude/insanity/repeatable 已有专测则不重复。

Run: `python -m pytest tests/test_save_load.py -q`

### Task 13: 文档回写 + 最终收口

- 簇评估 §10：N1 拆分落地；allied→devoted；P0-1/F8 改实态；F19 锚 L2；STEP4 词表；e2e_testbed 全元素；scheduled_events 桥；中值 `mid`；prompt 未做真实生成验证。
- ISSUES：F33 **仅 CLI schema** 备注进 §5，§2 行改为「前端编辑器/手写工作流仍缺」；F35 CLI mermaid 进 §5，前端留 §4；§4 生成管线清单追加本专项收口句。Task 12 新缺口登 §1/§2。
- MAINTENANCE.md 同步新文件/函数行号。
- `python -m pytest tests/ -q` 全绿后提交。

```bash
git add docs/ MAINTENANCE.md tests/
git commit -m "docs: 生成端回填专项收口 — §10 回写 + F33/F35 CLI 收口 + 测试盘点"
```

---

## Self-Review 记录

- Spec 覆盖：§1.1→Task 1-2；§1.2→Task 3-4；§1.3→Task 1/3/5；§2→Task 6-9；§3.1→Task 10；§3.2→Task 11；§4→Task 12；§5→Task 13。timed_effects 不进 fixture。`--strict` 只升 schema。environment noise=quiet。init_game 返回 dict。mermaid 断言 classDef。F33 不关前端手写路径。
- `_assemble_l2` 透传是 P2 附带，让「有能力产出」落地，不是管线系统升级。
- 占位符：无。JSON 示例禁止 str.format 以免打到 STEP25 的 `{`。

---

## 执行情况（2026-09-04）

**状态：plan / spec 已按审查修订，代码未开工。** 对照 spec 原稿、簇评估 §10、`ISSUES.md`、`design.md` 三层模型，以及 `layered_schema` / `lint` / `npc_manager` / `game_loop` / `e2e_testbed` 现码。初稿按原文落地会红或验收打架；下列条目已吸收进本文与 `2026-09-04-generation-side-backfill-design.md`。

### 审查发现 → 处置

| # | 发现 | 处置（已写入 plan/spec） |
|---|---|---|
| 1 | `--strict` 升全部 warning，与 Task 4「不可达 warning 不挡」、验收「testbed 过 strict」互斥；`IT_END.difficulty=""` 已是 schema warning | `--strict` **只升 `validate_all` 的 schema warning**；可达性保持 warning。Task 4 改 `IT_END.difficulty="None"`；新实体不进 dependency_graph |
| 2 | STEP2A 把 `noise` 写成 `normal`；运行时合法值是 `quiet\|noisy` | 词表与示例改为 `lighting∈dark\|dim\|normal`，`noise∈quiet\|noisy`；schema 嵌套校验锁非法轴值 |
| 3 | mermaid 测试要 `:::`/`style`，实现用 `classDef`；另写 `_find_cycles` 与已有 `detect_cycles` 重复 | 断言 `classDef`；环复用 `detect_cycles()` |
| 4 | Task 5 用 `game.world`；`init_game` 返回 dict，世界在 `game["keeper"].world`；默认起点 `6号车厢` | 测试改 dict 取 world，显式 `start_node="测试房间A"` |
| 5 | spec §1.1.3 中值单一事实源未做；`_ATTITUDE_MIDPOINTS` 与 STEP25 字面量是第二、三份 | `npc_attitude_tiers[].mid`；删私有表；STEP25 加载期派生，禁止第三份字面量 |
| 6 | STEP2A 只改 prompt，`_assemble_l2` 丢 scene 级字段；全局同级键会对不上每场景一份 | 字段写进 **每个** `scene_movements` 对象；P2 附带透传几行（非管线系统升级） |
| 7 | F33 整项搬 §5 会误关「手写模组/前端编辑器」 | 只收口 CLI schema；§2 手写/前端仍在。F35 前端留 §4 |
| 8 | 完备性未锁存量 scene_weapons / graded_result / 多场景；`IT_RECHECK` 写成「侦察」；hidden 钥匙与「测试钥匙」撞车 | 存量三项进防漂移测试；技能名「侦查」；hidden 改为「一页撕碎的笔记」 |

### 明确缺口（本期不修，收口时写 ISSUES / §10）

- 真实端到端模组生成验证不做。`pytest -m real_llm_smoke` 打的是对局主路径，**覆盖不到** `layered_parser`，P2 只作仪式性收口（402 不阻塞）。
- 未知字段仍静默（schema 引擎既有行为）。
- timed_effects 无模组 JSON 字段，不进 fixture。
- `run_game.py` 交互路径：Task 12 盘点，缺则登记 ISSUES，不硬造 e2e。

### 代码进度（2026-09-04 收口）

全部完成：`c8904c5` P1 schema + testbed 全元素 + scheduled_events 桥；`9c3d6b8` P2 prompt 最小回填 + assemble 透传；`916e57c` P3 lint --strict + mermaid；`ae9c526` P4 §10/ISSUES 回写 + save/load 新字段往返。收口 `python -m pytest tests/ -q`：**556 passed / 28 deselected**。明确缺口已写入 ISSUES §4 与簇评估 §10（每行标「未做真实生成验证」）。
