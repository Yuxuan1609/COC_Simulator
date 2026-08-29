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

（无）

### 🟡 有影响(待修)

| # | 问题 | 修法/备注 |
|---|------|----------|
| B3 | **LLM 测试 flaky**(统一观察) | 见处置约定;候选措施:real_llm 套件 retry 策略或分层标记。偶发长跑(>5min)也在此类 |

### 🟢 Minor(攒一批顺手清)

| # | 问题 | 备注 |
|---|------|------|
| B9 | control 对快于玩家的敌人 rounds off-by-one | spec 未规定先手;文档已注明"对快于玩家的敌人 rounds 应 ≥2"（阶段 0 跳过） |
| B10 | timed refresh 战斗侧曾无测试 | 已补(4d9a0ff);此处仅备忘 combat/judge 两处 refresh 实现需保持同步 |
| B19 | 角色卡加载失败静默降级默认卡 | frontend/routers/game.py 异常被吞换默认卡;玩家无提示（前端域,按约定不排期） |

---

## 2. 功能缺口(模拟器基础设施)

| # | 缺口 | 定位 |
|---|------|------|
| F1 | **物品转移**(丢弃/给予 NPC/交易) | use 大类剩余的最后一块通路:"把钥匙递给 NPC"类叙事接不住。范围裁决时未选,按需排期 |
| F3 | timed 只进 Author prompt | enrich/narrator 经 Author 产出间接感知(架构特性,同 known_spells 通路);叙事一致性有诉求时补直连 |
| F5 | **疯狂体系**(COC 核心) | 单次 SAN 损失>=5->临时疯狂(INT 检定);当日累计>=SAN/5->总结性疯狂;恐惧症/躁狂症标记。timed_effects 基建可承载;依赖 SAN check 通路(已接通)。模组高频写法"失败则疯狂" |
| F6 | **重伤/濒死/急救** | 当前 HP 0 直接 loss+game_over(combat.py:_build_single_round_result);缺:单次伤害>=HP/2->重伤 CON 检定(失败昏迷)/HP 0 濒死(每轮-1,可急救稳定)/急救+医学技能用途。剧情依赖(被俘/被救)会卡 |
| F7 | **战斗反应与骰子表达** | 闪避自动成功(玩家 dodge->敌方下次攻击必 miss,无对抗检定,策略退化);反击 fight back 选项无;奖励骰/惩罚骰(bonus/penalty dice)无--模组文本高频;push roll(孤注一掷)无 |
| F8 | **恢复生态+mythos 增长** | HP 每日自然恢复无(多日模组卡);SAN 恢复(安全环境/心理治疗)无;克苏鲁神话增长通路无(SAN_MAX=99-神话公式与技能列表已就位,@grant_spell 有而 mythos 加值无);advance_time 钩子现成(MP 已走此路) |
| F10 | **周期性/环境效应**(表达力缺口) | timed/effect 原子只有"到期清除",无周期 tick payload;毒每轮掉 HP/雾中每轮 SAN/诅咒每日发作类模组写法无结构化通道(F9 注记"每轮在雾中停留"即此例)。钩子现成:_tick_time_effects(小时粒度,MP 恢复已走)/_tick_temporary_effects(轮末,buff 递减已走)。方向:effect 原子加 interval(round/hour/day)+payload 原子数组,8 原子体系自然延伸(2026-08-26 机制层思考) |
| F12 | **条件效果**(触发式 effect) | 敌人特殊能力(狂暴 HP<50% 攻击+1D4)无数值通道;special_abilities/boss_mechanics 半接(judgment prompt 可见,战斗数值不执行,靠 LLM 自由发挥);effect 原子无触发条件(on_hp_below/on_round 等)。等内容需求出现再结构化,先靠 boss_mechanics 文本兜底 |

| F14 | **技能成长标记** | checked 标记已落（fce8f7a）；幕末成长检定循环仍 Step3/U4 |
| F15 | **金钱/交易/贿赂** | 信用评级只产文字标签,运行时无金钱概念;"塞钱给线人"等经典手段无通路 |
| F17 | **场景物品放置/拾取/容器** | 只有武器能放场景(scene_weapons),无 drop API、无容器嵌套;"抽屉里的东西""把物品藏回现场"接不住 |
| F18 | **时间触发世界事件调度器** | clock 纯计数器;"22:00 凶手行动"玩家不动永不发生;钩子现成(_tick_time_effects) |
| F19 | **环境状态进检定** | 光照/天气/噪音无修正源(难度只来自 entity.difficulty);手电筒/火柴 L0 无 effect,黑暗侦查无机械支撑 |
| F20 | **探索侧潜行/躲藏** | 潜行只在对峙与战斗;"悄悄潜入/躲进柜子"只能 Author 自由发挥 |
| F21 | **物品组合/合成 + 耐久/次数** | 无 combine/split;InventoryItem 只有 quantity,tool 类永不损耗 |
| F22 | **线索系统结构化** | note_item 只记扁平字符串;无线索实体/关联边/"集齐可推理"判定 |
| F23 | **场景状态演化 + 实体可重复策略** | 已成功实体一刀切不可重复;场景描述只有 Author 补丁能改;重读文件/复查现场被硬挡 |

| F25 | **Narrator 长期记忆** | build_narrator_prompt 只注入当前 brief+快照,无历史;伏笔回收/多轮呼应无锚点 |
| F26 | **谎言/欺骗机制** | 玩家陈述无条件采信并写入 memory,伪装身份套情报无支撑 |
| F27 | **NPC 度量层缺口**(U1 前置) | `set_attitude` 与 `process_npc_turn` 定义后零调用=死代码;好感/瞬态情绪/自主日程连度量字段都不存在 |
| F28 | **友方 NPC 战斗参与** | combat 自承"extendable to NPCs later";跟随 NPC 无 HP/行动/不被选为目标,战斗中凭空消失 |
| F29 | **NPC 死亡剧情连锁** | dead 只做门控;无目击者反应/态度联动/事件传播 |
| F30 | **追逐/移动力** | MOV 已从 Stats 删除;flee 单骰 DEX 立即定音,无追逐轮/速度分级 |
| F31 | **模组体检 lint** | 现有验证只到 schema+引用存在性;DependencyGraph 无可达性分析;无独立 CLI |
| F32 | **模组试玩报告/难度标定** | llm_player 只出 goal_achieved 布尔;无场景覆盖率/结局触达率/检定难度分布 |
| F33 | **手写模组支持** | 无手写路径;前端编辑器校验只查 scenes/entities 非空不接 layered_schema |
| F34 | **模组版本管理/增量再生** | 无 manifest/源文档快照;重跑静默覆盖手改 JSON |
| F35 | **分歧/结局结构可视化** | dependency_graph 只有 JSON;多结局分支汇合关系无法直观检查 |
| F36 | **管线进度/失败前端可见 + 质量量化指标** | launcher 后台线程 fire-and-forget;auto 失败仍打印"执行完毕"(前端域) |
| F37 | **撤销/回滚上一回合** | 无 undo;误操作只能翻旧手动存档或重开(体验破例,前端/CLI 皆缺) |
| F38 | **存档槽位 UI + 元信息 + autosave 入口** | 存读档靠手敲命令;save_game 只记 turn_number;autosave 无法经 /load 触及(前端域) |
| F39 | **叙事历史玩家侧回看** | 历史只在浏览器内存刷新即丢;WorldChronicle 已入档但只喂 Author(体验破例) |
| F40 | **战斗中刷新/断线恢复** | _combat_sessions 进程内存态;刷新丢战斗面板(体验破例,前端域) |
| F41 | **新手引导/规则查询/行动建议** | 帮助仅斜杠命令清单;场景可交互实体不作为建议呈现(前端域) |
| F42 | **回合进度真实反馈** | WS 进度流失真:LLM 前推一条即静态"思考中"(前端域) |
| F43 | **角色卡导入回流** | 导出 zip 无导入端点;文件浏览器白名单不含 .zip(前端域) |

## 3. 重构队列(约定:倒数第二)

| # | 项 | 备注 |
|---|---|---|
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
| F13-① 弹药消耗/装填 | 长期 TODO:库 `shots` 在,`Weapon.ammo` 未从库拷贝(`_build_investigator_weapon` 漏字段),combat 零读写;需弹匣当前量/装填动作/空枪失败 |
| F13-② malfunction 卡壳 | 长期 TODO:字段已拷到运行时武器,combat 命中判定不比较;需卡壳 flag+清膛占一轮 |
| F13-⑤ 射程/距离模型 | 长期 TODO:`Weapon.range` 纯展示,霰弹 `/` 截第一段;需距离带/移动/衰减整套状态机 |
| F13-⑥ 极难贯穿差异化 | 长期 TODO:`_get_tier` 已算只进文本,伤害不变;需贯穿/最大伤害公式 |
| F13-③ 玩家护甲 | 非目标(统一资源层 spec:equip 无机制加成;护甲只作用敌方) |
| 输入格式扩展(epub/html/URL)/Step0 只认 txt | 有真实内容源需求再动(2026-08-26 盘点) |
| 多语言模组/i18n | 叙事文本与结构键混存,远期 |
| 模组素材附件(地图/立绘/handout) | schema 无 image 字段,远期生态 |
| 多人混战目标选择/队友误伤/掩体 | 依赖 F28 先行;掩体等防御向机制随 F13 批次评估 |
| 移动端响应式/音效氛围/掷骰动效 | 前端打磨,随前端排期 |

---

## 5. 已收口(滚动,只留近期)

| 日期 | 项 | 方式 |
|------|----|------|
| 2026-08-29 | **B1 存读档 3 连** | 三连修法：① load_state 库透传 + load_warnings（1a9d43d）；② set_world 重绑 + save/load 唯一入口 + 会话库拷贝（260580e+a755c5a）；③ session_state 最小集入档（npc_injected_at_ids/recent_intents/last_comms_time），注入不重复（bfbda33）。存档 version 2；v1 additive-default。 |
| 2026-08-28 | **R1 C1 process_turn 拆分** | keeper 阶段化完成（5 宏阶段 + TurnRunner）；combat.py / scenario_core.py 拆分另排 |
| 2026-08-28 | **F16 锁-钥匙关联** | 降级为测试锁定+文档配方,未加机制(06ba6cc);若 Step2/3 真实模组需要更强锁语义再开新项。测试发现 `_ENTITY_ID_PATTERN` 强制数字,IT_LOCK 类无数字 ID 被当自然语言优雅放行;pattern 改为 `^[A-Z][A-Z0-9_]+[a-z]?$`(I1/I12a/AT2 仍匹配;中文 NL 仍优雅放行) |
| 2026-08-28 | **F9 SAN check 遭遇去重** | 目睹组全局去重入档;被攻击组场内去重解 multi_attack 叠加(76264df);F5/F8 联动仍跟踪 |
| 2026-08-28 | **F4 timed/effect 边界测试** | 补齐 expire_at 渲染兜底 / buff 探索侧降级等防御分支断言(d7113d5) |
| 2026-08-28 | **F11 库 schema 作者参考文档** | docs/library-schema.md(ca83ff8)+review 修 flags 接线(cb2b5a8) |
| 2026-08-26 | **F13 敌人 attack.skill_value 断链 + F24 纯对话 memory 漏记** | combat 优先读 skill_value（>0）否则 (DEX+POW)//2+dodge_bonus；game_loop 早退路径 npc_events 时 add_record。F13 其余①②⑤⑥ 入 §4 长期 TODO、③非目标。五域 F14–F43 回登 ISSUES |
| 2026-08-26 | **B13 三库裸 json.load / B14 skill_config 缓存死代码 / B15 fumble 边界 / B6 被支配渲染未命中 / B8 满 MP 仍耗累计器** | load_json_object 五库收敛；load_skill_config 默认路径真正缓存；_roll_d100 `roll>=96 and roll>target`；跳过叙事不写未命中；满 MP acc 清零 |
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
