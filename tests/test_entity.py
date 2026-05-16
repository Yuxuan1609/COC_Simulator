# tests/test_entity.py
import sys
sys.path.insert(0, "src")
from scenario_core import Entity


def test_entity_interaction():
    e = Entity(
        id="I1", entity_type="interaction", name="感知电车异常",
        scene="6号车厢", type="侦查", trigger="调查员苏醒时",
        result="##GRADED##",
        graded_result={
            "on_failure": "你没有察觉异常",
            "on_regular": "你意识到电车异常",
            "on_hard": "你明确察觉时间异常",
            "on_extreme": "你瞬间意识到诡异"
        },
        difficulty="regular"
    )
    assert e.id == "I1"
    assert e.entity_type == "interaction"
    assert e.scene == "6号车厢"
    assert e.graded_result["on_regular"] == "你意识到电车异常"


def test_entity_event():
    e = Entity(
        id="E1", entity_type="event", name="退路断绝",
        result="##END_坏结局:电车被吞噬##"
    )
    assert e.entity_type == "event"
    assert e.scene == ""  # events have no scene
    assert e.result.startswith("##END_")


def test_entity_auto_trigger():
    e = Entity(
        id="AT1", entity_type="auto_trigger", name="闻到血腥味",
        scene="7号车厢", result="一股浓烈的血腥臭味飘来",
        side_effects=["@stat_change(stat_name=SAN, delta=-1, narrative=闻到血腥味感到不安)"]
    )
    assert e.entity_type == "auto_trigger"
    assert "@stat_change" in e.side_effects[0]
