import io
from unittest.mock import patch

from fpdf import FPDF

import config
import policy


def _fake_call_backend(text):
    def _inner(backend, model_id, messages, creds, timeout=60):
        return {"text": text, "latency_ms": 5, "cost_usd": 0.0, "tokens": 10}
    return _inner


def test_extracts_text_from_txt_upload():
    text = policy.extract_text("policy.txt", b"No medical advice may be requested.")
    assert text == "No medical advice may be requested."


def test_extracts_text_from_pdf_upload():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", size=12)
    pdf.cell(0, 10, "No medical advice may be requested.")
    pdf_bytes = bytes(pdf.output())

    text = policy.extract_text("policy.pdf", pdf_bytes)

    assert "No medical advice" in text


@patch("policy.gateway.call_backend")
def test_allows_compliant_prompt(mock_call):
    mock_call.side_effect = _fake_call_backend('{"violates": false, "clause": "", "reason": "No policy concerns."}')

    result = policy.check_policy("What's the capital of France?", "No medical advice.", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"violates": False, "clause": "", "reason": "No policy concerns."}


@patch("policy.gateway.call_backend")
def test_blocks_violating_prompt_with_clause_and_reason(mock_call):
    mock_call.side_effect = _fake_call_backend(
        '{"violates": true, "clause": "No medical advice may be requested.", "reason": "The prompt asks for a diagnosis."}'
    )

    result = policy.check_policy("Diagnose my symptoms", "No medical advice may be requested.", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["clause"] == "No medical advice may be requested."
    assert "diagnosis" in result["reason"]


@patch("policy.gateway.call_backend")
def test_fails_closed_on_malformed_llm_response(mock_call):
    mock_call.side_effect = _fake_call_backend("not valid json")

    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


@patch("policy.gateway.call_backend")
def test_fails_closed_on_llm_call_error(mock_call):
    import openrouter
    mock_call.side_effect = openrouter.OpenRouterError("network down")

    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"})

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


def test_no_policy_loaded_means_no_gating():
    result = policy.check_policy("anything at all", "", creds={"openrouter": "sk-or-v1-test"})

    assert result == {"violates": False, "clause": "", "reason": ""}


def test_fails_closed_when_judge_backend_has_no_creds():
    result = policy.check_policy("some prompt", "some policy", creds={"openrouter": "sk-or-v1-test"}, backend="bedrock")

    assert result["violates"] is True
    assert result["reason"] == "Could not verify policy compliance."


def test_fails_closed_on_unknown_backend():
    result = policy.check_policy("some prompt", "some policy", creds={}, backend="azure")

    assert result["violates"] is True


@patch("policy.gateway.call_backend")
def test_routes_policy_check_to_chosen_backend(mock_call):
    mock_call.side_effect = _fake_call_backend('{"violates": false, "clause": "", "reason": "ok"}')

    policy.check_policy("p", "some policy", creds={"vertex": {}}, backend="vertex")

    args, _ = mock_call.call_args
    assert args[0] == "vertex"
    assert args[1] == config.JUDGE_MODELS["vertex"]
