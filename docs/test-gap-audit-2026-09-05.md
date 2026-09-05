# 后端测试缺口盘点（2026-09-05）

> 范围：src/ 全部 + tests/ 非前端。基线：`pytest tests/ -q` 556 passed / 28 deselected。
> 方法：grep 核对函数名在 tests/ 出现次数 + 逐文件读 except/序列化对称性。所有断言附 file:line。
> 已确认覆盖充分的项见 §4，勿重复补测。

## ① 高优先级

### H1. Boss 状态存读档往返零覆盖
- 位置：src/game/boss_manager.py:126-140（to_dict/from_dict）；src/scenario_core.py:1502-1511（load_state boss 分支 + 无库 warning）
- 现状：`grep -rn "boss" tests/test_save_load.py` 零命中；`BossManager.from_dict` 全 tests/ 零引用。enemy 的「无库 warning」「恢复失败 warning」有测（test_save_load.py:38），boss 同型两条分支（1504-1505、1510-1511）均无测。
- 风险：Boss 战中/后存档丢失 spawned/active 状态静默无感；BossManager 序列化字段漂移（如 `_instance_ids` 改名）无测试拦截，读档即静默丢 Boss。
- 建议：仿 test_save_load.py:23 加一个带 boss_lib 的 save→load 往返用例 + 无库 warning 用例。
- 优先级：高（存读档主路径，B1 同类问题曾三连修）。

### H2. Boss 软条件（`||`）LLM 判定路径零覆盖，失败乐观放行
- 位置：src/game/agents/keeper.py:320-369（`_check_boss_requirements` / `_evaluate_boss_soft_condition`，368 行 `except Exception: return True`）
- 现状：`grep -rn "soft_condition\|soft_trigger" tests/` 零命中；test_p0_pipeline_fixes.py:118-130 只测纯 hard/混合 hard 失败，无 `||` 软条件用例。
- 风险：LLM 不可用时 Boss 无条件触发（optimistic pass），方向性错误（应保守不触发）无测试暴露；软条件判定逻辑整体无回归锁。
- 建议：stub call_deepseek 补 3 例（soft 满足/不满足/LLM 异常时断言放行语义）。
- 优先级：高（Boss 触发是战斗主路径入口，且 except 放行方向值得拍板）。

### H3. run_game.py 交互主循环零专测 + `/trigger` 幽灵命令
- 位置：run_game.py:95-218（主循环）、107-163（斜杠命令分发）、160（help 文本）、366-609（`_run_interactive_combat`）
- 现状：全 tests/ 仅 test_combat_smoke.py:646 惰性导入测 `_run_interactive_combat` 被支配单分支。`/scene` `/info` `/events` `/flags` `/char` `/save` `/load` 七个命令、`_format_snapshot_chapters`（252）、`_print_turn_output`（351）、战斗子循环的 flee/loss/game_over/boss resolve_outcome（557-571）、max_rounds 平局（543）全无覆盖。
- 附带缺陷（非测试问题但由测试缺失掩盖）：help（160 行）宣称 `/trigger <E1>`，但 107-163 无此分支，`_handle_spawn_command`（game_loop.py:47-155）也只处理 `/spawn`、`/inject`——玩家输入 `/trigger` 会被当普通回合文本送 LLM。
- 风险：CLI 是 ISSUES.md §0 约定的唯一关注面，其入口脆性（如 181-184 game_over break、571 set_active(None) 顺序）改动无网兜。
- 建议：`_format_snapshot_chapters`/`_print_turn_output` 纯函数先补单测；命令分发表用 monkeypatch input 补 smoke；顺手删或接上 `/trigger`。
- 优先级：高（ISSUES §4 已注「不新开项」，此处仅登记现状，是否动工由用户拍板）。

## ② 中优先级

### M1. run_turn narrator 异常兜底无测试，且无 warning 落账
- 位置：src/game_loop.py:496-498（narrator.narrate 失败 → 固定文案「叙事生成暂时不可用」）
- 现状：`grep -rn "叙事生成暂时不可用" tests/` 零命中。对比 keeper._enrich 同类失败会 `_warnings.append`（keeper.py:656-658），此处 warning 不落账，玩家侧无 ⚠ 提示。
- 建议：monkeypatch narrator 抛错，断言返回文本且（若补 warning）warnings 含记录。

### M2. ConsumeItem 模糊匹配路径吞异常 + 零覆盖
- 位置：src/scenario_core.py:1605-1632（精确匹配失败 → LLM 模糊匹配，1631 行 `except Exception: pass`）
- 现状：`grep -rn "consume_item_fuzzy\|未找到匹配物品" tests/` 零命中；test_use_system.py:286 只测精确命中。
- 风险：LLM 异常静默吞掉，玩家只看到「未找到匹配物品」，消耗语义漂移（匹配错物品扣错库存）无锁。
- 建议：stub call_deepseek 补 matched/unmatched/异常三例。

### M3. 自动存档全链零覆盖 + 失败静默
- 位置：src/game_loop.py:702-744（`start_autosave`/`_autosave_callback`/`_check_autosave`，743 行 `except Exception: pass`）
- 现状：`grep -rn "autosave" tests/` 零命中。run_turn 每回合调 `_check_autosave`（351 行）。
- 风险：autosave 目录不可写/磁盘满时静默丢档，F38 的 autosave 入口依赖此链。
- 建议：直接调 `_check_autosave`（置 `_autosave_flag=True`）断言文件生成 + 写失败不炸回合。

### M4. judge/combat 两处 timed refresh 无同步锁（B10 备忘未闭环）
- 位置：src/game/judge.py:230-245 vs src/game/combat.py:1009-1030（同 id 替换 + interval/payload 透传，两份手写实现）
- 现状：各自有测（test_use_system.py:780、test_combat_smoke.py:461），但无测试断言两处对同一 atom 产出等价 entry。ISSUES.md:35 自述「两处 refresh 实现需保持同步」——正是靠人肉维持。
- 建议：加参数化 parity 测试：同一 timed atom（含 interval+payload）分别走 judge.execute_material 与 combat 结算，断言 entry 键值一致。

### M5. judge 失败惩罚 LLM 分支（retries>=2）默认套件零覆盖
- 位置：src/game/judge.py:444-470（`evaluate_failure_penalty` 调用 + markup_effects 解析）
- 现状：test_deterministic.py:420-441 打到 retries==2 即止，且 helpers 玩家 `personal_description` 为空跳过 452 行分支；真正覆盖只在 test_harness_parallel.py:312/614（LLM 路径）。
- 建议：确定性用例给 inv 非空 description + stub evaluate_failure_penalty，断言 narrative 替换与 markup 入 side_effects。

## ③ 低优先级（一行一条）

- L1 `_mp_regen_acc` 不入档：src/scenario_core.py:718 初始化、877-880 累计，to_dict（1343-1382）无此键——存读档丢不足 1 小时的 MP 累计，无测。修法：入 to_dict/from_dict 或拍板不持久化。
- L2 `_handle_spawn_command`（/spawn、/inject 调试命令，game_loop.py:47-155）零测试。修法：直接函数级调用 2 例。
- L3 `talk_to` LLM 异常 → 「沉默不语」（npc_manager.py:283-284）无异常分支测试；成功路径已覆盖（test_npc_attitude.py:76）。
- L4 `turn/` 五相位函数（phase_a~e、TurnRunner）无单元测试，全靠 e2e 间接覆盖（grep tests 零直接引用）——可接受，重构 R1 时若再拆分需补。
- L5 B3 LLM flaky 无 retry/分层标记落地（ISSUES.md:28）——测试基建缺口而非产品代码缺口。
- L6 `layered_pipeline.py:618-658` 六连 `except: pass`（库名单预提取）——生成端边缘，list_all 失败只影响 prompt 丰富度。
- L7 encounter.py:65-67 战斗入口 LLM 失败 → `combat_entry=None` 静默不入场——有 p0 相邻测试（test_p0_pipeline_fixes.py:87），异常分支本身无测。

## ④ 已确认覆盖充分（防重复劳动）

| 项 | 证据 |
|---|---|
| 存档新字段往返（scene_items/environment/scheduled_events） | test_save_load.py:219-241 |
| B20/B21 SAN/HP 单轨镜像 | test_combat_smoke.py:854、923 |
| F10 周期效应（hour/day/round、payload 隔离、expire） | test_periodic_effects.py 全部 9 例 |
| LLM 402→Ark fallback | test_llm_provider.py:15-61 |
| F5 疯狂（含读档重注 _insanity_llm） | test_insanity.py:115、230 |
| F27 attitude / F29 npc_dead / F26 talk_to | test_npc_attitude.py 全部 20+ 例 |
| F14 成长 + 版本化导出 | test_growth.py:29-91 |
| F17 scene_items 拾取/丢弃 | test_scene_items.py:208-293 |
| F18 scheduled_events（含 init_game 桥、存档往返、失败仍出队） | test_scheduled_events.py:20-135 |
| F23 repeatable / F25 narrative_memory / F31 lint / F32 playtest_report | test_repeatable.py / test_narrative_memory.py / test_module_lint.py / test_playtest_report.py |
| LUCK 声明消耗 | test_deterministic.py:850-874、test_skill_config.py:147 |
| 递归深度守卫 | test_deterministic.py:1524 |
| TurnMonitor freeze/重试契约 | test_turn_monitor.py、test_turn_result_contract.py |
| investigator 序列化（insanity/checked/timed_effects 过滤） | test_insanity.py:115、test_skill_checked.py:40、serialization.py:189-196 自带 warning |
| 敌人存读档（有库/无库/损坏） | test_save_load.py:23-59 |
