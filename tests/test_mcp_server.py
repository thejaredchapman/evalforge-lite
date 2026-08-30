import base64
from unittest.mock import patch

import limiter
import mcp_server


def setup_function():
    mcp_server._policy_text = None
    mcp_server._run_history.clear()
    limiter._attempts.clear()


def test_list_models_returns_providers_and_frontier():
    result = mcp_server.list_models()
    assert "providers" in result
    assert "frontier" in result
    assert len(result["frontier"]) > 0


def test_suggest_models_returns_family_suggestions():
    result = mcp_server.suggest_models("openai/gpt-5")
    assert "suggestions" in result
    assert any(m["id"] == "openai/gpt-5-mini" for m in result["suggestions"])


def test_set_policy_stores_text():
    result = mcp_server.set_policy("No medical advice.")
    assert result == {"ok": True}
    assert mcp_server._policy_text == "No medical advice."


def test_run_comparison_missing_api_key_returns_error():
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="")
    assert "error" in result
    assert "api_key" in result["error"]


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_returns_results_grades_and_verdict(mock_verdict, mock_run):
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

    result = mcp_server.run_comparison(
        test_cases=[{"prompt": "q1", "rubric": "be accurate"}],
        models=["openai/gpt-5"],
        api_key="sk-or-v1-test",
    )

    assert result["verdict"]["winner"] == "openai/gpt-5"
    assert result["grades"]["openai/gpt-5"]["letter"] == "A+"
    assert "run_id" in result
    assert "created_at" in result
    assert result["stats"]["openai/gpt-5"]["total_cost_usd"] == 0.01
    assert result["stats"]["openai/gpt-5"]["avg_latency_ms"] == 10.0


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_blocks_after_three_calls_in_window(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    payload = dict(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="sk-or-v1-test")

    for _ in range(3):
        result = mcp_server.run_comparison(**payload)
        assert "error" not in result

    fourth = mcp_server.run_comparison(**payload)
    assert fourth["error"] == "rate_limited"
    assert "reset_at" in fourth


def test_run_comparison_scrubs_api_key_on_error():
    with patch("mcp_server.runner.run", side_effect=Exception("failed using key sk-or-v1-abcdefgh12345678")):
        result = mcp_server.run_comparison(
            test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="sk-or-v1-abcdefgh12345678",
        )
    assert "sk-or-v1-abcdefgh12345678" not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_get_report_without_a_prior_run_returns_error():
    assert mcp_server.get_report() == {"error": "no_run_available"}


def test_get_report_csv_without_a_prior_run_returns_error():
    assert mcp_server.get_report_csv() == {"error": "no_run_available"}


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_after_a_run_returns_pdf_base64(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report()
    pdf_bytes = base64.b64decode(result["pdf_base64"])
    assert pdf_bytes.startswith(b"%PDF")


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_honors_run_id(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    first = mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report(run_id=first["run_id"])
    assert "pdf_base64" in result


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_csv_after_a_run_returns_csv(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report_csv()
    assert result["csv"].startswith("prompt,model_id,status")


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_list_runs_returns_history_newest_first(mock_verdict, mock_run):
    mock_run.return_value = []
    payload = dict(test_cases=[], models=["openai/gpt-5"], api_key="sk-or-v1-test")

    mock_verdict.return_value = {"winner": "first", "rationale": ""}
    mcp_server.run_comparison(**payload)

    mock_verdict.return_value = {"winner": "second", "rationale": ""}
    mcp_server.run_comparison(**payload)

    runs = mcp_server.list_runs()["runs"]
    assert runs[0]["winner"] == "second"
    assert runs[1]["winner"] == "first"


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_history_caps_at_five(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    payload = dict(test_cases=[], models=[], api_key="sk-or-v1-test")

    for _ in range(6):
        limiter._attempts.clear()  # bypass the 3-per-8h limit to exercise the history cap in isolation
        mcp_server.run_comparison(**payload)

    assert len(mcp_server.list_runs()["runs"]) == 5
