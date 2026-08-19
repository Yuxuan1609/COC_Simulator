# 统一资源层与影响层级设计（U6 法术 + U8 物品 + parse 动作规范化）

> 状态：设计确认，待实现。2026-08-18 与用户对齐定稿。
> 取代：`2026-05-27-magic-system-design.md`（其 SpellJudge 顶部短路架构废弃，素材库/管线感知部分被本设计吸收）。
> 前置已完成：U2 世界编年史（2026-08-14）、U9 技能系统重修（2026-08-15，20 技能/8 属性 + 归一单点）。

---

## 0. 背景与动机

三件事一体设计：

1. **U6 法术体系**：旧 spec（2026-05-27）延期等"世界状态 + 技能重修"，两项前置现已完成；但其 SpellJudge 顶部关键词短路架构与现行分层管线（PreParse -> parse LLM -> Judge 确定性闸门 -> enrich 并行 -> Author 门控）冲突，需重设计。
2. **U8 物品系统升级**：现 ItemManager 是纯名字计数背包（无库、无使用语义、无类型机制），与武器库模式割裂。
3. **parse other 大类规范化**：other 目前一锅端所有未匹配行为，靠 IntentDetector 事后判定；升级硬门控（2a225b6）因"实体+other 混合帧"误伤 ambient 类捎带（escalation C/E 稳定被挡，见 UPDATES.md 2026-08-18 备注）。

**核心洞察（用户定调）**：法术/物品/任意素材行为，分类轴心不是素材类型，而是**影响层级**。素材类型只保留为描述性元数据。@markup 体系是全项目既有的唯一副作用执行底座（模组 Phase2 / Author patch / AT/interaction side_effects 全走它），use 的解析结果标准化编译为 @markup 即闭环。

## 1. 影响层级分类模型（核心）

玩家动作按影响层级分三档：

| 档位 | 定义 | 结算路径 | 现有承接 |
|------|------|---------|---------|
| **L0 无影响** | 不改世界与调查员状态：氛围动作、感知、信息获取 | enrich 消化进叙事，无副作用 | IntentDetector needs_author=False 路径 |
| **L1 中间档** | 有影响且**确定性**：有限通道执行，**可选检定** | Judge 确定性结算：@markup 副作用 + 描述回写 | apply_side_effects / apply_world_update |
| **L2 需裁判** | 新行为 / 库外素材 / 需创造新实体 | Author Patch/StructuralEdit -> 产物=entity -> 回落正常 interaction 结算 | IntentDetector -> _integrate_patch 通路 |

### 1.1 检定承载下沉（不强制 interaction）

- **检定能力下沉到 Judge 通用层**：素材库条目可带 `check` 元数据；use 动作命中带 check 的素材 -> Judge 直接执行 D100，复用现有全套检定设施（`check_skill` 五路归一 / tier 四级 / trait enhancement / 失败递增惩罚）。
- **结果槽轻量化**：素材条目带 `on_success` / `on_failure`（可选 `on_hard` / `on_extreme`）文本槽，按 tier 选用；缺省则纯 enrich 叙事增强。
- **interaction + graded_result 仍是一种检定承载**（模组预置四档叙事、Author 创造实体），但不是唯一路径。
- **升格走语义**：行为与场景实体语义相关（"用钥匙开这扇门"）-> parse 给 `interaction + instrument`；无对应实体 -> `use` 独立结算。判定权在 parse 语义匹配，无硬规则。

### 1.2 门控调整（flavor 豁免，解决 escalation C/E）

parse 将 other 拆为两个子类后，`_COVERED_TYPES` 混合帧门控（keeper.py，2a225b6）调整为：

- 帧内 **实体 + other_flavor** 混合 -> **不挡**（flavor 不代表玩家意图已被实体覆盖，ambient AT 捎带不再绑架升级）
- 帧内 **实体 + other_creative** 混合 -> **维持硬挡**（防递归丢帧原逻辑保留）

**细化（2026-08-18 plan 定稿）**："实体分两档"--实质性动作（interaction/event/move/search/use/NPC 对话）在场时 creative 仍硬挡（防递归丢帧）；仅氛围 auto_trigger 捎带（如 AT_AMBIENT）不算实质覆盖，creative 照常升级（escalation C/E 修复点）。flavor 永不触发 IntentDetector。

## 2. 统一资源层

### 2.1 库文件

```
data/library/core/items.json     # ItemLibrary（core + data/library/extensions/ 扩展，同武器库模式）
data/library/core/spells.json    # SpellLibrary（同上）
```

items.json 条目 schema：

```json
{
  "id": "FIRST_AID_KIT",
  "name": "急救包",
  "aliases": ["医疗包", "急救箱"],
  "category": "consumable",          // consumable / tool / document / clothing / key / misc
  "description": "帆布挎包，内有止血带与磺胺粉",
  "impact": "L1",                    // L0 / L1 / L2 默认档（库预标注）
  "use_semantic": "consume",         // consume / equip / read / tool / none
  "stackable": true,
  "check": null,                     // 或 {"skill": "急救", "type": "regular"}
  "on_use": ["@stat_change(stat_name=\"HP\", delta=1D3)"],   // 编译为 @markup 序列
  "on_success": "", "on_failure": "",
  "on_hard": "", "on_extreme": "",
  "refund_on_fail": false,           // 检定失败是否退还消耗
  "constraints": {}                  // 材料/环境等硬性条件
}
```

spells.json 条目 schema：

```json
{
  "id": "HEART_ARREST",
  "name": "心脏骤停",
  "aliases": [],
  "category": "combat",              // combat / exploration
  "description": "以目光攥住敌人的心脏",
  "impact": "L1",
  "cost": {"mp": 12, "san": 1},      // MP 消耗 / 永久 SAN 损失
  "check": {"skill": "POW", "type": "opposed"},   // regular / hard / opposed
  "on_use": [],
  "on_success": "目标的胸膛猛地一缩…", "on_failure": "某种冰冷的东西反向攥住了你…",
  "on_hard": "", "on_extreme": "",
  "refund_on_fail": false,
  "constraints": {"range": "视线内", "materials": []},
  "effect": {"type": "damage", "formula": "1D6", "ignore_armor": true},   // 仅 category=combat：伤害/效果参数，供 _roll_damage
  "weight": "light"                  // light（本期）/ heavy（远期，不做）
}
```

### 2.2 库类

`src/library/items.py` / `src/library/spells.py`，与 WeaponLibrary 同构：`load_core` + `load_extension` + `get(id_or_name)` + `search` + `list_all`。**武器库不动**，但三类库共享 loader 模式（可提取 `_load_json_dir` 小工具，不改 WeaponLibrary 公开接口）。

### 2.3 Investigator 变更

```python
class Investigator:
    known_spells: list[str] = field(default_factory=list)   # spell_id 列表，category 从库读
```

**前置修复（HP/MP/SAN 被重算覆盖）**：

- `DerivedStats` 拆 `HP_MAX` / `MP_MAX`（=CON//3 / POW//5）与当前值 `HP` / `MP` / `SAN`
- `_recalc_derived` 只重算 MAX，**当前值不被重置**，仅 clamp 到新 MAX（属性增长时当前值可同步涨，属性下降时 clamp）
- `SAN` 本期不设 MAX（COC 的 99-克苏鲁神话上限随神话技能体系另议）：初始 = POW，recalc 永不触碰 SAN 当前值，永久损失直接扣当前值
- `modify_stat("HP"/"MP"/"SAN")` 语义 = 修改当前值

### 2.4 序列化 v2.1

- `meta.version = "2.1"`；新增 `known_spells`、`hp_max/mp_max` 字段
- **v2.0 旧卡兼容加载**：known_spells 缺省 `[]`，MAX 缺省由当前值/重算补齐；仍拒绝含 SIZ 的旧卡（v1 拒载逻辑不变）

### 2.5 @grant_spell（第 8 种 @markup）

- `side_effects.py` 新增 `GrantSpell(spell_ref, category="")` dataclass；`_MARKUP_PATTERN` 加 `grant_spell`
- `scenario_core.apply_side_effects` 新增分支：查 SpellLibrary（world 持有，`init_game` 加载）-> `known_spells.append(spell_id)` -> 消息 `[获得法术] <name>`；未命中 -> warning 消息（同 @spawn_enemy 未知引用的降级模式）

## 3. UseParser 独立子系统

`src/game/use_parser.py`（新建）。use 大类拥有自己的小型 parse 系统，待解析内容可换（目录注入），结果标准化编译为 @markup。

```
UseParser.resolve(raw_input, catalogs) -> UseParseResult | None
  ├─ 确定性层（优先）：使用谓词词表（用/使用/喝/吃/施放/念诵/佩戴/阅读/敷/点燃…）
  │    + 目录条目 name/aliases 精确 -> 包含 -> difflib 模糊匹配（同 _detect_direct_pickup 模式）
  ├─ LLM 兜底层：确定性未命中但输入含使用意图 -> 轻量模糊匹配 prompt
  │    （复用 build_consume_item_fuzzy_prompt 既有模式，该函数并入本模块）
  └─ 输出：UseParseResult = {catalog_kind, material_id, name, matched_text, impact,
         check, cost, on_use, result_slots, refund_on_fail}
```

**MaterialCatalog 协议（待解析内容可换）**：

```python
class MaterialCatalog(Protocol):
    def entries(self) -> list[dict]:   # [{id, name, aliases, kind, description, impact, on_use, ...}]
        ...
```

- `ItemCatalog`：ItemLibrary ∩ 玩家背包（仅持有物可用）
- `SpellCatalog`：SpellLibrary ∩ known_spells
- 未来素材源（环境物品、装置等）实现协议即插即用

**接入点（两段式）**：

1. **pre-parse 确定性尝试**：`process_turn` 在 pre-parse 阶段先跑 UseParser（同直接拾取通路模式），命中即短路进 `Judge._execute_material`
2. **main parse 兜底**：未命中但主 parse 产出 `{"type": "use", "text": 原文}` -> UseParser LLM 层二次解析；仍未命中 -> 按 impact=creative 升 Author

主 parse prompt 只需认识"这是使用行为"（粗分类），**不塞库清单**，素材库膨胀不影响主 parse。

## 4. parse 动作类型与判定管线

### 4.1 parse 输出类型表（新增部分）

```
{"type": "other", "impact": "flavor"}                          # L0：氛围/感知，enrich 消化
{"type": "other", "impact": "creative"}                        # L2：新行为，IntentDetector/Author
{"type": "use", "text": "把急救包里的止血带拿出来用"}             # 粗识别，UseParser 细解析
{"type": "interaction", "id": "IT_LOCK", "instrument": "钥匙"}  # 物品作语义条件槽（可选字段）
```

既有类型（move/search/npc_interact/auto_trigger/interaction/event）不变。

### 4.2 impact 判定优先级

1. use 命中库素材 -> **库预标注覆写** parse 意见（单向：parse 只能升档不能降档，冲突记 warning）
2. 未命中素材的自由行为 -> parse LLM 直接分类 flavor/creative

### 4.3 requirement 扩展：`item:` 条件

- 语法：requirement 含 `item:钥匙` -> `player.items.has("钥匙")`（硬条件）
- `_evaluate_requirement` / `parse_hard_requirement` 新增分支；管线 schema 描述与 Phase2 prompt 同步
- 不满足时的提示走既有 unmet 消息通路

### 4.4 Judge._execute_material（L1 执行通道）

```
use 动作 -> Judge._execute_material(material, player_input):
  1. 硬门（确定性，不过则失败消息，不升 Author）：
     法术：spell_id in known_spells
     物品：inventory.has(name) 且数量足够
     通用：MP >= cost.mp / materials 持有 / constraints 满足
  2. 扣减（原子）：MP -= cost.mp；物品数量 -1（use_semantic=consume）；
     SAN 永久损失 = derived.SAN 当前值 -cost.san
     refund_on_fail=true 时检定失败后回滚
  3. check 存在 -> D100 检定（check_skill 归一 + trait enhancement + 失败递增）；
     opposed 类型 -> opposed_check 小函数（见 §6.2）
  4. tier -> result_slots 选用（on_extreme/on_hard/on_success/on_failure，缺省槽回退）
  5. on_use @markup 序列 -> parse_markup_all -> apply_side_effects 统一执行
  6. 产出 ActionOutcome（含 SkillCheckResult 检定记录）-> 正常 enrich->curate->narrator
```

L0 素材（如感知类法术）跳过 2/3/5，仅结果文本进 enrich。

**use_semantic 语义（本期范围）**：`consume` = 数量 -1；`read` = 走结果槽文本（文档类）；`equip` = 仅描述性装备标记（角色卡展示，无机制加成，护甲机制非目标）；`tool` = 不消耗数量，仅触发 check/on_use（如开锁工具）。

## 5. L2 Author 通路（复用，不新建）

- `other/creative` 与 use 未命中库的素材引用 -> IntentDetector -> AuthorRequest（附素材描述上下文辅助 Author 理解）
- Author Patch 产物 = entity；若带 check/graded_result 走 interaction 正常结算
- 编年史照常：record_turn 的 intent/entities 通道 + record_patch 通道
- facts 渲染补**已知法术块**（render_for_author 玩家行扩展）

## 6. 战斗法术

### 6.1 CombatSystem 集成

- `_get_player_actions`：`known_spells ∩ category=combat` 追加 `cast_<SPELL_ID>` 动作（展示为 `施法:名称`）
- `_resolve_player_action` 的 `cast_*` 分支：硬门（已知/MP）-> 扣 MP -> check（opposed 用 §6.2）-> 伤害走 `_roll_damage(effect_params.formula)` 或效果文本 -> LLM 修正照常
- 战斗内不谈 impact 分级（战斗内一切皆有影响，检定走战斗系统）

### 6.2 opposed 对抗检定小函数

```
opposed_check(attacker_skill_value, defender_skill_value) -> ("win"|"lose"|"tie", detail)
  双方各 roll D100 对各自技能值 -> 成功等级高者胜；平级比 roll 值（低者胜）；双败 = tie
```

独立纯函数，战斗/探索两侧复用，单测覆盖。

### 6.3 非目标

敌人施法不做（敌人 attacks/special_abilities 已可表达怪异能力）。

## 7. 模组生成管线感知

| 步骤 | 修改 |
|------|------|
| Step 1a | user prompt 注入 items/spells 库摘要（名称+简效，≤500 chars，同武器库模式）；输出可含 `item_refs` / `spell_refs` |
| Phase 2 | @markup 标准化列表加 `@grant_spell`；item_gain/consume_item 的物品名可与 items.json 对齐（可选校验） |
| Step 3b + cross_validate_layers | 引用校验：`@grant_spell` 的 spell_ref / item 名不在库 -> warning（不阻断） |
| requirement 描述 | schema 与 prompt 同步 `item:` 语法 |

## 8. 编年史与前端接线

- **编年史**：facts 玩家行补已知法术；use 动作经 record_turn intent/entities 通道自动入史；@grant_spell 获得事件进 entities 通道（同 @spawn_enemy 模式）
- **前端最小适配**（不深入改造，按约定前端只做跟随性适配）：
  - 角色卡：HP/MP 当前/上限展示 + 已知法术列表区
  - 战斗动作列表由后端生成，自然带出施法选项，前端无改动
  - player-status API：快照字段补 `mp_max` / `hp_max` / `known_spells`

## 9. 测试策略

### 9.1 确定性 e2e（默认套件）

| 场景 | 断言要点 |
|------|---------|
| L0 感知法术 | 无副作用，叙事含结果文本，MP 不扣 |
| L1 急救包 | 数量 -1 + HP 恢复 + ActionOutcome 副作用记录 |
| 检定素材 | check 走 check_skill，tier 选槽，失败递增（retries/escalated_difficulty） |
| MP 扣减/不足/退款 | 扣减生效；不足拒绝不扣；refund_on_fail 失败回滚 |
| 门控 flavor 豁免 | 实体+other_flavor 混合帧不挡 Author；实体+other_creative 仍挡（改造 TestEscalationGate） |
| requirement item: | 持钥匙可通过，无钥匙 unmet 提示 |
| @grant_spell | 副作用入包 + 未知道具 warning 降级 |
| 序列化 v2.1 | 往返一致；v2.0 旧卡兼容加载（known_spells 缺省 []） |
| recalc 不回满 | modify_stat CON 后 HP 当前值保留（仅 clamp） |
| opposed_check | 单测：等级胜/roll 值胜/双败 tie |
| UseParser 确定性层 | 谓词+别名+模糊命中；否定句不触发；未持有不入目录 |

### 9.2 real_llm（on-demand）

- 新增 S 场景：施法感知（L0）、使用急救包（L1）、Author 创造法术互动（L2）
- escalation C/E 回归观察：门控 flavor 豁免后应恢复通过（UPDATES.md 2026-08-14/08-18 备注收口）

### 9.3 库内容起草

items.json 约 15 条（COC 文学风格：消耗品/工具/文献/钥匙类）、spells.json 约 10 条（战斗/探索各半）由实现方起草，用户审核后定稿。

## 10. 文件变更清单

| 文件 | 类型 | 内容 |
|------|------|------|
| `data/library/core/items.json` / `spells.json` | 新建 | 核心库 |
| `src/library/items.py` / `spells.py` | 新建 | ItemLibrary / SpellLibrary |
| `src/game/use_parser.py` | 新建 | UseParser + MaterialCatalog 协议 |
| `src/investigator/models.py` | 修改 | known_spells；HP/MP max-current 拆分；recalc 保留当前值 |
| `src/investigator/serialization.py` | 修改 | v2.1 + v2.0 兼容加载 |
| `src/game/side_effects.py` | 修改 | GrantSpell + 解析 |
| `src/scenario_core.py` | 修改 | apply_side_effects 分支；requirement `item:` |
| `src/game/judge.py` | 修改 | `_execute_material` + 检定下沉 + opposed_check |
| `src/game/agents/keeper.py` | 修改 | pre-parse UseParser 接入；parse 新类型；门控 flavor 豁免 |
| `src/game/combat.py` | 修改 | cast_* 动作 |
| `src/prompts.py` | 修改 | parse prompt（use 粗识别 + other 拆分）；库摘要；模糊匹配并入 |
| `src/module_designer/layered_parser.py` / `layered_pipeline.py` / `run_pipeline.py` | 修改 | 管线感知 + 引用校验 |
| `src/scenario_core.py`（WorldChronicle） | 修改 | facts 已知法术块 |
| `src/game_loop.py` | 修改 | init_game 加载两库 |
| `frontend/`（character 卡相关） | 修改 | 最小适配 |

## 11. 非目标

- 武器并入统一物品模型（保持独立，仅接口对齐）
- 重探索法术（世界状态拼接，远期）
- 局末成长 Epilogue Judge（与 U4 跨模组持久化同域）
- 敌人施法
- MP 自然恢复机制（时间恢复，可后补 TimeAgent 钩子）
- 前端深度改造

## 12. 成功标准

- 默认套件全绿（含 §9.1 新增）
- escalation C/E 恢复通过（门控 flavor 豁免生效）
- v2.0 旧卡可加载，法术/物品使用全链路可用（pre-parse 短路 / parse 兜底 / Author 升格三路全通）
- 编年史含法术获得与 use 动作事件
- MAINTENANCE.md 同步更新（按项目规则）
