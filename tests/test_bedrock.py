import json
from unittest.mock import Mock, patch

import pytest
import requests

import bedrock
from errors import GatewayError

API_KEY_CREDS = {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}
SIGV4_CREDS = {
    "region": "eu-west-1",
    "access_key_id": "AKIAABCDEFGHIJKLMNOP",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}


def _mock_response(json_body):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_body
    return resp


def _converse_body(text="Paris.", usage=None):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "usage": usage or {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
    }


def test_bedrock_error_is_a_gateway_error():
    assert issubclass(bedrock.BedrockError, GatewayError)


@pytest.mark.parametrize("region,prefix", [
    ("us-east-1", "us"), ("us-west-2", "us"), ("us-gov-west-1", "us-gov"),
    ("eu-central-1", "eu"), ("ap-northeast-1", "apac"),
])
def test_resolve_model_id_fills_geo_prefix_from_region(region, prefix):
    resolved = bedrock.resolve_model_id("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", region)
    assert resolved == f"{prefix}.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_resolve_model_id_leaves_plain_ids_alone():
    assert bedrock.resolve_model_id("amazon.nova-pro-v1:0", "sa-east-1") == "amazon.nova-pro-v1:0"


def test_resolve_model_id_unknown_geography_raises():
    with pytest.raises(bedrock.BedrockError):
        bedrock.resolve_model_id("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0", "sa-east-1")


def test_converse_url_percent_encodes_colon_in_model_id():
    url = bedrock.converse_url("us.anthropic.claude-haiku-4-5-20251001-v1:0", "us-east-1")
    assert url == (
        "https://bedrock-runtime.us-east-1.amazonaws.com/model/"
        "us.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )


def test_to_converse_body_lifts_system_messages():
    body = bedrock.to_converse_body([
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
    ])
    assert body == {
        "system": [{"text": "Be terse."}],
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    }


def test_to_converse_body_omits_system_when_absent():
    body = bedrock.to_converse_body([{"role": "user", "content": "hi"}])
    assert "system" not in body


@patch("bedrock.requests.post")
def test_call_model_returns_text_latency_tokens(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    result = bedrock.call_model("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
                                [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Paris."
    assert result["tokens"] == 15
    assert result["input_tokens"] == 12
    assert result["output_tokens"] == 3
    assert result["cost_usd"] == 0.0
    assert isinstance(result["latency_ms"], int)


@patch("bedrock.requests.post")
def test_call_model_uses_bearer_header_for_api_key(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    args, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer ABSKexampleexampleexample1234"
    assert json.loads(kwargs["data"]) == {"messages": [{"role": "user", "content": [{"text": "hi"}]}]}


@patch("bedrock.requests.post")
def test_call_model_signs_with_sigv4_for_access_keys(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
                       [{"role": "user", "content": "hi"}], SIGV4_CREDS)

    args, kwargs = mock_post.call_args
    auth = kwargs["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIAABCDEFGHIJKLMNOP/")
    assert "/eu-west-1/bedrock/aws4_request" in auth
    assert "X-Amz-Date" in kwargs["headers"]
    assert "X-Amz-Security-Token" not in kwargs["headers"]
    assert args[0] == (
        "https://bedrock-runtime.eu-west-1.amazonaws.com/model/"
        "eu.anthropic.claude-haiku-4-5-20251001-v1%3A0/converse"
    )
    assert isinstance(kwargs["data"], bytes)


@patch("bedrock.requests.post")
def test_call_model_includes_session_token_header_when_given(mock_post):
    mock_post.return_value = _mock_response(_converse_body())

    bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}],
                       {**SIGV4_CREDS, "session_token": "FwoGZXIvYXdzEXANPLETOKEN"})

    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-Amz-Security-Token"] == "FwoGZXIvYXdzEXANPLETOKEN"


@patch("bedrock.requests.post")
def test_call_model_skips_reasoning_blocks_to_first_text(mock_post):
    body = _converse_body()
    body["output"]["message"]["content"] = [
        {"reasoningContent": {"reasoningText": {"text": "thinking..."}}},
        {"text": "Final answer."},
    ]
    mock_post.return_value = _mock_response(body)

    result = bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)

    assert result["text"] == "Final answer."


@patch("bedrock.requests.post")
def test_call_model_raises_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("bedrock.requests.post")
def test_call_model_raises_on_malformed_json(mock_post):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.side_effect = ValueError("Expecting value")
    mock_post.return_value = resp

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)


@patch("bedrock.requests.post")
def test_call_model_raises_on_unexpected_shape(mock_post):
    mock_post.return_value = _mock_response({"output": {"message": {"content": [{"image": {}}]}}})

    with pytest.raises(bedrock.BedrockError):
        bedrock.call_model("amazon.nova-pro-v1:0", [{"role": "user", "content": "hi"}], API_KEY_CREDS)
