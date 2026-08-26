# MAINTENANCE.md — 维护文档（函数级）

> 记录所有模块的函数/类级信息：功能、签名、关键行号、上下游调用关系。
> **规则：每次修改代码文件后，必须同步更新本文档对应条目（行号/签名/功能）。** 另见 `agents.md`。
> **问题追踪**:已知 bug/功能缺口/重构/优化项集中于 `docs/ISSUES.md`(单一事实来源);修代码前先查彼处,收口后更新彼处。

---

## Changelog

| 日期 | 变更 |
|------|------|
| 2026-08-26 | 规则层盘点+机制缺口归档(文档工作,零代码):COC 规则六域现状盘点(检定/SAN/战斗/成长/恢复/LUCK),核心发现 P0 断裂链 san_loss(数据在库 8/8 敌人,tier1_san_check 死代码零调用)遭遇 SAN check 完全缺失->已接通(50a58b7/66e79ff/ace087b/1ce2ce4 详见各条);ISSUES 归档规则盘点缺口 F5-F9(疯狂/重伤/战斗反应/恢复生态/去重)+B15(fumble 边界)与机制思考缺口 F10-F12(周期性效应/库 schema 作者文档/条件效果);readme 战斗系统节补「遭遇理智检定」条目;UPDATES 增 2026-08-26 工作汇总节 |
| 2026-08-26 | SAN check 叙事补齐 review 修复（I1+M2，遭遇通路另两条战斗路径叙事不可见）--① src/game/combat.py `run_combat`（game_loop 自动战斗路径）终局叙事前置 san_log @417-421（CombatResult.narrative 开头插 "\n".join(state.san_log)+"\n" 后清空，镜像 _build_single_round_result 渲染即清语义；该路径不 build_single_round_result，原实现 _generate_combat_narrative 不读 san_log，玩家看不到目睹 check 文本）；② run_game.py CLI `_run_interactive_combat` 两处：进入战斗打印后逐行打印 san_log+清空 @370-373；命中显示硬编码"name用weapon击中！D100=x 造成N点伤害"改用 ea.narrative（已含敌名/武器/伤害句，可能追加"恐惧侵蚀"SAN check 文本）+D100 骰值前缀保留防信息丢失 @504-506（原行 D100 信息 narrative 不带）；③ M2：`parse_san_loss` 非空 raw 解析结果为空时记 combat logger debug（"[san] san_loss 无法解析: %r" 原文回显 @141-143，防未来数据坏分隔符静默禁用；空 raw/可解析输入零日志）；④ docs/ISSUES.md F9 追加设计注记：每轮情境组（如'0/1D20 (每轮在雾中停留)'）无触发点消费静默+multi_attack 每命中各一检加速 SAN 流失，与去重一并优化（不改状态）。TDD：tests/test_combat_smoke.py 增 2 测试（test_run_combat_narrative_includes_san_log：强制失败骰 roll=90 双方互不命中 draw，断言 CombatResult.narrative 含"理智检定"+敌名；test_parse_san_loss_garbage_logs_debug：caplog 断言空 raw/可解析输入零日志+坏输入 debug 原文回显），RED(2 failed)->GREEN；run_game.py 打印点 grep 代码级确认（CLI 无 pytest 覆盖惯例，不加强求）；test_combat_smoke 42 passed（基线 40+2）；全量回归 304 passed / 20 deselected（基线 302+2）；combat.py 1495->1505 行/run_game.py 601->606 行，combat.py 两表行号列 grep 实测全表对齐（_san_check_and_lose 142->147/run_combat 228->233/run_single_round 424->434/_build_single_round_result 588->598/_generate_combat_narrative 639->654/_init_combat 725->735/_match_action 769->802/_get_player_actions 801->834/_resolve_player_action 865->898/_resolve_enemy_action 1150->1160/_tick 1218->1228 等，含 66e79ff 后遗留漂移顺手修正；CombatSystem 类头 @206->212） |
| 2026-08-26 | 遭遇 SAN check 接线 Task2（两时点接线+首轮渲染+e2e，P0 收口 2/2）--src/game/combat.py 四处接线（1464->1495 行）：① CombatState 增 `san_log: list[str]` 字段（@196，开局目睹 SAN check 叙事行缓冲）；② `_init_combat` 末尾（hp_max 兜底循环后、return 前）目睹 check 循环 @772-789：对 expanded_enemies 按 enemy_ref 去重（群组拆分后同 ref 只 check 一次；跨战斗不去重，ISSUES F9 跟踪），目睹组=parse_san_loss 注释不含"攻击"的第一组（无则第一组兜底，空 san_loss 跳过），_san_check_and_lose 扣 state.player_san（下限 0），san_log 追加"你遭遇{ref}：{text}。"；③ `_build_single_round_result` 轮叙事 lines 前插 san_log 一次性渲染 @623-626（san_log 行插最前+渲染即清空，不随下轮重复）；④ `_resolve_enemy_action` 命中分支（damage+player_hp 更新后）被攻击情境 check @1206-1212：parse_san_loss 取注释含"攻击"的第一组（无则不追加），_san_check_and_lose 扣 state.player_san，action.narrative 追加" 恐惧侵蚀：{text}。"；战斗结束写回链路已就位（game_loop._run_combat_turn player_san->derived.SAN / run_game._run_interactive_combat @535 同语义），无需新增。TDD：tests/test_combat_smoke.py 增 TestSanCheckWiring 5 测试（_TestEnemy 补 san_loss/quantity 可选参数默认空/1 兼容既有 33 测试：目睹失败扣 SAN+san_log 叙事行带敌名/quantity=3 群组展开 3 实体同 ref 只 check 一次/空 san_loss 不 check/命中走被攻击组 check+恐惧侵蚀叙事/SAN 扣减/仅目睹组命中不追加 check），tests/e2e/test_deterministic.py 增 TestSanCheckE2E 1 测试（真实 EnemyLibrary san_loss="1/1D6" 敌 + CombatInit -> _init_combat -> run_single_round 完整回合，断言 round_narrative 含"理智检定"+写回后 SAN<=战前（宽断言）+san_log 渲染后清空），RED（5 failed：san_log 缺失/无 check；no_group 负向用例实现前平凡通过）->GREEN；test_combat_smoke 40 passed（基线 35+5）/e2e deterministic 43 passed（基线 42+1，test_unresolved_use_becomes_creative 首跑偶发失败复跑即过=2026-08-24 已记录既有 flaky）；全量回归 302 passed / 20 deselected（294 基线+8）；节内行号 grep 实测对齐（run_combat 227->228/run_single_round 423->424/_build_single_round_result 587->588/_init_combat 720->725/_resolve_enemy_action 1127->1150/_tick 1187->1218） |
| 2026-08-26 | 遭遇 SAN check 接线 Task1（解析+检定纯函数，P0 断链 1/2）--src/game/combat.py 模块级新增三函数（_apply_damage_multiplier 后，1414->1464 行）：`_san_loss_roll(formula)` @109（SAN 损失公式掷骰：纯数字直接 int，骰式走 utils.roll_formula--roll_formula 只吃 NdM+K 骰式不匹配返 0，纯数字需本地兼容，函数内 import）；`parse_san_loss(san_loss)` @121（库 san_loss 字段多情境解析"0/1D4 (目睹), 1/1D6 (被攻击)" -> [(成功公式, 失败公式, 情境注释), ...]，逗号分组+括号注释剥离+`x/y` 正则匹配，空/坏组跳过）；`_san_check_and_lose(san, success_formula, fail_formula)` @142（COC 7th 遭遇理智检定：D100 <= 当前 SAN 为成功，成功掉成功组/失败掉失败组，无 tier/fumble；SAN 检定文案"理智检定成功/失败(D100=x/y)，失去 N 点 SAN"；单次损失>=5 记 combat logger info（临时疯狂条件，ISSUES F5 疯狂体系未实现仅 log）；损失 max(0,..) 兜底）。TDD：tests/test_combat_smoke.py 增 TestSanCheckFunctions 2 测试（解析 5 例：单组/多组带注释/自由文本注释/空/坏格式；检定五分支：成功固定值/失败骰式/SAN=0 永失败/骰式 2D6 逐骰/SAN 扣减文案），RED(2 failed AttributeError)->GREEN；monkeypatch 目标勘误：combat.random 与 utils.random 为同一模块对象（两文件均模块级 import random），patch combat.random.randint 一处 D100/骰面两用均生效，计划稿成功->失败用例间漏了一次 re-patch（同 patch 下第二调用仍 roll=30 走成功分支），按测试意图补 re-patch 行；test_combat_smoke.py 全套 35 passed（基线 33+2）；节内行号 grep 实测 +50 对齐（CombatState 132->182/CombatSystem 155->206/run_combat 177->227/run_single_round 373->423/_build_single_round_result 538->587/_init_combat 670->720/_resolve_player_action 811->865/_resolve_enemy_action 1073->1127/_tick 1137->1187 等）；消费侧接线在 Task2 |
| 2026-08-25 | 小修批次+F2 参数收编计划 Task10 总收尾:10 任务 10 commit(6e2e93b/0362eba/3d7a910/1ab5365/6e1e6a3/fc03138/75c88b7/fe9d2bb/bd96769/245234f)全部落地,294 passed 基线(269+25)确立;ISSUES B2/B4/B5/B7/B11/B12+F2 收口归档,B13(库裸 json.load 同类)/B14(load_skill_config 缓存死代码)新跟踪;tests/test_game_config.py 末尾追加 test_skill_config_attributes_match_stats_fields 锁定 skill_config.attributes 键集==Stats 字段集(roll_stats 的 Stats(**vals) 依赖,22 passed);UPDATES.md 增 2026-08-25 工作汇总节、readme.md effect 节补参数中心一句、ISSUES F2 移入 §5 |
| 2026-08-25 | 小修批次+F2 Task9（前端 SAN bar 分母接线 san_max）+B11 version 对齐--① 数据链:SAN bar 分母由硬编码 /99 改 derived.SAN_MAX（=99-克苏鲁神话，克系内容失SAN后上限下降，原 /99 会显示不到顶/超顶）。 CombatState 增 `player_san_max: int = 99`（combat.py@139，_init_combat@693 从 player.derived.SAN_MAX 接线）；CombatResult 增同名字段（messages.py@142，run_combat 构造处 getattr 兜底 99）；_build_single_round_result dict（@580）与前端序列化 _serialize_combat_state_for_frontend（game.py@64）均带 player_san_max；② JSON 接口三处补 san_max：player-status?format=json（@700）、/api/game/init 响应（@854）、/api/game/state（@875，无 player 兜底 99）；③ 服务端渲染 character-card san_pct 用 `derived.SAN / max(1, derived.SAN_MAX)`（@576）；game.html updateCharHUD 取 data.san_max 换算 char-san-bar（543 附近）+ initGame/state 两处透传 san_max + renderCombatPanel 用 st.player_san_max（1103 附近）；④ B11：character.py _build_export meta.version "2.0"->"2.2"（@275，与核心 serialization.py v2.2 对齐）；⑤ TDD：tests/test_frontend_contract.py +6（player-status/state 含 san_max、character-card 62.5% 分母、_serialize/_init_combat/run_single_round 三层接线），_fake_game_with_spells derived 补 SAN_MAX=88；tests/test_frontend_character.py version 断言 2.0->2.2；RED 7 failed->GREEN 14 passed；grep 无 "/ 99" SAN 残留；⑥ 行号实测对齐：game.py 1187->1191 行（game_page 169/player_status 682/init 770/state 863/combat_start 893@979/combat_round 1002@1027/set_auto_win 882/_resolve_start_scene 1138/_make_default_inv 1184，顺手修正历史漂移 832/843/952 等）、combat.py 1410->1414 行（run_combat 177/run_single_round 373/_build_single_round_result 538/_init_combat 670/_tick 1137）、messages.py 302->303 行（SkillCheckResult 起全部 +1）；回归 tests/ 全量 293 passed / 20 deselected（基线 287+6）；ISSUES B11 移入 §5 已收口 |
| 2026-08-25 | 小修批次+F2 Task8（roll_stats 骰面收编 F2）+T7 review 补丁--① roll_stats 重构：骰面不再硬编码，读 skill_config.attributes.dice（[count,sides] 或 [count,sides,flat]：STR/CON/DEX/APP/POW/LUCK [3,6]=3D6、INT/EDU [2,6,6]=2D6+6，8 属性全有），总乘数读 game_config.stat_roll_multiplier（默认 5），消代码/数据重复；顶层 from utils import roll_d6 随之删除（rules.py 内已无调用方，random.randint 直掷）；② T7 review 补丁三则：(a) _cfg_shape_ok list 分支升级按首元素模板深校验行结构（行内 dict 必需键齐全+标量类型匹配或 None 特赦、list 行等长逐位类型、标量行类型一致），db_build_table 行内坏值（max_key 字符串/缺键）不再被浅校验放行后炸消费方，整体回缺省；(b) apply_age_modifiers tier clamp 扩为三数组对称防御 min(tier, max_tier, len(app)-1, len(phys)-1, len(edu)-1)，三表配长不对称不再 IndexError（tier 统一 clamp 到最短表档位，三表共用同一档，不出现 app 用 tier4/phys 用 tier1 的分裂）；(c) allocate_skill_points docstring「上限 99」改「上限 skill_value_cap(config)」；③ TDD：tests/test_game_config.py 末尾追加 4 测试（roll_stats 范围锁定 200 轮/multiplier=1 覆盖/db_build_table 行内坏值回退/年龄三表不对称统一 clamp），RED 3 failed（范围锁定测试对旧实现亦过=锁定型；计划稿 INT/EDU 上界 80 与 16 系笔误——(2D6+6)*5 上界实为 90、乘 1 时上界 18，锁定测试对旧实现即以 EDU=90 证伪，已按真实区间修正断言）-> GREEN 21 passed；④ rules.py 351->370 行（删 roll_d6 import -1、roll_stats 12->14 行、allocate docstring +1、tier clamp 1->3 行、_cfg_shape_ok 9->24 行），节内行号 grep 实测对齐（roll_stats 21->20、_calc_db_build 39->40、calc_derived 48->49、create_skill_list 69->70、allocate_skill_points 80->81、calc_occupation_points 113->115、apply_age_modifiers 140->142、get_credit_level 171->175、create_default_unarmed 185->189、load_occupations 199->203、load_occupation_labels 217->221、calc_db 227->231、opposed_check 263->267、_GAME_CONFIG_DEFAULTS 283->287、reset_game_config_cache 317->321、_cfg_shape_ok 323->327、get_game_config 334->353）；tests/test_game_config.py 196->242 行；回归 tests/ 全量 287 passed / 20 deselected（基线 283+4） |
| 2026-08-25 | 小修批次+F2 Task7（F2 主体）：rules.py 六函数散落数值收编进 game_config + T6 review 两补丁--① 六消费方接线（数据 T6 已迁入，本任务改读 config，默认值与现状逐位一致）：（a）_calc_db_build 硬编码 if-elif 链改遍历 game_config.db_build_table（max_key None=兜底行，空表兜底 ("0",0)）；（b）calc_derived 除数/基数（HP=CON//hp_divisor、MP=POW//mp_divisor、DODGE=DEX//dodge_divisor、SAN 上限=san_max_base-神话）读 game_config.derived；（c）allocate_skill_points 技能值上限 99 改读 skill_value_cap；（d）apply_age_modifiers start_age/max_tier/app/phys/edu 三组表读 age_modifiers（tier=min((age-start_age)//10, max_tier, len(app)-1)）；（e）删模块级 CREDIT_RATING_TABLE 常量（仅 rules.py 内部 get_credit_level 引用，已确认），get_credit_level 改读 credit_rating_table（sorted 升序遍历，空表兜底「身无分文」），typing.Dict 随之从 import 移除；（f）create_default_unarmed 伤害 "1D3+DB" 改读 unarmed_damage；② T6 review 补丁：g) get_game_config 校验升级 _cfg_shape_ok（顶层 type is 不变；嵌套 dict 必需键齐全递归，list 非空+元素类型一致（T8 补丁后按首元素模板深校验行结构：dict 嵌套+list 行结构均校验,坏值整体回退;None 仅 list 行内 dict 值合法））；h) 同步锁定测试 test_shipped_json_matches_defaults（data/game_config.json 与 _GAME_CONFIG_DEFAULTS 全量相等，不 monkeypatch 读真实 _CONFIG_PATH，teardown 既有 reset 防缓存污染）；③ TDD：tests/test_game_config.py 先加 7 测试（5 个 override + 嵌套内层坏值 + 同步锁）RED 6 failed/同步锁直接过 -> GREEN 17 passed；④ 连带修正 tests/test_use_system.py 3 处 get_game_config 整体替换 stub（test_timed_default_minutes_from_config/test_mp_recovery_rate_from_config/test_mp_regen_zero_rate_disables原 lambda 只返回单键 dict，F2 后 _world() 内 calc_derived 读 ["derived"] 即 KeyError）：改 {**_GAME_CONFIG_DEFAULTS, 单键覆盖}（测试意图不变：该键从 config 读）；rules.py 359->351 行（CREDIT_RATING_TABLE 删 10 行+收编净变化），节内行号 grep 实测对齐（calc_derived 55->48、allocate_skill_points 84->80、apply_age_modifiers 143->140、get_credit_level 191->171、create_default_unarmed 204->185、calc_db 246->227、opposed_check 282->263、_GAME_CONFIG_DEFAULTS 302->283、get_game_config 342->334、新增 _cfg_shape_ok @323）；tests/test_game_config.py 122->196 行；回归 tests/ 全量 283 passed / 20 deselected（基线 276+7，test_combat_phase_trigger 首跑偶发失败复跑即过=既有 flaky） |
| 2026-08-25 | 小修批次+F2 Task6（F2 第一步）：game_config 扩键+深拷贝（为 Task7/8 rules.py 参数收编铺路）--① data/game_config.json 3->10 键全量重写（新增 stat_roll_multiplier=5/skill_value_cap=99/unarmed_damage="1D3+DB"/derived{hp_divisor 3,mp_divisor 5,dodge_divisor 2,san_max_base 99}/db_build_table 6 行(max_key None 兜底)/age_modifiers{start_age 40,max_tier 4,app/phys/edu 三数组}/credit_rating_table 8 档），与 _GAME_CONFIG_DEFAULTS 逐键镜像；② rules.py：头部 import 区加 `import copy`；_GAME_CONFIG_DEFAULTS 同步扩为 10 键；get_game_config 末行 `return dict(_game_config_cache)` -> `return copy.deepcopy(_game_config_cache)`（原浅拷贝嵌套结构（dict/list）与缓存共享引用，调用方改 nested 值会污染缓存；顶层类型校验 `type is` 保持，嵌套键顶层类型不符整体回默认）；③ tests/test_game_config.py 末尾追加 3 测试（test_new_keys_present 新键默认值/test_nested_config_deep_copy 改 derived.hp_divisor 与 db_build_table[0].db 不污染缓存/test_nested_type_mismatch_falls_back 嵌套键类型不符回默认），RED(3 failed KeyError)->GREEN；连带修正旧测试 test_non_dict_json_falls_back：原断言硬编码 3 键整字典精确相等，扩键后过时（断言对象本身变了而非行为回退失效），改 `cfg == rules._GAME_CONFIG_DEFAULTS`（逐键等于缺省表，意图不变）；④ rules.py 334->359 行，节内行号 grep 实测对齐（roll_stats…opposed_check +1（import copy）、_GAME_CONFIG_DEFAULTS/_CONFIG_PATH 301/306->302/331、reset_game_config_cache 311->336、get_game_config 317->342）；此刻消费方（combat/judge/scenario_core）仍只读旧 3 键，新键无人消费，行为零变化；回归 tests/ 全量 276 passed / 20 deselected（基线 273+3） |
| 2026-08-25 | 小修批次 Task5/B12：tests/test_library_loader.py 末尾追加 test_data_root_cwd_independent（monkeypatch.chdir(tmp_path) 后不传 base_dir 调 load_item_library/load_spell_library 走 _DATA_ROOT，断言双库非空）--锁定 loader 默认路径与 cwd 无关（_DATA_ROOT@12 为包相对绝对路径），防将来改回 cwd 相对（改坏即此测试红）；纯测试收口零产品代码改动，src/library/loader.py 31 行不变；tests/test_library_loader.py 6 passed（基线 5+1）；ISSUES B12 移入 §5 已收口 |
| 2026-08-25 | 小修批次 Task4/B4：tests/e2e/test_escalation_real.py 5 个用例 pytest 运行留日志现场--test_case_a/b/c/d/e 签名 `def test_case_x(log_dir="")` -> `def test_case_x(tmp_path=None, log_dir="")`（tmp_path 前置，pytest 自动注入 builtin fixture），函数体首部加 2 行：`if not log_dir and tmp_path is not None: log_dir = str(tmp_path / "escalation_case_x")`，pytest 运行（log_dir 空）日志落 tmp_path 子目录，`_log_text/_log_json` 不再 no-op，失败有 prompt/response/meta 诊断现场；手跑入口 run() 调 `test_fn(log_dir=case_dir)`（@572）log_dir 非空短路、直接调用 tmp_path 缺省 None，两种形态零影响；文件 588->598 行（5 函数各净增 2 行，_setup_llm_logging @242 不变、CASE_MAP 523->533、run 543->553，grep 实测）；验证：`--collect-only -m real_llm` 5 tests collected 无错误、默认收集 5 deselected；ISSUES B4 移入 §5 已收口 |
| 2026-08-25 | 小修批次 Task3/B5：pytest.ini 加 `testpaths = tests`（其余 markers/addopts 原样）--裸 `pytest`/`python -m pytest`（无路径参数）原先从仓库根收集，run_step1b_test.py（模块级读已删的 data/modules/深渊之口/module_raw.txt）import 即 FileNotFoundError 报 `1 error during collection` 中断全部收集；加 testpaths 后根目录调试脚本（run_step1b_test.py/imp.py/test.py）不进收集范围（脚本保留，调试用途），`pytest tests/` 与裸 pytest 等价免 --ignore；验证：collect-only `272/292 tests collected (20 deselected)` 无 ERROR，`pytest tests/ -q` 272 passed / 20 deselected 全绿；ISSUES B5 移入 §5 已收口 |
| 2026-08-25 | 小修批次 Task2/B7：库文件损坏/格式错误报错带文件路径--src/library/items.py 与 spells.py `_load_file`（core 与 extensions 共用加载入口，一处修改两类文件全覆盖）裸 `json.load` 包 try/except：`(OSError, json.JSONDecodeError)` -> `raise ValueError(f"库文件加载失败: {path}") from e`（原 JSONDecodeError 不带来源路径，排障需逐文件试）；顺带覆盖顶层非 object（如数组）防御：`not isinstance(data, dict)` -> `raise ValueError(f"库文件格式错误(顶层应为 object): {path}")`（原对 `[1,2]` 抛 AttributeError: 'list' object has no attribute 'get'）；tests/test_library_loader.py 头部补 `import pytest` + 末尾追加 2 测试（test_corrupt_extension_json_error_names_file 损坏扩展 bad.json 带 / test_non_dict_library_json_error_names_file 顶层 [1,2] 数组，RED(JSONDecodeError 无路径+AttributeError)->GREEN）；items.py 90->95 行（_load_file @73 净增 6 行，get/list_all/__len__ 80/86/89->85/91/94）、spells.py 97->102 行（_load_file @80，get/list_all/__len__ 87/93/96->92/98/101），grep 实测对齐；ISSUES B7 移入 §5 已收口；tests/test_library_loader.py 5 passed（基线 3+2），关联回归 test_use_system+test_combat_smoke+loader 121 passed、tests/ 全量（除 e2e）230 passed、tests/e2e/test_deterministic.py 42 passed（test_unresolved_use_becomes_creative 首跑偶发失败复跑全绿，2026-08-24 T14 已记录的既有 flaky） |
| 2026-08-25 | 小修批次 Task1/B2：advance_time 清旧 day:/time: flag--scenario_core.py `advance_time`（@750）注入前先删 runtime_state 中带 `day:`/`time:` 前缀且不在当前 clock.get_time_flags() 的键（先攒 stale 列表再删，剧情实体条目无此前缀不受影响），防长期局 day:0..day:N 全 completed=True 经 build_snapshot completed 列表进每回合 prompt/存档膨胀；旧档读入后下一次 advance_time 自动清理，无需迁移；tests/e2e/test_deterministic.py 增 TestTimeFlagHygiene 1 测试（文件 1209->1236 行：早晨->夜间跨天只留当日 flag/时段切换只留当前时段/build_snapshot completed 不累积旧 day 三段断言；计划原稿首推 60 分钟 hour=1 实属夜间（h<5），断言 time:早晨 即便实现正确也必挂，改为 6*60/18*60 保 game_time=1440 跨天锚点与计划全部断言不变）；scenario_core.py 1764->1771 行，ScenarioWorld/MemoryManager/WorldChronicle 节内行号 +7 对齐 grep 实测（顺修节头 1759 漂移->1771）；ISSUES B2 移入已收口；tests/e2e/test_deterministic.py 全套 42 passed（基线 41+1） |
| 2026-08-24 | 问题集中化:新建 `docs/ISSUES.md`(bug 🔴🟡🟢/功能缺口/重构队列/处置约定/收口记录单一事实来源);UPDATES.md 全局已知观察节与队列节改为指针;MAINTENANCE 头部加问题追踪指引。同 commit 顺修武器库技能归一缺口(skill_config legacy_map 补 手枪/步枪/霰弹枪->枪械,4d62700) |
| 2026-08-24 | effect 表达力计划 T14（收口）：S15 + 文档 + 全量回归--① tests/e2e/test_scenarios.py 增 TestS15ExtensionSpell（文件 559->631 行）：扩展库法术游戏内施放（spec §8），tmp_path 造库根（copy core spells.json + extensions/spells/ext.json 写 EXT_WHISPER 暗影低语 L1/mp 2/check null/effect [timed 15min]），load_spell_library(base_dir) 断言扩展+core 双可见，make_world(spell_library=) + known_spells=["EXT_WHISPER"]，"施放暗影低语"走完整 keeper 回合（UseParser 确定性短路 -> execute_material，check=null 无检定保定性；enrich/time_agent/narrator 真实 LLM），断言 MP 12->10 + timed_effects [{id EXT_WHISPER/description 耳畔有低语萦绕/expire_at=施放时刻+15}] + 叙事宽断言（低语/声音/阴影任一，brief+narrative 合查）；retry_once 消化 time_agent 波动（timed 15min 内推满过期/MP 恢复属偶发）；mkdir exist_ok 保证 retry 重入安全；② readme.md 增「effect 原子系统（8 种，2026-08-21）」节（@markup 节后：原子表 damage/heal/mp_change/markup/buff/control/timed/narrative 战斗/探索双列 + 未知 type [unknown:x] 降级 + timed 软状态 + MP 恢复（每小时 1 点余数累计，mp_recovery_per_hour 可配）+ 扩展库约定（data/library/extensions/{items,spells}/*.json 放置即生效，游戏+管线双侧））+ 设计文档索引补 2026-08-21-effect-expression-design.md；③ changelog 补录 T3 缺失条目（本轮巡检发现，commit 31d3376+49aee16 当时未记）；④ 行号抽查（judge/combat/scenario_core/serialization/models/utils/loader 全准无漂移）；⑤ UPDATES.md 工作汇总 + 已知观察补条；全量回归：默认套件 268 passed / 20 deselected（S15 为 real_llm 标记不入默认套件；首轮 1 failed test_unresolved_use_becomes_creative 为偶发，复跑全绿）+ real_llm scenarios S1-S15 15/15 首跑全过（251s，无 retry 消化） |
| 2026-08-24 | effect 表达力计划 T13：e2e 确定性三场景（spec §8）--tests/e2e/test_deterministic.py 增 TestTimedAndCombatEffectsE2E 3 测试（文件 1046->1209 行）：① test_silence_veil_timed_mounts_and_expires 走完整 keeper 回合（"施放静默帷幕"经 UseParser 确定性短路→judge.execute_material→timed 入档），断言 timed_effects [{id SILENCE_VEIL/description/expire_at=施放时刻+10}]、MP 20→15、叙事含 on_success 槽文本，再 world.advance_time(10) 推满时长过期清空（探索侧 POW regular 检定走 check_skill 属性路径有 96+ 大失败，stub check_skill 保确定性）；② test_stone_skin_reduces_damage_in_combat 战斗入口（真实 core 法术库+EnemyLibrary 必中敌 DEX/POW=200+CombatInit→_init_combat+CombatSystem(spell_lib, world)），cast_STONE_SKIN（POW 技能 200 必过）断言 buff 挂 state.temporary_effects [{id/reduce 3/rounds 3}]+on_text 进叙事+MP 20→14+timed 挂 world.player(+30min)，_roll_damage monkeypatch 固定 7 后敌方攻击扣 7-3=4，对照干净 state（_fresh_state 同敌重展开）全额 7、差额恰为 reduce；③ test_dominate_skips_enemy_action monkeypatch investigator.rules.opposed_check 必胜（combat.py cast 分支函数内 import 时取模块属性，patch 可达），断言 controlled_rounds=2+MP 20→10+SAN 60→59、被支配敌 _resolve_enemy_action 跳过（success False/无法动弹叙事/damage 0/player_hp 不变）、_tick_temporary_effects 两次递减 2→1 仍跳过→0 恢复行动必中全额 7；全程真实产品代码零 API 调用；全套 268 passed（基线 265+3） |
| 2026-08-24 | T12 review 修复（Minor×2）：① judge.py buff/control 探索降级文本回退链（@236-237，原只读 description，战斗向 buff 原子带 on_text（STONE_SKIN 实例）读不到落空进默认兜底文本）--改 `description or on_text or （{t} 效果仅在战斗中生效。）`，与 combat.py on_text 字段同源；TestExecuteMaterialEffects 增 test_buff_without_description_falls_back_to_on_text（on_text 无 description 的 buff 原子→message 含 on_text 文本，RED->GREEN）；② test_necronomicon_page_grants_spell 闭环断言（正则解析 on_use 里 grant_spell 的 ref，断言 ref 在 SpellLibrary 可查到——防残页挂一个库里不存在的法术 id 静默降级；正则按内存字符串格式 `spell_ref="DREAM_GAZE"` 调整为 `r'spell_ref="?([A-Z_]+)"?'`，review 原稿 `\\"?` 匹配的是 JSON 转义形态）；judge.py 550->551 行（_execute_effect_atoms @188 不变，修改在函数体内），节内 buff/control 行描述更新；全套 265 passed（264+1） |
| 2026-08-24 | effect 表达力计划 T12：核心库内容升维（spec §7 数据示范，纯 JSON 变更零代码）--data/library/core/spells.json 5 条：STONE_SKIN effect 由空转单 dict `{"type":"buff","formula":null}` 升为 [buff(reduce 3/rounds 3/self/on_text)+timed(minutes 30)] 双原子（on_success 检定槽文本保留不冲突）；DOMINATE 补 effect [control(target enemy/rounds 2)]（T11 消费）；SILENCE_VEIL 补 effect [timed(minutes 10)]（T6/T8 消费）；HEART_ARREST/BLOOD_CALL damage 单 dict 显式包装为单元素数组（归一化兜底仍在，数据侧升维示范）；data/library/core/items.json 2 条：NECRONOMICON_PAGE on_use 追加 `@grant_spell(spell_ref="DREAM_GAZE")`（读残页受 SAN 代价+学会梦中窥探，T4 通路）；SALT 补 effect [timed(id SALT_LINE/minutes 60)]；tests/test_use_system.py 增 TestLibraryContentUpgrade 6 测试（STONE_SKIN buff+timed/DOMINATE control/SILENCE_VEIL timed/damage 数组格式/残页 grant_spell/盐袋 timed；按文件惯例补 load_core()，任务原片段缺加载调用 get() 返 None 会因错误原因失败），RED(5 failed 1 passed，damage 格式测试被归一化兜底先行通过)→GREEN；全套 264 passed（基线 257+1 用户本地 test_combat_smoke.py 新增 TestRunGameControlGuard+6 新测试，数目核查吻合） |
| 2026-08-24 | T11 review 修复：run_game.py 敌方 LLM 修正循环入口补 `if ea.damage <= 0: continue` 守卫（@468，对齐 combat.py @294，被支配跳过 action 不再送 _llm_correct_enemy_round，杜绝 LLM 给跳过攻击修正出正伤害）；敌方 CLI 展示补 `elif ea.weapon == "--" and ea.narrative: print(narrative)`（@502，跳过叙事可见）；玩家动作预置 `player_extra = ""`（@390，非 attack 分支 UnboundLocalError 预防） |
| 2026-08-24 | effect 表达力计划 T11：战斗 control 消费侧（spec §3，敌方行动跳过）--`_resolve_enemy_action` 顶部（@1078-1084，enemy_label 组装后、`_select_enemy_attack` 之前，不选攻击不掷骰）加 control 检查：`getattr(enemy, "controlled_rounds", 0) > 0` 时构造 CombatAction(actor=instance_id, action_type="attack", weapon/skill_name="--", target="player")，success=False、narrative="被无形的力量攫住，无法动弹。"（带 enemy_label）、damage=0（默认）、直接 return（不消耗 _player_dodging，跳过本身不递减 controlled_rounds，递减只在轮末 _tick）；敌方行动 3 处循环入口（combat.py @254/@437 + run_game.py @439）全走此函数单一消费点，multi_attack 循环每段调用均命中检查全跳过，跳过的 action 由调用方 append 进 state.log 叙事可见；tests/test_combat_smoke.py 增 TestCombatControl 3 测试（controlled_rounds=2 跳过+不耗 dodge+不递减+无 control 对照必中 7 伤害/tick 1->0 恢复行动归零后正常掷骰/无属性普通敌人 getattr 默认 0 正常路径），RED(2 failed)→GREEN；combat.py 1402->1410 行（_resolve_enemy_action 1073 不变，函数体内插入；_tick_temporary_effects 1125->1133/_check_phase 1138->1146/_apply_phase 1162->1170/_any_special_rules 1183->1191/_build_battle_snapshot 1193->1201/_build_round_result 1212->1220/_llm_correct_round 1240->1248/_llm_correct_enemy_round 1347->1355，grep 实测）；全套 257 passed（基线 254+3） |
| 2026-08-24 | T10 review 修复：run_game.py 交互战斗循环 `state.round += 1` 前补 `cs._tick_temporary_effects(state)`（@511，CLI 路径 buff 原先永不过期）；MAINTENANCE 轮末 tick 调用点表述修正为 3 处 |
| 2026-08-24 | effect 表达力计划 T10：战斗 buff 消费侧（spec §3，受击减免+轮末递减）--① `_resolve_enemy_action` 命中段加 buff 减伤（@1108-1114：`damage = _roll_damage(...)` 后、`action.damage` 前，总减免 = sum(temporary_effects[].reduce)，`damage = max(buff_damage_floor, damage - 总减免)`，floor 读 game_config（函数内 import get_game_config，monkeypatch 可达，与 T6/T7 模式一致），reduce_total=0 时零开销跳过）；② CombatSystem 新方法 `_tick_temporary_effects(state)`（@1125：轮末 temporary_effects 各条 rounds-1，归零移除（`rounds-1 > 0` 存活过滤）；顺带 enemy.controlled_rounds 递减（T11 消费，先写递减逻辑））；③ 两处轮末调用点 `state.round += 1` 之前各插 `self._tick_temporary_effects(state)`（run_combat 主循环 @348、run_single_round @531；后续 review 补 run_game.py 交互循环第 3 处 @511，全仓库共 3 处）；tests/test_combat_smoke.py 增 TestCombatBuff 4 测试（受击减免 7-3=4 对照断言/floor 默认 0 减穿归零+monkeypatch rules_mod.get_game_config 配 floor=1 扣 1/rounds 2->1 仍在再 tick 移除后伤害全额/双 buff 叠加 2+3=5），RED->GREEN；combat.py 1382->1402 行（run_single_round 371/_resolve_player_action 811/effect 遍历 @858-930/_resolve_enemy_action 1073/_tick_temporary_effects 1125/_check_phase 1138 等，grep 实测）；全套 254 passed（基线 250+4） |
| 2026-08-24 | T9 review 修复二（Important×2+Minor）：① combat.py cast 分支 timed 原子补 else 分支 logger warning（"game.combat"，"timed 原子需要 world/player 注入,跳过"，与 markup 无 world 同款；原无 world/player 静默跳过无日志）；② heal 骰式回退语义两侧统一--新增 utils.roll_formula（@136，解析 NdM+K 并掷骰，不匹配返回 0；utils.py 头部补 import random，220->232 行），judge.py `_roll` 内嵌函数删除改用共享解析器（_execute_effect_atoms 内 import re/random 一并清除，judge.py 560->550 行），两侧 heal 分支统一为 `formula 掷骰 or delta 回退`（垃圾 formula 回退 delta 恢复，原 combat 保留 delta/judge 归零分叉）；注意 review 所附代码片段（`delta = max(0, roll_formula(...))` 无回退）与 review 测试预期（"两侧都回 5"）矛盾，按测试预期实现回退语义；③ MAINTENANCE.md 行号漂移修正（CombatState @131->132/CombatSystem @154->155/_get_tier @1045->1047/combat.py 1380->1382 行，grep 实测）+ utils.py 节补 roll_formula 条目；测试 +3：test_timed_without_world_skips_with_warning（combat）、test_heal_garbage_formula_falls_back_to_delta（combat+judge 各一，RED->GREEN） |
| 2026-08-24 | T9 review 修复（Important×2+Minor×2）：① run_game._run_interactive_combat @361 补传 world（第 4 个生产构造点，原 grep 范围只扫 src/frontend/tests 漏了仓库根入口脚本；CLI 交互战斗 markup/timed 原子恢复生效）；② MAINTENANCE.md CombatSystem 节"3 处构造点"纠回 4 处（旧文档正确，run_game 构造点补列入）；③ combat.py cast 分支空 type 原子加 `if t` 守卫（@923-926：空 type 无前缀直出文本，与 judge.py T6 语义一致；原实现对空 type 打 `[unknown:]` 前缀）；④ tests/test_combat_smoke.py 增 2 测试：test_empty_type_atom_no_prefix（空 type 直出不打前缀）+ test_timed_atom_refresh_same_id（同 id timed 二次施放不叠条、expire_at 取最后一次，战斗侧 refresh 回归覆盖） |
| 2026-08-24 | effect 表达力计划 T9：战斗 cast 分支 effect 数组结算（spec §1.2 战斗列）--CombatSystem.__init__ 增 world 参数（@167，markup/timed 原子作用域，可选；缺省 markup 跳过+logger "game.combat" warning），3 处生产构造点传 world（game_loop.continue_standoff @786 传 keeper.world、frontend combat_start @975 传 world、combat_round @1023 传 _world）；cast 分支 effect 段重写为原子数组遍历（@856-928，检定成功才结算；原单 dict 读法对非空数组 AttributeError）：damage（保留 _roll_damage+ignore_armor+死亡标记）/heal（formula NdM 掷骰或 delta，clamp HP_MAX）/mp_change（clamp 0..MP_MAX）/markup（parse_markup_all+apply_side_effects 走 world）/timed（挂 world.player.timed_effects，同 id refresh 语义与 T6 一致，expire_at=clock.game_time+minutes，缺省读 timed_default_minutes）/buff（挂 state.temporary_effects {id,reduce,rounds}，消费在 T10）/control（写 target.controlled_rounds，消费在 T11）/narrative（text 拼 action.narrative）/未知 type（`[unknown:{t}] text/description` 降级，永不报错）；CombatState 增 temporary_effects 字段（@144，T10 直用）；combat.py 1320->1380 行节内行号对齐（_resolve_player_action 807->809、_get_tier 985->1045 等）；tests/test_combat_smoke.py 增 TestCastEffectAtoms 9 测试（heal 上升+clamp/mp 净+1/markup SAN 通路/无 world 跳过+warning/timed expire_at/buff 写状态/control 写 target/narrative+unknown 降级/damage 保留） |
| 2026-08-23 | effect 表达力计划 T8：WorldChronicle.render_for_author 玩家行渲染 timed_effects（LLM 可见性，spec §2.3）--法术列后拼 `生效中: 描述（剩N分钟）` 块（@1655-1659，多个用「；」连接，N=max(0, expire_at-clock.game_time) 剩余分钟，缺 expire_at 按 0 兜底；无描述条目跳过；空则整块不渲染，enrich/narrator/Author 写叙事可见"帷幕还在"）；tests/test_use_system.py 增 TestTimedFactsRender 3 测试（描述+生效中标签/剩10分钟/空列表不渲染区块）；scenario_core.py 1759->1764 行，WorldChronicle 节内行号对齐（render_for_author @1644 不变、_render_event 1720->1725、to_dict/from_dict 1740/1751->1745/1756） |
| 2026-08-23 | effect 表达力计划 T7：ScenarioWorld.advance_time 三合一（推时钟+MP 恢复+timed 过期清除，spec §2.2/§4）--advance_time 末尾调新增私有 `_tick_time_effects(minutes)`（@759）：① MP 恢复余数累计（__init__ 增 `_mp_regen_acc` 分钟累计器 @699，不序列化、丢帧可接受；攒满 60 分钟按 game_config 的 mp_recovery_per_hour 回点，clamp MP_MAX，`max(0,minutes)` 防负数，函数内 import get_game_config 使 monkeypatch investigator.rules.get_game_config 生效）；② timed_effects 过期清除（`expire_at<=game_time` 恰好到期即除，logger "scenario_core" 记被清 id 与 MP 变化）；keeper.py 时间推进改走 world.advance_time 入口（@781，原直调 clock.advance_time 绕过三合一钩子，任务前提纠偏）--MP 恢复/timed 清除在真实回合流生效；tests/test_use_system.py 增 TestAdvanceTimeHooks 7 测试（整时恢复/余数累计/clamp/恰好到期清除/未到期存活/config 速率/0 速率关闭）+ tests/e2e/test_deterministic.py TestTimeAdvance 增 test_time_delta_triggers_time_hooks（回合级接线回归）；附带修复 test_game_config.py 缓存污染（test_cache_hit_no_reread_then_reset 结束后 _game_config_cache 残留 tmp 路径值而 _CONFIG_PATH 已被 monkeypatch 还原，后续文件读默认配置全被污染，teardown_function 补 reset_game_config_cache）；scenario_core.py 1727->1759 行，节内行号 grep 实测全面对齐 |
| 2026-08-23 | effect 表达力计划 T6 review 修复二（Important+Minor）：① effect 结算加成功门槛（@176-179，检定失败/refund 路径不再免费获益，on_use 既有行为不动）；② timed 同 id refresh 语义（先移除同 id 旧条再 append，重复施放刷新时效不叠条）；③ buff/control/unknown 降级分支补 logger.warning（与 damage 同款含原子内容）；④ heal delta 路径 max(0,delta) 负数归零保护（spec 定义 heal 仅 +N）；⑤ 边界测试 7 个：检定失败 effect 不生效+MP 退回、timed refresh、mp_change 下限 clamp、heal delta 直加/负 delta no-op、空 type 无前缀、降级 warning 断言；judge.py 553->560 行，节内行号 grep 核实修正（execute_material 77->78、_execute_effect_atoms 187->188 等），T6 entry @175-178 -> @176-179 |
| 2026-08-23 | effect 表达力计划 T6 review 修复：L0 纯叙事短路 guard 纳入 effect（`not getattr(material, "effect", None)`，@105-107）--原 guard 含 on_use 不含 effect，L0+on_use 走完整通路而 L0+effect 静默丢弃，非对称；修后 L0+effect 素材走完整通路执行 effect；TestExecuteMaterialEffects 增 test_l0_with_effect_not_shortcircuited（timed 挂载不因短路丢失），_mat helper 改 setdefault 支持 impact 覆盖；judge.py 552->553 行，节内行号 +1 |
| 2026-08-23 | effect 表达力计划 T6：Judge.execute_material 探索侧 effect 原子结算--on_use @markup 之后调新增 `Judge._execute_effect_atoms(effects, player)`（@186，judge.py 行数 485->552）；语义按 spec §1.2 探索列：heal（formula NdM 掷骰/delta，clamp HP_MAX）、mp_change（clamp 0..MP_MAX）、markup（@标记走 parse_markup_all+apply_side_effects 与 on_use 同通路）、timed（挂 player.timed_effects，expire_at=clock.game_time+minutes，minutes 缺省读 get_game_config 的 timed_default_minutes）、damage（探索侧无目标：logger "game.judge" warning 跳过不阻断）、buff/control（降级 description 文本）、narrative（text 进结果）、未知 type（`[unknown:{type}]` 前缀降级）；effect 行拼在 on_use 行之后进 message（@176-179）；tests/test_use_system.py 增 TestExecuteMaterialEffects 9 测试（heal/mp clamp、markup SAN 通路、timed 挂载+config 缺省、damage 跳过+caplog warning、unknown/buff/control 降级、on_use 先 effect 后顺序断言） |
| 2026-08-22 | effect 表达力计划 T5 review 修复：timed_effects 过滤条件升级为 expire_at 类型校验（isinstance(int/float)，原仅查 key 存在会放过 str/None 值，Task 7 `t["expire_at"] <= now` 会 TypeError）；丢弃数>0 记 logging.warning（"investigator.serialization" logger）；坏元素过滤测试增 str/None expire_at 两用例，roundtrip 测试增元素级拷贝别名隔离断言；TestKnownSpells 删除版本号断言（解耦，版本由 TestTimedEffectsSerialization 覆盖） |
| 2026-08-22 | effect 表达力计划 T5：Investigator 增 timed_effects 字段（timed 原子软状态 `[{id, description, expire_at}]`，expire_at=GameClock.game_time 绝对分钟数，@200）；serialization 升 v2.2（to_dict 增 timed_effects 元素级拷贝 @96；from_dict 增缺省 [] + 非 dict/无 expire_at 坏元素过滤 @186，防旧档/手改数据炸 advance_time；无版本白名单、仅 SIZ 结构校验，旧档 v2.0/2.1 继续可加载）；models/serialization 两节行号对齐 grep 实测（修正既有漂移：__init__ 152->160、check_skill 216->226、modify_stat 309->326 等）；tests/test_use_system.py 增 TestTimedEffectsSerialization 4 测试（往返/旧档缺省/新卡缺省/坏元素过滤），known_spells 往返断言 version 2.1->2.2 |
| 2026-08-22 | effect 表达力计划 T4 review 修复：resolve 构造点 effect 透传升级为元素级浅拷贝+非 dict 过滤（@153,原 list() 外层拷贝致元素 dict 别名库单例,下游变异会污染全库,对齐 T3 库层元素级拷贝不变量）；TestCatalogEffectPassthrough 增别名隔离断言（resolve/resolve_llm 两路径 `is not` 库元素）+ 新增 test_resolve_llm_result_carries_effect（假 llm_call 回灌路径 effect 不丢回归,4 测试） |
| 2026-08-21 | effect 表达力计划 T4：use_parser.py 透传 effect 原子数组--UseParseResult 增 effect 字段(@35)、ItemCatalog/SpellCatalog entries() 增 "effect" 键(list 浅拷贝透传 @69/@99)、resolve 构造点透传(@153；resolve_llm 回灌 resolve 无需另改)；行数 176->180；tests/test_use_system.py 增 TestCatalogEffectPassthrough 3 测试；use_parser 节行号全面对齐 grep 实测（UseParseResult 30->22、USE_VERBS 21->14 等） |
| 2026-08-21 | effect 表达力计划 T3（本条 2026-08-24 T14 收口巡检补录，commit 31d3376+49aee16，当时漏记 changelog）：库 effect 字段升维原子数组（spec §1.1）--src/library/spells.py 新增模块级 `_normalize_effect`（旧单 dict 自动包装 [dict]、None/缺省 -> []、list 透传逐元素浅拷贝防别名）、LibrarySpell.effect 类型 dict -> list、from_dict 接归一化；src/library/items.py 对齐（from spells.py 导入 `_normalize_effect` @8，LibraryItem 增 effect list 字段 @29，from_dict 归一化）；tests/test_use_system.py 增 TestEffectNormalize 测试（数组透传/旧 dict 包装/非 dict 过滤）；T3 review（49aee16）：元素级浅拷贝防别名断言（sp.effect[0] is not 原始元素）+ 非 dict 元素过滤 + 防御性拷贝（改 sp.effect 不污染输入 dict）共 3 测试，combat.py cast 分支补 TODO 标记（当时单 dict 读法对非空数组 AttributeError，T9 重写为原子数组遍历后消除） |
| 2026-08-21 | effect 表达力计划 T2：新增 src/library/loader.py（load_item_library/load_spell_library，core+extensions 统一扫描，base_dir 可注入）；game_loop.init_game 与 run_pipeline 两处（run_interactive/run_auto）接入统一 loader，修复管线 extensions 不可见断点（管线此前只 load_core）；新增 tests/test_library_loader.py（3 测试）；game_loop 行号同步（run_turn 339→328、autosave 三函数 666/675/686→673/682/693、行数 902→909），run_pipeline 行数 1455→1474、run_auto 1246→1245、main 1346→1344 |
| 2026-08-21 | effect 表达力计划 T1 review 修复：get_game_config 增非 dict JSON 防御（[]/null/str 回退全缺省）、类型严格化（`type is`，bool 不混入 int 缺省）、缓存返回副本（防调用方污染）；tests/test_game_config.py 增 4 测试；rules.py 表 roll_stats…calc_db 行号 off-by-one 修正（19→20 等，对齐 grep 实测） |
| 2026-08-21 | effect 表达力计划 T1：新增 game_config 参数中心（data/game_config.json + rules.get_game_config/reset_game_config_cache，缺省兜底+类型校验+模块级缓存），rules.py 头部补模块级 import json/os，原有函数行号 +2 | 
| 2026-08-21 | 前端统一资源层接线补齐：player-status/init/state JSON 补 mp/mp_max/known_spells；character-card 状态区 MP 当前/上限 + 已知法术区；game.html HUD 三条(HP/MP/SAN)+法术行；tailwind-built.css 加 coc-blue 色板 |
| 2026-08-10 | 全量重写：覆盖 src/ + frontend/ + run_*.py + scripts/ + tools/（不含 tests/、notebooks/）。补齐 monitor、module_designer 子模块、llm_player、utils 等此前缺失部分，行号按 2026-08-10 代码快照更新 |
| 2026-08-19 | 统一资源层（U6 法术 + U8 物品 + parse 规范化）落地：新增 src/library/items.py、src/library/spells.py、src/game/use_parser.py 三节；keeper/judge/combat/side_effects/scenario_core/models/serialization/rules/prompts/game_loop/run_pipeline/layered_*/前端 game.py 行号与方法同步（详见各节）|
| 2026-08-18 | 行号巡检：keeper/combat/models/layered_parser/layered_pipeline/scenario_core/run_pipeline 行号对齐实际快照（08-14~15 代码提交后部分条目未同步）；内容条目经逐函数核对无缺漏 |

---

## 总体架构

```
run_game.py / run_pipeline.py / run_step0.py (入口)
  └─ src/game_loop.py       游戏主循环 (init_game / run_turn)
  └─ src/module_designer/   模组解析管线 (layered_parser / layered_pipeline / supplement_pipeline)
       └─ src/llm.py        统一 LLM 入口 (call_deepseek) + 传感器埋点
       └─ src/prompts.py    全部 prompt 构建
       └─ src/config.py / src/config_llm.py  配置
       └─ src/utils.py      文件解析 / token 估算 / 掷骰 / 技能配置与归一
  ├─ src/game/              Keeper 回合系统 (agents/ + combat + judge + npc/enemy/boss manager + clock)
  ├─ src/scenario_core.py   数据模型 + 世界状态 (DirectedGraph / ScenarioWorld / MemoryManager / WorldChronicle)
  ├─ src/investigator/      调查员系统 (COC 7th 车卡/检定)
  ├─ src/library/           武器/敌人/Boss 资源库 + 注入器 + 判定引擎
  ├─ src/monitor/           LLM 传感器 + 降级策略 + 回合监控 (管线健康)
  ├─ src/llm_player.py      LLM 自动玩家（测试用）
  ├─ frontend/              FastAPI 服务 + 6 个路由 (launcher/game/character/editor/files/assets)
  ├─ scripts/               库提取等辅助脚本
  └─ tools/                 解析器调试工具
```

---

## 入口脚本

### run_game.py (606 行) — CLI 文字跑团主入口

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_game` | `(character_path=None)` | 主循环：init_game → 加载调查员 → 开场回合 → 命令分发（/scene /info /events /flags /char /save /load /help /spawn）→ 普通回合 → 战斗交互子循环 → 结局判定 | 44 |
| `_build_scene_snapshot` | `(world) -> dict\|None` | 从 world 构建 PlayerFacingSnapshot 格式 dict（场景/出口/时间/NPC/敌人） | 210 |
| `_scene_text` | `(world)` | `/scene` 命令：快照 → Markdown 场景文本 | 227 |
| `_g` | `(obj, key, default=None)` | dict 与 dataclass 通用安全取值 | 234 |
| `_format_snapshot_chapters` | `(snap) -> str` | 快照格式化为半结构化 Markdown（场景/角色/时间/技能） | 241 |
| `_print_turn_output` | `(snap, brief, narrative)` | 打印回合输出 | 340 |
| `_run_interactive_combat` | `(game, combat_init)` | CLI 回合制战斗子循环（调用 CombatSystem，构造传 spell_lib+world @361，T9 战斗 markup/timed 原子可用；进入战斗打印 san_log 渲染即清 @370-373+命中显示改用 ea.narrative（D100 骰值前缀保留防丢，I1）@504-506） | 355 |

### run_pipeline.py (1474 行) — 模组解析管线 CLI

| 函数/类 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_load_document` | `(path) -> str` | 按扩展名加载 .docx/.txt/.pdf | 38 |
| `_pick_file_gui` | `() -> str` | tkinter 文件对话框选文档 | 66 |
| `_pick_file_scan` | `() -> str` | 扫描当前目录列文档供选择 | 90 |
| `PipelineConfig` | dataclass | 管线配置（路径/模型/温度/执行/注入开关），to_dict/to_json/from_dict/from_json/from_wizard | 176 |
| `LLMLogger` | `(output_dir)` | 包装 llm_json/llm_text，每次调用保存 prompt+response 到 `_llm_calls/<n>/`；wrap_json @371 / wrap_text @423 / call_log @467 | 352 |
| `PipelineAborted` | exception | 用户中止管线 | 475 |
| `InteractiveRunner` | `(config)` | 运行器：`_step_dir`@529 `_save_summary`@534 `_prompt_user`@538 `_handle_retry`@552 `_handle_edit`@573 `_handle_config_change`@600 `_interact`@658 | 480 |
| `_RetryStep` | exception | 重试当前步骤 | 676 |
| `_do_step1` | `(runner, verbose)` | Step1a 结构化提取 + 1b 精修（并行）；Step1a prompt 含 runner.ilib/runner.slib 双库摘要 | 685 |
| `_do_step2a` | `(runner, verbose)` | Step2a interactions 提取；技能名白名单经 `load_skill_checks()`（U9 起读 skill_config） | 737 |
| `_do_step2bc` | `(runner, verbose)` | Step2b+2c: events+AT + L1 + L3（并行） | 773 |
| `_do_step3a_25` | `(runner, verbose)` | Step3a 去重冲突 + 2.5 NPC 档案（并行）→ 绑定 → Boss 遭遇 → 组装 L2 | 827 |
| `_do_step3b` | `(runner, verbose)` | L1↔L2 交叉核对 + WR0 注入 | 918 |
| `_do_step35_phase1` | `(runner, verbose)` | Step3.5 依赖图（含循环重试）+ Phase1 约束 | 952 |
| `_do_phase2_finalize` | `(runner, verbose)` | Phase2 精简标准化 → 重组装 → Schema/交叉引用验证 → 保存 l1/l2/l3 最终产物；技能名经 `load_skill_checks()`，`stat_names` 已删 SIZ（:1043） | 1017 |
| `run_interactive` | `(config)` | 手动步进模式（每步 [c]继续 [r]重试 [e]编辑 [m]改配置 [q]退出），支持 start_from 断点续跑；统一资源层：经 `library.loader` 加载 Item/SpellLibrary（core+extensions，T2 起管线也扫扩展库）到 runner.ilib/runner.slib | 1163 |
| `run_auto` | `(config)` | 自动模式：复用同一组 `_do_step*` 全程无交互（同载双库，经 `library.loader` 含 extensions） | 1245 |
| `main` | `()` | argparse CLI：--auto/--config/--docx/--module/--start-from/--model/--thinking-off/--weapon-lib 等 | 1344 |

### run_step0.py (184 行) — 小说 → 模组文本转写

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `STEP0_SYSTEM` | str 常量 | 两阶段系统提示（先以作者理解故事、再以设计师改写为模组格式） | 13 |
| `run_step0` | `(input_path, output_path=None)` | 读取小说 → 构建 prompt → LLM 长文本转写 → 保存 `module_step0.txt` + system/user prompt 副本 | 127 |

### run_step1b_test.py (48 行)

单步测试脚本：直接对源文档执行 Step 1b（精修浓缩），输出 condensed 文本，用于快速验证 1b 质量。
注意：模块级读 `data/modules/深渊之口/module_raw.txt`（已删）且有 LLM 副作用，不进 pytest 收集（pytest.ini `testpaths = tests` 隔离，B5/2026-08-25）。

### imp.py / test.py

`imp.py` — 两行快速 import 冒烟；`test.py` — 简单调用测试。均无函数定义。

---

## src/game/messages.py (303 行) — 消息类型 / 契约

| 类 | 字段/说明 | 作用 | 行号 |
|----|-----------|------|------|
| `IntentResult` | `needs_author, intent, reasoning` | IntentDetector 输出 | 12 |
| `AuthorRequest` | `other_texts, intent, reasoning, scene_context` | Detector→Author 请求 | 20 |
| `ActionIntent` | `action, target, skill_checks` | Parse 解析出的玩家意图 | 29 |
| `ActionOutcome` | `intent, success, message, entity_id, entity_type, side_effects, skill_tier, skill_detail, enhancement` | 单个 entity 执行结果 | 39 |
| `SceneSnapshot` | `location, description, exits, perceptible_interactions, visible_npcs` | 场景信息快照 | 53 |
| `NarratorBrief` | `action_outcomes, ambient_changes, scene_snapshot, suggested_emphasis, enriched_summary` | KP→Narrator 策展结果 | 63 |
| `ModulePatch` | `entities, scene_descriptions, justification` | Author→Keeper 实体补丁 | 73 |
| `StructuralEdit` | `supplement_path, l3_updates, entry_scene, exit_scene, justification` | Author→Keeper 结构扩展 | 81 |
| `TurnInput` | `raw_text, player, action_type, action_target` | 回合入口数据；action_type 非空 → 跳过 LLM parse | 91 |
| `CombatEntryCheck` | `enter_combat, enemy_instance_ids, reasoning` | LLM 判定是否进入战斗 | 100 |
| `StandoffMatch` | `matched, skill_name, reason` | 对峙语义匹配 | 108 |
| `CombatInit` | `enemies, player, scene, initiative_context, environment_actions, player_action, player_targets, player_extra` | →CombatSystem 初始化 | 116 |
| `CombatResult` | `outcome, defeated_instance_ids, narrative, player_hp, player_san, player_san_max, rounds, round_log` | 战斗结果；player_san_max=F2 SAN bar 分母（默认 99） | 135 |
| `SkillCheckResult` | `entity_id, entity_type, skill_name, raw_roll, target, tier, success, enhancement` | 单次技能检定记录 | 148 |
| `PlayerFacingSnapshot` | `scene_name, scene_description, exits, time, npcs, enemies, combat, skill_checks, investigator` | 面向前端/CLI 的回合快照 | 161 |
| `RoundResult` | `round, player_action, player_target, player_roll, player_tier, player_damage, player_damage_type, player_effects, enemy_actions, status_changes, narrative` | 单回合战斗结果 | 179 |
| `Phase` | `trigger, name, overrides, description` | Boss 阶段定义 | 195 |
| `TimeCommsPacket` | `game_time, day, time_of_day, current_scene, player_actions, world_state` | Keeper→Author 时间通信包 | 204 |
| `PreParseResult` | `clarity, interpretation, question, resolved_text` | Pre-parse 消歧输出 | 215 |
| `EnrichInput` | `entities, actions` | parse→enrich 中间体 | 224 |
| `TurnStatus` | Enum: COMPLETED / SUSPENDED / FROZEN | 回合终局状态 | 233 |
| `PendingInteraction` | `kind, question, interaction_id` | 挂起待答问题（weapon_offer/standoff/clarify） | 241 |
| `EndingInfo` | `name, narrative, game_over` | 结局信息 | 249 |
| `TurnDiagnostics` | `combat_entry, time_agent, enrich_raw, pre_parse` | 低频/调试数据入口 | 257 |
| `TurnResult` | `status, brief, text, pending_interaction, combat_init, ending, npc_events, warnings, frozen_message, diagnostics` | **Keeper.process_turn 内部契约返回**；`__post_init__` 校验 SUSPENDED 必须带 pending_interaction | 266 |
| `PlayerTurnResult` | `status, brief, narrative, pending_interaction, player_snapshot, skill_results, combat, combat_init, ending, game_over, timestamp, diagnostics` | **run_turn 玩家面契约返回** | 290 |

---

## src/game/agents/keeper.py (1702 行) — Keeper 回合编配

### 模块级函数

| 函数 | 作用 | 行号 |
|------|------|------|
| `_describe_time_condition` | 时间条件 → 自然语言 | 32 |
| `_build_investigator_weapon` | 库武器 → 调查员 Weapon 实例 | 71 |

### Keeper 类（@93）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(world, phase1=None)` | 初始化 Judge/Curator/IntentDetector/PreParse/AgentMonitor/TurnMonitor/UseParser（llm_call 晚绑定 call_deepseek） | 99 |
| `_material_catalogs` | `()` | 统一资源层：世界库∩玩家状态构建 use 可解析目录（ItemCatalog=持有物∩物品库；SpellCatalog=known_spells∩法术库） | 137 |
| `process_turn` | `(turn_input, author=None, _depth=0) -> TurnResult` | **主流程**：weapon_offer 应答（严格只认「是/否」，其他输入作废 offer 走正常回合）-> 直接拾取通路（捡/拾/拿+武器名直接入包）-> 深度保护 -> NPC AT 注入 -> LUCK 声明式消耗识别（「烧/用 N 点幸运」-> spend_luck，成功才置 pending_luck_bonus，原子绑定）-> pre-parse 消歧/动作捷径 -> LLM parse -> NPC 对话分流 -> 后续 parse/judge/enrich/combat/TimeAgent/Author -> curate -> memory；TimeAgent time_delta>0 时走 `world.advance_time` 三合一入口（@781，T7：时钟+MP 恢复+timed 过期清除，原直调 clock 绕过钩子） | 149 |
| `_detect_direct_pickup` | `(raw) -> str \| None` | 直接拾取意图：拾取动词+场景武器名（场景仅一件可不点名），含否定词/已持有时不触发 | 1278 |
| `_devour_standoff_for_boss` | `(standoff_prompt, combat_init_result, all_outcomes, enrich_input) -> None` | F3：Boss 强制战吞掉对峙——撤回 standoff 播种/话术，avoidable 敌人并入 Boss 战（at 与 event 两条 engage 通路共用） | 1315 |
| `_grant_scene_weapons` | `(offer_list) -> str` | 发放武器入包并从场景移除，返回「、」连接名串（offer 应答与直接拾取共用） | 1297 |
| `_build_frozen_response` | `(exc)` | TurnFrozenError → FROZEN TurnResult | 1000 |
| `_scan_ending` | `(outcomes, author)` | 检查 ##END_*## 结局标记并触发 | 957 |
| `complete_combat_turn` | `(original_input, combat_result)` | 战斗后回放 enrich→curate；入口先把 outcome 记入编年史（record_combat_end，CLI/前端/auto 全通路覆盖） | 1025 |
| `resolve_standoff` | `(standoff_state, player_input)` | 对峙：LLM 匹配技能 → D100 → 特质修正；说服族判定经 normalize_skill_name 归一（魅惑/说服两族，旧名话术/恐吓落入说服） | 1068 |
| `_check_boss_requirements` | `(boss_entity, player_action)` | Boss 遭遇触发条件检查 | 1145 |
| `_evaluate_boss_soft_condition` | `(soft_condition, player_action, boss_name)` | Boss 软条件 LLM 评估 | 1170 |
| `_inject_npc_at` | `()` | 当前场景 NPC bound entity → 注入 node | 1197 |
| `_apply_pending` | `()` | 应用延迟副作用 + 移动 + NPC 跟随实体注入 | 1236 |
| `_parse` | `(raw) -> list[dict]` | LLM parse：玩家输入 → action 列表 | 1340 |
| `_enrich` | `(judged_entities, user_input) -> dict` | LLM enrich：合并判定结果 | 1373 |
| `_log_agent_response` | `(filename, data)` | 记录 agent 响应日志 | 1403 |
| `_find_entity_by_id` | `(entity_id)` | graph+NPC+boss 按 ID 查找 | 1416 |
| `_process_deterministic_only` | `(turn_input)` | 深度超限/降级时纯确定性执行 | 1451 |
| `_build_world_brief` | `()` | 构建 pre-parse 用世界简报 | 1472 |
| `_build_world_snapshot` | `()` | 构建世界快照 dict | 1488 |
| `_infer_time_category` | `(entity)` | 实体时间类别推断 | 1500 |
| `_run_time_agent` | `(action_summaries, raw)` | 调用 TimeAgent 评估时间 | 1507 |
| `_build_scene_context_for_author` | `()` | 构建 Author 场景上下文（含 chronicle 渲染） | 1514 |
| `_integrate_supplement` | `(structural_edit, author, intent, reasoning)` | 补充管线 → 集成到 graph；成功后 record_patch(level="structural") | 1531 |
| `_load_scene_into_graph` | `(scene_name, scene_data)` | 新场景注入 graph（补充管线产物） | 1620 |
| `_integrate_patch` | `(patch)` | ModulePatch 实体集成 + record_patch(level="patch")；entity_ids 记集成后真实 id | 1674 |

## src/game/agents/narrator.py (57 行) — 叙事者

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(l1_data)` | 持有 L1 数据 | 17 |
| `narrate` | `(brief, snap=None, user_input="") -> (brief, narrative, scene_update)` | KP 简报 → 沉浸式叙事 | 24 |
| `_build_prompt` | `(brief, l1_scene, snap, user_input)` | 构建叙事 prompt | 54 |

## src/game/agents/author.py (136 行) — 作者（创作者层）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(l3_data, persona="")` | 持有 L3 数据 | 29 |
| `handle_request` | `(request, turn_number=0) -> ModulePatch\|StructuralEdit` | 两级响应：Patch / StructuralEdit | 43 |
| `update_l3` | `(l3_updates)` | 增量更新 L3 | 94 |
| `assess_time_pressure` | `(comms_packet)` | 评估时间压力 | 99 |

## src/game/agents/time_agent.py (88 行) — 时间评估

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `build_prompt` | `(actions, current_input, time_costs=None)` | 构建时间评估 prompt | 29 |
| `assess` | `(actions=None, current_input="", time_costs=None, **kwargs) -> {time_delta, narrative_hint}` | LLM 评估本轮时间消耗 | 64 |

## src/game/combat.py (1505 行) — 战斗系统 v2

CombatState dataclass（@187）：回合可变状态；F2 增 `player_san_max: int = 99`（@194，SAN bar 分母，_init_combat 从 player.derived.SAN_MAX 接线）；T9 增 `temporary_effects: list`（@200，玩家侧 buff `[{id, reduce, rounds}]`，spec §3；T10 消费：受击减伤 + 轮末递减）；2026-08-26 增 `san_log: list[str]`（@201，开局目睹 SAN check 叙事行；_init_combat 写入，三处一次性渲染后清空：_build_single_round_result 首轮 @633-636/run_combat 终局前置 @417-421/run_game CLI 进入战斗打印 @370-373）。

### 模块级函数

| 函数 | 作用 | 行号 |
|------|------|------|
| `_roll_damage` | 从 dict/legacy 公式掷伤害骰；`db_override` 非 None 时优先用作 DB（玩家侧传 derived.DB，:1019 调用点），敌人路径仍 calc_db(STR, SIZ) | 15 |
| `_parse_legacy_damage` | 旧式伤害公式解析 | 69 |
| `_apply_armor` | 护甲减免 | 96 |
| `_apply_damage_multiplier` | 伤害类型倍率 | 103 |
| `_san_loss_roll` | SAN 损失公式掷骰：纯数字直接 int，骰式走 utils.roll_formula（遭遇 SAN check 通路 Task1，2026-08-26） | 109 |
| `parse_san_loss` | 库 san_loss 字段多情境解析 `"0/1D4 (目睹), 1/1D6 (被攻击)"` -> [(成功公式, 失败公式, 情境注释), ...]，空/坏组跳过；非空 raw 解析结果为空记 combat logger debug（原文回显，M2 防坏分隔符静默禁用）@141-143 | 121 |
| `_san_check_and_lose` | COC 7th 遭遇理智检定：D100 <= 当前 SAN 为成功，掉对应组公式，返回 (损失, 叙事)；损失>=5 仅 log（F5 未实现） | 147 |

### CombatSystem（@212，__init__ @224 增 spell_lib+world 参数--统一资源层法术库/markup·timed 原子作用域（world 可选，缺省 markup 跳过+warning）；4 处生产构造点传 world.spell_library+world：game_loop.continue_standoff@786、frontend combat_start@975/combat_round@1023、run_game._run_interactive_combat@361）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_combat` | `(combat_init, player_action="", max_rounds=20) -> CombatResult` | **主入口**：完整战斗循环（确定性 → LLM 修正 → 结算 → Boss 阶段；轮末 @405 `state.round += 1` 前调 `_tick_temporary_effects`；终局叙事前置 san_log 一次性渲染 @417-421（I1，自动战斗路径目睹 check 文本玩家可见）） | 233 |
| `run_single_round` | `(combat_init, state, action_id, target_ids, player_extra="") -> dict` | 交互式单回合（前端回合制；轮末 @594 `state.round += 1` 前调 `_tick_temporary_effects`） | 434 |
| `_build_single_round_result` | `(state, combat_init) -> dict` | 单回合结果 dict（胜负判定/回合叙事；F2 增 player_san_max 键 @635；2026-08-26 轮叙事 lines 前插 state.san_log 一次性渲染 @633-636（渲染即清空）） | 598 |
| `_generate_combat_narrative` | `(state, player, scene, log_dir)` | 战斗叙事生成 | 654 |
| `_init_combat` | `(combat_init) -> CombatState` | 初始化：展开 quantity 群组，按 DEX 排先攻；player_san_max=player.derived.SAN_MAX（F2 @798）；2026-08-26 末尾目睹 SAN check @782-799：expanded_enemies 按 enemy_ref 去重（同 ref 群组只一次，跨战斗不去重 F9 跟踪），目睹组=注释不含"攻击"的第一组，扣 state.player_san（下限 0）+san_log 追加叙事行 | 735 |
| `_match_action` | `(raw_input, available)` | 文本 → 动作 ID 匹配 | 802 |
| `_get_player_actions` | `(player, environment_actions)` | 固定动作列表（拳/踢/回避/逃跑/武器/环境/施法--known_spells∩combat 类生成 cast_<id> 动作） | 834 |
| `_skill_value` | `(player, skill_name)` | 技能值查询 | 887 |
| `_resolve_player_action` | `(state, player, action_id, target_iid, environment_actions)` | 执行玩家动作（cast_* 前缀走 cast_spell 分支：习得/MP 硬门 -> 扣减 -> opposed/常规检定 -> **effect 原子数组遍历 @908-980**（T9 重写，检定成功才结算）：damage 保留 _roll_damage+ignore_armor+死亡标记 / heal（formula 掷骰（utils.roll_formula 共享）或 delta 回退，clamp HP_MAX）/ mp_change（clamp 0..MP_MAX）/ markup（parse_markup_all+apply_side_effects 走 self.world，无 world 跳过+warning）/ timed（挂 world.player.timed_effects，同 id refresh，expire_at=clock.game_time+minutes，无 world/player 跳过+warning）/ buff（挂 state.temporary_effects，T10 消费）/ control（写 target.controlled_rounds，T11 已消费：_resolve_enemy_action 顶部跳过行动）/ narrative（拼 action.narrative）/ 未知 type `[unknown:{t}]` 降级永不报错） | 898 |
| `_get_tier` | `(roll, skill_value)` | COC 四级检定 | 1136 |
| `_select_enemy_attack` | `(enemy)` | 按权重随机选攻击 | 1148 |
| `_select_enemy_target` | `(state, enemy)` | 敌人选目标 | 1156 |
| `_resolve_enemy_action` | `(state, enemy, player)` | 执行敌人动作；顶部 @1128-1134 control 检查（T11）：`controlled_rounds > 0` 时跳过行动（success=False、narrative"被无形的力量攫住，无法动弹。"、damage=0、不掷骰不耗 _player_dodging、跳过本身不递减，归零靠轮末 _tick）；命中段 @1166-1172 buff 减伤（T10）：`damage = _roll_damage(...)` 后总减免 = sum(state.temporary_effects[].reduce)，`damage = max(buff_damage_floor, damage - 总减免)`（floor 读 game_config，函数内 import get_game_config；reduce_total=0 零开销跳过）；命中分支 2026-08-26 被攻击情境 SAN check @1216-1222：parse_san_loss 取注释含"攻击"的第一组（无则跳过），扣 state.player_san，action.narrative 追加" 恐惧侵蚀：{text}。" | 1160 |
| `_tick_temporary_effects` | `(state)` | 轮末递减（T10）：temporary_effects 各条 rounds-1、归零移除（`rounds-1 > 0` 存活过滤）；enemy.controlled_rounds 递减（T11 消费：_resolve_enemy_action 顶部检查）；调用点 run_combat @405 / run_single_round @594 / run_game.py 交互循环 @521（均在 `state.round += 1` 前，共 3 处） | 1228 |
| `_check_phase` / `_apply_phase` | — | Boss 阶段切换 | 1241 / 1265 |
| `_any_special_rules` | `(combat_init, enemies)` | 是否有 special_rules 需要 LLM | 1286 |
| `_build_battle_snapshot` | `(state, player, boss_phase)` | LLM 用战斗快照 | 1296 |
| `_build_round_result` | `(state, player_actions, enemy_actions, round_num)` | RoundResult 构建 | 1315 |
| `_llm_correct_round` | `(round_result, combat_init, enemies, player_extra, battle_snapshot, boss_phase, player_actions)` | LLM 修正玩家回合伤害 | 1343 |
| `_llm_correct_enemy_round` | `(enemy, action_data, player, player_extra, investigator_context)` | LLM 修正敌人攻击 | 1450 |

## src/game/judge.py (551 行) — 确定性闸门（无 LLM 依赖）

| 函数/方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_escalate_difficulty` | `(difficulty)` | 难度递增 regular→hard→extreme | 25 |
| `Judge.check_auto_triggers` | `()` | 触发当前场景满足简单条件的全部 AT | 47 |
| `Judge.execute_interaction` | `(intent, player_input="")` | 执行解析出的互动意图 | 63 |
| `Judge.execute_material` | `(material, player_input="")` | **统一资源层 L1 执行通道**：硬门（已知法术/持有/MP/材料）-> 扣减（refund_on_fail 回滚）-> 可选检定（下沉复用 check_skill/opposed_check）-> 结果槽（tier 选档）-> on_use @markup 经 apply_side_effects 执行 -> effect 原子数组经 _execute_effect_atoms 结算（on_use 先/effect 后，@176-179；检定失败不结算 effect，防 refund 后免费获益）；L0 零消耗无检定且无 on_use/effect 时纯叙事（guard 对称含 effect,@105） | 78 |
| `Judge._execute_effect_atoms` | `(effects, player) -> list[str]` | **探索侧 effect 原子结算**（spec §1.2 探索列）：heal（formula 掷骰（utils.roll_formula 共享解析器，垃圾 formula 回退 delta）/delta≥0 归零保护，clamp HP_MAX）/ mp_change（clamp 0..MP_MAX）/ markup（@标记走 parse_markup_all+apply_side_effects 同通路）/ timed（挂 player.timed_effects，同 id refresh 替换旧条刷新时效不叠条，expire_at=clock.game_time+minutes，缺省读 game_config 的 timed_default_minutes）/ damage（探索侧无目标：跳过+logger warning，不阻断）/ buff+control（降级文本进结果+logger warning；文本取 description 优先、回退 on_text（战斗向 buff 原子字段，与 combat.py 同源）、最后兜底「仅在战斗中生效」）/ narrative（text 进结果）/ 未知 type（`[unknown:{type}]` 前缀降级+logger warning）；永不报错阻断 | 188 |
| `Judge._execute_entity` | `(entity, intent=None, player_input="")` | **核心**：重复执行拦截 → NPC 特殊实体(follow/interact unlock) → 硬 requirement → 技能检定+特质增强 → ##GRADED## 解析 → @markup 剥离 → 失败惩罚/难度递增 → 完成标记 | 273 |
| `_split_requirement` | `(req) -> (hard, soft)` | `\|\|` 拆分硬/软条件 | 481 |
| `_is_simple_requirement` / `_check_simple_requirement` | — | AT 简单条件判定 | 492 / 503 |
| `_evaluate_requirement` | `(req) -> (bool, msg)` | flag: → AND/OR 解析 → 边依赖检查 | 514 |

## src/game/curator.py (68 行) — 策展器

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `assemble` | `(outcomes, ambient_changes, emphasis="", enriched_summary="") -> NarratorBrief` | 判定结果 + 场景快照 → NarratorBrief | 17 |
| `_build_snapshot` | `() -> SceneSnapshot` | 收集当前场景元数据 | 32 |

## src/game/side_effects.py (150 行) — @markup 副作用

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `ItemGain` / `ConsumeItem` / `StatChange` / `SpawnEnemy` / `GrantWeapon` / `GrantSpell` / `SceneWeapon` / `NPCStateChange` / `NPCFollow` | @标记 dataclass（GrantSpell：spell_ref + category 描述性，统一资源层第 8 种 markup） | 8–59 |
| `_parse_kwargs` | `@标记(...)` 参数解析 | 74 |
| `_build_side_effect` | 函数名+kwargs → dataclass | 81 |
| `parse_markup` | 解析单个文本中的 @标记 | 137 |
| `parse_markup_all` | `(text) -> list` 解析全部 @标记 | 147 |

## src/game/use_parser.py (180 行) - UseParser（统一资源层 use 大类独立 parse 系统）

| 类/函数 | 签名 | 作用 | 行号 |
|---------|------|------|------|
| `UseParseResult` | dataclass | 解析结果：catalog_kind(item/spell 描述性), material_id, name, matched_text, impact, check, cost, on_use, result_slots, refund_on_fail, use_semantic, constraints, effect(list 原子数组, 库预标注, Task 6 探索侧结算消费) | 22 |
| `MaterialCatalog` | Protocol | 目录协议（entries() -> 可解析条目 dict 列表）；待解析内容可换 | 38 |
| `ItemCatalog` | `(item_lib, inventory)` | 物品目录：持有物∩物品库（自由文本物品不进机械通路）；entries() 透传 effect（list 浅拷贝, @69） | 44 |
| `SpellCatalog` | `(spell_lib, known_spells)` | 法术目录：known_spells∩法术库；entries() 透传 effect（list 浅拷贝, @99） | 74 |
| `_best_material_match` | `(raw, entries)` | 精确 -> 包含 -> difflib(>=0.6) 三级匹配 | 104 |
| `UseParser.__init__` | `(llm_call=None)` | llm_call 可注入（keeper 晚绑定 call_deepseek） | 128 |
| `UseParser.resolve` | `(raw, catalogs)` | **确定性层**：否定词排除 -> USE_VERBS 谓词 -> 三级名称匹配 -> UseParseResult（effect 自 entry 透传 @153：元素级浅拷贝+非 dict 过滤,不别名库单例；resolve_llm 回灌本方法,无需另改） | 132 |
| `UseParser.resolve_llm` | `(raw, catalogs)` | **LLM 兜底**：build_material_fuzzy_prompt -> 目录校验回灌 resolve | 157 |
| `USE_VERBS` / `_NEGATION_RE` | 常量 | 使用谓词表 / 否定词正则 | 14 / 18 |

## src/game/npc_manager.py (411 行) — NPC 管理

### NPC dataclass（@10）字段：`name, role, personality_notes, appearance, what_they_can_do, interaction_triggers, can_follow, follow_requirements, can_interact, interact_requirements, bound_interactions, bound_auto_triggers, scene, attitude, following, memory, state, extra`

### NPCManager（@85）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_check_follow_conditions` | `(npc, world)` | 跟随条件检查 | 94 |
| `init_from_profiles` | `(profiles)` | 从 L2 npc_profiles 批量初始化 | 131 |
| `get` | `(name)` | 按名查询 | 155 |
| `get_in_scene` / `get_in_scene_snapshot` | — | 场景内 NPC（排除 dead/left）/ 轻量快照 | 158 / 162 |
| `talk_to` | `(npc_name, player_input, llm_call, world=None)` | state→can_interact→interact_requirements 门禁 → LLM 对话 | 175 |
| `set_attitude` / `set_following` / `get_following` / `set_state` / `set_scene` | — | 状态操作 | 244–259 |
| `sync_followers` | `(scene)` | 跟随 NPC 同步到新场景 | 265 |
| `to_dict` / `from_dict` | — | 序列化 | 273 / 289 |
| `process_npc_turn` | `(npc_name, user_input, world, llm_json, llm_text, judge, curator)` | 独立 API：talk_to→parse→judge→enrich→curate（主循环不调用） | 315 |

## src/game/enemy_manager.py (275 行) — 敌人管理

### EnemyInstance 字段：`instance_id, enemy_ref, scene, quantity, status, flags, combat_behavior, description, attributes, armor, attacks, special_abilities, san_loss, hp, boss_mechanics, multi_attack, damage_multipliers, dodge_bonus, special_rules, phases, _current_phase`

### EnemyManager（@40）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `spawn` | `(enemy_ref, scene, quantity=1)` | 从库实例化（同场景同类合并） | 47 |
| `remove` / `set_status` / `register` | — | 状态操作 | 89 / 139 / 143 |
| `get_active_in_scene` / `get_active_in_range` / `get_active_in_scene_snapshot` / `group_by_ref` / `get_by_id` | — | 查询族 | 94–160 |
| `add_to_combat` / `mark_defeated` / `mark_dead` | — | 战斗标记 | 147–157 |
| `enter_combat` / `exit_combat` | — | 批量 engaged / win→defeated、非 win→hostile | 163 / 170 |
| `get_combat_context` | `(scene, graph=None)` | 战斗判定用文本 | 185 |
| `to_dict` / `from_dict` | — | 序列化 | 201 / 227 |

## src/game/boss_manager.py (140 行) — Boss 管理

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `has_spawned` / `mark_spawned` | — | 防重复开战 | 14 / 17 |
| `check_by_engage_type` | `(engage_type, *, scene=None)` | 按 at/interaction/event 过滤遭遇 | 20 |
| `_create_instance` | `(boss_entity, scene)` | Boss 库 → EnemyInstance（CON+SIZ→HP） | 31 |
| `spawn_instance` | `(boss_entity)` | init 时预生成实例 | 69 |
| `build_combat_init` | `(boss_entity, player, scene, enemy_manager=None)` | 复用预生成实例或新建 → CombatInit | 73 |
| `active_boss_id` / `set_active` | property / setter | 活跃 Boss | 92 / 103 |
| `resolve_outcome` | `(combat_result)` | 战斗结果透出 | 106 |
| `active_snapshot` | `()` | 快照中的活跃 Boss 信息 | 111 |
| `to_dict` / `from_dict` | — | 序列化 | 126 / 135 |

## src/game/clock.py (60 行) — 游戏时钟

| 成员 | 说明 | 行号 |
|------|------|------|
| `day` / `hour` / `time_of_day` | property：分钟 → 天/小时/5 时段（夜间/早晨/白天/黄昏） | 14 / 18 / 22 |
| `advance_time` | `(minutes)` 推进时钟 | 34 |
| `get_time_flags` | `{day:N:True, time:period:True}` | 37 |
| `to_dict` / `from_dict` | 序列化 | 43 / 54 |

## src/game/pre_parse.py (89 行) — 消歧网关

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `disambiguate` | `(player_text, world_brief="") -> PreParseResult` | 判断输入清晰/模糊，跨 turn 整合，模糊 → 提问（SUSPENDED） | 32 |

## src/game/intent_detector.py (65 行) — 叙事意图检测

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `detect` | `(other_text, world_snapshot) -> IntentResult` | Flash 模型判断 'other' 输入是否有真实叙事意图（与 Enrich 并行）；降级时默认触发 Author | 23 |
| `_build_prompt` | `(other_text, world_snapshot)` | 构建检测 prompt | 47 |

## src/game/turn_logger.py (47 行) — 回合日志

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `log` | `(player_input, enrich_result, narrator_brief, narrator_narrative)` | 回合写为 `turn_NN.json` + `turn_log.jsonl` | 23 |

---

## src/game_loop.py (910 行) — 游戏主循环

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `set_turn_logger` | `(logger)` | 设置全局回合日志器（harness/入口调用） | 21 |
| `setup_logging` | `() -> str` | 统一初始化日志目录 + TurnLogger + prompt/llm 日志 | 27 |
| `_handle_spawn_command` | `(user_input, world, weapon_lib=None, enemy_lib=None, injector=None, keeper=None)` | 调试命令：/spawn enemy\|weapon、/inject [toggle\|status]、/health（TurnMonitor/PipelineHealth 快照） | 46 |
| `init_game` | `(l2_path, l1_path, l3_path, start_node="6号车厢", wr0_enabled=False) -> dict` | 从 JSON 初始化：_scene_names 重映射 → 库加载（物品/法术经 library.loader 统一加载 core+extensions，@224-226）→ ScenarioWorld → world 节点 AT 执行（延后 item_gain）→ at 型 Boss 预生成 → time_costs → Narrator/Keeper/Author | 155 |
| `run_turn` | `(game, user_input, weapon_lib=None, enemy_lib=None, injector=None, action_type="", action_target="") -> PlayerTurnResult` | **一回合**：自动存档检查 → 调试命令 → 对峙挂起分发 → keeper.process_turn → 回合末写编年史（chronicle.record_turn + 移动轨迹，FROZEN 不计，SUSPENDED 也入史）→ SUSPENDED/FROZEN 短路 → Narrator 叙事 → 场景更新 → 技能检定提取 → PlayerFacingSnapshot 组装（L1 描述/NPC 富化/技能 D100 解析） | 328 |
| `save_game` | `(game, path)` | 存档 + `_meta.turn_number` 写入 | 631 |
| `load_game` | `(game, path)` | 读档并回填世界属性 + turn_number | 647 |
| `_autosave_callback` / `start_autosave` / `_check_autosave` | — | 定时自动存档（AUTOSAVE_INTERVAL_SEC，最多 AUTOSAVE_MAX_COPIES 份轮换） | 673 / 682 / 693 |
| `continue_standoff` | `(keeper, player_input) -> TurnResult` | 对峙回避尝试：成功→下一组/进入战斗；失败→战斗；战斗内联跑（自动胜利短接；CombatSystem 构造传 spell_lib+world @786，T9 战斗 markup/timed 原子可用）→ complete_combat_turn | 710 |
| `format_turn_dynamic` | `(player_snapshot, brief, narrative) -> str` | 快照动态信息（时间/战斗/技能检定）+ 叙事 → 纯文本（CLI/LLM 玩家复用） | 827 |

---

## src/scenario_core.py (1771 行) — 数据模型 + 世界状态

### 数据类 / 基础模型

| 类 | 字段/说明 | 行号 |
|----|-----------|------|
| `Edge` | `target, method, requirement` — 场景通行边 | 39 |
| `Requirement` | `raw, entity_id, negated, flags` — 条件解析结果 | 49 |
| `Interaction` | 互动摘要模型 | 57 |
| `ActionResult` | `success, message, ...` | 71 |
| `Entity` | `id, entity_type, name, scene, type, requirement, trigger, result, side_effects, graded_result, difficulty, extra, time_condition` — 统一实体；`from_dict` 工厂 @109 | 89 |
| `Node` | `node_id, description, edges, to_here, interactions, auto_triggers, encounters, scene_weapons, extra`；`get_interaction`@264 `get_auto_trigger`@270 | 253 |
| `NodeRuntimeState` | `completed, result_tier, retries, escalated_difficulty` | 278 |

### 顶层函数

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `read_json_file` | `(file_path)` | 读 JSON | 29 |
| `find_entity_by_id` | `(world, entity_id)` | 场景+事件+NPC 联合查找 | 77 |
| `resolve_graded_result` | `(entity, tier) -> str` | 解析 `##GRADED##` 四档结果 | 138 |
| `has_ending` | `(text) -> (name, narrative)` | 检测 `##END_*:desc##` | 162 |
| `check_time_condition` | `(time_condition, day, time_of_day)` | 时间条件检查 | 173 |
| `_normalize_requirement` / `_side_effect_to_dict` | — | 内部工具 | 213 / 228 |
| `parse_hard_requirement` | `(hard, runtime_state)` | AND/OR/括号/flag 条件解析 | 563 |
| `apply_side_effects` | `(world, side_effects, npc_events=None, direct_weapon_callback=None)` | 副作用应用到世界（spawn_enemy/grant_weapon/stat_change/item_gain/consume_item/npc_state_change/npc_follow）（统一资源层：GrantSpell 分支经 spell_library 校验加入 known_spells，不重复授予） | 1251 |

### DirectedGraph（@290）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `load_scenes` / `load_events` | — | 从 dict/list 加载 | 307 / 347 |
| `get_edges_from` / `get_interactions` | — | 查询出边/互动 | 356 / 361 |
| `get_event` / `get_all_event_ids` | — | 事件查询 | 366 / 369 |
| `remove_node` / `remove_edge` | — | 图修改（补充管线用） | 374 / 382 |
| `to_dict` / `from_dict` | — | 序列化 | 399 / 450 |

### RequirementResolver（@504）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `check` / `get_unmet` / `resolve_chain` | — | 条件解析（check @510 / get_unmet @528 / resolve_chain @545） | 504 |

### ScenarioWorld（@650）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `__init__` | `(graph, start_node, background_story, wr0_enabled, enemy_library, weapon_library, boss_library, boss_encounters, npc_profiles, item_library, spell_library)` | 初始化世界 + Clock/EnemyManager/NPCManager/BossManager/MemoryManager/WorldChronicle（统一资源层：item_library/spell_library 挂载，init_game 注入；时间钩子：`_mp_regen_acc` MP 恢复分钟累计器 @699，不序列化） | 663 |
| `game_time` / `day` / `hour` / `time_of_day` / `time_context` | property | 时钟透出 | 722–742 |
| `advance_time` | `(minutes)` | **三合一**（spec §2.2/§4）：推进时钟 + 注入时间标记（注入前先清旧 `day:`/`time:` 前缀 flag 防长期局累积进 prompt/存档，ISSUES B2，旧档下次推进自动清理无需迁移） + 调 `_tick_time_effects` 时间钩子（keeper 每回合经 TimeAgent time_delta 走此单一入口） | 750 |
| `_tick_time_effects` | `(minutes)` | 时间钩子（私有）：① MP 恢复余数累计--`_mp_regen_acc` 攒 60 分钟按 game_config 的 `mp_recovery_per_hour` 回点，clamp MP_MAX，`max(0,minutes)` 防负数；② timed_effects 过期清除--`expire_at<=clock.game_time` 恰好到期即除；logger "scenario_core" 记 MP 变化/被清 id；get_game_config 函数内 import（monkeypatch investigator.rules.get_game_config 生效） | 766 |
| `load_dependency_graph` | `(dep_graph)` | 加载 L2 依赖图 → 注册 Boss 节点 | 809 |
| `get_runtime_state` / `get_incoming_edges` / `check_edge_requirements` | — | 运行时状态/依赖检查 | 838 / 844 / 849 |
| `mark_completed` / `is_entity_completed` | — | 完成标记 | 869 / 876 |
| `set_background` / `set_player` / `load_player` | — | 状态设置 | 885–895 |
| `get_current_description` / `get_possible_exits` / `get_available_interactions` | — | 场景查询 | 905–912 |
| `is_interaction_completed` / `are_entity_requirements_met` | — | 完成/条件判断 | 922 / 926 |
| `get_scene_summary` / `get_scene_info` | — | 场景汇总（前端/NPC 用） | 941 / 990 |
| `move` | `(target) -> ActionResult` | 移动 + NPC 跟随同步 | 1013 |
| `is_event_triggered` / `get_active_event_effects` | — | 事件状态 | 1038 / 1041 |
| `build_snapshot` | `() -> dict` | **单源快照**供所有 prompt builder/前端 | 1050 |
| `set_npc_state` / `get_npc_state` | — | NPC 状态快捷 | 1083 / 1086 |
| `apply_world_update` / `apply_scene_update` | — | 叙事回写 | 1090 / 1094 |
| `to_dict` / `from_dict` | — | 序列化（含 `chronicle` 键） | 1099 / 1140 |
| `save_state` / `load_state` | — | 全量存档/恢复 | 1172 / 1191 |

### MemoryManager（@1418）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `add_record` / `note_item` / `should_compress` / `compress` / `get_context` | — | 交互记录 / 物品记忆 / LLM 压缩 / 上下文构建 | 1433–1493 |
| `to_dict` / `from_dict` | — | 序列化 | 1515 / 1525 |

### WorldChronicle（@1542）— 世界状态摘要层（LLM 饲料，本期消费者=Author；挂载于 ScenarioWorld.chronicle）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `record_turn` | `(turn_number, raw_input, result, world)` | 每回合末记录事件（窗口15）+ entity_results（截断100）；通道：intent/entities/at/spawn(SpawnEnemy 副作用)/pending/combat start/ending/npc/boss diff | 1561 |
| `_diff_boss` | `(world) -> list[str]` | Boss 增量 diff（engage/defeated），基准集 `_boss_seen_spawned/_boss_seen_dead` 入档防读档重报；逻辑同 llm_player._collect_mech_line | 1602 |
| `record_combat_end` | `(outcome, world)` | 战斗结算后标注当回合 combat_end + 同回合补 boss defeated（由 keeper.complete_combat_turn 统一调用） | 1624 |
| `record_patch` | `(turn, level, entity_ids, new_scenes, justification)` | 补丁清单（append-only，justification 截断100）；entity_ids 为集成后真实 id（含 NEW_xxx 回退） | 1635 |
| `compress_events` | `(llm_call)` | LLM 蒸馏预留接口，本期不接线（NotImplementedError） | 1645 |
| `render_for_author` | `(world) -> str` | 渲染【世界真值】（玩家行含 HP/SAN/MP_MAX、武器+关键物品+已知法术、timed_effects 生效中块（描述+剩X分钟，空则不渲染，LLM 可见性 2026-08-21 spec §2.3）、敌人、Boss 块：已开战状态/阶段 + 未遭遇清单）+【已注入内容】+【编年史】 | 1651 |
| `_render_event` | `(e) -> str` | 单条事件紧凑渲染（含 combat=end(outcome)） | 1732 |
| `to_dict` / `from_dict` | — | 序列化（events 转 list + boss_seen 两集合） | 1752 / 1763 |

---

## src/investigator/ — 调查员系统（COC 7th）

### models.py (448 行)

| 类/方法 | 说明 | 行号 |
|---------|------|------|
| `Stats` / `DerivedStats` / `Skill` / `Occupation` / `Weapon` / `InventoryItem` | 数据类（U9：Stats 删 SIZ、DerivedStats 删 MOV，HP_MAX=CON//3；统一资源层增 MP_MAX=floor(POW/5)；Skill.category=属性归属拼接如 "INT、EDU"） | 14–81 |
| `_carry_current` | `(current, old_max, new_max)` | 模块级：上限变化携带当前值（涨上限同步涨差值，降上限 clamp） | 148 |
| `ItemManager` | 背包：add/remove/has/get/list_all/describe/to_dict/from_dict | 89–139 |
| `Investigator.__init__` | 构造调查员（含 check_warnings / pending_luck_bonus / label / known_spells 已知法术列表 / timed_effects 定时效果软状态 `[{id, description, expire_at}]`，2026-08-21 spec §2） | 160 |
| `skills_dict` / `get_skill` / `get_skill_value` | 技能查询（get_skill 经 normalize_skill_name 归一） | 205 / 211 / 220 |
| `check_skill` | `(skill_name, difficulty="regular")` D100 检定：五路归一（skill/attr/pseudo/ignore/unknown），未掌握记 check_warnings 默认放行 | 226 |
| `_roll_d100` | `(name, target)` 骰点+等级判定；消费 pending_luck_bonus（一次性 -N） | 247 |
| `spend_luck` | `(n)` 声明式消耗 LUCK，余额不足/N≤0 拒绝 | 268 |
| `check_skills` | `(skill_names)` 批量检定 | 277 |
| `build_snapshot` | 玩家状态快照（统一资源层增 mp_max / known_spells 字段） | 295 |
| `_recalc_derived` | 重算衍生属性：只重算上限/DB/BUILD/DODGE，当前值（HP/MP/SAN）经 _carry_current 携带或 clamp，SAN 永不重置 | 315 |
| `modify_stat` | `(stat_name, delta)` 支持骰子公式；SIZ->CON 映射（spec 7.2 旧模组兼容）；CON 变化按 HP_MAX=max(1,CON//3) 重算并压 HP | 326 |
| `modify_skill` / `has_item` / `list_items` | - | 410 / 417 / 421 |
| `add_weapon` / `remove_weapon` | 武器管理 | 425 / 428 |
| `save` / `load` | JSON 存档 | 435 / 441 |

### rules.py (370 行) — 纯函数规则引擎（U9：衍生公式 + 属性池分配；头部模块级 import copy/json/math/os/random；F2：六函数数值参数收编读 game_config；T8：roll_stats 骰面读 skill_config.dice）

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `roll_stats` | `() -> Stats` | 掷骰生成属性（无 SIZ）：骰面读 skill_config.attributes.dice（[count,sides] 或 [count,sides,flat]，INT/EDU=2D6+6），总乘数读 game_config.stat_roll_multiplier | 20 |
| `_calc_db_build` | `(key)` | DB/BUILD 查表（键=STR+CON//2），表读 game_config.db_build_table（max_key None=兜底行，空表返回 ("0",0)） | 40 |
| `calc_derived` | `(stats, age=20, cthulhu_mythos=0)` | 衍生属性：HP/MP/DODGE 除数与 SAN 上限基数读 game_config.derived，删 MOV | 49 |
| `create_skill_list` | `() -> list[Skill]` | 从 skill_config.json 生成 20 项技能 | 70 |
| `allocate_skill_points` | `(skills, stats, focus=None, focus_bonus=0)` | U9 属性池分配（池=属性×乘数，均分归属技能，no_pool 除外）；技能值上限读 game_config.skill_value_cap | 81 |
| `calc_occupation_points` | `(formula, stats)` | 职业点公式（旧 Occupation 兼容） | 115 |
| `apply_age_modifiers` | `(stats, age)` | 年龄修正，阈值/档位/三组惩罚表读 game_config.age_modifiers；tier 统一 clamp 至三表（app/phys/edu）最短可用档，不对称配置不 IndexError | 142 |
| `get_credit_level` | `(value)` | 信用等级，表读 game_config.credit_rating_table（原模块级 CREDIT_RATING_TABLE 常量已删） | 175 |
| `create_default_unarmed` | - | 默认徒手武器，伤害读 game_config.unarmed_damage | 189 |
| `load_occupations` | `(path)` | 旧职业 JSON 加载（兼容） | 203 |
| `load_occupation_labels` | `(path=None)` | U9 职业标签加载（occupation_labels.json） | 221 |
| `calc_db` | `(STR, SIZ)` | DB 字符串（敌人侧保留） | 231 |
| `opposed_check` | `(att_value, def_value) -> ("win"/"lose"/"tie", detail)` | **统一资源层对抗检定纯函数**：等级>技能值>平局；战斗/探索两侧复用 | 267 |
| `_opposed_roll` / `_TIER_RANK` | - | 单侧掷骰+四级判定 / 等级序表 | 252 / 249 |
| `_GAME_CONFIG_DEFAULTS` / `_CONFIG_PATH` | 模块级常量 | 数值参数缺省表 10 键（F2：mp_recovery_per_hour/timed_default_minutes/buff_damage_floor/stat_roll_multiplier/skill_value_cap/unarmed_damage/derived/db_build_table/age_modifiers/credit_rating_table，与 data/game_config.json 逐键镜像）/ data/game_config.json 路径（测试 monkeypatch 切入点） | 287 / 316 |
| `reset_game_config_cache` | `() -> None` | 测试用：清空 `_game_config_cache` 模块级缓存 | 321 |
| `_cfg_shape_ok` | `(v, dv) -> bool` | 嵌套配置形状校验（F2，T8 升级行深校验）：顶层/嵌套 dict 必需键齐全递归校验；list 非空且按首元素模板深校验行结构（行内 dict 键齐全+标量类型匹配或 None 特赦——db_build_table.max_key 兜底行合法；list 行等长逐位类型；标量行类型一致）；标量 `type is` 严格（bool 不混入 int） | 327 |
| `get_game_config` | `() -> dict` | **game_config 参数中心**：惰性加载 data/game_config.json，缺省兜底 + 非 dict JSON 防御（回退全缺省）+ 字段校验走 `_cfg_shape_ok`（dict 嵌套与 list 行结构坏值均整体回缺省）+ 模块级缓存（每次返回 `copy.deepcopy` 深拷贝，嵌套 dict/list 不与缓存共享引用，防调用方污染）；文件缺失/损坏静默回缺省。MP 恢复/timed 默认时长/buff 减伤下限/F2 衍生查表等统一从此读取 | 353 |

### serialization.py (195 行) — v2.2：删 SIZ/MOV 字段，旧卡（含 SIZ）拒绝加载；v2.2 增 timed_effects

| 函数 | 说明 | 行号 |
|------|------|------|
| `_occupation_dict_to_obj` | 职业 dict→对象 | 15 |
| `to_dict` / `to_json` | Investigator → dict/JSON（meta.version="2.2"，personal 含 label，known_spells 列表拷贝 / timed_effects 元素级拷贝 @96） | 27 / 100 |
| `from_dict` / `from_json` | dict/JSON → Investigator；stats 含 SIZ 即抛 ValueError 提示重建；timed_effects 缺省 []，过滤非 dict / expire_at 非数字（int/float，防 str/None 炸 Task 7 的 `<=` 比较）坏元素 @186，丢弃数>0 时记 logging.warning；无版本白名单（仅结构校验），旧档 v2.0/v2.1 继续可加载 | 107 / 191 |

---

## src/library/ — 资源库

### enemies.py (180 行) — EnemyLibrary（@137）

| 方法 | 作用 | 行号 |
|------|------|------|
| `load_core` / `load_extension` / `_load_file` | 加载 core + 扩展 | 143 / 150 / 153 |
| `get` / `list_all` / `search` / `__len__` | 查询族 | 160–176 |

数据类：`EnemyAttack`@11 `SpecialAbility`@46 `LibraryEnemy`@59（`from_dict` 解析 [flag] 标记）。

### weapons.py (136 行) — WeaponLibrary（@91）

| 函数/方法 | 作用 | 行号 |
|-----------|------|------|
| `_damage_str_to_dict` | 伤害字符串 → dict | 10 |
| `load_core` / `load_extension` / `_load_file` | 加载 | 97 / 104 / 107 |
| `get` / `list_all` / `search` / `__len__` | 查询族 | 114–132 |

### items.py (95 行) - ItemLibrary（统一资源层，@61）

| 方法 | 作用 | 行号 |
|------|------|------|
| `load_core` / `load_extension` / `_load_file` | 加载 data/library/core/items.json + 扩展；_load_file（B7，@73）损坏 JSON/OSError -> `ValueError("库文件加载失败: {path}")`、顶层非 dict -> `ValueError("库文件格式错误(顶层应为 object): {path}")`（报错带来源路径，core/extensions 共用） | 63 / 70 / 73 |
| `get` / `list_all` / `__len__` | 查询族（id/名称/别名三路 matches） | 85–95 |

数据类 `LibraryItem`@12：`id, name, aliases, category(consumable/tool/document/clothing/key/misc), description, impact(L0/L1/L2 库预标注), use_semantic(consume/equip/read/tool/none), stackable, check{skill,type}, on_use(@markup 序列), on_success/on_failure/on_hard/on_extreme, refund_on_fail, constraints, effect(list[dict] 原子数组, 2026-08-21 spec §1.1)`。effect 字段（T3，@29）：from_dict 经 `_normalize_effect`（自 spells.py 导入 @8）归一化——旧单 dict 包装为 [dict]，list 透传，缺省 []（@50）。

core 条目内容（T12 升维，2026-08-24）：NECRONOMICON_PAGE on_use 双 markup（`@stat_change(SAN,-1D4)` + `@grant_spell(spell_ref="DREAM_GAZE")`，读残页学法术通路示范）；SALT effect=[timed(id SALT_LINE, minutes 60)]（探索侧挂 timed_effects，T6 结算/T8 渲染）。其余 10 条无 effect（纯叙事 L0 为主）。

### spells.py (102 行) - SpellLibrary（统一资源层，@62）

| 函数/方法 | 作用 | 行号 |
|------|------|------|
| `_normalize_effect` | effect 归一化：旧单 dict -> [dict]；None/缺省 -> []；list 透传（逐元素浅拷贝，忽略非 dict 元素） | 9 |
| `load_core` / `load_extension` / `_load_file` | 加载 data/library/core/spells.json + 扩展；_load_file（B7，@80）损坏 JSON/OSError -> `ValueError("库文件加载失败: {path}")`、顶层非 dict -> `ValueError("库文件格式错误(顶层应为 object): {path}")`（与 items.py 同款，core/extensions 共用） | 70 / 77 / 80 |
| `get` / `list_all` / `__len__` | 查询族（id/名称/别名三路 matches） | 92–102 |

数据类 `LibrarySpell`@19：`id, name, aliases, category(combat/exploration), description, impact, cost{mp,san}, check{skill,type}, on_use, on_success/on_failure/on_hard/on_extreme, refund_on_fail, constraints, effect(list[dict] 原子数组, 2026-08-21 spec §1.1), weight`。effect 字段（T3，@35）：由旧单 dict（damage 类）升维为原子数组，from_dict @56 调 `_normalize_effect`；旧 JSON 单 dict 数据自动包装为单元素数组。combat.py cast 分支已由 T9 重写为原子数组遍历（@856-928，见 combat.py 节）。

core 条目内容（T12 升维，2026-08-24，8 条中 5 条带 effect）：STONE_SKIN=[buff(reduce 3, rounds 3, self)+timed(minutes 30)]（T10 减免/T6 挂载）；DOMINATE=[control(rounds 2, enemy)]（T11 跳过）；SILENCE_VEIL=[timed(minutes 10)]；HEART_ARREST/BLOOD_CALL=[damage(1D6 ignore_armor)/damage(1D4)]（显式数组）。LIFE_DETECTION/WITCH_LIGHT/DREAM_GAZE 无 effect（纯叙事，on_success 承载）。

### loader.py (31 行) - 统一库加载器（T2，2026-08-21 spec §6）

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_load` | `(core_cls, core_file, ext_subdir, base_dir)` | 内部通用：load_core(base/core/<file>) + 扫 base/extensions/<subdir>/*.json 逐个 load_extension | 15 |
| `load_item_library` | `(base_dir=None) -> ItemLibrary` | 物品库统一加载（base_dir 缺省=包相对 data/library 绝对路径，供测试注入） | 26 |
| `load_spell_library` | `(base_dir=None) -> SpellLibrary` | 法术库统一加载（同上） | 30 |

调用点：game_loop.init_game（@224-226）、run_pipeline.run_interactive/run_auto（@1175-1177 / @1257-1259；管线修复：此前只 load_core 不扫 extensions，用户扩展库管线不可见）。`_DATA_ROOT`@12 = src 上两级 data/library（绝对路径，摆脱 game_loop 旧 cwd 相对路径依赖）；cwd 独立性由 tests/test_library_loader.py test_data_root_cwd_independent 锁定（B12，2026-08-25）。

### bosses.py (79 行) — BossLibrary（@48）

| 方法 | 作用 | 行号 |
|------|------|------|
| `_load` / `_load_extensions` | 加载 bosses.json + 扩展目录 | 57 / 66 |
| `get` / `list_names` / `__len__` | 查询族 | 72–78 |

### injector.py (101 行) — ContentInjector

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `offline_inject_scene` | `(scene_data, l3_scene_intent=None)` | 离线按 danger_level 预填 encounter/weapon | 34 |
| `offline_inject_module` | `(l2_data, l3_data)` | 全场景离线注入 | 52 |
| `runtime_spawn_enemy` | `(enemy_name, scene_name, world=None)` | 运行时敌人遭遇 dict | 64 |
| `runtime_grant_weapon` | `(weapon_name)` | 运行时武器 dict | 81 |
| `status` | property | 注入状态 | 95 |

### judgment.py (123 行) — JudgmentEngine（Tier2 桩）

| 方法 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `tier1_skill_check` | `(skill_value, difficulty="regular") -> Tier1Result` | D100 检定（桩） | 40 |
| `tier1_damage_roll` | `(damage_formula, db=0)` | 伤害掷骰 | 56 |
| `tier1_san_check` | `(san_loss)` | SAN 检定 | 86 |
| `build_tier2_context` | `(tier1, enemy, weapon, world)` | Tier2 上下文 | 106 |

---

## src/monitor/ — 管线监控（LLM 埋点 + 降级 + 回合冻结）

### sensor.py (95 行) — LLMSensor 零侵入埋点

| 类 | 说明 | 行号 |
|----|------|------|
| `LLMCallRecord` | dataclass：一次 LLM 调用记录（label/model/耗时/状态/长度/tokens） | 9 |
| `AgentStats` | 聚合统计；`update(records, slow_threshold_ms)` 计算失败率/慢调用率（最近 20 条） | 23 |
| `LLMSensor` | `record()`@51 记录；`get_records/get_stats`@65/70；`history`@77；`consecutive_failures`@81；`recent_slow_rate`@91 | 44 |

### agent_monitor.py (86 行) — AgentMonitor 每 agent 监控

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `DegradationPolicy` | Protocol：on_timeout / on_consecutive_failures / on_degrade | 13 |
| `AgentMonitor.call` | `(llm_fn, prompt, **kwargs)` 包装 LLM 调用：降级时跳过/换模型/调 thinking；记录成功失败；恢复计数 | 29 |
| `_maybe_trigger` | 连续失败 ≥ LLM_MAX_CONSECUTIVE_FAILURES 或慢调用率超阈值 → 置 degraded | 72 |
| `degraded` / `stats` | property | 81 / 85 |

### policies.py (42 行) — 各 Agent 降级策略

`_BasePolicy`（@5）从 `config.DEGRADE_POLICY[agent_key]` 读取配置；`KeeperPolicy`@20 / `NarratorPolicy`@25 / `AuthorPolicy`@30 / `TimeAgentPolicy`@35 / `IntentDetectorPolicy`@40。

### turn_monitor.py (141 行) — 回合状态机

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `StepResult` | dataclass：步骤状态/重试次数/耗时/错误 | 11 |
| `TurnFrozenError` | 关键段耗尽重试 → 回合冻结异常 | 19 |
| `TurnMonitor.begin_turn` | 开始回合，清空步骤 | 33 |
| `execute_step` | `(step, fn, *, is_critical=False, max_retries)` 执行单步；重试循环；关键步失败 → 冻结消息 + TurnFrozenError；非关键失败 → 返回 None | 38 |
| `execute_parallel` | `(steps)` 线程池并行执行，冻结异常优先抛出 | 82 |
| `snapshot` | `() -> dict` 汇总 LLM 调用统计（按 agent）+ 回合步骤状态 + 冻结信息（前端 /health 用） | 109 |

### health.py (36 行) — PipelineHealth（已弃用）

`snapshot()` 逻辑已并入 TurnMonitor.snapshot()；保留兼容旧 /health 调用（构造时 DeprecationWarning）。

---

## src/module_designer/ — 三层信息引擎（管线）

### __init__.py (33 行)

re-export：`SceneL1/SceneL2/L3Designer` 及 load/save、`validate_l1/l2/l3/validate_all/is_valid`、全部 `parse_step*`/`build_step*`、`DependencyGraph`、`run_pipeline/cross_validate_layers/PipelineResult/save_pipeline_result`。

### layered_schema.py (361 行) — Schema 定义 + 验证

| 项 | 说明 | 行号 |
|----|------|------|
| `L1_*` / `L2_*` / `L3_*` | 三层字段 schema 常量（required/values/list_of） | 10–182 |
| `SchemaViolation` / `SchemaReport` | 违规/报告（add/errors/warnings/is_valid/summary） | 183 / 194 |
| `_validate_value` / `_validate_object` | 递归校验 | 226 / 258 |
| `validate_l1` / `validate_l2` / `validate_l3` / `validate_all` / `is_valid` | 各层验证入口 | 267–358 |

### dependency_graph.py (138 行) — 依赖图

| 类/方法 | 作用 | 行号 |
|---------|------|------|
| `DependencyNode` / `DependencyEdge` | dataclass + 序列化 | 9 / 24 |
| `DependencyGraph.build` | `(dependencies)` 建图（ID 前缀 I/AT/E 推断类型） | 46 |
| `detect_cycles` | DFS 检测所有循环 | 70 |
| `cut_edge` / `cut_random_edge_in_cycles` | 切断循环边 | 102 / 108 |
| `to_dict` / `from_dict` | 序列化 | 123 / 132 |

### l1_player.py (98 行) — L1 玩家层模型

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `Perceptible`（可感知元素）/ `NPCAppearance` / `SceneL1` | dataclass + to_dict/from_dict | 8–51 |
| `load_l1` / `save_l1` | L1 JSON 读写 | 84 / 92 |

### l2_keeper.py (220 行) — L2 KP 层模型

| 类/函数 | 说明 | 行号 |
|---------|------|------|
| `Encounter` / `SceneWeapon` / `AutoTrigger` / `SceneL2` | dataclass + 序列化 | 12–121 |
| `_normalize_npc_profile` | NPC profile 字段归一化 | 162 |
| `load_l2` / `save_l2` | L2 JSON 读写 | 184 / 198 |

### l3_designer.py (245 行) — L3 设计层模型

`ModuleMeta`@8 `WorldRule`@32 `SceneIntent`@54 `EndingCondition`@77 `ToneConstraints`@95 `NarrativeLine`@118 `TimePressureConfig`@144 `CharacterDesign`@173 `L3Designer`@192（to_dict/from_dict）；`load_l3`@232 `save_l3`@240。

### layered_parser.py (1497 行) — 管线 LLM 解析（每步含 build_*_prompt + parse_*）

| 函数 | 作用 | 行号 |
|------|------|------|
| `load_json` / `_clean_json` / `_safe_parse_json` / `_is_valid_json_output` | JSON 工具 | 33–67 |
| `_join_chapters` / `_parse_condensed_chapters` | 章节合并/浓缩文本解析 | 78 / 88 |
| `_slim_entity` / `_merge_phase2_fields` | 实体精简 / Phase2 字段合并 | 106 / 118 |
| `_with_fallback` | `(parse_fn, required_keys, fallback_data, max_retries, verbose, step_name)` 带重试与保底 | 153 |
| `parse_step1a` | 模块元信息+场景+角色+Boss+敌人/武器约束 + 统一资源层物品/法术库摘要（build_step1a_prompt 的 item_names/spell_names 参数，@grant_spell 与 item: 引用范围） | 290 
| `parse_step1b` | 精修浓缩模组文本 | 362 |
| `parse_step2a` | interactions + scene_movements；返回前对 interaction 的 `type` 字段调 `normalize_skill_name` 落库归一（旧技能名→新名，属性/伪技能/未识别保留原文并 print 提示） | 483 |
| `parse_step2b_combined` | events + auto_triggers（合并） | 589 |
| `parse_step2c_l1` | L1 场景感知 | 657 |
| `parse_step2c_l3` | L3 设计层 | 722 |
| `parse_step25_combined` | NPC 档案 + entity 归属 + follow/interact 解锁（合并） | 860 |
| `parse_step2_boss` | Boss 遭遇实体 | 958 |
| `parse_step3a` | 去重 + 冲突解决 + 结局标记 | 1042 |
| `_step3b_deterministic` / `parse_step3b` | L1↔L2 交叉核对（确定性修复 + LLM 补 linked_interaction） | 1058 / 1176 |
| `parse_step35` | 依赖图提取 | 1295 |
| `parse_step4` | Phase2：@markup 标准化（STEP4_SYSTEM 含 @grant_spell 语法说明；Step2A 约束 prompt 同步） | 1493 |

### layered_pipeline.py (917 行) — 管线编排

| 函数/类 | 作用 | 行号 |
|---------|------|------|
| `CrossRefIssue` / `CrossRefReport` | 交叉引用问题/报告 | 34 / 46 |
| `cross_validate_layers` | `(l1, l2, l3, weapon_lib, enemy_lib, spell_lib, item_lib)` 跨层引用验证（统一资源层：L2 side_effects @grant_spell.spell_ref -> 法术库校验，未知引用记 warning） | 97 |
| `_bind_npc_entities` | 扫描 entity NPC 归属 → 剥离+绑定 | 250 |
| `_extract_entity_bindings` | 从 npc_profiles 提取绑定 | 312 |
| `_inject_step1a_meta` | Step1a 角色 → NPC scene 注入 | 321 |
| `_inject_npc_special_entities` | 注入 follow_unlock + interact_unlock entity | 340 |
| `_assemble_l2` | 所有 entity 组装为 L2 JSON | 390 |
| `PipelineResult` | 结果容器（all_valid/summary） | 430 |
| `run_pipeline` | `(content, llm_json, llm_text=None, *, weapon_lib, enemy_lib, boss_lib, max_retries, verbose, inject_l3_wr0) -> PipelineResult` **4 步渐进管线主入口**：Step1→2a→2b+2c→3a∥2.5→3b→3.5/Phase1→Phase2→验证；技能名列表两处加载点（:485/:763）均从 `load_skill_config()["skills"]` 取新 20 表；Step3.5 `stat_names` 不含 SIZ | 440 |
| `save_pipeline_result` | `(result, module_dir)` 写 l1/l2/l3 JSON（l3 自动补 start_scene） | 922 |

### supplement_pipeline.py (515 行) — Author 触发的轻量补充管线

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `run_supplement_pipeline` | `(player_intent, reasoning, base_l3, entry_scene, exit_scene="", world_snapshot, output_dir, module_name, enemy_names)` | Step1 叙事规划（1 次 LLM）→ Step2 并行（2a entities / 2b L1 / 2c L3）→ 组装 L2 → 校验 → 写 `supplements/<ts>/l1/l2/l3_supp.json` | 155 |
| `_build_l3_context` | `(l3, current_scene)` | L3 → 自然语言摘要 | 250 |
| `_step_1_narrative` | `(player_intent, reasoning, base_l3, entry_scene, exit_scene, world_snapshot, enemy_names)` | 场景规划（SS1_/SS2_ 命名） | 300 |
| `_step_2a_entities` / `_step_2b_l1` / `_step_2c_l3` | — | 并行生成 | 375 / 404 / 419 |
| `_assemble_l2` | `(entities_data, scene_names)` | 补充 L2 组装 | 438 |
| `_validate_supplement` | `(l2, l1, scene_names)` | 补充内容校验 | 458 |

系统提示常量：`SUPP_STEP1_SYSTEM`@27 / `SUPP_STEP2A_SYSTEM`@55 / `SUPP_STEP2B_SYSTEM`@110 / `SUPP_STEP2C_SYSTEM`@134。

---

## src/llm.py (514 行) — LLM 封装

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `_init_sensor` | `()` | 延迟初始化 LLMSensor（避免 config 循环 import） | 48 |
| `set_llm_log_dir` / `set_log_label` | — | 响应日志目录/当前 label | 62 / 70 |
| `_log_response` | `(content, label=None)` | 响应写入 `<label>.txt` | 76 |
| `_extract_json` | `(content) -> str` | markdown 块/花括号定位提取 JSON | 93 |
| `call_deepseek` | `(prompt, *, json_mode=True, system=None, model=None, thinking=None, reasoning_effort=None, temperature=None, max_tokens=None, max_retries=3, fallback_schema=None, timeout=300.0, _label=None) -> dict\|str` | **统一 LLM 入口**：JSON 模式（重试+温度递减+fallback 兜底）/文本模式；内嵌传感器埋点；`_label` 规避并行日志竞态 | 123 |
| `get_sensor` | `()` | 获取传感器 | 268 |
| `evaluate_trait_enhancement` | `(inv_desc, skill_name, skill_detail, dice_roll, skill_value, entity_name, graded_tiers, search_context, player_input) -> dict` | 特质修正 sub-agent（虚拟骰子 ±20 逻辑；大成功/大失败保护；最多 1 级偏移校验） | 272 |
| `evaluate_failure_penalty` | `(inv_desc, entity_name, skill_name, skill_detail, failure_tier, scene_context, graded_on_failure, retry_count) -> dict` | 失败惩罚 sub-agent（重试越多后果越重，可带 @markup_effects） | 421 |
| `evaluate_combat_round_narrative` | `(round_log, enemies_desc, player_name, scene)` | 战斗叙事（走 build_combat_narrative_prompt） | 502 |

## src/prompts.py (1137 行) — Prompt 构建（所有 build_* 只构建不调用）

| 函数 | 签名/作用 | 行号 |
|------|-----------|------|
| `set_current_round` / `set_prompt_log_dir` / `_sanitize_label` / `_show_prompt` / `log_skill_result` | 日志设施 | 29–69 |
| `apply_trait_enhancement` | `(player, skill_name, skill_detail, entity_name, search_context, player_input, graded_tiers) -> (new_tier, enhancement)` judge/search/standoff 三处复用 | 90 |
| `_build_scene_context` / `_build_investigator_info` / `_build_player_state` / `_build_scene_state` / `_build_time_block` / `_build_world_state` / `_build_l1l3_context` | 确定性场景上下文构建 | 127–205 |
| `parse_narrative_output` | Narrator 输出解析 | 263 |
| `_build_entity_lines` | 场景实体 → prompt 行（`_split_req`@312 / `_fmt_inter`@332 / `_fmt_at`@341 / `_parse_req`@376 / `_split_req_str`@390 辅助） | 297 |
| `build_keeper_parse_prompt` | `(world, user_input)` Keeper Step1 实体匹配（JSON 表含 use 类型 + other 的 flavor/creative 子类；system 行为优先级含 use 返还规则与氛围 AT 不捎带） | 465 |
| `build_keeper_enrich_prompt` | `(world, judged_entities, user_input)` Step3 叙事整合 | 552 |
| `build_narrator_prompt` | `(brief, l1_scene, snap, user_input)` 沉浸式叙事 | 601 |
| `build_pre_parse_prompt` | `(player_text, ambiguity_context, world_brief)` 消歧 | 661 |
| `build_author_prompt` | `(request, l3_data, persona)` patch/structural 判定（prompt 含【世界编年史】块） | 741 |
| `build_combat_entry_prompt` | 战斗入口判定 | 925 |
| `build_standoff_match_prompt` | 对峙技能匹配 | 950 |
| `build_combat_narrative_prompt` | 战斗叙事 | 973 |
| `build_stat_narrative_prompt` | 属性变化 → 个人描述增量更新 | 999 |
| `build_material_fuzzy_prompt` | `(target, catalog_text, quantity=1)` **统一资源层**素材模糊匹配（物品/法术通用，输出 {matched, material, reason}） | 1020 |
| `build_consume_item_fuzzy_prompt` | 旧消耗品模糊匹配兼容包装（scenario_core 通路，读 material 或 item_name 双键） | 1039 |
| `build_time_pressure_assess_prompt` | 时间压力介入判定 | 1042 |
| `build_npc_intent_detect_prompt` | 是否在和 NPC 对话 | 1084 |
| `build_npc_parse_prompt` | NPC 互动解析 | 1105 |

## src/llm_player.py (482 行) - LLM 自动玩家（模组自动化测试）

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `load_profile` | `(path) -> dict` | 加载测试 profile JSON | 26 |
| `build_player_prompt` | `(world, narrative_result, short_history, long_memory, profile, player_snapshot) -> (system, user)` | 构建玩家 prompt（快照/时间/背包/NPC/出口/敌人 + 4 种测试模式段落） | 31 |
| `compress_memory` | `(short_history) -> str` | LLM 压缩短期记忆 | 101 |
| `_eval_success_checks` | `(names, entries) -> bool` | 按 tests/e2e/scenario_predicates.py 谓词注册表评估是否全部满足 | 115 |
| `_collect_mech_line` | `(game, result, turn_no, action, dt, prev_loc, prev_boss_state) -> str` | 采集单回合机制事件时间线（frozen/outcomes/move/tier/boss 状态 diff），格式对齐 tests/e2e/scenarios/audit_guide.md 第三节 | 138 |
| `run_llm_player` | `(profile_path, module_name, max_turns, max_duration_s, post_init_hook, log_dir) -> {log_dir, summary, goal_achieved}` | **主循环**：init_game -> 玩家 prompt -> call_deepseek -> run_turn -> 机制时间线 -> 摘要日志 `_summary.json` -> 结局/目标提前终止 -> 定期记忆压缩；含 goal 注入/播种 hook/谓词判定（场景 runner 三层判定用） | 225 |
| `_log_player_call` | `(turn, system_prompt, user_prompt, response)` | 玩家 LLM 交互全文写入 `player_llm.txt`（现为 run_llm_player 内嵌套函数） | 嵌套@296 |

## src/llm_player_prompts.py (81 行)

prompt 常量：`PLAYER_SYSTEM`@3 / `TEST_MODE_STRESS`@13 / `TEST_MODE_EXPLORATION`@23 / `TEST_MODE_ROLEPLAY`@31 / `TEST_MODE_GOAL`@40 / `MEMORY_COMPRESS_SYSTEM`+`MEMORY_COMPRESS_TEMPLATE` / `TEST_MODE_CUSTOM` 等。

## src/config.py (154 行) — 配置常量

| 常量 | 说明 |
|------|------|
| `WR0_ENABLED` / `SHOW_NON_TRIGGERABLE` / `SHOW_COMPLETED` | 创作者豁免 / Parse 展示控制 |
| `COMBAT_LLM_ENHANCEMENT` | 战斗 LLM 增强开关 |
| `LLM_TIMEOUT_MS` / `LLM_SLOW_THRESHOLD_MS` / `LLM_SLOW_RATE_THRESHOLD` / `LLM_MAX_CONSECUTIVE_FAILURES` / `LLM_DEGRADE_RECOVERY_COUNT` | 监控/降级参数 |
| `MONITOR_ENABLED` / `MONITOR_HISTORY_SIZE` | 传感器开关 |
| `MAX_ESCALATION_DEPTH` / `INTENT_COOLDOWN_WINDOW` / `COMMS_INTERVAL_MINUTES` / `NPC_MEMORY_CAP` | 回合控制 |
| `PIPELINE_MAX_RETRIES` / `INJECT_L3_WR0` / `TURN_STEP_MAX_RETRIES` | 管线/回合监控 |
| `DEGRADE_POLICY` | 各 Agent 降级策略 dict（keeper/narrator/author/time_agent/intent_detector） |
| `AGENT_SYSTEM_PROMPTS` | 12 个 Agent system prompt 覆盖 |
| `AUTOSAVE_ENABLED` / `AUTOSAVE_INTERVAL_SEC` / `AUTOSAVE_MAX_COPIES` / `AUTOSAVE_DIR` | 自动存档 |
| `OFFLINE_INJECTION_ENABLED` / `RUNTIME_INJECTION_ENABLED` | 注入开关 |

## src/config_llm.py (76 行) — LLM 后端配置（git 忽略；模板见 config_llm.template.py）

| 常量 | 说明 |
|------|------|
| `LLM_BASE_URL` / `LLM_API_KEY_ENV` | API 端点 / Key 环境变量名 |
| `LLM_DEFAULT_MODEL` / `LLM_FLASH_MODEL` | 主模型 / 轻量模型 |
| `LLM_THINKING_ENABLED` / `LLM_REASONING_EFFORT` / `LLM_TEMPERATURE_JSON` / `LLM_TEMPERATURE_TEXT` / `LLM_MAX_TOKENS_JSON` / `LLM_MAX_TOKENS_TEXT` | 默认生成参数 |
| `RE_*` | 各调用点 reasoning_effort 覆盖（RE_KEEPER_PARSE="max" 等） |

## src/utils.py (232 行) — 通用工具

| 函数 | 签名 | 作用 | 行号 |
|------|------|------|------|
| `parser` | `(file_path) -> str` | .docx/.pdf 解析入口（.doc 报错引导另存） | 11 |
| `_parse_docx` / `_parse_pdf` | — | python-docx / PyPDF2 解析 | 30 / 41 |
| `estimate_tokens` | `(text) -> int` | 中文≈1.5 token/字，英文≈0.25/字符 | 68 |
| `estimate_and_truncate_context` | `(content, extra_prompt_chars, max_tokens, safety_margin) -> str` | 超限截断（找段落/句号断点） | 78 |
| `roll_dice` / `roll_d6` | — | 掷骰 | 126 / 147 |
| `roll_formula` | `(formula) -> int` | 解析 NdM+K 骰式并掷骰；不匹配返回 0（judge/combat 的 heal 原子共用解析器，垃圾 formula 由调用方回退 delta） | 136 |
| `load_skill_config` | `(path=None) -> dict` | data/skill_config.json 技能体系配置（20技能/8属性/legacy_map/attr_aliases/pseudo_skills），缓存 | 145 |
| `normalize_skill_name` | `(name) -> (kind, value)` | 技能名归一单点：skill/attr/pseudo/ignore/unknown 五路 | 161 |
| `load_skill_checks` | `(path=None)` | U9：默认数据源已切换为 skill_config.json 的 skills 列表（保持 `[{"name": ...}]` 兼容形状）；旧 skill_checks.json 已删除 | 202 |
| `get_coc_skill_names` | `() -> list[str]` | 新 20 项技能名（缓存，从 skill_config.json 读取） | 215 |

## src/audit_player_log.py (411 行) — LLM 玩家日志审计

| 函数 | 作用 | 行号 |
|------|------|------|
| `load_summary` | 读 `_summary.json` | 12 |
| `_llm_audit` | LLM 分析玩家日志（叙事质量/检定/NPC/时间/连贯性）→ findings 表 | 18 |
| `audit` | `(log_dir) -> str` 主入口：确定性异常统计 + LLM 审计 + Markdown 报告 | 145 |
| `_audit_npc` / `_audit_enemy` / `_audit_combat` / `_audit_boss` / `_audit_time` / `_audit_author` / `_audit_side_effects` / `_audit_memory` | 各维度确定性异常扫描 | 304–396 |

---

## frontend/ — FastAPI 前端

### server.py (133 行) — 服务入口

| 项 | 说明 | 行号 |
|----|------|------|
| `app` | FastAPI("TRPG Assistant") + CORS + `/static` 挂载 + Jinja2 templates | 37–53 |
| 6 个 router include | files/launcher/character/game/editor/assets | 56–67 |
| `health` | `GET /health` | 70 |
| `_open_app_window` | pywebview 或 Edge/Chrome app 模式打开窗口 | 75 |
| `start_server`（main） | uvicorn 线程 + 自动开窗 | 125 |

启动时若 `src/config_llm.py` 缺失则自动从模板复制（@29）。

### _paths.py (19 行)

集中路径解析：`IS_FROZEN`（PyInstaller `sys._MEIPASS` / Nuitka `.dist` 后缀检测）、`PROJECT_ROOT`、`FRONTEND_DIR`。

### routers/launcher.py (238 行) — 启动页 API

| 端点 | 路由 | 行号 |
|------|------|------|
| `launcher_page` / `launcher_tab` | `GET /` / `GET /launcher/tabs/{tab}` | 46 / 54 |
| `save_config` / `load_config` | `POST/GET /api/config/save\|load`（模型/温度/超时/战斗增强等） | 70 / 95 |
| `start_step0` | `POST /api/step0/start` → run_step0 子进程 | 100 |
| `start_pipeline` | `POST /api/pipeline/start` → run_pipeline 子进程 | 140 |
| `validate_pipeline` | `POST /api/pipeline/validate` | 188 |

### routers/game.py (1191 行) — 游戏 API（核心）

| 端点 | 路由 | 作用 | 行号 |
|------|------|------|------|
| `game_page` | `GET /game` | 游戏页 | 169 |
| `_handle_slash_command` | — | 斜杠命令短路 | 173 |
| `process_turn` | `POST /api/game/turn` | 回合入口（线程池，防止阻塞事件循环） | 254 |
| `character_card` | `GET /api/game/character-card` | 角色卡 HTML（状态区 MP 当前/上限 + 已知法术区，库外 id 降级展示；F2 SAN bar 分母=derived.SAN_MAX @576） | 515 |
| `player_status` | `GET /api/game/player-status?format=` | HP/MP/SAN 状态；JSON 含 hp_max/mp_max/mp/known_spells/san_max（id 解析为名；F2 @700） | 682 |
| `game_command` | `POST /api/game/command` | 命令 | 716 |
| `scene_info` | `GET /api/game/scene` | 场景 HTML | 721 |
| `game_progress` | `WS /api/game/progress` | 管线进度推送 | 738 |
| `init_game_api` | `POST /api/game/init` | 初始化 + 首回合（响应含 hp_max/mp_max/mp/known_spells/san_max，F2 @854） | 770 |
| `game_state` | `GET /api/game/state` | 游戏状态 JSON（含 hp_max/mp_max/mp/known_spells/san_max，F2 @875） | 863 |
| `set_auto_win` | `POST /api/game/auto-win` | 战斗自动胜利开关 | 882 |
| `combat_start` | `POST /api/combat/start` | 初始化战斗会话（CombatSystem 传 world.spell_library+world @979，T9 战斗 markup/timed 原子可用） | 893 |
| `combat_round` | `POST /api/combat/round` | 执行一轮（CombatSystem 传 spell_library+world @1027，战斗施法可用） | 1002 |

序列化辅助：`_serialize_enemies_for_frontend`@34 / `_serialize_combat_state_for_frontend`@57（F2 增 player_san_max 键 @64，getattr 兜底 99） / `_deserialize_enemies_for_combat`@71 / `_init_libraries`@105 / `_known_spell_names`@504（known_spells id->中文名，统一资源层前端接线共用） / `_resolve_start_scene`@1138 / `_make_default_inv`@1184。

### routers/character.py (335 行) — 车卡 API

U9：SKILLS/STATS/STAT_ROLLS 均从 `data/skill_config.json` 读取（20 技能/8 属性，删 SIZ）；`roll_stats` 衍生公式 HP=CON//3、DB/BUILD 查表键=STR+CON//2。2026-08-15：`skills_list` 按归属属性分 8 块（双属性技能仅首块可编辑，块标题含乘数+池参考 JS 实时算）；职业标签下拉读 `occupation_labels.json`（专精 +10 封顶 99、专精徽标、换标签整表重渲染）；`_build_export` 参数 occupation→label，写 `inv.label`，meta.version=2.0；2026-08-25 B11：导出覆写 2.2（与核心 serialization v2.2 对齐，@275）。

`character_page`@50 / `upload_avatar`@60 / `step_partial`@73 / `roll_stats`@88 / `skills_list`@126 / `generate_description`@218（LLM 外貌）/ `_build_export`@235 / `export_character_get`@300 / `export_character`@319（ZIP 导出）；辅助 `_load_labels`@40（读 occupation_labels.json）/ `_roll_stat`@45。

### routers/editor.py (116 行) — JSON 编辑器

`editor_page`@21 / `load_json`@26 / `_render_tree`@37 / `save_json`@71 / `validate_json`@88 / `_type_label`@105。

### routers/files.py (60 行) — 文件浏览

`_safe_dir`@20（目录穿越防护）/ `list_files`@30（html/json 两种格式）。

### routers/assets.py (79 行) — 素材

`list_assets`@27 / `random_asset`@52。

---

## scripts/ 与 tools/

### scripts/extract_library.py (247 行) — 从文本提取敌人/Boss/武器入库

`_load_templates`@27 / `_template_to_example`@32 / `_load_existing`@38（去重）/ `_extract_via_llm`@64 / `_dedup`@113 / `_show_item`@125 / `_write_enemies/_write_bosses/_write_weapons`@147–166 / `main`@175（LLM 提取 → 去重 → 确认 → 写 JSON）。

### scripts/probe_nuitka.py (18 行)

Nuitka 打包环境探测（无函数定义）。

### tools/run_layered_parser.py (88 行)

对「常暗之厢」文档跑 parse_module + save_module + validate_all + run_pipeline 的调试脚本；`llm_parse`@31。

### tools/create_layered_notebook.py (198 行)

生成分层解析器 Jupyter notebook（无函数定义，顶层脚本）。
