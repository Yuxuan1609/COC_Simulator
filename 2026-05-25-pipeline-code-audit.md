# Pipeline 代码层面审计报告

**日期**: 2026-05-25  
**范围**: `src/module_designer/layered_parser.py` 全部 14 个 system prompt + `src/module_designer/layered_pipeline.py` 编排逻辑 + `src/llm.py` LLM 调用 + 标准库载入  
**基准运行**: `data/debug/20260525_200450`

---

## 一、System / User Prompt 架构检查

### 现状

每个 pipeline 步骤的调用正确分离了 system 与 user prompt：

```python
# layered_parser.py (所有 parse 函数统一模式):
def parse_step2a(...):
    prompt = build_step2a_prompt(chapters, scenes, characters)  # 用户提示词
    return llm_call(prompt, system=STEP2A_SYSTEM)               # 系统提示词
```

`run_pipeline.py` 中的 LLM wrapper 将两者正确记录到 `_llm_calls/<step>/prompt.txt`（`=== SYSTEM ===` + `=== USER ===` 分隔），并由 `call_deepseek()` 作为 `messages=[{system}, {user}]` 发送。

**结论**: 架构正确，14 步全部有 prompt + response 日志。

### 存在的问题

| # | 类型 | 位置 | 问题 |
|---|------|------|------|
| P1 | 🟡 | `layered_parser.py:163` (call_deepseek json_mode) | `default_system` 被硬编码为 `"你是一个严格的规则判定助手..."` — 如果 `system` 参数为 `None`，它会覆盖应有的 pipeline 专用 system prompt。所有 parse 函数都传了 system 所以未触发，但这是脆弱的默认值 |
| P2 | 🟢 | `layered_parser.py:228` (call_deepseek text_mode) | 同上，text mode 默认 system 为泛用 KP 提示词 |

---

## 二、Prompt 内容逐步骤审计

### Step 1a: 结构化提取

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含完整任务说明 | ✅ | 任务、原则、输出格式、要求均明确 |
| User 含动态数据 | ✅ | 武器/敌人/Boss 库 + 源文档 |
| 标准库引用正确 | ✅ | `enemy_ref`/`weapon_ref`/`boss_ref` 均要求从库选择 |
| 潜在问题 | 🟡 | `comms_interval` 估算方基于 `estimated_duration`，但 LLM 先估时长再算间隔，两步都可能不准 |

### Step 1b: 精修模组

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含完整任务说明 | ✅ | 章节结构、叙事要求明确 |
| 潜在问题 | 🟠 | 原文要求 "不压缩信息量"，但 LLM 在响应中用 5550 字符概括了原文。实际上信息已被压缩。Prompt 的 "保留所有关键叙事细节" 和 "不压缩信息量" 有矛盾 |

### Step 2a: Interactions 提取

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含完整 schema/规则 | ✅ | Entity 字段、requirement/trigger 区分、graded_result 规则详尽 |
| **P3: 技能名白名单缺失** | 🔴 | System prompt **没有提供标准技能列表**。LLM 只能根据"COC 7th常识"猜测技能名，导致 Step 2a 响应中 I6 `type: "灵感"`、I9 `type: "幸运"`——**这两个都不是技能名而是属性名**，不在 `data/skill_checks.json` 的 46 个技能中 |
| **P4: 缺少 `@markup` 格式说明** | 🟠 | Step 2a system 不提 `@标记` 语法，造成 LLM 用纯自然语言写 side_effects。标记转换完全推迟到 Phase 2，但 Phase 2 的 `_slim_entity` 只传 6 个字段，信息已在压缩中丢失 |
| **P5: AT_WORLD 要求与 role 冲突** | 🟡 | Step 2b AT 的 system 要求生成 AT_WORLD，但描述方式模糊（"描述：1调查员初始时身上带着什么 2哪个场景散布着什么武器..."），LLM 用自然语言而非 `@markup` 填写。Phase 2 后再转换时信息已退化 |

### Step 2b: Events / Auto-triggers

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **P6: Events system 不传场景列表** | 🟠 | `build_step2b_events_prompt` 传了 `scenes` 列表但 events 本身无 scene 字段，LLM 无法将事件关联到具体场景 |
| **P7: AT system 不传 L3 数据** | 🟡 | Auto-trigger 生成时只有精修模组，不知道 L3 的设计意图。导致可能生成与 L3 冲突的 AT |

### Step 2c: L1 / L3

| 检查项 | 状态 | 说明 |
|--------|------|------|
| L1 system 明确 "只描述无条件可见" | ✅ | perceptible vs ambient_hints 区分清楚 |
| L1 system 注入 L1_TEMPLATE | ✅ | 使用 `json.dumps(L1_TEMPLATE)` 提供示例 |
| **P8: L1 ambient_hints 泄漏检定信息** | 🟠 | System 说 "只描述无条件可见的内容"，但 `perceptible` 列表项的 `brief` 字段不应包含需要检定才能获取的信息。实际输出中 `5号车厢 ambient_hints` 泄漏了报纸日期（需 I5 检定才能发现） |
| **P9: L3 不传 L2 实体信息** | 🟡 | `build_step2c_l3_prompt` 只有精修模组 + 场景列表 + 角色列表，没有传 L2 entity 供参考。结局条件 `ending_conditions` 可能在 Step 3a 验证时发现不匹配 |

### Step 2.5: NPC 行为档案

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **P10: prompt 传的信息太少** | 🟠 | `build_step25_prompt` 传了 L3 characters + L1 NPC appearances + **截断的** L2 entity（name + result[:100] + trigger[:100]）。完整 entity 信息（requirement/side_effects/graded_result）未传入，LLM 无法准确描述 NPC 能触发什么互动 |
| **P11: can_follow 判断不传场景上下文** | 🟡 | NPC 能否跟随取决于模组设定（如乘务员腿伤），但 prompt 只传 L3 character 设计意图（可能不说伤情），精修模组原文不在此步骤传入 |

### Step 3a: 去重/冲突/结局

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含去重规则 | ✅ | based_on 合并、graded_result 校验、结局标记回补 |
| **P12: 缺少 "保留依赖链" 约束** | 🔴 | System 只说基于 based_on 合并，但**没有**说 "非 based_on 关系的 requirement 依赖（如 I8 依赖 I7）必须保留"。LLM 可能误将 requirement 中的 ID 视为冗余而清除。这正是审计 B1 问题的根因。应在 system 中增加：`requirement 中引用的 entity ID 即使不是 based_on 关系也不得清除，只修正格式错误` |
| **P13: 冲突解决顺序模糊** | 🟡 | System 说 "requirement/trigger 冲突以精修模组为准修正"，但没说如何处理 "entity 间冲突"（如两个 entity 描述同一件事但一个 based_on 指向另一个）。LLM 可能保守处理导致信息丢失 |

### Step 3b: L1↔L2 交叉核对

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含校验任务 | ✅ | linked_interaction、NPC 名称、场景名一致性 |
| **P14: 不传 chapters 全文** | 🟡 | `build_step3b_prompt` 只传 `module_overview`（`chapters.get('module_overview', '')`），不传精修模组其他章节。LLM 可能无法参考原文修正 linked_interaction |

### Step 3.5: 依赖图

| 检查项 | 状态 | 说明 |
|--------|------|------|
| **P15: requirement 解析规则不明确** | 🔴 | System 说 "裸 entity ID 默认指该实体完成"，但 `||` 后的软性条件中如有 entity ID 也要提取。问题是 `||` 后 "乘务员未被带走（I7 检定失败或未进行）" 这种描述含 I7，但语义是 "I7 失败或未做" 时才触发，而非 "I7 完成"。LLM 无法区分正向/反向依赖。这解释了 B2 问题（I13→I8 依赖遗漏）—— `I13.requirement = "I8||..."` 但 I8 的 requirement 在 step3a 被清空，dep_graph 无法识别 |
| **P16: 重试逻辑脆弱** | 🟡 | `_do_step35` 的重试依赖 LLM 每次返回不同结果。如果 LLM 第 2-3 次仍返回空 deps，最终 `circular_cut` 标记为 True 但 graph 可能不完整 |

### Phase 2: 精简标准化

| 检查项 | 状态 | 说明 |
|--------|------|------|
| System 含 @标记 语法 | ✅ | 7 种 @function 列举清楚 |
| **P17: entity ID 被丢弃** | 🔴 | `_slim_entity()` 只提取 `name, scene, type, result, graded_result, side_effects`，**丢弃了 `id`**。Phase 2 LLM 返回的 entity 没有 id，依赖 `_merge_phase2_fields` 按 `(name, scene)` 匹配回原文——如果 name 在 Phase 2 中被改写了怎么办？这个匹配是脆弱的 |
| **P18: 不传完整 side_effects** | 🟠 | `_slim_entity` 传了 side_effects 但 LLM 需要将其从自然语言转换为 @markup。如果 side_effects 描述模糊（如 "开抽屉的声音吸引了隔壁车厢的怪物"），LLM 无法确定该用 `@spawn_enemy` 还是保持自然语言。缺少上下文（精修模组原文不传入此步） |

---

## 三、标准库载入检查

### 武器库 (`data/library/core/weapons.json`)

| 检查项 | 结果 |
|--------|------|
| 格式 | ✅ JSON items[] 数组 |
| 包含 "小刀" | ✅ |
| 包含 "手电筒" | ✅ |
| 字段完整性 | ✅ skill_name, damage, range, shots, malfunction, era, rarity |

**备注**: "手电筒" 在库中是武器（`skill_name: "格斗"`, `damage: "1D3+DB"`），这合理——COC 中手电筒可作钝器。但它同时也是非武器实用物品。`@item_gain` 和 `@grant_weapon` 均可引用它，取决于上下文。

### 敌人库 (`data/library/core/enemies.json`)

| 检查项 | 结果 |
|--------|------|
| 格式 | ✅ JSON items[] 数组 |
| 包含 "Clicker" | ✅ |
| Clicker attributes | ✅ STR 80, CON 70, SIZ 65, DEX 50, POW 60 |
| Clicker 特殊能力 | ✅ 盲感（通过声音定位）、恐惧灵气（SAN 0/1D4） |
| combat_behavior flags | ✅ `[adjacent_aware]` |

**备注**: Clicker 的描述原文是 "通过声音定位猎物，对声音极度敏感"，说明它**会被声音吸引**而非惧怕。这与审计 B6 指出的 NPC 档案中 "惧怕强光" 矛盾——LLM 自行发明了弱点。

### Boss 库 (`data/library/core/bosses.json`)

| 检查项 | 结果 |
|--------|------|
| 格式 | ✅ JSON dict 键值对（非数组） |
| 包含 "吞噬之口" | ✅ |
| boss_mechanics 描述 | ✅ 需操作面板钥匙 + 电气维修/操作重型机械检定 |
| 弱点描述 | ✅ "常规武器攻击无效" |

**备注**: Boss 库中明确写了 "常规武器攻击无效" 且 "Boss 遭遇为环境威胁不可战斗"。但 Step 2 boss prompt 传的描述只有 "基于精修模组内容扩写"，LLM 可能生成 "唯有战斗" 的错误暗示（审计 H6）。

### 技能表 (`data/skill_checks.json`)

| 检查项 | 结果 |
|--------|------|
| 条目数 | 46 个技能 |
| 包含 "侦查" | ✅ |
| 包含 "灵感" | ❌ 不在表中 |
| 包含 "幸运" | ❌ 不在表中 |
| 包含 "图书馆使用" | ✅ |

**结论**: "灵感"（INT stat roll）和 "幸运"（LUCK stat roll）是 COC 7th 核心属性检定，不是技能检定。标准技能表没有它们。Step 2a LLM 将它们作为 `type` 写入 entity 是错误行为，Phase 2 再暴力改为 "侦查" 只是掩盖问题。

---

## 四、LLM 调用基础设施问题

| # | 类型 | 位置 | 问题 |
|---|------|------|------|
| L1 | 🔵 | `llm.py:162` | JSON mode `default_system` 描述为 "严格的规则判定助手" 但 pipeline 的多步骤需要的角色完全不同（从 "解析助手" 到 "设计师" 到 "校对助手"）。虽然各 parse 函数都传了 system=，但万一遗漏会发送错误角色设定 |
| L2 | 🔵 | `llm.py:167-177` | `response_format={"type": "json_object"}` 在非 OpenAI 兼容 API 上可能不工作。DeepSeek API 支持此参数，但如果有其他后端切换时需注意 |
| L3 | 🔵 | `llm.py:175` | `extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}` 是 DeepSeek 特有参数。切换 API 提供商时需修改 |

---

## 五、编排逻辑问题 (`layered_pipeline.py`)

| # | 类型 | 问题 |
|---|------|------|
| O1 | 🟡 | **Phase 1 结果未被使用** — `run_pipeline` 调用 `parse_phase1` 获取 enemies/weapons 约束，但 code 注释说 "Enemy/weapon constraints now come from Step 1a (merged Phase 1)"。Phase 1 的 LLM 调用被标记为 `phase2_standardize` 但实际上 Phase 1+2 已合并为单次调用。Phase 1 单独的 LLM 调用在 manual mode 中可能仍存在 |
| O2 | 🟡 | **`_bind_npc_entities` 的 fallback 逻辑** — line 633 判断 "LLM" or "deterministic"，但 deterministic 绑定规则未见注释说明。如果 LLM entity_bindings 失败，deterministic fallback 可能无法正确绑定 |
| O3 | 🟡 | **WR0 注入两次** — line 537 和 line 695 各做一次 WR0 注入检查，逻辑重复但参数略有不同（`"is_absolute": "最高规则..."` vs `"is_absolute": True`） |
| O4 | 🔵 | **`dep_graph` 重构建** — line 769 和 818 各做一次 `dep_graph.to_dict()` 写入，但 line 818 的 `l2_assembled` 在 line 815 已 `clear()` + `update()` |

---

## 六、总结与修复优先级

### 🔴 必须修复（导致输出数据错误）

| # | 问题 | 修复方向 |
|---|------|----------|
| P3 | Step 2a system prompt 缺少技能白名单 | `build_step2a_prompt` 添加技能列表到 prompt |
| P12 | Step 3a 缺少 "保留 requirement 依赖链" 约束 | STEP3A_SYSTEM 增加保留非 based_on 依赖的指令 |
| P15 | Step 3.5 requirement 解析无法区分正向/反向依赖 | STEP35_SYSTEM 增加语义说明 + 示例 |
| P17 | Phase 2 `_slim_entity` 丢弃 entity id | 增加 id 字段到 slim 实体（不传给 LLM 但用于匹配） |

### 🟠 强烈建议（改善生成质量）

| # | 问题 | 修复方向 |
|---|------|----------|
| P4 | Step 2a 不提 @markup 语法 | STEP2A_SYSTEM 添加 @标记 简短参考（不要求完全标准化） |
| P5 | AT_WORLD 的 @markup 生成时机错误 | 调整时序：在 Phase 2 中专门处理 AT_WORLD 的 side_effects 转换 |
| P10 | Step 2.5 prompt 信息不足 | `build_step25_prompt` 传递完整 entity（非截断）+ 精修模组 NPC 章节 |
| P18 | Phase 2 不传完整上下文 | `build_step4_prompt` 传递精修模组相关章节作为上下文 |

### 🟡 改善一致性

| # | 问题 | 修复方向 |
|---|------|----------|
| P8 | L1 ambient_hints 泄漏检定信息 | STEP2C_L1_SYSTEM 更严格地说明 perceptible vs 检定信息的边界 |
| P9 | Step 2c L3 不传 L2 entity | `build_step2c_l3_prompt` 传递 L2 entity 摘要 |
| P14 | Step 3b 不传 chapters 全文 | `build_step3b_prompt` 传递完整 chapters |

### 🔵 代码质量

| # | 问题 |
|---|------|
| O1 | Phase 1 结果未被使用（或日志名称误导） |
| O3 | WR0 注入代码重复 |
| P1/P2 | call_deepseek 默认 system prompt 不匹配 pipeline 场景 |

---

## 七、关于 "部分输出步骤没有显示提示词和输出结果" 的结论

经检查全部 14 个 `_llm_calls/*/` 子目录，**每个步骤都有 prompt.txt + response.json（或 response.txt）**。格式化也正确（`=== SYSTEM ===` + `=== USER ===` 分隔）。

如果某次运行有步骤缺 prompt/response，可能原因：
1. `output_dir` 权限问题导致目录创建失败
2. LLM 调用在 `_with_fallback` 中触发 `fallback_data`（fallback 不调 LLM，直接返回预设数据——此时无 prompt 日志）
3. Step 3.5 的 `_do_step35()` 有自己的重试循环（line 733-763），不经过 `_with_fallback`，如果 3 次都返回空 deps，`graph` 为 None 但仍算 "完成"

建议在 `_with_fallback` 中增加日志：当使用 fallback 时，在 `_llm_calls/<step>_fallback/` 下写一个标记文件说明原因。
