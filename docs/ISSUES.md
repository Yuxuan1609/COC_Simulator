# 问题与待办总账(ISSUES)

> **单一事实来源**:所有已知 bug / 功能缺口 / 重构 / 优化项集中于此。
> UPDATES.md 只保留历史工作汇总;新增问题一律进本文档,勿在别处另开清单。
> 维护约定:收口一项即从活跃区移入"已收口"节(滚动,只留近期);行号引用以最新代码为准。

---

## 0. 处置约定(优先级原则)

- **顺序**:修复类优先;**重构排倒数第二;存读档 🔴 排最后**(2026-07-31 约定)
- **范围**:当前只关注 CLI(run_game.py);前端(frontend/)暂不管,前端 bug/重构不排期除非阻塞 CLI
- **LLM flaky**:real_llm/LLM 相关测试受随机性影响时过时不过,**复跑确认即过不阻塞**;统一观察批量处理(2026-08-24 拍板)
- **模拟器定位**:素材内容(哪个法术/哪个物品)由用户与模组负责,系统只保证"任何合理设计的素材都能表达且被正确执行"——法术分级/物品经济/稀有度等内容体系明确**不做**

---

## 1. Bug

### 🔴 功能性(高,排最后修)

| # | 问题 | 细节 |
|---|------|------|
| B1 | **存读档 3 连**(队列 6) | ① EnemyManager.from_dict 无 library 静默吞异常 -> enemies 变 None;② 两条读档路径不一致(run_game 替换 world 但 judge/curator 持旧引用);③ `_npc_injected_at_ids` 不入档 -> 重复注入。注意 v2.2(timed_effects)后档格式又增字段,越晚修迁移越多 |

### 🟡 有影响(待修)

| # | 问题 | 修法/备注 |
|---|------|----------|
| B3 | **LLM 测试 flaky**(统一观察) | 见处置约定;候选措施:real_llm 套件 retry 策略或分层标记。偶发长跑(>5min)也在此类 |

### 🟢 Minor(攒一批顺手清)

| # | 问题 | 备注 |
|---|------|------|
| B6 | 战斗轮叙事把被支配跳过渲染"未命中" | 措辞不准,机制正确(combat.py 轮叙事行 + LLM 摘要喂 "--=0 D100=0" 噪声) |
| B8 | MP 恢复累计器在 MP 已满时仍被消耗 | 满 MP 休息 5 小时后花费 MP 不追回;spec 未规定,影响极小 |
| B9 | control 对快于玩家的敌人 rounds off-by-one | spec 未规定先手;文档已注明"对快于玩家的敌人 rounds 应 ≥2" |
| B10 | timed refresh 战斗侧曾无测试 | 已补(4d9a0ff);此处仅备忘 combat/judge 两处 refresh 实现需保持同步 |
| B13 | weapons/enemies/bosses 库裸 `json.load` 同类缺陷 | B7(0362eba)只修 items/spells(经 loader 的 core+extensions 通路);weapons.py:108/enemies.py:154/bosses.py:61 同款无路径报错+非 dict AttributeError,同类收编时顺修(届时抽 loader 共享 `_load_json_dict` 一次收敛) |
| B14 | load_skill_config 缓存写入死代码 | utils.py:167 if path is None 在 162 行重赋值后不可达,roll_stats 每次调用重读解析 JSON(实测 0.10s/200 次可接受);修法:拆显式 base 参数 |
| B15 | fumble 边界偏差:_roll_d100 roll>=96 无条件大失败 | COC 7th 应为 96-100 且>技能值;技能 96+ 时 roll 96-99 被误判(models.py _roll_d100)。低频,规则精度修 |

---

## 2. 功能缺口(模拟器基础设施)

| # | 缺口 | 定位 |
|---|------|------|
| F1 | **物品转移**(丢弃/给予 NPC/交易) | use 大类剩余的最后一块通路:"把钥匙递给 NPC"类叙事接不住。范围裁决时未选,按需排期 |
| F3 | timed 只进 Author prompt | enrich/narrator 经 Author 产出间接感知(架构特性,同 known_spells 通路);叙事一致性有诉求时补直连 |
| F4 | timed 缺 expire_at 渲染兜底测试 / buff 探索侧降级等边界 | 已修主体,防御分支断言零散(T8/T12 review 记录) |
| F5 | **疯狂体系**(COC 核心) | 单次 SAN 损失>=5->临时疯狂(INT 检定);当日累计>=SAN/5->总结性疯狂;恐惧症/躁狂症标记。timed_effects 基建可承载;依赖 SAN check 通路(已接通)。模组高频写法"失败则疯狂" |
| F6 | **重伤/濒死/急救** | 当前 HP 0 直接 loss+game_over(combat.py:_build_single_round_result);缺:单次伤害>=HP/2->重伤 CON 检定(失败昏迷)/HP 0 濒死(每轮-1,可急救稳定)/急救+医学技能用途。剧情依赖(被俘/被救)会卡 |
| F7 | **战斗反应与骰子表达** | 闪避自动成功(玩家 dodge->敌方下次攻击必 miss,无对抗检定,策略退化);反击 fight back 选项无;奖励骰/惩罚骰(bonus/penalty dice)无--模组文本高频;push roll(孤注一掷)无 |
| F8 | **恢复生态+mythos 增长** | HP 每日自然恢复无(多日模组卡);SAN 恢复(安全环境/心理治疗)无;克苏鲁神话增长通路无(SAN_MAX=99-神话公式与技能列表已就位,@grant_spell 有而 mythos 加值无);advance_time 钩子现成(MP 已走此路) |
| F9 | **SAN check 遭遇去重** | 当前实现(2026-08-26 接线)每场战斗对每个 enemy_ref check 一次(场内同 ref 多实例只一次);COC 规则是同恐怖源全局首次目睹才 check--需玩家 seen 集合入档。用户拍板:先接链路不去重,之后统一优化。设计注记(2026-08-26 I1 review):每轮情境组(如'0/1D20 (每轮在雾中停留)')当前无触发点消费,静默;multi_attack 敌每命中各一检,叠加不去重会加速 SAN 流失--与去重一并优化 |
| F10 | **周期性/环境效应**(表达力缺口) | timed/effect 原子只有"到期清除",无周期 tick payload;毒每轮掉 HP/雾中每轮 SAN/诅咒每日发作类模组写法无结构化通道(F9 注记"每轮在雾中停留"即此例)。钩子现成:_tick_time_effects(小时粒度,MP 恢复已走)/_tick_temporary_effects(轮末,buff 递减已走)。方向:effect 原子加 interval(round/hour/day)+payload 原子数组,8 原子体系自然延伸(2026-08-26 机制层思考) |
| F11 | **库 schema 作者参考文档** | 定位前提"素材能表达"需要作者知道怎么写;五库全字段(enemies/bosses/spells/items/weapons)+san_loss 多情境格式+combat_behavior [flag] 前缀+effect 原子+扩展库放置约定散在 readme 各节与代码。建议 docs/library-schema.md 集中(半天量级,素材生态前置) |
| F12 | **条件效果**(触发式 effect) | 敌人特殊能力(狂暴 HP<50% 攻击+1D4)无数值通道;special_abilities/boss_mechanics 半接(judgment prompt 可见,战斗数值不执行,靠 LLM 自由发挥);effect 原子无触发条件(on_hp_below/on_round 等)。等内容需求出现再结构化,先靠 boss_mechanics 文本兜底 |

## 3. 重构队列(约定:倒数第二)

| # | 项 | 备注 |
|---|---|---|
| R1 | **C1 process_turn 拆分** | 紧迫性上升:keeper.py 1701+ 行、combat.py 1410、scenario_core.py 1764,两轮大计划持续加码;加新机制前先拆 |
| R2 | 中断机制 resolver 注册表 | 2026-07-31 队列 5 |
| R3 | B5 战斗完成契约统一 | 2026-07-31 队列 5 |

## 4. 暂缓 / 远期 / 非目标备忘

| 项 | 状态 |
|----|------|
| R4 parse 稀疏实体过度匹配(IT_END 误触发) | 暂缓观察(2026-08-15 拍板,近两轮未复现) |
| 巡检层 verdict 化 | 暂缓(用户拍板) |
| 前端现栈优化(抽 JS/htmx/Alpine) | 等用户手动测试反馈后排期 |
| L2 即兴素材沉淀回库 / 扩展包生产流程 | 远期生态,有真实模组生产需求再动 |
| 敌人施法 / MP 战斗内恢复 / 局末成长 Epilogue | spec 明示非目标 |
| 擒抱/缴械/处决/连发/自动武器 | 内容型战斗选项,有真实模组需求再动(2026-08-25 规则层盘点) |
| judge 捏造证据空间(谓词外事件) | 已用谓词结果注入缓解;打磨 rubric 时注意 |

---

## 5. 已收口(滚动,只留近期)

| 日期 | 项 | 方式 |
|------|----|------|
| 2026-08-26 | **B17 `_handle_edit` 编辑回路无效 + B18 断点续跑不回灌中间状态** | d209787 `_apply_step_artifact` 回灌；本 commit `_hydrate_prior_steps` + resume_dir + launcher 校验改查 debug 中间目录 |
| 2026-08-26 | **B16 time_condition 两处静默失效** ① GameClock.time_of_day 补凌晨(hour<5)；② Judge.check_auto_triggers 兜底路径查 time_condition（list 先 dumps） | e371a33 + 本 commit |
| 2026-08-26 | 遭遇 SAN check 断链->接通（战斗开始目睹按 enemy_ref 去重 check+敌方命中"被攻击"组 check,san_loss 库数据激活,san_log 首轮渲染;跨场不去重 F9 跟踪,疯狂联动 F5 跟踪） | 50a58b7+66e79ff |
| 2026-08-25 | F2 参数集中化全面收编(rules 六函数+roll_stats 骰面+前端 SAN bar 分母+game_config 10 键/深拷贝/嵌套校验) | 75c88b7+fe9d2bb+bd96769+245234f |
| 2026-08-25 | **B11 前端 character.py 导出 version 覆写 "2.0" 与核心 v2.2 漂移** | 小修批次 Task9/F2:_build_export meta.version "2.0"->"2.2"(@275);tests/test_frontend_character.py 导出断言同步 2.2 |
| 2026-08-25 | **B12 loader 默认路径 cwd 独立性缺回归** | tests/test_library_loader.py 增 test_data_root_cwd_independent:monkeypatch.chdir(tmp_path) 后不传 base_dir 走 _DATA_ROOT 双库非空断言(锁定包相对绝对路径,防改回 cwd 相对);纯测试收口零产品代码改动 |
| 2026-08-25 | **B4 escalation_real pytest 运行无诊断现场** | test_case_a/b/c/d/e 签名加 `tmp_path=None`(pytest 注入 builtin fixture),log_dir 为空时落 `tmp_path/escalation_case_{a..e}` 子目录;手跑入口 run() 调 `test_fn(log_dir=case_dir)` log_dir 非空短路不受影响,默认参数 tmp_path=None 手跑/直接调用两形态兼容 |
| 2026-08-25 | **B5 run_step1b_test.py 裸 pytest 收集错误** | pytest.ini 加 `testpaths = tests`,裸 pytest 只收集 tests/;根目录调试脚本(模块级读已删的 data/modules/深渊之口/module_raw.txt)不再进收集范围,脚本本身保留不动(调试用途);`pytest tests/` 与 `python -m pytest` 等价免 --ignore |
| 2026-08-25 | **B7 loader 损坏扩展 JSON 报错缺文件名** | items/spells `_load_file` 裸 json.load 包 try/except:OSError/JSONDecodeError -> `ValueError` 带文件路径,另补顶层非 object 防御(数组原抛 AttributeError);core/extensions 共用入口一处覆盖两类;tests/test_library_loader.py 增 2 测试锁定 |
| 2026-08-25 | **B2 day:N time flag 随天数累积进 prompt/存档** | advance_time 注入前清旧 `day:`/`time:` 前缀 flag(推进时清理方案,旧档下次推进自动清理无需迁移);tests/e2e/test_deterministic.py TestTimeFlagHygiene 锁定(跨天/时段切换/build_snapshot 三段断言) |
| 2026-08-24 | **武器库技能名归一缺口**(手枪/步枪/霰弹枪不在 legacy_map -> STR/2 兜底 + warning 刷屏) | 4d62700:legacy_map 追加映射 + test_normalize_weapon_skill_names |
| 2026-08-24 | LLM flaky 处置约定 | UPDATES 记录:复跑即过不阻塞 |
| 2026-08-19 | escalation C/E 被挡 | 统一资源层门控 flavor 豁免收口(详见 UPDATES 2026-08-19 汇总) |
