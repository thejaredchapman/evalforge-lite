import io
import json
import re
from unittest.mock import patch

import pytest

import app as app_module
import gateway
import judge
import limiter


def _client():
    app_module.app.testing = True
    return app_module.app.test_client()


def setup_function():
    app_module._policy_store.clear()
    app_module._run_history_store.clear()
    limiter._attempts.clear()


def test_index_returns_200():
    resp = _client().get("/")
    assert resp.status_code == 200


def test_index_sets_session_cookie():
    resp = _client().get("/")
    assert "evalforge_session" in resp.headers.get("Set-Cookie", "")


def test_api_catalog_returns_providers_and_frontier():
    resp = _client().get("/api/catalog")
    body = resp.get_json()
    assert "providers" in body
    assert "frontier" in body
    assert len(body["frontier"]) > 0


@patch("app.catalog.fetch_openrouter_models")
def test_api_openrouter_models_returns_fetched_list(mock_fetch):
    mock_fetch.return_value = [{"id": "mistralai/mistral-large", "name": "Mistral Large"}]
    resp = _client().get("/api/openrouter-models")
    assert resp.get_json() == {"models": [{"id": "mistralai/mistral-large", "name": "Mistral Large"}]}


@patch("app.catalog.fetch_openrouter_models")
def test_api_openrouter_models_returns_empty_list_on_fetch_failure(mock_fetch):
    mock_fetch.return_value = []
    resp = _client().get("/api/openrouter-models")
    assert resp.get_json() == {"models": []}


@patch("app.judge.evaluate_prompt")
def test_api_evaluate_prompt_returns_score_and_feedback(mock_evaluate):
    mock_evaluate.return_value = {"score": 2, "feedback": "Too vague."}
    resp = _client().post("/api/evaluate-prompt", json={"prompt": "Tell me stuff", "api_key": "sk-or-v1-test"})
    assert resp.get_json() == {"score": 2, "feedback": "Too vague."}
    mock_evaluate.assert_called_once_with(
        "Tell me stuff", creds={"openrouter": "sk-or-v1-test"}, backend="openrouter"
    )


def test_api_evaluate_prompt_missing_prompt_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={"api_key": "sk-or-v1-test"})
    assert resp.status_code == 400


def test_api_evaluate_prompt_missing_api_key_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={"prompt": "hello"})
    assert resp.status_code == 400


@patch("app.judge.evaluate_prompt")
def test_api_evaluate_prompt_blocks_after_three_calls_in_window(mock_evaluate):
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}
    client = _client()
    payload = {"prompt": "hello", "api_key": "sk-or-v1-test"}

    for _ in range(3):
        resp = client.post("/api/evaluate-prompt", json=payload)
        assert resp.status_code == 200

    fourth = client.post("/api/evaluate-prompt", json=payload)
    assert fourth.status_code == 429


@patch("app.judge.evaluate_prompt")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_evaluate_prompt_rate_limit_is_independent_from_run_rate_limit(mock_verdict, mock_run, mock_evaluate):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}
    client = _client()

    # Use up all 3 run-limiter calls
    for _ in range(3):
        resp = client.post("/api/run", json={"test_cases": [], "models": [], "api_key": "sk-or-v1-test"})
        assert resp.status_code == 200

    # evaluate-prompt should still work — it's a separate rate-limit bucket
    resp = client.post("/api/evaluate-prompt", json={"prompt": "hello", "api_key": "sk-or-v1-test"})
    assert resp.status_code == 200


def test_api_policy_upload_stores_text_for_session():
    client = _client()
    resp = client.post(
        "/api/policy",
        data={"file": (io.BytesIO(b"No medical advice."), "policy.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    session_id = re.search(r"evalforge_session=([^;]+)", resp.headers["Set-Cookie"]).group(1)
    assert app_module._policy_store[session_id] == "No medical advice."


def test_api_run_missing_api_key_returns_400():
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 400
    assert "api_key" in resp.get_json()["error"]


def test_api_run_missing_test_cases_returns_400():
    resp = _client().post("/api/run", json={"api_key": "sk-or-v1-test", "models": ["openai/gpt-5"]})
    assert resp.status_code == 400


def test_api_run_missing_models_returns_400():
    resp = _client().post("/api/run", json={"api_key": "sk-or-v1-test", "test_cases": []})
    assert resp.status_code == 400


def test_api_run_non_json_body_returns_400():
    resp = _client().post("/api/run", data="not json", content_type="text/plain")
    assert resp.status_code == 400


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_returns_results_grades_and_verdict(mock_verdict, mock_run, mock_explain):
    mock_run.return_value = [{
        "test_case": {"prompt": "q1"},
        "cells": {
            "openai/gpt-5": {
                "model_id": "openai/gpt-5", "blocked": False, "error": None,
                "response_text": "answer", "latency_ms": 10, "cost_usd": 0.01, "tokens": 5,
                "checks": [], "judge_score": 5, "judge_rationale": "great",
            }
        },
    }]
    mock_verdict.return_value = {"winner": "openai/gpt-5", "rationale": "best"}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1", "rubric": "be accurate"}],
        "models": ["openai/gpt-5"],
        "api_key": "sk-or-v1-test",
    })

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["verdict"]["winner"] == "openai/gpt-5"
    assert body["grades"]["openai/gpt-5"]["letter"] == "A+"
    assert "run_id" in body
    assert "created_at" in body
    assert body["stats"]["openai/gpt-5"]["total_cost_usd"] == 0.01
    assert body["stats"]["openai/gpt-5"]["avg_latency_ms"] == 10.0
    assert body["grades"]["openai/gpt-5"]["categories"]["accuracy"] == 100.0
    assert body["results"][0]["best_model"]["model_id"] == "openai/gpt-5"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_blocks_after_three_calls_in_window(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test"}

    for _ in range(3):
        resp = client.post("/api/run", json=payload)
        assert resp.status_code == 200

    fourth = client.post("/api/run", json=payload)
    assert fourth.status_code == 429


def test_api_run_error_response_scrubs_api_key():
    with patch("app.runner.run", side_effect=Exception("failed using key sk-or-v1-abcdefgh12345678")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-abcdefgh12345678",
        })

    assert resp.status_code == 503
    body = resp.get_json()
    assert "sk-or-v1-abcdefgh12345678" not in body["error"]
    assert "[REDACTED]" in body["error"]


def test_api_report_without_a_prior_run_returns_404():
    resp = _client().get("/api/report")
    assert resp.status_code == 404


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_after_a_run_returns_pdf(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    run_resp = client.post("/api/run", json={
        "test_cases": [], "models": [], "api_key": "sk-or-v1-test",
    })
    assert run_resp.status_code == 200

    report_resp = client.get("/api/report")
    assert report_resp.status_code == 200
    assert report_resp.data.startswith(b"%PDF")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_honors_run_id_query_param(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"}

    first_resp = client.post("/api/run", json=payload)
    first_run_id = first_resp.get_json()["run_id"]
    client.post("/api/run", json=payload)  # second run becomes "latest"

    report_resp = client.get(f"/api/report?run_id={first_run_id}")
    assert report_resp.status_code == 200
    assert report_resp.data.startswith(b"%PDF")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_csv_after_a_run_returns_csv(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    client.post("/api/run", json={"test_cases": [], "models": [], "api_key": "sk-or-v1-test"})

    resp = client.get("/api/report.csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert resp.data.decode().startswith("prompt,model_id,status")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_runs_returns_history_newest_first(mock_verdict, mock_run):
    mock_run.return_value = []
    client = _client()
    payload = {"test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test"}

    mock_verdict.return_value = {"winner": "first", "rationale": ""}
    client.post("/api/run", json=payload)

    mock_verdict.return_value = {"winner": "second", "rationale": ""}
    client.post("/api/run", json=payload)

    runs_resp = client.get("/api/runs")
    runs = runs_resp.get_json()["runs"]
    assert runs[0]["winner"] == "second"
    assert runs[1]["winner"] == "first"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_runs_history_caps_at_five(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"}

    for _ in range(6):
        limiter._attempts.clear()  # bypass the 3-per-8h limit to exercise the history cap in isolation
        resp = client.post("/api/run", json=payload)
        assert resp.status_code == 200

    runs_resp = client.get("/api/runs")
    assert len(runs_resp.get_json()["runs"]) == 5


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_accepts_creds_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}],
        "models": ["anthropic/claude-sonnet-4.5@bedrock"],
        "creds": creds,
        "judge_backend": "bedrock",
    })

    assert resp.status_code == 200
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == creds
    assert run_kwargs["judge_backend"] == "bedrock"
    _, verdict_kwargs = mock_verdict.call_args
    assert verdict_kwargs["backend"] == "bedrock"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_legacy_api_key_becomes_openrouter_creds(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    _client().post("/api/run", json={"test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test"})

    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == {"openrouter": "sk-or-v1-test"}
    assert run_kwargs["judge_backend"] == "openrouter"


def test_api_run_invalid_judge_backend_returns_400():
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": [], "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "azure",
    })
    assert resp.status_code == 400
    assert "judge_backend" in resp.get_json()["error"]


def test_api_run_creds_must_be_an_object():
    resp = _client().post("/api/run", json={"test_cases": [], "models": [], "creds": "sk-or-v1-test"})
    assert resp.status_code == 400


def test_api_run_policy_without_judge_creds_returns_400_without_spending_a_run():
    client = _client()
    client.post(
        "/api/policy",
        data={"file": (io.BytesIO(b"No medical advice."), "policy.txt")},
        content_type="multipart/form-data",
    )

    resp = client.post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"],
        "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "vertex",
    })

    assert resp.status_code == 400
    assert "Vertex AI" in resp.get_json()["error"]
    assert all(len(v) == 0 for v in limiter._attempts.values())


def test_api_run_error_response_scrubs_aws_secret_by_exact_value(caplog):
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    with patch("app.runner.run", side_effect=Exception(f"signature mismatch for {secret}")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["anthropic/claude-sonnet-4.5@bedrock"],
            "creds": {
                "openrouter": "sk-or-v1-test",
                "bedrock": {"region": "us-east-1", "access_key_id": "AKIAABCDEFGHIJKLMNOP",
                            "secret_access_key": secret},
            },
        })

    assert resp.status_code == 503
    assert secret not in resp.get_json()["error"]
    assert secret not in caplog.text


@patch("app.judge.evaluate_prompt")
def test_api_evaluate_prompt_accepts_creds_and_judge_backend(mock_evaluate):
    mock_evaluate.return_value = {"score": 4, "feedback": "ok"}
    creds = {"vertex": {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.x"}}

    resp = _client().post("/api/evaluate-prompt", json={"prompt": "hi", "creds": creds, "judge_backend": "vertex"})

    assert resp.status_code == 200
    mock_evaluate.assert_called_once_with("hi", creds=creds, backend="vertex")


def test_api_evaluate_prompt_invalid_judge_backend_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={
        "prompt": "hi", "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "azure",
    })
    assert resp.status_code == 400


def test_api_run_without_judge_creds_returns_400_even_without_policy():
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"],
        "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "bedrock",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bedrock credentials are required for the judge backend."
    assert all(len(v) == 0 for v in limiter._attempts.values())


def test_api_run_invalid_backend_creds_rejected_before_rate_limit():
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["anthropic/claude-sonnet-4.5@bedrock"],
        "creds": {"openrouter": "sk-or-v1-test", "bedrock": {"region": "x.evil.com#", "api_key": "ABSKexample"}},
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Bedrock region is missing or invalid."
    assert all(len(v) == 0 for v in limiter._attempts.values())


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_ignores_bad_creds_for_backends_the_run_does_not_use(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"],
        "creds": {"openrouter": "sk-or-v1-test", "vertex": {"project": "BAD PROJECT", "region": "us-central1",
                                                             "access_token": "ya29.x"}},
    })
    assert resp.status_code == 200


def test_api_evaluate_prompt_without_judge_creds_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={
        "prompt": "hi", "creds": {"openrouter": "sk-or-v1-test"}, "judge_backend": "vertex",
    })
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Vertex AI credentials are required for the judge backend."


def test_api_run_rejects_more_than_four_models():
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q"}], "models": ["a/1", "a/2", "a/3", "a/4", "a/5"], "api_key": "sk-or-v1-test"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Pick at most 4 models."
    assert all(len(v) == 0 for v in limiter._attempts.values())


@pytest.mark.parametrize("bad_model", ["", "   "])
def test_api_run_rejects_empty_string_model_id(bad_model):
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q"}], "models": ["openai/gpt-5", bad_model], "api_key": "sk-or-v1-test"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Model ids must be non-empty strings."
    assert all(len(v) == 0 for v in limiter._attempts.values())


@pytest.mark.parametrize("repeats", [0, 4, "2", True, 2.0])
def test_api_run_rejects_bad_repeats(repeats):
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test", "repeats": repeats})
    assert resp.status_code == 400


@patch("app.analysis.build_run_result")
@patch("app.runner.run")
def test_api_run_passes_repeats_and_returns_analysis_fields(mock_run, mock_build):
    mock_run.return_value = []
    mock_build.return_value = {"results": [], "grades": {}, "stats": {}, "verdict": {"winner": None, "rationale": ""},
                               "suggestions": {}, "advice": "", "judge": {"backend": "openrouter", "model": "m"},
                               "bias_note": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test", "repeats": 3})
    assert resp.status_code == 200
    assert mock_run.call_args[1]["repeats"] == 3
    body = resp.get_json()
    assert {"run_id", "created_at", "suggestions", "advice", "judge", "bias_note"} <= set(body)


def test_api_catalog_exposes_cap_and_priority_weights():
    body = _client().get("/api/catalog").get_json()
    assert body["max_models"] == 4
    assert set(body["priority_weights"]) == {"balanced", "quality", "fastest", "cheapest"}
    assert body["priority_labels"]["fastest"] == "Fastest"


def test_api_report_rejects_invalid_priority():
    assert _client().get("/api/report?priority=vibes").status_code == 400


@patch("app.availability.snapshot")
def test_api_availability_returns_snapshot(mock_snapshot):
    mock_snapshot.return_value = {"generated_at": 123, "openrouter": {}, "backends": {}}
    resp = _client().get("/api/availability")
    assert resp.get_json() == {"generated_at": 123, "openrouter": {}, "backends": {}}


def test_api_catalog_exposes_regions_and_provider_links():
    body = _client().get("/api/catalog").get_json()
    assert set(body["regions"]) == {"bedrock", "vertex", "foundry"}
    assert set(body["provider_links"]) == {"openrouter", "bedrock", "vertex", "foundry"}
    assert body["provider_links"]["foundry"]["status"] == "https://azure.status.microsoft/en-us/status"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_accepts_foundry_target_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": "fake-api-key-12345678"}}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5@foundry"],
        "creds": creds, "judge_backend": "foundry",
    })

    assert resp.status_code == 200
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == creds
    assert run_kwargs["judge_backend"] == "foundry"


def test_api_run_error_response_scrubs_foundry_api_key(caplog):
    secret = "fake-foundry-secret-key-1234567890"
    with patch("app.runner.run", side_effect=Exception(f"request failed using {secret}")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5@foundry"],
            "creds": {"foundry": {"resource": "my-resource", "region": "eastus", "api_key": secret}},
            "judge_backend": "foundry",
        })
    assert resp.status_code == 503
    body = resp.get_json()
    assert secret not in body["error"]
    assert secret not in caplog.text


def test_availability_page_returns_200():
    resp = _client().get("/availability")
    assert resp.status_code == 200
    assert b"availability-table" in resp.data


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_includes_cost_and_per_cell_evaluation(mock_verdict, mock_run):
    mock_run.return_value = [{
        "test_case": {"prompt": "q1"},
        "cells": {
            "openai/gpt-5": {
                "model_id": "openai/gpt-5", "blocked": False, "error": None,
                "response_text": "answer", "latency_ms": 10, "cost_usd": 0.01, "tokens": 5,
                "checks": [], "judge_score": None, "judge_rationale": None,
                "evaluation": {
                    "available": True, "overall": 4,
                    "answered": {"score": 5, "explanation": "ok"}, "quality": {"score": 4, "explanation": "ok"},
                    "instruction_following": {"score": 4, "explanation": "ok"},
                    "completeness": {"score": 4, "explanation": "ok"}, "helpfulness": {"score": 4, "explanation": "ok"},
                    "safety": {"score": 5, "explanation": "ok"}, "strengths": [], "weaknesses": [], "reasoning": "ok",
                },
            }
        },
    }]
    mock_verdict.return_value = {"winner": "openai/gpt-5", "rationale": "best"}

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test",
    })

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["cost"] == {"model_usd": 0.0, "judge_usd": 0.0, "total_usd": 0.0, "judge_calls": 0}
    assert body["results"][0]["cells"]["openai/gpt-5"]["evaluation"]["overall"] == 4


def test_api_run_evaluation_gateway_error_never_leaks_secret(caplog):
    secret = "sk-or-v1-evalsecret1234567890"

    def _fake_call_target(target, messages, creds, timeout=60):
        return {"text": "answer", "latency_ms": 10, "cost_usd": 0.0, "tokens": 5, "output_tokens": 3}

    with patch("gateway.call_target", side_effect=_fake_call_target), \
         patch("judge.gateway.call_backend", side_effect=gateway.GatewayError(f"token {secret} rejected")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": secret,
        })

    assert resp.status_code == 200
    assert secret not in resp.get_data(as_text=True)
    body = resp.get_json()
    cell = body["results"][0]["cells"]["openai/gpt-5"]
    assert cell["evaluation"] == {"available": False, "reason": "Evaluation unavailable."}
    assert secret not in caplog.text
    history_resp = _client().get("/api/runs")
    assert secret not in history_resp.get_data(as_text=True)


SERVER_KEY = "sk-or-v1-server-secret-123456"


def test_api_catalog_lists_server_backends_without_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("FOUNDRY_RESOURCE", "evalforge-secret-resource")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-secret-key")
    data = _client().get("/api/catalog").get_json()
    assert data["server_backends"] == {"openrouter": {}, "foundry": {"region": "eastus2"}}
    text = json.dumps(data)
    for needle in (SERVER_KEY, "evalforge-secret-resource", "foundry-secret-key"):
        assert needle not in text


def test_api_catalog_server_backends_empty_by_default():
    assert _client().get("/api/catalog").get_json()["server_backends"] == {}


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_uses_server_key_when_client_sends_none(mock_verdict, mock_run, mock_explain, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 200
    assert mock_run.call_args.kwargs["creds"]["openrouter"] == SERVER_KEY


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_ignores_client_key_for_server_held_backend(mock_verdict, mock_run, mock_explain, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-user-key",
    })
    assert resp.status_code == 200
    assert mock_run.call_args.kwargs["creds"]["openrouter"] == SERVER_KEY


def test_api_run_without_any_creds_still_400_when_nothing_server_held():
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 400
    assert "api_key" in resp.get_json()["error"]


def test_api_run_error_scrubs_server_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    with patch("app.runner.run", side_effect=Exception(f"failed using key {SERVER_KEY}")):
        resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 503
    error = resp.get_json()["error"]
    assert SERVER_KEY not in error and "[REDACTED]" in error


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_server_key_cap_refuses_with_message(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]}
    assert client.post("/api/run", json=payload).status_code == 200
    second = client.post("/api/run", json=payload)
    assert second.status_code == 429
    body = second.get_json()
    assert body["error"] == "rate_limited"
    assert body["message"] == "The server's shared usage limit has been reached. Please try again later."
    assert body["reset_at"] is not None


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_session_limit_refusal_does_not_consume_server_cap(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]}
    for _ in range(3):
        assert client.post("/api/run", json=payload).status_code == 200
    assert client.post("/api/run", json=payload).status_code == 429  # per-session limit
    assert len(limiter._server_key_calls) == 3


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_cap_not_consumed_when_held_backend_is_not_needed(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-secret-key")
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-user-key",
    })
    assert resp.status_code == 200  # judge + target both OpenRouter, user-supplied
    assert limiter._server_key_calls == []


@patch("app.judge.evaluate_prompt")
def test_api_evaluate_prompt_uses_server_key_and_counts_against_cap(mock_evaluate, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_evaluate.return_value = {"score": 4, "feedback": "ok"}
    client = _client()
    assert client.post("/api/evaluate-prompt", json={"prompt": "hello"}).status_code == 200
    mock_evaluate.assert_called_once_with("hello", creds={"openrouter": SERVER_KEY}, backend="openrouter")
    second = client.post("/api/evaluate-prompt", json={"prompt": "hello again"})
    assert second.status_code == 429
    assert second.get_json()["message"].startswith("The server's shared usage limit")
