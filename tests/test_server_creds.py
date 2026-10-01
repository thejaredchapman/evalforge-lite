import json

import gateway
import server_creds

SA_JSON = json.dumps({"type": "service_account", "project_id": "p", "private_key": "KEYDATA"})


def test_nothing_set_means_nothing_held():
    assert server_creds.load() == {}
    assert server_creds.held_backends() == []
    assert server_creds.public_summary() == {}


def test_order_matches_gateway_backends():
    assert server_creds.ORDER == gateway.BACKENDS


def test_openrouter_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-v1-abc\n")
    assert server_creds.load() == {"openrouter": "sk-or-v1-abc"}


def test_whitespace_only_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    assert server_creds.load() == {}


def test_bedrock_api_key_style(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    assert server_creds.load()["bedrock"] == {"region": "us-east-1", "api_key": "ABSKexample"}


def test_bedrock_access_key_style_with_optional_session_token(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secretvalue")
    assert server_creds.load()["bedrock"] == {
        "region": "us-west-2", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secretvalue",
    }
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok")
    assert server_creds.load()["bedrock"]["session_token"] == "tok"


def test_bedrock_api_key_wins_over_access_keys(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secretvalue")
    assert server_creds.load()["bedrock"] == {"region": "us-east-1", "api_key": "ABSKexample"}


def test_bedrock_without_region_or_without_secret_is_not_held(monkeypatch):
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    assert "bedrock" not in server_creds.load()
    monkeypatch.delenv("BEDROCK_API_KEY")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")  # secret missing
    assert "bedrock" not in server_creds.load()


def test_vertex_service_account(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", SA_JSON)
    assert server_creds.load()["vertex"] == {
        "project": "my-proj", "region": "us-central1", "service_account_json": SA_JSON,
    }
    monkeypatch.setenv("VERTEX_REGION", "us-east5")
    assert server_creds.load()["vertex"]["region"] == "us-east5"


def test_vertex_invalid_or_non_object_json_is_not_held(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", "not json")
    assert "vertex" not in server_creds.load()
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", "[1, 2]")
    assert "vertex" not in server_creds.load()


def test_foundry_needs_resource_region_and_key(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    assert "foundry" not in server_creds.load()
    monkeypatch.setenv("FOUNDRY_API_KEY", "fkey")
    assert server_creds.load()["foundry"] == {"resource": "res", "region": "eastus2", "api_key": "fkey"}


def test_held_backends_follow_order(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "fkey")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abc")
    assert server_creds.held_backends() == ["openrouter", "foundry"]


def test_public_summary_has_only_names_and_regions(monkeypatch):
    secrets = {
        "OPENROUTER_API_KEY": "sk-or-v1-TOPSECRET",
        "BEDROCK_REGION": "us-east-1", "BEDROCK_API_KEY": "ABSK-TOPSECRET",
        "VERTEX_PROJECT": "secret-project-id", "VERTEX_SERVICE_ACCOUNT_JSON": SA_JSON, "VERTEX_REGION": "us-east5",
        "FOUNDRY_RESOURCE": "secret-resource", "FOUNDRY_REGION": "eastus2", "FOUNDRY_API_KEY": "FKEY-TOPSECRET",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    summary = server_creds.public_summary()
    assert summary == {
        "openrouter": {},
        "bedrock": {"region": "us-east-1"},
        "vertex": {"region": "us-east5"},
        "foundry": {"region": "eastus2"},
    }
    text = json.dumps(summary)
    for needle in ("TOPSECRET", "secret-project-id", "secret-resource", "KEYDATA"):
        assert needle not in text
