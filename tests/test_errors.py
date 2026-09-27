from unittest.mock import Mock, patch

import pytest
import requests

import bedrock
import openrouter
import vertex
from errors import MAX_BODY_CHARS, describe_request_error


def _http_error(body, status=403, reason="Forbidden"):
    resp = Mock()
    resp.text = body
    return requests.HTTPError(f"{status} Client Error: {reason} for url: https://example.test/x", response=resp)


def test_describe_request_error_appends_response_body():
    e = _http_error('{"message":"You don\'t have access to the model with the specified model ID."}')
    message = describe_request_error(e)
    assert message.startswith("403 Client Error: Forbidden")
    assert "Response body: {\"message\":\"You don't have access to the model" in message


def test_describe_request_error_without_response_is_plain_str():
    assert describe_request_error(requests.ConnectionError("connection refused")) == "connection refused"


def test_describe_request_error_ignores_empty_body():
    assert describe_request_error(_http_error("   ")).endswith("for url: https://example.test/x")


def test_describe_request_error_truncates_long_bodies():
    message = describe_request_error(_http_error("x" * (MAX_BODY_CHARS + 500)))
    assert f"[truncated, {MAX_BODY_CHARS + 500} characters total]" in message
    assert "x" * (MAX_BODY_CHARS + 1) not in message


def _failing_post(body):
    resp = Mock()
    resp.text = body
    resp.raise_for_status.side_effect = requests.HTTPError("403 Client Error: Forbidden", response=resp)
    return resp


@pytest.mark.parametrize("module,error_cls,call", [
    (bedrock, bedrock.BedrockError, lambda: bedrock.call_model(
        "amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}],
        {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"})),
    (vertex, vertex.VertexError, lambda: vertex.call_model(
        "google/gemini-2.5-flash", [{"role": "user", "content": "hi"}],
        {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.example-token"})),
    (openrouter, openrouter.OpenRouterError, lambda: openrouter.call_model(
        "openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-example")),
])
def test_providers_surface_response_body(module, error_cls, call):
    with patch.object(module.requests, "post", return_value=_failing_post('{"error":"model not enabled"}')):
        with pytest.raises(error_cls) as info:
            call()
    assert 'Response body: {"error":"model not enabled"}' in str(info.value)


def test_echoed_secrets_in_response_body_are_scrubbed():
    import scrub

    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}}
    e = _http_error('{"message":"Invalid key ABSKexampleexampleexample1234"}')
    shown = scrub.scrub(describe_request_error(e), creds)
    assert "ABSKexampleexampleexample1234" not in shown
    assert "[REDACTED]" in shown
