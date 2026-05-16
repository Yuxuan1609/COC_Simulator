# tests/test_entity_resolvers.py
import sys
sys.path.insert(0, "src")
from scenario_core import resolve_graded_result, has_ending, Entity


def test_resolve_graded_failure():
    e = Entity(id="I1", entity_type="interaction", name="test",
               result="##GRADED##",
               graded_result={
                   "on_failure": "你失败了",
                   "on_regular": "你成功了",
                   "on_hard": "你做得很好",
                   "on_extreme": "你完美达成"
               })
    result = resolve_graded_result(e, "failure")
    assert result == "你失败了"


def test_resolve_graded_regular():
    e = Entity(id="I1", entity_type="interaction", name="test",
               result="##GRADED##",
               graded_result={"on_failure": "fail", "on_regular": "ok"})
    assert resolve_graded_result(e, "regular") == "ok"


def test_resolve_graded_not_graded():
    e = Entity(id="I1", entity_type="interaction", name="test",
               result="plain result text")
    assert resolve_graded_result(e, "regular") == "plain result text"


def test_resolve_graded_fallback():
    """Unknown tier falls back to closest available tier."""
    e = Entity(id="I1", entity_type="interaction", name="test",
               result="##GRADED##",
               graded_result={"on_failure": "fail", "on_regular": "ok"})
    result = resolve_graded_result(e, "extreme")  # no on_extreme
    assert result == "ok"  # fallback to closest available


def test_has_ending():
    assert has_ending("##END_坏结局:电车被吞噬##") == ("坏结局", "电车被吞噬")


def test_has_ending_no_match():
    assert has_ending("ordinary result") == (None, None)


def test_has_ending_in_entity():
    e = Entity(id="E1", entity_type="event", name="test",
               result="##END_真结局:逃脱成功##")
    name, desc = has_ending(e.result)
    assert name == "真结局"
    assert desc == "逃脱成功"
