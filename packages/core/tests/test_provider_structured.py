"""M4-A 受限生成: provider 层 json_schema 透传 + 4xx 降级重试。

Run: cd <repo> && python -m pytest packages/core/tests/test_provider_structured.py -q
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from topoone.llm.providers import ollama as ollama_mod  # noqa: E402
from topoone.llm.providers import openai_compat as oc_mod  # noqa: E402

_SCHEMA = {"type": "object", "properties": {"tool": {"type": "string"}},
           "required": ["tool"]}
_MODEL = {"model": "m", "url": "http://x", "max_tokens": 100}


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def test_ollama_structured_passes_format(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "payload": json})
        return _Resp(200, {"message": {"content": "{}"}, "prompt_eval_count": 1,
                           "eval_count": 1})

    monkeypatch.setattr(ollama_mod.requests, "post", fake_post)
    ollama_mod.OllamaProvider().chat_sync(_MODEL, [], "structured", None, _SCHEMA)
    assert len(calls) == 1
    assert calls[0]["payload"]["format"] == _SCHEMA


def test_ollama_format_rejected_downgrades(monkeypatch):
    """老版本/网关拒收 format(4xx) → 降级重试一次不带 format(回提示词约束基线)。"""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(dict(json))
        if "format" in json:
            return _Resp(400, {"error": "format not supported"})
        return _Resp(200, {"message": {"content": "{}"}, "prompt_eval_count": 1,
                           "eval_count": 1})

    monkeypatch.setattr(ollama_mod.requests, "post", fake_post)
    ollama_mod.OllamaProvider().chat_sync(_MODEL, [], "structured", None, _SCHEMA)
    assert len(calls) == 2
    assert "format" in calls[0] and "format" not in calls[1]


def test_openai_compat_structured_response_format(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        if json.get("response_format") and calls.index(json) == 0:
            return _Resp(200, {"choices": [{"message": {"content": "{}"}}],
                               "usage": {}})
        return _Resp(200, {"choices": [{"message": {"content": "{}"}}],
                           "usage": {}})

    monkeypatch.setattr(oc_mod.requests, "post", fake_post)
    oc_mod.OpenAICompatProvider().chat_sync(_MODEL, [], "structured", None, _SCHEMA)
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["schema"] == _SCHEMA


def test_openai_compat_response_format_rejected_downgrades(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(dict(json))
        if "response_format" in json:
            return _Resp(400, {"error": "unsupported"})
        return _Resp(200, {"choices": [{"message": {"content": "{}"}}],
                           "usage": {}})

    monkeypatch.setattr(oc_mod.requests, "post", fake_post)
    oc_mod.OpenAICompatProvider().chat_sync(_MODEL, [], "structured", None, _SCHEMA)
    assert len(calls) == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]


def test_chat_mode_untouched():
    """chat/tools 模式 payload 不携带 structured 字段(现行为不变)。"""
    seen = []

    def fake_post(url, json=None, timeout=None):
        seen.append(json)
        return _Resp(200, {"message": {"content": "x"}, "eval_count": 1})

    ollama_mod.requests.post = fake_post
    try:
        ollama_mod.OllamaProvider().chat_sync(_MODEL, [], "chat", None, _SCHEMA)
    finally:
        del ollama_mod.requests.post
    assert "format" not in seen[0]
