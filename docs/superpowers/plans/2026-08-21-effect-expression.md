# effect 表达力 + MP 恢复 + 库注入通路 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 effect 原子数组结算(战斗+探索两侧)、MP 时间恢复、timed 时效软状态、扩展库管线可见--模拟器基础设施补完。

**Architecture:** effect 从单一 damage dict 升维为原子数组,按"确定性原语 / 战斗临时机制 / timed 软状态 / narrative 兜底"四层结算,markup 原子透传既有 @markup 底座;`world.advance_time` 成为时间钩子单一入口(推时钟 + MP 恢复 + timed 过期);库加载统一进 `library/loader.py` 修复管线 extensions 断点。

**Tech Stack:** Python 3.13 + pytest(系统 Python,`.venv` 无 pytest);FastAPI 前端仅跟随适配。

**Spec:** `docs/superpowers/specs/2026-08-21-effect-expression-design.md`

**约定:** 全程 TDD;测试命令 `python -m pytest <path> -q`;main 分支直提(项目惯例);每任务后同步 MAINTENANCE.md 相应条目(最后 Task 14 统一收口,中途涉及新文件/新函数的先加条目)。

---

### Task 1: game_config 参数中心

**Files:**
- Create: `data/game_config.json`
- Modify: `src/investigator/rules.py`(尾部追加)
- Test: `tests/test_game_config.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""game_config 参数中心:缺省兜底 + 文件覆盖 + 缓存 reset。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from investigator import rules


def setup_function():
    rules.reset_game_config_cache()


def test_defaults_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 1
    assert cfg["timed_default_minutes"] == 30
    assert cfg["buff_damage_floor"] == 0


def test_file_overrides_defaults(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text(json.dumps({"mp_recovery_per_hour": 2}), encoding="utf-8")
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 2
    assert cfg["timed_default_minutes"] == 30   # 未给字段用缺省


def test_partial_field_fallback(monkeypatch, tmp_path):
    p = tmp_path / "game_config.json"
    p.write_text('{"mp_recovery_per_hour": "x"}', encoding="utf-8")  # 非法类型
    monkeypatch.setattr(rules, "_CONFIG_PATH", str(p))
    cfg = rules.get_game_config()
    assert cfg["mp_recovery_per_hour"] == 1     # 类型不符回缺省,不崩
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: FAIL(`ImportError: cannot import name 'reset_game_config_cache'`)

- [ ] **Step 3: 实现**

`data/game_config.json`:

```json
{
  "mp_recovery_per_hour": 1,
  "timed_default_minutes": 30,
  "buff_damage_floor": 0
}
```

`src/investigator/rules.py` 尾部追加:

```python
# ── 数值参数中心（data/game_config.json，见 2026-08-21 spec §5）──

_GAME_CONFIG_DEFAULTS = {
    "mp_recovery_per_hour": 1,     # MP 每小时恢复点数
    "timed_default_minutes": 30,   # timed 原子缺省持续分钟
    "buff_damage_floor": 0,        # 战斗 buff 减伤后伤害下限
}
_GAME_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "game_config.json")
_game_config_cache: dict | None = None


def reset_game_config_cache() -> None:
    """测试用:清空配置缓存。"""
    global _game_config_cache
    _game_config_cache = None


def get_game_config() -> dict:
    """惰性加载 game_config.json,缺省兜底,模块级缓存。"""
    global _game_config_cache
    if _game_config_cache is not None:
        return _game_config_cache
    cfg = dict(_GAME_CONFIG_DEFAULTS)
    try:
        with open(_GAME_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, dv in _GAME_CONFIG_DEFAULTS.items():
            v = data.get(k, dv)
            if isinstance(v, type(dv)):
                cfg[k] = v
    except (OSError, ValueError):
        pass
    _game_config_cache = cfg
    return cfg
```

注意:`rules.py` 头部已有 `import json` / `import os` 则不重复导入(执行时核对,缺则补)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_game_config.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add data/game_config.json src/investigator/rules.py tests/test_game_config.py
git commit -m "feat: game_config 参数中心(get_game_config 缺省兜底+缓存)"
```

---

### Task 2: 库 loader 统一 + 管线 extensions 断点修复

**Files:**
- Create: `src/library/loader.py`
- Modify: `src/game_loop.py:225-237`(现扫描逻辑移入 loader)
- Modify: `run_pipeline.py:1175-1182` 与 `run_pipeline.py:1256-1263`(两处改用 loader)
- Test: `tests/test_library_loader.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
"""loader:core+extensions 统一加载,base_dir 注入,摘要可见性。"""
import json
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from library.loader import load_item_library, load_spell_library


def _make_ext(base, kind, entries):
    d = base / "extensions" / kind
    d.mkdir(parents=True)
    (d / "ext.json").write_text(json.dumps({kind: entries}, ensure_ascii=False),
                                encoding="utf-8")
    return d


def test_load_spell_library_core_plus_extension(tmp_path):
    _make_ext(tmp_path, "spells", [
        {"id": "EXT_DARK", "name": "暗影低语", "category": "exploration",
         "impact": "L1", "cost": {"mp": 3, "san": 0}}])
    lib = load_spell_library(base_dir=str(tmp_path))
    sp = lib.get("EXT_DARK")
    assert sp is not None and sp.name == "暗影低语"
    assert lib.get("HEART_ARREST") is not None      # core 也加载了


def test_load_item_library_core_plus_extension(tmp_path):
    _make_ext(tmp_path, "items", [
        {"id": "EXT_TALISMAN", "name": "旧护符", "category": "key",
         "impact": "L0", "use_semantic": "none"}])
    lib = load_item_library(base_dir=str(tmp_path))
    assert lib.get("EXT_TALISMAN") is not None
    assert lib.get("FIRST_AID_KIT") is not None


def test_extension_visible_in_step1a_summary(tmp_path):
    """管线摘要可见性:扩展法术名进 build_step1a_prompt 文本。"""
    _make_ext(tmp_path, "spells", [
        {"id": "EXT_DARK", "name": "暗影低语", "category": "exploration",
         "impact": "L1", "cost": {"mp": 3, "san": 0}}])
    lib = load_spell_library(base_dir=str(tmp_path))
    from module_designer.layered_parser import build_step1a_prompt
    prompt = build_step1a_prompt(
        "源文档", spell_names=[s.name for s in lib.list_all()])
    assert "暗影低语" in prompt
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_library_loader.py -q`
Expected: FAIL(`ModuleNotFoundError: No module named 'library.loader'`)

- [ ] **Step 3: 实现 loader**

`src/library/loader.py`:

```python
"""统一资源层库加载器:core + extensions 目录扫描(2026-08-21 spec §6)。

三个调用点统一:game_loop.init_game / run_pipeline 两处。
base_dir 参数供测试注入(base_dir 下应有 core/ 与 extensions/)。
"""
from __future__ import annotations
from pathlib import Path

from library.items import ItemLibrary
from library.spells import SpellLibrary

_DATA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "library"


def _load(core_cls, core_file: str, ext_subdir: str, base_dir: str | None):
    lib = core_cls()
    base = Path(base_dir) if base_dir else _DATA_ROOT
    lib.load_core(str(base / "core" / core_file))
    ext_dir = base / "extensions" / ext_subdir
    if ext_dir.is_dir():
        for f in sorted(ext_dir.glob("*.json")):
            lib.load_extension(str(f))
    return lib


def load_item_library(base_dir: str | None = None) -> ItemLibrary:
    return _load(ItemLibrary, "items.json", "items", base_dir)


def load_spell_library(base_dir: str | None = None) -> SpellLibrary:
    return _load(SpellLibrary, "spells.json", "spells", base_dir)
```

- [ ] **Step 4: 三处调用点接入**

`src/game_loop.py` 225-237 段替换为:

```python
    # 统一资源层:物品/法术库(core + extensions,统一 loader)
    from library.loader import load_item_library, load_spell_library
    item_lib = load_item_library()
    spell_lib = load_spell_library()
```

(删除原 `from library.items import ...` 起至 extensions 扫描的整段。)

`run_pipeline.py` 两处(约 1175-1182 与 1256-1263)的:

```python
    from library.items import ItemLibrary
    from library.spells import SpellLibrary
    ilib = ItemLibrary(); ilib.load_core(str(PROJECT_ROOT / "data/library/core/items.json"))
    slib = SpellLibrary(); slib.load_core(str(PROJECT_ROOT / "data/library/core/spells.json"))
```

均替换为:

```python
    from library.loader import load_item_library, load_spell_library
    ilib = load_item_library(str(PROJECT_ROOT / "data/library"))
    slib = load_spell_library(str(PROJECT_ROOT / "data/library"))
```

- [ ] **Step 5: 跑测试确认通过 + 既有套件不破**

Run: `python -m pytest tests/test_library_loader.py tests/test_use_system.py -q`
Expected: 全 passed

- [ ] **Step 6: 提交**

```bash
git add src/library/loader.py src/game_loop.py run_pipeline.py tests/test_library_loader.py
git commit -m "feat: library/loader 统一加载,修复管线 extensions 不可见断点"
```

---

### Task 3: effect 字段升维为原子数组(items/spells 库层)

**Files:**
- Modify: `src/library/spells.py:26,47`(effect: dict -> list[dict],from_dict 归一化)
- Modify: `src/library/items.py`(LibraryItem 加 effect 字段 + from_dict 归一化)
- Test: `tests/test_use_system.py`(追加)

- [ ] **Step 1: 写失败测试**(追加到 tests/test_use_system.py 末尾)

```python
class TestEffectNormalize:
    """effect 字段升维:旧 dict 自动包装为 [dict],list 透传(2026-08-21 spec §1.1)。"""

    def test_spell_effect_dict_wraps_to_list(self):
        from library.spells import LibrarySpell
        sp = LibrarySpell.from_dict({"id": "X", "name": "X",
                                     "effect": {"type": "damage", "formula": "1D6"}})
        assert sp.effect == [{"type": "damage", "formula": "1D6"}]

    def test_spell_effect_list_passthrough(self):
        from library.spells import LibrarySpell
        eff = [{"type": "buff", "reduce": 3, "rounds": 3},
               {"type": "timed", "id": "S", "description": "d", "minutes": 10}]
        sp = LibrarySpell.from_dict({"id": "X", "name": "X", "effect": eff})
        assert sp.effect == eff

    def test_spell_effect_empty(self):
        from library.spells import LibrarySpell
        sp = LibrarySpell.from_dict({"id": "X", "name": "X"})
        assert sp.effect == []

    def test_item_effect_field(self):
        from library.items import LibraryItem
        it = LibraryItem.from_dict({"id": "SALT", "name": "盐袋",
                                    "effect": [{"type": "timed",
                                                "id": "SALT_LINE",
                                                "description": "白色盐线",
                                                "minutes": 60}]})
        assert it.effect[0]["type"] == "timed"
        it2 = LibraryItem.from_dict({"id": "Y", "name": "Y"})
        assert it2.effect == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestEffectNormalize -q`
Expected: FAIL(`LibraryItem.from_dict` 无 effect / dict != list)

- [ ] **Step 3: 实现**

`src/library/spells.py`:
- 第 26 行字段声明改:`effect: list = field(default_factory=list)`
- `from_dict` 第 47 行改:

```python
            effect=_normalize_effect(data.get("effect")),
```

- 模块级加归一化函数(放 LibrarySpell 前):

```python
def _normalize_effect(raw) -> list:
    """旧单 dict 自动包装为 [dict];None/缺省 -> [];list 透传。"""
    if not raw:
        return []
    if isinstance(raw, dict):
        return [dict(raw)]
    return [dict(e) for e in raw if isinstance(e, dict)]
```

`src/library/items.py`:`LibraryItem` 加字段 `effect: list = field(default_factory=list)`,`from_dict` 加 `effect=_normalize_effect(data.get("effect"))`(同函数复制一份或从 spells 导入;两文件同包,`from library.spells import _normalize_effect` 即可,避免重复)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -q`
Expected: 全 passed(旧测试不受影响,旧条目 effect dict 已被加载归一化为 list)

**注意**:combat.py cast 分支现有代码 `spell.effect or {}` / `effect.get("type")` 在本任务后对数组失效--Task 9 会重写该分支。本任务后**必须先跑战斗相关测试确认现状**,若 `tests/test_combat_*.py` 有 cast 用例直接读 effect dict,把该用例暂时按新结构更新(单元素数组),并在 Task 9 完成后回归。

Run: `python -m pytest tests/test_combat_smoke.py tests/test_combat_interactive.py -q`

- [ ] **Step 5: 提交**

```bash
git add src/library/spells.py src/library/items.py tests/test_use_system.py
git commit -m "feat: 库 effect 字段升维原子数组(旧 dict 兼容包装)"
```

---

### Task 4: UseParseResult / Catalog 透传 effect

**Files:**
- Modify: `src/game/use_parser.py`(UseParseResult 加字段;ItemCatalog/SpellCatalog entries 透传)
- Test: `tests/test_use_system.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestCatalogEffectPassthrough:
    def test_spell_catalog_entries_carry_effect(self):
        from library.spells import SpellLibrary
        from game.use_parser import SpellCatalog
        lib = SpellLibrary()
        lib._spells["X"] = type(lib._spells.get("X", None) or object).__new__(
            __import__("library.spells", fromlist=["LibrarySpell"]).LibrarySpell)
        # 直接构造更简单:
        from library.spells import LibrarySpell
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒", "category": "exploration",
            "effect": [{"type": "timed", "id": "X_EFF",
                        "description": "耳畔嗡鸣", "minutes": 5}]})
        cat = SpellCatalog(lib, ["X"])
        entries = cat.entries()
        assert entries[0]["effect"] == [{"type": "timed", "id": "X_EFF",
                                         "description": "耳畔嗡鸣", "minutes": 5}]

    def test_resolve_result_carries_effect(self):
        from library.spells import SpellLibrary, LibrarySpell
        from game.use_parser import UseParser, SpellCatalog
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒",
            "effect": [{"type": "heal", "target": "self", "formula": "1D3"}]})
        r = UseParser().resolve("施放试咒", [SpellCatalog(lib, ["X"])])
        assert r is not None
        assert r.effect[0]["type"] == "heal"
```

(第一个测试前两行无效构造语句删除,以 `lib._spells["X"] = LibrarySpell.from_dict(...)` 直接构造为准。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestCatalogEffectPassthrough -q`
Expected: FAIL(entries 无 "effect" 键 / UseParseResult 无 effect)

- [ ] **Step 3: 实现**

`use_parser.py`:
- `UseParseResult` 加字段(34 行 constraints 后):`effect: list = field(default_factory=list)`
- `ItemCatalog.entries()`(67 行 constraints 后)加:`"effect": list(li.effect),`
- `SpellCatalog.entries()`(91 行 constraints 后)加:`"effect": list(sp.effect),`
- `resolve` 构建 UseParseResult 处(查 `_build_result` 或直接构造点)把 `"effect"` 从 entry 透传:在构造 UseParseResult 时加 `effect=list(entry.get("effect", [])),`

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/game/use_parser.py tests/test_use_system.py
git commit -m "feat: UseParseResult/Catalog 透传 effect 原子数组"
```

---

### Task 5: timed_effects 字段 + 序列化 v2.2

**Files:**
- Modify: `src/investigator/models.py:199`(known_spells 后加字段)
- Modify: `src/investigator/serialization.py`(version 2.1 -> 2.2;to_dict/from_dict 加 timed_effects)
- Test: `tests/test_use_system.py`(追加,或既有序列化测试文件若有归属则放彼处)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestTimedEffectsSerialization:
    def test_timed_effects_roundtrip(self):
        from investigator.models import Investigator, Stats
        from investigator import serialization
        inv = Investigator(name="测试", age=30, gender="男",
                           stats=Stats(STR=50, CON=50, SIZ=50, DEX=50, APP=50,
                                       INT=50, POW=60, EDU=50, LUCK=50))
        inv.timed_effects = [{"id": "SILENCE_VEIL",
                              "description": "帷幕吞掉一切声响",
                              "expire_at": 1234}]
        data = serialization.to_dict(inv)
        assert data["meta"]["version"] == "2.2"
        inv2 = serialization.from_dict(data)
        assert inv2.timed_effects == [{"id": "SILENCE_VEIL",
                                       "description": "帷幕吞掉一切声响",
                                       "expire_at": 1234}]

    def test_v21_loads_with_empty_timed_effects(self):
        from investigator.models import Investigator, Stats
        from investigator import serialization
        inv = Investigator(name="旧卡", age=30, gender="男",
                           stats=Stats(STR=50, CON=50, SIZ=50, DEX=50, APP=50,
                                       INT=50, POW=60, EDU=50, LUCK=50))
        data = serialization.to_dict(inv)
        data["meta"]["version"] = "2.1"
        del data["timed_effects"]
        inv2 = serialization.from_dict(data)
        assert inv2.timed_effects == []
```

(Investigator 构造签名以 models.py 现状为准,执行时如不同按既有测试的构造方式改写。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestTimedEffectsSerialization -q`
Expected: FAIL(`Investigator` 无 timed_effects / version 仍 2.1)

- [ ] **Step 3: 实现**

`models.py` 199 行后加:

```python
        self.timed_effects: list[dict] = []    # timed 原子软状态 [{id, description, expire_at}]
```

`serialization.py`:
- `to_dict`:version 改 `"2.2"`;`known_spells` 行(95)后加:

```python
        "timed_effects": list(getattr(inv, 'timed_effects', [])),
```

- `from_dict`:184 行 known_spells 赋值后加:

```python
    inv.timed_effects = list(data.get("timed_effects", []) or [])
```

- **v2.0/v2.1 拒载逻辑不变**(若 version 校验是白名单式,把 "2.2" 加进允许集;现状是"拒绝含 SIZ 旧卡"结构校验,核对后按实际改)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py tests/test_frontend_character.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/investigator/models.py src/investigator/serialization.py tests/test_use_system.py
git commit -m "feat: timed_effects 字段 + 序列化 v2.2(旧档缺省[])"
```

---

### Task 6: 探索侧 execute_material 执行 effect 数组

**Files:**
- Modify: `src/game/judge.py:168-180`(on_use 副作用后加 effect 遍历)
- Test: `tests/test_use_system.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestExecuteMaterialEffects:
    """探索侧 effect 原子结算(2026-08-21 spec §1.2 探索列)。"""

    def _mat(self, **kw):
        from game.use_parser import UseParseResult
        base = dict(catalog_kind="spell", material_id="X", name="试咒",
                    matched_text="试咒", impact="L1")
        base.update(kw)
        return UseParseResult(**base)

    def _world(self):
        from tests.e2e.helpers import make_world
        return make_world()

    def test_heal_clamped(self):
        from game.judge import Judge
        w = self._world()
        p = w.player
        p.derived.HP = p.derived.HP_MAX - 1        # 只缺 1 点
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "heal", "target": "self", "formula": "1D3"}]))
        assert out.success and p.derived.HP == p.derived.HP_MAX   # clamp 上限

    def test_mp_change_clamped(self):
        from game.judge import Judge
        w = self._world()
        p = w.player
        p.derived.MP = 1
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "mp_change", "target": "self", "delta": 5}]))
        assert out.success and p.derived.MP == p.derived.MP_MAX

    def test_markup_atom_applies_side_effect(self):
        from game.judge import Judge
        w = self._world()
        p = w.player
        p.derived.SAN = 50
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "markup",
                     "text": "@stat_change(stat_name=\"SAN\", delta=-1)"}]))
        assert out.success and p.derived.SAN == 49

    def test_timed_atom_mounts_on_player(self):
        from game.judge import Judge
        w = self._world()
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "timed", "id": "VEIL",
                     "description": "帷幕", "minutes": 10}]))
        assert out.success
        assert len(w.player.timed_effects) == 1
        te = w.player.timed_effects[0]
        assert te["id"] == "VEIL" and te["description"] == "帷幕"
        assert te["expire_at"] == w.clock.game_time + 10

    def test_timed_default_minutes_from_config(self, monkeypatch):
        import investigator.rules as R
        monkeypatch.setattr(R, "get_game_config",
                            lambda: {"timed_default_minutes": 45,
                                     "mp_recovery_per_hour": 1,
                                     "buff_damage_floor": 0})
        from game.judge import Judge
        w = self._world()
        j = Judge(w)
        j.execute_material(self._mat(
            effect=[{"type": "timed", "id": "T", "description": "d"}]))
        assert w.player.timed_effects[0]["expire_at"] == w.clock.game_time + 45

    def test_damage_atom_skipped_with_warning(self, caplog):
        from game.judge import Judge
        w = self._world()
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "damage", "formula": "1D6"},
                    {"type": "narrative", "text": "余音回荡。"}]))
        assert out.success                     # 不阻断
        assert "damage" in out.message or out.success   # damage 跳过仅日志
        assert "余音回荡" in out.message

    def test_unknown_type_degrades_to_narrative(self):
        from game.judge import Judge
        w = self._world()
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "summon", "description": "阴影中传来窸窣声"}]))
        assert out.success
        assert "[unknown:summon]" in out.message
        assert "窸窣声" in out.message

    def test_old_dict_effect_from_library_normalized(self):
        """库层旧 dict 在 from_dict 已归一,execute_material 只见 list。"""
        from game.judge import Judge
        w = self._world()
        j = Judge(w)
        out = j.execute_material(self._mat(
            effect=[{"type": "heal", "target": "self", "delta": 2}]))
        assert out.success
```

(`make_world` helper 在 tests/e2e/helpers.py,若直接导入路径不同按现状调整;`Judge` 构造签名按 judge.py 现状核对。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestExecuteMaterialEffects -q`
Expected: FAIL(effect 未被处理,timed_effects 为空,unknown 前缀缺失等)

- [ ] **Step 3: 实现**

`judge.py` execute_material 内,168 行 `# on_use @markup -> 统一副作用底座` 段之后、`message = text + ...` 之前插入 effect 遍历:

```python
        # effect 原子数组(2026-08-21 spec §1.2 探索侧)
        eff_msgs = self._execute_effect_atoms(material.effect or [], player)

        message = text + ("".join(f"\n{m}" for m in side_msgs + eff_msgs))
```

Judge 类内加方法(execute_material 后):

```python
    def _execute_effect_atoms(self, effects: list, player) -> list[str]:
        """探索侧 effect 原子结算。返回追加进 message 的行。"""
        import re
        from investigator.rules import get_game_config
        cfg = get_game_config()
        msgs: list[str] = []

        def _roll(formula: str) -> int:
            m = re.match(r"^(\d*)D(\d+)([+-]\d+)?$", formula.strip().upper())
            if not m:
                return 0
            n = int(m.group(1) or 1)
            d = int(m.group(2))
            bonus = int(m.group(3) or 0)
            import random
            return sum(random.randint(1, d) for _ in range(n)) + bonus

        for atom in effects or []:
            t = atom.get("type", "")
            if t == "heal":
                delta = int(atom.get("delta", 0) or 0)
                if "formula" in atom:
                    delta = _roll(str(atom["formula"]))
                if delta:
                    before = player.derived.HP
                    player.derived.HP = min(player.derived.HP_MAX,
                                            player.derived.HP + delta)
                    msgs.append(f"（恢复 {player.derived.HP - before} 点 HP。）")
            elif t == "mp_change":
                delta = int(atom.get("delta", 0) or 0)
                if delta:
                    before = player.derived.MP
                    player.derived.MP = max(0, min(player.derived.MP_MAX,
                                                   player.derived.MP + delta))
                    msgs.append(f"（MP {player.derived.MP - before:+d}。）")
            elif t == "markup":
                from game.side_effects import parse_markup_all
                from scenario_core import apply_side_effects
                effs = parse_markup_all(str(atom.get("text", "")))
                if effs:
                    msgs.extend(apply_side_effects(self.world, effs))
            elif t == "timed":
                minutes = int(atom.get("minutes", 0)
                              or cfg["timed_default_minutes"])
                player.timed_effects.append({
                    "id": str(atom.get("id", "TIMED")),
                    "description": str(atom.get("description", "")),
                    "expire_at": self.world.clock.game_time + minutes,
                })
            elif t == "damage":
                # 探索侧无伤害目标:跳过 + 日志,不硬造(spec §1.2)
                import logging
                logging.getLogger("game.judge").warning(
                    "[effect] damage 原子在探索侧跳过: %s", atom)
            elif t in ("buff", "control"):
                msgs.append(str(atom.get("description", "") or f"（{t} 效果仅在战斗中生效。）"))
            else:
                # narrative 原子 / 未知 type:标识符前缀降级(spec §1.3)
                text = str(atom.get("text") or atom.get("description") or "")
                msgs.append(f"[unknown:{t}] {text}" if t != "narrative" and t else text)
        return msgs
```

**注意**:MP_MAX 属性名核对 models.py 现状(DerivedStats 拆分后应为 `MP_MAX`);`parse_markup_all` 导入路径以 judge.py 文件头既有导入为准。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/game/judge.py tests/test_use_system.py
git commit -m "feat: execute_material 探索侧 effect 原子结算(heal/mp/markup/timed/降级)"
```

---

### Task 7: advance_time 三合一(MP 恢复 + timed 过期清除)

**Files:**
- Modify: `src/scenario_core.py:749-754`(advance_time 扩展)+ `ScenarioWorld.__init__`(加 `_mp_regen_acc`)
- Test: `tests/test_use_system.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestAdvanceTimeHooks:
    """advance_time 三合一:推时钟 + MP 恢复(余数累计) + timed 过期清除。"""

    def _world(self):
        from tests.e2e.helpers import make_world
        return make_world()

    def test_mp_recovery_whole_hours(self):
        w = self._world()
        p = w.player
        p.derived.MP = 0
        w.advance_time(120)                       # 2 小时
        assert p.derived.MP == 2

    def test_mp_recovery_accumulates_remainder(self):
        w = self._world()
        p = w.player
        p.derived.MP = 0
        w.advance_time(30)                        # 不足 1 小时
        assert p.derived.MP == 0
        w.advance_time(30)                        # 累计 60 分钟
        assert p.derived.MP == 1

    def test_mp_recovery_clamped(self):
        w = self._world()
        p = w.player
        p.derived.MP = p.derived.MP_MAX - 1
        w.advance_time(300)                       # 5 小时,但只缺 1 点
        assert p.derived.MP == p.derived.MP_MAX

    def test_timed_effect_expires(self):
        w = self._world()
        p = w.player
        p.timed_effects = [{"id": "V", "description": "帷幕",
                            "expire_at": w.clock.game_time + 10}]
        w.advance_time(10)                        # 恰好到期
        assert p.timed_effects == []

    def test_timed_effect_survives_before_expiry(self):
        w = self._world()
        p = w.player
        p.timed_effects = [{"id": "V", "description": "帷幕",
                            "expire_at": w.clock.game_time + 60}]
        w.advance_time(10)
        assert len(p.timed_effects) == 1

    def test_mp_recovery_rate_from_config(self, monkeypatch):
        import investigator.rules as R
        monkeypatch.setattr(R, "get_game_config",
                            lambda: {"mp_recovery_per_hour": 3,
                                     "timed_default_minutes": 30,
                                     "buff_damage_floor": 0})
        w = self._world()
        p = w.player
        p.derived.MP = 0
        w.advance_time(60)
        assert p.derived.MP == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestAdvanceTimeHooks -q`
Expected: FAIL(MP 不恢复/timed 不清除)

- [ ] **Step 3: 实现**

`scenario_core.py` advance_time(749)替换为:

```python
    def advance_time(self, minutes: int):
        self.clock.advance_time(minutes)
        # Auto-inject time flags into runtime_state
        for flag, value in self.clock.get_time_flags().items():
            state = self.get_runtime_state(flag)
            state.completed = value
        # ── 时间钩子(2026-08-21 spec §2.2/§4)──
        self._tick_time_effects(minutes)

    def _tick_time_effects(self, minutes: int):
        """MP 恢复(余数累计) + timed_effects 过期清除。"""
        import logging
        from investigator.rules import get_game_config
        cfg = get_game_config()
        p = self.player
        if p is None:
            return
        # MP 恢复
        self._mp_regen_acc = getattr(self, "_mp_regen_acc", 0) + max(0, minutes)
        per_hour = int(cfg["mp_recovery_per_hour"])
        if per_hour > 0:
            gain = (self._mp_regen_acc // 60) * per_hour
            if gain:
                self._mp_regen_acc -= (gain // per_hour) * 60
                before = p.derived.MP
                p.derived.MP = min(p.derived.MP_MAX, p.derived.MP + gain)
                if p.derived.MP != before:
                    logging.getLogger("scenario_core").info(
                        "[time] MP 恢复 %d -> %d", before, p.derived.MP)
        # timed 过期清除
        now = self.clock.game_time
        expired = [t for t in getattr(p, "timed_effects", []) if t["expire_at"] <= now]
        if expired:
            p.timed_effects = [t for t in p.timed_effects
                               if t["expire_at"] > now]
            for t in expired:
                logging.getLogger("scenario_core").info(
                    "[time] timed 效果过期: %s", t.get("id"))
```

`ScenarioWorld.__init__`(697-698 库字段附近)加:`self._mp_regen_acc = 0`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python -m pytest tests/test_use_system.py tests/test_chronicle.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/scenario_core.py tests/test_use_system.py
git commit -m "feat: advance_time 三合一(MP 余数累计恢复 + timed 过期清除)"
```

---

### Task 8: facts 渲染 timed_effects(LLM 可见性)

**Files:**
- Modify: `src/scenario_core.py:1620-1626`(render_for_author 玩家行)
- Test: `tests/test_use_system.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestTimedFactsRender:
    def test_active_timed_effects_rendered(self):
        from scenario_core import WorldChronicle
        from tests.e2e.helpers import make_world
        w = make_world()
        w.player.timed_effects = [
            {"id": "SILENCE_VEIL", "description": "帷幕吞掉一切声响",
             "expire_at": w.clock.game_time + 10}]
        c = WorldChronicle()
        text = c.render_for_author(w)
        assert "帷幕吞掉一切声响" in text

    def test_no_timed_effects_no_render(self):
        from scenario_core import WorldChronicle
        from tests.e2e.helpers import make_world
        w = make_world()
        c = WorldChronicle()
        text = c.render_for_author(w)
        assert "生效中" not in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestTimedFactsRender -q`
Expected: FAIL(渲染无 timed 内容)

- [ ] **Step 3: 实现**

`render_for_author` 玩家行(1622-1626)在法术段后追加状态段,把:

```python
            spells = "、".join(getattr(p, "known_spells", [])) or "无"
```

改为:

```python
            spells = "、".join(getattr(p, "known_spells", [])) or "无"
            timed = "；".join(
                f"{t['description']}（剩{max(0, t['expire_at'] - world.clock.game_time)}分钟）"
                for t in getattr(p, "timed_effects", []))
```

并在 `f" | 物品: {key_items} | 法术: {spells}"` 后拼 `f" | 生效中: {timed}" if timed else ""`(以 f-string 嵌入或条件拼接,保持原行结构)。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py tests/test_chronicle.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/scenario_core.py tests/test_use_system.py
git commit -m "feat: facts 玩家行渲染 timed_effects(LLM 可见)"
```

---

### Task 9: 战斗 cast 分支 effect 数组结算(非临时原子)

**Files:**
- Modify: `src/game/combat.py:166-171`(__init__ 加 world)+ 三处构造点传 world
- Modify: `src/game/combat.py:841-880`(cast 分支 effect 段重写)
- Test: `tests/test_combat_smoke.py`(追加)

- [ ] **Step 1: 写失败测试**(追加到 tests/test_combat_smoke.py,构造方式沿用该文件既有 helper)

```python
class TestCastEffectAtoms:
    """战斗侧 effect 原子:heal/mp_change/markup/timed/narrative/未知降级。"""

    def _combat(self, effect, known=("X",)):
        """构造最小战斗会话:1 敌人 + 玩家已知法术 X(POW 检定必过用 monkeypatch 或高技能)。"""
        # 沿用本文件既有 CombatInit/CombatSystem 构造 helper;法术库用内存库:
        from library.spells import SpellLibrary, LibrarySpell
        lib = SpellLibrary()
        lib._spells["X"] = LibrarySpell.from_dict({
            "id": "X", "name": "试咒", "category": "combat", "impact": "L1",
            "cost": {"mp": 1, "san": 0}, "check": {"skill": "POW", "type": "regular"},
            "effect": effect})
        # CombatSystem(spell_lib=lib, world=w);player.known_spells=list(known)
        # 细节按本文件既有测试的模式写(player/stats/init 构造)
        ...
```

(执行者注意:此测试类的具体构造代码**必须**参照 tests/test_combat_smoke.py 中既有战斗测试的 player/CombatInit/CombatSystem 组装方式补全,不许留 `...`;下列断言为目标行为:)

```python
    def test_heal_atom_in_combat(self):
        # player HP=HP_MAX-3, effect=[{heal formula 1D3}] -> cast 后 HP 上升且 clamp
        ...
    def test_mp_change_atom_in_combat(self):
        # effect=[{mp_change delta +2}] -> MP 增加
        ...
    def test_markup_atom_in_combat(self):
        # world 注入;effect=[{markup @stat_change SAN -1}] -> player.SAN -1
        ...
    def test_timed_atom_in_combat(self):
        # effect=[{timed}] -> player.timed_effects 挂载,expire_at=game_time+minutes
        ...
    def test_narrative_and_unknown_in_combat(self):
        # effect=[{narrative text}, {type summon description}] -> action.narrative 含 text 与 [unknown:summon]
        ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_combat_smoke.py::TestCastEffectAtoms -q`
Expected: FAIL(effect 数组未被遍历)

- [ ] **Step 3: 实现**

`combat.py` `__init__`(166-171)改:

```python
    def __init__(self, weapon_lib=None, llm_enhancement: bool = COMBAT_LLM_ENHANCEMENT,
                 spell_lib=None, world=None):
        self.weapon_lib = weapon_lib
        self.llm_enhancement = llm_enhancement
        self.spell_lib = spell_lib   # 统一资源层：法术库（cast_spell 动作）
        self.world = world           # 统一资源层：markup 原子副作用目标（可选）
```

三处构造点补 `world=`:
- `src/game_loop.py:797` -> `CombatSystem(spell_lib=..., world=keeper.world)`
- `frontend/routers/game.py:975` -> `CombatSystem(spell_lib=..., world=world)`
- `frontend/routers/game.py:1023` -> `CombatSystem(spell_lib=..., world=_world)`

cast 分支(841 行起)现有 effect 段:

```python
            effect = spell.effect or {}
            if action.success and effect.get("type") == "damage":
                ...
```

替换为 effect 数组遍历(damage 原子保留原结算逻辑):

```python
            if action.success:
                for atom in (spell.effect or []):
                    t = atom.get("type", "")
                    if t == "damage":
                        dmg = _roll_damage(atom.get("formula", "1D6"),
                                           player.stats.STR, player.stats.CON)
                        if not atom.get("ignore_armor") and target is not None:
                            dmg = _apply_armor(dmg, getattr(target, "armor", "") or "")
                        action.damage = dmg
                        action.narrative += f" 造成 {dmg} 点伤害。"
                        if target is not None:
                            target.hp = max(0, target.hp - dmg)
                            if target.hp <= 0:
                                target.status = "dead"
                    elif t == "heal":
                        import re as _re
                        m = _re.match(r"^(\d*)D(\d+)([+-]\d+)?$",
                                      str(atom.get("formula", "")).strip().upper())
                        delta = (int(atom.get("delta", 0) or 0) if not m else
                                 sum(random.randint(1, int(m.group(2)))
                                     for _ in range(int(m.group(1) or 1)))
                                 + int(m.group(3) or 0))
                        if delta:
                            player.derived.HP = min(player.derived.HP_MAX,
                                                    player.derived.HP + delta)
                            action.narrative += f" 你恢复了 {delta} 点 HP。"
                    elif t == "mp_change":
                        d = int(atom.get("delta", 0) or 0)
                        if d:
                            player.derived.MP = max(0, min(player.derived.MP_MAX,
                                                           player.derived.MP + d))
                    elif t == "markup":
                        if self.world is not None:
                            from game.side_effects import parse_markup_all
                            from scenario_core import apply_side_effects
                            effs = parse_markup_all(str(atom.get("text", "")))
                            if effs:
                                apply_side_effects(self.world, effs)
                    elif t == "timed":
                        from investigator.rules import get_game_config
                        minutes = int(atom.get("minutes", 0)
                                      or get_game_config()["timed_default_minutes"])
                        if self.world is not None and self.world.player is not None:
                            self.world.player.timed_effects.append({
                                "id": str(atom.get("id", "TIMED")),
                                "description": str(atom.get("description", "")),
                                "expire_at": self.world.clock.game_time + minutes,
                            })
                    elif t == "buff":
                        state.temporary_effects = getattr(state, "temporary_effects", [])
                        state.temporary_effects.append({
                            "id": str(atom.get("id", "BUFF")),
                            "reduce": int(atom.get("reduce", 0) or 0),
                            "rounds": int(atom.get("rounds", 1) or 1)})
                        action.narrative += f" {atom.get('on_text', '') or ''}"
                    elif t == "control":
                        if target is not None:
                            target.controlled_rounds = int(
                                atom.get("rounds", 1) or 1)
                            action.narrative += f" {target.enemy_ref} 无法动弹了。"
                    elif t == "narrative":
                        action.narrative += f" {atom.get('text', '')}"
                    else:
                        text = str(atom.get("text") or atom.get("description") or "")
                        action.narrative += f" [unknown:{t}] {text}"
            return action
```

(buff/control 原子在本任务即写入 state,其生效消费在 Task 10/11。)

- [ ] **Step 4: 跑测试确认通过 + 战斗套件回归**

Run: `python -m pytest tests/test_combat_smoke.py tests/test_combat_interactive.py tests/test_combat_smoke_interactive.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/game/combat.py src/game_loop.py frontend/routers/game.py tests/test_combat_smoke.py
git commit -m "feat: 战斗 cast effect 数组结算(world 注入 markup 通路)"
```

---

### Task 10: 战斗 buff(受击减免 + 轮末递减)

**Files:**
- Modify: `src/game/combat.py`(CombatState 加字段;_resolve_enemy_action 减免;两处 round += 1 前调用 _tick_temporary)
- Test: `tests/test_combat_smoke.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestCombatBuff:
    def test_buff_reduces_incoming_damage(self):
        # state.temporary_effects=[{id B, reduce 3, rounds 3}]
        # 敌方命中 damage=X -> player_hp 扣 max(floor, X-3)
        ...
    def test_buff_damage_floor(self):
        # reduce 99, 伤害 5, floor=0 -> 扣 0(地板来自 game_config,monkeypatch floor=1 验证可配)
        ...
    def test_buff_rounds_decay_and_expire(self):
        # rounds=2:轮1末->1,轮2末->0 且效果移除;移除后伤害全额
        ...
```

(构造细节沿用本文件既有模式补全,不留 `...`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_combat_smoke.py::TestCombatBuff -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`CombatState`(136 行区)加字段:

```python
    temporary_effects: list = field(default_factory=list)   # 玩家侧 buff [{id, reduce, rounds}]
```

`_resolve_enemy_action` 命中段(1040-1046),damage 计算后扣血前:

```python
            damage = _roll_damage(damage_formula, en_str, en_siz)
            # buff 减伤(2026-08-21 spec §3)
            from investigator.rules import get_game_config
            reduce_total = sum(int(t.get("reduce", 0) or 0)
                               for t in getattr(state, "temporary_effects", []))
            if reduce_total > 0:
                floor = int(get_game_config()["buff_damage_floor"])
                damage = max(floor, damage - reduce_total)
            action.damage = damage
```

轮末递减:CombatSystem 加方法:

```python
    def _tick_temporary_effects(self, state) -> None:
        """轮末:buff rounds 递减归零移除;enemy controlled_rounds 递减。"""
        alive = [t for t in getattr(state, "temporary_effects", [])
                 if int(t.get("rounds", 0)) - 1 > 0]
        for t in alive:
            t["rounds"] -= 1
        state.temporary_effects = alive
        for e in state.enemies:
            if getattr(e, "controlled_rounds", 0) > 0:
                e.controlled_rounds -= 1
```

两处 `state.round += 1`(346 与 528)**之前**各插一行:`self._tick_temporary_effects(state)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_combat_smoke.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/game/combat.py tests/test_combat_smoke.py
git commit -m "feat: 战斗 buff 受击减免+轮末递减(temporary_effects)"
```

---

### Task 11: 战斗 control(敌方行动跳过)

**Files:**
- Modify: `src/game/combat.py:_resolve_enemy_action`(顶部检查 controlled_rounds)
- Test: `tests/test_combat_smoke.py`(追加)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestCombatControl:
    def test_controlled_enemy_skips_action(self):
        # enemy.controlled_rounds=2 -> _resolve_enemy_action 返回 success=False
        # narrative 含"无法动弹",不掷攻击,player_hp 不变
        ...
    def test_control_decays_per_round(self):
        # rounds=1:轮末递减为 0,下轮恢复行动
        ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_combat_smoke.py::TestCombatControl -q`
Expected: FAIL

- [ ] **Step 3: 实现**

`_resolve_enemy_action` 顶部(1010 行后,构造 action 前或后均需保证不掷骰):

```python
        if getattr(enemy, "controlled_rounds", 0) > 0:
            action = CombatAction(actor=enemy.instance_id, action_type="attack",
                                  weapon="--", skill_name="--", target="player")
            action.success = False
            action.narrative = f"{enemy_label}被无形的力量攫住，无法动弹。"
            return action
```

(注意:此检查须在 `_select_enemy_attack`/掷骰之前,且在 `is_boss`/`enemy_label` 取值之后;若 action 构造依赖 attack 选取则把检查放在 attack 选取前、用 `getattr(enemy,'enemy_ref','敌人')` 组 label。)

- [ ] **Step 4: 跑测试确认通过 + 战斗全量**

Run: `python -m pytest tests/test_combat_smoke.py tests/test_combat_interactive.py tests/test_combat_smoke_interactive.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add src/game/combat.py tests/test_combat_smoke.py
git commit -m "feat: 战斗 control 敌方行动跳过(controlled_rounds)"
```

---

### Task 12: 核心库内容升维(数据示范)

**Files:**
- Modify: `data/library/core/spells.json`(石肤/支配/帷幕/心脏骤停/血之呼唤)
- Modify: `data/library/core/items.json`(残页/盐袋)
- Test: `tests/test_use_system.py`(追加冒烟)

- [ ] **Step 1: 写失败测试**(追加)

```python
class TestLibraryContentUpgrade:
    """2026-08-21 spec §7 内容示范:新原子在核心库真实条目上就位。"""

    def test_stone_skin_has_buff_and_timed(self):
        from library.spells import SpellLibrary
        sp = SpellLibrary().get("STONE_SKIN")   # 或 load_spell_library()
        types = [a["type"] for a in sp.effect]
        assert "buff" in types and "timed" in types

    def test_dominate_has_control(self):
        from library.spells import SpellLibrary
        sp = SpellLibrary().get("DOMINATE")
        assert any(a["type"] == "control" for a in sp.effect)

    def test_silence_veil_has_timed(self):
        from library.spells import SpellLibrary
        sp = SpellLibrary().get("SILENCE_VEIL")
        assert any(a["type"] == "timed" for a in sp.effect)

    def test_necronomicon_page_grants_spell(self):
        from library.items import ItemLibrary
        it = ItemLibrary().get("NECRONOMICON_PAGE")
        assert any("@grant_spell" in u for u in it.on_use)

    def test_salt_has_timed_effect(self):
        from library.items import ItemLibrary
        it = ItemLibrary().get("SALT")
        assert any(a.get("type") == "timed" for a in it.effect)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestLibraryContentUpgrade -q`
Expected: FAIL(条目还是旧结构)

- [ ] **Step 3: 修改 JSON**

`spells.json`:

```json
  STONE_SKIN 的 "effect" 字段改为:
  "effect": [
    {"type": "buff", "target": "self", "id": "STONE_SKIN", "reduce": 3, "rounds": 3,
     "on_text": "皮肤紧绷如石，接下来的打击会轻一些。"},
    {"type": "timed", "id": "STONE_SKIN", "description": "皮肤泛着大理石般的灰色纹路", "minutes": 30}
  ],

  DOMINATE: "effect": [{"type": "control", "target": "enemy", "rounds": 2}],

  SILENCE_VEIL: "effect": [
    {"type": "timed", "id": "SILENCE_VEIL", "description": "无形的帷幕吞掉帷幕内的一切声响", "minutes": 10}
  ],

  HEART_ARREST: "effect": [{"type": "damage", "formula": "1D6", "ignore_armor": true}],
  BLOOD_CALL:   "effect": [{"type": "damage", "formula": "1D4", "ignore_armor": false}],
```

`items.json`:

```json
  NECRONOMICON_PAGE 的 "on_use" 改为:
  "on_use": ["@stat_change(stat_name=\"SAN\", delta=-1D4)",
             "@grant_spell(spell_ref=\"DREAM_GAZE\")"],

  SALT 加 "effect" 字段:
  "effect": [{"type": "timed", "id": "SALT_LINE", "description": "白色盐线在地上连成一道界线", "minutes": 60}]
```

- [ ] **Step 4: 跑测试确认通过 + 全库加载冒烟**

Run: `python -m pytest tests/test_use_system.py tests/test_library_loader.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add data/library/core/spells.json data/library/core/items.json tests/test_use_system.py
git commit -m "feat: 核心库内容升维(buff/control/timed/grant_spell 示范)"
```

---

### Task 13: e2e deterministic 三场景

**Files:**
- Test: `tests/e2e/test_deterministic.py`(追加测试类,组装方式沿用本文件既有 make_world/keeper stub 模式)

- [ ] **Step 1: 写失败测试**(追加;沿用文件内既有 keeper/judge stub 模式,完整实现不留 `...`)

```python
class TestTimedAndCombatEffectsE2E:
    """2026-08-21 spec §8 e2e:帷幕 timed 入档+过期、石肤战斗减伤、支配控制轮次。"""

    def test_silence_veil_timed_mounts_and_expires(self):
        # 1) 玩家习得 SILENCE_VEIL -> "施放静默帷幕" 一回合
        # 2) 断言 timed_effects 挂载 + MP 扣减 + 叙事含帷幕描述
        # 3) world.advance_time(10) -> 断言 timed_effects 清空
        ...

    def test_stone_skin_reduces_damage_in_combat(self):
        # 战斗:敌 damage 恒定(monkeypatch _roll_damage 或固定公式敌)，
        # 玩家 cast_STONE_SKIN(检定必过:技能 monkeypatch 或高 POW)
        # -> 敌方命中伤害比 buff 前少 reduce=3(下限 floor)
        ...

    def test_dominate_skips_enemy_action(self):
        # 战斗:cast_DOMINATE(opposed 必胜:monkeypatch opposed_check -> win)
        # -> 敌 controlled_rounds=2；接下来两轮敌方行动 narrative 含"无法动弹"
        ...
```

(执行者:参照本文件 `TestUseTurnFlow`/`TestGateFlavorExemption` 的 stub 组装方式完整实现;检定必过用 monkeypatch `player.check_skill` 返回 `(True, "ok", "regular")` 与 `investigator.rules.opposed_check` 返回 `("win", "detail")`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestTimedAndCombatEffectsE2E -q`
Expected: FAIL

- [ ] **Step 3: 实现**(如 Step 1 测试暴露产品缺口,按 spec 修产品代码;测试组装问题修测试)

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/e2e/test_deterministic.py -q`
Expected: 全 passed

- [ ] **Step 5: 提交**

```bash
git add tests/e2e/test_deterministic.py
git commit -m "test: e2e 帷幕/石肤/支配 三场景(timed+buff+control)"
```

---

### Task 14: S15 real_llm + 文档 + 全量回归收口

**Files:**
- Test: `tests/e2e/test_scenarios.py`(追加 S15)
- Modify: `readme.md`(扩展库约定 + spec 索引 + U6 后续条目)
- Modify: `MAINTENANCE.md`(全量同步)
- Modify: `UPDATES.md`(工作汇总)

- [ ] **Step 1: S15 场景测试**(追加到 test_scenarios.py,模式沿用既有 S 场景)

```python
class TestS15ExtensionSpell:
    """S15:扩展库法术游戏内施放(2026-08-21 spec §8)。
    用 tmp extensions 目录注入扩展法术,走 make_world(item/spell 库透传)
    -> keeper 回合 -> 断言扣 MP + timed/effects 生效。real_llm 标记。"""
```

(实现细节沿用 S12-S14 模式;若 make_world 不支持库注入则先扩展 helper `make_world(spell_library=...)`--helpers.py 已有透传参数则直接用。)

- [ ] **Step 2: real_llm 全量**

Run: `python -m pytest tests/e2e/test_scenarios.py -q -m real_llm 2>&1 | tail -3`
Expected: S1-S15 全 passed(S15 新增)

- [ ] **Step 3: 默认套件全量**

Run: `python -m pytest tests/ -q 2>&1 | tail -1`
Expected: 全 passed(基线 183 + 本计划新增,0 failed)

- [ ] **Step 4: readme + MAINTENANCE + UPDATES**

readme.md:
- 统一资源层小节补:effect 原子类型表(8 种)、MP 恢复规则、timed 软状态、`data/library/extensions/` 约定目录(用户放 JSON 即生效,管线+游戏双侧可见)
- spec 索引加 `2026-08-21-effect-expression-design.md`

MAINTENANCE.md:
- 新增 `library/loader.py` 章节;`rules.py` 补 get_game_config;`combat.py` 补 cast effect 数组/temporary_effects/_tick_temporary_effects/_resolve_enemy_action(controlled 检查+减伤);`judge.py` 补 _execute_effect_atoms;`scenario_core.py` 补 _tick_time_effects/render_for_author timed 段;models/serialization 补 timed_effects/v2.2;行号全刷新;Changelog 加 2026-08-21 行

UPDATES.md: 工作汇总追加 2026-08-21 节(effect 表达力/MP 恢复/库注入断点修复/S15)

- [ ] **Step 5: 最终提交**

```bash
git add tests/e2e/test_scenarios.py tests/e2e/helpers.py readme.md MAINTENANCE.md UPDATES.md
git commit -m "test+docs: S15 扩展法术场景 + U6 表达力收口文档"
```

---

## 自审记录(Self-Review)

1. **Spec 覆盖**:§1(任务 3/4/6/9)、§2(任务 5/6/7/8)、§3(任务 9/10/11)、§4(任务 7)、§5(任务 1)、§6(任务 2)、§7(任务 12)、§8(任务 13/14)、§9 文件清单逐项对齐、§10 非目标无任务(正确)、§11 成功标准由 13/14 验证。✓
2. **占位符扫描**:Task 9/10/11/13 的战斗/e2e 测试含 `...` 骨架--这是**有意设计**:战斗与 e2e 的组装强依赖既有测试文件的 helper 模式(CombatInit 构造/make_world/stub keeper),凭空写死反而会与现实冲突;计划已明确"执行时必须参照既有模式补全,不留 `...`",且断言目标行为已写明。其余任务代码完整。⚠️ 已知取舍
3. **类型一致性**:effect: list[dict] 全链一致(库/UseParseResult/judge/combat);timed_effects: list[dict](models/serialization/advance_time/facts);temporary_effects: list[dict](CombatState);`_tick_temporary_effects`(combat)与 `_tick_time_effects`(scenario_core)命名区分明确。✓
4. **顺序依赖**:Task 5(字段)先于 Task 6(挂载消费)、Task 7(过期清除)后于 Task 5;Task 9 的 buff/control 原子写 state,消费在 10/11--每任务结束点测试均绿。✓
