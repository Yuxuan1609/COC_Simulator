# 统一资源层与影响层级 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 U6 法术 + U8 物品统一资源层与影响层级分类（L0/L1/L2），含 UseParser 子系统、@grant_spell、MP/HP 修复、门控 flavor 豁免、战斗施法与模组管线感知。

**Architecture:** 影响层级为分类轴心（素材类型仅描述元数据）；UseParser 独立小 parse 系统（目录可注入，确定性优先 + LLM 兜底）；结果标准化编译为 @markup 走既有 apply_side_effects 底座；检定能力下沉 Judge 通用层复用 check_skill 全套设施。

**Tech Stack:** Python 3.13, pytest（系统 Python 直跑 `python -m pytest`；注意 `.venv` 无 pytest）。spec：`docs/superpowers/specs/2026-08-18-unified-resource-impact-design.md`

**约定：** 每个任务 TDD（先写失败测试）；测试命令一律在项目根目录执行；commit 信息跟随仓库中文风格。所有新测试单元级放 `tests/test_use_system.py`（顶部需 `sys.path` 注入 src，见 Task 1），回合级放 `tests/e2e/test_deterministic.py`。

---

### Task 1: MP_MAX 拆分 + recalc 保留当前值（前置修复）

**Files:**
- Create: `tests/test_use_system.py`
- Modify: `src/investigator/rules.py:51-62`（calc_derived）
- Modify: `src/investigator/models.py:26-36`（DerivedStats）、`:303-307`（_recalc_derived）、`:361-367`（modify_stat CON/POW 分支）
- Modify: `src/investigator/serialization.py:61-67`（to_dict derived）、`:129-135`（from_dict derived）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_use_system.py`：

```python
"""统一资源层（U6 法术 + U8 物品）单元测试。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _inv():
    from investigator import Investigator
    from investigator.models import Stats
    from investigator.rules import calc_derived
    inv = Investigator(name="测试员", stats=Stats(
        STR=50, CON=60, DEX=50, APP=50, INT=70, POW=60, EDU=70, LUCK=50))
    inv.derived = calc_derived(inv.stats)
    return inv


class TestRecalcPreservesCurrent:
    def test_recalc_keeps_current_mp_hp_san(self):
        inv = _inv()
        inv.derived.MP = 2
        inv.derived.HP = 3
        inv.derived.SAN = 40
        inv._recalc_derived()
        assert inv.derived.MP_MAX == 12
        assert inv.derived.MP == 2, "recalc 不得重置当前 MP"
        assert inv.derived.HP == 3, "recalc 不得重置当前 HP"
        assert inv.derived.SAN == 40, "recalc 不得重置当前 SAN"

    def test_pow_growth_carries_mp(self):
        inv = _inv()          # POW60 -> MP_MAX 12
        inv.derived.MP = 2
        inv.modify_stat("POW", 10)   # POW70 -> MP_MAX 14，当前同步涨 2
        assert inv.derived.MP_MAX == 14
        assert inv.derived.MP == 4

    def test_pow_shrink_clamps_mp(self):
        inv = _inv()
        inv.modify_stat("POW", -10)  # POW50 -> MP_MAX 10，clamp
        assert inv.derived.MP_MAX == 10
        assert inv.derived.MP <= 10

    def test_con_growth_carries_hp(self):
        inv = _inv()          # HP_MAX 20
        inv.derived.HP = 5
        inv.modify_stat("CON", 30)   # CON90 -> HP_MAX 30，当前涨 10
        assert inv.derived.HP_MAX == 30
        assert inv.derived.HP == 15
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py -v`
Expected: FAIL（`AttributeError: MP_MAX` 或 recalc 后当前值被重置）

- [ ] **Step 3: 实现**

`src/investigator/models.py` DerivedStats（:26-36）`MP` 行后加：

```python
    MP_MAX: int = 0       # 魔法值上限 = floor(POW/5)
```

models.py 模块级（class Investigator 之前）加：

```python
def _carry_current(current: int, old_max: int, new_max: int) -> int:
    """上限变化时携带当前值：涨上限当前值同步涨差值，降上限 clamp。"""
    if new_max >= old_max:
        return min(current + (new_max - old_max), new_max)
    return min(current, new_max)
```

`_recalc_derived`（:303-307）替换为：

```python
    def _recalc_derived(self):
        """级联更新衍生属性：只重算上限/DB/BUILD/DODGE，当前值（HP/MP/SAN）保留并 clamp。"""
        from investigator.rules import calc_derived
        cthulhu = self.get_skill_value("克苏鲁神话")
        old = self.derived
        new = calc_derived(self.stats, self.age, cthulhu)
        new.HP = _carry_current(old.HP, old.HP_MAX, new.HP_MAX)
        new.MP = _carry_current(old.MP, getattr(old, "MP_MAX", old.MP), new.MP_MAX)
        new.SAN = min(old.SAN, new.SAN_MAX)   # SAN 当前值永不重置
        self.derived = new
```

`modify_stat`（:361-367）CON/POW 分支替换为：

```python
            if upper == "CON":
                _old_max = self.derived.HP_MAX
                self.derived.HP_MAX = max(1, stats.CON // 3)
                self.derived.HP = _carry_current(self.derived.HP, _old_max, self.derived.HP_MAX)
                detail += f", HP={self.derived.HP}/{self.derived.HP_MAX}"
            if upper == "POW":
                _old_max = getattr(self.derived, "MP_MAX", self.derived.MP)
                self.derived.MP_MAX = max(0, math.floor(stats.POW / 5))
                self.derived.MP = _carry_current(self.derived.MP, _old_max, self.derived.MP_MAX)
                detail += f", MP={self.derived.MP}/{self.derived.MP_MAX}"
```

`src/investigator/rules.py` calc_derived（:59-62）DerivedStats(...) 改为：

```python
    return DerivedStats(
        HP=hp, HP_MAX=hp, MP=mp, MP_MAX=mp, SAN=san, SAN_MAX=san_max,
        DB=db, BUILD=build, DODGE=dodge,
    )
```

`src/investigator/serialization.py` to_dict derived（:61-67）`"MP"` 行改为 `"MP": inv.derived.MP, "MP_MAX": inv.derived.MP_MAX,`；from_dict derived（:129-135）`MP=` 行改为：

```python
        MP=derived_data.get("MP", 0),
        MP_MAX=derived_data.get("MP_MAX", derived_data.get("MP", 0)),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py tests/test_skill_config.py -v`
Expected: 全 PASS（test_skill_config 是既有回归）

- [ ] **Step 5: Commit**

```bash
git add tests/test_use_system.py src/investigator/models.py src/investigator/rules.py src/investigator/serialization.py
git commit -m "fix: MP_MAX 拆分 + recalc 保留 HP/MP/SAN 当前值（统一资源层前置修复）"
```

---

### Task 2: known_spells 字段 + 序列化 v2.1

**Files:**
- Modify: `src/investigator/models.py:190`（__init__ 尾部）
- Modify: `src/investigator/serialization.py:42`（version）、to_dict 尾部、from_dict 尾部
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加到 tests/test_use_system.py）

```python
class TestKnownSpells:
    def test_default_empty_and_roundtrip(self, tmp_path):
        inv = _inv()
        assert inv.known_spells == []
        inv.known_spells = ["HEART_ARREST", "LIFE_DETECTION"]
        from investigator.serialization import to_dict, from_dict
        d = to_dict(inv)
        assert d["meta"]["version"] == "2.1"
        assert d["known_spells"] == ["HEART_ARREST", "LIFE_DETECTION"]
        inv2 = from_dict(d)
        assert inv2.known_spells == ["HEART_ARREST", "LIFE_DETECTION"]

    def test_v20_card_loads_with_empty_spells(self):
        from investigator.serialization import from_dict
        d = {
            "meta": {"version": "2.0"},
            "personal": {"name": "旧卡", "age": 30, "gender": "女"},
            "stats": {"STR": 50, "CON": 50, "DEX": 50, "APP": 50,
                      "INT": 60, "POW": 55, "EDU": 65, "LUCK": 40},
            "derived": {"HP": 16, "HP_MAX": 16, "MP": 11, "SAN": 55, "SAN_MAX": 99,
                        "DB": "0", "BUILD": 0, "DODGE": 25},
            "skills": [], "combat": {"weapons": []},
        }
        inv = from_dict(d)
        assert inv.known_spells == []
        assert inv.derived.MP_MAX == 11, "v2.0 无 MP_MAX 时由 MP 回填"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestKnownSpells -v`
Expected: FAIL（`AttributeError: known_spells`）

- [ ] **Step 3: 实现**

models.py `__init__`（`self.label` 行后）加：

```python
        self.known_spells: list[str] = []   # 已知法术 spell_id 列表（U6 统一资源层）
```

serialization.py to_dict：`"meta"` 的 `"version": "2.0"` 改 `"2.1"`；返回 dict 的 `"avatar_url"` 行后加：

```python
        "known_spells": list(getattr(inv, 'known_spells', [])),
```

from_dict 尾部构造 Investigator 后（返回前）加：

```python
    inv.known_spells = list(data.get("known_spells", []) or [])
```

（如 from_dict 以关键字构造，则在构造后追加赋值；保持其余逻辑不动。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/investigator/models.py src/investigator/serialization.py tests/test_use_system.py
git commit -m "feat: Investigator.known_spells + 序列化 v2.1（v2.0 兼容加载）"
```

---

### Task 3: ItemLibrary / SpellLibrary + 库 JSON

**Files:**
- Create: `data/library/core/items.json`、`data/library/core/spells.json`
- Create: `src/library/items.py`、`src/library/spells.py`
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestLibraries:
    def test_item_library_core_load(self):
        from library.items import ItemLibrary
        lib = ItemLibrary(); lib.load_core()
        assert len(lib) >= 10
        kit = lib.get("急救包")
        assert kit is not None and kit.impact == "L1"
        assert lib.get("FIRST_AID_KIT") is kit, "id 与名称/别名均可查"
        assert "医疗包" in kit.aliases

    def test_spell_library_core_load(self):
        from library.spells import SpellLibrary
        lib = SpellLibrary(); lib.load_core()
        assert len(lib) >= 6
        sp = lib.get("心脏骤停")
        assert sp.category == "combat"
        assert sp.cost.get("mp", 0) > 0
        life = lib.get("LIFE_DETECTION")
        assert life is not None and life.impact == "L0"

    def test_extension_merge(self, tmp_path):
        from library.items import ItemLibrary
        import json as _json
        p = tmp_path / "ext.json"
        p.write_text(_json.dumps({"items": [
            {"id": "EXT_X", "name": "扩展物品", "impact": "L1"}]}, ensure_ascii=False),
            encoding="utf-8")
        lib = ItemLibrary(); lib.load_core(); lib.load_extension(str(p))
        assert lib.get("扩展物品") is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestLibraries -v`
Expected: FAIL（ModuleNotFoundError: library.items）

- [ ] **Step 3: 实现**

创建 `src/library/items.py`：

```python
"""物品库数据类 + 加载器（统一资源层，同武器库模式）."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import os


@dataclass
class LibraryItem:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "misc"            # consumable/tool/document/clothing/key/misc
    description: str = ""
    impact: str = "L1"                # L0/L1/L2 默认档（库预标注）
    use_semantic: str = "none"        # consume/equip/read/tool/none
    stackable: bool = True
    check: Optional[dict] = None      # {"skill": "...", "type": "regular|hard|opposed"}
    on_use: list[str] = field(default_factory=list)   # @markup 序列
    on_success: str = ""
    on_failure: str = ""
    on_hard: str = ""
    on_extreme: str = ""
    refund_on_fail: bool = False
    constraints: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryItem":
        return cls(
            id=str(data.get("id", data.get("name", ""))),
            name=data.get("name", ""),
            aliases=list(data.get("aliases", []) or []),
            category=data.get("category", "misc"),
            description=data.get("description", ""),
            impact=data.get("impact", "L1"),
            use_semantic=data.get("use_semantic", "none"),
            stackable=bool(data.get("stackable", True)),
            check=data.get("check") or None,
            on_use=list(data.get("on_use", []) or []),
            on_success=data.get("on_success", ""),
            on_failure=data.get("on_failure", ""),
            on_hard=data.get("on_hard", ""),
            on_extreme=data.get("on_extreme", ""),
            refund_on_fail=bool(data.get("refund_on_fail", False)),
            constraints=dict(data.get("constraints", {}) or {}),
        )

    def matches(self, ref: str) -> bool:
        return ref in (self.id, self.name) or ref in self.aliases


class ItemLibrary:
    """物品库 -- core + extensions，id/名称/别名三路查询."""

    def __init__(self):
        self._items: dict[str, LibraryItem] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "data", "library", "core", "items.json")
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            li = LibraryItem.from_dict(item)
            self._items[li.id] = li

    def get(self, ref: str) -> Optional[LibraryItem]:
        for it in self._items.values():
            if it.matches(ref):
                return it
        return None

    def list_all(self) -> list[LibraryItem]:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)
```

创建 `src/library/spells.py`：

```python
"""法术库数据类 + 加载器（统一资源层）."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import json
import os


@dataclass
class LibrarySpell:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    category: str = "exploration"     # combat / exploration
    description: str = ""
    impact: str = "L1"
    cost: dict = field(default_factory=lambda: {"mp": 0, "san": 0})
    check: Optional[dict] = None      # {"skill": "POW", "type": "regular|hard|opposed"}
    on_use: list[str] = field(default_factory=list)
    on_success: str = ""
    on_failure: str = ""
    on_hard: str = ""
    on_extreme: str = ""
    refund_on_fail: bool = False
    constraints: dict = field(default_factory=dict)
    effect: dict = field(default_factory=dict)   # 战斗：{"type": "damage", "formula": "1D6", "ignore_armor": false}
    weight: str = "light"

    @classmethod
    def from_dict(cls, data: dict) -> "LibrarySpell":
        return cls(
            id=str(data.get("id", data.get("name", ""))),
            name=data.get("name", ""),
            aliases=list(data.get("aliases", []) or []),
            category=data.get("category", "exploration"),
            description=data.get("description", ""),
            impact=data.get("impact", "L1"),
            cost=dict(data.get("cost", {}) or {"mp": 0, "san": 0}),
            check=data.get("check") or None,
            on_use=list(data.get("on_use", []) or []),
            on_success=data.get("on_success", ""),
            on_failure=data.get("on_failure", ""),
            on_hard=data.get("on_hard", ""),
            on_extreme=data.get("on_extreme", ""),
            refund_on_fail=bool(data.get("refund_on_fail", False)),
            constraints=dict(data.get("constraints", {}) or {}),
            effect=dict(data.get("effect", {}) or {}),
            weight=data.get("weight", "light"),
        )

    def matches(self, ref: str) -> bool:
        return ref in (self.id, self.name) or ref in self.aliases


class SpellLibrary:
    """法术库 -- core + extensions."""

    def __init__(self):
        self._spells: dict[str, LibrarySpell] = {}

    def load_core(self, core_path: str = None) -> None:
        if core_path is None:
            core_path = os.path.join(
                os.path.dirname(__file__), "..", "..",
                "data", "library", "core", "spells.json")
        self._load_file(core_path)

    def load_extension(self, path: str) -> None:
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for sp in data.get("spells", []):
            ls = LibrarySpell.from_dict(sp)
            self._spells[ls.id] = ls

    def get(self, ref: str) -> Optional[LibrarySpell]:
        for sp in self._spells.values():
            if sp.matches(ref):
                return sp
        return None

    def list_all(self) -> list[LibrarySpell]:
        return list(self._spells.values())

    def __len__(self) -> int:
        return len(self._spells)
```

创建 `data/library/core/items.json`：

```json
{
  "items": [
    {"id": "FIRST_AID_KIT", "name": "急救包", "aliases": ["医疗包", "急救箱"],
     "category": "consumable", "impact": "L1", "use_semantic": "consume",
     "description": "帆布挎包，内有止血带、磺胺粉与卷起的绷带，散发着淡淡的药味。",
     "on_use": ["@stat_change(stat_name=\"HP\", delta=1D3)"],
     "on_success": "你咬开绷带的封口，草草地包扎了伤口，疼痛稍减。"},
    {"id": "WHISKEY", "name": "威士忌", "aliases": ["酒", "烈酒"],
     "category": "consumable", "impact": "L1", "use_semantic": "consume",
     "description": "半瓶廉价威士忌，标签已经褪色。",
     "on_use": ["@stat_change(stat_name=\"SAN\", delta=1)"],
     "on_success": "辛辣的液体滚过喉咙，你感到一丝短暂的镇定。"},
    {"id": "FLASHLIGHT", "name": "手电筒", "aliases": ["电筒"],
     "category": "tool", "impact": "L0", "use_semantic": "tool",
     "description": "军用手电筒，光柱稳定，照亮大约十步内的黑暗。"},
    {"id": "MATCHES", "name": "火柴", "aliases": ["火柴盒"],
     "category": "tool", "impact": "L0", "use_semantic": "tool",
     "description": "一盒受潮的木梗火柴，大约还剩十几根。"},
    {"id": "LOCKPICKS", "name": "开锁工具", "aliases": ["撬锁工具", "锁匠工具"],
     "category": "tool", "impact": "L1", "use_semantic": "tool",
     "description": "一卷油布包着的细铁钩与张力扳手。",
     "check": {"skill": "锁匠", "type": "regular"}, "refund_on_fail": true,
     "on_success": "铁钩在锁芯里轻轻一转，锁开了。", "on_failure": "铁钩发出令人牙酸的声响，锁纹丝不动。"},
    {"id": "CROWBAR", "name": "撬棍", "aliases": ["铁撬"],
     "category": "tool", "impact": "L1", "use_semantic": "tool",
     "description": "六十厘米长的钢制撬棍，边缘有旧漆的痕迹。",
     "check": {"skill": "力量", "type": "regular"},
     "on_success": "随着一声闷响，封条被撬开了。", "on_failure": "木板纹丝不动，虎口却被震得发麻。"},
    {"id": "ROPE", "name": "绳索", "aliases": ["绳子", "麻绳"],
     "category": "tool", "impact": "L0", "use_semantic": "tool",
     "description": "十五米粗麻绳，还带着缆绳的焦油味。"},
    {"id": "TELESCOPE", "name": "望远镜", "aliases": [],
     "category": "tool", "impact": "L0", "use_semantic": "tool",
     "description": "黄铜单筒望远镜，镜片边缘有一圈霉斑。"},
    {"id": "NECRONOMICON_PAGE", "name": "《死灵书》残页", "aliases": ["死灵书残页"],
     "category": "document", "impact": "L1", "use_semantic": "read",
     "description": "脆黄的残页上是无法归类的字母，读起来像有东西在纸上爬。",
     "on_use": ["@stat_change(stat_name=\"SAN\", delta=-1D4)"],
     "on_success": "你读完了残页。有些句子现在还黏在你的脑子里，撕不下来。"},
    {"id": "NEWSPAPER", "name": "旧报纸", "aliases": ["报纸"],
     "category": "document", "impact": "L0", "use_semantic": "read",
     "description": "三个月前的晨报，头版是本地失踪案的报道。"},
    {"id": "SALT", "name": "盐袋", "aliases": ["盐"],
     "category": "consumable", "impact": "L1", "use_semantic": "consume",
     "description": "粗海盐装在棉布袋里，民间说它能画出不可跨越的界线。",
     "on_success": "你抖出一圈盐线，白色的颗粒在地面连成弧形。"},
    {"id": "HOLY_SYMBOL", "name": "圣徽", "aliases": ["护身符", "十字架"],
     "category": "key", "impact": "L0", "use_semantic": "equip",
     "description": "黄铜圣徽，被无数只手摩挲得发亮。"}
  ]
}
```

创建 `data/library/core/spells.json`：

```json
{
  "spells": [
    {"id": "HEART_ARREST", "name": "心脏骤停", "aliases": [],
     "category": "combat", "impact": "L1",
     "description": "你凝视目标，以目光攥住它的心脏。",
     "cost": {"mp": 12, "san": 1},
     "check": {"skill": "POW", "type": "opposed"},
     "on_success": "目标的胸膛猛地一缩，仿佛被一只无形的手攥住。",
     "on_failure": "某种冰冷的东西反向攥住了你的心口。",
     "effect": {"type": "damage", "formula": "1D6", "ignore_armor": true},
     "constraints": {"range": "视线内"}},
    {"id": "BLOOD_CALL", "name": "血之呼唤", "aliases": [],
     "category": "combat", "impact": "L1",
     "description": "古老的音节撕开空气，让敌人的血违抗它的主人。",
     "cost": {"mp": 8, "san": 1},
     "check": {"skill": "POW", "type": "regular"},
     "on_success": "敌人的皮肤下浮起暗色的纹路，它踉跄了一步。",
     "on_failure": "音节在舌尖散成了无意义的气音。",
     "effect": {"type": "damage", "formula": "1D4", "ignore_armor": false}},
    {"id": "LIFE_DETECTION", "name": "生命觉察", "aliases": [],
     "category": "exploration", "impact": "L0",
     "description": "闭上眼，让意识像涟漪一样扩散，感知周遭的活物。",
     "cost": {"mp": 3, "san": 0},
     "check": null,
     "on_success": "黑暗里浮现出几团温热的轮廓——两团在楼下，一团在很近的地方。",
     "constraints": {"range": "当前场景"}},
    {"id": "WITCH_LIGHT", "name": "妖火", "aliases": ["巫光"],
     "category": "exploration", "impact": "L0",
     "description": "指尖凝起一簇苍白的冷光，不发热，也不照亮它不该照亮的东西。",
     "cost": {"mp": 2, "san": 0},
     "check": null,
     "on_success": "惨白的光晕在你掌心上方一寸处静静燃烧。"},
    {"id": "DREAM_GAZE", "name": "梦中窥探", "aliases": [],
     "category": "exploration", "impact": "L1",
     "description": "你盯着镜面或水面，让视线沉入另一侧的梦境。",
     "cost": {"mp": 6, "san": 1},
     "check": {"skill": "POW", "type": "hard"},
     "on_success": "镜面泛起涟漪。你看见了这间屋子过去的模样——以及站在角落里的那个影子。",
     "on_failure": "涟漪散去，只剩你自己苍白的倒影。",
     "constraints": {"materials": ["镜子或静止的水"]}},
    {"id": "SILENCE_VEIL", "name": "静默帷幕", "aliases": [],
     "category": "exploration", "impact": "L1",
     "description": "织起一层无形的帷幕，吞掉帷幕内的一切声响。",
     "cost": {"mp": 5, "san": 0},
     "check": {"skill": "POW", "type": "regular"},
     "on_success": "世界忽然安静下来，连你的心跳都像蒙上了棉布。",
     "on_failure": "音节走调，反而让四周安静得更加可疑。"},
    {"id": "STONE_SKIN", "name": "石肤术", "aliases": [],
     "category": "combat", "impact": "L1",
     "description": "你的皮肤泛起大理石般的灰色纹路。",
     "cost": {"mp": 6, "san": 0},
     "check": {"skill": "POW", "type": "regular"},
     "on_success": "皮肤紧绷如石。接下来的打击会轻一些。",
     "on_failure": "纹路浮现又褪去，你依旧血肉之躯。",
     "effect": {"type": "buff", "formula": null}},
    {"id": "DOMINATE", "name": "支配", "aliases": [],
     "category": "combat", "impact": "L1",
     "description": "你的意志越过界线，压向对方的意志。",
     "cost": {"mp": 10, "san": 1},
     "check": {"skill": "POW", "type": "opposed"},
     "on_success": "对方的眼神涣散了一瞬——那一瞬足够了。",
     "on_failure": "对方的眼神反而更清醒了，它认出了你。",
     "constraints": {"range": "视线内", "opposed_value": 60}}
  ]
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestLibraries -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add data/library/core/items.json data/library/core/spells.json src/library/items.py src/library/spells.py tests/test_use_system.py
git commit -m "feat: ItemLibrary/SpellLibrary + 核心库 JSON（统一资源层素材库）"
```

---

### Task 4: @grant_spell 副作用 + ScenarioWorld 库挂载

**Files:**
- Modify: `src/game/side_effects.py`（GrantSpell + pattern + builder）
- Modify: `src/scenario_core.py:663`（ScenarioWorld.__init__ 加 item_library/spell_library）、apply_side_effects（:1215 起）
- Modify: 全库 @markup 枚举同步（grep 定位）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestGrantSpell:
    def _world(self):
        from types import SimpleNamespace
        from scenario_core import DirectedGraph, ScenarioWorld
        from library.spells import SpellLibrary
        import json as _json, tempfile, os
        d = tempfile.mkdtemp()
        p = os.path.join(d, "spells.json")
        p_text = os.path.join(os.path.dirname(__file__), '..', 'data',
                              'library', 'core', 'spells.json')
        lib = SpellLibrary(str(p_text))
        world = ScenarioWorld(DirectedGraph(scenes={}, events=[]),
                              start_node="room", spell_library=lib)
        return world

    def test_grant_spell_known_ref(self):
        from scenario_core import apply_side_effects
        from game.side_effects import GrantSpell
        from investigator import Investigator
        world = self._world()
        inv = Investigator(name="测试")
        world.set_player(inv)
        msgs = apply_side_effects(world, [GrantSpell(spell_ref="HEART_ARREST")])
        assert "HEART_ARREST" in inv.known_spells
        assert any("获得法术" in m for m in msgs)
        apply_side_effects(world, [GrantSpell(spell_ref="HEART_ARREST")])
        assert inv.known_spells.count("HEART_ARREST") == 1, "不重复授予"

    def test_grant_spell_unknown_ref_degrades(self):
        from scenario_core import apply_side_effects
        from game.side_effects import GrantSpell
        from investigator import Investigator
        world = self._world()
        world.set_player(Investigator(name="测试"))
        msgs = apply_side_effects(world, [GrantSpell(spell_ref="不存在的法术")])
        assert any("不存在" in m for m in msgs)

    def test_parse_markup_grant_spell(self):
        from game.side_effects import parse_markup
        eff = parse_markup('@grant_spell(spell_ref="HEART_ARREST")')
        assert eff is not None and eff.spell_ref == "HEART_ARREST"
```

注意：`SpellLibrary(str(p_text))` 直接传路径不合现行构造（无参构造 + load_core）。改为：`lib = SpellLibrary(); lib.load_core(p_text)`。测试代码以该写法为准。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestGrantSpell -v`
Expected: FAIL（GrantSpell 不存在）

- [ ] **Step 3: 实现**

side_effects.py（NPCFollow 类后）加：

```python
@dataclass
class GrantSpell:
    spell_ref: str
    category: str = ""   # 描述性：combat/exploration，空则从库推断
```

`_MARKUP_PATTERN`（:62）改：

```python
_MARKUP_PATTERN = re.compile(
    r'@(spawn_enemy|grant_weapon|grant_spell|stat_change|item_gain|consume_item|npc_state_change|npc_follow)'
    r'\(([^)]*)\)'
)
```

`_build_side_effect`（grant_weapon 分支后）加：

```python
    elif func_name == "grant_spell":
        return GrantSpell(
            spell_ref=kwargs.get("spell_ref", ""),
            category=kwargs.get("category", ""),
        )
```

scenario_core.py `ScenarioWorld.__init__`（:663）签名在 `npc_profiles` 后追加 `item_library=None, spell_library=None`，函数体初始化区（与其他 manager 同区）加：

```python
        self.item_library = item_library      # 统一资源层：物品库（可选，init_game 注入）
        self.spell_library = spell_library    # 统一资源层：法术库
```

apply_side_effects（GrantWeapon 分支之前任意 elif 位）加：

```python
        elif isinstance(effect, GrantSpell):
            lib = getattr(world, "spell_library", None)
            spell = lib.get(effect.spell_ref) if lib else None
            if spell is None:
                msgs.append(f"[获得法术失败] {effect.spell_ref}（法术库中不存在，已跳过）")
            else:
                if world.player and effect.spell_ref not in world.player.known_spells:
                    world.player.known_spells.append(effect.spell_ref)
                msgs.append(f"[获得法术] {spell.name}")
```

@markup 枚举同步（剥除正则与文档列表都要含 grant_spell，否则 enrich 剥不干净）：

Run: `grep -rn "spawn_enemy|grant_weapon" src/ | grep -v "\.pyc"`
对每个命中（已知：`src/prompts.py:548` `_STRIP_MARKUP_RE`、`src/prompts.py:911` Author @markup 列表、judge.py 的 `_MARKUP_STRIP_RE` 定义处）在枚举中 `grant_weapon` 后插入 `|grant_spell`；prompts.py:911 长文本在 `@grant_weapon(...)` 句后追加 ` / @grant_spell(spell_ref="法术库名称或id")`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/game/side_effects.py src/scenario_core.py src/prompts.py src/game/judge.py tests/test_use_system.py
git commit -m "feat: @grant_spell 第8种markup + ScenarioWorld 库挂载 + apply_side_effects 分支"
```

---

### Task 5: UseParser 确定性层 + MaterialCatalog

**Files:**
- Create: `src/game/use_parser.py`
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestUseParserDeterministic:
    def _setup(self):
        from library.items import ItemLibrary
        from library.spells import SpellLibrary
        from game.use_parser import UseParser, ItemCatalog, SpellCatalog
        from investigator import Investigator
        ilib = ItemLibrary(); ilib.load_core()
        slib = SpellLibrary(); slib.load_core()
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=2)
        inv.known_spells = ["LIFE_DETECTION", "HEART_ARREST"]
        up = UseParser()
        cats = [ItemCatalog(ilib, inv.item_manager),
                SpellCatalog(slib, inv.known_spells)]
        return up, cats, inv

    def test_verb_name_exact_hit(self):
        up, cats, inv = self._setup()
        r = up.resolve("我使用急救包处理伤口", cats)
        assert r is not None and r.catalog_kind == "item"
        assert r.material_id == "FIRST_AID_KIT" and r.impact == "L1"

    def test_spell_cast_hit(self):
        up, cats, inv = self._setup()
        r = up.resolve("我闭上眼念诵生命觉察的咒文", cats)
        assert r is not None and r.catalog_kind == "spell"
        assert r.material_id == "LIFE_DETECTION" and r.impact == "L0"

    def test_alias_and_fuzzy(self):
        up, cats, inv = self._setup()
        r = up.resolve("喝一口烈酒壮胆", cats)
        assert r is not None and r.material_id == "WHISKEY"

    def test_negation_rejected(self):
        up, cats, inv = self._setup()
        assert up.resolve("我不用急救包", cats) is None

    def test_unheld_item_not_in_catalog(self):
        up, cats, inv = self._setup()
        r = up.resolve("我使用撬棍撬开门", cats)
        assert r is None, "未持有的库物品不入目录，走 interaction 语义路径"

    def test_no_verb_no_hit(self):
        up, cats, inv = self._setup()
        assert up.resolve("急救包挺好的", cats) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestUseParserDeterministic -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现** 创建 `src/game/use_parser.py`：

```python
"""UseParser -- use 大类的独立小型 parse 系统（统一资源层）。

待解析内容可换：MaterialCatalog 协议注入（ItemCatalog/SpellCatalog/未来素材源）。
确定性层优先（谓词 + 名称匹配），LLM 兜底（resolve_llm）。
输出标准化为 UseParseResult，on_use 编译为 @markup 序列，走 apply_side_effects 执行。
"""
from __future__ import annotations
import difflib
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol


USE_VERBS = ("使用", "服用", "施放", "施展", "念诵", "吟唱", "咏唱", "佩戴", "戴上",
             "翻阅", "涂抹", "喝", "饮", "吃", "敷", "用", "施法", "阅读", "翻开",
             "点燃", "打开")

_NEGATION_RE = re.compile(r"(不|别|无须|无需|没有|没法)")


@dataclass
class UseParseResult:
    catalog_kind: str          # "item" | "spell"（描述性）
    material_id: str
    name: str
    matched_text: str
    impact: str                # L0 / L1 / L2
    check: Optional[dict] = None
    cost: dict = field(default_factory=lambda: {"mp": 0, "san": 0})
    on_use: list[str] = field(default_factory=list)
    result_slots: dict = field(default_factory=dict)
    refund_on_fail: bool = False
    use_semantic: str = "none"
    constraints: dict = field(default_factory=dict)


class MaterialCatalog(Protocol):
    def entries(self) -> list[dict]:
        """返回可解析条目：{id, name, aliases, kind, description, impact, ...}"""
        ...


class ItemCatalog:
    """物品目录：ItemLibrary ∩ 玩家背包（仅持有物可用）。"""

    def __init__(self, item_lib, inventory):
        self._lib = item_lib
        self._inv = inventory

    def entries(self) -> list[dict]:
        out = []
        if not (self._lib and self._inv):
            return out
        for it in self._inv.list_all():
            li = self._lib.get(it.name)
            if li is None:
                continue   # 自由文本物品无库元数据，不进机械使用通路
            out.append({
                "id": li.id, "name": li.name, "aliases": list(li.aliases),
                "kind": "item", "description": li.description, "impact": li.impact,
                "check": li.check, "cost": {"mp": 0, "san": 0},
                "on_use": list(li.on_use),
                "result_slots": {"on_success": li.on_success, "on_failure": li.on_failure,
                                 "on_hard": li.on_hard, "on_extreme": li.on_extreme},
                "refund_on_fail": li.refund_on_fail,
                "use_semantic": li.use_semantic,
                "constraints": dict(li.constraints),
            })
        return out


class SpellCatalog:
    """法术目录：SpellLibrary ∩ known_spells。"""

    def __init__(self, spell_lib, known_spells: list[str]):
        self._lib = spell_lib
        self._known = known_spells

    def entries(self) -> list[dict]:
        out = []
        if not self._lib:
            return out
        for sid in self._known:
            sp = self._lib.get(sid)
            if sp is None:
                continue
            out.append({
                "id": sp.id, "name": sp.name, "aliases": list(sp.aliases),
                "kind": "spell", "description": sp.description, "impact": sp.impact,
                "check": sp.check, "cost": dict(sp.cost),
                "on_use": list(sp.on_use),
                "result_slots": {"on_success": sp.on_success, "on_failure": sp.on_failure,
                                 "on_hard": sp.on_hard, "on_extreme": sp.on_extreme},
                "refund_on_fail": sp.refund_on_fail,
                "use_semantic": "cast",
                "constraints": dict(sp.constraints),
            })
        return out


def _best_material_match(raw: str, entries: list[dict]):
    """精确 -> 包含 -> difflib(>=0.6) 三级匹配，返回 (entry, matched_text) 或 None。"""
    best = None
    best_score = 0.0
    for e in entries:
        candidates = [e["name"]] + list(e.get("aliases", []))
        for cand in candidates:
            if not cand:
                continue
            if cand == raw:
                return e, cand
            if cand in raw:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, cand, raw).ratio()
            if score > best_score:
                best_score = score
                best = (e, cand)
    if best_score >= 0.6:
        return best
    return None


class UseParser:
    def __init__(self, llm_call=None):
        self.llm_call = llm_call   # 可注入（keeper/测试）；None 时 LLM 兜底不可用

    # ── 确定性层 ──
    def resolve(self, raw: str, catalogs: list[MaterialCatalog]) -> Optional[UseParseResult]:
        if not raw or not catalogs:
            return None
        if _NEGATION_RE.search(raw):
            return None
        if not any(v in raw for v in USE_VERBS):
            return None
        entries = [e for c in catalogs for e in c.entries()]
        hit = _best_material_match(raw, entries)
        if hit is None:
            return None
        e, matched = hit
        return UseParseResult(
            catalog_kind=e["kind"], material_id=e["id"], name=e["name"],
            matched_text=matched, impact=e["impact"], check=e.get("check"),
            cost=dict(e.get("cost") or {"mp": 0, "san": 0}),
            on_use=list(e.get("on_use") or []),
            result_slots=dict(e.get("result_slots") or {}),
            refund_on_fail=bool(e.get("refund_on_fail", False)),
            use_semantic=e.get("use_semantic", "none"),
            constraints=dict(e.get("constraints") or {}),
        )

    # ── LLM 兜底层（Task 6 实现）──
    def resolve_llm(self, raw: str, catalogs: list[MaterialCatalog]) -> Optional[UseParseResult]:
        from prompts import build_material_fuzzy_prompt
        if self.llm_call is None:
            return None
        entries = [e for c in catalogs for e in c.entries()]
        if not entries:
            return None
        catalog_text = "\n".join(
            f"- {e['name']}（{'/'.join(e.get('aliases', []))}）：{e['description'][:50]}"
            for e in entries)
        resp = self.llm_call(build_material_fuzzy_prompt(raw, catalog_text),
                             json_mode=True, system="你是 COC 7th KP 助理。")
        if isinstance(resp, str):
            import json as _json
            try:
                resp = _json.loads(resp)
            except Exception:
                return None
        if not (isinstance(resp, dict) and resp.get("matched") and resp.get("material")):
            return None
        for e in entries:
            if resp["material"] in (e["name"], *e.get("aliases", []), e["id"]):
                return self.resolve(f"使用{e['name']}", catalogs)
        return None
```

注意 `resolve_llm` 依赖 `prompts.build_material_fuzzy_prompt`（Task 6 提供）；本任务先实现 `resolve` 与目录类，`resolve_llm` 方法体先写为 `return None`，Task 6 再替换为上述完整实现。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestUseParserDeterministic -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/game/use_parser.py tests/test_use_system.py
git commit -m "feat: UseParser 确定性层 + MaterialCatalog 协议（use 大类独立parse系统）"
```

---

### Task 6: LLM 兜底 + build_material_fuzzy_prompt

**Files:**
- Modify: `src/prompts.py:1018`（build_consume_item_fuzzy_prompt 改为通用版）
- Modify: `src/game/use_parser.py`（resolve_llm 完整实现）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestUseParserLLM:
    def test_resolve_llm_match(self):
        from library.items import ItemLibrary
        from game.use_parser import UseParser, ItemCatalog
        ilib = ItemLibrary(); ilib.load_core()
        from investigator import Investigator
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=1)
        import json as _json
        calls = {}
        def fake_llm(prompt, **kw):
            calls["prompt"] = prompt
            return _json.dumps({"matched": True, "material": "急救包",
                                "reason": "语义相同"}, ensure_ascii=False)
        up = UseParser(llm_call=fake_llm)
        cats = [ItemCatalog(ilib, inv.item_manager)]
        # 原文无动词/名匹配失败场景由 LLM 兜底
        r = up.resolve_llm("把那个能止血的包拿来用", cats)
        assert r is not None and r.material_id == "FIRST_AID_KIT"
        assert "急救包" in calls["prompt"]

    def test_resolve_llm_unmatched(self):
        from library.items import ItemLibrary
        from game.use_parser import UseParser, ItemCatalog
        from investigator import Investigator
        ilib = ItemLibrary(); ilib.load_core()
        inv = Investigator(name="测试")
        inv.item_manager.add("急救包", quantity=1)
        up = UseParser(llm_call=lambda p, **k: {"matched": False, "material": "", "reason": ""})
        assert up.resolve_llm("随便看看", [ItemCatalog(ilib, inv.item_manager)]) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestUseParserLLM -v`
Expected: FAIL（resolve_llm 返回 None / build_material_fuzzy_prompt 不存在）

- [ ] **Step 3: 实现**

prompts.py 将 `build_consume_item_fuzzy_prompt`（:1018）改造为通用版（保留函数名供 scenario_core 兼容，新增通用名）：

```python
def build_material_fuzzy_prompt(target: str, catalog_text: str, quantity: int = 1) -> str:
    prompt = f"""你是 COC 7th KP 助理。玩家输入中提到的物品/法术与可用目录名称不匹配。请判断目录中是否有语义相同的条目。

玩家输入：{target}
{'（需消耗 x%d）' % quantity if quantity and quantity > 1 else ''}
可用目录：
{catalog_text}

请判断目录中是否有条目与玩家所指语义相同，以 JSON 格式输出：
{{"matched": true/false, "material": "目录中的条目名", "reason": "匹配理由"}}

规则：
- 模糊匹配（如"止血的包"匹配"急救包"、"手电"匹配"手电筒"）-> matched=true
- 完全无关或玩家并非要使用某个条目 -> matched=false
- material 必须是目录中存在的条目名（精确复制）"""
    _show_prompt("Material Fuzzy", prompt)
    return prompt


def build_consume_item_fuzzy_prompt(target: str, quantity: int, held_items: str) -> str:
    """兼容包装：旧消耗品模糊匹配（scenario_core 通路）。"""
    return build_material_fuzzy_prompt(f"消耗物品：{target}", held_items, quantity)
```

use_parser.py `resolve_llm` 替换为 Step 3（Task 5）所列完整实现（调用 `self.llm_call(prompt, json_mode=True, system=...)`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/prompts.py src/game/use_parser.py tests/test_use_system.py
git commit -m "feat: UseParser LLM 兜底 + build_material_fuzzy_prompt 通用化"
```

---

### Task 7: opposed_check 对抗检定（rules.py）

**Files:**
- Modify: `src/investigator/rules.py`（文件尾部追加）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestOpposedCheck:
    def test_outcomes_and_message(self):
        import random
        from investigator.rules import opposed_check
        random.seed(7)
        seen = set()
        for _ in range(300):
            outcome, detail = opposed_check(80, 30)
            assert outcome in ("win", "lose", "tie")
            assert "对抗 D100" in detail
            seen.add(outcome)
        assert "win" in seen, "80 vs 30 必然出现 win"

    def test_equal_values_mostly_tie_or_split(self):
        import random
        from investigator.rules import opposed_check
        random.seed(11)
        for _ in range(50):
            outcome, _ = opposed_check(50, 50)
            assert outcome == "tie", "同值同级对抗按平局处理"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestOpposedCheck -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现** rules.py 尾部追加：

```python
# ═══════════════════════════════════════════════════════════════
#  对抗检定（统一资源层：法术/物品 opposed 检定，战斗/探索两侧复用）
# ═══════════════════════════════════════════════════════════════

_TIER_RANK = {"fumble": 0, "failure": 0, "regular": 1, "hard": 2, "extreme": 3}


def _opposed_roll(value: int) -> tuple[int, str]:
    roll = random.randint(1, 100)
    if roll >= 96 and roll > value:
        return roll, "fumble"
    if roll == 1:
        return roll, "extreme"
    if roll <= max(1, value // 5):
        return roll, "extreme"
    if roll <= max(1, value // 2):
        return roll, "hard"
    if roll <= value:
        return roll, "regular"
    return roll, "failure"


def opposed_check(att_value: int, def_value: int) -> tuple[str, str]:
    """对抗检定：成功等级高者胜；同级比技能值；再同（或双败）为 tie。
    返回 (\"win\"|\"lose\"|\"tie\", detail)。"""
    a_roll, a_tier = _opposed_roll(att_value)
    d_roll, d_tier = _opposed_roll(def_value)
    detail = (f"对抗 D100: 攻方 {a_roll}/{att_value}({a_tier}) vs "
              f"守方 {d_roll}/{def_value}({d_tier})")
    if _TIER_RANK[a_tier] != _TIER_RANK[d_tier]:
        return ("win" if _TIER_RANK[a_tier] > _TIER_RANK[d_tier] else "lose"), detail
    if _TIER_RANK[a_tier] == 0:
        return "tie", detail + "（双方均失败）"
    if att_value != def_value:
        return ("win" if att_value > def_value else "lose"), detail + "（同级比技能值）"
    return "tie", detail + "（不分胜负）"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestOpposedCheck -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add src/investigator/rules.py tests/test_use_system.py
git commit -m "feat: opposed_check 对抗检定纯函数（等级>技能值>平局）"
```

---

### Task 8: Judge.execute_material（L1 执行通道）

**Files:**
- Modify: `src/game/judge.py`（Judge 类内追加方法）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加；用 e2e helpers 的 make_world）

```python
class TestExecuteMaterial:
    def _world(self):
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))
        from helpers import make_world, make_scene
        from library.spells import SpellLibrary
        from library.items import ItemLibrary
        from investigator import Investigator
        slib = SpellLibrary(); slib.load_core()
        ilib = ItemLibrary(); ilib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a",
                           item_library=ilib, spell_library=slib)
        inv = Investigator(name="测试")
        from investigator.rules import calc_derived
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 20
        world.set_player(inv)
        return world, inv

    def test_l0_spell_no_cost_no_check(self):
        from game.judge import Judge
        from game.use_parser import UseParser, SpellCatalog
        world, inv = self._world()
        inv.known_spells = ["LIFE_DETECTION"]
        judge = Judge(world)
        up = UseParser()
        m = up.resolve("念诵生命觉察", [SpellCatalog(world.spell_library, inv.known_spells)])
        out = judge.execute_material(m, "念诵生命觉察")
        assert out.success and out.entity_type == "material"
        assert inv.derived.MP == 17, "L0 感知法术也要扣 MP cost"
        assert "轮廓" in out.message

    def test_l1_item_consume_heals(self):
        from game.judge import Judge
        from game.use_parser import UseParser, ItemCatalog
        world, inv = self._world()
        inv.item_manager.add("急救包", quantity=2)
        inv.derived.HP = 5
        judge = Judge(world)
        m = UseParser().resolve("使用急救包", [ItemCatalog(world.item_library, inv.item_manager)])
        out = judge.execute_material(m, "使用急救包")
        assert out.success
        assert inv.item_manager.get("急救包").quantity == 1
        assert inv.derived.HP > 5, "@stat_change HP 恢复生效"

    def test_mp_insufficient_rejected(self):
        from game.judge import Judge
        from game.use_parser import UseParser, SpellCatalog
        world, inv = self._world()
        inv.known_spells = ["HEART_ARREST"]
        inv.derived.MP = 3
        judge = Judge(world)
        m = UseParser().resolve("施放心脏骤停", [SpellCatalog(world.spell_library, inv.known_spells)])
        out = judge.execute_material(m, "施放心脏骤停")
        assert not out.success and "MP不足" in out.message
        assert inv.derived.MP == 3 and inv.derived.SAN == inv.derived.SAN

    def test_unknown_spell_rejected(self):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = self._world()
        judge = Judge(world)
        m = UseParseResult(catalog_kind="spell", material_id="HEART_ARREST",
                           name="心脏骤停", matched_text="心脏骤停", impact="L1")
        out = judge.execute_material(m, "施法")
        assert not out.success and "尚未习得" in out.message

    def test_check_failure_uses_slot_and_refund(self):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = self._world()
        inv.item_manager.add("开锁工具", quantity=1)
        judge = Judge(world)
        m = UseParseResult(
            catalog_kind="item", material_id="LOCKPICKS", name="开锁工具",
            matched_text="开锁工具", impact="L1",
            check={"skill": "锁匠", "type": "regular"},
            cost={"mp": 0, "san": 0},
            result_slots={"on_success": "锁开了。", "on_failure": "锁纹丝不动。"},
            refund_on_fail=True, use_semantic="tool")
        inv.check_skill = lambda s, d="regular": (False, "锁匠检定：D100=98/10 失败", "failure")
        out = judge.execute_material(m, "开锁")
        assert not out.success and "纹丝不动" in out.message
        assert inv.item_manager.has("开锁工具"), "tool 语义失败不消耗，refund 兜底"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestExecuteMaterial -v`
Expected: FAIL（make_world 无 item_library 参数 / execute_material 不存在）

先给 `tests/e2e/helpers.py` make_world 加透传（:26-37）：

```python
def make_world(scenes, start_node, npc_profiles=None, enemy_library=None,
               weapon_library=None, boss_library=None, boss_encounters=None,
               item_library=None, spell_library=None):
    from scenario_core import DirectedGraph, ScenarioWorld
    return ScenarioWorld(
        DirectedGraph(scenes=scenes, events=[]),
        start_node=start_node,
        npc_profiles=npc_profiles,
        enemy_library=enemy_library,
        weapon_library=weapon_library,
        boss_library=boss_library,
        boss_encounters=boss_encounters,
        item_library=item_library,
        spell_library=spell_library,
    )
```

- [ ] **Step 3: 实现** judge.py Judge 类内（execute_interaction 之后）追加：

```python
    def execute_material(self, material, player_input: str = "") -> ActionOutcome:
        """L1 执行通道：use 动作确定性结算。
        硬门（已知/持有/MP/材料）-> 扣减（refund_on_fail 回滚）-> 可选检定
        -> 结果槽 -> on_use @markup 副作用。L0 无消耗无检定时纯叙事。"""
        player = self.world.player
        intent = ActionIntent(action="use", target=material.name)

        def _fail(msg: str) -> ActionOutcome:
            return ActionOutcome(intent=intent, success=False, message=msg,
                                 entity_id=material.material_id,
                                 entity_type="material")

        if player is None:
            return _fail("（无调查员，无法使用素材。）")
        if material.catalog_kind == "spell" and material.material_id not in player.known_spells:
            return _fail(f"你尚未习得「{material.name}」。")

        cost = material.cost or {}
        need_mp = int(cost.get("mp", 0) or 0)
        need_san = int(cost.get("san", 0) or 0)
        if need_mp and player.derived.MP < need_mp:
            return _fail(f"MP不足：需要 {need_mp}，当前 {player.derived.MP}。")
        for mat in (material.constraints or {}).get("materials", []):
            if not player.item_manager.has(mat):
                return _fail(f"缺少材料：{mat}。")

        # L0 且零消耗无检定：纯叙事
        if (material.impact == "L0" and not need_mp and not need_san
                and not material.check and not material.on_use):
            text = (material.result_slots or {}).get("on_success") or material.description
            return ActionOutcome(intent=intent, success=True, message=text,
                                 entity_id=material.material_id,
                                 entity_type="material")

        # 扣减（原子）
        if need_mp:
            player.derived.MP -= need_mp
        if need_san:
            player.derived.SAN = max(0, player.derived.SAN - need_san)
        consumed_item = None
        if (material.catalog_kind == "item"
                and material.use_semantic == "consume"):
            if not player.item_manager.has(material.name):
                if need_mp:
                    player.derived.MP += need_mp
                return _fail(f"你没有「{material.name}」。")
            player.item_manager.remove(material.name, 1)
            consumed_item = material.name

        # 可选检定（检定能力下沉：复用 check_skill 全套）
        skill_tier = ""
        skill_detail = ""
        success = True
        if material.check:
            cskill = material.check.get("skill", "")
            ctype = material.check.get("type", "regular")
            if ctype == "opposed":
                from investigator.rules import opposed_check
                def_val = int((material.constraints or {}).get("opposed_value", 50))
                att_val = player.get_skill_value(cskill) or getattr(
                    player.stats, cskill, 50)
                outcome, detail = opposed_check(att_val, def_val)
                skill_detail = f"[use] {material.name} | 对抗 {cskill}={att_val} vs {def_val} | {detail}"
                success = outcome == "win"
                skill_tier = "regular" if success else "failure"
            else:
                ok, msg, skill_tier = player.check_skill(
                    cskill, "hard" if ctype == "hard" else "regular")
                skill_detail = f"[use] {material.name} | {cskill} | {msg}"
                success = ok
            log_skill_result(skill_detail)

        if not success and material.refund_on_fail:
            if need_mp:
                player.derived.MP += need_mp
            if need_san:
                player.derived.SAN += need_san
            if consumed_item:
                player.item_manager.add(consumed_item, quantity=1)

        # 结果槽（tier 选用）
        slots = material.result_slots or {}
        if success:
            text = ((slots.get("on_extreme") if skill_tier == "extreme" else "")
                    or (slots.get("on_hard") if skill_tier == "hard" else "")
                    or slots.get("on_success")
                    or f"你使用了{material.name}。")
        else:
            text = slots.get("on_failure") or f"{material.name}没有产生效果。"

        # on_use @markup -> 统一副作用底座
        side_effects = parse_markup_all(" ".join(material.on_use)) if material.on_use else []
        side_msgs = []
        if side_effects:
            from scenario_core import apply_side_effects
            side_msgs = apply_side_effects(self.world, side_effects)

        message = text + ("".join(f"\n{m}" for m in side_msgs))
        return ActionOutcome(
            intent=intent, success=success, message=message,
            entity_id=material.material_id, entity_type="material",
            side_effects=side_effects, skill_tier=skill_tier,
            skill_detail=skill_detail,
        )
```

注意：judge.py 若未导入 `log_skill_result`/`parse_markup_all`，检查文件头部既有 import（`_execute_entity` 已使用二者，直接复用）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestExecuteMaterial -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/game/judge.py tests/e2e/helpers.py tests/test_use_system.py
git commit -m "feat: Judge.execute_material L1 执行通道（硬门/扣减/检定下沉/结果槽/on_use副作用）"
```

---

### Task 9: keeper 接入（pre-parse 短路 + use 类型 + 门控 flavor 豁免）

**Files:**
- Modify: `src/game/agents/keeper.py:99`（__init__）、:155-160（短路区）、:189-229（pre-parse 区）、:283-300（门控）、Step 2 judge 循环 use 分支
- Modify: `src/prompts.py:465-542`（parse prompt 类型表 + system prompt）
- Modify: `docs/superpowers/specs/2026-08-18-unified-resource-impact-design.md`（§1.2 细化为"实质性动作"规则，见 Step 3 末）
- Test: `tests/e2e/test_deterministic.py`

- [ ] **Step 1: 写失败测试**（追加到 tests/e2e/test_deterministic.py）

```python
class TestUseTurnFlow:
    def _setup(self, monkeypatch):
        from game.agents.keeper import Keeper
        from library.items import ItemLibrary
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.rules import calc_derived
        ilib = ItemLibrary(); ilib.load_core()
        slib = SpellLibrary(); slib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a",
                           item_library=ilib, spell_library=slib)
        inv = Investigator(name="测试员")
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 20
        world.set_player(inv)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        return world, inv, keeper, game

    def test_preparse_shortcut_item_use(self, monkeypatch):
        from game_loop import run_turn
        world, inv, keeper, game = self._setup(monkeypatch)
        inv.item_manager.add("急救包", quantity=1)
        inv.derived.HP = 3
        r = run_turn(game, "我使用急救包")
        assert_player_turn_contract(r)
        assert not world.item_manager.get("急救包") or \
            world.item_manager.get("急救包").quantity == 0
        assert inv.derived.HP > 3
        assert r.status.name == "COMPLETED"

    def test_parse_use_entry_routes_to_material(self, monkeypatch):
        """pre-parse 确定性未命中（无动词直配），parse 返回 use 类型 -> LLM 兜底仍可解析。"""
        from game_loop import run_turn
        from game.use_parser import UseParseResult
        world, inv, keeper, game = self._setup(monkeypatch)
        inv.item_manager.add("急救包", quantity=1)
        keeper._parse = lambda raw: [{"type": "use", "text": raw}]
        def fake_llm(prompt, **kw):
            import json as _json
            return _json.dumps({"matched": True, "material": "急救包", "reason": ""},
                               ensure_ascii=False)
        keeper.use_parser.llm_call = fake_llm
        r = run_turn(game, "急救的那个包，快用")
        assert_player_turn_contract(r)
        assert inv.derived.HP == inv.derived.HP  # 无 check 无伤害，仅通路可达
        assert any(getattr(o.intent, "action", "") == "use"
                   for o in r.brief.action_outcomes), "use 动作必须产出 outcome"

    def test_unresolved_use_becomes_creative(self, monkeypatch):
        from game_loop import run_turn
        world, inv, keeper, game = self._setup(monkeypatch)
        keeper._parse = lambda raw: [{"type": "use", "text": "用不知名的古怪装置"}]
        keeper.use_parser.llm_call = lambda p, **k: {"matched": False, "material": "", "reason": ""}

        class _FakeAuthor:
            time_pressure = None
            calls = 0
            def handle_request(self, request, turn_number=0):
                _FakeAuthor.calls += 1
                from game.messages import ModulePatch
                return ModulePatch(entities=[], scene_descriptions=[], justification="x")

        game["author"] = _FakeAuthor()
        from helpers import StubNarrator
        game["narrator"] = StubNarrator()
        r = run_turn(game, "用不知名的古怪装置")
        assert_player_turn_contract(r)
        assert _FakeAuthor.calls == 1, "未命中素材的 use 应转 creative 升 Author"


class TestGateFlavorExemption:
    """门控 flavor 豁免：氛围 AT 捎带不挡 creative；实质性动作仍硬挡。"""

    def _world_with_at(self):
        at = {
            "id": "AT_AMBIENT", "entity_type": "auto_trigger", "type": "无",
            "name": "灯泡闪烁", "requirement": "", "trigger": "进入房间",
            "result": "灯泡滋滋作响。", "side_effects": [],
            "graded_result": None, "difficulty": "None",
            "scene": "room_a", "time_condition": [],
        }
        return make_world({"room_a": make_scene(auto_triggers=[at])}, "room_a")

    def test_at_plus_creative_still_escalates(self, monkeypatch):
        from game.agents.keeper import Keeper

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        for cls in (TestGateFlavorExemption,):
            pass
        world = self._world_with_at()
        _p = _player(world)
        keeper = Keeper(world)
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "auto_trigger", "id": "AT_AMBIENT"},
                                        {"type": "other", "impact": "creative",
                                         "text": "在墙上刻字求救"}]])
        class _FakeAuthor:
            time_pressure = None
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "在墙上刻字求救")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 1, "AT 捎带 + creative：实质性动作缺席，detector 必须启动（escalation C/E 修复）"

    def test_interaction_plus_creative_suppressed(self, monkeypatch):
        from game.agents.keeper import Keeper
        inter = {
            "id": "IT_KEY", "entity_type": "interaction", "name": "翻砖",
            "scene": "room_a", "type": "None", "requirement": "",
            "trigger": "翻开松砖", "result": "找到钥匙。",
            "side_effects": [], "difficulty": "None", "time_condition": [],
        }
        world = make_world({"room_a": make_scene(interactions=[inter])}, "room_a")
        _p = _player(world)
        keeper = Keeper(world)

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_KEY"},
                                        {"type": "other", "impact": "creative",
                                         "text": "顺便大喊救命"}]])
        class _FakeAuthor:
            time_pressure = None
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "翻砖，顺便大喊救命")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 0, "实质性实体 + creative：维持硬挡（防递归丢帧）"

    def test_flavor_never_triggers_detector(self, monkeypatch):
        from game.agents.keeper import Keeper
        world = self._world_with_at()
        _p = _player(world)
        keeper = Keeper(world)

        class _FakeDetector:
            called = 0
            def detect(self, text, snapshot):
                _FakeDetector.called += 1
                class R:
                    needs_author = False; intent = ""; reasoning = ""
                return R()
        keeper.intent_detector = _FakeDetector()
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "other", "impact": "flavor",
                                         "text": "哼着歌"}]])
        class _FakeAuthor:
            time_pressure = None
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": _FakeAuthor()}
        from game_loop import run_turn
        r = run_turn(game, "哼着歌走两步")
        assert_player_turn_contract(r)
        assert _FakeDetector.called == 0, "flavor 永不触发 detector"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestUseTurnFlow tests/e2e/test_deterministic.py::TestGateFlavorExemption -v`
Expected: FAIL（use 分支/门控未实现）

- [ ] **Step 3: 实现**

keeper.py `__init__`（TurnMonitor 初始化后）加：

```python
        from game.use_parser import UseParser
        self.use_parser = UseParser()
```

`_material_catalogs` 方法（与 `_build_world_brief` 同区）：

```python
    def _material_catalogs(self):
        from game.use_parser import ItemCatalog, SpellCatalog
        cats = []
        p = self.world.player
        if p is not None:
            if getattr(self.world, "item_library", None):
                cats.append(ItemCatalog(self.world.item_library, p.item_manager))
            if getattr(self.world, "spell_library", None) and getattr(p, "known_spells", None):
                cats.append(SpellCatalog(self.world.spell_library, p.known_spells))
        return cats
```

pre-parse 短路区（:155 直接拾取块后、`if _depth >= MAX_ESCALATION_DEPTH:` 前）加：

```python
        # UseParser 确定性短路（统一资源层）：使用谓词+素材名命中 -> use 动作，跳过 LLM parse
        use_hit = None
        if self.use_parser:
            use_hit = self.use_parser.resolve(raw, self._material_catalogs())
        if use_hit:
            parse_result = [{"type": "use", "material": use_hit}]
```

注意：现有结构中 `parse_result` 在 `if at == "move"/elif at == "search"/else:` 三分支内赋值。改造为：在 `# ── Pre-parse shortcut` 处先判 `use_hit`，命中则设 `parse_result` 并跳过三分支（用 `if use_hit: ... elif at == "move": ... elif at == "search": ... else: ...` 的链式结构，pre_parse/LLM parse 只在 else 分支执行）。

use 条目归一 + 门控（:283-300 替换）：

```python
        # use 条目归一：LLM 粗识别但确定性层未命中 -> LLM 兜底；仍未命中转 other/creative
        _normalized = []
        for e in parse_result:
            if e.get("type") == "use" and not e.get("material"):
                _m = (self.use_parser.resolve_llm(raw, self._material_catalogs())
                      if self.use_parser else None)
                if _m is not None:
                    _normalized.append({"type": "use", "material": _m})
                else:
                    _normalized.append({"type": "other", "impact": "creative",
                                        "text": e.get("text") or raw})
            else:
                _normalized.append(e)
        parse_result = _normalized

        # Launch IntentDetector early if there are creative "other" entries.
        # 门控（flavor 豁免，2026-08-18 spec §1.2 细化）：
        # - other/impact=flavor：永不触发 detector（氛围动作 enrich 消化）
        # - other/impact=creative：仅当帧内无【实质性动作】时升级--
        #   实质性 = interaction/event/move/search/use/NPC 对话（防递归丢帧，硬挡保留）；
        #   仅氛围 auto_trigger 捎带（如 AT_AMBIENT）不算实质覆盖（escalation C/E 修复）
        other_entries = [e for e in parse_result if e.get("type") == "other"]
        other_creative = [e for e in other_entries if e.get("impact") != "flavor"]
        _SUBSTANTIVE_TYPES = ("interaction", "event", "move", "search", "use")
        has_substantive = bool(npc_interact_entries) or any(
            e.get("type") in _SUBSTANTIVE_TYPES for e in parse_result)
        detect_future = None
        executor = None
        if other_creative and author and not has_substantive:
            other_text = "; ".join(e.get("text", "") for e in other_creative)
            world_snapshot = self._build_world_snapshot()
            executor = ThreadPoolExecutor(max_workers=1)
            detect_future = executor.submit(
                self.intent_detector.detect, other_text, world_snapshot
            )
```

（原 `has_covered`/`_COVERED_TYPES` 逻辑整体被上文替换；后续代码若引用 `other_entries` 做 enrich 注入，保持引用不变即可。）

Step 2 judge 循环（:302 起，`elif entry_type == "move":` 之前）加 use 分支：

```python
            elif entry_type == "use":
                material = entry.get("material")
                if material is not None:
                    all_outcomes.append(self.judge.execute_material(material, raw))
```

（归一化后 use 必带 material，else 情况已转 other/creative，不会到达此处。）

prompts.py `build_keeper_parse_prompt`（:528-539）JSON 示例改为：

```
返回 JSON（直接输出，不要额外文字）：
{{
  "actions": [
    {{"type": "auto_trigger", "id": "AT1"}},
    {{"type": "interaction", "id": "I3"}},
    {{"type": "event", "id": "E22"}},
    {{"type": "npc_interact", "npc_name": "京山 人吉"}},
    {{"type": "move", "target": "7号车厢"}},
    {{"type": "search"}},
    {{"type": "use", "text": "使用背包里的急救包"}},
    {{"type": "other", "text": "唱了一首歌", "impact": "flavor"}},
    {{"type": "other", "text": "用刀在墙上刻字", "impact": "creative"}}
  ]
}}
```

同函数 `_show_prompt(...)` 的 system 字符串，在「行为优先级」段落替换为：

```
行为优先级：
- 有明确对应实体时优先返回实体
- 玩家使用/服用/施放/念诵背包物品或已知法术时返回 use，text 填原文（不要自己猜物品名）
- 玩家行为泛指搜索整个场景时返回 search，想要移动到另一场景时返回 move
- 当玩家明显是要和当前场景中存在的 NPC 对话/互动/询问时返回 npc_interact，npc_name 填 NPC 名称
- 其他情况下返回 other：纯氛围/感慨/感知描述（唱歌、观察、自言自语）用 impact="flavor"；尝试新行为、改变环境、创造性地使用周围事物用 impact="creative"
- 与玩家行为无关的氛围 auto_trigger 不要捎带
- 一般一个动作只匹配一个结果，特殊情况下允许多个。玩家一轮输入可能不只有一个动作
- auto_trigger 必须在 actions 列表最前面
```

spec §1.2 补充（编辑 spec 文档，加在门控调整小节末尾）：

```markdown
**细化（2026-08-18 plan 定稿）**："实体分两档"——实质性动作（interaction/event/move/search/use/NPC 对话）在场时 creative 仍硬挡（防递归丢帧）；仅氛围 auto_trigger 捎带（如 AT_AMBIENT）不算实质覆盖，creative 照常升级（escalation C/E 修复点）。flavor 永不触发 IntentDetector。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/e2e/test_deterministic.py -v`
Expected: 全 PASS（含既有 TestEscalationGate--若其 mock 结构与新门控冲突，按新语义更新该测试的断言，不改测试意图）

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py src/prompts.py docs/superpowers/specs/2026-08-18-unified-resource-impact-design.md tests/e2e/test_deterministic.py
git commit -m "feat: keeper 接入统一资源层--UseParser 短路/use类型/门控flavor豁免(实质动作硬挡保留)"
```

---

### Task 10: requirement `item:` 条件

**Files:**
- Modify: `src/game/judge.py:334`（_evaluate_requirement 开头）
- Test: `tests/e2e/test_deterministic.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestRequirementItem:
    def _world(self):
        inter = {
            "id": "IT_DOOR", "entity_type": "interaction", "name": "开锁",
            "scene": "room_a", "type": "None",
            "requirement": "item:黄铜钥匙", "trigger": "用钥匙开门",
            "result": "门开了。", "side_effects": [],
            "difficulty": "None", "time_condition": [],
        }
        return make_world({"room_a": make_scene(interactions=[inter])}, "room_a")

    def test_item_gate_blocks_and_allows(self, monkeypatch):
        from game.agents.keeper import Keeper
        from game_loop import run_turn
        world = self._world()
        inv = _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_DOOR"}]])
        game = make_game(keeper)

        r1 = run_turn(game, "用钥匙开门")     # 无钥匙
        assert_player_turn_contract(r1)
        assert not world.is_entity_completed("IT_DOOR")
        assert any("黄铜钥匙" in (o.message or "") for o in r1.brief.action_outcomes)

        inv.item_manager.add("黄铜钥匙", quantity=1)
        r2 = run_turn(game, "用钥匙开门")     # 有钥匙
        assert_player_turn_contract(r2)
        assert world.is_entity_completed("IT_DOOR")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestRequirementItem -v`
Expected: FAIL（item: 条件被当作普通实体 ID，静默通过或报错）

- [ ] **Step 3: 实现** judge.py `_evaluate_requirement` 函数体最前面插入：

```python
        # 统一资源层：item:物品名 硬条件（持有检查）先行短路
        import re as _re
        _item_toks = _re.findall(r"item[:：]([^&|（）()\s]+)", req or "")
        if _item_toks:
            p = self.world.player
            for tok in _item_toks:
                tok = tok.strip()
                if not (p and p.item_manager.has(tok)):
                    return False, f"需要物品：{tok}"
            req = _re.sub(r"item[:：][^&|（）()\s]+", "", req).strip(" &|ANDORandor")
            if not req:
                return True, ""
```

（其余逻辑不动；`req` 清洗后为空则直接通过。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/e2e/test_deterministic.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/game/judge.py tests/e2e/test_deterministic.py
git commit -m "feat: requirement 支持 item:物品名 硬条件（统一资源层条件槽）"
```

---

### Task 11: 战斗 cast_spell

**Files:**
- Modify: `src/game/combat.py:166`（__init__）、`:741-779`（_get_player_actions）、`:792`（_resolve_player_action cast 分支）
- Modify: `src/game_loop.py:779`、`run_game.py:361`、`frontend/routers/game.py:929,975`（CombatSystem 构造传 spell_lib）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestCombatCast:
    def _combat(self):
        from game.combat import CombatSystem
        from library.spells import SpellLibrary
        from investigator import Investigator
        from investigator.rules import calc_derived
        slib = SpellLibrary(); slib.load_core()
        cs = CombatSystem(spell_lib=slib)
        inv = Investigator(name="法师")
        inv.derived = calc_derived(inv.stats)
        inv.derived.MP = 30
        inv.known_spells = ["HEART_ARREST", "LIFE_DETECTION"]
        return cs, slib, inv

    def test_actions_include_known_combat_spells_only(self):
        cs, slib, inv = self._combat()
        acts = cs._get_player_actions(inv)
        ids = [a["id"] for a in acts]
        assert "cast_HEART_ARREST" in ids
        assert "cast_LIFE_DETECTION" not in ids, "exploration 类不进战斗动作"

    def test_cast_without_known_spell_fails(self):
        import random
        random.seed(3)
        from game.combat import CombatState, CombatAction
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        inv.known_spells = []
        state = SimpleNamespace(enemies=[], _player_dodging=False)
        act = cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "")
        assert not act.success and "尚未习得" in act.narrative

    def test_cast_deducts_mp(self):
        import random
        random.seed(5)
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        enemy = SimpleNamespace(instance_id="E1", enemy_ref="深潜者", hp=10,
                                status="hostile", attributes={"POW": 30}, armor="")
        state = SimpleNamespace(enemies=[enemy], _player_dodging=False)
        before = inv.derived.MP
        cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "E1")
        assert inv.derived.MP == before - 12, "施法必须扣 MP（12）"

    def test_mp_insufficient_fails_without_deduction(self):
        from types import SimpleNamespace
        cs, slib, inv = self._combat()
        inv.derived.MP = 3
        state = SimpleNamespace(enemies=[], _player_dodging=False)
        act = cs._resolve_player_action(state, inv, "cast_HEART_ARREST", "")
        assert not act.success and "MP不足" in act.narrative
        assert inv.derived.MP == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestCombatCast -v`
Expected: FAIL（CombatSystem 无 spell_lib 参数）

- [ ] **Step 3: 实现**

combat.py `__init__`（:166）签名加 `spell_lib=None`，函数体存 `self.spell_lib = spell_lib`。

`_get_player_actions`（weapon 循环后、environment 循环前）加：

```python
        # 施法动作（统一资源层：known_spells ∩ combat 类）
        spell_lib = getattr(self, "spell_lib", None)
        for sid in getattr(player, "known_spells", []):
            sp = spell_lib.get(sid) if spell_lib else None
            if sp is None or sp.category != "combat":
                continue
            skill_name = (sp.check or {}).get("skill", "POW")
            actions.append({
                "id": f"cast_{sid}", "label": f"施法:{sp.name}",
                "skill": skill_name,
                "value": self._skill_value(player, skill_name),
                "damage": None,
            })
```

`_resolve_player_action`（dodge 分支之前）加：

```python
        if action_id.startswith("cast_"):
            from investigator.rules import opposed_check
            spell = (self.spell_lib.get(action_id[5:])
                     if getattr(self, "spell_lib", None) else None)
            action.action_type = "cast_spell"
            if spell is None or action_id[5:] not in getattr(player, "known_spells", []):
                action.success = False
                action.narrative = "你尚未习得该法术，施法失败。"
                return action
            cost = spell.cost or {}
            need_mp = int(cost.get("mp", 0) or 0)
            need_san = int(cost.get("san", 0) or 0)
            if player.derived.MP < need_mp:
                action.success = False
                action.narrative = f"MP不足（需 {need_mp}，有 {player.derived.MP}），施法失败。"
                return action
            player.derived.MP -= need_mp
            if need_san:
                player.derived.SAN = max(0, player.derived.SAN - need_san)

            target = None
            for e in state.enemies:
                if getattr(e, "instance_id", None) == target_iid and e.status != "dead":
                    target = e
                    break

            check = spell.check or {"skill": "POW", "type": "regular"}
            action.skill_name = check.get("skill", "POW")
            action.skill_value = self._skill_value(player, action.skill_name)
            if check.get("type") == "opposed" and target is not None:
                def_val = (getattr(target, "attributes", None) or {}).get("POW", 50)
                outcome, detail = opposed_check(action.skill_value or 50, def_val)
                action.success = outcome == "win"
                action.tier = "regular" if action.success else "failure"
                action.narrative = f"{spell.name}！{detail}"
            else:
                action.roll = random.randint(1, 100)
                action.success = action.roll <= (action.skill_value or 50)
                action.tier = (self._get_tier(action.roll, action.skill_value)
                               if action.success else "failure")
                action.narrative = f"{spell.name}！D100={action.roll}/{action.skill_value}"

            effect = spell.effect or {}
            if action.success and effect.get("type") == "damage":
                dmg = _roll_damage(effect.get("formula", "1D6"),
                                   player.stats.STR, player.stats.CON)
                if not effect.get("ignore_armor") and target is not None:
                    dmg = _apply_armor(dmg, getattr(target, "armor", "") or "")
                action.damage = dmg
                action.narrative += f" 造成 {dmg} 点伤害。"
                if target is not None:
                    target.hp = max(0, target.hp - dmg)
                    if target.hp <= 0:
                        target.status = "dead"
            return action
```

调用点改造（grep `CombatSystem(` 确认共 4 处生产代码）：

- `src/game_loop.py:779`、`run_game.py:361`、`frontend/routers/game.py:929`、`frontend/routers/game.py:975` 均改为：

```python
        cs = CombatSystem(spell_lib=getattr(world, "spell_library", None))
```

（run_game 中 world 变量名以现场为准：`game["keeper"].world`；frontend 同理取 keeper.world；保持原有其它实参不变，仅追加 spell_lib。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestCombatCast tests/test_combat_smoke.py tests/test_combat_smoke_interactive.py -v`
Expected: 全 PASS（战斗既有回归不破）

- [ ] **Step 5: Commit**

```bash
git add src/game/combat.py src/game_loop.py run_game.py frontend/routers/game.py tests/test_use_system.py
git commit -m "feat: 战斗 cast_spell 动作（known_spells∩combat + MP 扣减 + opposed/伤害）"
```

---

### Task 12: 模组管线感知

**Files:**
- Modify: `src/module_designer/layered_parser.py:260`（build_step1a_prompt）、`:279`（parse_step1a）、`:1355`（STEP4_SYSTEM）、约束 prompt（:532 附近）
- Modify: `src/module_designer/layered_pipeline.py:97`（cross_validate_layers）
- Modify: `run_pipeline.py`（库加载与传参，:1160/:1237 附近）
- Test: `tests/test_use_system.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestPipelineAwareness:
    def test_cross_validate_flags_unknown_spell_ref(self, tmp_path):
        import json as _json
        from module_designer.layered_pipeline import cross_validate_layers
        from library.spells import SpellLibrary
        slib = SpellLibrary(); slib.load_core()
        l1 = {"scenes": {}}
        l2 = {"scenes": {"s1": {"interactions": [{
            "id": "I1", "entity_type": "interaction", "name": "读书",
            "type": "None", "requirement": "", "trigger": "读书",
            "result": "你学会了咒文。", "scene": "s1",
            "side_effects": ['@grant_spell(spell_ref="不存在的法术")'],
            "difficulty": "None"}], "auto_triggers": []}}, "events": []}
        l3 = {"module_meta": {}}
        report = cross_validate_layers(l1, l2, l3, None, None,
                                       spell_lib=slib)
        joined = " ".join(str(i) for i in report.issues)
        assert "不存在的法术" in joined, "未知 spell_ref 必须进交叉校验报告"

    def test_step1a_prompt_contains_libraries(self):
        from module_designer.layered_parser import build_step1a_prompt
        p = build_step1a_prompt("模组内容", ["小刀"], ["深潜者"], [],
                                item_names=["急救包（consumable）：止血"],
                                spell_names=["HEART_ARREST 心脏骤停（combat）：攥心"])
        assert "急救包" in p and "HEART_ARREST" in p
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_use_system.py::TestPipelineAwareness -v`
Expected: FAIL（cross_validate_layers 无 spell_lib 参数）

- [ ] **Step 3: 实现**

layered_parser.py `build_step1a_prompt`（:260）签名追加 `item_names: list[str] = None, spell_names: list[str] = None`；prompt 模板中武器/敌人库摘要块之后追加（无则跳过整块）：

```python
{f"""## 可用物品库（item_gain / requirement 的 item: 可引用）
{chr(10).join(f"- {n}" for n in item_names)}

## 可用法术库（@grant_spell 的 spell_ref 可引用 id 或名称）
{chr(10).join(f"- {n}" for n in spell_names)}""" if (item_names or spell_names) else ""}
```

（以现场 f-string 风格融入；要点：两段清单文本出现在 prompt 中。）

`parse_step1a`（:279）签名追加同名参数并透传给 `build_step1a_prompt`。

STEP4_SYSTEM（:1355）与 Phase1 约束 prompt（:532 附近）的 @标记 文档行，在 `@grant_weapon(...)` 示例行后各追加一行：

```
@grant_spell(spell_ref="法术库id或名称") -- 授予玩家法术（加入 known_spells）
```

layered_pipeline.py `cross_validate_layers`（:97）签名追加 `spell_lib=None, item_lib=None`；函数内（参照现有 GrantWeapon/武器引用校验的写法与 report 记录 API）追加：

```python
    # 统一资源层：@grant_spell / item: 引用校验
    if spell_lib is not None:
        import re as _re
        for sc in (l2_data.get("scenes", {}) or {}).values():
            for ent in (sc.get("interactions", []) + sc.get("auto_triggers", [])):
                for se in (ent.get("side_effects") or []):
                    m = _re.search(r'spell_ref="([^"]+)"', str(se))
                    if m and not spell_lib.get(m.group(1)):
                        report.add(CrossRefIssue(
                            layer="l2", entity_id=ent.get("id", ""),
                            field="side_effects",
                            issue=f"@grant_spell 引用未知法术: {m.group(1)}"))
```

（`CrossRefIssue`/`report.add` 的实际字段名以现场类定义为准对齐；若 add 签名不同，按邻近武器校验分支同样方式记录。）

run_pipeline.py：在 `wl = WeaponLibrary(); wl.load_core(...)`（run_interactive :1160 与 run_auto :1237 两处）后追加：

```python
        from library.items import ItemLibrary
        from library.spells import SpellLibrary
        ilib = ItemLibrary(); ilib.load_core(str(PROJECT_ROOT / "data/library/core/items.json"))
        slib = SpellLibrary(); slib.load_core(str(PROJECT_ROOT / "data/library/core/spells.json"))
```

并把 `run_pipeline(...)` 调用（:1091 附近的 `weapon_lib=runner.wl, enemy_lib=runner.el`）追加 `item_lib=ilib, spell_lib=slib`；layered_pipeline.run_pipeline 签名追加 `item_lib=None, spell_lib=None` 并传入 `parse_step1a(item_names=[f"{i.name}（{i.category}）：{i.description[:30]}" for i in item_lib.list_all()] if item_lib else None, spell_names=[f"{s.id} {s.name}（{s.category}）：{s.description[:30]}" for s in spell_lib.list_all()] if spell_lib else None, ...)`（在现有调用点追加两个关键字实参）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_use_system.py::TestPipelineAwareness tests/test_p0_pipeline_fixes.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py run_pipeline.py tests/test_use_system.py
git commit -m "feat: 管线感知统一资源层--Step1a 库摘要/@grant_spell 标准化/交叉校验"
```

---

### Task 13: init_game 接线 + 编年史 + 快照字段

**Files:**
- Modify: `src/game_loop.py:209-240`（库加载 + ScenarioWorld 构造）
- Modify: `src/scenario_core.py:1607-1612`（render_for_author 玩家行）
- Modify: `src/investigator/models.py:285`（build_snapshot）
- Test: `tests/e2e/test_deterministic.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestChronicleSpellFacts:
    def test_player_line_contains_spells_and_mp_max(self, monkeypatch):
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.known_spells = ["HEART_ARREST"]
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)
        from game_loop import run_turn
        run_turn(game, "四处看看")
        rendered = world.chronicle.render_for_author(world)
        assert "HEART_ARREST" in rendered, "编年史玩家行必须含已知法术"
        assert "MP" in rendered

    def test_snapshot_has_mp_max_and_spells(self):
        from investigator import Investigator
        from investigator.rules import calc_derived
        inv = Investigator(name="快照")
        inv.derived = calc_derived(inv.stats)
        inv.known_spells = ["LIFE_DETECTION"]
        snap = inv.build_snapshot()
        assert snap.get("mp_max") == inv.derived.MP_MAX
        assert snap.get("known_spells") == ["LIFE_DETECTION"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/e2e/test_deterministic.py::TestChronicleSpellFacts -v`
Expected: FAIL（快照无字段/编年史无法术）

- [ ] **Step 3: 实现**

game_loop.py init_game：武器库加载块（:218 起，`weapon_lib` 加载完成后）追加：

```python
    # 统一资源层：物品/法术库
    from library.items import ItemLibrary
    from library.spells import SpellLibrary
    item_lib = ItemLibrary()
    item_lib.load_core()
    _item_ext_dir = Path("data/library/extensions/items")
    if _item_ext_dir.is_dir():
        for _f in sorted(_item_ext_dir.glob("*.json")):
            item_lib.load_extension(str(_f))
    spell_lib = SpellLibrary()
    spell_lib.load_core()
    _spell_ext_dir = Path("data/library/extensions/spells")
    if _spell_ext_dir.is_dir():
        for _f in sorted(_spell_ext_dir.glob("*.json")):
            spell_lib.load_extension(str(_f))
```

ScenarioWorld 构造（:234）追加 `item_library=item_lib, spell_library=spell_lib`。

scenario_core.py render_for_author 玩家行（:1607-1612）替换为：

```python
        p = world.player
        if p:
            weapons = "、".join(w.name for w in p.weapons) or "无"
            key_items = "、".join(getattr(world.memory, "key_items", [])) or "无"
            spells = "、".join(getattr(p, "known_spells", [])) or "无"
            parts.append(f"  玩家: HP {p.derived.HP}/{p.derived.HP_MAX} "
                         f"SAN {p.derived.SAN}/{p.derived.SAN_MAX} "
                         f"MP {p.derived.MP}/{getattr(p.derived, 'MP_MAX', '?')} "
                         f"LUCK {p.stats.LUCK} | 武器: {weapons}"
                         f" | 物品: {key_items} | 法术: {spells}")
```

models.py build_snapshot（:285 起的 dict）`"mp": self.derived.MP,` 行后加：

```python
                "mp_max": self.derived.MP_MAX,
                "known_spells": list(getattr(self, "known_spells", [])),
```

（前端展示层按项目约定不排期：快照字段经 player-status API 自然流出，模板展示随队列 0 前端优化一并做。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/e2e/test_deterministic.py tests/test_chronicle.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add src/game_loop.py src/scenario_core.py src/investigator/models.py tests/e2e/test_deterministic.py
git commit -m "feat: init_game 双库接线 + 编年史法术块 + 快照 mp_max/known_spells"
```

---

### Task 14: real_llm 场景 + 全量回归 + 文档

**Files:**
- Modify: `tests/e2e/test_scenarios.py`（追加 S12-S14）
- Modify: `MAINTENANCE.md`、`readme.md`（待升级表 U6/U8）、`UPDATES.md`
- 无新 src 改动（本任务是验收与文档）

- [ ] **Step 1: 追加 real_llm 场景**（tests/e2e/test_scenarios.py 末尾）

```python
class TestS12SpellPerception:
    @retry_once
    def test_l0_spell_perception(self):
        """L0 感知法术：UseParser 命中 -> 无副作用叙事，真实 narrator。"""
        from library.spells import SpellLibrary
        from game.agents.keeper import Keeper
        slib = SpellLibrary(); slib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a", spell_library=slib)
        inv = _player(world)
        inv.known_spells = ["LIFE_DETECTION"]
        keeper = Keeper(world)
        keeper.narrator_l1 = _l1("room_a")
        game = _real_game(world, _l1("room_a"))
        from game_loop import run_turn
        r = run_turn(game, "我闭上眼睛，念诵生命觉察的咒文，感知周围的活物")
        assert_player_turn_contract(r)
        assert r.status.name == "COMPLETED"
        assert inv.derived.MP < 3 or inv.derived.MP <= inv.derived.MP_MAX


class TestS13ItemUse:
    @retry_once
    def test_l1_first_aid(self):
        from library.items import ItemLibrary
        ilib = ItemLibrary(); ilib.load_core()
        world = make_world({"room_a": make_scene()}, "room_a", item_library=ilib)
        inv = _player(world)
        inv.item_manager.add("急救包", quantity=1)
        inv.derived.HP = max(1, inv.derived.HP_MAX - 5)
        game = _real_game(world, _l1("room_a"))
        from game_loop import run_turn
        r = run_turn(game, "我拿出急救包，给自己处理伤口")
        assert_player_turn_contract(r)
        assert inv.item_manager.get("急救包") is None \
            or inv.item_manager.get("急救包").quantity == 0


class TestS14SpellAuthor:
    @retry_once
    def test_unknown_material_escalates(self):
        """库外素材引用 -> creative -> Author。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        _player(world)
        keeper = Keeper(world)
        keeper.narrator_l1 = _l1("room_a")

        from game.agents.author import Author
        author = Author({"module_meta": {"name": "t"}, "scene_intents": {},
                         "ending_conditions": []})
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": author}
        from helpers import stub_keeper_llm
        import pytest as _pytest
        # parse 粗识别 use 但素材未命中（确定性层无该物品/法术）
        keeper._parse = lambda raw: [{"type": "use", "text": raw}]
        keeper.use_parser.llm_call = lambda p, **k: {"matched": False, "material": "", "reason": ""}
        from game_loop import run_turn
        r = run_turn(game, "我举起那台古怪的黄铜装置，按下了侧面的按钮")
        assert_player_turn_contract(r)
        # Author 通路真实 LLM：只断言回合完整，不硬断言 patch 内容
```

- [ ] **Step 2: 跑 real_llm 套件与回归**

Run: `python -m pytest tests/ -q`（默认套件，全部应绿）
Run: `python -m pytest tests/e2e/test_scenarios.py -m real_llm -v`（S1-S14）
Run: `python tests/e2e/test_escalation_real.py`（C/E 回归观察：flavor 豁免后应恢复，若仍被挡记录到 UPDATES 已知观察）

- [ ] **Step 3: 更新文档**

- `MAINTENANCE.md`：新增/更新条目--`src/library/items.py`、`src/library/spells.py`、`src/game/use_parser.py`（函数级表）、models/serialization/judge/keeper/combat/prompts/scenario_core/game_loop/layered_*/run_pipeline 的变更行号与新增方法（execute_material、_material_catalogs、opposed_check、ItemCatalog 等）；Changelog 加一行
- `readme.md`：待升级表 U6/U8 行标 ✅（注明 2026-08-18 统一资源层落地）；@markup 表 @grant_spell 行从"U9 预留"改为正式；设计文档索引加新 spec
- `UPDATES.md`：追加工作汇总（本期内容 + 测试现状 + 门控备注收口情况）

- [ ] **Step 4: 全量验证**

Run: `python -m pytest tests/ -q && python -m pytest tests/ -m real_llm -q`
Expected: 默认套件全绿；real_llm 除既有波动外 S12-S14 通过

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_scenarios.py MAINTENANCE.md readme.md UPDATES.md
git commit -m "test+docs: real_llm S12-S14 场景 + U6/U8 完成记录 + MAINTENANCE 同步"
```

---

## Self-Review 记录

- **Spec 覆盖**：§1 影响层级（Task 8/9）、§1.1 检定下沉（Task 8）、§1.2 门控（Task 9）、§2 资源层+MP 修复（Task 1/2/3）、§2.5 @grant_spell（Task 4）、§3 UseParser（Task 5/6）、§4 parse/requirement（Task 9/10）、§5 L2 复用（Task 9 归一化转 creative）、§6 战斗（Task 7/11）、§7 管线（Task 12）、§8 编年史/快照（Task 13）、§9 测试（各 Task + 14）。前端模板展示明确缓期（随队列 0），已在 Task 13 注明。
- **占位符**：无 TBD；Task 12 中 cross_validate 的 CrossRefIssue 字段名标注"以现场类定义为准对齐"，属边界适配非占位（邻近武器校验分支为模板）。
- **类型一致性**：UseParseResult 字段在 Task 5 定义后被 Task 8/9 一致引用；`execute_material` 签名 Task 8/9 一致；`spell_lib` 参数名 Task 11/12/13 统一。
