from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from smart_home_sim.hybrid_planning.lmstudio import (
    ChatMessage,
    LMStudioClient,
    LMStudioConfig,
    LMStudioContentError,
    LMStudioResponseError,
    LMStudioUnavailableError,
    extract_json_value,
)


def _envelope(content: str, *, finish: str = "stop", usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": usage if usage is not None else {"total_tokens": 12},
    }


def _client(content: str, **config: object) -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        return json.dumps(_envelope(content))

    return LMStudioClient(LMStudioConfig(**config), transport=transport)


def _raising_client(error: Exception) -> LMStudioClient:
    def transport(url: str, body: bytes, timeout: float) -> str:
        raise error

    return LMStudioClient(transport=transport)


def test_extract_bare_object_and_array() -> None:
    assert extract_json_value('{"a": 1}') == {"a": 1}
    assert extract_json_value("[1, 2, 3]") == [1, 2, 3]


def test_extract_from_json_fence() -> None:
    text = "Here you go:\n```json\n{\"a\": 1}\n```\nDone."
    assert extract_json_value(text) == {"a": 1}


def test_extract_from_plain_fence() -> None:
    text = "```\n{\"b\": 2}\n```"
    assert extract_json_value(text) == {"b": 2}


def test_extract_from_surrounding_prose_and_braced_strings() -> None:
    text = 'The plan is {"note": "has } and { braces", "n": 2} okay?'
    assert extract_json_value(text) == {"note": "has } and { braces", "n": 2}


def test_extract_handles_escaped_quotes_inside_strings() -> None:
    text = 'prose {"a": "he said \\" and } stay", "n": 1} tail'
    assert extract_json_value(text) == {"a": 'he said " and } stay', "n": 1}


def test_extract_prefers_answer_after_reasoning_block() -> None:
    text = (
        "<think>Keys: {\"name\": ...} and a decoy {\"a\": 999}</think>\n"
        'Here is the result:\n{"a": 1, "b": 2}'
    )
    assert extract_json_value(text) == {"a": 1, "b": 2}


def test_extract_handles_dangling_close_think_tag() -> None:
    text = 'reasoning with a { brace </think>\n{"final": true}'
    assert extract_json_value(text) == {"final": True}


def test_extract_without_json_raises() -> None:
    with pytest.raises(LMStudioContentError):
        extract_json_value("no json here at all")


def test_extract_with_unbalanced_opener_raises() -> None:
    with pytest.raises(LMStudioContentError):
        extract_json_value('prefix {"a": 1 never closes')


def test_config_endpoint_normalises_trailing_slash() -> None:
    assert LMStudioConfig(base_url="http://x:1234/").endpoint == "http://x:1234/v1/chat/completions"


def test_complete_returns_content_and_metadata() -> None:
    client = _client("hello world")
    completion = client.complete([ChatMessage("user", "hi")])
    assert completion.content == "hello world"
    assert completion.finish_reason == "stop"
    assert completion.usage == {"total_tokens": 12}
    assert completion.duration_seconds >= 0


def test_complete_includes_seed_when_configured() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, body: bytes, timeout: float) -> str:
        captured.update(json.loads(body))
        return json.dumps(_envelope("ok"))

    client = LMStudioClient(LMStudioConfig(seed=7), transport=transport)
    client.complete([ChatMessage("user", "hi")])
    assert captured["seed"] == 7
    assert captured["stream"] is False


def test_complete_omits_seed_by_default_and_honours_override() -> None:
    captured: dict[str, object] = {}

    def transport(url: str, body: bytes, timeout: float) -> str:
        captured.clear()
        captured.update(json.loads(body))
        return json.dumps(_envelope("ok"))

    client = LMStudioClient(transport=transport)
    client.complete([ChatMessage("user", "hi")])
    assert "seed" not in captured
    client.complete([ChatMessage("user", "hi")], seed=99, temperature=0.1, max_tokens=64)
    assert captured["seed"] == 99
    assert captured["temperature"] == 0.1
    assert captured["max_tokens"] == 64


def test_complete_json_parses_data() -> None:
    client = _client('```json\n{"k": "v"}\n```')
    completion = client.complete_json([ChatMessage("user", "hi")])
    assert completion.data == {"k": "v"}


def test_malformed_envelope_raises_response_error() -> None:
    client = LMStudioClient(transport=lambda url, body, timeout: json.dumps({"nope": True}))
    with pytest.raises(LMStudioResponseError):
        client.complete([ChatMessage("user", "hi")])


def test_non_text_content_raises_response_error() -> None:
    client = LMStudioClient(
        transport=lambda url, body, timeout: json.dumps(
            {"choices": [{"message": {"content": 5}, "finish_reason": "stop"}]}
        )
    )
    with pytest.raises(LMStudioResponseError):
        client.complete([ChatMessage("user", "hi")])


def test_http_error_maps_to_response_error() -> None:
    error = urllib.error.HTTPError("http://x", 500, "boom", {}, None)  # type: ignore[arg-type]
    with pytest.raises(LMStudioResponseError):
        _raising_client(error).complete([ChatMessage("user", "hi")])


def test_url_error_maps_to_unavailable() -> None:
    with pytest.raises(LMStudioUnavailableError):
        _raising_client(urllib.error.URLError("refused")).complete([ChatMessage("user", "hi")])


def test_timeout_maps_to_unavailable() -> None:
    with pytest.raises(LMStudioUnavailableError):
        _raising_client(TimeoutError()).complete([ChatMessage("user", "hi")])


def test_default_urllib_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        def __init__(self, text: str) -> None:
            self._text = text.encode("utf-8")

        def read(self) -> bytes:
            return self._text

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(json.dumps(_envelope("live"))),
    )
    completion = LMStudioClient().complete([ChatMessage("user", "hi")])
    assert completion.content == "live"
