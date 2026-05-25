# NPC-Entity Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate NPC interactions from the Entity pipeline — bind NPC-related entities to NPC profiles at generation time, add NPC turn processing at runtime, expose NPC visibility as independent output.

**Architecture:** Three layers: (1) module gen — prompt changes + deterministic entity-to-NPC binding via `_bind_npc_entities()`, (2) runtime — NPC turn with talk_to/intent-detect/parse/judge/enrich/curate, game_loop handles narration, NPC AT injected into main parse, (3) output — `npcs_visible` and `npc_events` fields in `run_turn()` return.

**Tech Stack:** Python dataclasses, DeepSeek LLM (flash model for intent detection), existing Judge/Curator/Narrator reuse.

---

### Task 1: NPC dataclass — add new fields

**Files:** Modify `src/game/npc_manager.py:8-24`

- [ ] **Step 1: Add `can_follow`, `follow_requirements`, `bound_interactions`, `bound_auto_triggers`**

```python
@dataclass
class NPC:
    name: str
    role: str = ""
    personality_notes: str = ""
    appearance: str = ""
    what_they_can_do: str = ""
    interaction_triggers: list[str] = field(default_factory=list)
    can_follow: bool = False
    follow_requirements: str = ""

    bound_interactions: list[dict] = field(default_factory=list)
    bound_auto_triggers: list[dict] = field(default_factory=list)

    scene: str = ""
    attitude: str = "neutral"
    following: bool = False
    memory: list[str] = field(default_factory=list)
    state: str = "alive"
    extra: dict | None = None
```

- [ ] **Step 2: Update `init_from_profiles()`**

```python
def init_from_profiles(self, profiles: dict):
    for name, data in profiles.items():
        self._npcs[name] = NPC(
            name=data.get("name", name),
            role=data.get("role", ""),
            personality_notes=data.get("personality_notes", ""),
            appearance=data.get("appearance", ""),
            what_they_can_do=data.get("what_they_can_do", ""),
            interaction_triggers=list(data.get("interaction_triggers", [])),
            can_follow=data.get("can_follow", False),
            follow_requirements=data.get("follow_requirements", ""),
            bound_interactions=list(data.get("bound_interactions", [])),
            bound_auto_triggers=list(data.get("bound_auto_triggers", [])),
            scene=data.get("scene", ""),
            state=data.get("initial_state", "alive"),
            following=data.get("initial_following", False),
            attitude=data.get("initial_attitude", "neutral"),
        )
```

- [ ] **Step 3: Update `from_dict()`**

```python
def from_dict(self, data: dict, profiles: dict):
    for name, state_data in data.items():
        profile = profiles.get(name, {})
        self._npcs[name] = NPC(
            name=name,
            role=profile.get("role", ""),
            personality_notes=profile.get("personality_notes", ""),
            appearance=profile.get("appearance", ""),
            what_they_can_do=profile.get("what_they_can_do", ""),
            interaction_triggers=list(profile.get("interaction_triggers", [])),
            can_follow=profile.get("can_follow", False),
            follow_requirements=profile.get("follow_requirements", ""),
            bound_interactions=list(profile.get("bound_interactions", [])),
            bound_auto_triggers=list(profile.get("bound_auto_triggers", [])),
            scene=state_data.get("scene", ""),
            attitude=state_data.get("attitude", "neutral"),
            following=state_data.get("following", False),
            memory=list(state_data.get("memory", [])),
            state=state_data.get("state", "alive"),
            extra=state_data.get("extra"),
        )
```

- [ ] **Step 4: Commit**

```bash
git add src/game/npc_manager.py
git commit -m "feat: add can_follow, follow_requirements, bound_entities to NPC dataclass"
```

---

### Task 2: NPCManager — state gate + follow conditions + enhanced talk_to

**Files:** Modify `src/game/npc_manager.py:27,72-99`

- [ ] **Step 1: Add constants and `_check_follow_conditions()` to NPCManager**

```python
class NPCManager:
    def __init__(self):
        self._npcs: dict[str, NPC] = {}

    STATE_GATE_MESSAGES: dict[str, str] = {
        "dead": "（{name} 已无法交谈）",
        "left": "（{name} 不在此处）",
    }

    def _check_follow_conditions(self, npc: NPC, world) -> tuple[bool, str]:
        """Check if NPC can follow. Returns (can_follow, reason_if_not)."""
        if not npc.can_follow:
            return False, f"{npc.name} 不愿意跟随你"
        if npc.state in ("dead", "left"):
            return False, f"{npc.name} 无法跟随（{npc.state}）"
        if npc.follow_requirements:
            from scenario_core import parse_hard_requirement
            met = parse_hard_requirement(npc.follow_requirements, world.runtime_state)
            if not met:
                return False, f"跟随条件尚未满足（{npc.follow_requirements}）"
        return True, ""
```

- [ ] **Step 2: Rewrite `talk_to()` with state gate + interaction_triggers + info-delivery instruction**

```python
    def talk_to(self, npc_name: str, player_input: str, llm_call) -> str:
        """State gate -> inject profile/memory context -> LLM -> append memory."""
        npc = self._npcs.get(npc_name)
        if not npc:
            return f"（{npc_name} 不在此处。）"

        gate = STATE_GATE_MESSAGES.get(npc.state, "")
        if gate:
            return gate.format(name=npc.name)

        triggers_text = ""
        if npc.interaction_triggers:
            triggers_text = f"互动触发条件：{'； '.join(npc.interaction_triggers)}\n"

        system_prompt = (
            f"你是 NPC「{npc.name}」。\n"
            f"角色：{npc.role}\n"
            f"性格：{npc.personality_notes}\n"
            f"外貌：{npc.appearance}\n"
            f"能力与所知信息：{npc.what_they_can_do}\n"
            + triggers_text
            + f"当前态度：{npc.attitude}\n"
            f"当前状态：{npc.state}\n"
            + (f"对话记忆：{'； '.join(npc.memory[-5:])}\n" if npc.memory else "")
            + "\n请用符合角色设定的语气回复调查员。\n"
            "若调查员询问或触及你能力范围内/互动触发条件中的信息，应如实告知所知内容，不刻意隐瞒。\n"
            "回复简洁（1-3句话）。"
        )
        user_prompt = f"调查员对你说：「{player_input}」"

        try:
            response = llm_call(user_prompt, system=system_prompt, json_mode=False)
        except Exception:
            response = f"（{npc.name} 沉默不语。）"

        npc.memory.append(f"玩家：「{player_input}」-> 回复：「{response}」")
        if len(npc.memory) > NPC_MEMORY_CAP:
            npc.memory = npc.memory[-20:]
        return response
```

- [ ] **Step 3: Commit**

```bash
git add src/game/npc_manager.py
git commit -m "feat: state gate, follow_conditions, enhanced talk_to with interaction_triggers"
```

---

### Task 3: NPC prompt builders — intent detection + NPC parse

**Files:** Modify `src/prompts.py` (append at end)

- [ ] **Step 1: Add `build_npc_intent_detect_prompt()`**

```python
def build_npc_intent_detect_prompt(user_input: str, npc_names: list[str]) -> str:
    """Flash LLM: determine if player input is actually talking to an NPC."""
    names_text = "、".join(npc_names)
    prompt = f"""判断玩家输入是否真的是在和 NPC 对话。

在场景中的 NPC：{names_text}
玩家输入：「{user_input}」

判断标准：
- 如果玩家在对 NPC 说话/询问/请求，is_talking=true
- 如果玩家只是在描述场景/物品中提到了 NPC 名字（如"墙上写着老妇人三字"、"老妇人的照片"），is_talking=false
- 如果玩家同时有对话意图和实体操作意图，is_talking=true

返回 JSON：
{{"is_talking": true/false, "npc_name": "对话目标NPC名称或空"}}

直接输出 JSON。"""
    _show_prompt("NPC Intent Detect", prompt)
    return prompt
```

- [ ] **Step 2: Add `build_npc_parse_prompt()`**

```python
def build_npc_parse_prompt(npc_name: str, user_input: str, bound_interactions: list[dict],
                            bound_auto_triggers: list[dict], current_scene: str) -> str:
    """NPC turn: match player input against NPC's bound entities (current scene only)."""
    scene_entities = [e for e in bound_interactions
                      if e.get("source_scene", "") == current_scene]
    scene_at = [e for e in bound_auto_triggers
                if e.get("source_scene", "") == current_scene]

    entity_text = ""
    for e in scene_entities:
        entity_text += f"  [INTERACT] id={e.get('id','')} name=\"{e.get('name','')}\" trigger=\"{e.get('trigger','')}\"\n"
    for e in scene_at:
        entity_text += f"  [AUTO_TRIGGER] id={e.get('id','')} name=\"{e.get('name','')}\" trigger=\"{e.get('trigger','')}\"\n"

    prompt = f"""你是 NPC「{npc_name}」的互动解析助手。判断玩家输入是否触发了以下实体。

【NPC 专属实体】
{entity_text or '（无）'}

【玩家输入】
{user_input}

返回 JSON：
{{
  "matched_entities": ["entity_id_1", "entity_id_2"],
  "follow_request": true/false,
  "reasoning": "简短匹配逻辑"
}}

follow_request：如果玩家请求 NPC 跟随自己（"跟我来""跟我走""跟着我"等），设为 true。
直接输出 JSON。"""
    _show_prompt("NPC Parse", prompt)
    return prompt
```

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "feat: add NPC intent detection and NPC parse prompt builders"
```

---

### Task 4: NPCManager.process_npc_turn — talk_to -> parse -> judge -> enrich -> curate

**Files:** Modify `src/game/npc_manager.py` (add method to NPCManager)

- [ ] **Step 1: Add `process_npc_turn()`**

Does NOT call narrator — returns NarratorBrief for game_loop to narrate, same as normal turns.

```python
    def process_npc_turn(self, npc_name: str, user_input: str, world,
                         llm_json, llm_text, judge, curator) -> dict:
        """Execute NPC turn: talk_to -> parse -> judge -> enrich -> curate.
        Returns {'brief': NarratorBrief, 'npc_events': [...], 'enrich': str}.
        game_loop handles narration.
        """
        from prompts import build_npc_parse_prompt, build_keeper_enrich_prompt
        from game.messages import ActionIntent, ActionOutcome, EnrichInput

        npc = self._npcs.get(npc_name)
        if not npc:
            return {"brief": f"（{npc_name} 不在此处。）"}

        dialogue = self.talk_to(npc_name, user_input, llm_text)

        matched_entity_ids = []
        follow_request = False
        matched_entities = []

        if npc.bound_interactions or npc.bound_auto_triggers:
            parse_prompt = build_npc_parse_prompt(
                npc_name, user_input, npc.bound_interactions, npc.bound_auto_triggers,
                world.current_location,
            )
            try:
                parse_result = llm_json(parse_prompt)
                matched_entity_ids = parse_result.get("matched_entities", [])
                follow_request = parse_result.get("follow_request", False)
            except Exception:
                matched_entity_ids = []

            all_bound = npc.bound_interactions + npc.bound_auto_triggers
            for eid in matched_entity_ids:
                for e in all_bound:
                    if e.get("id") == eid:
                        matched_entities.append(e)
                        break

        npc_events = []
        if follow_request:
            ok, reason = self._check_follow_conditions(npc, world)
            if ok:
                self.set_following(npc_name, True)
                npc_events.append(f"{npc_name} 开始跟随你")
            else:
                npc_events.append(reason)

        all_outcomes: list[ActionOutcome] = []
        enrich_input = EnrichInput()
        for entity in matched_entities:
            from scenario_core import Entity as EntityCls
            ent = EntityCls(
                id=entity.get("id", ""),
                entity_type=entity.get("entity_type", "interaction"),
                name=entity.get("name", ""),
                scene=entity.get("source_scene", ""),
                type=entity.get("type", ""),
                requirement=entity.get("requirement", ""),
                trigger=entity.get("trigger", ""),
                result=entity.get("result", ""),
                side_effects=entity.get("side_effects", []),
                graded_result=entity.get("graded_result"),
                difficulty=entity.get("difficulty", ""),
                extra=entity.get("extra"),
            )
            intent = ActionIntent(action="interact", target=entity.get("name", ""))
            outcome = judge._execute_entity(ent, intent=intent, player_input=user_input)
            all_outcomes.append(outcome)
            enrich_input.entities.append({
                "entity_type": ent.entity_type,
                "id": ent.id,
                "name": ent.name,
                "result": outcome.message,
                "success": outcome.success,
                "skill_tier": outcome.skill_tier,
            })
            if outcome.success:
                tr = entity.get("extra", {}).get("time_range") if entity.get("extra") else None
                enrich_input.actions.append({
                    "type": ent.entity_type,
                    "name": ent.name,
                    "success": True,
                    "time_range": tr,
                })

        enrich_prompt = build_keeper_enrich_prompt(world, enrich_input.entities, user_input)
        try:
            enrich_result = llm_json(enrich_prompt)
            enrich_text = enrich_result.get("results", dialogue)
            emphasis = enrich_result.get("emphasis_hint", "")
        except Exception:
            enrich_text = dialogue
            emphasis = ""

        if not all_outcomes:
            dialogue_outcome = ActionOutcome(
                intent=ActionIntent(action="other", target=npc_name),
                success=True, message=dialogue, entity_type="interaction",
            )
            all_outcomes = [dialogue_outcome]

        ambient_changes = [f"{npc_name}: {dialogue}"] if not matched_entities else []
        brief = curator.assemble(all_outcomes, ambient_changes, emphasis=emphasis)

        return {"brief": brief, "npc_events": npc_events, "enrich": enrich_text}
```

- [ ] **Step 2: Commit**

```bash
git add src/game/npc_manager.py
git commit -m "feat: add process_npc_turn -- talk_to/parse/judge/enrich/curate"
```

---

### Task 5: Keeper — NPC routing with intent detection + NPC AT injection

**Files:** Modify `src/game/agents/keeper.py:86-93`

- [ ] **Step 1: Replace NPC routing block (lines 86-93)**

```python
        # NPC interaction routing with intent detection
        if self.world.npcs:
            npcs_present = self.world.npcs.get_in_scene(self.world.current_location)
            npc_names = [n.name for n in npcs_present]
            matched_name = next((n for n in npc_names if n in raw), None)
            if matched_name:
                from prompts import build_npc_intent_detect_prompt
                intent_prompt = build_npc_intent_detect_prompt(raw, npc_names)
                try:
                    intent_result = call_deepseek(
                        intent_prompt, json_mode=True,
                        model=LLM_FLASH_MODEL, reasoning_effort="low",
                        system="你是回合解析助手。仅输出 JSON。",
                    )
                    is_talking = intent_result.get("is_talking", False)
                except Exception:
                    is_talking = True

                if is_talking:
                    npc_result = self.world.npcs.process_npc_turn(
                        npc_name=matched_name, user_input=raw,
                        world=self.world,
                        llm_json=lambda prompt, **kw: call_deepseek(prompt, json_mode=True, **kw),
                        llm_text=lambda prompt, **kw: call_deepseek(prompt, json_mode=False, **kw),
                        judge=self.judge, curator=self.curator,
                    )
                    npc_result["npc_events"] = npc_result.get("npc_events", [])
                    self._inject_npc_at()
                    return npc_result
```

- [ ] **Step 2: Add `_inject_npc_at()` method to Keeper**

```python
    def _inject_npc_at(self):
        """Inject condition-satisfied NPC auto-triggers into current node."""
        if not self.world.npcs:
            return
        for npc in self.world.npcs._npcs.values():
            for at in npc.bound_auto_triggers:
                at_scene = at.get("source_scene", "")
                if at_scene != self.world.current_location:
                    continue
                eid = at.get("id", "")
                req = at.get("requirement", "")
                if req:
                    from scenario_core import parse_hard_requirement
                    if not parse_hard_requirement(req, self.world.runtime_state):
                        continue
                node = self.world._current_node()
                if node:
                    existing_ids = {e.id for e in node.auto_triggers}
                    if eid not in existing_ids:
                        from scenario_core import Entity
                        node.auto_triggers.append(Entity(
                            id=eid, entity_type="auto_trigger",
                            name=at.get("name", ""), scene=at_scene,
                            type=at.get("type", ""), requirement=req,
                            trigger=at.get("trigger", ""), result=at.get("result", ""),
                            side_effects=at.get("side_effects", []),
                            graded_result=at.get("graded_result"),
                            difficulty=at.get("difficulty", ""),
                            extra=at.get("extra"),
                        ))
```

- [ ] **Step 3: Call `_inject_npc_at()` at start of normal parse path**

After the NPC routing block, before `# Step 1: Parse`:

```python
        # Inject NPC ATs before normal parse
        self._inject_npc_at()
```

- [ ] **Step 4: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: NPC intent detection routing + process_npc_turn + AT injection"
```

---

### Task 6: game_loop — npcs_visible + npc_events output

**Files:** Modify `src/game_loop.py:319-334` (before return in run_turn)

- [ ] **Step 1: Build NPC visible output before return**

```python
    # NPC visible output
    npcs_visible = {"in_scene": [], "following": []}
    npc_events_out = result.get("npc_events", [])
    if world.npcs:
        in_scene = world.npcs.get_in_scene(world.current_location)
        npcs_visible["in_scene"] = [n.name for n in in_scene if n.state not in ("dead", "left")]
        npcs_visible["following"] = [n.name for n in world.npcs.get_following()]
```

- [ ] **Step 2: Add to return dict**

After `"time_agent": result.get("time_agent"),`:

```python
        "npcs_visible": npcs_visible,
        "npc_events": npc_events_out,
```

- [ ] **Step 3: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: add npcs_visible and npc_events to run_turn output"
```

---

### Task 7: Module gen — Step 2.5 add can_follow field

**Files:** Modify `src/module_designer/layered_parser.py:762-821`

- [ ] **Step 1: Update STEP25_SYSTEM to mention can_follow**

Append before `- 仅输出 JSON`:

```
- can_follow：判断 NPC 是否可能跟随调查员行动。如果 NPC 的行动能力/性格/处境
  允许跟随（非固定在某地、无强制离开理由、愿意协助调查员），设为 true
```

- [ ] **Step 2: Update build_step25_prompt output format**

Add `"can_follow": true/false` in the npc_profiles output format example.

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: add can_follow to Step 2.5 NPC profile generation"
```

---

### Task 8: Module gen — Step 2a/2b prompt NPC exclusion rules

**Files:** Modify `src/module_designer/layered_parser.py`

- [ ] **Step 1: STEP2A_SYSTEM (line ~357)** — append before `- 仅输出 JSON`:

```
- NPC互动是否生成 entity 的判断标准：entity 必须有可感知的游戏机制后果：
  技能检定、物品给予/消耗、属性变化、NPC状态变更（受伤/死亡等）、
  触发新的事件、场景永久性变化。
  单纯的NPC对话/交谈/打听消息（无机制后果的信息传递）不生成 entity，
  由运行时 NPC 对话系统处理。
- NPC 跟随/离开/加入队伍不生成 entity（由运行时 NPC 跟随机制处理，
  条件由 npc_profile 的 can_follow + follow_requirements 控制）。
  entity 中不出现 NPC 跟随/离开玩家的描述。
```

- [ ] **Step 2: STEP2B_EVENTS_SYSTEM (line ~447)** — append before `- 仅输出 JSON`:

```
- 与NPC的纯粹对话/交谈不生成 event（NPC对话由运行时NPC系统处理）。
  只有涉及实质性世界影响的NPC互动才可生成 event。
- NPC 跟随/离开不生成 event。
```

- [ ] **Step 3: STEP2B_AT_SYSTEM (line ~543)** — append before `- 必须生成 AT_WORLD`:

```
- 与NPC的纯粹对话/交谈不生成 auto_trigger（NPC对话由运行时NPC系统处理）。
  只有涉及实质性世界影响的NPC互动才可生成 auto_trigger。
- NPC 跟随/离开不生成 auto_trigger。
```

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: add NPC exclusion rules to Step 2a/2b prompts"
```

---

### Task 9: Module gen — _bind_npc_entities() deterministic post-processing

**Files:** Modify `src/module_designer/layered_pipeline.py`

- [ ] **Step 1: Add `_bind_npc_entities()` function before `_assemble_l2()`**

```python
def _bind_npc_entities(interactions: list[dict], auto_triggers: list[dict],
                       npc_profiles: dict) -> tuple[list[dict], list[dict], dict]:
    """Scan entities for NPC name references -> strip from scene -> bind to NPC profile.
    Preserves entity IDs. Tags each bound entity with source_scene.
    """
    npc_names = set(npc_profiles.keys())
    if not npc_names:
        return interactions, auto_triggers, npc_profiles

    def _references_npc(entity: dict) -> str | None:
        fields = " ".join([
            entity.get("name", ""), entity.get("trigger", ""), entity.get("result", ""),
        ])
        for name in npc_names:
            if name in fields:
                return name
        return None

    def _is_follow_event(entity: dict) -> bool:
        combined = " ".join([
            entity.get("name", ""), entity.get("trigger", ""), entity.get("result", ""),
        ])
        follow_kw = ("跟随", "跟着", "加入队伍", "离开队伍", "开始跟随", "停止跟随")
        return any(kw in combined for kw in follow_kw)

    filtered_interactions = []
    filtered_auto_triggers = []

    for e in interactions:
        if _is_follow_event(e):
            continue
        npc_name = _references_npc(e)
        if npc_name:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_interactions", [])
            npc_profiles[npc_name]["bound_interactions"].append(e_copy)
        else:
            filtered_interactions.append(e)

    for e in auto_triggers:
        if _is_follow_event(e):
            continue
        npc_name = _references_npc(e)
        if npc_name:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_auto_triggers", [])
            npc_profiles[npc_name]["bound_auto_triggers"].append(e_copy)
        else:
            filtered_auto_triggers.append(e)

    return filtered_interactions, filtered_auto_triggers, npc_profiles
```

- [ ] **Step 2: Integrate into run_pipeline()**

After Step 3a + Step 2.5 results (after `npc_profiles = step25.get("npc_profiles", {})`), add:

```python
    interactions, auto_triggers, npc_profiles = _bind_npc_entities(
        interactions, auto_triggers, npc_profiles,
    )
    if verbose:
        bound_count = sum(
            len(p.get("bound_interactions", [])) + len(p.get("bound_auto_triggers", []))
            for p in npc_profiles.values()
        )
        print(f"  [NPC Bind] {bound_count} entities bound to NPCs")
```

Also update `_assemble_l2()` call args to pass updated `npc_profiles`.

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_pipeline.py
git commit -m "feat: add _bind_npc_entities deterministic post-processing"
```

---

### Task 10: Update readme TODO

**Files:** Modify `readme.md`

- [ ] **Step 1: Add NPC TODO items**

```markdown
| 14 | O15 | NPC 态度层级复杂影响 | 5级态度 -> 信息透露量/检定难度/战斗触发。当前仅注入 prompt 供 LLM 自行解读 |
| 15 | O16 | 世界状态更新纳入 NPC 关键事件 | NPC 跟随/死亡/态度转变等纳入 dependency graph 和 runtime_state |
| 16 | O17 | 半主动 NPC ambient triggers | NPCManager 预留 hook，未来对接 AutoTrigger 系统 |
| 17 | O18 | requirement 确定性 NPC 状态语法 | 如 NPC:name.attitude=friendly 形式的硬性条件解析 |
```

- [ ] **Step 2: Commit**

```bash
git add readme.md
git commit -m "docs: add NPC TODO items to readme"
```

---

### Task 11: Tests — NPC state gate + follow conditions

**Files:** Modify `tests/test_npc_manager.py`

- [ ] **Step 1: Add tests**

```python
def test_state_gate_dead_rejects():
    mgr = NPCManager()
    mgr._npcs["x"] = NPC(name="x", state="dead")
    result = mgr.talk_to("x", "hello", lambda prompt, **kw: "SHOULD_NOT_CALL")
    assert "无法交谈" in result

def test_state_gate_left_rejects():
    mgr = NPCManager()
    mgr._npcs["x"] = NPC(name="x", state="left")
    result = mgr.talk_to("x", "hello", lambda prompt, **kw: "SHOULD_NOT_CALL")
    assert "不在此处" in result

def test_follow_conditions_can_follow_false():
    mgr = NPCManager()
    npc = NPC(name="x", can_follow=False)
    mgr._npcs["x"] = npc
    ok, reason = mgr._check_follow_conditions(npc, world=None)
    assert not ok
    assert "不愿意" in reason

def test_follow_conditions_state_dead():
    mgr = NPCManager()
    npc = NPC(name="x", can_follow=True, state="dead")
    mgr._npcs["x"] = npc
    ok, reason = mgr._check_follow_conditions(npc, world=None)
    assert not ok
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH="src;." python -m pytest tests/test_npc_manager.py -v --tb=short
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_npc_manager.py
git commit -m "test: add NPC state gate and follow conditions tests"
```

---

### Task 12: Integration test — NPC turn routing

**Files:** Create `tests/test_npc_turn.py`

- [ ] **Step 1: Write test**

```python
"""Integration test: NPC turn routing with mocked LLM."""
from game.npc_manager import NPCManager, NPC

def test_follow_request_updates_state():
    from scenario_core import DirectedGraph, ScenarioWorld
    graph = DirectedGraph(scenes={
        "start": {"description": "", "interactions": [], "auto_triggers": []},
    })
    world = ScenarioWorld(graph, start_node="start")
    world.npcs = NPCManager()
    npc = NPC(name="老妇人", scene="start", can_follow=True)
    world.npcs._npcs["老妇人"] = npc
    ok, _ = world.npcs._check_follow_conditions(npc, world)
    assert ok
    world.npcs.set_following("老妇人", True)
    assert npc.following
    assert "老妇人" in [n.name for n in world.npcs.get_following()]

def test_state_gate_dead_no_dialogue():
    mgr = NPCManager()
    mgr._npcs["dead"] = NPC(name="dead", state="dead")
    r = mgr.talk_to("dead", "hi", lambda **kw: "X")
    assert "无法交谈" in r
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH="src;." python -m pytest tests/test_npc_turn.py -v --tb=short
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_npc_turn.py
git commit -m "test: add NPC turn routing integration tests"
```
