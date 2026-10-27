import asyncio
import base64
import json

import httpx
import pytest

from bookguild.llm import OpenRouterClient
from bookguild.reliability import PermanentError, TransientError


def client_returning(handler) -> OpenRouterClient:
    return OpenRouterClient("sk-test", transport=httpx.MockTransport(handler))


def completion(content="Hello", cost=0.0012, images=None):
    message = {"role": "assistant", "content": content}
    if images:
        message["images"] = images
    return {
        "model": "qwen/qwen3.7-flash",
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": cost},
    }


def run(coro):
    return asyncio.run(coro)


def test_chat_parses_text_tokens_and_cost():
    sent = {}

    def handler(request: httpx.Request):
        sent["auth"] = request.headers["authorization"]
        sent["body"] = request.read()
        return httpx.Response(200, json=completion())

    result = run(client_returning(handler).chat("qwen/qwen3.7-flash", [{"role": "user", "content": "hi"}]))
    assert result.text == "Hello"
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (10, 5, 0.0012)
    assert sent["auth"] == "Bearer sk-test"
    assert b'"usage": {"include": true}' in sent["body"] or b'"usage":{"include":true}' in sent["body"]


@pytest.mark.parametrize("status, error_type, use_fallback", [
    (401, PermanentError, False),
    (402, PermanentError, False),
    (404, PermanentError, True),
    (429, TransientError, True),
    (503, TransientError, True),
])
def test_http_errors_are_classified(status, error_type, use_fallback):
    client = client_returning(lambda r: httpx.Response(status, json={"error": {"message": "nope", "code": status}}))
    with pytest.raises(error_type) as caught:
        run(client.chat("m/x", []))
    assert type(caught.value) is error_type
    assert caught.value.use_fallback is use_fallback
    assert caught.value.status == status


def test_error_inside_200_body_is_detected():
    client = client_returning(lambda r: httpx.Response(200, json={"error": {"message": "overloaded", "code": 502}}))
    with pytest.raises(TransientError):
        run(client.chat("m/x", []))


def test_timeout_and_empty_reply_are_transient():
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(TransientError):
        run(client_returning(timeout).chat("m/x", []))
    with pytest.raises(TransientError):
        run(client_returning(lambda r: httpx.Response(200, json=completion(content=""))).chat("m/x", []))


def test_missing_key_fails_without_any_request():
    calls = []
    client = OpenRouterClient(None, transport=httpx.MockTransport(lambda r: calls.append(r)))
    with pytest.raises(PermanentError):
        run(client.chat("m/x", []))
    assert calls == []


def test_image_is_decoded():
    png = b"\x89PNG fake"
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    body = completion(content="", images=[{"type": "image_url", "image_url": {"url": url}}])
    result = run(client_returning(lambda r: httpx.Response(200, json=body)).generate_image("g/img", "a cat"))
    assert result.images == [png]


def test_list_models_reads_prices_per_million():
    body = {"data": [
        {"id": "b/model", "name": "B", "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
         "context_length": 1000, "architecture": {"output_modalities": ["text"]}},
        {"id": "a/img", "name": "A", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["image", "text"]}},
        {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
    ]}
    models = run(client_returning(lambda r: httpx.Response(200, json=body)).list_models())
    assert [m.id for m in models] == ["a/img", "b/model"]
    assert models[1].input_per_m == pytest.approx(0.1)
    assert models[0].makes_images and not models[1].makes_images


def test_thinking_setting_is_sent():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.read()))
        return httpx.Response(200, json=completion())

    client = client_returning(handler)
    run(client.chat("m/x", [], thinking="off"))
    run(client.chat("m/x", [], thinking="low"))
    run(client.chat("m/x", []))
    assert bodies[0]["reasoning"] == {"enabled": False}
    assert bodies[1]["reasoning"] == {"effort": "low"}
    assert "reasoning" not in bodies[2]


def test_cut_off_reply_explains_itself_and_keeps_the_cost():
    body = completion(content="")
    body["choices"][0]["finish_reason"] = "length"
    with pytest.raises(TransientError, match="cut off at its 4000-token limit") as caught:
        run(client_returning(lambda r: httpx.Response(200, json=body)).chat("m/x", [], max_tokens=4000))
    assert caught.value.result.cost_usd == 0.0012
