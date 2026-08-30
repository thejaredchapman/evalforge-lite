import io
import re
from unittest.mock import patch

import app as app_module
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
    mock_evaluate.assert_called_once_with("Tell me stuff", api_key="sk-or-v1-test")


def test_api_evaluate_prompt_missing_prompt_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={"api_key": "sk-or-v1-test"})
    assert resp.status_code == 400


def test_api_evaluate_prompt_missing_api_key_returns_400():
    resp = _client().post("/api/evaluate-prompt", json={"prompt": "hello"})
    assert resp.status_code == 400


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


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_returns_results_grades_and_verdict(mock_verdict, mock_run):
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
