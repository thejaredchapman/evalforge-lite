import io
import json
import re

import pdfplumber

import config
import openrouter

POLICY_PROMPT_TEMPLATE = """You are a compliance checker. Given a company policy and a user's prompt, determine whether the prompt violates the policy.

Policy:
{policy}

Prompt:
{prompt}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"violates": <true or false>, "clause": "<quoted or paraphrased policy clause, empty string if no violation>", "reason": "<one sentence>"}}
"""


def extract_text(filename, file_bytes):
    if filename.lower().endswith(".pdf"):
        parts = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)
    return file_bytes.decode("utf-8")


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(match.group(0))


def check_policy(prompt, policy_text, api_key, judge_model=None):
    if not policy_text:
        return {"violates": False, "clause": "", "reason": ""}

    try:
        model = judge_model or config.JUDGE_MODEL
        llm_prompt = POLICY_PROMPT_TEMPLATE.format(policy=policy_text, prompt=prompt)
        result = openrouter.call_model(model, [{"role": "user", "content": llm_prompt}], api_key=api_key)
        parsed = _extract_json(result["text"])
        violates = bool(parsed["violates"])
        clause = str(parsed.get("clause", ""))
        reason = str(parsed.get("reason", ""))
    except (openrouter.OpenRouterError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"violates": True, "clause": "", "reason": "Could not verify policy compliance."}

    return {"violates": violates, "clause": clause, "reason": reason}
