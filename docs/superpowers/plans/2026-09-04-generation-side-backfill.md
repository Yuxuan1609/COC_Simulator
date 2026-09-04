# 生成端回填专项 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 生成端 schema 修补 + 样例模组补全 + prompt 最小回填 + lint/graph 工具（F33/F35）+ 消费端测试盘点补缺，全部确定性测试收口。

**Architecture:** 方案 A 三阶段递进。P1 schema（地基）→ 样例模组（e2e_testbed 补全设计元素）→ 契约测试；P2 prompt 最小回填（STEP2A/STEP4/STEP25）；P3 工具（lint --strict、dependency_graph mermaid）。贯穿消费端测试盘点。以 schema 正确为核心，不做真实端到端生成验证（明确缺口标注）。

**Tech Stack:** Python 3.13 / pytest；`src/module_designer/`（layered_schema / layered_parser / lint / dependency_graph）；fixture `data/modules/e2e_testbed/`。

**Spec:** `docs/superpowers/specs/2026-09-04-generation-side-backfill-design.md`

**已知事实（实现时直接引用，勿重复探索）：**
- 态度五档单一事实源在 `src/investigator/rules.py:322` 的 `get_game_config()["npc_attitude_tiers"]`（list of `{max, label, key}`，key ∈ hostile/wary/neutral/friendly/devoted）。`src/game/npc_manager.py:48` 的 `attitude_tier(value)` 消费它。schema 侧**派生**引用，禁止复制字面量。
- 运行时 NPC 档案加载已读 `attitude_value`（npc_manager.py:64-69 `_resolve_profile_attitude_value`），schema 只是没声明。
- `scene_items` 数据形状：`[{"kind": "item"|"weapon", "ref": str, "quantity": int, "hidden": bool}]`（scenario_core.py:736-743 加载）。
- `environment` 数据形状：`{"lighting": "dark"|"dim"|..., "noise": "noisy"|...}`（两轴，test_environment.py 为准）。
- `attitude_min`：int，放 interaction 顶层（keeper.py:393 先读顶层，extra 兜底）。
- `npc_dead:` requirement 语法：`npc_dead:NPC名`（N4，judge 解析）。
- `scheduled_events` 形状：`[{"id", "at_minutes", "markup", "description"}]`（scenario_core.py:720）；**init_game 当前不读 l2 的 scheduled_events 键**（断链，Task 5 修）。
- spec §1.2 的「timed_effects interval+payload 一例」修正：timed_effects 是 markup 驱动的运行时玩家状态，模组 JSON 无对应字段，由既有 `tests/test_periodic_effects.py` 覆盖，不进 fixture（spec 偏差备注，收口时回写）。
- e2e_testbed 现有：场景 测试房间A/测试房间B、NPC 测试乘务员、IT_SEARCH/IT_END/AT_ATMO/AT_SPAWN_WANDERER、scene_weapons 小刀、ending END_TEST、bos s_encounters、dependency_graph。
- `validate_l2`（layered_schema.py:287）只校验 scenes/events/npc_profiles/boss_encounters，顶层其他键（如 scheduled_events）被忽略，无需 schema 改动。
- lint `run_lint(module_dir) -> int`（lint.py:48），已调 `validate_all`；schema 违规目前全是 warning 级 → exit code 恒 0，F33 要加 `--strict`。

---

## P1 — Schema 修补 + 样例模组补全

### Task 1: 生成端 schema 契约测试（先写，红）

**Files:**
- Create: `tests/test_generation_schema.py`

- [ ] **Step 1: 写失败测试**

```python
"""生成端 schema 契约：NPC 态度字段 + 枚举对齐（spec §1.1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _attitude_keys():
    from investigator.rules import get_game_config
    return [t["key"] for t in get_game_config()["npc_attitude_tiers"]]


class TestNpcProfileSchema:
    def test_attitude_value_field_accepted(self):
        """attitude_value 是合法 optional 字段，合法值不产生违规。"""
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": -75}}}
        report = validate_l2(data)
        assert not [v for v in report.violations if "attitude_value" in v.path]

    def test_attitude_value_out_of_range_warns(self):
        """attitude_value 超出 -100~100 → warning。"""
        from module_designer.layered_schema import validate_l2
        data = {"npc_profiles": {"张三": {"name": "张三", "attitude_value": 150}}}
        report = validate_l2(data)
        assert any("attitude_value" in v.path and v.severity == "warning"
                   for v in report.violations)

    def test_initial_attitude_enum_aligned_with_runtime(self):
        """initial_attitude 枚举 = 运行时五档（单一事实源派生），allied 非法。"""
        from module_designer.layered_schema import validate_l2
        keys = _attitude_keys()
        assert set(keys) == {"hostile", "wary", "neutral", "friendly", "devoted"}
        good = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "devoted"}}}
        assert not [v for v in validate_l2(good).violations
                    if "initial_attitude" in v.path]
        bad = {"npc_profiles": {"张三": {"name": "张三", "initial_attitude": "allied"}}}
        assert any("initial_attitude" in v.path
                   for v in validate_l2(bad).violations)

    def test_runtime_known_profile_fields_accepted(self):
        """运行时/真实模组已有的 profile 字段不再是未知字段：scene/all_scenes/bound_*。"""
        from module_designer.layered_schema import L2_NPC_PROFILE_SCHEMA
        for f in ("attitude_value", "scene", "all_scenes",
                  "bound_interactions", "bound_auto_triggers"):
            assert f in L2_NPC_PROFILE_SCHEMA, f"schema 缺字段 {f}"
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_generation_schema.py -q`
Expected: FAIL（attitude_value 等字段不在 schema、无 min/max 规则）

### Task 2: Schema 实现（转绿）

**Files:**
- Modify: `src/module_designer/layered_schema.py`（L2_NPC_PROFILE_SCHEMA :71-85；_validate_value :232-261）
- Test: `tests/test_generation_schema.py`

- [ ] **Step 1: `_validate_value` 加 min/max 数值检查（warning 级）**

在枚举值检查块（:245-251）之后插入：

```python
    # 数值范围检查
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in rules and value < rules["min"]:
            report.add(f"{path}.{field}",
                       f"值 {value} 低于下限 {rules['min']}", "warning")
        if "max" in rules and value > rules["max"]:
            report.add(f"{path}.{field}",
                       f"值 {value} 高于上限 {rules['max']}", "warning")
```

- [ ] **Step 2: 态度档位从运行时配置派生 + NPC profile schema 补齐**

文件顶部 import 区后加：

```python
def _attitude_keys() -> tuple:
    """态度档位从运行时 game_config 派生（单一事实源，禁复制字面量）。"""
    from investigator.rules import get_game_config
    return tuple(t["key"] for t in get_game_config()["npc_attitude_tiers"])
```

`L2_NPC_PROFILE_SCHEMA` 改为（替换 :71-85 整段）：

```python
L2_NPC_PROFILE_SCHEMA = {
    "name": {"required": True},
    "role": {"required": False},
    "personality_notes": {"required": False},
    "appearance": {"required": False},
    "what_they_can_do": {"required": False},
    "interaction_triggers": {"required": False},
    "initial_state": {"required": False},
    "initial_attitude": {"required": False, "values": _attitude_keys()},
    "attitude_value": {"required": False, "min": -100, "max": 100},
    "initial_following": {"required": False},
    "can_interact": {"required": False},
    "can_follow": {"required": False},
    "follow_requirements": {"required": False},
    "interact_requirements": {"required": False},
    "scene": {"required": False},
    "all_scenes": {"required": False},
    "bound_interactions": {"required": False},
    "bound_auto_triggers": {"required": False},
}
```

注意：`_attitude_keys()` 在 import 时即调用（模块加载期读 game_config）——若担心 import 顺序，改为 `"values": tuple(...)` 内联调用即可；investigator.rules 无 module_designer 反向依赖，无环。

- [ ] **Step 3: 跑测试确认绿**

Run: `python -m pytest tests/test_generation_schema.py -q`
Expected: 4 passed

### Task 3: 样例模组完备性防漂移测试（先写，红）

**Files:**
- Create: `tests/test_fixture_completeness.py`

- [ ] **Step 1: 写失败测试**

```python
"""e2e_testbed 样例模组完备性：模组数据层已设计元素必须有实例承载（spec §1.2）。

新增模组数据层机制时：① e2e_testbed 加实例 ② 此处加检查。两者必须同步。
timed_effects 为 markup 驱动运行时状态，无模组字段，由 test_periodic_effects.py 覆盖，不在此列。
"""
import json
import os

TESTBED = os.path.join(os.path.dirname(__file__), '..', 'data',
                       'modules', 'e2e_testbed')


def _load(name):
    with open(os.path.join(TESTBED, name), encoding='utf-8') as f:
        return json.load(f)


def _all_entities(l2):
    for s in (l2.get("scenes") or {}).values():
        yield from s.get("interactions") or []
        yield from s.get("auto_triggers") or []
    yield from l2.get("events") or []


class TestFixtureCompleteness:
    def test_scene_items_hidden_and_exposed(self):
        l2 = _load("l2_keeper.json")
        items = [i for s in l2["scenes"].values()
                 for i in (s.get("scene_items") or [])]
        assert any(i.get("hidden") for i in items), "缺 hidden scene_item 实例"
        assert any(not i.get("hidden") for i in items), "缺 exposed scene_item 实例"

    def test_environment_two_axes(self):
        l2 = _load("l2_keeper.json")
        envs = [s.get("environment") for s in l2["scenes"].values()
                if s.get("environment")]
        assert any("lighting" in e for e in envs), "缺 environment.lighting 实例"
        assert any("noise" in e for e in envs), "缺 environment.noise 实例"

    def test_npc_attitude_value_and_attitude_min(self):
        l2 = _load("l2_keeper.json")
        profiles = l2.get("npc_profiles") or {}
        assert any(p.get("attitude_value") is not None
                   for p in profiles.values()), "缺 NPC attitude_value 实例"
        assert any(e.get("attitude_min") is not None or
                   (e.get("extra") or {}).get("attitude_min") is not None
                   for e in _all_entities(l2)), "缺 interaction attitude_min 实例"

    def test_repeatable_entity(self):
        l2 = _load("l2_keeper.json")
        assert any(e.get("repeatable") for e in _all_entities(l2)), \
            "缺 repeatable: true 实体实例"

    def test_npc_dead_requirement(self):
        l2 = _load("l2_keeper.json")
        assert any("npc_dead:" in (e.get("requirement") or "")
                   for e in _all_entities(l2)), "缺 npc_dead: requirement 实例"

    def test_scheduled_events(self):
        l2 = _load("l2_keeper.json")
        evs = l2.get("scheduled_events") or []
        assert any(e.get("at_minutes") and e.get("markup")
                 for e in evs), "缺 scheduled_events 实例"

    def test_player_goal(self):
        l3 = _load("l3_designer.json")
        assert (l3.get("module_meta") or {}).get("player_goal"), \
            "缺 module_meta.player_goal"

    def test_multiple_endings(self):
        l3 = _load("l3_designer.json")
        assert len(l3.get("ending_conditions") or []) >= 2, \
            "缺多结局实例（>=2 个 ending_conditions）"

    def test_boss_encounter_and_time_condition_present(self):
        """存量元素回归：boss_encounters / time_condition 仍在。"""
        l2 = _load("l2_keeper.json")
        assert l2.get("boss_encounters"), "boss_encounters 缺失"
        assert any(e.get("time_condition") for e in _all_entities(l2)), \
            "缺 time_condition 实例"
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_fixture_completeness.py -q`
Expected: 多数 FAIL（8 元素当前全缺；boss/time_condition 视现状可能已绿）

### Task 4: e2e_testbed 补全（转绿）

**Files:**
- Modify: `data/modules/e2e_testbed/l2_keeper.json`
- Modify: `data/modules/e2e_testbed/l3_designer.json`
- Modify: `data/modules/e2e_testbed/l1_player.json`（仅当场景描述需呼应 environment 时，可选）

- [ ] **Step 1: l2_keeper.json 增补**

在 `scenes.测试房间A` 对象内追加键：

```json
"scene_items": [
  {"kind": "item", "ref": "生锈的钥匙", "quantity": 1, "hidden": true},
  {"kind": "item", "ref": "蜡烛", "quantity": 1, "hidden": false}
],
"environment": {"lighting": "dim", "noise": "noisy"}
```

在 `scenes.测试房间B` 的 auto_triggers 数组追加（npc_dead 实例）：

```json
{"id": "AT_CORPSE_REACT", "type": "无", "name": "乘务员尸体异变",
 "requirement": "npc_dead:测试乘务员",
 "trigger": "测试乘务员死亡后玩家进入测试房间B",
 "result": "乘务员的尸体不见了，地上拖着一道暗色的痕迹。",
 "side_effects": [], "difficulty": "None", "scene": "测试房间B",
 "time_condition": [{"day": ">=1", "times": ["夜间"]}]}
```

在 `scenes.测试房间A` 的 interactions 数组追加（repeatable + attitude_min 实例）：

```json
{"id": "IT_RECHECK", "scene": "测试房间A", "type": "侦察",
 "name": "复查墙壁刻痕", "requirement": "",
 "trigger": "玩家再次仔细检查墙壁刻痕时",
 "result": "刻痕的排列似乎比记忆中多了一组。",
 "side_effects": [], "difficulty": "regular", "time_condition": [],
 "repeatable": true}
```

和（attitude_min 实例，需先有 NPC 态度门槛）：

```json
{"id": "IT_ASK_REPORT", "scene": "测试房间A", "type": "话术",
 "name": "向乘务员索要血书情报", "requirement": "",
 "trigger": "玩家向测试乘务员打听血书的来历时",
 "result": "##GRADED##",
 "graded_result": {"on_failure": "乘务员含糊地岔开了话题。",
   "on_regular": "乘务员压低声音透露了血书的一部分内容。",
   "on_hard": "乘务员把血书的来历和盘托出。",
   "on_extreme": "乘务员不仅说出全部，还主动提出带路。"},
 "difficulty": "regular", "time_condition": [], "attitude_min": -30}
```

顶层（与 `scenes` 平级）追加：

```json
"scheduled_events": [
  {"id": "SE_NIGHT_CHILL", "at_minutes": 60,
   "markup": "@stat_change(stat_name=\"SAN\", delta=-1)",
   "description": "入夜后石室温度骤降，调查员心神不宁"}
]
```

`npc_profiles.测试乘务员` 对象内追加：

```json
"attitude_value": 10
```

注意：
- 时间基准：`at_minutes` 为从开局起算的分钟数（test_scheduled_events.py 语义），取 60 不与现有测试冲突（fixture 当前无其他 scheduled 消费者）。
- 追加键时保持 JSON 合法（前一键尾逗号）。
- IT_RECHECK/IT_ASK_REPORT 若进 dependency_graph 节点集，同步在 `dependency_graph` 键补节点（先读现有 dependency_graph 结构再决定；若 lint 报不可达 warning 属预期——它们是玩家可选行动，warning 级不挡）。

- [ ] **Step 2: l3_designer.json 增补**

`module_meta` 内追加：

```json
"player_goal": "调查石室血书的来历，活着离开这座石室"
```

`ending_conditions` 数组追加第二结局：

```json
{"id": "END_DEATH", "name": "陨落结局",
 "condition": "调查员 HP 降至 0 或 SAN 归零",
 "narrative": "石室重归寂静，符号在墙上微微发亮，等待下一位访客。"}
```

- [ ] **Step 3: 跑完备性测试确认绿**

Run: `python -m pytest tests/test_fixture_completeness.py -q`
Expected: 9 passed

- [ ] **Step 4: 回归 e2e_testbed 消费者**

Run: `python -m pytest tests/ -q -k "save_load or scene_items or environment or npc_attitude or lint or scheduled"`
Expected: 全绿（fixture 改动不得破坏现有消费测试；若 test_module_lint 对 testbed 断言了旧内容，按其断言语义更新）

### Task 5: scheduled_events 加载桥（断链修复，TDD）

**Files:**
- Modify: `src/game_loop.py`（init_game，world 构造后 :247 附近）
- Test: `tests/test_scheduled_events.py` 追加

- [ ] **Step 1: 写失败测试**

`tests/test_scheduled_events.py` 末尾追加：

```python
class TestScheduledEventsModuleLoad:
    def test_init_game_loads_scheduled_events(self, tmp_path):
        """l2 JSON 顶层 scheduled_events 键 → world.scheduled_events（断链修复）。"""
        import json
        import shutil
        src_dir = os.path.join(os.path.dirname(__file__), '..', 'data',
                               'modules', 'e2e_testbed')
        mod = tmp_path / "mod"
        shutil.copytree(src_dir, mod)
        l2p = mod / "l2_keeper.json"
        l2 = json.loads(l2p.read_text(encoding='utf-8'))
        assert l2.get("scheduled_events"), "fixture 应先含 scheduled_events（Task 4）"
        from game_loop import init_game
        game = init_game(str(l2p), str(mod / "l1_player.json"),
                         str(mod / "l3_designer.json"))
        assert any(e.get("id") == "SE_NIGHT_CHILL"
                   for e in game.world.scheduled_events)
```

注意：先确认 `init_game` 返回对象属性名（`game.world`？读 game_loop.py:155 函数签名与返回）；若签名不同按实际调整。

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_scheduled_events.py::TestScheduledEventsModuleLoad -q`
Expected: FAIL（world.scheduled_events 为空）

- [ ] **Step 3: 实现加载桥**

`src/game_loop.py` 在 `world.load_dependency_graph(dep_graph)`（:251）之后插入：

```python
    # F18 时刻事件：l2 顶层 scheduled_events 键入运行时队列
    world.scheduled_events = [dict(e) for e in l2.get("scheduled_events", [])
                              if isinstance(e, dict)]
```

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest tests/test_scheduled_events.py -q`
Expected: 全绿

- [ ] **Step 5: P1 收口提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿（约 540+ passed）

```bash
git add src/module_designer/layered_schema.py tests/test_generation_schema.py \
        tests/test_fixture_completeness.py data/modules/e2e_testbed/ \
        src/game_loop.py tests/test_scheduled_events.py MAINTENANCE.md
git commit -m "feat: P1 生成端 schema 修补 + e2e_testbed 全元素补全 + scheduled_events 加载桥"
```

MAINTENANCE.md 同步：L2_NPC_PROFILE_SCHEMA 新字段、`_validate_value` min/max、init_game scheduled_events 行、两个新测试文件。

---

## P2 — Prompt 最小回填

### Task 6: Prompt 防回退断言测试（先写，红）

**Files:**
- Create: `tests/test_generation_prompts.py`

- [ ] **Step 1: 写失败测试**

```python
"""生成 prompt 最小回填防回退：新字段/词表/语义必须出现在 prompt 文本中（spec §2）。

只断言「说明存在」，不断言教学措辞——prompt 从简约定，管线系统升级时允许重写措辞。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestStep2APrompt:
    def test_scene_items_and_environment_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "scene_items" in STEP2A_SYSTEM
        assert "environment" in STEP2A_SYSTEM
        assert "hidden" in STEP2A_SYSTEM  # scene_items 的 hidden 字段

    def test_difficulty_semantics_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "半数" in STEP2A_SYSTEM or "半值" in STEP2A_SYSTEM  # hard 语义
        assert "1/5" in STEP2A_SYSTEM or "五分之一" in STEP2A_SYSTEM  # extreme 语义

    def test_repeatable_documented(self):
        from module_designer.layered_parser import STEP2A_SYSTEM
        assert "repeatable" in STEP2A_SYSTEM


class TestStep4Prompt:
    def test_new_markup_verbs_documented(self):
        from module_designer.layered_parser import STEP4_SYSTEM
        assert "@attitude_change" in STEP4_SYSTEM
        assert "@env_change" in STEP4_SYSTEM
        assert "npc_dead:" in STEP4_SYSTEM

    def test_mythos_pattern_documented(self):
        from module_designer.layered_parser import STEP4_SYSTEM
        assert "克苏鲁神话" in STEP4_SYSTEM  # F8 模式推荐


class TestStep25Prompt:
    def test_attitude_value_in_output(self):
        from module_designer.layered_parser import STEP25_COMBINED_SYSTEM
        assert "attitude_value" in STEP25_COMBINED_SYSTEM
        assert "devoted" in STEP25_COMBINED_SYSTEM
        assert "allied" not in STEP25_COMBINED_SYSTEM  # 枚举漂移修复
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_generation_prompts.py -q`
Expected: 多数 FAIL（当前 STEP25 含 allied、无 attitude_value 等）

### Task 7: STEP2A 回填（转绿 1/3）

**Files:**
- Modify: `src/module_designer/layered_parser.py` STEP2A_SYSTEM（:377-398 原则区 + :402-419 输出格式区）

- [ ] **Step 1: 原则区追加（:397 附近，`NPC 跟随/离开实体由管线…` 行之后）**

```
- scene_items：场景中可拾取/可发现的物品列表，[{"kind":"item"|"weapon","ref":"物品名","quantity":1,"hidden":true|false}]。hidden=true 表示需搜索类互动成功后暴露（在对应 entity 的 result 中描述发现）；模组中「最初看不见但可找到」的物品必须 hidden=true
- environment：场景环境状态，{"lighting":"normal|dim|dark","noise":"normal|noisy"}，只填非默认轴。黑暗/昏暗环境会影响搜索类检定（运行时自动施加修正），模组有黑暗场景时填 "lighting":"dark" 或 "dim"
- difficulty 语义：regular=满技能值、hard=技能值半数、extreme=技能值 1/5（运行时真实生效）。仅靠运气或专业训练才能成功的行动应标 hard/extreme，不要全用 regular
- repeatable：默认 once（完成即不可再做）。玩家有合理理由重复执行且重复有意义的实体（如复查现场、再次打听）标 "repeatable": true
```

- [ ] **Step 2: 输出格式示例 entity（:405-418）加两键示例**

在示例 interaction 的 `"based_on": null` 前加：

```
      "repeatable": false,
```

在输出格式顶层 `"scene_movements"` 前加场景级示例键：

```
  "scene_items": [{"kind": "item", "ref": "物品名", "quantity": 1, "hidden": true}],
  "environment": {"lighting": "dim", "noise": "normal"},
```

注意：实际输出 JSON 结构以 scene 为键——把这两个键写进 scene_movements 同级的说明文字里（「每个场景可同时输出 scene_items / environment 键」），不破坏现有 scene_movements 结构约定。

- [ ] **Step 3: 跑测试**

Run: `python -m pytest tests/test_generation_prompts.py::TestStep2APrompt -q`
Expected: 3 passed

### Task 8: STEP4 回填（转绿 2/3）

**Files:**
- Modify: `src/module_designer/layered_parser.py` STEP4_SYSTEM markup 列表（:1405 `@npc_follow` 块之后）

- [ ] **Step 1: markup 词表追加**

在 `@npc_follow` 条目后插入：

```
    @attitude_change(npc_name="NPC名", delta=±10)
      用法：NPC 对调查员的态度数值变化（-100~100，正数改善）。交谈/事件导致态度转变时使用。npc_name 必须与 NPC 列表精确一致。
    @env_change(axis="lighting|noise", value="新值")
      用法：永久改变当前场景的环境轴状态（如点灯后 lighting 从 dark 变 normal）。axis 仅限 lighting/noise。
```

- [ ] **Step 2: requirement 语法说明追加（:1419 time_condition 校验条之后）**

```
8. **npc_dead 前置语法**: requirement 中可写 `npc_dead:NPC名`，表示「该 NPC 死亡后才可触发」（npc_name 必须与 NPC 列表精确一致）。死亡连锁反应类 auto_trigger 使用此语法。
9. **克苏鲁神话增长（F8 模式）**: 阅读典籍/目击神话生物类的 entity，在 graded_result 或 side_effects 中挂 @stat_change(stat_name="克苏鲁神话", delta=+N)。仅这两类情境使用，普通事件不要挂。
```

- [ ] **Step 3: 跑测试**

Run: `python -m pytest tests/test_generation_prompts.py::TestStep4Prompt -q`
Expected: 2 passed

### Task 9: STEP25 回填（转绿 3/3）

**Files:**
- Modify: `src/module_designer/layered_parser.py` STEP25_COMBINED_SYSTEM（:744 枚举行 + :779-780 输出格式）

- [ ] **Step 1: 枚举漂移修复 + attitude_value 说明**

:744 行改为：

```
- initial_attitude：NPC 初始态度，默认 "neutral"（可选值：hostile / wary / neutral / friendly / devoted）
- attitude_value：NPC 初始态度数值（-100~100 整数），与 initial_attitude 档位一致（hostile≈-75, wary≈-30, neutral=0, friendly≈30, devoted≈75）。态度对剧情有明确影响的 NPC 两字段都填；其余只填 initial_attitude
```

输出格式（:780 `"initial_attitude": "neutral",` 后）加一行：

```
      "attitude_value": 0,
```

- [ ] **Step 2: 跑 P2 全部测试 + 全量回归**

Run: `python -m pytest tests/test_generation_prompts.py -q`
Expected: 7 passed

Run: `python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 3: prompt 主路径改动 → real_llm_smoke**

Run: `python -m pytest -m real_llm_smoke -q`
Expected: 6 passed（若 402 且 fallback 未生效则记录，不阻塞提交）

- [ ] **Step 4: P2 收口提交**

```bash
git add src/module_designer/layered_parser.py tests/test_generation_prompts.py MAINTENANCE.md
git commit -m "feat: P2 生成 prompt 最小回填 — STEP2A/STEP4/STEP25 新字段词表 + allied→devoted 枚举修复"
```

---

## P3 — 工具（F33 / F35）

### Task 10: F33 lint --strict（TDD）

**Files:**
- Modify: `src/module_designer/lint.py`（run_lint :48-118 + `__main__` :121-122）
- Test: `tests/test_module_lint.py` 追加

- [ ] **Step 1: 写失败测试**

`tests/test_module_lint.py` 末尾追加：

```python
class TestLintStrict:
    def _write_module(self, tmp_path, l2_overrides):
        import json
        mod = tmp_path / "mod"
        mod.mkdir()
        base = {"scenes": {}, "events": [], "npc_profiles": {},
                "boss_encounters": [], "dependency_graph": {}}
        base.update(l2_overrides)
        (mod / "l2_keeper.json").write_text(
            json.dumps(base, ensure_ascii=False), encoding='utf-8')
        (mod / "l1_player.json").write_text("{}", encoding='utf-8')
        (mod / "l3_designer.json").write_text("{}", encoding='utf-8')
        return mod

    def test_schema_warning_not_blocking_by_default(self, tmp_path):
        """schema 违规（如非法 attitude 档位）默认 warning：exit code 仍为 0。"""
        from module_designer.lint import run_lint
        mod = self._write_module(tmp_path, {"npc_profiles": {
            "张三": {"name": "张三", "initial_attitude": "allied"}}})
        assert run_lint(str(mod)) == 0

    def test_strict_escalates_warnings(self, tmp_path):
        """--strict：schema warning 升级为影响 exit code。"""
        from module_designer.lint import run_lint
        mod = self._write_module(tmp_path, {"npc_profiles": {
            "张三": {"name": "张三", "initial_attitude": "allied"}}})
        assert run_lint(str(mod), strict=True) == 1

    def test_testbed_passes_strict(self):
        """e2e_testbed（全元素样例）在 strict 下零 error。"""
        import os
        from module_designer.lint import run_lint
        testbed = os.path.join(os.path.dirname(__file__), '..', 'data',
                               'modules', 'e2e_testbed')
        assert run_lint(testbed, strict=True) == 0
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_module_lint.py::TestLintStrict -q`
Expected: FAIL（run_lint 无 strict 参数）

- [ ] **Step 3: 实现 strict**

`lint.py:48` 签名与计数逻辑改：

```python
def run_lint(module_dir: str, strict: bool = False) -> int:
    """返回 exit code：有 error=1；strict=True 时 warning 也计 1。否则 0。"""
```

:114 汇总行后、return 前改：

```python
    return 1 if n_error or (strict and n_warn) else 0
```

`__main__` 块改：

```python
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(run_lint(args[0] if args else ".",
                      strict="--strict" in sys.argv))
```

注意 `test_strict_escalates_warnings` 的合法化依赖 Task 2 的 schema 枚举生效（allied → warning）。

- [ ] **Step 4: 跑测试确认绿**

Run: `python -m pytest tests/test_module_lint.py -q`
Expected: 全绿（含既有 lint 测试不回归——既有测试不传 strict 默认 False）

### Task 11: F35 依赖图 mermaid 导出（TDD）

**Files:**
- Modify: `src/module_designer/dependency_graph.py`（DependencyGraph 加 `to_mermaid`）
- Modify: `src/module_designer/lint.py`（CLI 子命令或独立入口，二选一——**实现时选 lint 加 `--graph` 标志**，少一个入口文件）
- Test: `tests/test_module_lint.py` 追加（或新 `tests/test_dependency_graph.py`，选后者，职责单一）

- [ ] **Step 1: 写失败测试**

Create `tests/test_dependency_graph.py`：

```python
"""F35 依赖图 mermaid 导出（spec §3.2）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestToMermaid:
    def _graph(self):
        from module_designer.dependency_graph import (
            DependencyEdge, DependencyGraph, DependencyNode)
        g = DependencyGraph()
        g.nodes["I1"] = DependencyNode(entity_id="I1", entity_type="interaction",
                                       name="搜索墙壁")
        g.nodes["AT2"] = DependencyNode(entity_id="AT2", entity_type="auto_trigger",
                                        name="尸体异变")
        g.nodes["END_TEST"] = DependencyNode(entity_id="END_TEST",
                                             entity_type="ending", name="测试结局")
        g.edges.append(DependencyEdge(source="AT2", target="I1",
                                      dep_type="interaction"))
        g.edges.append(DependencyEdge(source="END_TEST", target="AT2",
                                      dep_type="auto_trigger"))
        return g

    def test_nodes_and_edges_rendered(self):
        m = self._graph().to_mermaid()
        assert m.startswith("graph TD") or m.startswith("flowchart TD")
        assert "I1" in m and "搜索墙壁" in m
        assert "AT2" in m and "尸体异变" in m
        assert "AT2 --> I1" in m

    def test_ending_highlighted(self):
        m = self._graph().to_mermaid()
        assert "END_TEST" in m
        assert ":::" in m or "style" in m  # 结局节点有样式标注

    def test_circular_marked(self):
        from module_designer.dependency_graph import (
            DependencyEdge, DependencyGraph, DependencyNode)
        g = DependencyGraph()
        g.nodes["A"] = DependencyNode(entity_id="A")
        g.nodes["B"] = DependencyNode(entity_id="B")
        g.edges.append(DependencyEdge(source="A", target="B"))
        g.edges.append(DependencyEdge(source="B", target="A"))
        m = g.to_mermaid()
        assert "环" in m or "cycle" in m.lower() or "circular" in m.lower()
```

注意：先读 DependencyGraph 现有环检测 API（`_circular_cut`/`_cut_info` :43-44 与 `reachable_from`），测试断言以对齐实现；若现有环信息只在 cut 时记录，`to_mermaid` 自行做一次 DFS 检环即可（小图，无性能顾虑）。

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_dependency_graph.py -q`
Expected: FAIL（无 to_mermaid）

- [ ] **Step 3: 实现 to_mermaid**

`dependency_graph.py` DependencyGraph 类内加：

```python
    def to_mermaid(self) -> str:
        """导出 mermaid flowchart。结局节点高亮；检测到的环以注释标注。"""
        lines = ["flowchart TD"]
        for nid, node in self.nodes.items():
            label = f"{nid}[{node.name or nid}]" if node.entity_type != "ending" \
                else f"{nid}([{node.name or nid}])"
            lines.append(f"    {label}")
        for e in self.edges:
            lines.append(f"    {e.source} --> {e.target}")
        endings = [n for n in self.nodes.values() if n.entity_type == "ending"]
        if endings:
            lines.append("    classDef ending fill:#f9d423,stroke:#333")
            lines.append("    class " + ",".join(n.entity_id for n in endings)
                         + " ending")
        cycles = self._find_cycles()
        for cyc in cycles:
            lines.append(f"    %% 环: {' -> '.join(cyc)}")
        return "\n".join(lines)

    def _find_cycles(self) -> list:
        """DFS 检环，返回环路径列表（导出标注用，不影响运行时）。"""
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e.target, []).append(e.source)  # target 解锁 source
        cycles, stack, state = [], [], {}

        def dfs(n: str):
            state[n] = 1
            stack.append(n)
            for m in adj.get(n, []):
                if state.get(m) == 1:
                    cycles.append(stack[stack.index(m):] + [m])
                elif state.get(m) is None:
                    dfs(m)
            stack.pop()
            state[n] = 2

        for n in self.nodes:
            if state.get(n) is None:
                dfs(n)
        return cycles
```

注意边方向语义：DependencyEdge(source=依赖方, target=被依赖方)（:24-27）。mermaid 画 `source --> target` 表示「source 依赖 target」。`_find_cycles` 的邻接方向不影响环的存在性，保持一致即可。

- [ ] **Step 4: lint CLI 加 --graph 输出**

`lint.py __main__` 块改为：

```python
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    module_dir = args[0] if args else "."
    if "--graph" in sys.argv:
        import json as _json
        from pathlib import Path as _Path
        l2 = _json.loads((_Path(module_dir) / "l2_keeper.json")
                         .read_text(encoding="utf-8"))
        raw = l2.get("dependency_graph") or {}
        g = DependencyGraph.from_dict(raw) if raw.get("nodes") \
            else _scene_graph(_json.loads((_Path(module_dir) / "l1_player.json")
                                          .read_text(encoding="utf-8")), l2)
        print(g.to_mermaid())
        sys.exit(0)
    sys.exit(run_lint(module_dir, strict="--strict" in sys.argv))
```

（`DependencyGraph.from_dict` 与 `_scene_graph` 均已存在。）

- [ ] **Step 5: 跑测试确认绿 + P3 收口提交**

Run: `python -m pytest tests/test_dependency_graph.py tests/test_module_lint.py -q`
Expected: 全绿

手测：`python -m module_designer.lint data/modules/e2e_testbed --graph`（应打印 mermaid；模块 `__main__.py` 若不走 lint.py 则按实际入口调整命令）

```bash
git add src/module_designer/lint.py src/module_designer/dependency_graph.py \
        tests/test_module_lint.py tests/test_dependency_graph.py MAINTENANCE.md
git commit -m "feat: P3 lint --strict schema 校验升级 + 依赖图 mermaid 导出（F33/F35 CLI 形态）"
```

---

## P4 — 消费端测试盘点 + 收尾

### Task 12: 消费端测试盘点 → 缺口清单

**Files:**
- Read-only 盘点；产出写进 Task 13 的 ISSUES 回写

- [ ] **Step 1: 逐项核对覆盖**

对照清单逐项 grep tests/ 确认有专测：

| 机制 | 预期测试文件 | 核对点 |
|---|---|---|
| F17 scene_items | test_scene_items.py | ✅ 已有（加载/入档往返） |
| F19 environment | test_environment.py | ✅ 已有 |
| F23 repeatable | test_repeatable.py | 确认含存档往返 |
| F18 scheduled_events | test_scheduled_events.py | Task 5 后含模组加载 |
| F10 周期效应 | test_periodic_effects.py | 确认含存档往返 |
| F5 疯狂 | test_insanity.py | 确认含存档往返 |
| F27/N1 attitude | test_npc_attitude.py | 确认含存档往返 |
| N3 talk_to | test_deterministic.py::test_friendly_talk_calls_llm | ✅ 已有 |
| N4 npc_dead | test_deterministic.py | ✅ 已有 |
| B21 HP 单轨 | test_combat_smoke.py::TestCombatHpSingleTrack | ✅ 已有 |
| LLM fallback | test_llm_provider.py | ✅ 已有 |
| F14 技能成长 | test_skill_checked.py / test_growth.py | ✅ 已有 |
| F25 narrative memory | test_narrative_memory.py | ✅ 已有 |
| F31/F32 | test_module_lint.py / test_playtest_report.py | ✅ 已有 |

- [ ] **Step 2: 存档 round-trip 综合断言（疑似真空缺，补一个）**

`tests/test_save_load.py` 追加：

```python
class TestNewFieldsSaveRoundtrip:
    def test_new_mechanics_survive_save_load(self, tmp_path):
        """近期落地机制入档往返：scene_items/environment/attitude/insanity/scheduled/repeatable。"""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))
        from helpers import make_world, make_scene
        from scenario_core import ScenarioWorld

        world = make_world({"room_a": make_scene(
            environment={"lighting": "dark", "noise": "noisy"})}, "room_a")
        # scene_items
        from game.side_effects import SceneItem
        world.scene_items["room_a"] = [
            SceneItem(kind="item", ref="钥匙", hidden=True, quantity=1)]
        # scheduled_events
        world.scheduled_events = [{"id": "ev1", "at_minutes": 60,
                                   "markup": "@stat_change(stat_name=\"SAN\", delta=-1)",
                                   "description": "测试"}]
        # environment override
        world.environment_overrides["room_a"] = {"lighting": "dim"}

        path = str(tmp_path / "save.json")
        world.save_state(path)
        restored = ScenarioWorld.load_state(path)

        assert restored.current_environment().get("lighting") == "dim"
        assert any(i.ref == "钥匙" and i.hidden
                   for i in restored.scene_items.get("room_a", []))
        assert any(e["id"] == "ev1" for e in restored.scheduled_events)
```

实现时注意：`make_world`/`make_scene`/`SceneItem` 的实际签名先读 tests/e2e/helpers.py 与 game/side_effects.py 对齐；attitude/insanity/repeatable-completed 若需 player/npc 对象，按 test_npc_attitude.py / test_insanity.py 现成 fixture 模式各补一条断言（**只补实际缺的**——若既有测试已覆盖入档往返，此步只留 scene_items/environment/scheduled 三项）。

- [ ] **Step 3: 跑测试**

Run: `python -m pytest tests/test_save_load.py -q`
Expected: 全绿（若红 = 发现真存档缺口，按 systematic-debugging 修复后重跑）

### Task 13: 文档回写 + 最终收口

**Files:**
- Modify: `docs/superpowers/specs/2026-08-31-cluster-assessment.md` §10
- Modify: `docs/ISSUES.md`（§4 影响清单条目、§5 收口、F33/F35 移出活跃区）
- Modify: `MAINTENANCE.md`

- [ ] **Step 1: §10 回写**

修正点（spec §5）：
- N1 行拆分：interaction.`attitude_min` schema+prompt 已落地；NPC profile `attitude_value` schema 已落地
- 枚举漂移（allied→devoted）已修
- P0-1/F8 措辞由「应」改实态：prompt 最小回填已做，**未做真实生成验证**
- F19 锚点 L1→L2 scene
- STEP4 词表（@attitude_change/@env_change/npc_dead:）已回填
- e2e_testbed 样例模组全元素补全 + 防漂移测试
- scheduled_events 加载桥（新发现的断链）已修
- 总注：「prompt 最小回填未做真实端到端生成验证，待管线系统升级时一并重验」

- [ ] **Step 2: ISSUES 回写**

- F33/F35 从 §2 活跃区移入 §5（CLI 形态落地；F35 前端渲染留 §4 备注随前端专项）
- §4「模组生成管线影响清单」条目追加：「生成端回填专项已收口（2026-09-04）：schema 修补 + prompt 最小回填 + e2e_testbed 全元素 + F33 strict/F35 mermaid；prompt 未做真实生成验证，管线系统升级时重验」
- Task 12 盘点若发现新缺口，登记 §1/§2

- [ ] **Step 3: MAINTENANCE.md 同步**

新文件/函数行号：test_generation_schema / test_fixture_completeness / test_generation_prompts / test_dependency_graph；layered_schema `_attitude_keys`、min/max 校验；lint `strict`/`--graph`；DependencyGraph `to_mermaid`/`_find_cycles`；game_loop scheduled_events 桥。

- [ ] **Step 4: 最终验证 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿

```bash
git add docs/ MAINTENANCE.md tests/
git commit -m "docs: 生成端回填专项收口 — §10 回写 + F33/F35 收口 + 测试盘点"
```

---

## Self-Review 记录

- Spec 覆盖：§1.1→Task 1-2；§1.2→Task 3-4；§1.3→Task 1/3 测试；§2→Task 6-9；§3.1→Task 10；§3.2→Task 11；§4→Task 12；§5→Task 13。spec §1.2 timed_effects 项已修正为「不进 fixture」（见头部已知事实）。
- 占位符扫描：Task 4 的 dependency_graph 节点同步、Task 11 的环检测 API 对齐、Task 12 的 helpers 签名对齐均标注「先读再写」——均为单行确认非占位。
- 类型一致性：`run_lint(module_dir, strict=False)`、`to_mermaid()`、`SceneItem(kind, ref, hidden, quantity)`、`_attitude_keys()` 全文一致。
