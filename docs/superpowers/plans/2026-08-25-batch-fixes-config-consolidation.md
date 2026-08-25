# 小修批次 + F2 参数集中化收编 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 ISSUES.md 小修批次(B2/B4/B5/B7/B11/B12)+ F2 参数集中化全面收编(rules.py 散落数值迁 game_config,前端 SAN bar 分母接线)。

**Architecture:** 两批次:A 批 5 个独立小修(时间 flag 清理/库报错带路径/pytest testpaths/escalation 日志现场/cwd 回归测试);B 批 F2 收编(game_config 扩键+深拷贝 -> rules.py 六函数读 config -> roll_stats 读骰面 -> 前端 san_max 接线),数值行为默认不变(数据迁移非语义变更),全靠现有测试回归锁定。

**Tech Stack:** 纯 Python 标准库,pytest(默认套件 `-m "not real_llm"`),系统 Python `python -m pytest`。

**约定(执行者必读):**
- 测试命令一律 `python -m pytest <路径> -q`(系统 Python,.venv 无 pytest)
- 全量回归:`python -m pytest tests/ -q`,基线 **269 passed + 20 deselected**(test_unresolved_use_becomes_creative 偶发 fail 属 LLM flaky 约定:复跑确认即过,不阻塞)
- LLM flaky 约定:real_llm/LLM 相关测试过时不过,复跑确认即过不阻塞
- **禁止 `git add -A`/`git add .`**:工作区有用户有意保留的删除与修改(见 `git status`),git add 只写明确文件名
- 中文 commit message,main 直提
- import 模式:测试文件头部 `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))`(tests/e2e/ 下是 `'..', '..', 'src'`)
- game_config 测试模式(见 tests/test_game_config.py):`setup_function/teardown_function` 调 `rules.reset_game_config_cache()` + `monkeypatch.setattr(rules, "_CONFIG_PATH", str(tmp_path / "xxx.json"))`
- 本计划行号以 2026-08-25 代码为准,编辑时以内容锚点优先

---

## 批次 A:小修

### Task 1: B2 时间 flag 推进清理

**背景:** `GameClock.get_time_flags()` 返回 `{f"day:{N}": True, f"time:{tod}": True}`;`ScenarioWorld.advance_time` 每次注入 `runtime_state` 但从不清旧,长期局 `runtime_state` 里 day:0..day:N 全部 completed=True,经 `build_snapshot` 的 `completed` 列表进每回合 prompt,且随存档序列化(膨胀)。修复:推进时清掉非当前的 `day:`/`time:` 前缀条目。旧档读入后下一次 advance_time 自动清理,无需迁移。

**Files:**
- Modify: `src/scenario_core.py`(advance_time,约 751-757 行)
- Test: `tests/e2e/test_deterministic.py`(文件末尾加 TestTimeFlagHygiene 类)

- [ ] **Step 1: 写失败测试**

在 `tests/e2e/test_deterministic.py` 文件末尾追加:

```python
class TestTimeFlagHygiene:
    """ISSUES B2:advance_time 清旧 day:/time: flag,防 prompt/存档累积。"""

    def test_stale_day_time_flags_cleared(self):
        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        world.advance_time(60)        # game_time=60: day 0, hour 1(早晨)
        assert "day:0" in world.runtime_state
        assert "time:早晨" in world.runtime_state

        world.advance_time(23 * 60)   # game_time=1440: day 1, hour 0(夜间)
        assert "day:1" in world.runtime_state
        assert "day:0" not in world.runtime_state
        # time flag 只保留当前时段
        tods = [k for k in world.runtime_state if k.startswith("time:")]
        assert tods == ["time:夜间"]

        world.advance_time(8 * 60)    # game_time=1920: day 1, hour 8(白天)
        assert "time:白天" in world.runtime_state
        assert "time:夜间" not in world.runtime_state

        # build_snapshot completed 列表不再累积旧 day flag
        snap = world.build_snapshot()
        completed = snap["runtime"]["completed"]
        assert "day:0" not in completed and "day:1" in completed
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestTimeFlagHygiene -q`
Expected: FAIL(`assert "day:0" not in world.runtime_state` 断言失败)

- [ ] **Step 3: 实现**

`src/scenario_core.py` advance_time(当前实现):

```python
    def advance_time(self, minutes: int):
        self.clock.advance_time(minutes)
        # Auto-inject time flags into runtime_state
        for flag, value in self.clock.get_time_flags().items():
            state = self.get_runtime_state(flag)
            state.completed = value
        # 时间钩子(2026-08-21 spec §2.2/§4)
        self._tick_time_effects(minutes)
```

改为:

```python
    def advance_time(self, minutes: int):
        self.clock.advance_time(minutes)
        # Auto-inject time flags into runtime_state
        # (先清旧 day:/time: flag 防长期局累积进 prompt/存档 -- ISSUES B2)
        current = self.clock.get_time_flags()
        for prefix in ("day:", "time:"):
            stale = [k for k in self.runtime_state
                     if k.startswith(prefix) and k not in current]
            for k in stale:
                del self.runtime_state[k]
        for flag, value in current.items():
            state = self.get_runtime_state(flag)
            state.completed = value
        # 时间钩子(2026-08-21 spec §2.2/§4)
        self._tick_time_effects(minutes)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestTimeFlagHygiene -q`
Expected: PASS

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest tests/e2e/test_deterministic.py -q`
Expected: 全绿(该文件全确定性 stub)

```bash
git add src/scenario_core.py tests/e2e/test_deterministic.py
git commit -m "fix: advance_time 清旧 day:/time: flag(B2 prompt/存档累积)"
```

### Task 2: B7 库文件损坏报错带文件路径

**背景:** `ItemLibrary._load_file`(src/library/items.py 约 75-79)与 `SpellLibrary._load_file`(src/library/spells.py 约 84-88)裸调 `json.load(f)`,JSON 损坏抛 JSONDecodeError 不带来源路径,排障需逐文件试。包一层带路径的 ValueError。core 与 extension 文件共用 `_load_file`,一处覆盖两类。

**Files:**
- Modify: `src/library/items.py`(_load_file)
- Modify: `src/library/spells.py`(_load_file)
- Test: `tests/test_library_loader.py`(追加 2 测试)

- [ ] **Step 1: 写失败测试**

`tests/test_library_loader.py` 顶部确认有 `import pytest`(无则加),文件末尾追加:

```python
def test_corrupt_extension_json_error_names_file(tmp_path):
    """ISSUES B7:损坏扩展 JSON 报错带文件路径。"""
    base = tmp_path
    (base / "core").mkdir(parents=True)
    (base / "core" / "items.json").write_text('{"items": []}', encoding="utf-8")
    ext = base / "extensions" / "items"
    ext.mkdir(parents=True)
    (ext / "bad.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json"):
        load_item_library(str(base))


def test_non_dict_library_json_error_names_file(tmp_path):
    """库文件顶层非 object(如数组)报错带文件路径。"""
    base = tmp_path
    (base / "core").mkdir(parents=True)
    (base / "core" / "spells.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="spells.json"):
        load_spell_library(str(base))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_library_loader.py -q -k "error_names_file"`
Expected: FAIL(抛的是 json.JSONDecodeError / AttributeError,非 ValueError match)

- [ ] **Step 3: 实现**

`src/library/items.py` `_load_file` 改为:

```python
    def _load_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"库文件加载失败: {path}") from e
        if not isinstance(data, dict):
            raise ValueError(f"库文件格式错误(顶层应为 object): {path}")
        for item in data.get("items", []):
            li = LibraryItem.from_dict(item)
            self._items[li.id] = li
```

`src/library/spells.py` `_load_file` 同样模式(`spells` 键 / `LibrarySpell`):

```python
    def _load_file(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"库文件加载失败: {path}") from e
        if not isinstance(data, dict):
            raise ValueError(f"库文件格式错误(顶层应为 object): {path}")
        for sp in data.get("spells", []):
            ls = LibrarySpell.from_dict(sp)
            self._spells[ls.id] = ls
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_library_loader.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add src/library/items.py src/library/spells.py tests/test_library_loader.py
git commit -m "fix: 库文件损坏/格式错误报错带文件路径(B7)"
```

### Task 3: B5 pytest testpaths 隔离根目录脚本

**背景:** 裸 `pytest`(不带参数)从仓库根收集,`run_step1b_test.py`(调试脚本,模块级读已被用户删除的 `data/modules/深渊之口/module_raw.txt`)import 即 FileNotFoundError,报 collection error。`pytest.ini` 已存在(仅 markers + addopts),加 `testpaths = tests` 让裸 pytest 只收集 tests/。

**Files:**
- Modify: `pytest.ini`

- [ ] **Step 1: 确认现状(失败证据)**

Run: `python -m pytest -q --collect-only 2>&1 | tail -3`
Expected: 含 `ERROR run_step1b_test.py - FileNotFoundError` 与 `1 error during collection`

- [ ] **Step 2: 实现**

`pytest.ini` 全文改为:

```ini
[pytest]
testpaths = tests
markers =
    real_llm: 真实 LLM 调用测试（on-demand，默认不运行；pytest -m real_llm 执行）
addopts = -m "not real_llm"
```

- [ ] **Step 3: 验证**

Run: `python -m pytest -q --collect-only 2>&1 | tail -2`
Expected: `269/289 tests collected (20 deselected)`,无 ERROR。

Run: `python -m pytest tests/ -q 2>&1 | tail -1`
Expected: `269 passed ...`(或 268 passed + 1 个 LLM flaky failed,复跑确认)

- [ ] **Step 4: 提交**

```bash
git add pytest.ini
git commit -m "fix: pytest testpaths=tests 隔离根目录调试脚本收集错(B5)"
```

### Task 4: B4 escalation real_llm pytest 运行留日志现场

**背景:** `tests/e2e/test_escalation_real.py` 5 个 `test_case_*(log_dir="")` 函数被 pytest(带 `-m real_llm`)运行时 log_dir 为空,`_log_text/_log_json` no-op,失败无诊断现场,需 `python tests/e2e/test_escalation_real.py <CASE>` 手跑。修法:签名加 `tmp_path=None`(pytest 注入 fixture),log_dir 空时落到 tmp_path 子目录;手跑入口 `run()` 调 `test_fn(log_dir=case_dir)` 不受影响。

**Files:**
- Modify: `tests/e2e/test_escalation_real.py`(test_case_a/b/c/d/e 各 2 行改动)

- [ ] **Step 1: 实现(签名+落盘逻辑)**

对 5 个函数(test_case_a / test_case_b / test_case_c / test_case_d / test_case_e)做同样改动。以 test_case_a 为例,当前:

```python
def test_case_a(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
```

改为:

```python
def test_case_a(tmp_path=None, log_dir=""):
    if not log_dir and tmp_path is not None:
        log_dir = str(tmp_path / "escalation_case_a")   # pytest 运行留日志现场(ISSUES B4)
    stop_llm = _setup_llm_logging(log_dir)
```

b/c/d/e 同样(子目录名分别 escalation_case_b / escalation_case_c / escalation_case_d / escalation_case_e)。函数体其余不动。

- [ ] **Step 2: 验证收集合法**

Run: `python -m pytest tests/e2e/test_escalation_real.py --collect-only -q -m real_llm 2>&1 | tail -3`
Expected: 收集 5 个测试,无 fixture 错误

- [ ] **Step 3: 验证手跑入口不受影响(代码级)**

确认文件尾部 `run()` 中 `test_fn(log_dir=case_dir)` 调用形态不变(手跑时 log_dir 非空,tmp_path 默认 None,短路)。真实 API 跑一遍可选(`python tests/e2e/test_escalation_real.py A`,按需,不强制)。

- [ ] **Step 4: 提交**

```bash
git add tests/e2e/test_escalation_real.py
git commit -m "fix: escalation real_llm pytest 运行日志落 tmp_path 留现场(B4)"
```

### Task 5: B12 loader 默认路径 cwd 独立性回归测试

**背景:** `src/library/loader.py` `_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "library"` 已是包相对绝对路径,但无回归测试锁定(防止将来被改成 cwd 相对)。

**Files:**
- Test: `tests/test_library_loader.py`(追加 1 测试)

- [ ] **Step 1: 写测试(当前应直接通过--这是锁定型测试)**

`tests/test_library_loader.py` 末尾追加:

```python
def test_data_root_cwd_independent(tmp_path, monkeypatch):
    """ISSUES B12:loader 默认路径与 cwd 无关(_DATA_ROOT 为包相对绝对路径锁定)。"""
    monkeypatch.chdir(tmp_path)
    lib = load_item_library()      # 不传 base_dir,走 _DATA_ROOT
    assert len(lib) > 0
    assert len(load_spell_library()) > 0
```

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/test_library_loader.py -q`
Expected: 全部 PASS(含 Task 2 的 2 个新测试)

- [ ] **Step 3: 提交**

```bash
git add tests/test_library_loader.py
git commit -m "test: loader 默认路径 cwd 独立性回归(B12)"
```

---

## 批次 B:F2 参数集中化收编

### Task 6: game_config 扩键 + get_game_config 深拷贝

**背景:** F2 第一步。新键:stat_roll_multiplier / skill_value_cap / unarmed_damage / derived(除数组)/ db_build_table / age_modifiers / credit_rating_table(阈值-标签对列表,避免 JSON 字符串键转 int)。`get_game_config` 现返回浅拷贝 `dict(...)`,嵌套结构共享引用,调用方改嵌套会污染缓存,改 `copy.deepcopy`。类型校验 `type(v) is type(dv)` 顶层保持(嵌套键类型不符回退默认)。

**Files:**
- Modify: `data/game_config.json`(全量重写)
- Modify: `src/investigator/rules.py`(_GAME_CONFIG_DEFAULTS 扩展 @301-305,get_game_config @317-334 返回 deepcopy;顶部加 `import copy`)
- Test: `tests/test_game_config.py`(追加 3 测试)

- [ ] **Step 1: 写失败测试**

`tests/test_game_config.py` 末尾追加:

```python
def test_new_keys_present():
    """F2 收编键齐全(默认值)。"""
    cfg = rules.get_game_config()
    assert cfg["stat_roll_multiplier"] == 5
    assert cfg["skill_value_cap"] == 99
    assert cfg["unarmed_damage"] == "1D3+DB"
    assert cfg["derived"] == {"hp_divisor": 3, "mp_divisor": 5,
                              "dodge_divisor": 2, "san_max_base": 99}
    assert len(cfg["db_build_table"]) == 6
    assert cfg["db_build_table"][-1] == {"max_key": None, "db": "+2D6", "build": 3}
    assert cfg["age_modifiers"]["start_age"] == 40
    assert cfg["age_modifiers"]["app_penalties"] == [-5, -10, -15, -20, -25]
    assert len(cfg["credit_rating_table"]) == 8
    assert cfg["credit_rating_table"][0] == [0, "身无分文"]


def test_nested_config_deep_copy():
    """嵌套结构返回深拷贝:改返回值不污染缓存。"""
    cfg1 = rules.get_game_config()
    cfg1["derived"]["hp_divisor"] = 99
    cfg1["db_build_table"][0]["db"] = "HACK"
    cfg2 = rules.get_game_config()
    assert cfg2["derived"]["hp_divisor"] == 3
    assert cfg2["db_build_table"][0]["db"] == "-2"


def test_nested_type_mismatch_falls_back(monkeypatch, tmp_path):
    """嵌套键类型不匹配回退默认。"""
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"derived": 3, "db_build_table": "x",
                             "credit_rating_table": 9}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["derived"]["hp_divisor"] == 3
    assert cfg["db_build_table"][0]["db"] == "-2"
    assert cfg["credit_rating_table"][0] == [0, "身无分文"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: test_new_keys_present FAIL(KeyError),test_nested_config_deep_copy FAIL(浅拷贝污染)

- [ ] **Step 3: 实现**

`data/game_config.json` 全量重写:

```json
{
  "mp_recovery_per_hour": 1,
  "timed_default_minutes": 30,
  "buff_damage_floor": 0,
  "stat_roll_multiplier": 5,
  "skill_value_cap": 99,
  "unarmed_damage": "1D3+DB",
  "derived": {
    "hp_divisor": 3,
    "mp_divisor": 5,
    "dodge_divisor": 2,
    "san_max_base": 99
  },
  "db_build_table": [
    {"max_key": 64, "db": "-2", "build": -2},
    {"max_key": 84, "db": "-1", "build": -1},
    {"max_key": 124, "db": "0", "build": 0},
    {"max_key": 164, "db": "+1D4", "build": 1},
    {"max_key": 204, "db": "+1D6", "build": 2},
    {"max_key": null, "db": "+2D6", "build": 3}
  ],
  "age_modifiers": {
    "start_age": 40,
    "max_tier": 4,
    "app_penalties": [-5, -10, -15, -20, -25],
    "phys_penalties": [0, -5, -10, -20, -40],
    "edu_bonuses": [5, 10, 15, 20, 25]
  },
  "credit_rating_table": [
    [0, "身无分文"],
    [5, "拮据"],
    [10, "一般"],
    [20, "中等"],
    [30, "宽裕"],
    [50, "富裕"],
    [70, "富有"],
    [90, "极富"]
  ]
}
```

`src/investigator/rules.py`:顶部 import 区加 `import copy`;`_GAME_CONFIG_DEFAULTS` 替换为:

```python
_GAME_CONFIG_DEFAULTS = {
    "mp_recovery_per_hour": 1,     # MP 每小时恢复点数
    "timed_default_minutes": 30,   # timed 原子缺省持续分钟
    "buff_damage_floor": 0,        # 战斗 buff 减伤后伤害下限
    "stat_roll_multiplier": 5,     # 属性掷骰总乘数(U9: 3D6*5 / (2D6+6)*5)
    "skill_value_cap": 99,         # 技能值上限
    "unarmed_damage": "1D3+DB",    # 默认徒手武器伤害
    "derived": {                   # 衍生公式参数(除数/基数)
        "hp_divisor": 3, "mp_divisor": 5, "dodge_divisor": 2, "san_max_base": 99,
    },
    "db_build_table": [            # DB/BUILD 查表(键=STR+CON//2,max_key None=兜底行)
        {"max_key": 64, "db": "-2", "build": -2},
        {"max_key": 84, "db": "-1", "build": -1},
        {"max_key": 124, "db": "0", "build": 0},
        {"max_key": 164, "db": "+1D4", "build": 1},
        {"max_key": 204, "db": "+1D6", "build": 2},
        {"max_key": None, "db": "+2D6", "build": 3},
    ],
    "age_modifiers": {             # 年龄修正(start_age 起每 10 年一档)
        "start_age": 40, "max_tier": 4,
        "app_penalties": [-5, -10, -15, -20, -25],
        "phys_penalties": [0, -5, -10, -20, -40],
        "edu_bonuses": [5, 10, 15, 20, 25],
    },
    "credit_rating_table": [       # 信用评级 [阈值, 标签](升序)
        [0, "身无分文"], [5, "拮据"], [10, "一般"], [20, "中等"],
        [30, "宽裕"], [50, "富裕"], [70, "富有"], [90, "极富"],
    ],
}
```

`get_game_config` 最后一行 `return dict(_game_config_cache)` 改 `return copy.deepcopy(_game_config_cache)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add data/game_config.json src/investigator/rules.py tests/test_game_config.py
git commit -m "feat: game_config 扩键(F2 衍生/查表/年龄/信用/上限)+嵌套深拷贝"
```

### Task 7: rules.py 六函数收编读 config

**背景:** F2 主体。`_calc_db_build` / `calc_derived` / `allocate_skill_points`(cap)/ `apply_age_modifiers` / `get_credit_level`(删模块常量 CREDIT_RATING_TABLE,已确认无外部引用)/ `create_default_unarmed` 改读 `get_game_config()`。**默认值与现状完全一致**(数据迁移),现有测试回归即锁定。

**Files:**
- Modify: `src/investigator/rules.py`(六函数)
- Test: `tests/test_game_config.py`(追加 5 覆盖测试;`from investigator.models import Stats, Skill` 加到文件 import 区)

- [ ] **Step 1: 写失败测试**

`tests/test_game_config.py` import 区加:

```python
from investigator.models import Stats, Skill
```

文件末尾追加:

```python
def test_calc_derived_reads_config(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"derived": {"hp_divisor": 2, "mp_divisor": 10,
                                          "dodge_divisor": 4, "san_max_base": 90}}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = Stats(STR=50, CON=60, DEX=70, APP=40, INT=60, POW=50, EDU=70, LUCK=50)
    d = rules.calc_derived(st)
    assert d.HP == 30      # 60 // 2
    assert d.MP == 5       # 50 // 10
    assert d.DODGE == 17   # 70 // 4
    assert d.SAN_MAX == 90


def test_db_build_table_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"db_build_table": [
        {"max_key": 100, "db": "+9D9", "build": 9},
        {"max_key": None, "db": "0", "build": 0}]}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules._calc_db_build(50) == ("+9D9", 9)
    assert rules._calc_db_build(150) == ("0", 0)


def test_age_modifiers_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"age_modifiers": {"start_age": 20, "max_tier": 1,
                                                "app_penalties": [-1, -2],
                                                "phys_penalties": [0, -3],
                                                "edu_bonuses": [1, 2]}}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    rules.apply_age_modifiers(st, 35)   # (35-20)//10 = tier 1
    assert st.APP == 48 and st.STR == 47 and st.CON == 47 and st.DEX == 47
    assert st.EDU == 52


def test_credit_rating_table_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"credit_rating_table": [[0, "穷"], [80, "豪"]]}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules.get_credit_level(90) == "豪"
    assert rules.get_credit_level(10) == "穷"


def test_skill_cap_and_unarmed_override(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"skill_value_cap": 80, "unarmed_damage": "1D2"}),
                 encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    assert rules.create_default_unarmed().damage == "1D2"
    sk = [Skill(name="射击", base_value=50, value=50, category="DEX")]
    st = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    out = rules.allocate_skill_points(sk, st, focus=["射击"], focus_bonus=100)
    assert out[0].value == 80   # 50+100 被 cap 80 截断
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_game_config.py -q -k "override or reads_config"`
Expected: 5 个新测试 FAIL(仍读硬编码)

- [ ] **Step 3: 实现六函数**

`src/investigator/rules.py`:

(a) `_calc_db_build` 替换为:

```python
def _calc_db_build(key: int) -> Tuple[str, int]:
    """U9 查表键 = STR + CON//2，返回 (DB, BUILD)(表: game_config.db_build_table)。"""
    for row in get_game_config()["db_build_table"]:
        mk = row["max_key"]
        if mk is None or key <= mk:
            return row["db"], row["build"]
    return "0", 0  # 空表兜底
```

(b) `calc_derived` 替换为:

```python
def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """U9 衍生公式(除数/基数见 game_config.derived)：HP=CON//hp_divisor；
    MP=POW//mp_divisor；DODGE=DEX//dodge_divisor；SAN 上限=san_max_base-神话；
    DB/BUILD 查表键=STR+CON//2。"""
    d = get_game_config()["derived"]
    hp = max(1, math.floor(stats.CON / d["hp_divisor"]))
    mp = math.floor(stats.POW / d["mp_divisor"])
    san = stats.POW
    san_max = d["san_max_base"] - cthulhu_mythos
    dodge = math.floor(stats.DEX / d["dodge_divisor"])
    db, build = _calc_db_build(stats.STR + stats.CON // 2)
    return DerivedStats(
        HP=hp, HP_MAX=hp, MP=mp, MP_MAX=mp, SAN=san, SAN_MAX=san_max,
        DB=db, BUILD=build, DODGE=dodge,
    )
```

(c) `allocate_skill_points` 最后一行循环替换(原 `s.value = min(99, ...)`):

```python
    cap = get_game_config()["skill_value_cap"]
    for s in skills:
        s.value = min(cap, max(s.value, s.base_value if s.name not in no_pool else 0))
    return skills
```

(d) `apply_age_modifiers` 替换为(保留原 docstring 表格):

```python
def apply_age_modifiers(stats: Stats, age: int):
    """
    COC 7th 年龄修正（原位修改）。表与阈值: game_config.age_modifiers。

    | 年龄段 (tier) | APP    | STR/CON/DEX   | EDU  |
    |---------------|--------|---------------|------|
    | 40-49 (0)     | -5     | 0             | +5   |
    | 50-59 (1)     | -10    | -5            | +10  |
    | 60-69 (2)     | -15    | -10           | +15  |
    | 70-79 (3)     | -20    | -20           | +20  |
    | 80+ (4)       | -25    | -40           | +25  |
    """
    cfg = get_game_config()["age_modifiers"]
    if age < cfg["start_age"]:
        return

    tier = (age - cfg["start_age"]) // 10
    tier = min(tier, cfg["max_tier"], len(cfg["app_penalties"]) - 1)

    stats.APP = max(0, stats.APP + cfg["app_penalties"][tier])
    if cfg["phys_penalties"][tier]:
        stats.STR = max(0, stats.STR + cfg["phys_penalties"][tier])
        stats.CON = max(0, stats.CON + cfg["phys_penalties"][tier])
        stats.DEX = max(0, stats.DEX + cfg["phys_penalties"][tier])
    stats.EDU = min(99, stats.EDU + cfg["edu_bonuses"][tier])
```

(e) 删除模块级 `CREDIT_RATING_TABLE: Dict[int, str] = {...}` 常量块;`get_credit_level` 替换为:

```python
def get_credit_level(value: int) -> str:
    """根据信用评级数值返回等级描述(表: game_config.credit_rating_table)。"""
    table = sorted(get_game_config()["credit_rating_table"])
    result = table[0][1] if table else "身无分文"
    for threshold, label in table:
        if value >= threshold:
            result = label
    return result
```

(f) `create_default_unarmed` 中 `damage="1D3+DB"` 改 `damage=get_game_config()["unarmed_damage"]`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 回归(现有规则行为锁定)+ 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿(数值默认不变;test_unresolved_use_becomes_creative 偶发 fail 按 LLM flaky 约定复跑)

```bash
git add src/investigator/rules.py tests/test_game_config.py
git commit -m "refactor: rules.py 六函数散落数值收编进 game_config(F2)"
```

### Task 8: roll_stats 骰面读 skill_config.dice

**背景:** `roll_stats` 硬编码骰面(STR 3D6*5 / INT (2D6+6)*5 / ...),而 `skill_config.json attributes` 已有 `dice` 字段(`[count, sides]` 或 `[count, sides, flat]`,如 STR `[3,6]`、INT `[2,6,6]`=2D6+6)。消重复:代码读数据。总乘数 *5 收编为 `game_config.stat_roll_multiplier`(Task 6 已加)。`load_skill_config` 无兜底但它是 repo 内数据,与 `create_skill_list` 同信任级别。

**Files:**
- Modify: `src/investigator/rules.py`(roll_stats @20-31)
- Test: `tests/test_game_config.py`(追加 2 测试)

- [ ] **Step 1: 写失败测试**

`tests/test_game_config.py` 末尾追加:

```python
def test_roll_stats_range_matches_dice_config():
    """骰面读 skill_config.dice:STR 3D6*5∈[15,90];INT/EDU (2D6+6)*5∈[40,80]。"""
    for _ in range(200):
        st = rules.roll_stats()
        assert 15 <= st.STR <= 90
        assert 15 <= st.CON <= 90 and 15 <= st.DEX <= 90
        assert 40 <= st.INT <= 80 and 40 <= st.EDU <= 80
        assert 15 <= st.POW <= 90 and 15 <= st.LUCK <= 90


def test_roll_stats_multiplier_config(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"stat_roll_multiplier": 1}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    st = rules.roll_stats()
    assert 3 <= st.STR <= 18    # 3D6*1
    assert 8 <= st.INT <= 16    # (2D6+6)*1
```

注:test_roll_stats_range_matches_dice_config 对旧实现也过(行为一致),它是回归锁定;multiplier 测试旧实现必败(旧实现硬编码 *5)。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_game_config.py -q -k roll_stats`
Expected: test_roll_stats_multiplier_config FAIL(STR 上限 90 非 18)

- [ ] **Step 3: 实现**

`roll_stats` 替换为:

```python
def roll_stats() -> Stats:
    """掷骰生成核心属性。骰面读 skill_config.attributes.dice([count, sides] 或
    [count, sides, flat]),总乘数 game_config.stat_roll_multiplier(默认 5)。"""
    from utils import load_skill_config
    cfg = load_skill_config()
    times = get_game_config()["stat_roll_multiplier"]
    vals = {}
    for attr, ac in cfg["attributes"].items():
        dice = ac.get("dice", [3, 6])
        count, sides = int(dice[0]), int(dice[1])
        flat = int(dice[2]) if len(dice) > 2 else 0
        roll = sum(random.randint(1, sides) for _ in range(count))
        vals[attr] = (roll + flat) * times
    return Stats(**vals)
```

(rules.py 顶部已 `import random`,无需加。)

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: 全部 PASS

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿

```bash
git add src/investigator/rules.py tests/test_game_config.py
git commit -m "refactor: roll_stats 骰面读 skill_config.dice+乘数入 game_config(F2)"
```

### Task 9: 前端 SAN bar 分母接线 san_max + B11 version 对齐

**背景:** SAN 上限实际是 `derived.SAN_MAX`(=99-克苏鲁神话),前端三处硬编码 /99:frontend/routers/game.py:575(服务端渲染角色卡 `derived.SAN / 99 * 100`)、frontend/templates/game.html:543(char-san-bar `san / 99 * 100`)、game.html:1101(`st.player_san / 99 * 100`,st 为战斗状态)。修法:服务端直接用 `derived.SAN_MAX`;两处 JSON 接口补 `san_max` 字段(player-status 类接口)与 `player_san_max`(战斗状态);模板 JS 换用。顺修 B11:frontend/routers/character.py 导出 version "2.0" -> "2.2"。

**Files:**
- Modify: `src/game/messages.py`(CombatState 加 player_san_max 字段,约 141 行 player_san 旁)
- Modify: `src/game/combat.py`(3 处 CombatState 构造/序列化点:约 365(转发)、577(dict)、689(从 player 构造)——以 `player_san` grep 结果为准)
- Modify: `frontend/routers/game.py`(575 除数;851/871 附近接口 dict 加 san_max;63 附近战斗 state 转发加 player_san_max)
- Modify: `frontend/templates/game.html`(543 / 1101 两处 JS)
- Modify: `frontend/routers/character.py`(version "2.0"->"2.2")
- Test: `tests/test_frontend_contract.py`(追加接口契约测试)

- [ ] **Step 1: 调查确认接口形态**

Run: `grep -n "player_san\|san_max" frontend/routers/game.py src/game/combat.py src/game/messages.py`
确认:63 附近战斗 state 转发 dict、575 渲染除数、851/871 附近 player 状态接口 dict 的具体上下文(接口路由名与字段名,测试要用)。若 851/871 附近接口已有 `san` 字段,在同 dict 加 `san_max`;CombatState 构造点若上下文有 player 对象则 `player_san_max=player.derived.SAN_MAX`,转发点 `player_san_max=getattr(state, "player_san_max", 99)`。

- [ ] **Step 2: 写失败测试**

`tests/test_frontend_contract.py` 末尾追加(接口路径以 Step 1 实查为准,下面按 player-status 假设;若实际路由不同照实改):

```python
def test_player_status_includes_san_max(client):
    """F2:player 状态接口暴露 san_max(SAN bar 分母数据来源)。"""
    resp = client.get("/api/player/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "san_max" in data
    assert data["san_max"] >= data.get("san", 0)
```

(无存档时接口可能返回默认调查员或 404,按现有测试对该接口的处理方式对齐;核心断言:有数据时含 san_max 字段。)

- [ ] **Step 3: 跑测试确认失败**

Run: `python -m pytest tests/test_frontend_contract.py -q -k san_max`
Expected: FAIL(接口无 san_max 键)

- [ ] **Step 4: 实现**

(a) `src/game/messages.py` CombatState dataclass:`player_san: int = 0` 下一行加 `player_san_max: int = 99`

(b) `src/game/combat.py` 3 处(以 grep 实查为准):
- 从 player 构造处(约 689 `player_san=player.derived.SAN`):同处加 `player_san_max=player.derived.SAN_MAX`
- 转发处(约 365 `player_san=state.player_san`):加 `player_san_max=getattr(state, "player_san_max", 99)`
- dict 序列化处(约 577 `"player_san": state.player_san`):加 `"player_san_max": getattr(state, "player_san_max", 99)`

(c) `frontend/routers/game.py`:
- 约 575:`san_pct = min(100, max(0, derived.SAN / 99 * 100))` -> `san_pct = min(100, max(0, derived.SAN / max(1, derived.SAN_MAX) * 100))`
- 851/871 附近接口 dict:`"san": inv.derived.SAN` 旁加 `"san_max": inv.derived.SAN_MAX`;`"san": p.derived.SAN if p else 0` 旁加 `"san_max": p.derived.SAN_MAX if p else 99`
- 63 附近战斗 state 转发:`"player_san": state.player_san` 旁加 `"player_san_max": getattr(state, "player_san_max", 99)`

(d) `frontend/templates/game.html`:
- 约 543:`document.getElementById('char-san-bar').style.width = (san > 0 ? (san / 99 * 100) : 0) + '%';` -> 换用数据里的 san_max(查该函数数据来源接口的返回,取 `(san > 0 ? (san / Math.max(1, san_max) * 100) : 0)`,变量名按函数上下文)
- 约 1101:`var sanPct = st.player_san > 0 ? (st.player_san / 99 * 100) : 0;` -> `var sanPct = st.player_san > 0 ? (st.player_san / Math.max(1, st.player_san_max || 99) * 100) : 0;`

(e) `frontend/routers/character.py`:导出 dict 中 `"version": "2.0"` -> `"version": "2.2"`

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_frontend_contract.py tests/test_frontend_character.py -q`
Expected: 全部 PASS

Run: `grep -n "/ 99" frontend/templates/game.html frontend/routers/game.py`
Expected: 无残留 SAN 硬编码除法(排除无关行)

- [ ] **Step 6: 回归 + 提交**

Run: `python -m pytest tests/ -q`
Expected: 全绿

```bash
git add src/game/messages.py src/game/combat.py frontend/routers/game.py frontend/templates/game.html frontend/routers/character.py tests/test_frontend_contract.py
git commit -m "fix: 前端 SAN bar 分母接线 san_max+B11 version 对齐 v2.2(F2)"
```

### Task 10: 文档同步 + 全量回归

**Files:**
- Modify: `MAINTENANCE.md`(changelog 行 + 受影响函数条目行号/说明:scenario_core.advance_time / library.items._load_file / library.spells._load_file / rules.{roll_stats,_calc_db_build,calc_derived,allocate_skill_points,apply_age_modifiers,get_credit_level,create_default_unarmed,get_game_config,_GAME_CONFIG_DEFAULTS} / game.messages.CombatState / combat 构造点 / frontend routers game.py+character.py / game.html;新增测试文件条目)
- Modify: `docs/ISSUES.md`(§1 B2/B4/B5/B7/B11/B12 移入 §5 已收口;§2 F2 移入已收口,留 F1/F3/F4;B10 备忘保留)
- Modify: `UPDATES.md`(新起「工作汇总(2026-08-25)」节:小修批次 5 项 + F2 收编范围/方式/测试数)
- Modify: `readme.md`(effect 原子系统节 MP 恢复句附近补一句:数值参数集中 `data/game_config.json`——MP 恢复/衍生公式除数/DB/BUILD 查表/年龄修正/信用评级/技能上限/属性骰面乘数,改档调参免改码)

- [ ] **Step 1: MAINTENANCE.md 同步**

按上述清单逐条更新函数条目(行号以改动后代码为准,用 grep 重新定位);changelog 表格加一行(格式仿照现有 `| 2026-08-24 | ... |`)。MAINTENANCE.md 长行中文编辑用 Python 脚本+锚点替换(全角标点会使部分编辑工具匹配失败)。

- [ ] **Step 2: ISSUES.md 收口**

B2/B4/B5/B7/B11/B12 从 §1 各表删除;§2 删 F2 行;§5 已收口表追加 7 行(日期 2026-08-25,方式=各 commit hash);B10 备忘与 F1/F3/F4、R1-R3、B1/B3/B6/B8/B9 保持不动。

- [ ] **Step 3: UPDATES.md + readme.md**

新增工作汇总节(仿 2026-08-24 节结构:已完成/测试现状);readme 补参数中心一句。

- [ ] **Step 4: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿,记录最终测试数(预计 269 + 新增约 15 = ~284 passed / 20 deselected)

Run: `python -m pytest -q --collect-only 2>&1 | tail -2`
Expected: 无收集错误(testpaths 生效)

- [ ] **Step 5: 提交**

```bash
git add MAINTENANCE.md docs/ISSUES.md UPDATES.md readme.md
git commit -m "docs: 小修批次+F2 收编收口(MAINTENANCE/ISSUES/UPDATES/readme)"
```

---

## Self-Review 记录

- 覆盖:用户拍板范围 = 小修批次(B2/B4/B5/B7/B12 + B11 顺修)+ F2 全量(后端 rules+config / roll_stats 骰面 / 前端 SAN bar)。B1(存读档)/F1(物品转移)用户明确不排;B3 观察约定不动;B6/B8/B9 spec 未规定类不动。✓
- 占位符扫描:Task 9 Step 1/4 含"以 grep 实查为准"的调查指令(前端接口路径存在会话未实查的盲区,已给出完整候选模式与验证命令,非占位符)。其余任务代码完整。✓
- 类型一致:Stats 8 字段构造一致;get_game_config()["derived"] dict 键名 hp_divisor/mp_divisor/dodge_divisor/san_max_base 在 Task 6/7 一致;db_build_table 行结构 {max_key, db, build} 两处一致;credit_rating_table 均为 [阈值, 标签] 对列表。✓
- 风险点:Task 7 (e) 删模块常量 CREDIT_RATING_TABLE 已确认无外部引用(grep 仅 rules.py 内两处);Task 8 Stats(**vals) 依赖 config attributes 键与 Stats 字段一致(8 键全有,已实查);Task 9 前端模板 JS 无自动化测试,靠 grep 验证+契约测试覆盖接口侧。✓
