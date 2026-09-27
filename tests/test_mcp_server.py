import base64
import io
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


@patch("mcp_server.judge.evaluate_prompt")
def test_evaluate_prompt_returns_score_and_feedback(mock_evaluate):
    mock_evaluate.return_value = {"score": 2, "feedback": "Too vague."}
    result = mcp_server.evaluate_prompt("Tell me stuff", api_key="sk-or-v1-test")
    assert result == {"score": 2, "feedback": "Too vague."}
    mock_evaluate.assert_called_once_with(
        "Tell me stuff", creds={"openrouter": "sk-or-v1-test"}, backend="openrouter"
    )


@patch("mcp_server.judge.evaluate_prompt")
def test_evaluate_prompt_blocks_after_three_calls_in_window(mock_evaluate):
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}

    for _ in range(3):
        result = mcp_server.evaluate_prompt("hello", api_key="sk-or-v1-test")
        assert "error" not in result

    fourth = mcp_server.evaluate_prompt("hello", api_key="sk-or-v1-test")
    assert fourth["error"] == "rate_limited"
    assert "reset_at" in fourth


@patch("mcp_server.judge.evaluate_prompt")
@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_evaluate_prompt_rate_limit_is_independent_from_run_rate_limit(mock_verdict, mock_run, mock_evaluate):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}

    for _ in range(3):
        result = mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")
        assert "error" not in result

    # evaluate_prompt should still work — it's a separate rate-limit bucket
    result = mcp_server.evaluate_prompt("hello", api_key="sk-or-v1-test")
    assert "error" not in result


def test_run_comparison_missing_api_key_returns_error():
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="")
    assert "error" in result
    assert "api_key" in result["error"]


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_returns_results_grades_and_verdict(mock_verdict, mock_run, mock_explain):
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
    assert result["grades"]["openai/gpt-5"]["categories"]["accuracy"] == 100.0
    assert result["results"][0]["best_model"]["model_id"] == "openai/gpt-5"


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


@patch("mcp_server.analysis.build_run_result")
@patch("mcp_server.runner.run", return_value=[])
def test_get_report_after_priority_run_includes_priority_line(mock_run, mock_build):
    mock_build.return_value = {
        "results": [], "verdict": {"winner": None, "rationale": ""}, "suggestions": {}, "advice": "",
        "judge": {"backend": "openrouter", "model": "m"}, "bias_note": "",
        "grades": {"a/x": {"score": 95, "categories": {"response_time": 0, "throughput": 0, "cost_efficiency": 0}},
                   "a/y": {"score": 70, "categories": {"response_time": 100, "throughput": 100, "cost_efficiency": 100}}},
        "stats": {"a/x": {"ok_cells": 1, "avg_latency_ms": 900}, "a/y": {"ok_cells": 1, "avg_latency_ms": 100}},
    }
    mcp_server.run_comparison(test_cases=[], models=["a/x", "a/y"], api_key="sk-or-v1-test", priority="fastest")

    result = mcp_server.get_report()
    import pdfplumber
    pdf_bytes = base64.b64decode(result["pdf_base64"])
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Priority:" in text


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


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_accepts_creds_and_judge_backend(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexampleexampleexample1234"}}

    result = mcp_server.run_comparison(
        test_cases=[{"prompt": "q1"}], models=["anthropic/claude-sonnet-4.5@bedrock"],
        creds=creds, judge_backend="bedrock",
    )

    assert "error" not in result
    _, run_kwargs = mock_run.call_args
    assert run_kwargs["creds"] == creds
    assert run_kwargs["judge_backend"] == "bedrock"
    assert mock_verdict.call_args[1]["backend"] == "bedrock"


def test_run_comparison_invalid_judge_backend_returns_error():
    result = mcp_server.run_comparison(test_cases=[], models=[], creds={"openrouter": "sk-or-v1-test"},
                                       judge_backend="azure")
    assert result["error"] == "Invalid judge_backend."


def test_run_comparison_policy_without_judge_creds_returns_error():
    mcp_server.set_policy("No medical advice.")
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"],
                                       api_key="sk-or-v1-test", judge_backend="vertex")
    assert "Vertex AI" in result["error"]


def test_run_comparison_error_scrubs_secret_by_exact_value():
    secret = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    with patch("mcp_server.runner.run", side_effect=Exception(f"signature mismatch for {secret}")):
        result = mcp_server.run_comparison(
            test_cases=[{"prompt": "q1"}], models=["anthropic/claude-sonnet-4.5@bedrock"],
            creds={"bedrock": {"region": "us-east-1", "access_key_id": "AKIAABCDEFGHIJKLMNOP",
                               "secret_access_key": secret}},
            judge_backend="bedrock",
        )
    assert secret not in result["error"]


@patch("mcp_server.judge.evaluate_prompt")
def test_evaluate_prompt_tool_accepts_creds(mock_evaluate):
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}
    creds = {"vertex": {"project": "my-project-123", "region": "us-central1", "access_token": "ya29.x"}}

    mcp_server.evaluate_prompt("hi", creds=creds, judge_backend="vertex")

    mock_evaluate.assert_called_once_with("hi", creds=creds, backend="vertex")


def test_evaluate_prompt_tool_without_creds_returns_error():
    result = mcp_server.evaluate_prompt("hi")
    assert "creds" in result["error"]


def test_run_comparison_without_judge_creds_returns_error_even_without_policy():
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"],
                                       api_key="sk-or-v1-test", judge_backend="bedrock")
    assert result["error"] == "Bedrock credentials are required for the judge backend."
    assert all(len(v) == 0 for v in limiter._attempts.values())


def test_run_comparison_invalid_backend_creds_rejected_before_rate_limit():
    result = mcp_server.run_comparison(
        test_cases=[{"prompt": "q1"}], models=["anthropic/claude-sonnet-4.5@bedrock"],
        creds={"openrouter": "sk-or-v1-test", "bedrock": {"region": "x.evil.com#", "api_key": "ABSKexample"}},
    )
    assert result["error"] == "Bedrock region is missing or invalid."
    assert all(len(v) == 0 for v in limiter._attempts.values())


def test_evaluate_prompt_tool_without_judge_creds_returns_error():
    result = mcp_server.evaluate_prompt("hi", api_key="sk-or-v1-test", judge_backend="vertex")
    assert result["error"] == "Vertex AI credentials are required for the judge backend."


def test_run_comparison_rejects_more_than_four_models():
    result = mcp_server.run_comparison(test_cases=[], models=["a/1", "a/2", "a/3", "a/4", "a/5"], api_key="sk-or-v1-test")
    assert result == {"error": "Pick at most 4 models."}


def test_run_comparison_rejects_invalid_priority_and_repeats():
    assert mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test", priority="vibes") == {"error": "Invalid priority."}
    assert mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test", repeats=5) == {"error": "repeats must be 1, 2, or 3."}
    assert mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test", repeats=2.0) == {"error": "repeats must be 1, 2, or 3."}


def test_run_comparison_rejects_empty_string_model_id():
    result = mcp_server.run_comparison(test_cases=[], models=["openai/gpt-5", "   "], api_key="sk-or-v1-test")
    assert result == {"error": "Model ids must be non-empty strings."}
    assert all(len(v) == 0 for v in limiter._attempts.values())


@patch("mcp_server.analysis.build_run_result")
@patch("mcp_server.runner.run", return_value=[])
def test_run_comparison_returns_ranking_for_priority(mock_run, mock_build):
    mock_build.return_value = {
        "results": [], "verdict": {"winner": None, "rationale": ""}, "suggestions": {}, "advice": "",
        "judge": {"backend": "openrouter", "model": "m"}, "bias_note": "",
        "grades": {"a/x": {"score": 95, "categories": {"response_time": 0, "throughput": 0, "cost_efficiency": 0}},
                   "a/y": {"score": 70, "categories": {"response_time": 100, "throughput": 100, "cost_efficiency": 100}}},
        "stats": {"a/x": {"ok_cells": 1, "avg_latency_ms": 900}, "a/y": {"ok_cells": 1, "avg_latency_ms": 100}},
    }
    result = mcp_server.run_comparison(test_cases=[], models=["a/x", "a/y"], api_key="sk-or-v1-test", priority="fastest", repeats=2)
    assert result["ranking"] == ["a/y", "a/x"]
    assert result["best_for_priority"] == "a/y"
    assert mock_run.call_args[1]["repeats"] == 2
