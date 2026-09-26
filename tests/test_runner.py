from unittest.mock import patch

import gateway
import openrouter
import runner


def _fake_call_target(target, messages, creds, timeout=60):
    return {"text": f"response from {target}", "latency_ms": 10, "cost_usd": 0.001, "tokens": 20}


@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_fans_out_every_test_case_by_model_pair(mock_call):
    test_cases = [{"prompt": "q1"}, {"prompt": "q2"}]
    model_ids = ["openai/gpt-5", "anthropic/claude-opus-4.5"]

    results = runner.run(test_cases, model_ids, creds={"openrouter": "sk-or-v1-test"})

    assert len(results) == 2
    for row in results:
        assert set(row["cells"].keys()) == set(model_ids)
    assert mock_call.call_count == 4


@patch("runner.gateway.call_target")
def test_one_model_failure_does_not_abort_other_cells(mock_call):
    def _side_effect(target, messages, creds, timeout=60):
        if target == "broken/model":
            raise openrouter.OpenRouterError("rate limited")
        return {"text": "ok response", "latency_ms": 5, "cost_usd": 0.0, "tokens": 5}

    mock_call.side_effect = _side_effect

    results = runner.run([{"prompt": "q1"}], ["broken/model", "openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"})

    cells = results[0]["cells"]
    assert cells["broken/model"]["error"] == "rate limited"
    assert cells["openai/gpt-5"]["error"] is None
    assert cells["openai/gpt-5"]["response_text"] == "ok response"


@patch("runner.policy.check_policy")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_policy_blocked_case_skips_model_calls_entirely(mock_call, mock_policy):
    mock_policy.return_value = {"violates": True, "clause": "No medical advice.", "reason": "asks for diagnosis"}

    results = runner.run(
        [{"prompt": "diagnose me"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"}, policy_text="No medical advice."
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["blocked"] is True
    assert cell["policy_clause"] == "No medical advice."
    mock_call.assert_not_called()


@patch("runner.checks.run_checks")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_runs_rule_checks_when_defined(mock_call, mock_checks):
    mock_checks.return_value = [{"check": {"type": "contains", "value": "x"}, "passed": True}]

    results = runner.run(
        [{"prompt": "q1", "checks": [{"type": "contains", "value": "x"}]}],
        ["openai/gpt-5"],
        creds={"openrouter": "sk-or-v1-test"},
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["checks"] == [{"check": {"type": "contains", "value": "x"}, "passed": True}]


@patch("runner.judge.llm_judge")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_runs_judge_when_rubric_defined(mock_call, mock_judge):
    mock_judge.return_value = {"score": 4, "rationale": "Good."}

    results = runner.run(
        [{"prompt": "q1", "rubric": "be accurate"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"}
    )

    cell = results[0]["cells"]["openai/gpt-5"]
    assert cell["judge_score"] == 4
    assert cell["judge_rationale"] == "Good."


@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_same_model_on_two_backends_gets_two_cells(mock_call):
    targets = ["anthropic/claude-sonnet-4.5", "anthropic/claude-sonnet-4.5@bedrock"]

    results = runner.run(
        [{"prompt": "q1"}], targets,
        creds={"openrouter": "sk-or-v1-test", "bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}},
    )

    cells = results[0]["cells"]
    assert set(cells.keys()) == set(targets)
    assert cells["anthropic/claude-sonnet-4.5@bedrock"]["response_text"] == "response from anthropic/claude-sonnet-4.5@bedrock"


def test_missing_backend_creds_becomes_a_cell_error_not_a_crash():
    results = runner.run([{"prompt": "q1"}], ["anthropic/claude-sonnet-4.5@bedrock"],
                         creds={"openrouter": "sk-or-v1-test"})

    cell = results[0]["cells"]["anthropic/claude-sonnet-4.5@bedrock"]
    assert cell["error"] == "No Bedrock credentials supplied."


@patch("runner.gateway.prepare_creds")
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_prepares_creds_once_and_threads_prepared_creds(mock_call, mock_prepare):
    mock_prepare.return_value = {"openrouter": "sk-or-v1-prepared"}

    runner.run([{"prompt": "q1"}, {"prompt": "q2"}], ["openai/gpt-5", "openai/gpt-5-mini"],
               creds={"openrouter": "sk-or-v1-raw"})

    mock_prepare.assert_called_once_with({"openrouter": "sk-or-v1-raw"})
    for call in mock_call.call_args_list:
        assert call[0][2] == {"openrouter": "sk-or-v1-prepared"}


@patch("runner.gateway.call_target")
def test_cell_error_is_scrubbed_of_credential_secrets(mock_call):
    secret = "ABSKexamplesecretvalue1234567890"

    def _side_effect(target, messages, creds, timeout=60):
        raise gateway.GatewayError(f"bad header 'Bearer {secret}'")

    mock_call.side_effect = _side_effect

    creds = {"bedrock": {"region": "us-east-1", "api_key": secret}}
    results = runner.run([{"prompt": "q1"}], ["anthropic/claude-sonnet-4.5@bedrock"], creds=creds)

    error = results[0]["cells"]["anthropic/claude-sonnet-4.5@bedrock"]["error"]
    assert secret not in error
    assert "[REDACTED]" in error


@patch("runner.judge.llm_judge", return_value={"score": 4, "rationale": "Good."})
@patch("runner.policy.check_policy", return_value={"violates": False, "clause": "", "reason": ""})
@patch("runner.gateway.call_target", side_effect=_fake_call_target)
def test_judge_backend_is_passed_to_policy_and_judge(mock_call, mock_policy, mock_judge):
    runner.run([{"prompt": "q1", "rubric": "r"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"},
               policy_text="some policy", judge_backend="vertex")

    assert mock_policy.call_args[1]["backend"] == "vertex"
    assert mock_judge.call_args[1]["backend"] == "vertex"
