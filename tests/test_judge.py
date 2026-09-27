from unittest.mock import patch

import pytest

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


@patch("judge.gateway.call_backend")
def test_evaluate_prompt_parses_clean_json_response(mock_call):
    mock_call.side_effect = _fake_call_backend(
        '{"score": 2, "feedback": "Too vague — specify the desired output format and length."}'
    )

    result = judge.evaluate_prompt("Tell me about dogs", creds={"openrouter": "sk-or-v1-test"})

    assert result == {
        "score": 2, "feedback": "Too vague — specify the desired output format and length.",
    }


@patch("judge.gateway.call_backend")
def test_evaluate_prompt_fallback_on_malformed_response(mock_call):
    mock_call.side_effect = _fake_call_backend("not json at all")

    result = judge.evaluate_prompt("some prompt", creds={"openrouter": "sk-or-v1-test"})

    assert result["score"] is None
    assert "Could not evaluate" in result["feedback"]


@patch("judge.gateway.call_backend")
def test_evaluate_prompt_fallback_on_gateway_error(mock_call):
    mock_call.side_effect = gateway.GatewayError("No Vertex AI credentials supplied.")

    result = judge.evaluate_prompt("some prompt", creds={}, backend="vertex")

    assert result["score"] is None
    assert "Could not evaluate" in result["feedback"]


@patch("judge.gateway.call_backend")
def test_evaluate_prompt_passes_creds_backend_and_model_through(mock_call):
    mock_call.side_effect = _fake_call_backend('{"score": 4, "feedback": "Clear and specific."}')
    creds = {"bedrock": {"region": "us-east-1", "api_key": "ABSKexample"}}

    judge.evaluate_prompt("some prompt", creds=creds, backend="bedrock")

    args, _ = mock_call.call_args
    assert args[0] == "bedrock"
    assert args[1] == config.JUDGE_MODELS["bedrock"]
    assert args[3] is creds


def test_evaluate_prompt_unknown_backend_degrades_instead_of_raising():
    result = judge.evaluate_prompt("some prompt", creds={}, backend="azure")
    assert result["score"] is None


_SUMMARY = {
    "models": {"anthropic/claude-sonnet-4.5": {"quality": 80, "response_time": 20, "throughput": 30, "cost_efficiency": 50}},
    "suggestions": {"anthropic/claude-sonnet-4.5": {"model_id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5",
                                                     "reason_code": "latency"}},
}


@patch("judge.gateway.call_backend")
def test_explain_recommendations_returns_advice(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "Sonnet was slow; Claude Haiku 4.5 should respond faster."}')
    text = judge.explain_recommendations(_SUMMARY, creds={"openrouter": "sk-or-v1-test"})
    assert text == "Sonnet was slow; Claude Haiku 4.5 should respond faster."
    prompt = mock_call.call_args[0][2][0]["content"]
    assert "Claude Haiku 4.5" in prompt and "anthropic/claude-sonnet-4.5" in prompt


@patch("judge.gateway.call_backend")
def test_explain_recommendations_rejects_disallowed_models(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "Try GPT-5 instead."}')
    assert judge.explain_recommendations(_SUMMARY, creds={}, disallowed_terms=["GPT-5", "openai/gpt-5"]) == ""


@patch("judge.gateway.call_backend", side_effect=gateway.GatewayError("down"))
def test_explain_recommendations_fails_soft(mock_call):
    assert judge.explain_recommendations(_SUMMARY, creds={}) == ""


@patch("judge.gateway.call_backend")
def test_explain_recommendations_unparseable_is_empty(mock_call):
    mock_call.side_effect = _fake_call_backend("no json here")
    assert judge.explain_recommendations(_SUMMARY, creds={}) == ""


@patch("judge.gateway.call_backend")
def test_explain_recommendations_allows_longer_allowed_name_containing_disallowed(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "GPT-5 Mini was fastest."}')
    assert judge.explain_recommendations(_SUMMARY, creds={}, disallowed_terms=["GPT-5", "openai/gpt-5"],
                                         allowed_terms=["GPT-5 Mini", "openai/gpt-5-mini"]) == "GPT-5 Mini was fastest."


@patch("judge.gateway.call_backend")
def test_explain_recommendations_blocks_shorter_disallowed_name_next_to_allowed(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "GPT-5 Mini was fast, but GPT-5 would be better."}')
    assert judge.explain_recommendations(_SUMMARY, creds={}, disallowed_terms=["GPT-5", "openai/gpt-5"],
                                         allowed_terms=["GPT-5 Mini", "openai/gpt-5-mini"]) == ""


@pytest.mark.parametrize("bad_summary", [
    None,
    {"models": {}, "suggestions": {"x": {"model_id": "y", "name": "z"}}},
    {"models": "not a dict", "suggestions": {}},
])
@patch("judge.gateway.call_backend")
def test_explain_recommendations_malformed_summary_is_empty(mock_call, bad_summary):
    assert judge.explain_recommendations(bad_summary, creds={}) == ""
    mock_call.assert_not_called()


@patch("judge.gateway.call_backend")
def test_explain_recommendations_word_boundary_ignores_substring_match(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "This metadata field is unaffected by the change."}')
    assert judge.explain_recommendations(_SUMMARY, creds={}, disallowed_terms=["Meta"]) == (
        "This metadata field is unaffected by the change."
    )


@patch("judge.gateway.call_backend")
def test_explain_recommendations_word_boundary_blocks_whole_word(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "Sonnet is slow; consider Claude or DeepSeek instead."}')
    assert judge.explain_recommendations(
        _SUMMARY, creds={}, disallowed_terms=["Claude", "DeepSeek"],
    ) == ""
