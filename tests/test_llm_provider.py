"""LLM provider 列表 + 402 切 fallback。"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class _FakeStatusError(Exception):
    def __init__(self, status_code, message="err"):
        super().__init__(message)
        self.status_code = status_code


def test_should_fallback_only_on_402():
    from llm import _should_fallback
    assert _should_fallback(_FakeStatusError(402, "Insufficient Balance"))
    assert not _should_fallback(_FakeStatusError(401, "invalid api key"))
    assert not _should_fallback(_FakeStatusError(429, "rate limit"))
    assert not _should_fallback(RuntimeError("timeout"))


def test_map_model_uses_fallback_flash():
    from llm import _map_model
    fb = {"default_model": "deepseek-v4-flash", "flash_model": "deepseek-v4-flash"}
    assert _map_model("deepseek-v4-flash-vision-exp", fb) == "deepseek-v4-flash"
    assert _map_model("deepseek-v4-flash", fb) == "deepseek-v4-flash"


def test_chat_create_402_switches_to_fallback(monkeypatch):
    import llm

    class _Primary:
        def __init__(self):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw):
            raise _FakeStatusError(402, "Insufficient Balance")

    class _Fallback:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kw):
            self.calls.append(kw)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content='{"ok": true}'))])

    fb = _Fallback()
    monkeypatch.setattr(llm, "client", _Primary())
    monkeypatch.setattr(llm, "_fallback_client", fb)
    monkeypatch.setattr(llm, "_fallback_provider", {
        "default_model": "deepseek-v4-flash", "flash_model": "deepseek-v4-flash"})
    monkeypatch.setattr(llm, "_use_fallback", False)

    resp = llm._chat_create(model="deepseek-v4-flash-vision-exp", messages=[])
    assert fb.calls, "402 后必须改走 fallback client"
    assert fb.calls[0]["model"] == "deepseek-v4-flash"
    assert resp.choices[0].message.content == '{"ok": true}'
    assert llm._use_fallback is True
