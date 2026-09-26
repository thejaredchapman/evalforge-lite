from unittest.mock import patch

import config
import gateway
import judge


def _fake_call_backend(text):
    def _inner(backend, model_id, messages, creds, timeout=60):
        return {"text": text, "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    return _inner


@patch("judge.gateway.call_backend")
def test_llm_judge_parses_clean_json_response(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 4, "rationale": "Accurate and concise."}')

    result = judge.llm_judge("Paris is the capital of France.", "must be accurate", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"score": 4, "rationale": "Accurate and concise."}


@patch("judge.gateway.call_backend")
def test_llm_judge_parses_json_wrapped_in_prose(mock_call):
    mock_call.side_effect = _fake_call_backend(
        'Sure, here is my evaluation:\n{"score": 5, "rationale": "Perfect."}\nHope that helps!'
    )

    result = judge.llm_judge("some response", "some rubric", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"score": 5, "rationale": "Perfect."}


@patch("judge.gateway.call_backend")
def test_llm_judge_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_backend("I refuse to answer in JSON.")

    result = judge.llm_judge("some response", "some rubric", creds={"openrouter": "sk-or-v1-test"})

    assert result["score"] is None
    assert "Could not parse" in result["rationale"]


@patch("judge.gateway.call_backend")
def test_llm_judge_passes_creds_and_model_through(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 3, "rationale": "ok"}')
    creds = {"openrouter": "sk-or-v1-mykey"}

    judge.llm_judge("resp", "rubric", creds=creds, judge_model="anthropic/claude-haiku-4.5")

    args, _ = mock_call.call_args
    assert args[0] == "openrouter"
    assert args[1] == "anthropic/claude-haiku-4.5"
    assert args[3] is creds


@patch("judge.gateway.call_backend")
def test_llm_judge_uses_backend_default_judge_model(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 3, "rationale": "ok"}')

    judge.llm_judge("resp", "rubric", creds={"vertex": {}}, backend="vertex")

    args, _ = mock_call.call_args
    assert args[0] == "vertex"
    assert args[1] == config.JUDGE_MODELS["vertex"]


@patch("judge.gateway.call_backend")
def test_llm_judge_degrades_on_gateway_error(mock_call):
    mock_call.side_effect = gateway.GatewayError("No Bedrock credentials supplied.")

    result = judge.llm_judge("resp", "rubric", creds={}, backend="bedrock")

    assert result["score"] is None
    assert "Could not parse" in result["rationale"]


def test_llm_judge_unknown_backend_degrades_instead_of_raising():
    result = judge.llm_judge("resp", "rubric", creds={}, backend="azure")
    assert result["score"] is None


@patch("judge.gateway.call_backend")
def test_overall_verdict_routes_to_chosen_backend(mock_call):
    mock_call.side_effect = _fake_call_backend('{"winner": "a", "rationale": "b"}')

    judge.overall_verdict({"a": {"score": 90.0}}, creds={"bedrock": {}}, backend="bedrock")

    args, _ = mock_call.call_args
    assert args[0] == "bedrock"
    assert args[1] == config.JUDGE_MODELS["bedrock"]


@patch("judge.gateway.call_backend")
def test_overall_verdict_returns_winner_and_rationale(mock_call):
    mock_call.side_effect = _fake_call_backend(
        '{"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}'
    )

    result = judge.overall_verdict(
        {"openai/gpt-5": {"score": 95.0, "letter": "A"}, "meta-llama/llama-3.3-70b-instruct": {"score": 70.0, "letter": "C-"}},
        creds={"openrouter": "sk-or-v1-test"},
    )

    assert result == {"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}


@patch("judge.gateway.call_backend")
def test_overall_verdict_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_backend("not json at all")

    result = judge.overall_verdict({"openai/gpt-5": {"score": 90.0, "letter": "A-"}}, creds={"openrouter": "sk-or-v1-test"})

    assert result["winner"] is None
    assert "Could not parse" in result["rationale"]
