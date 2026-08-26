# Phase 0 Bug Fix + Test Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清掉 ISSUES §1 除 B1/B3/B9/B19 外的全部活跃 bug，并把 real_llm 验证拆成默认/smoke/全量三档，降低每任务验证成本。

**Architecture:** Bug 按独立提交串行修；B17/B18 共享 `_apply_step_artifact(runner, path)` 把磁盘中间产物回灌 runner。测试策略不删现有 real_llm 用例，只加 `real_llm_smoke` 标记 + AGENTS.md 验证约定。

**Tech Stack:** Python / pytest / FastAPI launcher / 现有管线 `InteractiveRunner`

**验证政策（全任务遵守）：**
- 每任务结束后只跑：`pytest tests/ -q`（`addopts = -m "not real_llm"`，约 294 条，零 API）
- 禁止在单任务后跑 `pytest -m real_llm`
- 阶段 0 全部代码完成后跑一次：`pytest -m real_llm_smoke`
- 全量 `pytest -m real_llm` 仅在用户明确要求或改了 prompt/parse/narrator 时跑

**明确不做：** B1 存读档、B3 flaky、B9 control off-by-one（文档已注）、B19 前端静默降级、F13/F24、删除任何现有 real_llm 用例

**Work from:** `C:\Users\micha\PyCharmMiscProject`（当前 main 分支，用户已同意在 main 上执行）

**AGENTS.md 硬规则：** 每次改代码后同步更新 `MAINTENANCE.md`（行号/签名/功能）。

---

### Task 1: 测试分层政策（先落地，后续任务按此验证）

**Files:**
- Modify: `pytest.ini`
- Modify: `tests/e2e/test_scenarios.py`（给 3 个方法加 mark）
- Modify: `tests/e2e/test_escalation_real.py`（给 1 个 case 加 mark）
- Modify: `AGENTS.md`
- Modify: `MAINTENANCE.md`

- [ ] **Step 1: pytest.ini 加 smoke marker**

```ini
[pytest]
testpaths = tests
markers =
    real_llm: 真实 LLM 调用测试（on-demand，默认不运行；pytest -m real_llm 执行）
    real_llm_smoke: real_llm 短烟子集（约 4 条；pytest -m real_llm_smoke 执行）
addopts = -m "not real_llm"
```

- [ ] **Step 2: 给 4 条现有用例叠加 `real_llm_smoke`（不新建文件、不删用例）**

`tests/e2e/test_scenarios.py` 三个方法装饰器改为：

```python
class TestS1NormalTurn:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_normal_action_turn(self):
        ...

class TestS2AmbiguousClarify:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_ambiguous_then_clarified(self):
        ...

class TestS4StandoffAvoid:
    @retry_once
    @pytest.mark.real_llm_smoke
    def test_standoff_then_avoid(self):
        ...
```

`tests/e2e/test_escalation_real.py` 的 `test_case_a`：

```python
@pytest.mark.real_llm_smoke
def test_case_a(tmp_path=None, log_dir=""):
    ...
```

文件级 `pytestmark = pytest.mark.real_llm` 保留，两条 marker 并存。`pytest -m real_llm` 仍收集全部 20 条。

- [ ] **Step 3: AGENTS.md 追加验证约定**

```markdown
## 测试验证约定

- 每个任务收口默认只跑 `pytest tests/ -q`（已排除 real_llm，零 API）
- 禁止在单任务后跑全量 `pytest -m real_llm`
- 改了 prompt / parse / narrator / keeper 主路径，或一个阶段全部代码完成后，跑 `pytest -m real_llm_smoke`
- 全量 `pytest -m real_llm` 仅用户明确要求时执行
```

- [ ] **Step 4: 确认收集分层**

```
pytest tests/ --collect-only -q
pytest -m real_llm --collect-only -q
pytest -m real_llm_smoke --collect-only -q
```

预期：默认约 294 collected / 20 deselected；`real_llm` 仍 20；`real_llm_smoke` 正好 4。

- [ ] **Step 5: 更新 MAINTENANCE.md changelog 一行 + 提交**

```
git add pytest.ini tests/e2e/test_scenarios.py tests/e2e/test_escalation_real.py AGENTS.md MAINTENANCE.md
git commit -m "test: add real_llm_smoke marker and verification policy"
```

不要提交无关脏文件（`.claude/`、autosave、data/modules/supplements、imp.py、test.py）。

---

### Task 2: B16-① `time_of_day` 补凌晨

**Files:**
- Modify: `src/game/clock.py:22-32`
- Test: `tests/test_clock.py`（新建）
- Modify: `MAINTENANCE.md` GameClock 节

- [ ] **Step 1: 写失败测试 `tests/test_clock.py`**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from game.clock import GameClock

def test_time_of_day_bands():
    cases = [
        (0, "凌晨"), (4 * 60 + 59, "凌晨"),
        (5 * 60, "早晨"), (7 * 60 + 59, "早晨"),
        (8 * 60, "白天"), (16 * 60 + 59, "白天"),
        (17 * 60, "黄昏"), (19 * 60 + 59, "黄昏"),
        (20 * 60, "夜间"), (23 * 60 + 59, "夜间"),
    ]
    for minutes, expected in cases:
        c = GameClock(start_time=minutes)
        assert c.time_of_day == expected, f"{minutes}m hour={c.hour} got {c.time_of_day}"

def test_get_time_flags_uses_lingchen():
    c = GameClock(start_time=60)  # 01:00
    flags = c.get_time_flags()
    assert flags.get("time:凌晨") is True
    assert "time:夜间" not in flags
```

- [ ] **Step 2: `pytest tests/test_clock.py -q` 预期 RED**（h<5 现返回「夜间」）

- [ ] **Step 3: 改 `clock.py` `time_of_day`**

```python
@property
def time_of_day(self) -> str:
    h = self.hour
    if h < 5:
        return "凌晨"
    if h < 8:
        return "早晨"
    if h < 17:
        return "白天"
    if h < 20:
        return "黄昏"
    return "夜间"
```

- [ ] **Step 4: `pytest tests/test_clock.py tests/e2e/test_deterministic.py::TestTimeFlagHygiene -q` 预期 GREEN**

- [ ] **Step 5: MAINTENANCE GameClock `time_of_day` 行描述改为含凌晨 + changelog + 提交**

```
git add src/game/clock.py tests/test_clock.py MAINTENANCE.md
git commit -m "fix: GameClock time_of_day emits 凌晨 for hour<5"
```

注意：`TestTimeFlagHygiene`（`tests/e2e/test_deterministic.py` 约 1266 行）断言跨天/时段切换 flag。改凌晨后，原先把 hour<5 当「夜间」的用例若存在需同步。`test_stale_day_time_flags_cleared` 用 `6*60`/`18*60` 锚点，应不受影响。

---

### Task 3: B16-② `check_auto_triggers` 补 time_condition

**Files:**
- Modify: `src/game/judge.py:47-59`
- Test: `tests/e2e/test_deterministic.py` 增 `TestAutoTriggerTimeCondition`
- Modify: `MAINTENANCE.md` Judge 节

`make_scene` 签名（`tests/e2e/helpers.py:16`）：`make_scene(interactions=None, exits=None, **overrides)`，`auto_triggers` 经 `**overrides` 传入。

- [ ] **Step 1: 写失败测试**（追加到 `test_deterministic.py` 末尾）

```python
class TestAutoTriggerTimeCondition:
    def _at(self, times):
        import json
        return {
            "id": "AT_DAWN", "entity_type": "auto_trigger",
            "name": "凌晨低语", "scene": "room_a",
            "type": "None", "requirement": "", "trigger": "time",
            "result": "黑暗中传来低语。", "side_effects": [],
            "difficulty": "None",
            "time_condition": json.dumps([{"day": "ALL", "times": times}]),
        }

    def test_dawn_at_fires_only_at_lingchen(self):
        from game.judge import Judge
        from game.clock import GameClock
        world = make_world({"room_a": make_scene(
            auto_triggers=[self._at(["凌晨"])])}, "room_a")
        world.clock = GameClock(start_time=60)  # 01:00 凌晨
        judge = Judge(world)
        out = judge.check_auto_triggers()
        assert len(out) == 1 and out[0].success

        world.clock = GameClock(start_time=12 * 60)  # 白天
        out2 = judge.check_auto_triggers()
        assert out2 == []

    def test_empty_time_condition_still_fires(self):
        from game.judge import Judge
        world = make_world({"room_a": make_scene(
            auto_triggers=[{
                "id": "AT_ALWAYS", "entity_type": "auto_trigger",
                "name": "常驻", "scene": "room_a", "type": "None",
                "requirement": "", "trigger": "enter",
                "result": "灯在闪。", "side_effects": [],
                "difficulty": "None", "time_condition": [],
            }])}, "room_a")
        out = Judge(world).check_auto_triggers()
        assert len(out) == 1
```

注意：`Entity.time_condition` 可能是 str 或 list。`check_time_condition`（`scenario_core.py:173`）目前只 `json.loads` 字符串；list 会走 `TypeError` 后 `return True`（malformed -> allow）。调用前若是 list 先 `json.dumps`。

- [ ] **Step 2: 跑测试预期 RED**（白天也会 fire）

- [ ] **Step 3: 改 `judge.py` `check_auto_triggers`**

```python
def check_auto_triggers(self) -> list[ActionOutcome]:
    results = []
    node = self.world._current_node()
    if not node:
        return results
    from scenario_core import check_time_condition
    import json
    tod = self.world.clock.time_of_day
    day = self.world.clock.day
    for at in node.auto_triggers:
        if not self._check_simple_requirement(at):
            continue
        tc = at.time_condition if hasattr(at, "time_condition") else ""
        if isinstance(tc, list):
            tc = json.dumps(tc, ensure_ascii=False)
        if not check_time_condition(tc, day, tod):
            continue
        results.append(self._execute_entity(at))
    return results
```

- [ ] **Step 4: 跑该测试 + `pytest tests/ -q` GREEN**

- [ ] **Step 5: MAINTENANCE + ISSUES B16 移入 §5 + 提交**

```
git commit -m "fix: check_auto_triggers honors time_condition"
```

---

### Task 4: B17 `_handle_edit` 回灌 + 共享 `_apply_step_artifact`

**Files:**
- Modify: `run_pipeline.py`（新增 `_apply_step_artifact`；改 `_handle_edit`）
- Test: `tests/test_pipeline_resume.py`（新建）
- Modify: `MAINTENANCE.md` run_pipeline 节

`InteractiveRunner` 中间字段见 `run_pipeline.py:506-521`。各步产物文件名：

| 步骤 | 文件 |
|---|---|
| step_1 | `1a_structured_extraction.json`, `1b_condensed_text.txt` |
| step_2a | `2a_interactions.json` |
| step_2bc | `2b_combined.json`, `2c_l1.json`, `2c_l3.json` |
| step_3a | `3a_dedup_conflict.json`；另 `step_25/25_npc_profiles.json` |
| step_3b | `3b_cross_check.json` |
| step_35 | `35_dependency_graph.json`；另 `phase_1/phase1_style_preview.json` |

`DependencyGraph.from_dict` 已存在（`dependency_graph.py:132`）。`_parse_condensed_chapters` 已在 `run_pipeline.py` 内。

- [ ] **Step 1: 写失败测试 `tests/test_pipeline_resume.py`**

```python
import json, sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from run_pipeline import InteractiveRunner, PipelineConfig, _apply_step_artifact

def _runner(tmp_path):
    cfg = PipelineConfig(output_dir=str(tmp_path), module_name="t")
    r = InteractiveRunner.__new__(InteractiveRunner)
    r.config = cfg
    r.output_dir = Path(tmp_path)
    r.step1a = {}; r.scenes = []; r.characters = []
    r.step1b = {}; r.chapters = {}
    r.interactions = []; r.scene_movements = {}
    r.events = []; r.auto_triggers = []
    r.l1_data = {}; r.l3_data = {}
    r.npc_profiles = {}; r.l2_assembled = {}
    r.dep_graph = None; r.phase1_clean = {}
    return r

def test_apply_1a_reloads_scenes(tmp_path):
    p = tmp_path / "1a_structured_extraction.json"
    p.write_text(json.dumps({"scenes": [{"name": "A"}], "characters": [{"name": "B"}]}), encoding="utf-8")
    r = _runner(tmp_path)
    _apply_step_artifact(r, p)
    assert r.scenes == [{"name": "A"}]
    assert r.characters == [{"name": "B"}]
    assert r.step1a["scenes"][0]["name"] == "A"

def test_apply_2a_reloads_interactions(tmp_path):
    p = tmp_path / "2a_interactions.json"
    p.write_text(json.dumps({"interactions": [{"id": "IT1"}], "scene_movements": {"x": 1}}), encoding="utf-8")
    r = _runner(tmp_path)
    _apply_step_artifact(r, p)
    assert r.interactions == [{"id": "IT1"}]
    assert r.scene_movements == {"x": 1}

def test_apply_missing_file_raises(tmp_path):
    import pytest
    r = _runner(tmp_path)
    with pytest.raises(FileNotFoundError):
        _apply_step_artifact(r, tmp_path / "nope.json")
```

- [ ] **Step 2: RED**

- [ ] **Step 3: 实现 `_apply_step_artifact`（放在 `InteractiveRunner` 之前，模块级）**

按文件名分发：

| 文件名 | 回灌字段 |
|---|---|
| `1a_structured_extraction.json` | `step1a`；`scenes=step1a["scenes"]`；`characters=step1a["characters"]` |
| `1b_condensed_text.txt` | `step1b={"condensed_text": text}`；`chapters=_parse_condensed_chapters(text)` |
| `2a_interactions.json` | `interactions`；`scene_movements` |
| `2b_combined.json` | `events`；`auto_triggers` |
| `2c_l1.json` | `l1_data` |
| `2c_l3.json` | `l3_data` |
| `3a_dedup_conflict.json` | `interactions`/`events`/`auto_triggers`（有则覆盖） |
| `25_npc_profiles.json` | `npc_profiles`（文件可能是 `{npc_profiles: ...}` 或直接 dict） |
| `3b_cross_check.json` | `l1_data`/`l3_data`（`step3b.get("l1_data")`） |
| `35_dependency_graph.json` | `dep_graph = DependencyGraph.from_dict(data)` |
| `phase1_style_preview.json` | `phase1_clean` |
| 未知文件名 | `raise ValueError(f"无法回灌: {path.name}")` |

JSON 损坏 → `raise ValueError(f"中间文件损坏: {path}") from e`

- [ ] **Step 4: 改 `_handle_edit`**，编辑器返回后调用 `_apply_step_artifact`；失败 print 告警、不假装已加载：

```python
input("  按 Enter 确认已保存...")
try:
    _apply_step_artifact(self, Path(path))
    print(f"  已重新加载: {path}")
except Exception as e:
    print(f"  [错误] 重新加载失败，runner 仍用内存旧数据: {e}")
```

- [ ] **Step 5: `pytest tests/test_pipeline_resume.py -q` + 默认套件 GREEN；MAINTENANCE；提交**

```
git commit -m "fix: pipeline _handle_edit reloads artifacts into runner"
```

---

### Task 5: B18 断点续跑回灌

**Files:**
- Modify: `run_pipeline.py`（`PipelineConfig.resume_dir`；`InteractiveRunner.__init__`；`_hydrate_prior_steps`；`run_interactive`/`run_auto` 跳步前调用）
- Modify: `tests/test_pipeline_resume.py`
- Modify: `frontend/routers/launcher.py:188-227`（校验改查 debug 中间目录）
- Modify: `MAINTENANCE.md`

`_STEP_ORDER = ["step_1", "step_2a", "step_2bc", "step_3a", "step_3b", "step_35", "phase_2"]`（已在 `run_pipeline.py:1160`）

- [ ] **Step 1: 写失败测试**

```python
def test_hydrate_from_step1_then_start_2a(tmp_path):
    run_dir = tmp_path / "20260101_000000"
    (run_dir / "step_1").mkdir(parents=True)
    (run_dir / "step_1" / "1a_structured_extraction.json").write_text(
        json.dumps({"scenes": [{"name": "S"}], "characters": []}), encoding="utf-8")
    (run_dir / "step_1" / "1b_condensed_text.txt").write_text("## 章\n正文", encoding="utf-8")
    r = _runner(tmp_path)
    r.output_dir = run_dir
    from run_pipeline import _hydrate_prior_steps
    _hydrate_prior_steps(r, start_from="step_2a")
    assert r.scenes == [{"name": "S"}]
    assert r.step1a["scenes"][0]["name"] == "S"

def test_hydrate_missing_prior_raises(tmp_path):
    import pytest
    r = _runner(tmp_path)
    r.output_dir = tmp_path / "empty"
    r.output_dir.mkdir()
    from run_pipeline import _hydrate_prior_steps
    with pytest.raises(FileNotFoundError):
        _hydrate_prior_steps(r, start_from="step_2a")
```

- [ ] **Step 2: RED**

- [ ] **Step 3: 实现 `_hydrate_prior_steps(runner, start_from)`**

对 `start_from` 之前的每一步，按该步已知产物文件调用 `_apply_step_artifact`。缺文件 → `FileNotFoundError` 列出缺哪些。

step_3a 额外：回灌 3a + 25 后，若 `l1_data`/`interactions` 已在，调用现有 `_assemble_l2(...)` 填 `l2_assembled`（boss_encounters 可空列表）。

- [ ] **Step 4: `PipelineConfig` 增 `resume_dir: str = ""`**

`InteractiveRunner.__init__`：
- `start_from == "step_1"`：保持现逻辑（新建 timestamp 目录）
- 否则：`resume = config.resume_dir` 或自动选 `PROJECT_ROOT/config.output_dir` 下最新子目录；`self.output_dir` 指向该目录，**不再新建 timestamp**
- 找不到可续跑目录 → 打印错误并 `sys.exit(1)`

`run_interactive` / `run_auto` 在 skip 循环前：

```python
if config.start_from != "step_1":
    _hydrate_prior_steps(runner, config.start_from)
```

跳过分支仍 `_completed_steps.add`，但 runner 字段已有数据。

CLI：若已有 `--start-from`，加 `--resume-dir` 可选。`from_wizard`/`from_dict` 同步字段。

- [ ] **Step 5: 修 launcher `validate_pipeline`**

`required` 改为查 `data/debug/<resume 或最新 timestamp>/step_*` 产物，不再查 `data/modules/<name>/l2_keeper.json`。`start_from` 键与 `_STEP_ORDER` 对齐（至少 `step_2a`/`step_2bc`/`step_3a`/`step_3b`/`step_35`/`phase_2`）。

- [ ] **Step 6: 测试 + 默认套件 GREEN；ISSUES B17/B18 移 §5；提交**

```
git commit -m "fix: pipeline resume hydrates runner from step artifacts"
```

---

### Task 6: B13 三库裸 `json.load` 收敛

**Files:**
- Modify: `src/library/loader.py` 新增 `load_json_object`
- Modify: `src/library/items.py` `_load_file`、`src/library/spells.py` `_load_file`、`src/library/weapons.py:107-109`、`src/library/enemies.py:153-155`、`src/library/bosses.py:57-61` 改走共享函数
- Test: `tests/test_library_loader.py` 追加 weapons/enemies/bosses 损坏文件用例

- [ ] **Step 1: 失败测试**（weapons 损坏 JSON 报错带路径；顶层数组报「应为 object」）

复用 items 测试写法，对 `WeaponLibrary._load_file` / `EnemyLibrary._load_file` / `BossLibrary._load` 各一条。

- [ ] **Step 2: RED**

- [ ] **Step 3: `loader.py` 增加**

```python
import json
def load_json_object(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"库文件加载失败: {path}") from e
    if not isinstance(data, dict):
        raise ValueError(f"库文件格式错误(顶层应为 object): {path}")
    return data
```

items/spells 的 try/except 删掉，改 `data = load_json_object(path)`。weapons/enemies/bosses 同。

- [ ] **Step 4: GREEN；ISSUES B13 → §5；提交**

```
git commit -m "fix: shared load_json_object for all library JSON files"
```

---

### Task 7: B14 `load_skill_config` 缓存死代码

**Files:**
- Modify: `src/utils.py:157-170`
- Test: `tests/test_skill_config.py`（或新建一条 cache 测试）

- [ ] **Step 1: 失败测试**

spy `json.load`：两次 `load_skill_config()`（不传 path）应只读一次文件。

- [ ] **Step 2: RED**（第二次仍读文件，因为 `if path is None` 在赋值后不可达、从不写 cache）

- [ ] **Step 3: 改函数**

```python
def load_skill_config(path: str | None = None) -> dict:
    global _SKILL_CONFIG_CACHE
    if path is not None:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if _SKILL_CONFIG_CACHE is None:
        default = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "data", "skill_config.json"))
        with open(default, "r", encoding="utf-8") as f:
            _SKILL_CONFIG_CACHE = json.load(f)
    return _SKILL_CONFIG_CACHE
```

显式 `path` 不写 cache（避免测试/临时文件污染默认缓存）。

- [ ] **Step 4: GREEN；B14 → §5；提交**

```
git commit -m "fix: load_skill_config actually caches the default file"
```

---

### Task 8: B15 fumble 边界（按 ISSUES 简化公式，对齐 `opposed_check`）

**Files:**
- Modify: `src/investigator/models.py:247-253`
- Test: 在现有 investigator/skill 测试文件增 fumble 用例

口径（用户拍板）：`roll >= 96 and roll > target`。技能 96+ 时 96-99 不再误判；`opposed_check`（`rules.py:254`）已是此公式，只改 `_roll_d100`。

- [ ] **Step 1: 失败测试**

技能 99 掷 96 → 非 fumble；技能 99 掷 100 → fumble；技能 50 掷 96 → fumble。

`check_skill` 的 target 以 `Skill.value` 为准，测试里设 value/base 与现模型对齐。

- [ ] **Step 2: RED**（当前 `roll>=96` 无条件 fumble）

- [ ] **Step 3:**

```python
if roll >= 96 and roll > target:
    return False, f"{name}检定：D100={roll}/{target} ≥96 大失败！", "fumble"
```

- [ ] **Step 4: GREEN；B15 → §5；提交**

```
git commit -m "fix: fumble requires roll>=96 and roll>skill"
```

---

### Task 9: B6 被支配跳过不再渲染「未命中」

**Files:**
- Modify: `src/game/combat.py:619-632`（`_build_single_round_result` 叙事组装）
- Test: `tests/test_combat_smoke.py` `TestCombatControl` 增一条

被支配敌人 `_resolve_enemy_action` 已返回 `weapon="--"`、`success=False`、`narrative` 含「无法动弹」。轮叙事把 `success=False` 一律写成「未命中」。

- [ ] **Step 1: 失败测试**

对被支配敌人跑 `_resolve_enemy_action` + `_build_single_round_result`（或 `run_single_round`），断言 `round_narrative` 不含「未命中」，含「无法动弹」或跳过语义。

- [ ] **Step 2: RED**

- [ ] **Step 3: 改叙事组装**

```python
if a.action_type == "attack":
    if a.weapon == "--" or (not a.success and a.damage <= 0 and "无法动弹" in (a.narrative or "")):
        lines.append(f"{actor} | {a.narrative or '无法行动'}")
    else:
        s = "命中" if a.success else "未命中"
        ...
```

- [ ] **Step 4: GREEN；B6 → §5；提交**

```
git commit -m "fix: controlled skip no longer renders as miss"
```

---

### Task 10: B8 满 MP 不消耗恢复累计器

**Files:**
- Modify: `src/scenario_core.py:766-784`
- Test: `tests/test_use_system.py` `TestAdvanceTimeHooks` 增一条

口径：满 MP 期间 acc 清零，花费 MP 后从 0 开始攒（不把满期间的小时银行起来）。

```python
if p.derived.MP >= p.derived.MP_MAX:
    self._mp_regen_acc = 0
else:
    self._mp_regen_acc += max(0, minutes)
    ... existing convert ...
```

- [ ] **Step 1: 失败测试**

1. 满 MP + 120 分钟 → acc == 0（或不因「兑换但 gain=0」被花掉后再从 0 错位）
2. 不满 MP + 60 分钟 → 仍 +per_hour（回归）
3. 满 MP 休息 5 小时，花 1 点 MP，再推 60 分钟 → MP 回到满（或 +1）

- [ ] **Step 2: RED**

- [ ] **Step 3: 按上口径改 `_tick_time_effects`**

- [ ] **Step 4: GREEN；B8 → §5；提交**

```
git commit -m "fix: MP regen accumulator does not burn while MP is full"
```

---

### Task 11: 文档收口 + smoke 门禁

**Files:** `docs/ISSUES.md`、`MAINTENANCE.md`、`UPDATES.md`（若仍有活跃指针）

- [ ] **Step 1:** B16/B17/B18/B13/B14/B15/B6/B8 全部在 §5；§1 活跃区只剩 B1/B3/B9/B19（B9 注明跳过）
- [ ] **Step 2:** `pytest tests/ -q` 全绿
- [ ] **Step 3:** `pytest -m real_llm_smoke` 一次（4 条，允许 retry_once）
- [ ] **Step 4:** changelog 汇总行；提交 `docs: close phase-0 bug batch in ISSUES`

---

## 任务依赖

```
T1 测试政策
  → T2 B16 凌晨 → T3 B16 AT 时间门
  → T4 B17 回灌函数 → T5 B18 续跑（依赖 T4）
  → T6 B13 / T7 B14 / T8 B15 / T9 B6 / T10 B8 互不依赖，T4 之后可并行
  → T11 收口（全部之后）
```

B9 不修。B1/B3/B19 不动。
