# Debug Journal — COC Simulator

> 更新原则：每次解决复杂 Bug 后记录症状、根因、解决方案。与 `LEARNING_JOURNAL.md` 交叉对比。保持 ≤10000 字。

---

## 1. NPC 名称匹配失败
- **症状**：玩家用"乘务员"指代 NPC"京山 人吉"，系统不触发 NPC 交互
- **根因**：`keeper.py` 用 `npc.name in raw` 做精确子串匹配，role/别名通通不认
- **解决**：改为 parse 层 `npc_interact` 类型，LLM 在 parse 时判断玩家是否在和场景内 NPC 对话

## 2. TimeAgent response 不写入日志 + 时间不推进
- **症状**：timeagent.txt 只有 prompt 没有 response；game clock 始终为 0
- **根因**：TimeAgent 传了 `thinking=False` 和 `max_tokens=300`，与 Keeper Enrich 的调用格式不一致，导致 `call_deepseek` 的内部路径行为异常
- **解决**：去掉多余参数，与 Keeper Enrich 保持完全一致的调用格式

## 3. Enrich + TimeAgent 并行日志竞态
- **症状**：TimeAgent 的 response 出现在 keeper_enrich.txt 中，内容是 Enrich 格式
- **根因**：`_show_prompt` 设置全局 `_current_log_label`，并行时互相覆盖
- **解决**：`TimeAgent._log_response()` 直接打开 timeagent.txt 追加，不依赖全局 label

## 4. Author Patch 导致 move 重复执行
- **症状**：Author Patch 后 `process_turn()` 递归，move 被执行两次
- **根因**：第一次 parse 已执行 move（修改 `world.current_location`），递归再次执行
- **解决**：两阶段提交——side_effects 和 move 压入 pending，Author 确认通过后统一 `_apply_pending()`

## 5. NPC bound entity 在 parse prompt 中分类错误
- **症状**：NPC 绑定的 I7/I8/AT6 显示在`【场景实体】`而非`【NPC 专属实体】`
- **根因**：`_build_entity_lines()` 只对 AT 检查注入标记，没对 interaction 做同样处理
- **解决**：直接从 `npc.bound_*` 收集 ID 集，遍历时检查归属

## 6. Python 函数内 import 导致 UnboundLocalError
- **症状**：`keeper.py:286` 报 `UnboundLocalError: ActionOutcome`
- **根因**：`process_turn()` 函数体内有 `from game.messages import ActionOutcome`，Python 编译时将整个函数内的 `ActionOutcome` 视为局部变量，import 之前的引用报错
- **解决**：删除函数内 import，模块顶部已有

## 7. 失败惩罚叙事在 enrich 管道中丢失
- **症状**：多次检定失败后 LLM 生成了惩罚叙事（扣血/刷怪/叙事文本），但玩家看不到惩罚反馈
- **根因**：两层 bug — (a) `judged_entities` 只收集 `success=True` 的实体，失败实体不进入 enrich；(b) `all_outcomes[0].message` 被 enrich 结果无条件覆写，当失败实体排在首位时惩罚叙事被擦除
- **解决**：(a) `judged_entities` 改为收集所有实体（含 failure）；(b) enrich 覆写规则改为只覆盖第一个成功且非 AT 的 outcome
- **关联**：`src/game/agents/keeper.py:113-121, 325-332`；`src/prompts.py:530`（enrich 指示词更新）

## 8. ##GRADED## 结果未传递到 enrich
- **症状**：enrich prompt 中 entity 的 result 显示 `"考古学检定：D100=62/1 > 失败"`（裸 D100 字符串），而非模组预设的 `on_failure` 分级文本
- **根因**：`judge.py:127` 把 `skill_message` 设为 `skill_result`（D100 原始字符串），而 `line 171` 正确解析的 `result_text`（`resolve_graded_result` 输出）被丢弃——成功分支用了 `result_text`，失败分支用了 `skill_result`
- **解决**：在 `resolve_graded_result` 后添加 `if has_graded: skill_message = result_text`，使失败路径也使用分级文本
- **关联**：`src/game/judge.py:174-175`

## 9. @markup 泄漏到 LLM prompt
- **症状**：含 inline markup 的 entity（如 IT5 的 `@spawn_enemy(enemy_ref="深潜者", ...)`）把这些语法传给 enrich LLM
- **根因**：`entity.result` 和 `entity.side_effects` 是两条并行路径——side_effects 被 parse_markup_all 解析执行，但 result 中的 @markup 原样保留
- **解决**：两层防护 — (a) judge 层面：`result_text = _MARKUP_STRIP_RE.sub("", result_text)` 从源头清除；(b) enrich prompt 层面：同样 strip 作为防御
- **关联**：`src/game/judge.py:174`；`src/prompts.py:506`

## 10. EnemyAttack 被当 dict 访问
- **症状**：`combat.py` 执行时报 `'EnemyAttack' object has no attribute 'get'`
- **根因**：`EnemyAttack` 是 dataclass（有 `.name`, `.damage` 属性），但 `combat.py` 多处用 `attack['name']`、`attack.get('weight')` 等 dict 方式访问
- **解决**：`attack['name']` → `attack.name`；`a.get('weight', 1)` → `getattr(a, 'weight', 1)`
- **关联**：`src/game/combat.py:294, 309-310, 320-388`

## 11. Mock patch 未覆盖 Narrator/TimeAgent 的 call_deepseek
- **症状**：mock 模式下 test harness 日志缺失 Narrator 和 TimeAgent 调用，且测试耗时异常（10-30s per case）
- **根因**：Narrator 和 TimeAgent 在模块顶部用 `from llm import call_deepseek` 导入，`patch("llm.call_deepseek", ...)` 只替换模块属性，已导入的本地引用不受影响——导致这两个 agent 绕过 mock 进行了真实 API 调用
- **解决**：在 patches 列表中新增 `patch("game.agents.narrator.call_deepseek", ...)` 和 `patch("game.agents.time_agent.call_deepseek", ...)`
- **关联**：`tests/test_harness_parallel.py`；`tests/test_harness_stability.py`

## 12. G9/G10 子系统未序列化
- **症状**：存档/读档后 ItemManager（物品）、GameClock（时间）、EnemyManager（敌人位置）、NPCManager（态度）、BossManager（状态）全部丢失
- **根因**：`ScenarioWorld.to_dict()` 和 `from_dict()` 只序列化了核心状态字段，子系统全部跳过；`Investigator` 的 `to_dict()` 也未包含 `item_manager`
- **解决**：扩展 `to_dict()` 输出 clock/enemies/npcs/bosses/scene_weapons/memory；`load_state()` 中逐一恢复（含 library 缺失降级处理）；investigator 序列化新增 `item_manager` 字段
- **关联**：`src/scenario_core.py:976-1070`；`src/investigator/serialization.py:88, 168-170`；`tests/test_save_load_roundtrip.py`
- **教训**：改完一个之后翻其他文件看是否有同样的 import-in-function 模式——果然 judge.py 也有

## 13. Enrich results 类型不一致导致 TypeError
- **症状**：`keeper.py:284` 报 `TypeError: string indices must be integers, not 'str'`
- **根因**：Enrich prompt 输出 `"results": "整合后的叙事"`（单一合并字符串），但代码期望 `"results": {"I1": "..."}`（per-entity dict）。Python 的 `"I1" in "整合后的叙事"` 是合法子串检查，不会报错，因此偶然命中时 `"整合后的叙事"["I1"]` 才爆 TypeError
- **解决**：`isinstance(results, dict)` 守卫——字符串直接跳过 per-entity 分配；后续改为 string results 走 `all_outcomes[0].message = results` 简单路径

## 14. auto_trigger 结果在 flavor_outcomes 和 ambient_changes 中重复
- **症状**：Narrator prompt 的 `【即兴行为】` 和 `【环境变化】` 显示完全相同的文本，LLM 将其当作两份独立内容生成重复叙事
- **根因**：`keeper.py:100` 把 AT 的 `intent.action` 设成 `"other"`，导致 AT outcome 同时进入 `flavor_outcomes`（prompts.py 按 `action=="other"` 过滤）和 `ambient_changes`（keeper.py 按 `entity_type=="auto_trigger"` 过滤）
- **解决**：在 `prompts.py` 的 flavor_outcomes 过滤中加入 `o.entity_type != "auto_trigger"`，同时省略空 `flavor_outcomes` 时整个 `【即兴行为】` 段落

## 15. evaluate_trait_enhancement 多行 f-string 被 edit 工具截断
- **症状**：特质增强 Prompt 只剩第一行"你是 TRPG 规则辅助裁判..."，LLM 收不到参赛信息、检定详情等关键上下文，但不会直接报错（因为仍是一个合法 f-string），只在日志中才能发现
- **根因**：`edit` 工具的 `oldString` 参数匹配多行 f-string 时只覆盖了第一行 `prompt = f"""..."""`，替换后整段 prompt 被截断。更危险的是——Python 语法仍然合法，不会报 SyntaxError，是一种静默破坏
- **解决**：重新编辑，`oldString` 精确匹配截断态的完整第一行+闭合 `"""`，`newString` 提供完整 prompt。**此事发生两次**——第一次修复后被后续 commit 无意中重新截断（第二次修改 `set_log_label` 时再次使用了匹配第一行的 `oldString`）
- **教训**：对多行 f-string 使用 edit 时，`oldString` 必须包含足够长的唯一上下文；修改后立即 `python -m py_compile` + 随机读几行确认内容没有被阉割

## 16. Enrich prompt f-string 中未转义花括号导致 NameError
- **症状**：`run_game.py` 运行时 `NameError: name '整合后���' is not defined`
- **根因**：Enrich prompt 的 JSON 输出示例中有 `"results": {整合后的叙事}` 被 Python f-string 当作变量引用求值
- **解决**：加引号改为 `"results": "整合后的叙事"`

## 17. 日志系统重构：response 未按 agent 分文件
- **症状**：所有 LLM response 写入单一 `llm.txt`，不同 agent 的 prompt 和 response 分在两个文件里，排查时需要手动拼接
- **根因**：`_log_response` 始终写 `llm.txt`
- **解决**：引入 `_current_log_label` 全局变量 + `set_log_label()` 函数。`_show_prompt` 在写 prompt 前设置 label，`_log_response` 按 label 写入对应文件。`evaluate_trait_enhancement` 不走 `call_deepseek` 所以需要手动 `set_log_label("skill_checks")`

---

## 18. NPC 系统完全空转 — scene 字段无人填充

- **症状**：NPC 对话路由永不触发，`npcs_visible` 永远空列表，整个 NPC-Entity 分离系统形同虚设
- **根因**：三层断链 — (a) Step 2.5 不生成 `initial_scene`；(b) `_bind_npc_entities()` 不设置 NPC 的 `scene` 字段；(c) `init_game()` 有一段死代码循环试图从 `scene_data.get("npcs", [])` 读，但 L2 scenes 根本没有 `npcs` 字段。最终所有 NPC `scene=""` → `get_in_scene()` 永远返回空
- **解决**：在 `_bind_npc_entities()` 绑 entity 时从第一个 entity 的 source_scene 推断 NPC 所在场景；纯对话框 NPC 从 L1 npc_appearances 兜底。Step 2.5 不该写 scene（scene 绑定是确定性逻辑，不该交由 LLM）
- **教训**：新架构上线前必须做端到端 smoke test——这里只要打印 `npc.scene` 一眼就看出是空，但没人验证过

## 19. 18 个管线步骤的 System/User Prompt 批量重构

- **症状**：所有模块生成步骤的提示词中，稳定内容（角色定义、规则、JSON Schema）和动态数据（章节文本、entity 列表）混在 user prompt 中，每次调用重复发送
- **根因**：最初的设计没有区分 system/user prompt，所有内容塞在 build 函数的 f-string 里
- **解决**：13 步主管线 + 4 步补充管线逐一重构——静态内容（任务定义、字段规则、输出格式、要求）移入 STEP*_SYSTEM，user prompt 仅保留 `chapter_text`、`entity_list`、`scene_names` 等动态数据。补充管线原本没有独立 system prompt，全在 inline 构建
- **关联**：`src/module_designer/layered_parser.py`；`src/module_designer/supplement_pipeline.py`

## 20. Edit 工具替换中文代码块时引入全角引号

- **症状**：`keeper.py` 整个 action 处理循环（~180 行）被替换后，所有 Python 字符串引号变成全角 `""`，`SyntaxError: invalid character U+201C`
- **根因**：`Edit` 工具的 `new_string` 参数中，中文文本的引号（如 `"拾取"`, `"搜索"`, `"other"`）被统一渲染为全角引号。替换块大量混合中英文时，Python dict key 如 `"type"` 也被感染
- **解决**：`python -c "content.replace('“', '\"').replace('”', '\"')"` 一键替换所有全角引号。注意：字符串内容中的中文引号也会变成 ASCII 引号，但在语义上等价不产生逻辑 bug
- **教训**：Edit 替换含中文的大段代码后，立即 `grep -n '[“”]' file.py` 检查全角引号；或直接用 Write 重写整个文件避免 Edit 的中间渲染问题

## 21. 条件块内定义的变量在块外引用导致 UnboundLocalError

- **症状**：`test_case_e_author_structural` 报 `UnboundLocalError: cannot access local variable 'enrich_executor'`
- **根因**：`enrich_executor = ThreadPoolExecutor(...)` 在 `if judged_entities or action_summaries:` 块内定义，但 `if enrich_executor:` 和 `enrich_executor.shutdown()` 在块外无条件执行。当条件为 False 时变量未绑定
- **解决**：在 `if` 块前添加 `enrich_executor = None` 初始化
- **教训**：条件块内创建的变量如需在块外引用，必须在块前初始化为 `None`。同类模式已见于 #13（`isinstance(results, dict)` 守卫），两者都是"先存在性检查再使用"导致的问题
