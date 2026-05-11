# COC 7th 车卡模拟器 —— 设计规格

## 概述

基于《克苏鲁的呼唤》(Call of Cthulhu) 第7版规则书，设计一个解耦的角色卡创建系统。角色创建通过独立前端页面完成，导出 JSON 文件后由 Python 后端加载到 `ScenarioWorld` 中。新的 `Investigator` 类完全替代现有的 `Player` 桩类。

---

## 1. 数据模型 (`src/investigator/models.py`)

### Stats — 核心属性

```python
@dataclass
class Stats:
    STR: int = 0   # 力量   (3D6*5)
    CON: int = 0   # 体质   (3D6*5)
    SIZ: int = 0   # 体型   (2D6+6)*5
    DEX: int = 0   # 敏捷   (3D6*5)
    APP: int = 0   # 外貌   (3D6*5)
    INT: int = 0   # 智力   (2D6+6)*5
    POW: int = 0   # 意志   (3D6*5)
    EDU: int = 0   # 教育   (2D6+6)*5
    LUCK: int = 0  # 幸运   (3D6*5)
```

### DerivedStats — 衍生属性

```python
@dataclass
class DerivedStats:
    HP: int = 0        # 生命值 = floor((CON+SIZ)/10)
    MP: int = 0        # 魔法值 = floor(POW/5)
    SAN: int = 0       # 当前理智 = POW (初始)
    SAN_MAX: int = 99  # 最大理智 = 99 - 克苏鲁神话值
    MOV: int = 8       # 移动力 (7/8/9，基于 STR/SIZ/DEX 比较)
    DB: str = "0"      # 伤害加值 ("-2"/"-1"/"0"/"+1D4"/"+1D6"/"+2D6+")
    BUILD: int = 0     # 体格 (-2/-1/0/1/2/3+)
    DODGE: int = 0     # 闪避 = floor(DEX/2)
```

### Skill — 技能

```python
@dataclass
class Skill:
    name: str           # 技能名（"图书馆使用"、"侦查" 等）
    base_value: int     # 基础值
    value: int          # 当前值（初始=基础值，分配技能点后增长）
    category: str       # 分类：战斗/社交/知识/感知/操作/通用
    is_occupation: bool # 是否标记为职业技能
```

### Occupation — 职业定义

```python
@dataclass
class Occupation:
    name: str
    description: str
    occupation_skills: List[str]        # 职业技能名列表
    credit_rating_range: Tuple[int, int] # (min, max)
    skill_points_formula: str           # "EDU*4", "EDU*2+DEX*2" 等
```

### Weapon — 武器

```python
@dataclass
class Weapon:
    name: str
    skill_name: str    # 关联技能名（"格斗"、"枪械" 等）
    damage: str        # "1D3+DB"、"1D6" 等
    range: str         # "接触"、"20码" 等
    ammo: int = 0
    malfunction: int = 100  # 故障值
```

### Investigator — 主类

```python
class Investigator:
    name: str
    age: int
    gender: str
    occupation: Occupation | None
    stats: Stats
    derived: DerivedStats
    skills: List[Skill]
    weapons: List[Weapon]
    equipment: List[str]
    backstory: str
    appearance: str
    personal_description: str

    # 兼容旧 Player 接口
    @property
    def skills_dict(self) -> Dict[str, int]:
        """返回 {技能名: 当前值} 映射"""
        return {s.name: s.value for s in self.skills}
```

---

## 2. 公用掷骰 (`src/utils.py`)

`roll_dice` 和 `roll_d6` 放在 `src/utils.py`，作为公用工具函数。车卡系统、主循环技能鉴定等都从此导入。

```python
# src/utils.py 新增
def roll_dice(num: int, sides: int) -> int:
    """投 num 个 sides 面骰子求和"""
    import random
    return sum(random.randint(1, sides) for _ in range(num))

def roll_d6(num: int) -> int:
    """投 num 个 6 面骰子求和"""
    return roll_dice(num, 6)
```

## 3. 规则引擎 (`src/investigator/rules.py`)

全部为纯函数，不依赖类实例。掷骰函数从 `src.utils` 导入。

### 属性生成

- `roll_stats() -> Stats` — 标准规则掷骰生成（调用 `utils.roll_d6`）
  - STR/CON/DEX/APP/POW/LUCK: `roll_d6(3) * 5`
  - SIZ/INT/EDU: `(roll_d6(2) + 6) * 5`

### 衍生属性计算

- `calc_derived(stats: Stats, age: int, cthulhu_mythos: int = 0) -> DerivedStats`
  - HP = `floor((CON+SIZ)/10)`
  - MP = `floor(POW/5)`
  - SAN = POW 初始值
  - SAN_MAX = `99 - cthulhu_mythos`
  - MOV: STR<SIZ 且 DEX<SIZ → 7; STR>SIZ 且 DEX>SIZ → 9; 其他 → 8
  - DB/BUILD: 查表 (STR+SIZ 区间映射)
  - DODGE = `floor(DEX/2)`

### 技能基础值表

```python
SKILL_BASE_VALUES = {
    "会计": 5, "人类学": 1, "估价": 5, "考古学": 1,
    "魅惑": 15, "攀爬": 20, "计算机使用": 5, "信用评级": 0,
    "克苏鲁神话": 0, "乔装": 5, "闪避": "DEX/2", "汽车驾驶": 20,
    "电气维修": 10, "电子学": 1, "话术": 5, "格斗": 25,
    "枪械": 20, "急救": 30, "历史": 5, "恐吓": 15,
    "跳跃": 20, "外语": 1, "母语": "EDU", "法律": 5,
    "图书馆使用": 20, "聆听": 20, "锁匠": 1, "机械维修": 10,
    "医学": 1, "博物学": 10, "导航": 10, "神秘学": 5,
    "操作重型机械": 1, "说服": 10, "驾驶": 20, "心理学": 10,
    "精神分析": 1, "骑术": 5, "科学": 1, "妙手": 10,
    "潜行": 20, "侦查": 25, "生存": 10, "游泳": 20,
    "投掷": 20, "追踪": 10,
}
```

- `create_skill_list() -> List[Skill]` — 从基础值表生成完整技能列表
- `resolve_base_value(base: int | str, stats: Stats | None) -> int` — 处理特殊基础值（"DEX/2", "EDU"）
- `allocate_skill_points(skills, occupation_skills, occupation_points, interest_points) -> List[Skill]`
- `apply_age_modifiers(stats, skills, age)` — 40+ 年龄修正

### 信用评级表

```python
CREDIT_RATING_TABLE = {
    0: "身无分文", 5: "拮据", 10: "一般",
    20: "中等", 30: "宽裕", 50: "富裕", 70: "富有", 90: "极富",
}
```

### 战斗相关

- `create_default_unarmed() -> Weapon` — 徒手攻击 "1D3+DB"
- `create_dodge_skill() -> Skill` — 闪避技能

---

## 4. 序列化 (`src/investigator/serialization.py`)

### JSON 格式

```json
{
  "meta": {
    "version": "1.0",
    "created_at": "2026-05-09T00:00:00",
    "rules_edition": "COC7"
  },
  "personal": {
    "name": "...",
    "age": 20,
    "gender": "...",
    "occupation": "...",
    "description": "...",
    "appearance": "..."
  },
  "stats": {"STR": 65, "CON": 25, ...},
  "derived": {"HP": 7, "MP": 12, "SAN": 60, "MOV": 9, "DB": "0", "BUILD": 0, "DODGE": 30, "SAN_MAX": 99},
  "skills": [
    {"name": "图书馆使用", "base": 20, "value": 60, "category": "知识", "is_occupation": true},
    ...
  ],
  "combat": {
    "weapons": [
      {"name": "拳头", "skill_name": "格斗", "damage": "1D3+DB", "range": "接触", "ammo": 0, "malfunction": 100}
    ]
  },
  "equipment": ["手电筒", "笔记本"],
  "backstory": "..."
}
```

### API

```python
def to_json(investigator: Investigator, path: str) -> None
def from_json(path: str) -> Investigator
def to_dict(investigator: Investigator) -> dict
def from_dict(data: dict) -> Investigator
```

---

## 5. 文件结构

```
src/
  utils.py                # 已存在，新增 roll_dice() / roll_d6() 公用掷骰函数
  investigator/
    __init__.py          # 公开 API: Investigator, load_investigator, Skill, Stats, DerivedStats, Weapon
    models.py            # 数据类
    rules.py             # COC 7th 规则函数（从 utils 导入掷骰）
    serialization.py     # JSON 序列化/反序列化
  scenario_core.py       # 移除 Player 类, ScenarioWorld.set_player 接受 Investigator, 新增 load_player(path)
  game_loop.py           # 不变（world.player 兼容）
  prompts.py             # _build_player_skills 适配新接口

frontend/
  character.html          # 车卡页面（纯静态）
  character.js            # CharacterBuilder 主逻辑
  character.css           # COC 1920s 美学

data/
  occupations.json        # COC 7th 标准职业
```

---

## 6. 前端车卡

### 流程

| 步骤 | 内容 | 操作 |
|------|------|------|
| 1 | 基本信息 | 姓名、年龄、性别 |
| 2 | 属性生成 | 掷骰随机/手动输入 |
| 3 | 职业与技能 | 选职业→职业技能标记→技能点分配(职业+兴趣) |
| 4 | 战斗与装备 | 武器+随身物品 |
| 5 | 导出 | 预览+下载 JSON |

### 技术方案

- 纯静态 HTML+CSS+JS，无框架
- COC 1920s 美学（暗旧纸张色、衬线字体）
- 状态存浏览器内存，最后一步导出

---

## 7. ScenarioWorld 集成（设计级，暂不实现）

### 兼容性

- `world.player` 返回 `Investigator | None`，truthiness 行为不变
- `_build_player_skills()` 改为访问 `world.player.skills` 列表自行格式化
- `SkillSystem` 当前为桩，不需要改动

### 加载流程（未来）

```
investigator = load_investigator("character.json")
world = ScenarioWorld(graph, start_node, background)
world.set_player(investigator)
```

### 游戏中属性修改（未来，暂不实现）

- `Investigator.modify_stat(name, delta)` → 级联更新衍生属性
- `Investigator.modify_skill(name, delta)` → 技能成长标记
- `Investigator.add_item(item)` / `remove_item(item)`
- `Investigator.add_weapon(w)` / `remove_weapon(name)`
- 可选自动写回 JSON 保存

---

## 8. 不做的事

- 不实现 6 版规则
- `SkillSystem` 真实骰子鉴定逻辑保留为桩（未来任务）
- `ScenarioWorld` 集成和游戏中属性修改仅设计文档
- 不创建 CLI 交互流程（用前端替代）
