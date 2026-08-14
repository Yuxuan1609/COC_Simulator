"""场景谓词注册表：声明式机器谓词，输入为 llm_player 每回合 summary 日志条目列表。

每个谓词函数签名：`fn(entries: list[dict]) -> bool`。
entries 为 _summary.json 的 turns_detail（含 input/brief/combat/pending/
npcs_visible/weapons/player_alive/location/ending 等字段）。
llm_player 的 success_checks 与 run_scenario 的 predicates 判定共用本注册表。
"""

PREDICATES = {}


def predicate(fn):
    PREDICATES[fn.__name__] = fn
    return fn


@predicate
def combat_occurred(entries: list[dict]) -> bool:
    """任意回合发生了战斗结算。"""
    return any(e.get("combat") for e in entries)


@predicate
def standoff_occurred(entries: list[dict]) -> bool:
    """任意回合触发了对峙（pending_interaction.kind == standoff）。"""
    return any(e.get("pending") == "standoff" for e in entries)


@predicate
def weapon_picked_up(entries: list[dict]) -> bool:
    """玩家拾取了武器：a) 系统输出"你拾起了"（offer/直接拾取通路均输出）；
    b) 武器数量相对首回合记录值增长（兜底，首回合内拾取时该通道有盲区）。"""
    for e in entries:
        text = f"{e.get('brief') or ''}{e.get('narrative') or ''}"
        if "你拾起了" in text:
            return True
    if len(entries) >= 2:
        baseline = len(entries[0].get("weapons") or [])
        return any(len(e.get("weapons") or []) > baseline for e in entries[1:])
    return False


@predicate
def npc_following(entries: list[dict]) -> bool:
    """任意回合有 NPC 处于跟随状态。"""
    return any(e.get("npcs_visible", {}).get("following") for e in entries)


@predicate
def game_over(entries: list[dict]) -> bool:
    """任意回合触发了结局。"""
    return any(e.get("ending") for e in entries)


@predicate
def player_alive(entries: list[dict]) -> bool:
    """末回合玩家仍然存活。"""
    return bool(entries) and bool(entries[-1].get("player_alive", True))
