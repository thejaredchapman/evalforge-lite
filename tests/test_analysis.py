from unittest.mock import patch

import analysis


def _ok(latency, tps, cost=0.001, score=4):
    return {"blocked": False, "error": None, "response_text": "a", "latency_ms": latency, "latency_ms_stdev": None,
            "tokens_per_sec": tps, "cost_usd": cost, "tokens": 10, "output_tokens": 5, "checks": [],
            "judge_score": score, "judge_rationale": "ok"}


RESULTS = [{"test_case": {"prompt": "q", "rubric": "r"}, "cells": {
    "anthropic/claude-sonnet-4.5": _ok(3000, 20.0, score=5),  # same quality, 3x slower -> "latency" weakness
    "openai/gpt-5": _ok(1000, 80.0, score=5),
    "meta-llama/llama-4-scout": {"blocked": False, "error": "down"},
}}]
TARGETS = ["anthropic/claude-sonnet-4.5", "openai/gpt-5", "meta-llama/llama-4-scout"]


@patch("analysis.judge.explain_recommendations", return_value="Plain advice.")
@patch("analysis.judge.overall_verdict", return_value={"winner": "openai/gpt-5", "rationale": "best"})
def test_build_run_result_shape(mock_verdict, mock_explain):
    out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "sk-or-v1-test"}, "openrouter")
    assert set(out) >= {"results", "grades", "stats", "verdict", "suggestions", "advice", "judge", "bias_note"}
    assert out["stats"]["anthropic/claude-sonnet-4.5"]["avg_tokens_per_sec"] == 20.0
    assert out["stats"]["meta-llama/llama-4-scout"] == {
        "total_cost_usd": 0.0, "avg_latency_ms": 0.0, "avg_latency_stdev_ms": None, "avg_tokens_per_sec": None,
        "ok_cells": 0, "error_cells": 1, "blocked_cells": 0,
    }
    assert set(out["grades"]["openai/gpt-5"]["categories"]) == {
        "accuracy", "rule_checks", "cost_efficiency", "response_time", "throughput"}
    assert out["suggestions"]["anthropic/claude-sonnet-4.5"]["model_id"] == "anthropic/claude-haiku-4.5"
    assert out["suggestions"]["meta-llama/llama-4-scout"] is None
    assert out["advice"] == "Plain advice."
    assert out["judge"] == {"backend": "openrouter", "model": "openai/gpt-4o-mini"}
    assert out["results"][0]["best_model"]["model_id"] == "openai/gpt-5"
    disallowed = mock_explain.call_args[1]["disallowed_terms"]
    assert "Claude Haiku 4.5" not in disallowed and "GPT-5 Mini" in disallowed


@patch("analysis.judge.explain_recommendations", return_value="x")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_bias_note_when_judge_shares_a_provider(mock_verdict, mock_explain):
    out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "sk-or-v1-test"}, "openrouter")
    assert "GPT-5" in out["bias_note"] or "openai/gpt-5" in out["bias_note"]


@patch("analysis.judge.explain_recommendations")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": "No models were run."})
def test_no_successful_targets_skips_explainer(mock_verdict, mock_explain):
    results = [{"test_case": {"prompt": "q"}, "cells": {"openai/gpt-5": {"blocked": True, "policy_clause": "c", "policy_reason": "r"}}}]
    out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    assert out["advice"] == ""
    assert out["stats"]["openai/gpt-5"]["blocked_cells"] == 1
    mock_explain.assert_not_called()


def test_judge_model_label_resolves_bedrock_geo():
    assert analysis.judge_model_label("bedrock", {"bedrock": {"region": "eu-west-1", "api_key": "k"}}).startswith("eu.anthropic.")
    assert analysis.judge_model_label("bedrock", {}).startswith("{geo}.")


def test_disallowed_terms_keep_shorter_sibling_when_longer_variant_is_allowed():
    import catalog
    terms = analysis._disallowed_terms(catalog.load_catalog(), ["openai/gpt-5-mini"], ["GPT-5 Mini"])
    assert "GPT-5" in terms and "openai/gpt-5" in terms
    assert "GPT-5 Mini" not in terms and "openai/gpt-5-mini" not in terms


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_explainer_receives_allowed_terms_and_stats_are_floats(mock_verdict, mock_explain):
    out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter")
    allowed = mock_explain.call_args[1]["allowed_terms"]
    assert "anthropic/claude-sonnet-4.5" in allowed and "Claude Haiku 4.5" in allowed
    assert isinstance(out["stats"]["openai/gpt-5"]["avg_latency_ms"], float)


def test_disallowed_terms_include_off_provider_stems_and_off_catalog_vendors():
    import catalog
    terms = analysis._disallowed_terms(catalog.load_catalog(), ["openai/gpt-5", "openai/gpt-4o"], ["GPT-5", "GPT-4o"])
    assert "Claude" in terms and "Anthropic" in terms
    assert "Gemini" in terms and "Llama" in terms
    assert "DeepSeek" in terms
    assert "GPT" not in terms and "OpenAI" not in terms


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_explainer_allowed_terms_include_backend_labels(mock_verdict, mock_explain):
    analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter")
    allowed = mock_explain.call_args[1]["allowed_terms"]
    assert "Google Vertex AI" in allowed


@patch("judge.gateway.call_backend")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_advice_naming_off_catalog_model_is_dropped_end_to_end(mock_verdict, mock_call_backend):
    results = [{"test_case": {"prompt": "q", "rubric": "r"}, "cells": {
        "openai/gpt-5": _ok(1000, 50.0, score=5),
        "openai/gpt-4o": _ok(1200, 40.0, score=4),
    }}]
    targets = ["openai/gpt-5", "openai/gpt-4o"]

    def _fake(backend, model_id, messages, creds, timeout=60):
        return {"text": '{"advice": "GPT-5 is slow; consider Claude or DeepSeek instead."}',
                "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    mock_call_backend.side_effect = _fake

    out = analysis.build_run_result(results, targets, {"openrouter": "sk-or-v1-test"}, "openrouter")
    assert out["advice"] == ""
