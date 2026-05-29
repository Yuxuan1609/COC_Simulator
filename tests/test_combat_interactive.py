"""COC 7th 战斗模拟器 — 交互式迷你游戏。

模拟游戏中触发 CombatInit 后的完整战斗流程：
选择武器 → 选择敌人 → 回合制战斗 → 结果

LLM prompt/response 日志位置: data/debug/combat_interactive/<timestamp>/

用法:
    python tests/test_combat_interactive.py
    python tests/test_combat_interactive.py --seed 42
"""
from __future__ import annotations
import sys, os, random, re, json as _json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from investigator.models import Investigator, Stats, DerivedStats, Skill
from investigator.rules import calc_derived
from game.combat import CombatSystem, CombatAction, _roll_damage, _apply_damage_multiplier
from game.messages import CombatInit

LOG_DIR: str | None = None   # 由 main() 设置


def _setup_log_dir():
    global LOG_DIR
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "debug",
                           "combat_interactive", ts)
    os.makedirs(LOG_DIR, exist_ok=True)
    print(f"\n📝 日志目录: {LOG_DIR}\n")
    return LOG_DIR


def _write_llm_log(call_idx: int, tag: str, system_prompt: str,
                   user_prompt: str, response: str):
    """写入 LLM 调用日志：system / user / response 分开记录。"""
    if not LOG_DIR:
        return
    idx_str = f"{call_idx:03d}"
    sys_path = os.path.join(LOG_DIR, f"{idx_str}_{tag}_system.txt")
    user_path = os.path.join(LOG_DIR, f"{idx_str}_{tag}_user.txt")
    resp_path = os.path.join(LOG_DIR, f"{idx_str}_{tag}_response.txt")
    with open(sys_path, "w", encoding="utf-8") as f:
        f.write(system_prompt)
    with open(user_path, "w", encoding="utf-8") as f:
        f.write(user_prompt)
    with open(resp_path, "w", encoding="utf-8") as f:
        f.write(response)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 特殊武器 CombatSystem 子类 — 处理 TEST_WEAPON 规则 + LLM 日志
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class _InteractiveCombatSystem(CombatSystem):
    """子类化 CombatSystem，LLM prompt/response 日志记录。"""

    _llm_call_counter: int = 0
    _log_tag: str = ""

    def _next_log_tag(self) -> str:
        self._llm_call_counter += 1
        return f"{self._llm_call_counter:03d}_{self._log_tag}"

    def _resolve_player_action(self, state, player, action_id: str,
                               target_iid: str, environment_actions=None) -> CombatAction:
        return super()._resolve_player_action(state, player, action_id,
                                              target_iid, environment_actions)

    def _generate_combat_narrative(self, state, player, scene: str) -> str:
        """带日志的战斗叙事生成。静态→system，动态→user，分开记录。"""
        if not state.full_log:
            return ""
        try:
            from llm import call_deepseek
            from config_llm import LLM_FLASH_MODEL

            log_lines = []
            enemies_desc = ", ".join(
                f"{getattr(e, 'enemy_ref', getattr(e, 'name', '未知'))}"
                for e in state.enemies
            )
            for a in state.full_log:
                hp_info = f" HP{a.hp_before}→{a.hp_after}" if a.damage > 0 else ""
                actor = "调查员" if a.actor == "player" else a.actor
                log_lines.append(
                    f"第{a.round_num}轮 {actor} {a.action_type}"
                    f"({a.skill_name}={a.skill_value} D100={a.roll} {a.tier})"
                    f" 伤害{a.damage}{hp_info}"
                )
            player_name = getattr(player, 'name', '调查员') if player else '调查员'

            # ── 分离静态/动态 ──
            system_prompt = (
                "你是TRPG战斗叙事者，简洁概述战斗过程。\n"
                "场景：" + scene + "\n"
                "调查员：" + player_name + "\n"
                "敌人：" + enemies_desc
            )
            user_prompt = (
                "根据以下战斗日志生成一段简洁的摘要（中文≤120字）：\n"
                + "\n".join(log_lines)
                + "\n\n返回 JSON：{\"summary\": \"...\"}，直接输出 JSON。"
            )

            response = call_deepseek(
                user_prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system=system_prompt,
                fallback_schema={"summary": ""},
            )
            data = _json.loads(response) if isinstance(response, str) else response
            summary = data.get("summary", "") or ""

            _write_llm_log(self._llm_call_counter + 1, "narrative",
                          system_prompt, user_prompt, summary)
            self._llm_call_counter += 1

            return summary
        except Exception:
            return ""

    def _llm_correct_round(self, round_result: dict, combat_init, enemies,
                           player_extra: str, battle_snapshot: str,
                           boss_phase: str, player_actions: list = None) -> dict:
        """带日志的 LLM 回合修正（与父类 prompt 结构保持一致）。"""
        try:
            from llm import call_deepseek
            from config_llm import LLM_FLASH_MODEL

            player_actions = player_actions or []
            player = combat_init.player
            inv_desc = getattr(player, 'personal_description', '') or ''
            if getattr(player, 'extra', ''):
                inv_desc = (inv_desc + '\n' + player.extra).strip()
            inv_name = getattr(player, 'name', '调查员')

            active_weapon_rules = ""
            active_weapon_name = ""
            attack_lines = []
            for i, pa in enumerate(player_actions):
                if pa.get("action_type") != "attack":
                    continue
                if not active_weapon_name and pa.get("weapon"):
                    active_weapon_name = pa["weapon"]
                    for w in getattr(player, 'weapons', []):
                        if getattr(w, 'name', '') == active_weapon_name:
                            active_weapon_rules = getattr(w, 'special_rules', '') or ''
                            break
                tgt = next((e for e in enemies if getattr(e, 'instance_id', '') == pa.get("target", "")), None)
                tgt_name = getattr(tgt, 'enemy_ref', pa.get("target", "?"))
                attack_lines.append(
                    f"第{i+1}击: {active_weapon_name or '基础攻击'} → {tgt_name}"
                    f" | D100={pa.get('roll', 0)} → {pa.get('tier', '')}"
                    f" | 原始伤害{pa.get('damage', 0)}（{pa.get('damage_type', '物理')}）"
                )
            if not attack_lines and player_actions:
                pa = player_actions[0]
                attack_lines.append(f"动作: {pa.get('action_type', '?')} | D100={pa.get('roll', 0)}")

            lines = []
            if inv_desc:
                lines.append(f"【调查员背景】\n{inv_name}: {inv_desc}")
            extra = (player_extra or '').strip()
            if extra:
                lines.append(f"【本轮额外意图】\n{extra}\n（仅在有特殊规则且意图匹配时生效）")

            lines.append(f"玩家使用「{active_weapon_name or '基础攻击'}」发动攻击：")
            lines.extend(attack_lines)

            if active_weapon_rules:
                lines.append(f"\n【武器特殊规则】\n{active_weapon_name}: {active_weapon_rules}")

            # 目标 + 在场敌人状态（不含护甲，护甲由固定规则结算）
            for pa in player_actions:
                tgt_iid = pa.get("target", "")
                tgt = next((e for e in enemies if getattr(e, 'instance_id', '') == tgt_iid), None)
                if tgt:
                    lines.append(f"\n【目标状态】{getattr(tgt, 'enemy_ref', '?')}: HP {getattr(tgt, 'hp', 0)}/{getattr(tgt, 'hp_max', 1)}")
                    break

            all_sr = []
            for e in enemies:
                sr = getattr(e, 'special_rules', '') or ''
                if sr:
                    tag = "[Boss]" if getattr(e, 'boss_mechanics', '') else ""
                    all_sr.append(f"{getattr(e, 'enemy_ref', '?')}{tag}: {sr}")
            if all_sr:
                lines.append(f"\n【在场敌人特殊规则】")
                lines.extend(all_sr)

            lines.append(f"\n【修正指令】\n请根据上述特殊规则修正 player_damage 和 narrative。")
            lines.append("返回 JSON：{\"player_damage\": <int>, \"narrative\": \"<string>\"}")

            user_prompt = "\n".join(lines)
            system_prompt = "你是 COC 7th 战斗裁判助理。根据武器/敌人特殊规则修正伤害值。narrative 用中文简述修正理由。"

            response = call_deepseek(
                user_prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system=system_prompt,
                fallback_schema={"player_damage": round_result.get("player_damage", 0),
                                "narrative": round_result.get("narrative", "")},
            )
            data = _json.loads(response) if isinstance(response, str) else response
            corrected = dict(round_result)
            corrected["player_damage"] = int(data.get("player_damage", round_result.get("player_damage", 0)))
            corrected["narrative"] = data.get("narrative", round_result.get("narrative", ""))

            _write_llm_log(self._llm_call_counter + 1, "correct",
                          system_prompt, user_prompt,
                          _json.dumps(corrected, ensure_ascii=False, indent=2))
            self._llm_call_counter += 1
            return corrected
        except Exception:
            return round_result

    def _llm_correct_enemy_round(self, enemy, action_data: dict, player,
                                 player_extra: str = "",
                                 investigator_context: str = "") -> dict:
        """带日志的敌人 LLM 回合修正。"""
        try:
            from llm import call_deepseek
            from config_llm import LLM_FLASH_MODEL

            enemy_name = getattr(enemy, 'enemy_ref', '敌人')
            atk_name = action_data.get("action_type", "攻击")
            roll = action_data.get("roll", 0)
            tier = action_data.get("tier", "")
            damage = action_data.get("damage", 0)
            dmg_type = action_data.get("damage_type", "物理")
            enemy_rules = getattr(enemy, 'special_rules', '') or ''
            inv_name = getattr(player, 'name', '调查员')

            lines = []
            if investigator_context:
                lines.append(f"【调查员背景】\n{inv_name}: {investigator_context}")
            extra = (player_extra or '').strip()
            if extra:
                lines.append(f"【本轮额外意图】\n{extra}\n（可能影响敌人攻击效果）")

            lines.append(f"{enemy_name}使用「{atk_name}」攻击{inv_name}")
            lines.append(f"D100={roll} → {tier}")
            lines.append(f"原始伤害值: {damage}（{dmg_type}）")

            if enemy_rules:
                lines.append(f"\n【敌人特殊规则】\n{enemy_name}: {enemy_rules}")

            if investigator_context:
                lines.append(f"\n【调查员特质影响】\n若调查员背景中有关联属性，请据此调整伤害。")

            lines.append(f"\n【修正指令】\n根据敌人特殊规则和调查员特质，修正伤害值。")
            lines.append("返回 JSON：{\"damage\": <int>, \"narrative\": \"<string>\"}")

            user_prompt = "\n".join(lines)
            system_prompt = "你是 COC 7th 战斗裁判助理。根据敌人特殊规则和调查员特质修正伤害。narrative 用中文简述修正理由。"

            response = call_deepseek(
                user_prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system=system_prompt,
                fallback_schema={"damage": damage, "narrative": ""},
            )
            data = _json.loads(response) if isinstance(response, str) else response
            result = {"damage": data.get("damage", damage), "narrative": data.get("narrative", "")}

            _write_llm_log(self._llm_call_counter + 1, f"enemy_{enemy_name}",
                          system_prompt, user_prompt,
                          _json.dumps(result, ensure_ascii=False, indent=2))
            self._llm_call_counter += 1
            return result
        except Exception:
            return {"damage": action_data.get("damage", 0), "narrative": ""}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 数据加载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_libraries():
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    wl = WeaponLibrary()
    wl.load_core()
    el = EnemyLibrary()
    el.load_core()
    return wl, el


def _make_investigator(name="调查员", hp=50, san=60):
    inv = Investigator()
    inv.name = name
    inv.personal_description = "退役士兵，左腿有旧伤。面对大型生物时容易紧张，但在近身格斗中经验丰富。对物理攻击有轻微心理阴影。"
    inv.extra = "【测试字段】后续 trait 系统扩展预留"
    inv.stats = Stats(STR=60, CON=60, SIZ=50, DEX=55, APP=50, INT=60, POW=55, EDU=60, LUCK=50)
    inv.derived = calc_derived(inv.stats)
    inv.derived.HP = hp
    inv.derived.HP_MAX = hp
    inv.derived.SAN = san
    inv.skills = [
        Skill(name="格斗", base_value=25, value=85, category="战斗"),
        Skill(name="格斗(拳)", base_value=25, value=85, category="战斗"),
        Skill(name="格斗(脚)", base_value=25, value=80, category="战斗"),
        Skill(name="回避", base_value=20, value=80, category="战斗"),
        Skill(name="潜行", base_value=20, value=80, category="感知"),
        Skill(name="手枪", base_value=20, value=85, category="战斗"),
        Skill(name="步枪", base_value=25, value=80, category="战斗"),
        Skill(name="霰弹枪", base_value=25, value=80, category="战斗"),
    ]
    return inv


def _spawn_enemy(lib_enemy, instance_id: str, quantity: int = 1):
    from game.enemy_manager import EnemyInstance
    attrs = lib_enemy.attributes
    base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * quantity
    hp_val = getattr(lib_enemy, 'hp', base_hp)
    if hp_val <= 0:
        hp_val = base_hp

    return EnemyInstance(
        instance_id=instance_id,
        enemy_ref=lib_enemy.name,
        scene="测试房间",
        quantity=quantity,
        status="hostile",
        flags=list(lib_enemy.flags),
        combat_behavior=lib_enemy.combat_behavior,
        description=lib_enemy.description,
        attributes=dict(attrs),
        armor=lib_enemy.armor,
        attacks=list(lib_enemy.attacks),
        special_abilities=list(lib_enemy.special_abilities),
        san_loss=lib_enemy.san_loss,
        hp=hp_val,
        multi_attack=getattr(lib_enemy, 'multi_attack', 1),
        damage_multipliers=dict(getattr(lib_enemy, 'damage_multipliers', {})),
        dodge_bonus=getattr(lib_enemy, 'dodge_bonus', 0),
        special_rules=getattr(lib_enemy, 'special_rules', ''),
        phases=list(getattr(lib_enemy, 'phases', [])),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 交互式 UI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _clear():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')


def _divider(char="═", width=56):
    print(char * width)


def _header(text: str):
    _divider()
    print(f"  {text}")
    _divider()
    print()


def choose_weapons(wl) -> list:
    """交互式选择武器。返回 LibraryWeapon 列表。"""
    weapons = wl.list_all()
    # 始终可用的基础动作
    fixed = [
        {"name": "拳击", "damage": "1D3+DB", "skill": "格斗", "val": 50},
        {"name": "踢击", "damage": "1D6+DB", "skill": "格斗", "val": 45},
    ]

    print("📦 基础动作（始终可用）：")
    for i, f in enumerate(fixed, 1):
        print(f"  {i}. {f['name']} ({f['damage']}) — {f['skill']}[{f['val']}]")
    print()

    print("📦 可选武器库：")
    shown = []
    idx = len(fixed) + 1
    for w in weapons:
        sr = getattr(w, 'special_rules', '') or ''
        tag = " ⚡测试武器" if "TEST_WEAPON" in sr else ""
        print(f"  {idx}. {w.name} ({w.damage}) — {w.skill_name}[?]{tag}")
        shown.append(w)
        idx += 1
    print()

    selected = []
    try:
        raw = input("选择武器（编号用逗号分隔，回车确认，或输入 a 选全部）: ").strip()
    except (EOFError, KeyboardInterrupt):
        return selected

    if raw.lower() == 'a':
        selected = list(shown)
        print(f"✅ 已装备全部 {len(shown)} 把武器")
        return selected

    for part in raw.replace(",", " ").split():
        part = part.strip()
        if not part.isdigit():
            continue
        n = int(part)
        if n <= len(fixed):
            continue  # 跳过基础动作（已内置）
        wi = n - len(fixed) - 1
        if 0 <= wi < len(shown):
            w = shown[wi]
            if w not in selected:
                selected.append(w)

    if selected:
        print(f"✅ 已装备：{', '.join(w.name for w in selected)}")
    else:
        print("⚠ 未选择武器，将仅使用拳击/踢击。")
    return selected


def choose_enemies(el) -> list[tuple]:
    """交互式选择敌人及数量。逐步选择，避免格式解析问题。"""
    enemies = [e for e in el.list_all() if e.name != "TestDummy"]

    print("👾 敌人库：")
    for i, e in enumerate(enemies, 1):
        attrs = e.attributes
        con, siz = attrs.get("CON", 50), attrs.get("SIZ", 50)
        est_hp = (con + siz) // 10
        armor = e.armor or "无"
        print(f"  {i}. {e.name} (HP~{est_hp}, 护甲:{armor})")
    print()

    selected = []
    while True:
        try:
            raw = input("添加敌人（编号 数量，如 1 2 表示 Clicker×2；直接回车完成）: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not raw:
            break
        parts = raw.split()
        if len(parts) < 1:
            continue
        try:
            n = int(parts[0])
            qty = int(parts[1]) if len(parts) >= 2 else 1
        except ValueError:
            print(f"  ⚠ 格式错误，示例: 1 2 (Clicker×2)")
            continue
        if 1 <= n <= len(enemies):
            qty = max(1, min(5, qty))
            selected.append((enemies[n - 1], qty))
            print(f"  ✅ 已添加: {enemies[n - 1].name} ×{qty}")
        else:
            print(f"  ⚠ 编号 {n} 超出范围 (1-{len(enemies)})")

    if selected:
        desc = ", ".join(f"{e.name} ×{q}" for e, q in selected)
        print(f"✅ 即将交战：{desc}")
    else:
        print("⚠ 未选择敌人，使用默认 Clicker x1。")
        selected = [(enemies[0], 1)]
    return selected

    # 兼容中英文逗号
    raw = raw.replace("，", ",").replace(",", " ")
    for part in raw.split():
        part = part.strip()
        qty = 1
        if "x" in part.lower() or "X" in part or "×" in part:
            try:
                # 统一替换为小写 x 再 split
                clean = part.lower().replace("×", "x")
                num_str, qty_str = clean.split("x", 1)
                part = num_str.strip()
                qty = max(1, min(5, int(qty_str.strip() or 1)))
            except ValueError:
                print(f"  ⚠ 跳过无效格式: {part}")
                continue
        if not part.isdigit():
            continue
        n = int(part)
        if 1 <= n <= len(enemies):
            selected.append((enemies[n - 1], qty))
        else:
            print(f"  ⚠ 编号 {n} 超出范围 (1-{len(enemies)})")

    if selected:
        desc = ", ".join(f"{e.name} x{q}" for e, q in selected)
        print(f"✅ 即将交战：{desc}")
    else:
        print("⚠ 未选择敌人，使用默认 Clicker x1。")
        selected = [(enemies[0], 1)]
    return selected


def _fmt_damage(dmg) -> str:
    """Format damage spec as readable string: 1D6+DB, 2d6+4, 特殊, etc."""
    if isinstance(dmg, dict):
        n, d, b, db = dmg.get("dice_n", 0), dmg.get("dice_d", 0), dmg.get("bonus", 0), dmg.get("use_db", False)
        parts = []
        if n > 0 and d > 0:
            parts.append(f"{n}D{d}")
        if b > 0:
            parts.append(f"+{b}")
        if db:
            parts.append("+DB")
        return "".join(parts) if parts else "0"
    return str(dmg) if dmg else "?"


def _get_enemy_display(enemy, show_id: bool = False) -> str:
    hp = getattr(enemy, 'hp', 0)
    hp_max = getattr(enemy, 'hp_max', hp) or 1
    hp_pct = int(hp / hp_max * 10) if hp_max > 0 else 0
    bar = "█" * hp_pct + "░" * (10 - hp_pct)
    status = getattr(enemy, 'status', '') or ''
    phase = getattr(enemy, '_current_phase', '') or ''
    extra = f" [{status}]" if status else ""
    extra += f" 🔥{phase}" if phase else ""
    name = getattr(enemy, 'enemy_ref', '?')
    if show_id:
        iid = getattr(enemy, 'instance_id', '')
        if iid:
            name += f" ({iid[-4:]})"
    return f"{name} HP {hp}/{hp_max} [{bar}]{extra}"


def combat_turn_loop(cs: CombatSystem, combat_init: CombatInit, player_weapons: list):
    """交互式回合制战斗循环。"""
    state = cs._init_combat(combat_init)
    environment_actions = getattr(combat_init, 'environment_actions', [])
    max_rounds = 20
    round_log = []

    player = combat_init.player
    available = cs._get_player_actions(player, environment_actions)

    # 构建武器名称→id 映射
    weapon_actions = [a for a in available if a["id"].startswith("weapon:")]
    env_actions = [a for a in available if a["id"].startswith("env:")]

    # 初始化敌人 hp_max
    for e in state.enemies:
        if not hasattr(e, 'hp_max') or not getattr(e, 'hp_max', 0):
            e.hp_max = getattr(e, 'hp', 10)
        if getattr(e, 'boss_mechanics', ''):
            state._boss_hp_max = getattr(e, 'hp_max', state.player_hp)

    _clear()
    _header("⚔ 战斗开始！")
    enemy_desc = ", ".join(_get_enemy_display(e) for e in state.enemies)
    print(f"你在 {combat_init.scene} 遭遇了 {enemy_desc}\n")

    needs_llm = cs._any_special_rules(combat_init, state.enemies)

    while not state.finished and state.round <= max_rounds:
        alive_enemies = [e for e in state.enemies
                        if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_enemies:
            state.finished = True
            break

        _divider("━")
        print(f"  第 {state.round} 轮")
        _divider("━")
        print(f"你的 HP: {state.player_hp}/{state.player_hp_max}  SAN: {state.player_san}")
        for e in state.enemies:
            print(f"  {_get_enemy_display(e)}")
        print()

        # ── 玩家行动选择 ──
        round_targets = []  # 本轮所有攻击目标（支持 multi_attack）
        while True:
            print("动作选项:")
            print("  a  攻击（选择武器和目标）")
            print("  d  回避")
            print("  f  逃跑")
            print("  c  隐蔽")
            print("  m  瞄准")
            print("  g  蓄力")
            choice = input("\n> ").strip().lower()

            if choice in ('d', 'f', 'c', 'm', 'g'):
                mapping = {'d': 'dodge', 'f': 'flee', 'c': 'conceal', 'm': 'aim', 'g': 'charge'}
                action_id = mapping[choice]
                round_targets = [alive_enemies[0].instance_id if alive_enemies else "unknown"]
                break
            elif choice == 'a':
                # 选择武器
                print("\n  武器选择：")
                wp_list = weapon_actions.copy()
                wp_list.extend(env_actions)
                punch_a = next((a for a in available if a["id"] == "punch"), None)
                kick_a = next((a for a in available if a["id"] == "kick"), None)
                display_list = []
                if punch_a:
                    display_list.append(("拳击", punch_a, ""))
                if kick_a:
                    display_list.append(("踢击", kick_a, ""))
                for wa in wp_list:
                    tag = ""
                    multi = wa.get("multi_attack", 1)
                    if multi > 1:
                        tag = f" ×{multi}"
                    display_list.append((wa["label"], wa, tag))

                for i, (label, wa, tag) in enumerate(display_list, 1):
                    dmg_fmt = _fmt_damage(wa.get("damage")) if isinstance(wa, dict) else ""
                    skill = wa.get("skill", "?") if isinstance(wa, dict) else ""
                    val = wa.get("value", "?") if isinstance(wa, dict) else ""
                    print(f"    {i}. {label} ({dmg_fmt}) — {skill}[{val}]{tag}")

                wp_choice = input("  选择武器编号: ").strip()
                if not wp_choice.isdigit():
                    continue
                wp_idx = int(wp_choice) - 1
                if 0 <= wp_idx < len(display_list):
                    _, chosen, _ = display_list[wp_idx]
                    action_id = chosen.get("id") if isinstance(chosen, dict) else chosen["id"]
                else:
                    continue

                # 获取 multi_attack 数量
                multi = chosen.get("multi_attack", 1) if isinstance(chosen, dict) else 1

                # 选择目标（multi_attack 次）
                round_targets = []
                for atk_i in range(multi):
                    if len(alive_enemies) == 1:
                        tgt = alive_enemies[0].instance_id
                        if multi == 1:
                            print(f"  目标: {_get_enemy_display(alive_enemies[0], show_id=True)}")
                    else:
                        print(f"\n  攻击 {atk_i + 1}/{multi} — 目标选择：")
                        for j, e in enumerate(alive_enemies, 1):
                            print(f"    {j}. {_get_enemy_display(e, show_id=True)}")
                        t_choice = input("  选择目标编号: ").strip()
                        if t_choice.isdigit() and 1 <= int(t_choice) <= len(alive_enemies):
                            tgt = alive_enemies[int(t_choice) - 1].instance_id
                        else:
                            round_targets = []
                            break
                    round_targets.append(tgt)
                if round_targets:
                    break
                else:
                    continue
            else:
                print("  无效选择。")
                continue

        # 设置 state 变量（run_combat 内部使用）
        state.log = []
        state._player_dodging = False
        state._player_concealed = getattr(state, '_player_concealed', False)
        state._player_aiming = getattr(state, '_player_aiming', False)
        state._player_charged = getattr(state, '_player_charged', False)

        player_actions = []
        enemy_actions = []

        # 按先攻顺序执行
        for iid in state.initiative_order:
            if iid == "player":
                for tgt in round_targets:
                    if not tgt:
                        continue
                    pa = cs._resolve_player_action(state, player, action_id, tgt, environment_actions)
                    pa.round_num = state.round
                    state.log.append(pa)
                    state.full_log.append(pa)
                    player_actions.append({
                        "action_type": pa.action_type,
                        "target": pa.target,
                        "weapon": pa.weapon,
                        "roll": pa.roll,
                        "tier": pa.tier,
                        "damage": pa.damage,
                        "damage_type": getattr(pa, 'damage_type', '物理'),
                        "effects": [],
                    })

                    # 打印玩家动作结果
                    tier_labels = {"extreme": "极难成功", "hard": "困难成功", "regular": "常规成功",
                                  "failure": "失败", "fumble": "大失败"}
                    tier_cn = tier_labels.get(pa.tier, pa.tier or "")
                    if pa.action_type == "dodge":
                        print(f"\n  ▶ 你进入了回避姿态。")
                    elif pa.action_type in ("conceal", "aim", "charge"):
                        print(f"\n  ▶ {pa.narrative}")
                    elif pa.action_type == "flee":
                        status = "✅" if pa.success else "❌"
                        print(f"\n  ▶ {status} {pa.narrative}")
                    elif pa.action_type == "attack":
                        status = "✓" if pa.success else "✗"
                        dmg_str = f" → 造成 {pa.damage} 点伤害" if pa.success and pa.damage > 0 else ""
                        target_name = getattr(
                            next((e for e in state.enemies if e.instance_id == tgt), None),
                            'enemy_ref', '?')
                        print(f"\n  ▶ {status} {pa.weapon} → {target_name} D100={pa.roll} {tier_cn}{dmg_str}")
                        print(f"     {pa.narrative}")

                    if state.finished:
                        break
                if state.finished:
                    break
                continue

            # 敌人行动
            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'status', '') == 'dead' or getattr(enemy, 'hp', 1) <= 0:
                continue

            multi = getattr(enemy, 'multi_attack', 1)
            for _ in range(multi):
                ea = cs._resolve_enemy_action(state, enemy, player)
                ea.round_num = state.round
                state.log.append(ea)
                state.full_log.append(ea)
                enemy_actions.append({
                    "actor": ea.actor,
                    "action_type": ea.action_type,
                    "roll": ea.roll,
                    "tier": ea.tier,
                    "damage": ea.damage,
                    "damage_type": getattr(ea, 'damage_type', '物理'),
                    "effects": [],
                })

                name = getattr(enemy, 'enemy_ref', '敌人')
                if ea.damage > 0:
                    print(f"\n  ◀ {name}用{ea.weapon}击中了你！D100={ea.roll} → 造成{ea.damage}点伤害")
                else:
                    miss_note = "被你闪开了！" if getattr(state, '_player_dodging', False) else "未能命中。"
                    print(f"  ◀ {name}的{ea.weapon} {miss_note}")

                if state.player_hp <= 0:
                    state.finished = True
                    break
            if state.finished:
                break

        # 构建本轮结果
        rresult = cs._build_round_result(state, player_actions, enemy_actions, state.round)

        if needs_llm:
            boss_phase = getattr(state, '_boss_current_phase', '') or ''
            snapshot = cs._build_battle_snapshot(state, player, boss_phase)
            rresult = cs._llm_correct_round(
                rresult, combat_init, state.enemies,
                getattr(combat_init, 'player_extra', '') or '', snapshot, boss_phase, player_actions
            )
            # 显示玩家修正结果
            for i, pa in enumerate(player_actions):
                if pa.get("damage", 0) != rresult.get("player_damage", 0) and pa.get("action_type") == "attack":
                    print(f"     ⚡ LLM修正: 第{i+1}击伤害 {pa['damage']} → {rresult['player_damage']}")

            # ── 敌人 LLM 修正 ──
            inv_context = getattr(player, 'personal_description', '') or ''
            if getattr(player, 'extra', ''):
                inv_context = (inv_context + '\n' + player.extra).strip()
            for ea_data in enemy_actions:
                old_dmg = ea_data.get("damage", 0)
                if old_dmg <= 0:
                    continue
                enemy_id = ea_data.get("actor", "")
                enemy = next((e for e in state.enemies
                             if getattr(e, 'instance_id', '') == enemy_id), None)
                if enemy and getattr(enemy, 'special_rules', ''):
                    from concurrent.futures import ThreadPoolExecutor
                    corrected = cs._llm_correct_enemy_round(
                        enemy, ea_data, player,
                        getattr(combat_init, 'player_extra', '') or '', inv_context
                    )
                    new_dmg = max(0, corrected.get("damage", old_dmg))
                    state.player_hp = max(0, state.player_hp + old_dmg - new_dmg)
                    ea_data["damage"] = new_dmg
                    if new_dmg != old_dmg:
                        print(f"     ⚡ LLM修正({getattr(enemy, 'enemy_ref', '?')}): 伤害 {old_dmg} → {new_dmg}")

        # 应用玩家伤害到敌人 — 每击独立结算
        corrected_dmg = rresult.get("player_damage", 0)
        for pa in player_actions:
            if pa.get("action_type") != "attack":
                continue
            dmg = pa.get("damage", 0)
            tgt_iid = pa.get("target", "")
            enemy = next((e for e in state.enemies if getattr(e, 'instance_id', '') == tgt_iid), None)
            if not enemy:
                continue
            # 使用 LLM 修正后的伤害值（取 max 防 None/空）
            try:
                effective_dmg = max(0, int(corrected_dmg if corrected_dmg is not None else dmg))
            except (ValueError, TypeError):
                effective_dmg = max(0, int(dmg) if dmg else 0)
            old_hp = getattr(enemy, 'hp', 10)
            enemy.hp = max(0, old_hp - effective_dmg)
            if effective_dmg > 0:
                print(f"     {getattr(enemy, 'enemy_ref', '敌人')} HP: {old_hp} → {enemy.hp}"
                      + (f" (LLM修正: {dmg} → {effective_dmg})" if effective_dmg != dmg else ""))

        # 检查阶段触发
        for enemy in state.enemies:
            if getattr(enemy, 'hp', 1) <= 0 or getattr(enemy, 'status', '') == 'dead':
                continue
            triggered = cs._check_phase(state, enemy)
            if triggered:
                desc = cs._apply_phase(state, enemy, triggered, getattr(enemy, 'phases', []))
                if desc:
                    print(f"\n  🔥 {getattr(enemy, 'enemy_ref', '敌人')} 进入【{triggered}】阶段！{desc}")

        round_log.append(rresult)

        alive_after = [e for e in state.enemies
                      if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_after:
            state.finished = True

        state.round += 1
        print()

    # ── 战斗结果 ──
    _divider("═")
    outcome = "win"
    if state.player_hp <= 0:
        outcome = "loss"
    elif state.round > max_rounds:
        outcome = "draw"

    outcome_labels = {"win": "✅ 胜利！", "loss": "💀 败北！", "draw": "⏱ 时间耗尽，平局"}
    print(f"  {outcome_labels.get(outcome, outcome)}")
    print(f"  轮数: {state.round - 1}")
    print(f"  剩余 HP: {state.player_hp}/{state.player_hp_max}")
    print(f"  剩余 SAN: {state.player_san}")

    defeated = [e for e in state.enemies
                if getattr(e, 'hp', 1) <= 0 or getattr(e, 'status', '') == 'dead']
    if defeated:
        print(f"  击败: {', '.join(getattr(e, 'enemy_ref', '?') for e in defeated)}")
    survivors = [e for e in state.enemies if e not in defeated]
    if survivors and outcome == "loss":
        hp_list = ", ".join(f"{getattr(e, 'enemy_ref', '?')}(HP{getattr(e, 'hp', 0)})" for e in survivors)
        print(f"  存活敌人: {hp_list}")
    _divider("═")

    # 生成战斗叙事
    narrative = cs._generate_combat_narrative(state, player, combat_init.scene)
    if narrative:
        print(f"\n  📜 战斗总结：{narrative}")

    return outcome


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主入口
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    import argparse
    parser = argparse.ArgumentParser(description="COC 7th 战斗模拟器")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（复现战斗）")
    parser.add_argument("--quick", action="store_true",
                       help="快速模式：跳过选择，用默认配置直接战斗")
    parser.add_argument("--preset", action="store_true",
                       help="预设模式：固定 2 深潜者 + 1 Clicker，跳过选择")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    _setup_log_dir()

    # 加载库
    wl, el = _load_libraries()

    # 交互式选择
    if args.preset:
        selected_weapons = [wl.get("试作型裁决者")] if wl.get("试作型裁决者") else []
        selected_enemies = [(el.get("深潜者"), 2), (el.get("Clicker"), 1)]
        print("⚡ 预设模式：深潜者 x2 + Clicker x1 + 试作型裁决者")
    elif args.quick:
        selected_weapons = []
        selected_enemies = [(el.get("Clicker"), 1)]
        print("⚡ 快速模式：武器=默认，敌人=Clicker x1")
    else:
        selected_weapons = choose_weapons(wl)
        print()
        selected_enemies = choose_enemies(el)
        print()

    if not selected_enemies:
        print("没有敌人，退出。")
        return

    # 创建调查员并装备武器
    player = _make_investigator()
    # 将 LibraryWeapon 转为 Investigator 武器格式
    from library.weapons import LibraryWeapon
    player.weapons = []
    for w in selected_weapons:
        if isinstance(w, LibraryWeapon):
            # 创建一个简单武器对象挂到 player 上
            class _Wpn:
                def __init__(self, lw):
                    self.name = lw.name
                    self.skill_name = lw.skill_name
                    self.skill_used = lw.skill_name
                    self.damage = lw.damage
                    self.damage_type = getattr(lw, 'damage_type', '物理')
                    self.armor_piercing = getattr(lw, 'armor_piercing', 0)
                    self.attack_bonus = getattr(lw, 'attack_bonus', 0)
                    self.multi_attack = getattr(lw, 'multi_attack', 1)
                    self.special_rules = getattr(lw, 'special_rules', '')
                    self.range = getattr(lw, 'range', '近战')
            player.weapons.append(_Wpn(w))

    # 生成敌人实例
    enemy_instances = []
    import uuid
    for lib_enemy, qty in selected_enemies:
        for qi in range(qty):
            iid = f"{lib_enemy.name}_{uuid.uuid4().hex[:8]}"
            inst = _spawn_enemy(lib_enemy, iid, 1)
            enemy_instances.append(inst)
    print(f"🎯 生成了 {len(enemy_instances)} 个敌人实例")
    for ei in enemy_instances:
        print(f"   [{ei.instance_id[-4:]}] {ei.enemy_ref} HP={ei.hp}")

    # 构建 CombatInit
    combat_init = CombatInit(
        enemies=enemy_instances,
        player=player,
        scene="测试房间",
        initiative_context="模拟战斗 — 交互式 Smoke Test",
    )

    # 运行战斗
    cs = _InteractiveCombatSystem()
    combat_turn_loop(cs, combat_init, selected_weapons)

    print("\n战斗模拟结束。感谢使用！")


if __name__ == "__main__":
    main()
