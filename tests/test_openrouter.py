from unittest.mock import Mock, patch

import pytest

import openrouter


def _mock_response(json_body, status_ok=True):
    resp = Mock()
    resp.json.return_value = json_body
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = Exception("HTTP error")
    return resp


@patch("openrouter.requests.post")
def test_call_model_returns_text_latency_cost_tokens(mock_post):
    mock_post.return_value = _mock_response({
        "choices": [{"message": {"content": "Paris is the capital of France."}}],
        "usage": {"total_tokens": 42, "cost": 0.0012},
    })

    result = openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")

    assert result["text"] == "Paris is the capital of France."
    assert result["tokens"] == 42
    assert result["cost_usd"] == 0.0012
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0


@patch("openrouter.requests.post")
def test_call_model_sends_bearer_auth_header_with_caller_key(mock_post):
    mock_post.return_value = _mock_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 1, "cost": 0.0},
    })

    openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-secret")

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-v1-secret"


@patch("openrouter.requests.post")
def test_call_model_raises_openrouter_error_on_request_exception(mock_post):
    import requests
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(openrouter.OpenRouterError):
        openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")


@patch("openrouter.requests.post")
def test_call_model_raises_openrouter_error_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"unexpected": "shape"})

    with pytest.raises(openrouter.OpenRouterError):
        openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")


@patch("openrouter.requests.post")
def test_call_model_defaults_missing_cost_to_zero(mock_post):
    mock_post.return_value = _mock_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 5},
    })

    result = openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")

    assert result["cost_usd"] == 0.0


@patch("openrouter.requests.post")
def test_call_model_raises_openrouter_error_on_malformed_json(mock_post):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("Expecting value")

    mock_post.return_value = resp

    with pytest.raises(openrouter.OpenRouterError):
        openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")
