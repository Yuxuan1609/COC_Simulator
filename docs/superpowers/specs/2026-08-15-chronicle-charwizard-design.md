# 编年史补全 + 车卡向导 U9 适配 设计

**日期**: 2026-08-15
**状态**: 已批准（口头）
**前置**: U9 技能系统重修（plan `docs/superpowers/plans/2026-08-14-skill-system-redesign.md`）已完成；U2 WorldChronicle 基础版已上线
**来源**: UPDATES.md 待办 0（U9 前端遗留部分）+ 0.6（U2 遗留 minor 三项）；R4 parse 稀疏实体过度匹配本期**不处理**，仅在 UPDATES.md 标注暂缓

---

## 1. 范围

两条独立工作流，一个 spec：

- **A. 编年史/patch 收尾**（后端，`src/scenario_core.py` + `src/game/agents/keeper.py`）
- **B. 车卡向导 U9 适配**（前端，`frontend/routers/character.py` + 模板）

明确**不做**：`_collect_mech_line` 切源（见 2.3）；前端现栈优化（抽 JS/htmx/Alpine）；R4。

---

## 2. A. 编年史/patch 收尾

### 2.1 `_integrate_patch` entity_ids 统一（keeper.py:1620-1645）

现状：`record_patch` 记录的是原始 dict 的 `e.get("id","")`，而实体构造时缺 id 会回退 `NEW_{hash%10000}`——两边不一致，缺 id 时编年史记到空串。

改动：实体构造循环中收集真实 `entity.id`，传给 `record_patch`。

### 2.2 编年史补 combat/boss/spawn 投影（scenario_core.py `WorldChronicle`）

`record_turn` 现有通道：intent/entities/at/pending/combat start/ending/npc。补三个通道，格式与 `llm_player._collect_mech_line` 对齐：

| 通道 | 来源 | 渲染 |
|------|------|------|
| `spawn` | outcomes 的 side_effects 中 `SpawnEnemy` | `spawn=ref×N,…` |
| `combat_end` | `result.combat["outcome"]` | `combat=end(win)` |
| `boss` | Chronicle 内部维护 `_boss_seen_spawned`/`_boss_seen_dead` 集合，每次 record_turn 对 `world.bosses._spawned_boss_ids` 及实例 status 做 diff（逻辑同 llm_player.py:190-204） | `boss=engage(ID)` / `boss=defeated(ID)` |

`_render_event` 的 key 列表同步加 `spawn`/`boss`；`combat` 通道从仅 start 扩展为 start/end 两种字符串。

序列化：`_boss_seen_*` 集合需入 `to_dict/from_dict`（否则读档后 boss diff 重报 engage——可接受但更吵；入档成本极低，做）。

### 2.3 为什么本期不切 `_collect_mech_line` 的源

`_collect_mech_line` 还采集 move 轨迹、tier 修正箭头（`↑/↓`）、enemies_here 等 chronicle 没有的字段。切源会丢信息。本期只把编年史补成**完备副本**，测试侧采集器不动。后续若要统一，先把 move/增强信息补进 chronicle 再切。

### 2.4 facts 渲染补 Boss 组 + 玩家关键物品（`render_for_author`）

- 玩家行追加：`物品: {world.memory.key_items 或 '无'}`（关键物品在 MemoryManager，scenario_core:1376）
- 新增 Boss 块（敌人块之后）：
  - 已开战：遍历 `world.bosses._spawned_boss_ids`，每行 `Boss: {boss_id}@{scene} 状态={inst.status} 阶段={inst._current_phase or '—'}`（实例经 `_instance_ids` → `world.enemies.get_by_id`）
  - 未遭遇：`world.bosses._encounters` 中不在 spawned 集合的，列 `Boss: {id}@{scene} 未遭遇`

---

## 3. B. 车卡向导 U9 适配

### 3.1 技能列表按属性分块（`skills_list`，character.py:128）

- 按 `skill_config.json` 的 `attributes` 顺序分 8 块（STR/CON/DEX/APP/INT/POW/EDU/LUCK）
- 技能归入其 `attr` 列表的**每个**属性块；第二及以后归属块渲染**只读行**（无 input，避免同名 input 重复收集导致 skills-json 错乱）
- 块标题：`{STAT_LABELS[attr]} ({attr}) ×{multiplier}`；池点数参考值由模板 JS 读当前属性 input 值 × 乘数实时计算（乘数表以 JS 对象注入模板）
- 无归属属性的技能（如克苏鲁神话）归入末尾「特殊」块
- 删除旧 `cat_order`/职业下拉联动逻辑（occupations.json 已删）

### 3.2 职业标签选择（step2 顶部）

- 下拉数据源：`data/occupation_labels.json`（6 标签 + 自定义），替代已恒空的 occupations 下拉
- 选中标签：其 focus 技能 input 值 +10（封顶 99），行加「专精」徽标高亮；**换标签时撤销旧加成再加新加成**（JS 记录上一次应用的 focus 集合与加成值）；选「自定义」= 无加成
- 导出链路：`_build_export` 增 `label: str` 参数 → `inv.label = label`（序列化 personal.label 已支持，v2.0）；GET/POST export 两个端点签名同步加 `label`
- 删除 `_load_occupations()` 与 `Occupation` 构造残留（occupation 字段置 None）

### 3.3 模板 SIZ 残留清理

- `character.html:57,64,68`：vals 删 SIZ；hp 公式改 `Math.floor(vals.CON/3)`；ss 改 `vals.STR + Math.floor(vals.CON/2)`
- `char-step3.html:68-69`：statLabels/statNames 删 SIZ
- `help-character.html:6`：删 SIZ 行

---

## 4. 测试

- **A 项**：`tests/test_chronicle.py` 追加——patch 记录真实 id（含缺 id 回退）；spawn/combat_end/boss engage+defeated diff 投影；facts 渲染含 Boss 块与玩家物品；`_boss_seen_*` 序列化往返
- **B 项**：`tests/test_frontend_character.py`（新建，FastAPI TestClient）——step2 含标签下拉；skills-list 按属性分块且含乘数、双属性技能仅一个 input；导出 zip 内 character.json 含 label、无 SIZ、version=2.0
- 回归：默认套件 127 全绿；场景层/实连层不动

## 5. 文档同步

- `UPDATES.md`：完成记录 + 待办 0/0.6 移除、待办 1（R4）标注「暂缓（2026-08-15 用户拍板）」
- `MAINTENANCE.md`：涉及文件条目行号/签名更新
