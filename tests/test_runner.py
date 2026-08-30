from unittest.mock import patch

import openrouter
import runner


def _fake_call_model(model_id, messages, api_key, timeout=60):
    return {"text": f"response from {model_id}", "latency_ms": 10, "cost_usd": 0.001, "tokens": 20}


@patch("runner.openrouter.call_model", side_effect=_fake_call_model)
def test_fans_out_every_test_case_by_model_pair(mock_call):
    test_cases = [{"prompt": "q1"}, {"prompt": "q2"}]
    model_ids = ["openai/gpt-5", "anthropic/claude-opus-4.5"]

    results = runner.run(test_cases, model_ids, api_key="sk-or-v1-test")

    assert len(results) == 2
    for row in results:
        assert set(row["cells"].keys()) == set(model_ids)
    assert mock_call.call_count == 4


@patch("runner.openrouter.call_model")
def test_one_model_failure_does_not_abort_other_cells(mock_call):
    def _side_effect(model_id, messages, api_key, timeout=60):
        if model_id == "broken/model":
            raise openrouter.OpenRouterError("rate limited")
        return {"text": "ok response", "latency_ms": 5, "cost_usd": 0.0, "tokens": 5}

    mock_call.side_effect = _side_effect

    results = runner.run([{"prompt": "q1"}], ["broken/model", "openai/gpt-5"], api_key="sk-or-v1-test")

    cells = results[0]["cells"]
    assert cells["broken/model"]["error"] == "rate limited"
    assert cells["openai/gpt-5"]["error"] is None
    assert cells["openai/gpt-5"]["response_text"] == "ok response"


@patch("runner.policy.check_policy")
@patch("runner.openrouter.call_model", side_effect=_fake_call_model)
def test_policy_blocked_case_skips_model_calls_entirely(mock_call, mock_policy):
    mock_policy.return_value = {"violates": True, "clause": "No medical advice.", "reason": "asks for diagnosis"}

    results = runner.run(
        [{"prompt": "diagnose me"}], ["openai/gpt-5"], api_key="sk-or-v1-test", policy_text="No medical advice."
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["blocked"] is True
    assert cell["policy_clause"] == "No medical advice."
    mock_call.assert_not_called()


@patch("runner.checks.run_checks")
@patch("runner.openrouter.call_model", side_effect=_fake_call_model)
def test_runs_rule_checks_when_defined(mock_call, mock_checks):
    mock_checks.return_value = [{"check": {"type": "contains", "value": "x"}, "passed": True}]

    results = runner.run(
        [{"prompt": "q1", "checks": [{"type": "contains", "value": "x"}]}],
        ["openai/gpt-5"],
        api_key="sk-or-v1-test",
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["checks"] == [{"check": {"type": "contains", "value": "x"}, "passed": True}]


@patch("runner.judge.llm_judge")
@patch("runner.openrouter.call_model", side_effect=_fake_call_model)
def test_runs_judge_when_rubric_defined(mock_call, mock_judge):
    mock_judge.return_value = {"score": 4, "rationale": "Good."}

    results = runner.run(
        [{"prompt": "q1", "rubric": "be accurate"}], ["openai/gpt-5"], api_key="sk-or-v1-test"
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["judge_score"] == 4
    assert cell["judge_rationale"] == "Good."
