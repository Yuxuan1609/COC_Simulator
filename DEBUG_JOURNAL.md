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
- **症状/根因**：`judged_entities` 只收集 success=True 的实体，失败实体不进 enrich；且 `all_outcomes[0].message` 被 enrich 无条件覆写
- **解决**：judged_entities 改为收集所有实体（含 failure）；enrich 覆写只对第一个成功且非 AT 的 outcome
- **关联**：`src/game/agents/keeper.py:113-121, 325-332`

## 8. ##GRADED## 结果未传递到 enrich
- **症状**：enrich prompt 中 entity.result 显示裸 D100 字符串而非 on_failure 分级文本
- **根因/解决**：失败分支用了 `skill_result`（原始 D100）而非 `result_text`（resolve_graded_result 输出）→ 加 `if has_graded: skill_message = result_text`
- **关联**：`src/game/judge.py:174-175`

## 9. @markup 泄漏到 LLM prompt
- **症状/根因**：entity.result 中的 @markup 原样保留传给 enrich → 两层 strip 防护（judge + enrich prompt）
- **关联**：`src/game/judge.py:174`；`src/prompts.py:506`

## 10. EnemyAttack 被当 dict 访问
- **症状/根因/解决**：`EnemyAttack` 是 dataclass，但 combat.py 用 dict 方式 (`attack['name']`) 访问 → 全部改为属性访问 (`attack.name` / `getattr(a, 'weight', 1)`)
- **关联**：`src/game/combat.py:294,309-310,320-388`

## 11. Mock patch 未覆盖 Narrator/TimeAgent 的 call_deepseek
- **症状**：mock 模式下日志缺失且耗时异常（10-30s/case）——Narrator/TimeAgent 绕过 mock 调用真实 API
- **根因/解决**：`from llm import call_deepseek` 创建模块级本地引用，`patch("llm.call_deepseek")` 只替换模块属性不影响已导入引用 → 显式 patch 每个 agent 的 `call_deepseek`
- **关联**：已在 LEARNING_JOURNAL 记录通用模式

## 12. G9/G10 子系统未序列化
- **症状**：存档/读档后 ItemManager/GameClock/EnemyManager/NPCManager/BossManager 全部丢失
- **解决**：`to_dict()` 扩展输出 clock/enemies/npcs/bosses/scene_weapons/memory；`load_state()` 逐一恢复；investigator 序列化新增 `item_manager`
- **关联**：`src/scenario_core.py:976-1070`；`tests/test_save_load_roundtrip.py`

## 13. Enrich results 类型不一致导致 TypeError
- **症状/根因**：Enrich 有时输出 `"results": "合并叙事"`（字符串）而非 `"results": {"I1": "..."}`（dict），字符串下标访问报 TypeError
- **解决**：`isinstance(results, dict)` 守卫

## 14. auto_trigger 在 flavor_outcomes 和 ambient_changes 中重复
- **症状/根因/解决**：AT 的 action 设为 "other" 导致同时进入两个列表 → 过滤条件加 `o.entity_type != "auto_trigger"`

## 15. evaluate_trait_enhancement 多行 f-string 被 edit 工具截断
- **症状**：Prompt 只剩第一行，LLM 收不到关键上下文。更危险的是——语法仍合法不报错，静默破坏
- **根因**：edit 的 `oldString` 匹配多行 f-string 时只覆盖第一行 → 截断。**发生两次**——第二次在后续 commit 中无意重新截断
- **解决/教训**：`oldString` 必须含足够长的唯一上下文；改后 `py_compile` + 随机读几行确认

## 16. Enrich prompt f-string 中未转义花括号导致 NameError
- **症状**：`run_game.py` 运行时 `NameError: name '整合后���' is not defined`
- **根因**：Enrich prompt 的 JSON 输出示例中有 `"results": {整合后的叙事}` 被 Python f-string 当作变量引用求值
- **解决**：加引号改为 `"results": "整合后的叙事"`

## 17. 日志系统重构：response 未按 agent 分文件
- **症状/解决**：所有 response 写入单一 `llm.txt` → 引入 `_current_log_label` 全局变量，`_show_prompt` 设 label，`_log_response` 按 label 写入对应文件

## 18. NPC 系统完全空转 — scene 字段无人填充
- **症状**：NPC 对话路由永不触发——所有 NPC `scene=""` → `get_in_scene()` 返回空
- **根因**：Step 2.5 不生成 initial_scene + `_bind_npc_entities()` 不设 scene + init_game 死代码读不存在的 `npcs` 字段
- **解决/教训**：从 entity source_scene 推断 NPC 位置；新架构上线前必须端到端 smoke test

## 19. 18 个管线步骤的 System/User Prompt 批量重构
- **症状/根因**：所有 build 函数把角色定义/规则/JSON Schema 和动态数据混在 user prompt 中，每次重复发送
- **解决**：13 步主管线 + 4 步补充管线逐一拆分——静态内容移入 STEP*_SYSTEM，user prompt 仅保留动态数据
- **关联**：`src/module_designer/layered_parser.py`；`src/module_designer/supplement_pipeline.py`

## 20. Edit 工具替换中文代码块时引入全角引号
- **症状**：~180 行替换后所有 Python 字符串引号变全角 `""`，`SyntaxError: invalid character`
- **根因/解决**：Edit 的 `new_string` 中混合中英文时中文引号感染 Python 引号 → `python -c "content.replace('“', '\"').replace('”', '\"')"` 一键修复；事后 `grep -n '[“”]' file.py` 检查
- **教训**：大块中文代码替换优先用 Write 重写整个文件

## 21. 条件块内定义的变量在块外引用导致 UnboundLocalError
- **症状/根因**：`enrich_executor = ThreadPoolExecutor(...)` 在条件块内，块外 `enrich_executor.shutdown()` 无条件执行
- **解决/教训**：条件块前初始化为 `None`；同类问题见 #13

## 22. LLM logging wrapper 导致 NPC 对话静默失败

- **症状**：test harness 中 NPC 对话返回"（京山 人吉 沉默不语。）"（fallback 文本），即使 LLM response 正常
- **根因**：两层 — (a) wrapper 有显式默认参数 `model=""`，空字符串传给 `call_deepseek` 后被 `_model = model if model is not None else "deepseek-v4-pro"` 当作合法模型名，API 返回错误；(b) `NPCManager.talk_to()` 用 `except Exception` 静默吞掉所有异常，返回 fallback
- **解决**：wrapper 改为 `def _logging_wrapper(prompt, json_mode=True, **kw)` — 移除所有显式默认参数，从 `kw` 中提取 `system` 用于日志，过滤 `allowed = {"json_mode", "model", "system", "reasoning_effort", ...}` 并只传这些到真实 API。`json_mode` 覆盖 `kw` 中的值（以防调用方在 kw 中传了不同的 json_mode）
- **关键教训**：`call_deepseek` 用 `is not None` 判断默认值（而非 falsy 检查），所以空字符串 `""` 和 `None` 行为完全不同。任何 wrapper 都不应给这类参数设空字符串默认值
- **关联**：`tests/test_harness_stability.py:78-100`；`tests/test_harness_parallel.py:85-107`；已在 LEARNING_JOURNAL 中记录了通用模式

## 23. NPC 名称中空格导致对话路由不匹配

- **症状**：test harness Case B Turn 2 用"京山人吉"（无空格）不触发 NPC 对话，而 data profile 中是"京山 人吉"（有空格）
- **根因**：`keeper.py` 的 NPC 路由用 `npc.name in raw` 做裸子串匹配，容错性极低
- **解决**：test input 中添加空格（"京山 人吉，..."）。长期方案见 Debug #1 — parse 层 `npc_interact` 类型
- **关联**：`tests/test_harness_stability.py:135`；`tests/test_harness_parallel.py:250,349`
