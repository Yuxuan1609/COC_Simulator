# U9 技能系统重修 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 COC 7th 45 技能/9 属性体系替换为 20 技能/8 属性配置化体系，技能名归一单点下沉，模组串联三层防护。

**Architecture:** `data/skill_config.json` 单一事实源（技能/属性/乘数/legacy_map/attr_aliases/pseudo_skills）；`utils.normalize_skill_name()` 唯一归一入口；`Investigator.get_skill()/check_skill()` 单点消费；敌人/Boss 库的 SIZ **保留不动**（只删调查员侧）。

**Tech Stack:** Python 3、dataclass、JSON 配置、pytest。

**Spec:** `docs/superpowers/specs/2026-06-10-skill-system-redesign.md`（2026-08-14 修订版，config JSON 全文在其中 5.1/5.2 节）

**关键边界（动手前必读）：**
- 敌人/Boss 库 attributes 含 SIZ，`enemy_manager.py:57,63,241`、`boss_manager.py:41`、`combat.py:15,49,876,963` 的 `(CON+SIZ)/10` HP 公式与 `calc_db(STR, SIZ)` **全部保留**——神话生物有体型。只删 `Investigator.Stats.SIZ` 与 `DerivedStats.MOV`。
- 现行 `rules.py:260` 有"闪避"技能、`combat.py:783` 特判"回避"——统一走 pseudo_skills（回避/闪避→DODGE），新技能表不含闪避。
- `check_skill` 未掌握默认成功的容错**保留**，但必须经 `Investigator.check_warnings` 可观测。
- 旧角色卡/旧存档（含 SIZ 的 stats 结构）一律拒绝加载，提示重建。
- TDD；commit 英文 prefix + 中文描述；改代码后同步 MAINTENANCE.md。

---

### Task 1: skill_config + 归一函数

**Files:**
- Create: `data/skill_config.json`
- Create: `data/occupation_labels.json`
- Modify: `src/utils.py:142-161`
- Test: `tests/test_skill_config.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_skill_config.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils import load_skill_config, normalize_skill_name, get_coc_skill_names


def test_config_loads_20_skills_8_attributes():
    cfg = load_skill_config()
    assert len(cfg["skills"]) == 20
    assert set(cfg["attributes"].keys()) == {
        "STR", "CON", "DEX", "APP", "INT", "POW", "EDU", "LUCK"}
    names = [s["name"] for s in cfg["skills"]]
    assert "侦查" in names and "话术" not in names


def test_normalize_exact_new_skill():
    assert normalize_skill_name("侦查") == ("skill", "侦查")


def test_normalize_legacy_map():
    assert normalize_skill_name("话术") == ("skill", "说服")
    assert normalize_skill_name("急救") == ("skill", "生存")
    assert normalize_skill_name("导航") == ("skill", "侦查")


def test_normalize_bracket_specialization():
    assert normalize_skill_name("格斗(拳)") == ("skill", "格斗")
    assert normalize_skill_name("射击（手枪）") == ("skill", "枪械")


def test_normalize_attr_alias():
    assert normalize_skill_name("敏捷") == ("attr", "DEX")
    assert normalize_skill_name("意志") == ("attr", "POW")
    assert normalize_skill_name("SIZ") == ("attr", "CON")
    assert normalize_skill_name("灵感") == ("attr", "INT")


def test_normalize_pseudo_dodge():
    assert normalize_skill_name("回避") == ("pseudo", "DODGE")
    assert normalize_skill_name("闪避") == ("pseudo", "DODGE")


def test_normalize_deprecated_and_unknown():
    assert normalize_skill_name("母语") == ("ignore", "母语")
    assert normalize_skill_name("炼金术") == ("unknown", "炼金术")


def test_skill_names_from_config():
    names = get_coc_skill_names()
    assert len(names) == 20 and "运动" in names
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -x -q`
Expected: FAIL `ImportError: cannot import name 'load_skill_config'`

- [ ] **Step 3: 创建 data/skill_config.json**

内容用 spec 5.1 节全文（attributes 8 项含 multiplier 梯队 0.5/1/1.5、derived 公式表、skills 20 项、legacy_map、attr_aliases、pseudo_skills）。注意 `derived` 节的公式字段仅供文档化，代码不写通用公式解析器（YAGNI）——公式硬编码在 rules.py。

- [ ] **Step 4: 创建 data/occupation_labels.json**

内容用 spec 5.2 节全文（6 标签 + 自定义）。

- [ ] **Step 5: utils.py 实现**

在 `src/utils.py` 的 `load_skill_checks` 前插入：

```python
_SKILL_CONFIG_CACHE: dict | None = None


def load_skill_config(path: str | None = None) -> dict:
    """加载技能体系配置（技能/属性/legacy_map/attr_aliases/pseudo_skills），缓存。"""
    global _SKILL_CONFIG_CACHE
    if _SKILL_CONFIG_CACHE is None or path is not None:
        import json
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "skill_config.json")
            path = os.path.normpath(path)
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if path.endswith("skill_config.json"):
            _SKILL_CONFIG_CACHE = cfg
        return cfg
    return _SKILL_CONFIG_CACHE


def normalize_skill_name(name: str) -> tuple[str, str]:
    """技能名归一单点。返回 (kind, value)：
    ("skill", 新技能名) / ("attr", 属性英文名) / ("pseudo", "DODGE") /
    ("ignore", 原名)（已废弃如母语） / ("unknown", 原名)（未识别）。
    顺序：新表精确 → legacy_map → 去括号重试 → 属性别名 → 伪技能 → unknown。
    """
    cfg = load_skill_config()
    name = (name or "").strip()
    if not name:
        return ("unknown", name)
    new_names = {s["name"] for s in cfg["skills"]}
    legacy = cfg.get("legacy_map", {})

    def _lookup(n: str) -> tuple[str, str] | None:
        if n in new_names:
            return ("skill", n)
        if n in legacy:
            mapped = legacy[n]
            return ("ignore", n) if mapped is None else ("skill", mapped)
        return None

    hit = _lookup(name)
    if hit:
        return hit
    import re as _re
    stripped = _re.sub(r"[（(][^)）]*[)）]", "", name).strip()
    if stripped != name:
        hit = _lookup(stripped)
        if hit:
            return hit
    aliases = cfg.get("attr_aliases", {})
    if name in aliases:
        return ("attr", aliases[name])
    pseudo = cfg.get("pseudo_skills", {})
    if name in pseudo:
        return ("pseudo", pseudo[name])
    return ("unknown", name)
```

`get_coc_skill_names()` 改为从 config 读：

```python
def get_coc_skill_names() -> list[str]:
    """获取新 20 项技能名列表（缓存，从 data/skill_config.json 读取）。"""
    global _COC_SKILL_NAMES_CACHE
    if _COC_SKILL_NAMES_CACHE is None:
        _COC_SKILL_NAMES_CACHE = [s["name"] for s in load_skill_config()["skills"]]
    return _COC_SKILL_NAMES_CACHE
```

（`load_skill_checks()` 保留签名不动，Task 8 处理数据源。）

- [ ] **Step 6: 跑测试确认绿**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add data/skill_config.json data/occupation_labels.json src/utils.py tests/test_skill_config.py
git commit -m "feat: U9 技能配置 + 归一函数——skill_config.json 单一事实源，normalize_skill_name 五路归一"
```

---

### Task 2: models.py——Stats 删 SIZ + check_skill 归一/属性通路/LUCK

**Files:**
- Modify: `src/investigator/models.py:13-53`（Stats/DerivedStats/Skill）、`:149-268`（Investigator）
- Test: `tests/test_skill_config.py`（追加）

- [ ] **Step 1: 写失败测试（追加到 tests/test_skill_config.py）**

```python
def test_stats_no_siz_derived_no_mov():
    from investigator.models import Stats, DerivedStats
    s = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    assert not hasattr(s, "SIZ")
    d = DerivedStats()
    assert not hasattr(d, "MOV")


def test_check_skill_legacy_name_normalized():
    from investigator.models import Investigator, Skill
    inv = Investigator(name="t")
    inv.skills.append(Skill(name="说服", base_value=15, value=50))
    ok, msg, tier = inv.check_skill("话术")  # legacy → 说服
    assert "话术" in msg and "未掌握" not in msg


def test_check_skill_attr_channel():
    from investigator.models import Investigator, Stats
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=99, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    ok, msg, tier = inv.check_skill("敏捷")  # 属性通路，阈值=DEX=99
    assert ok and "未掌握" not in msg


def test_check_skill_unknown_warns_and_passes():
    from investigator.models import Investigator
    inv = Investigator(name="t")
    ok, msg, tier = inv.check_skill("炼金术")
    assert ok and "未掌握" in msg
    assert any("炼金术" in w for w in inv.check_warnings)


def test_spend_luck_and_pending_bonus():
    from investigator.models import Investigator, Stats, Skill
    inv = Investigator(name="t")
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    ok, msg = inv.spend_luck(10)
    assert ok and inv.stats.LUCK == 40
    inv.pending_luck_bonus = 10
    inv.skills.append(Skill(name="侦查", base_value=25, value=25))
    ok2, msg2, _ = inv.check_skill("侦查")
    assert inv.pending_luck_bonus == 0, "幸运加值必须一次性消费"
    ok3, _ = inv.spend_luck(99)
    assert not ok3, "余额不足必须拒绝"


def test_check_skill_pseudo_dodge():
    from investigator.models import Investigator
    inv = Investigator(name="t")
    inv.derived.DODGE = 99
    ok, msg, tier = inv.check_skill("闪避")
    assert ok and "未掌握" not in msg
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q -k "stats_no_siz or legacy_name or attr_channel or unknown_warns or spend_luck or pseudo_dodge"`
Expected: FAIL（SIZ 仍存在 / check_warnings 不存在等）

- [ ] **Step 3: models.py 改造**

3a. `Stats`（:13-24）删 SIZ 行：

```python
@dataclass
class Stats:
    """八项核心属性（U9：SIZ 并入 CON，删除 MOV）"""
    STR: int = 0   # 力量   (3D6*5)
    CON: int = 0   # 体质   (3D6*5)，并入原 SIZ
    DEX: int = 0   # 敏捷   (3D6*5)
    APP: int = 0   # 外貌   (3D6*5)
    INT: int = 0   # 智力   (2D6+6)*5
    POW: int = 0   # 意志   (3D6*5)
    EDU: int = 0   # 教育   (2D6+6)*5
    LUCK: int = 0  # 幸运   (3D6*5)，自身即技能值，可消耗
```

3b. `DerivedStats`（:27-38）删 MOV 行，注释 HP 公式改 `= CON//3`。

3c. `Investigator._ALLOWED_STATS`（:152）删 `"SIZ"`。

3d. `Investigator.__init__` 末尾（:188 后）加：

```python
        self.check_warnings: list[str] = []   # 技能归一/未掌握 warning（keeper 每回合收集）
        self.pending_luck_bonus: int = 0      # LUCK 声明消耗的下一次检定加值（一次性）
        self.label: str = ""                  # 职业标签名（U9 标签制）
```

3e. `get_skill`（:199-203）加归一：

```python
    def get_skill(self, name: str) -> Optional[Skill]:
        from utils import normalize_skill_name
        kind, value = normalize_skill_name(name)
        lookup = value if kind == "skill" else name
        for s in self.skills:
            if s.name == lookup:
                return s
        return None
```

3f. `check_skill`（:211-254）重写为归一 + 属性/伪技能通路 + LUCK 消费：

```python
    def check_skill(self, skill_name: str, difficulty: str = "regular") -> tuple:
        """D100 检定。名归一经 normalize_skill_name：
        skill→技能值；attr→属性值；pseudo(DODGE)→衍生闪避；
        ignore→直接成功；unknown/未掌握→记 check_warnings 后默认成功。
        pending_luck_bonus 存在时给骰点 -N（下限 1），一次性消费。"""
        from utils import normalize_skill_name
        kind, value = normalize_skill_name(skill_name)
        if kind == "ignore":
            return True, f"{skill_name}（已废弃技能，跳过检定）", "regular"
        if kind == "attr":
            target = getattr(self.stats, value, 0)
            return self._roll_d100(skill_name, target)
        if kind == "pseudo":
            return self._roll_d100(skill_name, self.derived.DODGE)
        skill = self.get_skill(skill_name)  # kind=="skill" 时 get_skill 已归一
        if skill is None:
            self.check_warnings.append(
                f"未掌握技能[{skill_name}]（归一={kind}:{value}），默认成功放行")
            return True, f"{skill_name}（未掌握，默认判定成功）", "regular"
        return self._roll_d100(skill_name, skill.value)

    def _roll_d100(self, name: str, target: int) -> tuple:
        roll = random.randint(1, 100)
        if self.pending_luck_bonus:
            roll = max(1, roll - self.pending_luck_bonus)
            self.pending_luck_bonus = 0
        if roll >= 96:
            return False, f"{name}检定：D100={roll}/{target} ≥96 大失败！", "fumble"
        if roll == 1:
            return True, f"{name}检定：D100=1/{target} 大成功！", "extreme"
        extreme_threshold = max(1, target // 5)
        hard_threshold = max(1, target // 2)
        if roll <= extreme_threshold:
            tier = "extreme"
        elif roll <= hard_threshold:
            tier = "hard"
        elif roll <= target:
            tier = "regular"
        else:
            return False, f"{name}检定：D100={roll}/{target} > 失败", "failure"
        return True, f"{name}检定：D100={roll}/{target} ≤ {target} 成功（{tier}级）", tier

    def spend_luck(self, n: int) -> tuple[bool, str]:
        """消耗 N 点 LUCK（声明式）。余额不足或 N≤0 拒绝。"""
        if n <= 0:
            return False, "消耗点数必须为正"
        if self.stats.LUCK < n:
            return False, f"幸运不足：当前 {self.stats.LUCK}，需 {n}"
        self.stats.LUCK -= n
        return True, f"消耗 {n} 点幸运（剩余 {self.stats.LUCK}）"
```

（原 check_skill 内联骰点逻辑全部进 `_roll_d100`；`check_skills` 批量方法不动。）

- [ ] **Step 4: 跑测试确认绿**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q`
Expected: 13 passed

- [ ] **Step 5: 跑全量套件查回归**

Run: `python -X utf8 -m pytest tests/ -q --ignore=tests/e2e/test_scenarios.py --ignore=tests/e2e/test_escalation_real.py`
Expected: 有 FAIL——引用 SIZ/MOV 的旧测试与旧卡（combat_test_character.json）会在 Task 4/8 修，本步记录失败清单即可，**不要在本任务修**

- [ ] **Step 6: Commit**

```bash
git add src/investigator/models.py tests/test_skill_config.py
git commit -m "feat: U9 models——Stats 删 SIZ/MOV，check_skill 单点归一+属性/伪技能通路+LUCK 声明消耗"
```

---

### Task 3: rules.py 重写

**Files:**
- Modify: `src/investigator/rules.py`（roll_stats:17、calc_derived:52、SKILL_BASE_VALUES:81、create_skill_list:118、allocate_skill_points:132、create_default_dodge_skill:260、load_occupations:275）
- Test: `tests/test_skill_config.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_roll_stats_no_siz():
    from investigator.rules import roll_stats
    s = roll_stats()
    assert not hasattr(s, "SIZ")
    assert 15 <= s.STR <= 90 and 40 <= s.INT <= 90


def test_calc_derived_new_formulas():
    from investigator.models import Stats
    from investigator.rules import calc_derived
    s = Stats(STR=80, CON=60, DEX=70, APP=50, INT=60, POW=55, EDU=65, LUCK=40)
    d = calc_derived(s)
    assert d.HP == 20 and d.HP_MAX == 20          # CON//3
    assert d.MP == 11 and d.SAN == 55              # POW//5 / POW
    assert d.DODGE == 35                           # DEX//2
    assert not hasattr(d, "MOV")
    # DB/BUILD 查表键 = STR + CON//2 = 80+30 = 110 → "0"/0
    assert d.DB == "0" and d.BUILD == 0


def test_create_skill_list_from_config():
    from investigator.rules import create_skill_list
    skills = create_skill_list()
    assert len(skills) == 20
    spot = next(s for s in skills if s.name == "侦查")
    assert spot.base_value == 25 and spot.value == 25


def test_allocate_attribute_pools():
    from investigator.models import Stats
    from investigator.rules import create_skill_list, allocate_skill_points
    stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=60)
    skills = create_skill_list()
    allocate_skill_points(skills, stats, focus=["侦查"], focus_bonus=10)
    spot = next(s for s in skills if s.name == "侦查")
    # 池：INT=60*1.5=90，EDU=60*1.5=90，各均分到归属技能后叠加；标签 +10
    assert spot.value > 25, "池分配后必须高于基础值"
    assert spot.value <= 99
    cthulhu = next(s for s in skills if s.name == "克苏鲁神话")
    assert cthulhu.value == 0, "克苏鲁神话不走池"
    luck = next((s for s in skills if s.name == "幸运"), None)
    assert luck is None, "LUCK 不在技能列表"


def test_load_occupation_labels():
    from investigator.rules import load_occupation_labels
    labels = load_occupation_labels()
    names = [l["name"] for l in labels]
    assert "侦探" in names and "自定义" in names
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q -k "roll_stats or calc_derived or create_skill_list or allocate or occupation_labels"`
Expected: FAIL

- [ ] **Step 3: rules.py 改造**

3a. `roll_stats()`（:17-29）删 SIZ 行。

3b. `calc_derived()`（:52-73）重写：

```python
def calc_derived(stats: Stats, age: int = 20, cthulhu_mythos: int = 0) -> DerivedStats:
    """U9 衍生公式：HP=CON//3；DB/BUILD 查表键=STR+CON//2；删 MOV。"""
    hp = max(1, math.floor(stats.CON / 3))
    mp = math.floor(stats.POW / 5)
    san = stats.POW
    san_max = 99 - cthulhu_mythos
    dodge = math.floor(stats.DEX / 2)
    db, build = _calc_db_build(stats.STR + stats.CON // 2)
    return DerivedStats(
        HP=hp, HP_MAX=hp, MP=mp, SAN=san, SAN_MAX=san_max,
        DB=db, BUILD=build, DODGE=dodge,
    )
```

（`_calc_db_build` 查表逻辑不变——区间表与新键值域兼容。）

3c. 删 `SKILL_BASE_VALUES`（:81-94）与 `SKILL_CATEGORIES`（:97-110）两个硬编码表；`create_skill_list()` 改从 config：

```python
def create_skill_list() -> List[Skill]:
    """从 skill_config.json 生成新 20 项技能列表（克苏鲁神话 base=0 不走池）。"""
    from utils import load_skill_config
    cfg = load_skill_config()
    return [
        Skill(name=s["name"], base_value=s["base"], value=s["base"],
              category="、".join(s.get("attr", [])))
        for s in cfg["skills"]
    ]
```

3d. `allocate_skill_points` 重写为属性池制：

```python
def allocate_skill_points(
    skills: List[Skill],
    stats: Stats,
    focus: List[str] | None = None,
    focus_bonus: int = 0,
) -> List[Skill]:
    """U9 属性池分配：每属性池=属性值×乘数（config），均分到归属技能；
    多属性技能从各归属池分别获益叠加；focus 技能额外 +focus_bonus；上限 99。"""
    from utils import load_skill_config
    cfg = load_skill_config()
    attrs_cfg = cfg["attributes"]
    skill_attrs = {s["name"]: s.get("attr", []) for s in cfg["skills"]}
    no_pool = {s["name"] for s in cfg["skills"] if s.get("special") == "no_pool"}

    by_name = {s.name: s for s in skills}
    for attr, ac in attrs_cfg.items():
        pool = int(getattr(stats, attr, 0) * float(ac.get("multiplier", 0)))
        members = [n for n, al in skill_attrs.items()
                   if attr in al and n not in no_pool and n in by_name]
        if not members or pool <= 0:
            continue
        per, rem = divmod(pool, len(members))
        for i, n in enumerate(members):
            by_name[n].value += per + (1 if i < rem else 0)
    for n in (focus or []):
        if n in by_name:
            by_name[n].value += focus_bonus
    for s in skills:
        s.value = min(99, max(s.value, s.base_value if s.name not in no_pool else 0))
    return skills
```

3e. 删 `create_default_dodge_skill()`（:260-268，闪避不再是技能，由 pseudo_skills 通路处理）；`calc_occupation_points`/`load_occupations` 保留（旧 Occupation dataclass 兼容用）；新增：

```python
def load_occupation_labels(path: str | None = None) -> list:
    """加载职业标签（U9 标签制）。"""
    import json, os
    if path is None:
        path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "occupation_labels.json"))
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

3f. `calc_db(STR, SIZ)`（:293）**保留不动**（敌人侧仍用）。

- [ ] **Step 4: 跑测试确认绿**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/investigator/rules.py tests/test_skill_config.py
git commit -m "feat: U9 rules——新衍生公式(HP=CON/3,DB键=STR+CON/2) + 属性池分配 + 职业标签加载"
```

---

### Task 4: serialization.py——新结构 + 旧卡拒绝

**Files:**
- Modify: `src/investigator/serialization.py:40-94`（to_dict）、`:104-184`（from_dict）
- Test: `tests/test_skill_config.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_roundtrip_new_structure():
    import tempfile, os
    from investigator.models import Investigator, Stats, Skill
    from investigator.rules import calc_derived
    from investigator.serialization import to_json, from_json
    inv = Investigator(name="新卡", age=30)
    inv.stats = Stats(STR=60, CON=60, DEX=60, APP=60, INT=60, POW=60, EDU=60, LUCK=50)
    inv.derived = calc_derived(inv.stats)
    inv.skills.append(Skill(name="侦查", base_value=25, value=50))
    inv.label = "侦探"
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "c.json")
        to_json(inv, p)
        back = from_json(p)
    assert back.name == "新卡" and back.label == "侦探"
    assert back.get_skill("侦查").value == 50
    assert not hasattr(back.stats, "SIZ")


def test_old_card_rejected():
    import pytest
    from investigator.serialization import from_dict
    old = {"meta": {"version": "1.0"}, "personal": {"name": "旧卡"},
           "stats": {"STR": 60, "CON": 60, "SIZ": 65, "DEX": 60, "APP": 50,
                     "INT": 60, "POW": 55, "EDU": 65, "LUCK": 40},
           "skills": [{"name": "话术", "base": 5, "value": 40}]}
    with pytest.raises(ValueError, match="重建"):
        from_dict(old)
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q -k "roundtrip or old_card"`
Expected: FAIL

- [ ] **Step 3: serialization.py 改造**

3a. `to_dict`（:40-94）：`meta.version` 改 `"2.0"`；`stats` 块删 SIZ 键；`derived` 块删 MOV 键；`personal` 块加 `"label": getattr(inv, 'label', '')`。

3b. `from_dict`（:104+）开头加旧卡检测：

```python
def from_dict(data: dict) -> Investigator:
    """dict → Investigator。旧 45 技能/含 SIZ 结构的卡拒绝加载（U9 强制重建）。"""
    stats_data = data.get("stats", {})
    if "SIZ" in stats_data:
        raise ValueError(
            "旧版角色卡（含 SIZ 的 45 技能体系）不兼容新技能体系，请重建角色。")
```

随后 `Stats(...)` 构造删 SIZ 参数；`DerivedStats(...)` 删 MOV 参数；Investigator 构造后加 `inv.label = personal.get("label", "")`。

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q` → Expected: 20 passed
Run: `python -X utf8 -m pytest tests/ -q --ignore=tests/e2e/test_scenarios.py --ignore=tests/e2e/test_escalation_real.py` → 记录仍失败的（预期：引用旧卡/SIZ 的测试）

- [ ] **Step 5: Commit**

```bash
git add src/investigator/serialization.py tests/test_skill_config.py
git commit -m "feat: U9 序列化 v2.0——删 SIZ/MOV 字段 + 旧卡拒绝加载提示重建"
```

---

### Task 5: keeper/judge/combat 适配

**Files:**
- Modify: `src/game/agents/keeper.py:1057`（standoff 说服集合）、keeper 回合早期（LUCK 识别，插在 `_inject_npc_at()` 调用后约 :173）
- Modify: `src/game/combat.py`（玩家 DB 取值）
- Test: `tests/e2e/test_deterministic.py`（追加 TestLuckDeclare）

- [ ] **Step 1: 写失败测试（追加 tests/e2e/test_deterministic.py）**

```python
class TestLuckDeclare:  # U9: LUCK 输入声明式消耗
    def test_burn_luck_applies_bonus(self, monkeypatch):
        """输入"烧5点幸运"→ LUCK -5，pending_luck_bonus 被当回合检定消费。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        interaction = {
            "id": "IT_LOCK", "entity_type": "interaction",
            "name": "撬锁", "scene": "room_a",
            "type": "锁匠", "requirement": "", "trigger": "尝试撬锁",
            "result": "开了。", "side_effects": [], "difficulty": "regular",
            "time_condition": [],
        }
        world = make_world({"room_a": make_scene(interactions=[interaction])}, "room_a")
        inv = _player(world)
        inv.stats.LUCK = 50
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        run_turn(game, "烧5点幸运，然后撬锁")
        assert inv.stats.LUCK == 45, f"LUCK 必须扣 5，实际 {inv.stats.LUCK}"
        assert inv.pending_luck_bonus == 0, "加值必须已被检定消费"

    def test_burn_luck_insufficient_rejected(self, monkeypatch):
        """LUCK 余额不足 → 不扣减，记 warning。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.stats.LUCK = 3
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        run_turn(game, "烧10点幸运")
        assert inv.stats.LUCK == 3, "余额不足不得扣减"
        assert any("幸运" in w for w in keeper._warnings)
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/e2e/test_deterministic.py::TestLuckDeclare -x -q`
Expected: FAIL（LUCK 未扣）

- [ ] **Step 3: keeper.py 加 LUCK 识别**

在 `process_turn` 的 `self._inject_npc_at()`（约 :173）之后插入：

```python
        # U9：LUCK 声明式消耗——"烧/用 N 点幸运" → spend_luck + pending_luck_bonus
        _luck_m = re.search(r"(?:烧|燃烧|用|消耗)\s*(\d{1,2})\s*点?\s*(?:幸运|运气|LUCK|luck)",
                            raw)
        if _luck_m:
            _n = int(_luck_m.group(1))
            _ok, _msg = self.world.player.spend_luck(_n)
            if _ok:
                self.world.player.pending_luck_bonus = _n
            self._warnings.append(f"LUCK 消耗：{_msg}")
```

注意 `_warnings.clear()` 在 :166 回合开始处——本插入点在其后，warning 不会被清。

3b. keeper.py:1057 standoff 说服集合归一：

```python
            from utils import normalize_skill_name as _nsn
            if _nsn(skill_name)[1] in ("魅惑", "说服"):
```

（替换 `if skill_name in ("魅惑", "说服", "话术", "恐吓"):`——旧名经归一后落进"魅惑/说服"两族。）

3c. combat.py 玩家 DB：`:15` `_roll_damage(damage_spec, STR=50, SIZ=50)` 中 `db = calc_db(STR, SIZ)` 的**玩家调用点**改为优先用 `player.derived.DB`；敌人调用点保留 `calc_db(STR, SIZ)`。具体：找到 `_roll_damage` 玩家侧调用处（`:49` 附近），传入的 STR/SIZ 对玩家改为 `(0, 0)` 并在 damage_spec 解析 "DB" 时直接取 `player.derived.DB`；若该函数对玩家/敌人共用，则加参数 `db_override: str | None = None`：

```python
def _roll_damage(damage_spec, STR: int = 50, SIZ: int = 50, db_override: str | None = None) -> int:
    ...
    db = db_override if db_override is not None else calc_db(STR, SIZ)
```

玩家路径调用点传 `db_override=getattr(player.derived, "DB", None)`。

3d. judge.py 无改动（归一在 check_skill 单点生效）——确认 judge.py:168-174 照旧。

- [ ] **Step 4: 跑测试确认绿**

Run: `python -X utf8 -m pytest tests/e2e/test_deterministic.py -q`
Expected: 27+ passed（含 TestLuckDeclare 2 个）

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py src/game/combat.py tests/e2e/test_deterministic.py
git commit -m "feat: U9 keeper/combat——LUCK 声明式消耗识别 + standoff 说服集合归一 + 玩家 DB 取 derived"
```

---

### Task 6: 管线适配（parser/pipeline/supplement）

**Files:**
- Modify: `src/module_designer/layered_pipeline.py:484-490`、`:758`（stat_names 删 SIZ）、`:766-772`
- Modify: `src/module_designer/layered_parser.py:1410-1420` 附近（STEP4 实体落库点）
- Modify: `src/module_designer/supplement_pipeline.py:381` 附近
- Test: `tests/test_skill_config.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_pipeline_stat_names_no_siz():
    """stat_names 不含 SIZ（SIZ→CON 由 attr_aliases 兜底）。"""
    import re
    src = open("src/module_designer/layered_pipeline.py", encoding="utf-8").read()
    m = re.search(r"stat_names\s*=\s*\[([^\]]*)\]", src)
    assert m and '"SIZ"' not in m.group(1)


def test_normalize_entity_type_for_storage():
    """落库归一：旧技能名→新名；属性名/未知名保留原文。"""
    from utils import normalize_skill_name
    assert normalize_skill_name("话术") == ("skill", "说服")
    assert normalize_skill_name("敏捷")[0] == "attr"
```

- [ ] **Step 2: 实现**

2a. `layered_pipeline.py:758`：stat_names 列表删 `"SIZ"`。
2b. `layered_pipeline.py:484-490` 与 `:766-772`：`load_skill_checks()` 调用改为 `load_skill_config()["skills"]`（字段名同为 `name`，下游 `s["name"]` 不变）。
2c. `layered_parser.py` STEP2A/STEP4 实体落库处（parse_step2a 返回 dict 前）：对 entity 的 `type` 字段调 `normalize_skill_name`，`("skill", mapped)` 且 mapped≠原名 → 替换并 `warnings.append(f"技能名归一: {原名}→{mapped}")`；attr/pseudo/unknown 保留原名不替换（运行时单点兜底）。落库点在 :471 `parse_step2a` 内——在 return 前遍历结果 dict 的实体列表处理。
2d. `supplement_pipeline.py:381`：`get_coc_skill_names()` 调用不变（已自动返回新 20 表）。

- [ ] **Step 3: 跑测试**

Run: `python -X utf8 -m pytest tests/test_skill_config.py -q -k "pipeline or normalize_entity"` → Expected: PASS
Run: 全量默认套件 → 记录回归

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_pipeline.py src/module_designer/layered_parser.py tests/test_skill_config.py
git commit -m "feat: U9 管线——stat_names 删 SIZ + 技能名从 config 拉取 + 落库归一"
```

---

### Task 7: 前端最小适配

**Files:**
- Modify: `frontend/routers/character.py:47-48`（STATS/STAT_LABELS）、`:22`（SKILLS）
- Test: 无新测试——跑现有前端相关测试 + 手动 import 冒烟

- [ ] **Step 1: 改数据源**

`STATS` 改为从 config 读：`STATS = list(load_skill_config()["attributes"].keys())`（top 加 `from utils import load_skill_config`，注意 sys.path）；`STAT_LABELS` 删 `"SIZ": "体型"`；`SKILLS` 列表替换为新 20 项（从 config 读或按 spec 3.1 硬抄）。

- [ ] **Step 2: 冒烟**

Run: `python -X utf8 -c "import sys; sys.path.insert(0,'src'); sys.path.insert(0,'frontend'); from routers import character; print(character.STATS, len(character.SKILLS))"`
Expected: `['STR', 'CON', 'DEX', 'APP', 'INT', 'POW', 'EDU', 'LUCK'] 20`

- [ ] **Step 3: Commit**

```bash
git add frontend/routers/character.py
git commit -m "feat: U9 前端最小适配——STATS/SKILLS 从 skill_config 读，删 SIZ"
```

---

### Task 8: 数据清理 + 测试卡重建

**Files:**
- Delete: `data/occupations.json`
- Modify: `src/utils.py:142`（load_skill_checks 数据源切换到 config 或保留旧文件兼容）
- Rewrite: `data/investigator/combat_test_character.json`（新 20 技能 v2.0 结构）
- Test: 全量回归

- [ ] **Step 1: 重建测试卡**

用新体系生成 `combat_test_character.json`：v2.0 meta、8 属性无 SIZ、20 技能（格斗 80/枪械 60/侦查 60，其余基础值）、保留原特质描述字段、武器 徒手+小刀。手写 JSON 或脚本生成后经 `from_json` 验证可加载。

- [ ] **Step 2: 删 occupations.json + load_skill_checks 切换**

`load_skill_checks()` 内部改读 `skill_config.json` 的 skills 列表（保持返回 `[{"name": ...}]` 兼容形状），之后删除 `data/skill_checks.json` 与 `data/occupations.json`。

- [ ] **Step 3: 全量回归**

Run: `python -X utf8 -m pytest tests/ -q --ignore=tests/e2e/test_scenarios.py --ignore=tests/e2e/test_escalation_real.py`
Expected: 全绿（此前记录的 SIZ/旧卡相关失败在本任务清零——若有测试直接构造含 SIZ 的 Stats，删该参数）

- [ ] **Step 4: Commit**

```bash
git add -A data/ src/utils.py
git commit -m "chore: U9 数据清理——删 skill_checks/occupations 旧文件，测试卡按新体系重建"
```

---

### Task 9: 场景层回归 + 文档同步

**Files:**
- Modify: `MAINTENANCE.md`（models/rules/serialization/utils/keeper/combat 条目行号与签名）
- Modify: `UPDATES.md`（U9 完成记录 + 待办移除 0.5）
- Modify: `readme.md:357`（U9 行标注✅）
- Test: 场景层 S-D + 实连层子集

- [ ] **Step 1: 场景层 S-D 实跑**

Run: `python -X utf8 tests/e2e/run_scenario.py tests/e2e/scenarios/full_clear.yaml`
Expected: VERDICT PASS（三层）

- [ ] **Step 2: 实连层子集**

Run: `python -X utf8 -m pytest tests/e2e/test_scenarios.py -q -m real_llm`
Expected: 全过（技能名链路真实面验证：S3 武器 offer、standoff 匹配等）

- [ ] **Step 3: 文档同步 + Commit**

MAINTENANCE.md 更新涉及文件条目；UPDATES.md 记完成；readme U9 行加 ✅。

```bash
git add MAINTENANCE.md UPDATES.md readme.md
git commit -m "docs: U9 完成记录——场景层 S-D 与实连层全绿"
```

---

## Self-Review 记录

- Spec 覆盖：1.1 三层防护→Task 1/6；2.1 属性→Task 2/3；2.3 LUCK→Task 2/5；2.4 POW→Task 2（attr 通路）；3.x 技能/池→Task 1/3；4 标签→Task 1/3；5 配置→Task 1；6.1 文件表→Task 2-8；7.1-7.3 兼容→Task 1/4/6；8 步骤→Task 1-9
- 类型一致性：`normalize_skill_name` 返回 `(kind, value)` 四元 kind 在 Task 1/2/5/6 一致；`check_warnings`/`pending_luck_bonus`/`spend_luck`/`label` 在 Task 2 定义、Task 4/5 使用一致
- 已知留白：前端模板按属性分块 UI 完整版后置（spec 允许最小适配先行）；LUCK 恢复 1D10 触发器依赖 @markup，本期不实现（spec 标注由模组/GM 触发）
