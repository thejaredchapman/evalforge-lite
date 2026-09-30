from unittest.mock import Mock, patch

import pytest
import requests

import foundry
from errors import GatewayError

API_KEY_CREDS = {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}
TOKEN_CREDS = {"resource": "my-resource", "region": "eastus",
              "access_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123signature"}


def _mock_response(json_body):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def _chat_body(text="Paris."):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
    }


def test_foundry_error_is_a_gateway_error():
    assert issubclass(foundry.FoundryError, GatewayError)


def test_endpoint_url_uses_resource_subdomain():
    assert foundry.endpoint_url("my-resource") == (
        "https://my-resource.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    )


@patch("foundry.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    result = foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 11
    assert result["input_tokens"] == 9
    assert result["output_tokens"] == 2
    assert result["cost_usd"] == 0.0


@patch("foundry.requests.post")
def test_call_model_sends_api_key_header_when_api_key_present(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    args, kwargs = mock_post.call_args
    assert args[0] == foundry.endpoint_url("my-resource")
    assert kwargs["headers"]["api-key"] == "fake-api-key-12345678"
    assert "Authorization" not in kwargs["headers"]
    assert kwargs["json"] == {"model": "openai/gpt-5", "messages": [{"role": "user", "content": "hi"}]}


@patch("foundry.requests.post")
def test_call_model_sends_bearer_token_when_access_token_present(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], TOKEN_CREDS)

    args, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN_CREDS['access_token']}"
    assert "api-key" not in kwargs["headers"]


def test_call_model_without_any_auth_raises():
    with pytest.raises(foundry.FoundryError, match="Foundry credentials were not prepared."):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}],
                           {"resource": "my-resource", "region": "eastus"})


@patch("foundry.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("foundry.requests.post")
def test_call_model_raises_on_malformed_json(mock_post):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("bad json")
    mock_post.return_value = resp

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("foundry.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"unexpected": "shape"})

    with pytest.raises(foundry.FoundryError):
        foundry.call_model("openai/gpt-5", [{"role": "user", "content": "hi"}], API_KEY_CREDS)
