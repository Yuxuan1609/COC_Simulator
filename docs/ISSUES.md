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
| B4 | **escalation_real pytest 无诊断现场** | `test_escalation_real.py:184` log_dir="" 使日志 no-op,失败需 `python tests/e2e/test_escalation_real.py C E` 手跑 |

### 🟢 Minor(攒一批顺手清)

| # | 问题 | 备注 |
|---|------|------|
| B6 | 战斗轮叙事把被支配跳过渲染"未命中" | 措辞不准,机制正确(combat.py 轮叙事行 + LLM 摘要喂 "--=0 D100=0" 噪声) |
| B8 | MP 恢复累计器在 MP 已满时仍被消耗 | 满 MP 休息 5 小时后花费 MP 不追回;spec 未规定,影响极小 |
| B9 | control 对快于玩家的敌人 rounds off-by-one | spec 未规定先手;文档已注明"对快于玩家的敌人 rounds 应 ≥2" |
| B10 | timed refresh 战斗侧曾无测试 | 已补(4d9a0ff);此处仅备忘 combat/judge 两处 refresh 实现需保持同步 |
| B11 | 前端 character.py 导出 version 覆写 "2.0" 与核心 v2.2 漂移 | pre-existing;前端不排期约定下搁置 |
| B12 | 默认路径 cwd 独立性无回归测试 | loader._DATA_ROOT 已是包相对绝对路径,但缺 monkeypatch _DATA_ROOT + os.chdir 的锁定测试 |
| B13 | weapons/enemies/bosses 库裸 `json.load` 同类缺陷 | B7(0362eba)只修 items/spells(经 loader 的 core+extensions 通路);weapons.py:108/enemies.py:154/bosses.py:61 同款无路径报错+非 dict AttributeError,同类收编时顺修(届时抽 loader 共享 `_load_json_dict` 一次收敛) |

---

## 2. 功能缺口(模拟器基础设施)

| # | 缺口 | 定位 |
|---|------|------|
| F1 | **物品转移**(丢弃/给予 NPC/交易) | use 大类剩余的最后一块通路:"把钥匙递给 NPC"类叙事接不住。范围裁决时未选,按需排期 |
| F2 | **参数集中化全面收编**(已拍板,下一步) | rules.py 函数体内散落数值(DB/BUILD 查表/tier 阈值/EDU 增益表)迁 data/game_config.json;前端硬编码(SAN bar /99 等)收编 |
| F3 | timed 只进 Author prompt | enrich/narrator 经 Author 产出间接感知(架构特性,同 known_spells 通路);叙事一致性有诉求时补直连 |
| F4 | timed 缺 expire_at 渲染兜底测试 / buff 探索侧降级等边界 | 已修主体,防御分支断言零散(T8/T12 review 记录) |

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
| judge 捏造证据空间(谓词外事件) | 已用谓词结果注入缓解;打磨 rubric 时注意 |

---

## 5. 已收口(滚动,只留近期)

| 日期 | 项 | 方式 |
|------|----|------|
| 2026-08-25 | **B5 run_step1b_test.py 裸 pytest 收集错误** | pytest.ini 加 `testpaths = tests`,裸 pytest 只收集 tests/;根目录调试脚本(模块级读已删的 data/modules/深渊之口/module_raw.txt)不再进收集范围,脚本本身保留不动(调试用途);`pytest tests/` 与 `python -m pytest` 等价免 --ignore |
| 2026-08-25 | **B7 loader 损坏扩展 JSON 报错缺文件名** | items/spells `_load_file` 裸 json.load 包 try/except:OSError/JSONDecodeError -> `ValueError` 带文件路径,另补顶层非 object 防御(数组原抛 AttributeError);core/extensions 共用入口一处覆盖两类;tests/test_library_loader.py 增 2 测试锁定 |
| 2026-08-25 | **B2 day:N time flag 随天数累积进 prompt/存档** | advance_time 注入前清旧 `day:`/`time:` 前缀 flag(推进时清理方案,旧档下次推进自动清理无需迁移);tests/e2e/test_deterministic.py TestTimeFlagHygiene 锁定(跨天/时段切换/build_snapshot 三段断言) |
| 2026-08-24 | **武器库技能名归一缺口**(手枪/步枪/霰弹枪不在 legacy_map -> STR/2 兜底 + warning 刷屏) | 4d62700:legacy_map 追加映射 + test_normalize_weapon_skill_names |
| 2026-08-24 | LLM flaky 处置约定 | UPDATES 记录:复跑即过不阻塞 |
| 2026-08-19 | escalation C/E 被挡 | 统一资源层门控 flavor 豁免收口(详见 UPDATES 2026-08-19 汇总) |
