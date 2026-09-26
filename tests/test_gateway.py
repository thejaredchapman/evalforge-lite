import json
from unittest.mock import patch

import pytest

import gateway
from errors import GatewayError

MESSAGES = [{"role": "user", "content": "hi"}]
FAKE_RESULT = {"text": "ok", "latency_ms": 5, "cost_usd": 0.0, "tokens": 30,
               "input_tokens": 10, "output_tokens": 20}


@pytest.mark.parametrize("target,expected", [
    ("anthropic/claude-sonnet-4.5", ("anthropic/claude-sonnet-4.5", "openrouter")),
    ("anthropic/claude-sonnet-4.5@bedrock", ("anthropic/claude-sonnet-4.5", "bedrock")),
    ("google/gemini-3-pro@vertex", ("google/gemini-3-pro", "vertex")),
    ("google/gemini-3-pro@openrouter", ("google/gemini-3-pro", "openrouter")),
    ("some/model@unknown", ("some/model@unknown", "openrouter")),
])
def test_parse_target(target, expected):
    assert gateway.parse_target(target) == expected


@pytest.mark.parametrize("bad", ["", None, 42])
def test_parse_target_rejects_empty_or_non_string(bad):
    with pytest.raises(GatewayError):
        gateway.parse_target(bad)


def test_prepare_creds_passes_openrouter_key_and_bedrock_api_key():
    prepared = gateway.prepare_creds({
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "us-east-1", "api_key": "ABSKexample", "junk": "dropped"},
    })
    assert prepared == {
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "us-east-1", "api_key": "ABSKexample"},
    }


def test_prepare_creds_keeps_bedrock_access_keys_and_session_token():
    prepared = gateway.prepare_creds({"bedrock": {
        "region": "eu-west-1", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret",
        "session_token": "tok",
    }})
    assert prepared["bedrock"] == {
        "region": "eu-west-1", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret",
        "session_token": "tok",
    }


@pytest.mark.parametrize("region", ["x.evil.com#", "us-east-1.evil.com", "US-EAST-1", "", None])
def test_prepare_creds_rejects_bad_bedrock_region(region):
    prepared = gateway.prepare_creds({"bedrock": {"region": region, "api_key": "ABSKexample"}})
    assert prepared["bedrock"] == {"error": "Bedrock region is missing or invalid."}


def test_prepare_creds_bedrock_without_any_auth_is_an_error():
    prepared = gateway.prepare_creds({"bedrock": {"region": "us-east-1"}})
    assert "error" in prepared["bedrock"]


@pytest.mark.parametrize("bad_value", ["ABSKexample\n", " ABSKexample", "ABSK\texample"])
def test_prepare_creds_rejects_bedrock_api_key_with_whitespace_or_control_chars(bad_value):
    prepared = gateway.prepare_creds({"bedrock": {"region": "us-east-1", "api_key": bad_value}})
    assert prepared["bedrock"] == {"error": "Bedrock credentials contain whitespace or control characters."}


@pytest.mark.parametrize("field,bad_value", [
    ("access_key_id", "AKIAEXAMPLE\n"),
    ("secret_access_key", " secret"),
    ("session_token", "tok\twith\ttabs"),
])
def test_prepare_creds_rejects_bedrock_access_key_fields_with_whitespace_or_control_chars(field, bad_value):
    raw = {"region": "us-east-1", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secret"}
    raw[field] = bad_value
    prepared = gateway.prepare_creds({"bedrock": raw})
    assert prepared["bedrock"] == {"error": "Bedrock credentials contain whitespace or control characters."}


@pytest.mark.parametrize("project,region", [
    ("evil.com#", "us-central1"),
    ("my-project-123", "x.evil.com#"),
    ("my-project-123", "us-central1/../../x"),
])
def test_prepare_creds_rejects_bad_vertex_project_or_region(project, region):
    prepared = gateway.prepare_creds({"vertex": {"project": project, "region": region, "access_token": "ya29.x"}})
    assert "error" in prepared["vertex"]


def test_prepare_creds_accepts_vertex_global_region_with_access_token():
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "global",
                                                 "access_token": "ya29.x"}})
    assert prepared["vertex"] == {"project": "my-project-123", "region": "global", "access_token": "ya29.x"}


@pytest.mark.parametrize("bad_value", ["ya29.x\n", " ya29.x", "ya29.\tx"])
def test_prepare_creds_rejects_vertex_access_token_with_whitespace_or_control_chars(bad_value):
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "access_token": bad_value}})
    assert prepared["vertex"] == {"error": "Vertex credentials contain whitespace or control characters."}


@patch("gateway.vertex.mint_token", return_value="ya29.minted")
def test_prepare_creds_mints_vertex_token_from_service_account(mock_mint):
    sa = {"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": json.dumps(sa)}})
    assert prepared["vertex"] == {"project": "my-project-123", "region": "us-central1",
                                  "access_token": "ya29.minted"}
    mock_mint.assert_called_once_with(sa)


@pytest.mark.parametrize("raw", ["not json", json.dumps({"type": "authorized_user"}), json.dumps([1])])
def test_prepare_creds_rejects_bad_service_account_json(raw):
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": raw}})
    assert "error" in prepared["vertex"]


@patch("gateway.vertex.mint_token")
def test_prepare_creds_records_mint_failure_as_error(mock_mint):
    import vertex
    mock_mint.side_effect = vertex.VertexError("Could not obtain a Vertex access token from the service account.")
    prepared = gateway.prepare_creds({"vertex": {"project": "my-project-123", "region": "us-central1",
                                                 "service_account_json": json.dumps({"type": "service_account"})}})
    assert prepared["vertex"] == {"error": "Could not obtain a Vertex access token from the service account."}


@patch("gateway.vertex.mint_token", return_value="ya29.minted")
def test_prepare_creds_is_idempotent(mock_mint):
    raw = {
        "openrouter": "sk-or-v1-test",
        "bedrock": {"region": "nowhere"},
        "vertex": {"project": "my-project-123", "region": "us-central1",
                   "service_account_json": json.dumps({"type": "service_account"})},
    }
    once = gateway.prepare_creds(raw)
    twice = gateway.prepare_creds(once)
    assert twice == once
    assert mock_mint.call_count == 1


def test_prepare_creds_tolerates_non_dict():
    assert gateway.prepare_creds(None) == {}


@pytest.mark.parametrize("bad_value", ["sk-or-v1-test\n", " sk-or-v1-test", "sk-or-v1-\ttest"])
def test_prepare_creds_rejects_openrouter_key_with_whitespace_or_control_chars(bad_value):
    prepared = gateway.prepare_creds({"openrouter": bad_value})
    assert prepared["openrouter"] == {"error": "OpenRouter credentials contain whitespace or control characters."}


@patch("gateway.openrouter.call_model", return_value=FAKE_RESULT)
def test_call_backend_openrouter_passes_key(mock_call):
    gateway.call_backend("openrouter", "openai/gpt-5", MESSAGES, {"openrouter": "sk-or-v1-test"})
    args, kwargs = mock_call.call_args
    assert args[0] == "openai/gpt-5"
    assert kwargs["api_key"] == "sk-or-v1-test"


@patch("gateway.bedrock.call_model", return_value=FAKE_RESULT)
def test_call_backend_bedrock_passes_backend_creds(mock_call):
    bedrock_creds = {"region": "us-east-1", "api_key": "ABSKexample"}
    gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES, {"bedrock": bedrock_creds})
    args, _ = mock_call.call_args
    assert args == ("amazon.nova-pro-v1:0", MESSAGES, bedrock_creds)


@patch("gateway.vertex.call_model", return_value=FAKE_RESULT)
def test_call_backend_vertex_passes_backend_creds(mock_call):
    vertex_creds = {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.x"}
    gateway.call_backend("vertex", "google/gemini-2.5-flash", MESSAGES, {"vertex": vertex_creds})
    args, _ = mock_call.call_args
    assert args == ("google/gemini-2.5-flash", MESSAGES, vertex_creds)


def test_call_backend_missing_creds_raises_named_error():
    with pytest.raises(GatewayError, match="No Bedrock credentials supplied."):
        gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES, {"openrouter": "sk-or-v1-test"})


def test_call_backend_surfaces_prepare_error():
    with pytest.raises(GatewayError, match="Bedrock region is missing or invalid."):
        gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES,
                             {"bedrock": {"error": "Bedrock region is missing or invalid."}})


def test_call_backend_unknown_backend_raises():
    with pytest.raises(GatewayError):
        gateway.call_backend("azure", "x", MESSAGES, {"azure": "k"})


@patch("gateway.bedrock.call_model", return_value=FAKE_RESULT)
def test_call_backend_validates_raw_creds_before_dispatch(mock_call):
    with pytest.raises(GatewayError, match="Bedrock region is missing or invalid."):
        gateway.call_backend("bedrock", "amazon.nova-pro-v1:0", MESSAGES,
                             {"bedrock": {"region": "x.evil.com#", "api_key": "ABSKexample"}})
    mock_call.assert_not_called()


@pytest.mark.parametrize("backend,raw", [
    ("bedrock", {"api_key": "ABSKexample"}),
    ("bedrock", {"region": "us-east-1"}),
    ("vertex", {"access_token": "ya29.x"}),
    ("vertex", {"project": "my-project-123", "access_token": "ya29.x"}),
])
def test_call_backend_incomplete_creds_raise_gateway_error(backend, raw):
    with pytest.raises(GatewayError):
        gateway.call_backend(backend, "some-model", MESSAGES, {backend: raw})


@patch("gateway.vertex.mint_token")
@patch("gateway.vertex.call_model", return_value=FAKE_RESULT)
def test_call_backend_does_not_remint_prepared_vertex_creds(mock_call, mock_mint):
    prepared = {"vertex": {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.x"}}
    gateway.call_backend("vertex", "google/gemini-2.5-flash", MESSAGES, prepared)
    mock_mint.assert_not_called()
    assert mock_call.call_args[0][2] == prepared["vertex"]


def test_estimate_cost():
    assert gateway.estimate_cost({"input_per_m": 3.0, "output_per_m": 15.0}, 1_000_000, 100_000) == 4.5
    assert gateway.estimate_cost(None, 1000, 1000) == 0.0


@patch("gateway.openrouter.call_model", return_value=dict(FAKE_RESULT, cost_usd=0.0042))
def test_call_target_openrouter_keeps_reported_cost(mock_call):
    result = gateway.call_target("openai/gpt-5", MESSAGES, {"openrouter": "sk-or-v1-test"})
    assert result["cost_usd"] == 0.0042
    assert mock_call.call_args[0][0] == "openai/gpt-5"


@patch("gateway.bedrock.call_model", return_value=dict(FAKE_RESULT))
def test_call_target_bedrock_resolves_route_and_prices_it(mock_call):
    result = gateway.call_target("anthropic/claude-sonnet-4.5@bedrock", MESSAGES,
                                 {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}})
    assert mock_call.call_args[0][0] == "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0"
    # 10 input tokens * $3/M + 20 output tokens * $15/M
    assert result["cost_usd"] == pytest.approx(0.00033)


def test_call_target_model_without_route_raises():
    with pytest.raises(GatewayError, match="openai/gpt-5 is not available on Bedrock."):
        gateway.call_target("openai/gpt-5@bedrock", MESSAGES,
                            {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}})


def test_normalize_creds_keeps_creds_unchanged_when_openrouter_already_present():
    creds = {"openrouter": "sk-or-v1-existing", "bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}}
    assert gateway.normalize_creds(creds, "sk-or-v1-x") is creds


def test_normalize_creds_merges_legacy_api_key_when_creds_lacks_openrouter():
    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}}
    result = gateway.normalize_creds(creds, "sk-or-v1-x")
    assert result == {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}, "openrouter": "sk-or-v1-x"}
    assert result is not creds


def test_normalize_creds_turns_legacy_api_key_into_openrouter_creds():
    assert gateway.normalize_creds(None, "sk-or-v1-x") == {"openrouter": "sk-or-v1-x"}


@pytest.mark.parametrize("creds,api_key", [(None, None), ({}, ""), ("sk-or-v1-x", None), (None, 42)])
def test_normalize_creds_returns_none_when_unusable(creds, api_key):
    assert gateway.normalize_creds(creds, api_key) is None
