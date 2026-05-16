# tests/test_markup.py
import sys
sys.path.insert(0, "src")
from scenario_core import parse_markup, parse_markup_all, ItemGain, StatChange, SpawnEnemy, GrantWeapon, NPCStateChange


def test_parse_spawn_enemy():
    result = parse_markup("@spawn_enemy(enemy_ref=Clicker, scene=7号车厢, quantity=2)")
    assert isinstance(result, SpawnEnemy)
    assert result.enemy_ref == "Clicker"
    assert result.scene == "7号车厢"
    assert result.quantity == 2


def test_parse_grant_weapon():
    result = parse_markup("@grant_weapon(weapon_ref=手电筒, scene=, quantity=1)")
    assert isinstance(result, GrantWeapon)
    assert result.weapon_ref == "手电筒"
    assert result.quantity == 1


def test_parse_stat_change():
    result = parse_markup("@stat_change(stat_name=SAN, delta=-1d4, narrative=目睹惨状)")
    assert isinstance(result, StatChange)
    assert result.stat_name == "SAN"
    assert result.delta == "-1d4"
    assert result.narrative == "目睹惨状"


def test_parse_item_gain():
    result = parse_markup("@item_gain(item_name=钥匙)")
    assert isinstance(result, ItemGain)
    assert result.item_name == "钥匙"


def test_parse_npc_state_change():
    result = parse_markup("@npc_state_change(npc_name=京山人吉, new_state=清醒)")
    assert isinstance(result, NPCStateChange)
    assert result.npc_name == "京山人吉"
    assert result.new_state == "清醒"


def test_parse_multiple_markups():
    text = "@item_gain(item_name=钥匙) and @stat_change(stat_name=SAN, delta=-1, narrative=test)"
    results = parse_markup_all(text)
    assert len(results) == 2
    assert isinstance(results[0], ItemGain)
    assert isinstance(results[1], StatChange)


def test_parse_markup_no_match():
    result = parse_markup("plain text with no markup")
    assert result is None


def test_parse_markup_all_no_match():
    results = parse_markup_all("just ordinary text")
    assert results == []
