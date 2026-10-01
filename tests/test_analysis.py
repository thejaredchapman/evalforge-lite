from unittest.mock import patch

import analysis
import costs
import judge


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
        "evaluation_avg": {
            "answered": None, "quality": None, "instruction_following": None, "completeness": None,
            "helpfulness": None, "safety": None, "overall_avg": None, "evaluated_cells": 0,
        },
        "latency_vs_fastest": None,
    }
    assert set(out["grades"]["openai/gpt-5"]["categories"]) == {
        "accuracy", "rule_checks", "cost_efficiency", "response_time", "throughput", "evaluation"}
    assert out["cost"] == {"model_usd": 0.0, "judge_usd": 0.0, "total_usd": 0.0, "judge_calls": 0}
    assert out["results"][0]["latency_ranking"][0]["model_id"] == "openai/gpt-5"
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


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_explainer_allowed_terms_include_foundry_label(mock_verdict, mock_explain):
    analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter")
    allowed = mock_explain.call_args[1]["allowed_terms"]
    assert "Microsoft Foundry" in allowed


def _cell(latency, cost=0.001, judge_score=None, checks=None, evaluation=None):
    return {
        "blocked": False, "error": None, "response_text": "a", "latency_ms": latency, "latency_ms_stdev": None,
        "tokens_per_sec": None, "cost_usd": cost, "tokens": 10, "output_tokens": 5,
        "checks": checks or [], "judge_score": judge_score, "judge_rationale": "ok" if judge_score else None,
        "evaluation": evaluation,
    }


def _available_evaluation(overall, **score_overrides):
    criteria = {crit: {"score": score_overrides.get(crit, overall), "explanation": "ok"}
                for crit in judge.EVALUATION_CRITERIA}
    return {**criteria, "strengths": [], "weaknesses": [], "reasoning": "ok", "overall": overall, "available": True}


def test_evaluation_avg_aggregates_available_evaluations_only():
    results = [
        {"test_case": {"prompt": "q"}, "cells": {"openai/gpt-5": _cell(1000, evaluation=_available_evaluation(4, answered=5))}},
        {"test_case": {"prompt": "q2"}, "cells": {"openai/gpt-5": _cell(1200, evaluation=_available_evaluation(2, answered=3))}},
    ]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    evaluation_avg = out["stats"]["openai/gpt-5"]["evaluation_avg"]
    assert evaluation_avg["answered"] == 4.0
    assert evaluation_avg["quality"] == 3.0
    assert evaluation_avg["overall_avg"] == 3.0
    assert evaluation_avg["evaluated_cells"] == 2


def test_evaluation_unavailable_cells_are_excluded_from_evaluation_avg():
    results = [{"test_case": {"prompt": "q"}, "cells": {
        "openai/gpt-5": _cell(1000, evaluation={"available": False, "reason": "Evaluation unavailable."}),
    }}]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    evaluation_avg = out["stats"]["openai/gpt-5"]["evaluation_avg"]
    assert evaluation_avg["evaluated_cells"] == 0
    assert evaluation_avg["answered"] is None


def test_quality_score_blends_existing_and_evaluation_scores_equally():
    results = [{"test_case": {"prompt": "q", "rubric": "r"}, "cells": {
        "openai/gpt-5": _cell(1000, judge_score=5, evaluation=_available_evaluation(3)),
    }}]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    # existing (judge-only) score: 5 * 20 = 100.0; eval score: 3 * 20 = 60.0; blended: 80.0
    assert out["grades"]["openai/gpt-5"]["score"] == 80.0
    assert out["grades"]["openai/gpt-5"]["categories"]["evaluation"] == 60.0


def test_quality_score_is_evaluation_only_without_rubric_or_checks():
    results = [{"test_case": {"prompt": "q"}, "cells": {
        "openai/gpt-5": _cell(1000, evaluation=_available_evaluation(4)),
    }}]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    assert out["grades"]["openai/gpt-5"]["score"] == 80.0
    assert out["grades"]["openai/gpt-5"]["letter"] == "B-"


def test_quality_score_is_none_without_evaluation_rubric_or_checks():
    results = [{"test_case": {"prompt": "q"}, "cells": {
        "openai/gpt-5": _cell(1000, evaluation={"available": False, "reason": "Evaluation unavailable."}),
    }}]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    assert out["grades"]["openai/gpt-5"]["score"] is None
    assert out["grades"]["openai/gpt-5"]["categories"]["evaluation"] is None


def test_latency_vs_fastest_and_ranking():
    results = [{"test_case": {"prompt": "q"}, "cells": {
        "openai/gpt-5": _cell(1000),
        "anthropic/claude-sonnet-4.5": _cell(2500),
        "meta-llama/llama-4-scout": {"blocked": False, "error": "down"},
    }}]
    targets = ["openai/gpt-5", "anthropic/claude-sonnet-4.5", "meta-llama/llama-4-scout"]
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(results, targets, {"openrouter": "k"}, "openrouter")
    assert out["stats"]["openai/gpt-5"]["latency_vs_fastest"] == 1.0
    assert out["stats"]["anthropic/claude-sonnet-4.5"]["latency_vs_fastest"] == 2.5
    assert out["stats"]["meta-llama/llama-4-scout"]["latency_vs_fastest"] is None
    assert out["results"][0]["latency_ranking"] == [
        {"model_id": "openai/gpt-5", "latency_ms": 1000},
        {"model_id": "anthropic/claude-sonnet-4.5", "latency_ms": 2500},
    ]


def test_cost_in_result_uses_meter_totals():
    meter = costs.CostMeter()
    meter.add("model", 0.01)
    meter.add("judge", 0.002)
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter", meter=meter)
    assert out["cost"] == {"model_usd": 0.01, "judge_usd": 0.002, "total_usd": 0.012, "judge_calls": 1}


def test_cost_in_result_defaults_to_zero_without_meter():
    with patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""}), \
         patch("analysis.judge.explain_recommendations", return_value=""):
        out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "k"}, "openrouter")
    assert out["cost"] == {"model_usd": 0.0, "judge_usd": 0.0, "total_usd": 0.0, "judge_calls": 0}
