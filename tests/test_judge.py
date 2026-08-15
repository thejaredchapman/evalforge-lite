from unittest.mock import patch

import judge


def _fake_call_model(text):
    def _inner(model_id, messages, api_key, timeout=60):
        return {"text": text, "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    return _inner


@patch("judge.openrouter.call_model")
def test_llm_judge_parses_clean_json_response(mock_call):
    mock_call.side_effect = _fake_call_model('{"score": 4, "rationale": "Accurate and concise."}')

    result = judge.llm_judge("Paris is the capital of France.", "must be accurate", api_key="sk-or-v1-test")

    assert result == {"score": 4, "rationale": "Accurate and concise."}


@patch("judge.openrouter.call_model")
def test_llm_judge_parses_json_wrapped_in_prose(mock_call):
    mock_call.side_effect = _fake_call_model(
        'Sure, here is my evaluation:\n{"score": 5, "rationale": "Perfect."}\nHope that helps!'
    )

    result = judge.llm_judge("some response", "some rubric", api_key="sk-or-v1-test")

    assert result == {"score": 5, "rationale": "Perfect."}


@patch("judge.openrouter.call_model")
def test_llm_judge_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_model("I refuse to answer in JSON.")

    result = judge.llm_judge("some response", "some rubric", api_key="sk-or-v1-test")

    assert result["score"] is None
    assert "Could not parse" in result["rationale"]


@patch("judge.openrouter.call_model")
def test_llm_judge_passes_api_key_and_model_through(mock_call):
    mock_call.side_effect = _fake_call_model('{"score": 3, "rationale": "ok"}')

    judge.llm_judge("resp", "rubric", api_key="sk-or-v1-mykey", judge_model="anthropic/claude-haiku-4.5")

    args, kwargs = mock_call.call_args
    assert args[0] == "anthropic/claude-haiku-4.5"
    assert kwargs["api_key"] == "sk-or-v1-mykey"


@patch("judge.openrouter.call_model")
def test_overall_verdict_returns_winner_and_rationale(mock_call):
    mock_call.side_effect = _fake_call_model(
        '{"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}'
    )

    result = judge.overall_verdict(
        {"openai/gpt-5": {"score": 95.0, "letter": "A"}, "meta-llama/llama-3.3-70b-instruct": {"score": 70.0, "letter": "C-"}},
        api_key="sk-or-v1-test",
    )

    assert result == {"winner": "openai/gpt-5", "rationale": "Highest accuracy and cleanest formatting."}


@patch("judge.openrouter.call_model")
def test_overall_verdict_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_model("not json at all")

    result = judge.overall_verdict({"openai/gpt-5": {"score": 90.0, "letter": "A-"}}, api_key="sk-or-v1-test")

    assert result["winner"] is None
    assert "Could not parse" in result["rationale"]
