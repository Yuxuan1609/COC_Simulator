"""Quasi-unit tests for IntentDetector — LLM calls are mocked."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
from game.intent_detector import IntentDetector, IntentResult


def _mock_call_deepseek(prompt, json_mode, model, system, reasoning_effort=None,
                        fallback_schema=None):
    """Simulate LLM responses for detector tests."""
    # Check meaningful intent first — the prompt template itself contains
    # "唱歌"/"讲笑话" in the examples section, so those must be checked after.
    if "对话" in prompt or "黑影" in prompt:
        return json.dumps({
            "has_intent": True,
            "intent": "玩家试图与黑暗中的存在进行交流",
            "reasoning": "模组中没有与存在沟通的机制，这是全新的叙事路径"
        })
    if "唱首歌" in prompt or "讲笑话" in prompt:
        return json.dumps({"has_intent": False, "intent": "", "reasoning": "纯角色扮演行为"})
    return json.dumps({"has_intent": False, "intent": "", "reasoning": ""})


def test_detector_flavor_behavior(monkeypatch):
    """Pure RP like singing should not trigger author."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("唱了一首快乐的小曲", {"location": "测试房间"})

    assert isinstance(result, IntentResult)
    assert result.needs_author is False


def test_detector_meaningful_intent(monkeypatch):
    """Narrative-breaking intent should trigger author."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("试图和远处那个黑影对话", {"location": "7号车厢"})

    assert result.needs_author is True
    assert len(result.intent) > 0
    assert len(result.reasoning) > 0


def test_detector_empty_other(monkeypatch):
    """Empty input should not trigger."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("", {"location": "测试房间"})

    assert result.needs_author is False
