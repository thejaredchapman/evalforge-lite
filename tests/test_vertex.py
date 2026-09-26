from unittest.mock import Mock, patch

import pytest
import requests

import vertex
from errors import GatewayError

CREDS = {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.example-token"}


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


def test_vertex_error_is_a_gateway_error():
    assert issubclass(vertex.VertexError, GatewayError)


def test_endpoint_url_uses_regional_host():
    assert vertex.endpoint_url("my-project-123", "us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/my-project-123"
        "/locations/us-central1/endpoints/openapi/chat/completions"
    )


def test_endpoint_url_uses_unprefixed_host_for_global():
    assert vertex.endpoint_url("my-project-123", "global") == (
        "https://aiplatform.googleapis.com/v1/projects/my-project-123"
        "/locations/global/endpoints/openapi/chat/completions"
    )


@patch("vertex.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    result = vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 11
    assert result["input_tokens"] == 9
    assert result["output_tokens"] == 2
    assert result["cost_usd"] == 0.0


@patch("vertex.requests.post")
def test_call_model_sends_bearer_token_and_model(mock_post):
    mock_post.return_value = _mock_response(_chat_body())

    vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)

    args, kwargs = mock_post.call_args
    assert args[0] == vertex.endpoint_url("my-project-123", "us-central1")
    assert kwargs["headers"]["Authorization"] == "Bearer ya29.example-token"
    assert kwargs["json"] == {"model": "google/gemini-2.5-flash", "messages": [{"role": "user", "content": "hi"}]}


def test_call_model_without_access_token_raises():
    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}],
                          {"project": "my-project-123", "region": "us-central1"})


@patch("vertex.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)


@patch("vertex.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"unexpected": "shape"})

    with pytest.raises(vertex.VertexError):
        vertex.call_model("google/gemini-2.5-flash", [{"role": "user", "content": "hi"}], CREDS)


@patch("vertex.service_account.Credentials.from_service_account_info")
def test_mint_token_overrides_caller_token_uri(mock_from_info):
    sa_creds = Mock()
    sa_creds.token = "ya29.minted"
    mock_from_info.return_value = sa_creds

    token = vertex.mint_token({"type": "service_account", "token_uri": "https://evil.example/steal"})

    info_passed = mock_from_info.call_args[0][0]
    assert info_passed["token_uri"] == "https://oauth2.googleapis.com/token"
    assert mock_from_info.call_args[1]["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    sa_creds.refresh.assert_called_once()
    assert token == "ya29.minted"


@patch("vertex.service_account.Credentials.from_service_account_info")
def test_mint_token_wraps_auth_failures_without_leaking_detail(mock_from_info):
    mock_from_info.side_effect = ValueError("bad private key -----BEGIN PRIVATE KEY-----abc")

    with pytest.raises(vertex.VertexError) as exc_info:
        vertex.mint_token({"type": "service_account"})

    assert "PRIVATE KEY" not in str(exc_info.value)
