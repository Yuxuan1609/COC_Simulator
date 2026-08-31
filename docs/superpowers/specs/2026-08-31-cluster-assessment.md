# 簇 → 架构需求评估文档（Step3 范围决策稿）

> 2026-08-31。来源：路线图 spec（2026-08-26-remaining-issues-roadmap-design.md）§2.44 要求的 Step2 收尾产物。
> 方法：六簇逐点过内容 × 现有架构交叉评估（2026-08-31 六路代码探索），每点给 **做/缓/非目标** 倾向 + 难度定级 + 数据模型改动 + 依赖；末章给跨簇多步骤方案。
> 本文档是**讨论基础稿**，非最终拍板；逐簇确认后才开工。行号以 2026-08-31 HEAD 为准。

## 0. 两个跨簇隐藏前置（影响全局，先行处理）

### P0-1 `check_skill` difficulty 死参数（用户已拍板：必修）

- 事实：`Investigator.check_skill(skill_name, difficulty="regular")`（models.py:227）接受 difficulty 但函数体完全不用；`_roll_d100`（models.py:251）永远按满值判定。`judge.py:350` 与 `judge.py:150` 都在传 hard/escalated，**全无效**；失败递增 `runtime_state.escalated_difficulty`（judge.py:391-404）写了状态但骰子不认。唯一实现 difficulty 的 `JudgmentEngine.tier1_skill_check`（library/judgment.py:40-54）是死代码。
- 影响面：修复后所有 hard/extreme 检定真正变难 = **全局判定平衡变化**；escalated_difficulty 从无效变有效。
- 范围：`_roll_d100` 按 difficulty 调目标值（hard=半数/extreme=1/5，COC7）+ 全量测试重基线 + real_llm_smoke。
- 同时是 F7（对抗/奖惩骰语义）、F19（环境修正通道）的前置。

### P0-2 scenario-end 钩子缺失

- 事实：`run_game.py:205` 结局 break 后无任何钩子；战斗败北 break（:180-183）同；`llm_player.py:435` 同。无结算/成长/自动存档点。
- 影响面：U4 幕末成长、结局结算叙事的公共挂点。
- 范围：`game_loop` 或 run_game/llm_player 双挂点加 `on_scenario_end(game)` 回调骨架（默认空实现）。

## 1. A 簇 — COC 核心规则

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| F8 恢复生态 | 做 | **低** | 无新结构；config 加恢复速率项 | `advance_time`→`_tick_time_effects`（scenario_core.py:771-801）钩子现成，MP 恢复是现成模板；日界检测自行比较 advance 前后 day。HP 日恢复 + SAN 恢复（安全环境/时段）挂同处。mythos 增长：`modify_skill`（models.py:414）+ `calc_derived` SAN_MAX=99-神话（rules.py:57）现成，**缺触发点设计**（何时涨？模组事件？SAN 损失联动？——待讨论） |
| F5 疯狂体系 | 做 | 中 | 玩家增疯狂状态字段（临时/总结性 + 恐惧症/躁狂症标记），入档 | 挂点已留：`_san_check_and_lose`（combat.py:155-157）单次损失≥5 已有 log 并明示 F5 未实现；当日累计需 per-day SAN 计数器（`san_seen_sources` 是 world 级可入档集合的先例，scenario_core.py:702）。**讨论点**：疯狂的表现层做到哪——仅状态标记+prompt 注入让 LLM 演绎，还是行为控制（强制行动表）？后者难度跳升 |
| F6 重伤/濒死/急救 | 做 | 中高 | 玩家 HP 状态机（正常/重伤/濒死/昏迷），入档 | 伤害入口单点（`_resolve_enemy_action` combat.py:1225-1228）易挂；但 HP0→game_over 判定（combat.py:612-614）+ 三处写回通路（game_loop.py:798-815 / :725-838 / frontend game.py:1064）都要改。昏迷=玩家失能，需战斗内新状态 + 急救动作（战斗内/外两形态）。**讨论点**：濒死期玩家能做什么（仅等待救援？）；Boss 战现不 game_over 的特例如何交互 |
| F7 战斗反应与骰子 | 做 | **高** | 无新持久结构；combat 回合结构改动 | 奖惩骰：D100 层加函数即可（低）；闪避对抗化挂点精确（combat.py:1204-1208 现为消费 `_player_dodging` 直接 miss），`opposed_check`（rules.py:267-280）现成；**但敌方回合插玩家反应 = 中断机制**（ISSUES R2 resolver 注册表的天然应用场景），CLI `run_combat` 全自动循环（combat.py:234）要开决策点；反击同理。push roll：探索侧 escalated_difficulty 是近似物，战斗侧全新。**建议与 R2 合并立项**。讨论点：CLI 交互形态（每敌击问一次？预设策略？） |

簇内排序建议：F8 → F5 → F6 → F7（F7 结构最重，最后）。

## 2. B 簇 — 世界物品交互

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| F23 实体可重复策略 | 做 | 中 | Entity 增 repeatable 策略位；schema + 管线 + prompt 同步 | one-shot 硬挡单点（judge.py:271-276），加策略位后「重读文件/复查现场」解锁。讨论点：策略取值集（once / repeatable / repeatable_with_diminishing？）；完成后 prompt 呈现（prompts.py:356-370 已完成段）同步 |
| F1 物品转移 | 做（最小版） | 中 | markup 加 `@give_item`/`@drop_item`；最小版 NPC 不持物（给予=从玩家扣+叙事确认） | NPC 无 inventory 字段（npc_manager.py:10-30）；最小版丢弃入场景依赖 F17 的场景物品容器。真「NPC 持物/还回」需 NPC inventory = 另一个台阶。**依赖 F17 或降级为纯叙事** |
| F17 场景物品/容器 | 做 | 中高 | 泛化 `scene_weapons` → `scene_items`；拾取链路泛化；容器嵌套另议 | scene_weapons 端到端已通（声明 l2_keeper.py:47 → 运行时 scenario_core.py:697 → 发现 adjudicate.py:141-150 → offer understand.py:19-33 → 授予 keeper.py:470-486），但**全链绑 weapon_library**（understand.py:35-40 直接拾取、offer 应答都只认武器）。泛化到任意物品需 LibraryItem 介入（无库物品放场景？自由文本物品？）。容器嵌套建议**缓**，先做平面场景物品 |
| F21 组合/耐久 | **缓** | 中 | LibraryItem 加耐久/配方；InventoryItem 加字段 | materials 只检持有不扣（judge.py:105-107）；无真实模组需求驱动，等内容需求出现再做 |
| F15 金钱 | **缓** | 中 | 从零概念 | 信用评级只产文字标签（models.py:61-62）；无真实模组需求 |

簇内排序建议：F23 → F17（平面）→ F1（搭 F17）。F17 是本簇结构重心。

## 3. C 簇 — NPC 系统

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| F27 NPC 度量层 | 做（先行） | 中 | NPC 加 favorability/mood 数值字段，入档；`set_attitude` 接线或重写 | `set_attitude`（npc_manager.py:244）/`process_npc_turn`（:315）确认死代码（全 src 零调用，现行对话走 understand.py:117-163 内联路径）。attitude 现是自由字符串唯一消费在 talk_to prompt（:223）。**U1 前置**。讨论点：度量维度集（好感单轴？+瞬态情绪？）；检定/事件如何改度量 |
| F29 死亡剧情连锁 | 做 | 中 | 无新结构；死亡钩子广播 | `set_state` 单点（scenario_core.py:1390），目击者反应可走现有 AT/事件系统触发。讨论点：连锁的载体（自动事件 vs keeper 检测注入） |
| F20 探索侧潜行/躲藏 | 做 | 中 | 玩家/场景隐蔽状态位 | 潜行现在只在对峙（keeper.py:275-302）与战斗 conceal（combat.py:1054-1066）。探索侧需 understand 识别潜行意图 → 检定 → 隐蔽态影响后续遭遇判定（EncounterProvider 可读）。讨论点：隐蔽态的消费点范围（只影响遭遇？还是也影响 AT/NPC 感知） |
| F28 友方 NPC 参战 | 做（最后） | **最高** | combat 玩家侧多方化：CombatState 标量→列表 | 单数假设遍布：`state.player_hp/player_san` 标量（combat.py:191-194）、initiative 固定 `"player"` id、`_select_enemy_target` 硬编码 return "player"（:1165）、`CombatInit.player` 单对象。等于战斗引擎半重写。EncounterProvider 只解决进场不解决战斗内。建议 P4 单独立项 |
| F26 谎言/欺骗 | **缓** | 高 | memory 加真伪标记 + NPC 事实校验 | 玩家陈述无条件写入 npc.memory（npc_manager.py:237）且 system prompt 明示"如实告知"（:227）。依赖 F27 度量层落地后再评估 |

簇内排序建议：F27 → F29 → F20 →（F26 观察）→ F28（P4）。

## 4. D 簇 — 时间与环境

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| F18 时刻事件触发 | 做（**降级版**，用户已拍板） | 中低 | world 增 scheduled_events 队列（时刻→实体/事件），入档 | 用户确认：玩家不动时间不走 OK（原地休息已支持），**不需要主动推时间**。降级为：advance_time 跨越时刻点时触发（crossing 检测挂在 scenario_core.py:755-769）。不需要 idle 推进，调度器大幅简化 |
| F10 周期性/环境效应 | 做 | 中 | timed_effects 加 interval + payload 原子数组 | 现在 `{id, description, expire_at}` 纯展示（models.py:201），到期只删（scenario_core.py:794-801）；战斗侧 `_tick_temporary_effects`（combat.py:1246-1255）只递减 counter 无 payload。双侧 executor（judge.py:193-252 / combat.py:954-1024）需同步扩。8 原子体系自然延伸 |
| F19 环境状态进检定 | 做 | 中 | 场景环境字段（光照/天气/噪音）+ 检定修正通道 | **前置 P0-1**（difficulty 死参数修复后才存在可用的修正通道）。之后环境 → 难度/奖惩骰映射。讨论点：环境字段挂 L1 还是 L2；修正幅度表 |

簇内排序建议：F18（降级后最轻）→ F10 → F19（等 P0-1）。

## 5. E 簇 — 叙事与成长

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| U4 幕末成长检定 | 做 | **低** | 无新结构（checked 已落入档） | COC7：roll > skill → +1d10；`modify_skill` 现成。**前置 P0-2**（end 钩子）。注意 attr/pseudo 检定不标 checked（models.py:236-240）——幕末只处理 Skill 列表 |
| F25 Narrator 长期记忆 | 做 | 低-中 | 消费 `narrative_memory` 占位；Chronicle 压缩接线 | WorldChronicle/MemoryManager 已入档且 narrator 完全不消费（build_narrator_prompt prompts.py:603-658 只收 brief+snapshot）。`chronicle.events_summary` 字段预留但 `compress_events` raise NotImplementedError（scenario_core.py:1666-1668）——压缩策略是实现主体。改 narrator prompt → 触发 real_llm_smoke。讨论点：注入哪份（memory.get_context vs chronicle 蒸馏）、token 预算 |
| F22 线索系统结构化 | 做 | 中 | 消费 `clues` 占位：线索实体 + 关联边 + 集齐判定 | note_item 现只 append flat 字符串（scenario_core.py:1470-1472）。结构全新但纯数据+消费端（prompt/模组判定）。讨论点：集齐判定的执行者（keeper 机械判定 vs Author LLM）；与 key_items 的迁移关系 |

簇内排序建议：U4 → F25 → F22。

## 6. F 簇 — 模组工具链

| 项 | 倾向 | 难度 | 数据模型改动 | 依据 / 讨论点 |
|---|---|---|---|---|
| F31 模组体检 lint | 做 | 中 | 无（工具层） | validate_* 引擎可复用（layered_schema.py:226-264）；补：entity id 唯一性/引用存在性（现 cross_validate 只查 5 类，layered_pipeline.py:97-219）/DependencyGraph 可达性（现只有 detect_cycles，dependency_graph.py:70-100）/孤立场景/难度分布。需新建 CLI（module_designer 无 __main__）。与游戏代码零耦合，可任意穿插 |
| F32 试玩报告/难度标定 | 做 | 中 | 无（聚合层） | mech 行已含 entity/tier/location/ending 原始数据（llm_player.py:138-222）；turns_detail 全量在 _summary.json。加聚合统计层（场景覆盖率/结局触达/检定难度分布），谓词注册表（scenario_predicates.py）可复用模式。多次试玩汇总是另一个台阶 |
| F33 手写模组支持 | **缓** | 高 | — | editor/validate 仅 JSON 语法（editor.py:87-102），接 validate_all 是小事，但手写工作流=前端主战场，等前端排期 |
| F34 版本管理/增量再生 | **缓** | 高 | manifest/快照从零 | 保存直接覆写（run_pipeline.py:1285-1293），无手写检测。等真实痛点 |
| F35 分歧/结局可视化 | **缓** | 高 | — | 全新组件+前端依赖，等前端排期 |

簇内排序建议：F31 → F32，可穿插在任何簇之间。

## 7. 跨簇多步骤方案（按难度 × 依赖混排，替代按簇滚动）

> 相对 roadmap §2 的「六簇滚动」是**排序逻辑的修订**：同一批内顺序可换，批间有依赖（P0 解锁后面）。

```
S3-P0 隐藏前置批
  1. difficulty 死参数修复 + 测试重基线（用户已拍板必修）
     ⚠ 全局判定平衡变化；需 real_llm_smoke + 观察 e2e 难度敏感场景
  2. scenario-end 钩子骨架（on_scenario_end 双挂点）

S3-P1 快赢批（低难度，各自独立收口）
  3. F8 恢复生态（HP 日恢复 / SAN 恢复 / mythos 触发点）
  4. U4 幕末成长检定（消费 checked）
  5. F25 narrator 长期记忆注入（改 narrator prompt → real_llm_smoke）

S3-P2 中项批（顺序可换；F31/F32 与游戏零耦合可穿插）
  6. F5 疯狂体系
  7. F23 实体可重复策略 + F1 最小转移
  8. F18 时刻事件触发（降级版）+ F10 周期效应
  9. F27 NPC 度量层 + F29 死亡连锁
 10. F31 lint / F32 试玩报告

S3-P3 结构项（建议各自独立 spec/plan）
 11. F17 场景物品泛化（B 簇重心）
 12. F19 环境修正（P0-1 已铺路）
 13. F6 重伤/濒死状态机
 14. F7 战斗反应 + R2 中断机制（合并立项）
 15. F20 探索潜行 + F22 线索结构

S3-P4 大改
 16. F28 友方 NPC 参战（combat 多方化）
```

维持缓：F15 / F21 / F26 / F33 / F34 / F35（同步回 ISSUES 活跃区标注）。

## 8. 待讨论问题清单（细化讨论用）

1. **F8 mythos 增长触发点**：模组事件驱动 vs SAN 损失联动 vs 阅读典籍类 interaction？
2. **F5 疯狂表现层深度**：状态标记+LLM 演绎（轻）vs 行为控制（重）？恐惧症/躁狂症是内容库还是自由文本？
3. **F6 濒死交互形态**：濒死期玩家能做什么；NPC 救援如何表达（依赖 F27/F28？）
4. **F7/R2 CLI 交互形态**：敌方每击问一次 vs 预设反应策略；前端域不在范围，CLI 先行是否可接受
5. **F23 策略取值集**：once / repeatable / 是否需要 diminishing 档
6. **F17 无库自由文本物品能否放场景**；容器嵌套是否正式缓
7. **F27 度量维度**：好感单轴 + 瞬态情绪？检定/事件改度量的规则
8. **F29 连锁载体**：自动事件系统 vs keeper 检测注入
9. **F20 隐蔽态消费范围**：只影响遭遇判定，还是也影响 AT/NPC 感知
10. **F22 集齐判定执行者**：keeper 机械判定 vs Author LLM；与 MemoryManager.key_items 的迁移关系
11. **F25 记忆注入源与 token 预算**：memory.get_context() vs chronicle 蒸馏；压缩阈值
12. **F19 环境字段挂 L1 还是 L2**；修正幅度表
13. **F32 单次报告 vs 多次试玩汇总**的范围切分
14. **U4 幕末成长范围**：只成长 checked 技能？失败检定（COC7 不成长）；attr 类不处理确认
15. **P0-1 平衡影响**：修复后既有模组的难度实体是否需要普查一遍 difficulty 标注

## 9. 既有架构资产清单（避免重复设计）

| 资产 | 位置 | 可复用于 |
|---|---|---|
| `opposed_check(att, def)` | rules.py:267-280 | F7 闪避对抗/反击（现仅法术 opposed 用） |
| `_tick_time_effects` + MP 恢复模板 | scenario_core.py:771-801 | F8 恢复 / F10 周期 tick |
| `san_seen_sources` 入档集合模式 | scenario_core.py:702 | F5 当日累计计数器 |
| `_san_check_and_lose` + F5 log 挂点 | combat.py:147-161 | F5 阈值检测 |
| `EncounterProvider` Protocol 链 | turn/encounter.py:23-24, 210 | F20 隐蔽态消费 / F28 进场 / 未来遭遇扩展 |
| escalated_difficulty 递增态 | judge.py:391-404 | F7 push roll（P0-1 修复后真正生效） |
| `Skill.checked` + 序列化 | models.py:48, serialization.py:75/148 | U4 幕末成长 |
| `clues`/`narrative_memory` 占位（v2 入档） | scenario_core.py:703-704/1146/1177 | F22 / F25 |
| `chronicle.events_summary` 预留字段 | scenario_core.py:1666-1668 | F25 蒸馏（现为 NotImplementedError） |
| mech 机制事件时间线 | llm_player.py:138-222 | F32 难度分布/覆盖率原始数据 |
| validate_* 引擎 + SchemaReport | layered_schema.py:226-264 | F31 lint 新检查层 |
| `item:名字` / `flag:` 硬条件 | judge.py:523-541 | F23 / F1 门控 |
| additive-default 存档约定 | unified-save spec §2 | 全部新入档字段遵守 |
