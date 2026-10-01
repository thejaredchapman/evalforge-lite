import advisor

CATALOG = {
    "anthropic": {"models": [
        {"id": "~anthropic/claude-opus-latest", "name": "Claude Opus (Latest)", "tier": "flagship"},
        {"id": "anthropic/claude-opus-4.5", "name": "Claude Opus 4.5", "tier": "flagship",
         "routes": {"bedrock": {"id": "x"}}},
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "tier": "balanced",
         "routes": {"bedrock": {"id": "y"}}},
        {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "tier": "fast"},
    ]},
    "openai": {"models": [
        {"id": "openai/gpt-5", "name": "GPT-5", "tier": "flagship"},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "tier": "fast"},
    ]},
}


def _g(score, response_time=100.0, throughput=100.0, cost_efficiency=100.0):
    return {"score": score, "categories": {"response_time": response_time, "throughput": throughput,
                                           "cost_efficiency": cost_efficiency}}


def _s(latency=1000.0, tps=50.0, cost=0.001, ok=1):
    return {"ok_cells": ok, "avg_latency_ms": latency, "avg_tokens_per_sec": tps, "total_cost_usd": cost}


def test_low_quality_suggests_higher_tier_same_provider():
    out = advisor.suggest_all({"anthropic/claude-sonnet-4.5": _g(60)},
                              {"anthropic/claude-sonnet-4.5": _s()}, CATALOG)
    assert out["anthropic/claude-sonnet-4.5"]["model_id"] == "anthropic/claude-opus-4.5"
    assert out["anthropic/claude-sonnet-4.5"]["reason_code"] == "quality"


def test_quality_trailing_best_by_15_is_weak():
    grades = {"anthropic/claude-sonnet-4.5": _g(80), "openai/gpt-5": _g(96)}
    stats = {t: _s() for t in grades}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"]["reason_code"] == "quality"


def test_slow_model_suggests_faster_tier_when_gap_is_real():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=0.0),
              "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5": _s(latency=3000.0, tps=20.0), "openai/gpt-5": _s(latency=1000.0, tps=80.0)}
    out = advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"]
    assert out["model_id"] == "anthropic/claude-haiku-4.5"
    assert out["reason_code"] == "latency"


def test_small_latency_gap_is_not_flagged():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=100.0),
              "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5": _s(latency=1100.0), "openai/gpt-5": _s(latency=1000.0)}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_pricey_strong_model_suggests_cheaper_tier():
    grades = {"anthropic/claude-opus-4.5": _g(95, cost_efficiency=0.0), "openai/gpt-5": _g(93)}
    stats = {"anthropic/claude-opus-4.5": _s(cost=0.01), "openai/gpt-5": _s(cost=0.002)}
    out = advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-opus-4.5"]
    assert out["model_id"] == "anthropic/claude-sonnet-4.5"
    assert out["reason_code"] == "cost"


def test_bedrock_target_only_suggests_bedrock_routed_siblings_with_suffix():
    grades = {"anthropic/claude-sonnet-4.5@bedrock": _g(90, response_time=0.0), "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5@bedrock": _s(latency=3000.0), "openai/gpt-5": _s(latency=1000.0)}
    # Haiku (fast) has no bedrock route in this fixture, so there's no faster Bedrock sibling.
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5@bedrock"] is None
    grades = {"anthropic/claude-sonnet-4.5@bedrock": _g(60)}
    out = advisor.suggest_all(grades, {"anthropic/claude-sonnet-4.5@bedrock": _s()}, CATALOG)
    assert out["anthropic/claude-sonnet-4.5@bedrock"]["model_id"] == "anthropic/claude-opus-4.5@bedrock"
    assert "Bedrock" in out["anthropic/claude-sonnet-4.5@bedrock"]["reason"]


def test_never_suggests_aliases_other_providers_or_already_compared_targets():
    grades = {"anthropic/claude-sonnet-4.5": _g(60), "anthropic/claude-opus-4.5": _g(90)}
    stats = {t: _s() for t in grades}
    # Opus is already compared and the alias is excluded, so there's no higher-tier candidate left.
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_failed_target_and_custom_ids_get_no_suggestion():
    grades = {"anthropic/claude-sonnet-4.5": _g(None), "someone/custom-model": _g(10)}
    stats = {"anthropic/claude-sonnet-4.5": _s(ok=0), "someone/custom-model": _s()}
    out = advisor.suggest_all(grades, stats, CATALOG)
    assert out == {"anthropic/claude-sonnet-4.5": None, "someone/custom-model": None}


def test_one_model_run_only_uses_quality_rule():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=0.0, cost_efficiency=0.0)}
    assert advisor.suggest_all(grades, {"anthropic/claude-sonnet-4.5": _s()}, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_good_fit_returns_none():
    grades = {"anthropic/claude-sonnet-4.5": _g(92), "openai/gpt-5": _g(94)}
    stats = {t: _s() for t in grades}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None
