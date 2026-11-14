import json

import httpx
import pytest

from outage_matcher.evals import deepseek
from outage_matcher.evals.deepseek import DeepSeekClient, DeepSeekError


def completion(content, prompt_tokens=11, completion_tokens=7):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def make_client(handler, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return DeepSeekClient("k-test", http=http, sleep=lambda _s: None, **kwargs)


def test_chat_json_sends_json_mode_request_and_parses_reply():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('{"ok": true}'))

    result = make_client(handler).chat_json([{"role": "user", "content": "hi"}], temperature=0.0)
    assert result.data == {"ok": True}
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.calls) == (11, 7, 1)
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert seen["auth"] == "Bearer k-test"
    body = seen["body"]
    assert body["model"] == "deepseek-chat"
    assert body["temperature"] == 0.0
    assert body["response_format"] == {"type": "json_object"}


def test_retries_transient_failures_then_succeeds():
    replies = [httpx.Response(503), httpx.Response(429), httpx.Response(200, json=completion("{}"))]
    calls = []

    def handler(request):
        calls.append(1)
        return replies[len(calls) - 1]

    assert make_client(handler).chat_json([]).data == {}
    assert len(calls) == 3


def test_gives_up_after_max_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    with pytest.raises(DeepSeekError, match="gave up"):
        make_client(handler, max_retries=2).chat_json([])
    assert len(calls) == 3


def test_client_error_is_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, text="bad key")

    with pytest.raises(DeepSeekError, match="HTTP 401"):
        make_client(handler).chat_json([])
    assert len(calls) == 1


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_reply_that_is_not_a_json_object_is_an_error(content):
    client = make_client(lambda request: httpx.Response(200, json=completion(content)))
    with pytest.raises(DeepSeekError):
        client.chat_json([])


def test_unexpected_response_shape_is_an_error():
    client = make_client(lambda request: httpx.Response(200, json={"choices": []}))
    with pytest.raises(DeepSeekError, match="shape"):
        client.chat_json([])


def test_usage_adds_up():
    a = deepseek.TokenUsage(10, 5, 1)
    assert a.plus(deepseek.TokenUsage(1, 2, 1)) == deepseek.TokenUsage(11, 7, 2)


@pytest.mark.parametrize(
    "value, expected",
    [(None, None), ("", None), ("your-key-here", None), ("  sk-real  ", "sk-real")],
)
def test_api_key_ignores_missing_and_placeholder(monkeypatch, value, expected):
    monkeypatch.setattr(deepseek, "load_dotenv", lambda: False)
    if value is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", value)
    assert deepseek.api_key() == expected
