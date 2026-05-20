"""Tests for NPC dataclass + NPCManager."""
from game.npc_manager import NPC, NPCManager


def _make_npc(name="京山 人吉", scene="4号车厢"):
    return NPC(
        name=name,
        role="受伤的电车乘务员",
        personality_notes="求生欲强烈，受伤后虚弱无助",
        appearance="三十岁左右男性，身穿标准铁路制服，腿部有严重撕裂伤",
        what_they_can_do="提供关键信息（钥匙位置、怪物弱点）",
        interaction_triggers=["尝试急救", "主动交谈"],
        scene=scene,
    )


def test_npc_creation():
    npc = _make_npc()
    assert npc.name == "京山 人吉"
    assert npc.attitude == "neutral"
    assert npc.following is False
    assert npc.state == "alive"
    assert len(npc.memory) == 0


def test_talk_to_basic():
    mgr = NPCManager()
    profiles = {
        "京山 人吉": {
            "name": "京山 人吉",
            "role": "受伤的乘务员",
            "personality_notes": "虚弱但负责",
            "appearance": "身穿制服，腿部受伤",
            "what_they_can_do": "提供信息",
            "interaction_triggers": ["交谈"],
        }
    }
    mgr.init_from_profiles(profiles)

    def mock_llm(prompt, **kwargs):
        return "（乘务员虚弱地说）钥匙...在3号车厢的挎包里..."

    response = mgr.talk_to("京山 人吉", "钥匙在哪里？", mock_llm)
    assert "钥匙" in response
    assert len(mgr.get("京山 人吉").memory) > 0


def test_following_sync():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "NPC_A": {"name": "NPC_A", "role": "", "personality_notes": "",
                   "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
        "NPC_B": {"name": "NPC_B", "role": "", "personality_notes": "",
                   "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_scene("NPC_A", "1号车厢")
    mgr.set_scene("NPC_B", "2号车厢")
    mgr.set_following("NPC_A", True)

    assert mgr.get("NPC_A").following is True
    assert mgr.get("NPC_B").following is False

    mgr.sync_followers("3号车厢")
    assert mgr.get("NPC_A").scene == "3号车厢"
    assert mgr.get("NPC_B").scene == "2号车厢"


def test_get_in_scene():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "A": {"name": "A", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
        "B": {"name": "B", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_scene("A", "1号车厢")
    mgr.set_scene("B", "2号车厢")
    assert len(mgr.get_in_scene("1号车厢")) == 1
    assert mgr.get_in_scene("1号车厢")[0].name == "A"


def test_npc_state_changes():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "A": {"name": "A", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_attitude("A", "friendly")
    assert mgr.get("A").attitude == "friendly"
    mgr.set_state("A", "injured")
    assert mgr.get("A").state == "injured"


def test_serialization_roundtrip():
    mgr = NPCManager()
    profiles = {
        "NPC1": {"name": "NPC1", "role": "测试", "personality_notes": "性格",
                  "appearance": "外貌", "what_they_can_do": "能力", "interaction_triggers": ["触发1"]},
    }
    mgr.init_from_profiles(profiles)
    mgr.set_scene("NPC1", "2号车厢")
    mgr.set_attitude("NPC1", "friendly")
    mgr.set_following("NPC1", True)
    mgr.get("NPC1").memory.append("玩家问了钥匙的事")

    data = mgr.to_dict()
    mgr2 = NPCManager()
    mgr2.init_from_profiles(profiles)
    mgr2.from_dict(data, profiles)
    npc = mgr2.get("NPC1")
    assert npc.scene == "2号车厢"
    assert npc.attitude == "friendly"
    assert npc.following is True
    assert "钥匙" in npc.memory[0]
