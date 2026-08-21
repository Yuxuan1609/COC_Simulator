# effect 表达力 + MP 恢复 + 库注入通路设计

> 状态：设计确认，待实现。2026-08-21 与用户对齐定稿。
> 前置已完成：统一资源层（2026-08-18 spec，14 任务全落地，commit ee699d2 + c544bc2 前端接线）。
> 定位基调：**模拟器基础设施**--素材内容（哪个法术/哪个物品）由用户与模组负责，系统保证"任何合理设计的素材都能表达且被正确执行"。法术分级/物品经济等内容体系明确不做。

---

## 0. 背景与动机

统一资源层落地后遗留三类缺口（2026-08-21 review 结论）：

1. **effect 表达力**：库 schema 的 `effect` 只支持 `damage` 一种结算（combat.py cast 分支），石肤/支配/治疗类条目写出来也空转--buff 施放成功后无任何机制后果。
2. **MP 生态断裂**：MP 零恢复途径（spec 非目标遗留），法术只能是一次性弹药，模组的法术设计建立在错误假设上。
3. **库注入通路断点**：`game_loop.init_game` 扫 `data/library/extensions/{items,spells}/*.json`，但 `run_pipeline` 两处只 `load_core()`--用户加了扩展库后游戏内能用，**模组生成管线看不见**，模组永远不会引用扩展素材。

用户设计定调：effect 尽可能做全，**对标 @markup 体系**，同时用自然语言（特殊标识符+文本描述）处理没想到的情况。

## 1. effect 原子模型（核心）

### 1.1 schema：单 dict 升维为原子数组

```json
"effect": [
  {"type": "damage", "formula": "1D6", "ignore_armor": true},
  {"type": "heal", "target": "self", "formula": "1D3"},
  {"type": "mp_change", "target": "self", "delta": 2},
  {"type": "markup", "text": "@stat_change(stat_name=\"SAN\", delta=-1)"},
  {"type": "buff", "target": "self", "reduce": 3, "rounds": 3},
  {"type": "control", "target": "enemy", "rounds": 2},
  {"type": "timed", "id": "SILENCE_VEIL", "description": "无形的帷幕吞掉帷幕内的一切声响", "minutes": 10},
  {"type": "narrative", "text": "目标将在今夜的梦中受到侵扰"}
]
```

- **兼容**：旧单 dict 格式加载时自动包装为 `[dict]`，现有库条目无需修改。
- `effect` 数组字段 **items.json / spells.json 通用**（execute_material 对两类素材统一结算）。
- `target` 仅 `"self"` / `"enemy"` 两种；探索侧无 enemy 实体，`enemy` 向原子按 §1.2 降级。

### 1.2 各原子结算语义（战斗 / 探索两侧）

| 原子 | 战斗侧（cast 分支） | 探索侧（execute_material） |
|------|--------------------|---------------------------|
| `damage` | 既有结算：formula roll + 护甲（`ignore_armor` 跳过）+ 死亡标记 | **跳过 + 日志 warning**（无伤害目标，不硬造） |
| `heal` | modify_stat HP +N（clamp 上限） | 同左 |
| `mp_change` | MP ±N（clamp 0..MP_MAX） | 同左 |
| `markup` | parse_markup_all -> apply_side_effects | 同左（与 on_use 同通路） |
| `buff` | CombatState.temporary_effects 挂 `{id, reduce, rounds}`，受击减免（下限 `buff_damage_floor`），每轮末 rounds-1 归零移除 | 降级为 narrative 进结果文本 |
| `control` | 目标 enemy 挂 `controlled_rounds=N`，敌方行动阶段跳过并出叙事，每轮末递减 | 降级为 narrative |
| `timed` | 挂 player.timed_effects（见 §2） | 同左 |
| `narrative` | 文本拼进 action.narrative + 作为 LLM 修正环节指引 | 文本进结果槽/enrich |

### 1.3 未知 type 兜底（永不空转，永不阻断）

未知 `type` 整体按 narrative 处理，text 为标识符前缀 + 原始描述：

```
[unknown:summon] 描述文本
```

- 战斗内：进 action.narrative，交既有 LLM 修正环节裁量。
- 探索侧：进结果文本，交 narrator/enrich 消化。
- 不报错、不阻断其余原子执行。

### 1.4 执行点

- **战斗侧**：`_resolve_player_action` 的 `cast_*` 分支，检定成功后遍历 effect 数组逐原子执行；`damage` 部分保持现有代码路径。
- **探索侧**：`Judge.execute_material`，check/扣减后（on_use @markup 之后）遍历执行；降级原子记 warning 不中断。

## 2. timed 时效原语（探索侧软状态）

**分工原则**：`buff`/`control` 是战斗硬机制（轮驱动，战斗结束随 state 销毁）；`timed` 是探索软状态（时钟驱动，可跨场景持续）。

### 2.1 结构与挂载

- `player.timed_effects: list[dict]`，元素 `{"id", "description", "expire_at"}`。
- `expire_at` = 挂载时刻 `clock.game_time + minutes`（绝对分钟数，GameClock.game_time 为纯整数分钟）。
- `minutes` 缺省取 `timed_default_minutes`（game_config）。

### 2.2 过期清除：advance_time 三合一钩子

`world.advance_time(minutes)`（scenario_core，探索侧所有时间推进的单一入口，keeper 每回合必经）内部完成：

1. 推时钟（现状）
2. **MP 恢复**（§4）
3. **timed_effects 过期清除**：清除时记日志，不打扰玩家叙事

### 2.3 LLM 可见性 + 序列化

- `timed_effects` 进编年史 facts 玩家行（同已知法术块模式）--> enrich/narrator/Author 写叙事时知道"帷幕还在"。
- 序列化 **v2.2**：新增 `timed_effects` 字段；v2.1/v2.0 旧档缺省 `[]`。存档恢复后 clock 同步恢复，过期逻辑照常。

## 3. 战斗临时机制（最小状态面）

- `CombatState.temporary_effects: list[dict]`：玩家侧 buff `{id, reduce, rounds}`；受击结算处总减免 = sum(reduce)，伤害下限 `buff_damage_floor`（默认 0）；每轮末 rounds-1，归零移除。
- enemy 实例挂 `controlled_rounds: int`：敌方行动阶段检查 >0 则跳过行动并出叙事；每轮末递减。
- **不进存档**：战斗结束随 CombatState 丢弃。战斗内 clock 不推进，故 timed 分钟时效在战斗中冻结（符合直觉）。

## 4. MP 恢复

- 落点：`world.advance_time` 钩子（§2.2 三合一之一）。
- 规则：`mp_recovery_per_hour`（默认 1）/小时，**带余数累计**（world 挂 `_mp_regen_accumulator` 分钟累加器，攒够 60 回 1 点，碎片时间不丢失），clamp 到 MP_MAX。
- 战斗内不恢复（不推时钟）；SAN/HP 明确不自动恢复。

## 5. 参数中心 data/game_config.json

现状核查：项目无数值参数中心（DB 查表/tier 阈值散在 rules.py 函数体，前端 SAN bar 硬编码 /99）。本期**只立中心收编新参数，不迁移旧数值**（迁移列后续优化，见 §10）：

```json
{
  "mp_recovery_per_hour": 1,
  "timed_default_minutes": 30,
  "buff_damage_floor": 0
}
```

`rules.py` 提供 `get_game_config()`：模块级缓存惰性加载 + 内置缺省兜底（文件/字段缺失不崩），测试可 reset 缓存。

## 6. 库注入通路

- 新建 `src/library/loader.py`：`load_item_library(base_dir=None)` / `load_spell_library(base_dir=None)`，统一 core + `extensions/{items,spells}/*.json` 扫描；`base_dir` 参数便于测试注入。
- 三个调用点统一改用 loader：`game_loop.init_game`（现有扫描逻辑移入）、`run_pipeline` 两处（**补上 extensions 扫描，断点修复**）。
- 管线 Step 1a 摘要 / cross_validate 用的就是 runner.ilib/slib，加载改造后扩展条目自然可见，无需单独改。
- 前端不加库路径参数，按约定目录零配置。
- 文档：readme 记约定目录（用户放 JSON 即生效）。

## 7. 内容示例升维（纯数据变更，示范新原子）

| 条目 | 变更 |
|------|------|
| 石肤术 STONE_SKIN | effect 升维数组：`buff(reduce 3, rounds 3)` + `timed(30min 描述)` |
| 支配 DOMINATE | effect 补 `control(rounds 2)` |
| 静默帷幕 SILENCE_VEIL | effect 补 `timed(10min)` |
| 心脏骤停/血之呼唤 | 保持 damage（升维数组格式对齐） |
| 《死灵书》残页 | on_use 挂 `@grant_spell(spell_ref="...")`--读书学法术通路示范 |
| 盐袋 SALT | effect 补 `timed`（民间驱邪盐线，描述性软状态） |

## 8. 测试策略

| 层 | 覆盖 |
|----|------|
| 单测 effect 原子 | 多原子遍历 / heal / mp_change / markup 透传 / buff 减伤+轮递减+下限 / control 跳过敌方行动+递减 / timed 挂载与过期 / 未知 type 降级 narrative / 旧 dict 自动升维 |
| 单测 advance_time | MP 整点恢复 / 余数累计 / clamp MP_MAX / timed 过期清除（含恰好到期） |
| 单测 timed 序列化 | v2.2 往返一致 / v2.1 旧档缺省 [] |
| 单测库注入 | loader 合并扩展 / base_dir 注入 / 游戏侧施放扩展法术 / 管线 Step 1a 摘要含扩展条目 |
| 单测 game_config | 文件缺失用缺省 / 字段缺失用缺省 / 缓存 reset |
| e2e deterministic | 静默帷幕（timed 入档+advance_time 过期）、石肤术（战斗减伤）、支配（控制敌人轮次） |
| real_llm | S15：扩展库法术游戏内施放（管线摘要可见性由单测覆盖，不跑真实管线） |

## 9. 文件变更清单

| 文件 | 类型 | 内容 |
|------|------|------|
| `src/library/loader.py` | 新建 | load_item_library / load_spell_library |
| `src/game/combat.py` | 修改 | cast 分支 effect 数组结算 + temporary_effects + controlled_rounds |
| `src/game/judge.py` | 修改 | execute_material 执行 effect 数组（含降级） |
| `src/scenario_core.py` | 修改 | advance_time 三合一；facts 渲染 timed_effects |
| `src/investigator/models.py` | 修改 | player.timed_effects 字段 |
| `src/investigator/serialization.py` | 修改 | v2.2 + 旧档兼容 |
| `src/investigator/rules.py` | 修改 | get_game_config() |
| `data/game_config.json` | 新建 | 参数中心（本期 3 参数） |
| `src/game_loop.py` / `run_pipeline.py` | 修改 | 改用 loader，补 extensions 扫描 |
| `data/library/core/spells.json` / `items.json` | 修改 | 条目升维示范（§7） |
| `tests/test_use_system.py` / `tests/e2e/test_deterministic.py` / `tests/e2e/test_scenarios.py` | 修改 | §8 各层测试 |
| `readme.md` / `MAINTENANCE.md` | 修改 | 扩展目录约定 + 同步 |

## 10. 非目标与后续优化队列

**非目标（本期不做）**：
- 敌人施法 / MP 战斗内恢复 / SAN·HP 自动恢复
- 法术分级、物品经济、稀有度等内容体系
- 物品转移（丢弃/给予 NPC）
- L2 即兴素材沉淀回库、扩展包生产流程

**后续优化队列（用户已拍板排入）**：
- **参数集中化全面收编**：DB/BUILD 查表、tier 阈值、EDU 增益表等 rules.py 函数体内数值迁移进 game_config.json；前端硬编码（SAN bar /99 等）收编
- 武器库 legacy_map 缺口统一修（手枪/步枪/霰弹枪 -> 枪械，UPDATES.md 已备注）
- 队列 3 重构；存读档 3 个 🔴 bug

## 11. 成功标准

- 石肤/支配/静默帷幕在战斗与探索两侧均有真实机制或状态后果，不再空转
- 未知 effect type 永不报错阻断，降级路径可观测（日志/叙事）
- MP 按时间恢复且余数不丢失；timed 效果过期自动清除且存档往返一致
- 扩展库三链路全通：游戏加载可用 / 施放可用（S15）/ 管线摘要可见（单测）
- 默认套件全绿（含 §8 新增）；v2.1/v2.0 旧档可加载
- MAINTENANCE.md 同步更新（按项目规则）
