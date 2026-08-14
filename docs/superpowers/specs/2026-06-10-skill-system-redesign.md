# 技能系统重设计方案

> 状态：修订版（2026-08-14 评估后补丁，待实施）
>
> 2026-08-14 评估结论：方向合理，主线风险在**模组串联**（模组文档由 LLM 生成、检定技能名动态注入，
> 技能名对不上时 `check_skill` 未掌握=默认成功静默放行，断裂不可观测）。本版补丁以串联可靠性为核心修订。
>
> 已拍板决策：
> 1. **legacy 归一单点下沉**到 `Investigator.get_skill()/check_skill()`（含 legacy_map、去括号、属性别名），所有调用方零改动
> 2. **旧角色卡强制重建**（45 技能旧结构的存档卡不做迁移，加载时提示重建）
> 3. **LUCK 消耗为输入声明式**（玩家输入"烧 N 点幸运/用幸运"，keeper 检定前识别扣减）
> 4. **调参为次要事项**——乘数全部入 `skill_config.json`，初始取缩乘数梯队，后续慢慢调

---

## 1. 目标

将 COC 7th 原始 46 项技能合并精简为 20 项，属性从 9 项优化为 8 项（CON+SIZ 合并），技能点分块到各属性下管控，配置文件化。

### 1.1 模组串联三层防护（核心设计约束）

模组侧技能名不可信（LLM 生成、训练数据全是旧 46 表、可能幻觉），必须三层防护：

| 层 | 位置 | 行为 |
|----|------|------|
| 生成端 | STEP2A/STEP4/supplement prompt | 注入新 20 技能表，引导 LLM 用新名 |
| 解析端 | layered_parser / supplement_pipeline | entity `type` 落库前经归一函数；归一后仍未知 → 保留原名并记 warning（不丢实体） |
| 运行时 | `Investigator.get_skill()` 单点 | legacy_map → 去括号取主名 → 属性别名 → 依次尝试；全部未命中且角色无此技能 → **记 warning 后**默认成功放行（现状容错保留，但断裂必须可观测） |

归一顺序（单点实现于 `get_skill`，`check_skill`/`get_skill_value` 自动受益）：
1. 精确命中新 20 表 → 用之
2. `legacy_map` 命中（如 话术→说服、急救→生存）→ 用之
3. 去括号取主名（如 格斗(拳)→格斗、射击(手枪)→枪械）→ 再查表
4. 属性别名命中（敏捷/力量/体质/智力/意志/教育/外貌/幸运 及 STR/CON/DEX/INT/POW/EDU/LUCK 英文名）→ 走**属性检定通路**（阈值=属性值，非技能）
5. 全部未命中 → None（调用方按未掌握处理 + warning）

> 属性检定通路顺带修复现存的静默断裂：现有模组数据已出现 `type="敏捷"`（现行 45 表无此技能，默认成功白给）。
> 「回避」作为 DODGE 派生伪技能（combat.py 已特判），不进技能表，归一函数须识别 `回避/闪避 → DODGE`。

---

## 2. 属性体系

### 2.1 属性列表（8 项）

| # | 属性 | 骰法 | 范围 | 说明 |
|---|------|------|------|------|
| STR | 力量 | 3D6×5 | 15~90 | — |
| CON | 体质 | 3D6×5 | 15~90 | 合并原 CON+SIZ |
| DEX | 敏捷 | 3D6×5 | 15~90 | — |
| APP | 外貌 | 3D6×5 | 15~90 | — |
| INT | 智力 | (2D6+6)×5 | 40~90 | — |
| POW | 意志 | 3D6×5 | 15~90 | — |
| EDU | 教育 | (2D6+6)×5 | 40~90 | — |
| LUCK | 幸运 | 3D6×5 | 15~90 | 自身即技能值，可消耗 |

> 删除：SIZ（并入 CON）、MOV（代码中未实质使用）

### 2.2 衍生属性

| 衍生属性 | 公式 | 说明 |
|---------|------|------|
| HP / HP_MAX | CON / 3 | 原来 (CON+SIZ)/10，新 CON 值域相近，➗3 保持范围 5~30 |
| MP | POW / 5 | 不变 |
| SAN | POW | 初始 SAN = POW |
| SAN_MAX | 99 - 克苏鲁神话值 | 不变 |
| DODGE | DEX / 2 | 不变 |
| DB | STR + CON/2 → 查表 | 伤害加值，表沿用 |
| BUILD | STR + CON/2 → 查表 | 体格，表沿用 |
| MOV | — | 删除 |

### 2.3 LUCK（幸运）特殊规则

- **技能值**：直接等于当前 LUCK 属性值
- **消耗（输入声明式）**：玩家输入中声明"烧 N 点幸运 / 用 N 点幸运"时，keeper 在本回合技能检定前扣减 N 点 LUCK 并给检定结果 +N（消耗后技能值同步下降；消耗至 0 不影响其他检定，但失去消耗能力）。识别位置：keeper 回合处理早期（parse 后、judge 前），从 parse 的 `skill_checks`/自由文本中匹配；未声明则不消耗，无自动兜底
- **恢复**：每模组或每个重大事件后 GM 可恢复 1D10 （具体由模组 @markup 或 GM 判定触发）

### 2.4 POW（意志）特殊规则

- POW 既是 stat 也是技能——可投 D100 对抗 POW 做意志/疯狂/法术对抗检定
- POW 不参与常规技能池分配，但其值本身即技能值
- POW 变化时 MP 联动更新（保持现有逻辑）

---

## 3. 技能体系（20 项）

### 3.1 技能列表 — 属性归属映射

| # | 技能 | 归属属性 | 基础值 | 说明（合并来源） |
|---|------|---------|:-----:|------|
| 1 | 格斗 | STR + DEX | 25 | 格斗（原） |
| 2 | 枪械 | DEX | 20 | 枪械（原） |
| 3 | 运动 | STR + CON + DEX | 20 | 攀爬 + 跳跃 + 游泳 + 投掷 |
| 4 | 潜行 | DEX | 20 | 潜行（原） |
| 5 | 偷窃 | DEX | 10 | 锁匠 + 妙手 |
| 6 | 驾驶 | DEX | 20 | 汽车驾驶 + 驾驶 + 骑术 |
| 7 | 生存 | CON + INT | 30 | 急救 + 生存 |
| 8 | 侦查 | INT + EDU | 25 | 侦查 + 追踪 + 聆听 |
| 9 | 学术 | INT + EDU | 20 | 图书馆使用 + 历史 + 博物学 |
| 10 | 心理学 | INT + EDU | 10 | 心理学 + 精神分析 |
| 11 | 科学 | EDU | 1 | 科学 + 医学 |
| 12 | 技术 | EDU | 5 | 计算机使用 + 电子学 |
| 13 | 社会科学 | EDU | 5 | 会计 + 估价 + 考古学 + 人类学 + 法律 |
| 14 | 外语 | EDU | 1 | 外语（原），母语已删除 |
| 15 | 维修 | INT + EDU | 10 | 机械维修 + 电气维修 + 操作重型机械 |
| 16 | 信用评级 | APP + EDU | 0 | 信用评级（原） |
| 17 | 说服 | APP + EDU | 15 | 说服 + 话术 + 恐吓 |
| 18 | 魅惑 | APP | 15 | 魅惑 + 乔装 |
| 19 | 神秘学 | INT + POW | 5 | 神秘学（原） |
| 20 | 克苏鲁神话 | POW | 0 | 特殊（基础=0，不参与技能点池） |

> 注：「投掷」作为合并前的旧技能，现已归入运动。如旧模块 entity 的 `type` 字段为"投掷"，运行时通过 `legacy_map` 自动映射到"运动"。
>
> ~~导航~~ 已删除。原导航相关检定归入「侦查」按具体情况判定。

### 3.2 技能-属性归属总览

```
STR  (×2): 格斗       运动
CON  (×2): 生存       运动
DEX  (×3): 潜行 偷窃 驾驶 枪械 运动 格斗
POW  (×3): 神秘学     — (克苏鲁神话=特殊，不走池)
APP  (×5): 魅惑 说服 信用评级
INT  (×5): 学术 心理学 侦查 维修 生存 神秘学
EDU  (×5): 社会科学 外语 信用评级 科学 技术 维修 学术 侦查 心理学 说服
LUCK (—): 自己（stat=skill，无池）
```

- 单属性技能：一个池，自由分配
- 多属性技能：从每个归属属性池分别获得点数，叠加到技能上
- 每技能值上限 99

### 3.3 技能点公式

每个属性的技能点池 = `属性值 × 点数乘数`（乘数全部入 `skill_config.json`，**调参为次要事项，参数化后慢慢改**）

初始乘数取缩乘数梯队（被动强的属性点数少）：

| 属性 | 初始乘数 | 被动加成 | 设计原则 |
|------|:---:|---------|---------|
| STR | ×0.5 | DB 伤害加值 | 被动强 → 点数少 |
| CON | ×0.5 | HP=CON/3 | 被动强 → 点数少 |
| DEX | ×1 | DODGE=DEX/2 | 中等被动 → 中等点数 |
| POW | ×1 | MP, SAN 初始 | 中等被动 → 中等点数 |
| APP | ×1.5 | 无 | 无被动 → 富点数 |
| INT | ×1.5 | 无 | 无被动 → 富点数 |
| EDU | ×1.5 | 无 | 无被动 → 富点数 |

> 以平均属性 60 为例，总池 ≈ 450 点（原方案 ×2~×5 时 ≈1500 点、10/21 技能触顶 99）。
> 初始值不求精确，上线后按实际体验在 config 里微调；多属性技能的多池叠加规则保留（上限 99）。

### 3.4 示例计算（按初始梯队乘数重算）

角色：全属性 60（池：STR/CON 30、DEX/POW 60、APP/INT/EDU 90）

```
STR 池: 30 → 格斗(15) + 运动(15)
CON 池: 30 → 生存(15) + 运动(15)
DEX 池: 60 → 潜行(10) + 偷窃(10) + 驾驶(10) + 枪械(10) + 运动(10) + 格斗(10)
POW 池: 60 → 神秘学(60)
APP 池: 90 → 魅惑(30) + 说服(30) + 信用评级(30)
INT 池: 90 → 学术(15) + 心理学(15) + 侦查(15) + 维修(15) + 生存(15) + 神秘学(15)
EDU 池: 90 → 科社(10) + 外语(10) + 信用(10) + 科学(10) + 技术(10) + 维修(10) + 学术(10) + 侦查(10) + 心理学(10)

最终技能值（基础+分配）:
  格斗 50 / 枪械 30 / 运动 55 / 潜行 30 / 偷窃 20 / 驾驶 30
  生存 60 / 侦查 50 / 学术 45 / 心理学 35 / 科学 11 / 技术 15
  科社 15 / 外语 11 / 维修 35 / 信用 40 / 说服 55 / 魅惑 45
  神秘学 80 / 克苏鲁 0（不走池）

触顶 99: 0/20 技能；最高为神秘学 80（POW 池集中投入的结果，可接受）
分布合理，无需进一步调参即可上线
```

---

## 4. 职业标签系统（简化版）

### 4.1 设计原则

- 原 10 职业 `occupation.json` 的方案 A（职业分类 + 上限约束）替换为方案 B（轻量标签）
- 每个标签标记 2~3 个**专精技能**，给予 **+10 固定加成**
- 不约束技能点分配方向——玩家可将点数投入任意技能
- 角色创建时只需选择一个标签

### 4.2 职业标签（初定 6 个）

| 标签 | 专精技能 | +10 加成 |
|------|---------|:------:|
| 学者 | 学术、科学、外语 | ✓ |
| 侦探 | 侦查、心理学、潜行 | ✓ |
| 医生 | 生存(含急救)、科学、心理学 | ✓ |
| 记者 | 社会科学、说服、侦查 | ✓ |
| 工程师 | 技术、维修、科学 | ✓ |
| 执法者 | 格斗、枪械、说服 | ✓ |

> 待扩展：罪犯、艺术家等可按需添加。全部放入 `data/occupation_labels.json` 配置文件。

---

## 5. 配置文件格式

### 5.1 `data/skill_config.json`（新配置文件，替代部分 `skill_checks.json` + `rules.py` 硬编码）

```jsonc
{
  "attributes": {
    "STR": { "dice": [3, 6], "multiplier": 0.5, "passive": ["DB"] },
    "CON": { "dice": [3, 6], "multiplier": 0.5, "passive": ["HP"] },
    "DEX": { "dice": [3, 6], "multiplier": 1, "passive": ["DODGE"] },
    "APP": { "dice": [3, 6], "multiplier": 1.5, "passive": [] },
    "INT": { "dice": [2, 6, 6], "multiplier": 1.5, "passive": [] },
    "POW": { "dice": [3, 6], "multiplier": 1, "passive": ["MP", "SAN"] },
    "EDU": { "dice": [2, 6, 6], "multiplier": 1.5, "passive": [] },
    "LUCK": { "dice": [3, 6], "multiplier": 0, "passive": [], "special": "self_skill" }
  },

  "derived": {
    "HP": { "formula": "CON / 3" },
    "MP": { "formula": "POW / 5" },
    "SAN": { "formula": "POW" },
    "SAN_MAX": { "formula": "99 - cthulhu_mythos" },
    "DODGE": { "formula": "DEX / 2" },
    "DB": { "formula": "table(STR + CON/2)", "table": { "0-64": "-2", "65-84": "-1", "85-124": "0", "125-164": "+1D4", "165-204": "+1D6", "205+": "+2D6" } },
    "BUILD": { "formula": "table(STR + CON/2)", "table": { "0-64": "-2", "65-84": "-1", "85-124": "0", "125-164": "1", "165-204": "2", "205+": "3" } }
  },

  "skills": [
    { "name": "格斗",   "attr": ["STR", "DEX"],       "base": 25 },
    { "name": "枪械",   "attr": ["DEX"],               "base": 20 },
    { "name": "运动",   "attr": ["STR", "CON", "DEX"], "base": 20 },
    { "name": "潜行",   "attr": ["DEX"],               "base": 20 },
    { "name": "偷窃",   "attr": ["DEX"],               "base": 10 },
    { "name": "驾驶",   "attr": ["DEX"],               "base": 20 },
    { "name": "生存",   "attr": ["CON", "INT"],        "base": 30 },
    { "name": "侦查",   "attr": ["INT", "EDU"],        "base": 25 },
    { "name": "学术",   "attr": ["INT", "EDU"],        "base": 20 },
    { "name": "心理学", "attr": ["INT", "EDU"],        "base": 10 },
    { "name": "科学",   "attr": ["EDU"],               "base": 1 },
    { "name": "技术",   "attr": ["EDU"],               "base": 5 },
    { "name": "社会科学","attr": ["EDU"],              "base": 5 },
    { "name": "外语",   "attr": ["EDU"],               "base": 1 },
    { "name": "维修",   "attr": ["INT", "EDU"],        "base": 10 },
    { "name": "信用评级","attr": ["APP", "EDU"],       "base": 0 },
    { "name": "说服",   "attr": ["APP", "EDU"],        "base": 15 },
    { "name": "魅惑",   "attr": ["APP"],               "base": 15 },
    { "name": "神秘学", "attr": ["INT", "POW"],        "base": 5 },
    { "name": "克苏鲁神话","attr": ["POW"],            "base": 0, "special": "no_pool" }
  ],

  "legacy_map": {
    "会计": "社会科学", "估价": "社会科学", "考古学": "社会科学",
    "人类学": "社会科学", "法律": "社会科学",
    "攀爬": "运动", "跳跃": "运动", "游泳": "运动", "投掷": "运动",
    "汽车驾驶": "驾驶", "驾驶": "驾驶", "骑术": "驾驶",
    "机械维修": "维修", "电气维修": "维修", "操作重型机械": "维修",
    "魅惑": "魅惑", "乔装": "魅惑",
    "说服": "说服", "话术": "说服", "恐吓": "说服",
    "锁匠": "偷窃", "妙手": "偷窃",
    "急救": "生存", "生存": "生存",
    "侦查": "侦查", "追踪": "侦查", "聆听": "侦查",
    "图书馆使用": "学术", "历史": "学术", "博物学": "学术",
    "心理学": "心理学", "精神分析": "心理学",
    "科学": "科学", "医学": "科学",
    "计算机使用": "技术", "电子学": "技术",
    "格斗": "格斗", "枪械": "枪械", "射击": "枪械",
    "神秘学": "神秘学", "外语": "外语",
    "克苏鲁神话": "克苏鲁神话", "信用评级": "信用评级",
    "导航": "侦查",
    "母语": null
  },

  "attr_aliases": {
    "力量": "STR", "体质": "CON", "敏捷": "DEX", "外貌": "APP",
    "智力": "INT", "灵感": "INT", "意志": "POW", "教育": "EDU",
    "幸运": "LUCK",
    "STR": "STR", "CON": "CON", "DEX": "DEX", "APP": "APP",
    "INT": "INT", "POW": "POW", "EDU": "EDU", "LUCK": "LUCK",
    "SIZ": "CON"
  },

  "pseudo_skills": {
    "回避": "DODGE", "闪避": "DODGE"
  }
}
```

### 5.2 `data/occupation_labels.json`（新）

```jsonc
[
  { "name": "学者",   "focus": ["学术", "科学", "外语"],     "bonus": 10 },
  { "name": "侦探",   "focus": ["侦查", "心理学", "潜行"],   "bonus": 10 },
  { "name": "医生",   "focus": ["生存", "科学", "心理学"],   "bonus": 10 },
  { "name": "记者",   "focus": ["社会科学", "说服", "侦查"], "bonus": 10 },
  { "name": "工程师", "focus": ["技术", "维修", "科学"],     "bonus": 10 },
  { "name": "执法者", "focus": ["格斗", "枪械", "说服"],     "bonus": 10 },
  { "name": "自定义", "focus": [],                            "bonus": 0 }
]
```

---

## 6. 影响范围

### 6.1 需要修改的文件

| 文件 | 改动 |
|------|------|
| `data/skill_config.json` | **新建**，技能/属性/legacy_map/attr_aliases/pseudo_skills 配置 |
| `data/occupation_labels.json` | **新建**，职业标签定义 |
| `data/skill_checks.json` | 更新为新 20 项技能定义（或删除，由 config.json 替代） |
| `data/occupations.json` | 删除旧职业定义（被 `occupation_labels.json` 替代） |
| `src/investigator/models.py` | `Stats` 删 SIZ；新增 LUCK 消耗方法；技能模型适配 `attr` 多属性；**`get_skill()` 单点归一**（legacy_map → 去括号 → 属性别名 → 伪技能）；未掌握放行时记 warning；新增属性检定通路（阈值=属性值） |
| `src/investigator/rules.py` | 删 `SKILL_BASE_VALUES`/`SKILL_CATEGORIES` 硬编码；重写 `roll_stats()`、`calc_derived()`、`create_skill_list()`、`allocate_skill_points()`（乘数从 config 读） |
| `src/investigator/serialization.py` | `to_dict`/`from_dict` 适配新 Stats+Skills 结构；**加载到旧 45 技能结构卡 → 拒绝加载并提示重建**（强制重建，不做迁移） |
| `src/utils.py` | `load_skill_checks()`→从 config 加载；`get_coc_skill_names()` 返回新 20 项；新增 `normalize_skill_name()` 归一函数（供 models/parser 共用） |
| `src/game/agents/keeper.py` | standoff 说服类硬编码集合 `("魅惑","说服","话术","恐吓")` → 归一后判断（`normalize(name)=="说服" or "魅惑"`）；内置搜索"侦查"不变；LUCK 声明式消耗识别（parse 后、judge 前） |
| `src/game/judge.py` | 无大改——`entity.type` 照旧传入 `check_skill()`，归一在单点自动生效 |
| `src/game/combat.py` | 旧技能引用（格斗/枪械）不变；"回避"伪技能约定沿用（经 pseudo_skills 归一）；HP/DODGE 公式适配 |
| `src/module_designer/layered_parser.py` | STEP2A/STEP4 的 `skill_names` 从 config 拉取新列表；`stat_names` 删 SIZ；**entity `type` 落库前经 `normalize_skill_name()`，未知名保留+warning** |
| `src/module_designer/layered_pipeline.py` | 技能名/属性名加载适配 |
| `src/prompts.py` | `build_standoff_match_prompt()` 技能列表更新 |
| `src/module_designer/supplement_pipeline.py` | 技能列表更新；补充实体落库前同样归一+warning |
| `frontend/routers/character.py` | `SKILLS` 列表 + `STATS` 列表更新；技能点分配 UI 改为按属性分块 |
| `frontend/routers/game.py` | 调查员面板属性/技能展示更新 |
| `frontend/templates/` (多个) | 角色创建 UI 改版（按属性分块显示技能 + 点数）、战斗 UI 技能引用更新 |

### 6.2 不受影响的部分

- **D100 检定机制** (`check_skill()`)：逻辑不变，仅 skill_name 变
- **LLM 对话/叙事**：prompt 中 skill_names 替换为新列表，LLM 无需感知映射
- **@markup 管线**：Phase 2 `@stat_change` 的 `stat_names` 更新（删 SIZ），`type` 字段映射通过 `legacy_map` 处理
- **武器/敌人数据库**：`skill_name` 字段如有旧名（如"格斗(拳)"），通过映射表归一
- **战斗系统**：格斗/枪械保留原名，基本不受影响

---

## 7. 旧数据兼容

### 7.1 旧模组：技能名归一

管线生成的旧模块 JSON 中 entity 的 `type` 字段可能含旧技能名（如"投掷""话术""急救"）。运行时在 `get_skill()` 单点经 `legacy_map` 自动归一（见 1.1 三层防护）：

- 带括号特化名（如"格斗(拳)""射击(手枪)"）：去括号取主名后再映射
- 属性名/中文别名（如"敏捷""意志"）：走属性检定通路（`attr_aliases`）
- "回避/闪避"：伪技能通路 → DODGE 派生值（`pseudo_skills`）
- 归一后仍未知名：保留原名，记 warning，按未掌握默认成功放行（容错保留，断裂可观测）

> 现有模组实测：data/modules 全部 entity type（侦查/话术/神秘学/潜行/聆听/投掷/急救/考古学/医学/计算机使用/精神分析/历史/妙手/锁匠/跳跃/导航/图书馆使用 等）均可归一；唯"敏捷"需属性通路（现行版本即静默白给，本方案顺带修复）。

### 7.2 旧模组：属性映射

旧模块 `@stat_change` 含 `SIZ` → 映射到 `CON`。旧模块 JSON 中如有 `SIZ` 引用 → 静默转 `CON`。

### 7.3 旧角色卡：强制重建

已存 45 技能结构的调查员卡（`data/investigator/*.json`）**不做迁移**：`from_dict` 检测到旧结构（含已删除技能名/SIZ 字段）时拒绝加载并明确提示"请按新技能体系重建角色"。

理由：技能合并的聚合规则（多旧技能→一新技能如何取值）无解且语义不公允；重建成本低于维护一套有歧义的迁移逻辑。测试用卡（如 `combat_test_character.json`）按新体系重新生成。

---

## 8. 实施步骤（概要）

1. 创建 `data/skill_config.json`（技能/属性/legacy_map/attr_aliases/pseudo_skills，乘数取初始梯队）
2. `utils.py`：新增 `normalize_skill_name()` 归一函数 + config 加载
3. 重写 `models.py`：删 `SIZ`、`get_skill()` 单点归一、属性检定通路、LUCK 消耗方法、未掌握 warning
4. 重写 `rules.py`：新的 `roll_stats()`/`calc_derived()`/`allocate_skill_points()`
5. 适配 `serialization.py`（新结构 + 旧卡拒绝加载）
6. `judge.py`/`combat.py`/`keeper.py`：公式适配、standoff 硬编码集合归一化、LUCK 声明消耗识别
7. 管线：`skill_names`/`stat_names` 替换 + parser/supplement 落库归一+warning
8. 前端：角色创建 UI 改版 + 战斗/面板技能名更新（最小适配先行，完整改版可后置）
9. 创建 `occupation_labels.json`，删除 `occupations.json`
10. 测试：三层 E2E 回归网（86 骨架 + 实连 + 场景层）全绿；新增归一函数单测（旧名/括号名/属性名/未知名四路）；旧模组（深渊第七城/常暗之厢）实跑冒烟
