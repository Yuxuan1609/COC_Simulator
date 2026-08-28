# 库 Schema 作者参考

> 面向模组/素材作者：五库全字段 + 写法约定。字段语义以 `src/library/*.py` 的 dataclass 为唯一事实源，本文档是作者视角索引（含接线状态：✅ 已接线 / ◐ 半接（prompt 可见或部分生效）/ ✗ 未接线纯展示）。

## 1. 放置约定

- **核心库**：`data/library/core/{enemies,bosses,weapons,items,spells}.json`（随仓库分发）
- **扩展库**：与核心同 schema，后加载覆盖核心（同名条目扩展赢）
  - items / spells：放 `data/library/extensions/{items,spells}/*.json` 自动扫描（`src/library/loader.py`）
  - enemies：放 `data/library/extensions/enemies/*.json` 自动扫描（`game_loop.py` init_game）
  - bosses：放 `data/library/extensions/bosses/*.json` 自动扫描（`BossLibrary(extensions_dir=...)`）
  - weapons：有 `load_extension(path)` API，当前无自动扫描目录（只能代码调用）
- **顶层结构**：
  - enemies / weapons / items：`{"items": [条目, ...]}`（注意：键名统一是 `items`，即使是敌人/武器库）
  - spells：`{"spells": [条目, ...]}`
  - bosses：`{"<boss名>": {字段...}}`（顶层 dict 按名索引，**不是列表**）

## 2. enemies（敌人）

主键 `name`，模组 encounter 的 `enemy_ref` 引用此名。

| 字段 | 类型 | 接线 | 说明 |
|---|---|---|---|
| name | str | — | 主键 |
| type | str | ✅ | 类型标签（如 神话生物/人类），库内 search 过滤用 |
| attributes | dict | ✅ | STR/CON/SIZ/DEX/POW 等。HP=(CON+SIZ)//10；伤害 DB 由 STR/SIZ 推导；命中兜底见 attacks |
| armor | str | ✅ | 护甲描述，取字符串中**第一个数字**作护甲值（"2点厚皮"→2）；只作用敌方（玩家对敌伤害减护甲，玩家侧无护甲机制 F13-③ 非目标）；缺省 "无" |
| attacks | list | ✅ | 见下表 |
| special_abilities | list | ◐ | `[{name, desc}]`，仅名称进 Tier2 判定 prompt（`library/judgment.py`），无数值执行 |
| san_loss | str | ✅ | 多情境格式，见 §7 |
| combat_behavior | str | ✅ | 支持 `[flag]` 前缀，见 §8；剩余文本进判定/叙事 prompt |
| description | str | ◐ | 叙事展示 |
| flags | list | ✅ | 运行时 flag 集（如 `boss` 标识）；也可从 combat_behavior `[flag]` 前缀提取 |
| multi_attack | int=1 | ✅ | 每轮攻击次数 |
| damage_multipliers | dict | ✅ | `{"<伤害类型>": 倍率}`，>1 易伤 / <1 抗性 / 0 免疫；按武器 `damage_type` 匹配（combat.py `_apply_damage_multiplier`） |
| dodge_bonus | int=0 | ✅ | 加在敌人命中技能值上（与 attacks.skill_value 或兜底值相加） |
| special_rules | str | ◐ | 非空时激活战斗 LLM 逐轮修正，文本进修正 prompt，无数值执行 |
| phases | list | ✅ | `[{trigger, name, overrides, description}]`，trigger 如 `"hp_below_pct:0.5"`，overrides 覆盖字段（如 `{"multi_attack": 2}`） |
| status | str="hostile" | ✅ | 运行时状态，死亡置 `dead`（作者一般不写） |

### attacks 元素

| 字段 | 类型 | 说明 |
|---|---|---|
| name | str | 攻击名（战斗日志显示） |
| damage | dict/str | `{dice_n, dice_d, bonus, use_db}` 或字符串 `"1D6+2"`（`DB` 记入 use_db；`"/"` 后半忽略，如 "1D6/1D3" 取 1D6） |
| skill_name | str | 技能名（展示用；命中值不查玩家技能表） |
| skill_value | int | **>0 时命中技能值用此值**；否则回退 `(DEX+POW)//2`（属性缺省按 50）；两种情况都再加 `dodge_bonus` |
| weight | int=1 | 攻击选择权重（加权随机挑选） |
| notes | str | 备注 |

真实示例（`data/library/core/enemies.json` Clicker 摘录）：

```json
{
  "name": "Clicker",
  "type": "神话生物",
  "attributes": {"STR": 80, "CON": 70, "SIZ": 65, "DEX": 50, "POW": 60},
  "armor": "2点厚皮",
  "attacks": [
    {"name": "噬咬", "damage": {"dice_n": 1, "dice_d": 8, "bonus": 0, "use_db": true},
     "skill_name": "格斗", "skill_value": 50, "weight": 2, "notes": ""}
  ],
  "san_loss": "0/1D4 (目睹), 1/1D6 (被攻击)",
  "combat_behavior": "[adjacent_aware] | 优先攻击发出最大声音的目标。",
  "phases": [
    {"trigger": "hp_below_pct:0.5", "name": "狂暴",
     "overrides": {"multi_attack": 2}, "description": "受伤后陷入狂暴"}
  ]
}
```

## 3. bosses

在 enemies 字段集之上有以下**差异**（`src/library/bosses.py`）：

| 差异点 | 说明 |
|---|---|
| boss_mechanics | str，boss 专属。◐ 半接：运行时充当 combat_behavior 进判定/叙事 prompt、触发 `[Boss]` 标签与 HP 显示；数值不执行 |
| 无 combat_behavior / 无 status 字段 | 不要在 boss 条目里写这两个字段（写了也不被加载） |
| `[flag]` 前缀不做加载期剥离 | bosses 的 from_dict 无 flag 剥离逻辑；flags 直接写 `flags` 数组（惯例含 `"boss"`） |
| 顶层结构 | `{"<boss名>": {...}}`，见 §1 |

其余字段（name, type, attributes, armor, attacks, special_abilities, san_loss, description, flags, multi_attack, damage_multipliers, dodge_bonus, phases, special_rules）语义同 §2。

真实示例（`data/library/core/bosses.json` 深渊之口摘录）：

```json
{
  "深渊之口": {
    "name": "深渊之口",
    "type": "神话生物/古神残骸",
    "attributes": {"STR": 300, "CON": 500, "SIZ": 400, "DEX": 5, "POW": 200},
    "armor": "20点异界物质（常规武器无效；需封印后以仪式武器攻击）",
    "san_loss": "1D10/2D100 (目击雕像本体), 0/1D20 (每轮在雾中停留)",
    "boss_mechanics": "必须先将铜镜和玉刀夺回，在黑石祭坛逆向封印……",
    "flags": ["boss"]
  }
}
```

（注：san_loss 每轮情境组目前无触发点消费，静默——ISSUES F9/F10 跟踪。）

## 4. weapons（武器）

主键 `name`。顶层 `{"items": [...]}`。

| 字段 | 类型 | 接线 | 说明 |
|---|---|---|---|
| name | str | — | 主键 |
| skill_name | str | ✅ | 技能名，归一链：skill_config.json 新表精确 → legacy_map → 去括号重试 → 属性别名 → 伪技能 → unknown |
| damage | dict/str | ✅ | 同敌人 damage 格式（dict 或 "1D10+2"） |
| range | str | ✗ | 纯展示（距离模型 ISSUES F13-⑤ 长期 TODO） |
| shots | int=0 | ✗ | 纯展示；兼容旧名 `ammo`（弹药消耗 F13-① 长期 TODO） |
| malfunction | int=100 | ✗ | 纯展示（卡壳 F13-② 长期 TODO） |
| era | str="all" | ✅ | 时代标签（1920s 等），库内 search 过滤 |
| rarity | str="common" | ✅ | 稀有度标签，库内 search 过滤 |
| damage_type | str="物理" | ✅ | 匹配敌人 damage_multipliers 的键（如 {"火": 2.0}） |
| armor_piercing | int=0 | ✅ | 逐点抵消敌方护甲值（combat.py 玩家攻击路径） |
| attack_bonus | int=0 | ✅ | 加在玩家命中技能值上 |
| multi_attack | int=1 | ✅ | 玩家每轮攻击次数；兼容旧名 `attacks_per_round` |
| special_rules | str | ◐ | 非空激活战斗 LLM 逐轮修正，文本进修正 prompt，无数值执行 |
| description | str | ◐ | 展示 |

真实示例（`data/library/core/weapons.json` 摘录）：

```json
{"name": ".45自动手枪", "skill_name": "手枪",
 "damage": {"dice_n": 1, "dice_d": 10, "bonus": 2, "use_db": false},
 "range": "15码", "shots": 7, "malfunction": 100,
 "era": "1920s", "rarity": "common", "damage_type": "物理",
 "armor_piercing": 0, "attack_bonus": 0, "multi_attack": 1,
 "special_rules": "可连射，每追加一发-5惩罚"}
```

## 5. items（物品）

主键 `id`（缺省取 name）。匹配走 id/name/aliases 三路。顶层 `{"items": [...]}`。

| 字段 | 类型 | 接线 | 说明 |
|---|---|---|---|
| id | str | — | 主键 |
| name | str | ✅ | 匹配/展示 |
| aliases | list | ✅ | 匹配用别名 |
| category | str="misc" | ◐ | consumable/tool/document/clothing/key/misc |
| description | str | ◐ | 展示 |
| impact | str="L1" | ✅ | L0/L1/L2 默认档（L0+零消耗无检定无副作用=纯叙事短路） |
| use_semantic | str="none" | ✅ | consume/equip/read/tool/none；consume 使用时消耗一件 |
| stackable | bool=true | ✅ | 背包堆叠 |
| check | dict | ✅ | `{"skill": "...", "type": "regular\|hard\|opposed"}` 使用检定（如开锁工具→锁匠）；null=无检定保定性成功 |
| on_use | list[str] | ✅ | `@markup` 序列（如 `@stat_change(stat_name="HP", delta=1D3)`），统一副作用底座，无条件执行 |
| on_success / on_failure | str | ✅ | 检定成功/失败结果文本 |
| on_hard / on_extreme | str | ✅ | 困难/极难成功分级文本（按检定等级优先选用） |
| refund_on_fail | bool=false | ✅ | 失败回滚本次消耗（MP/SAN/消耗品） |
| constraints | dict | ◐ | 已接线：`materials`（材料持有硬门）、`opposed_value`（对抗检定对方值）；`range` 等其余键为作者提示性字段未做硬评估 |
| effect | list | ✅ | effect 原子数组，见 §9；**仅检定成功后结算** |

真实示例（`data/library/core/items.json` 摘录）：

```json
{"id": "LOCKPICKS", "name": "开锁工具", "aliases": ["撬锁工具", "锁匠工具"],
 "category": "tool", "impact": "L1", "use_semantic": "tool",
 "description": "一卷油布包着的细铁钩与张力扳手。",
 "check": {"skill": "锁匠", "type": "regular"}, "refund_on_fail": true,
 "on_success": "铁钩在锁芯里轻轻一转，锁开了。",
 "on_failure": "铁钩发出令人牙酸的声响，锁纹丝不动。"}
```

timed 原子示例（SALT 盐袋）：`"effect": [{"type": "timed", "id": "SALT_LINE", "description": "白色盐线在地上连成一道界线", "minutes": 60}]`

## 6. spells（法术）

主键 `id`（缺省取 name）。匹配走 id/name/aliases 三路。顶层 `{"spells": [...]}`。

| 字段 | 类型 | 接线 | 说明 |
|---|---|---|---|
| id | str | — | 主键 |
| name / aliases | | ✅ | 匹配/展示 |
| category | str="exploration" | ◐ | combat / exploration |
| description | str | ◐ | 展示 |
| impact | str="L1" | ✅ | L0/L1/L2 默认档 |
| cost | dict | ✅ | `{mp, san}`：MP 做前置硬门（不足不能用）+ 使用时扣减；SAN 直接扣减（无前置门） |
| check | dict | ✅ | `{"skill": "POW", "type": "regular\|hard\|opposed"}` 施放检定；null=无检定 |
| on_use | list[str] | ✅ | `@markup` 序列（如 `@grant_spell(spell_ref="...")`） |
| on_success / on_failure / on_hard / on_extreme | str | ✅ | 分级结果文本 |
| refund_on_fail | bool=false | ✅ | 失败回滚 MP/SAN 扣减 |
| constraints | dict | ◐ | 同 items（materials / opposed_value 接线，range 提示性） |
| effect | list | ✅ | effect 原子数组，见 §9；仅检定成功后结算 |
| weight | str="light" | ◐ | 重量标签 |

真实示例（`data/library/core/spells.json` 摘录）：

```json
{"id": "STONE_SKIN", "name": "石肤术", "category": "combat", "impact": "L1",
 "cost": {"mp": 6, "san": 0},
 "check": {"skill": "POW", "type": "regular"},
 "on_success": "皮肤紧绷如石。接下来的打击会轻一些。",
 "effect": [
   {"type": "buff", "target": "self", "id": "STONE_SKIN", "reduce": 3, "rounds": 3,
    "on_text": "皮肤紧绷如石，接下来的打击会轻一些。"},
   {"type": "timed", "id": "STONE_SKIN", "description": "皮肤泛着大理石般的灰色纹路", "minutes": 30}
 ]}
```

注意：法术需玩家先习得（known_spells，如经 `@grant_spell`）才能施放。

## 7. san_loss 多情境格式

格式：`"成功公式/失败公式 (情境注释), ..."`，逗号分组。解析在 `src/game/combat.py` `parse_san_loss`；空组/坏组静默跳过（不报错）。

示例：`"0/1D4 (目睹), 1/1D6 (被攻击)"`、`"1D10/2D100 (目击雕像本体), 0/1D20 (每轮在雾中停留)"`

- **目睹组**（情境注释不含 "攻击"）：开战时对每个 enemy_ref 做 SAN check 一次
  - 同场同 enemy_ref 多实例去重（群组展开后只查一次）
  - **跨场不去重**（重复遭遇重复 check）——全局首次目睹去重是 ISSUES F9 待办
  - 若所有组都含 "攻击" 注释，退回首组作目睹检定
- **被攻击组**（注释含 "攻击"）：敌方命中时 check；**当前每次命中都触发**（无首次去重，multi_attack 敌人会加速 SAN 流失——ISSUES F9 跟踪）
- **每轮情境组**（如 "每轮在雾中停留"）：目前无触发点消费，静默（ISSUES F9/F10）
- 公式：纯数字（"0"/"1"）或骰式（"1D4"/"2D100"）；检定 D100 ≤ 当前 SAN 为成功，成功掉成功式、失败掉失败式

## 8. combat_behavior [flag] 前缀

combat_behavior 文本支持 `[flag]` 前缀（可多个连续），**加载期**被剥离并转入该敌人的 flags（`src/library/enemies.py` from_dict）；前缀后的 `|` 分隔符一并清理；剩余文本进判定/叙事 prompt。

```
"[adjacent_aware] | 优先攻击发出最大声音的目标。"
→ flags += ["adjacent_aware"]，combat_behavior = "优先攻击发出最大声音的目标。"
```

注意：**bosses 库不做此剥离**（见 §3）。

## 9. effect 原子（8 类）

items / spells 的 `effect` 数组，原子 `type ∈ {heal, mp_change, markup, timed, damage, buff, control, narrative}`。

| type | 字段 | 探索侧（judge._execute_effect_atoms） | 战斗侧（combat.py cast 分支） |
|---|---|---|---|
| heal | `delta` 或 `formula` | ✅ 恢复 HP（clamp HP_MAX） | ✅ 同左 |
| mp_change | `delta` | ✅ MP 增减（clamp 0..MP_MAX，负数扣减） | ✅ 同左 |
| markup | `text`（@标记串） | ✅ 走统一副作用底座 | ✅ 需 world 注入，否则跳过+warning |
| timed | `id, description, minutes` | ✅ 挂 timed_effects（同 id 重复刷新不叠加；minutes 缺省读 game_config） | ✅ 需 world/player 注入 |
| damage | `formula, ignore_armor` | ✗ 跳过 + 日志告警（探索侧无目标） | ✅ 掷骰扣敌方 HP，ignore_armor=true 无视护甲 |
| buff | `target, id, reduce, rounds, on_text` | ◐ 降级为文本 | ✅ 进 temporary_effects，敌方伤害总减免=sum(reduce)，轮末 rounds 递减 |
| control | `target, rounds` | ◐ 降级为文本 | ✅ 写敌方 controlled_rounds，被控敌人跳过行动，轮末递减 |
| narrative | `text` | ✅ 文本进结果 | ✅ 同左 |
| 未知 type | | 降级进结果文本（`[unknown:type]` 前缀）+ 告警，不报错 | 同左 |

- effect **仅在检定成功后结算**（失败/refund 路径不结算，防退款后免费获益）
- 旧单 dict 格式自动包装为单元素数组（`_normalize_effect`），建议新数据直接写数组

## 10. 配方：锁-钥匙

**锁** = interaction entity（模组 L2 keeper 层），用技能检定实体表达：

```json
{"id": "I25", "scene": "居住区", "type": "锁匠",
 "name": "撬开侧室石质抽屉", "requirement": "",
 "trigger": "你们进入一间侧室，埃莉诺快步走向一个石质抽屉开始撬动，你可以协助。",
 "result": "##GRADED##",
 "graded_result": {
   "on_failure": "抽屉没能打开，甚至可能触发了警报。",
   "on_regular": "你撬开抽屉，里面有…… @item_gain(item_name=\"...\", quantity=1)",
   "on_hard": "……", "on_extreme": "……"
 },
 "difficulty": "regular"}
```

- `type` 填技能名（锁匠/力量/聆听等），检定成功后运行时 `mark_completed(实体id)`；失败重试会**难度递增**（regular→hard→extreme）
- `graded_result` 四档文本按骰值等级选用；文本内可嵌 `@item_gain` 等 markup

**门**（硬条件）两种写法，注意各自的作用域：

1. 出口（`from_here`/`to_here` 边）的 `requirement` 写**锁实体裸 ID**（如 `"I25"`）——parse_hard_requirement 查运行时完成态，检定通过前过不去；支持 AND/OR 组合（真实模组示例：`"I22 AND I29"`、`"I1 AND I35"`）
2. interaction 实体的 `requirement` 写 `item:具体钥匙名`（如 `"item:黄铜钥匙"`）——judge 持有检查硬门，没钥匙实体不触发（失败信息含所需物品名）

**注意**：`item:` 持有硬门只对**实体 requirement** 生效；写在**边（出口）requirement** 上的 `item:` 识别不了实体 ID 会优雅放行（不是门）。物品硬门必须落在实体上。

**物品配合**：物品库的"开锁工具"（LOCKPICKS）`check` 指向锁匠技能（skill_config legacy_map: 锁匠→偷窃），可与锁实体配合叙事。

**反模式**：requirement 写泛名 `item:钥匙` —— 持有检查按名字匹配，任意同名物品都能过实体硬门。钥匙要用具体专名（`item:黄铜钥匙`），或走锁实体 ID 硬条件。
