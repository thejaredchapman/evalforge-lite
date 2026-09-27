import json
import re

import config
import gateway

JUDGE_PROMPT_TEMPLATE = """You are an expert evaluator. Given a rubric and a model's response, score the response.

Rubric: {rubric}

Response:
{response}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"score": <integer 1-5>, "rationale": "<one sentence>"}}
"""

VERDICT_PROMPT_TEMPLATE = """You are comparing the aggregate performance of several LLMs on a benchmark suite.

Per-model stats:
{stats}

Which model performed best overall? Respond with ONLY a JSON object in this exact shape, no other text:
{{"winner": "<model id>", "rationale": "<two sentences>"}}
"""

PROMPT_EVAL_TEMPLATE = """You are a prompt engineering expert. Evaluate the following prompt for clarity,
specificity, and how likely it is to get a consistent, high-quality response from an LLM.

Prompt:
{prompt}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"score": <integer 1-5>, "feedback": "<one or two sentences of specific, actionable feedback>"}}
"""

EXPLAIN_PROMPT_TEMPLATE = """You are advising a developer who just compared several LLMs.
Using ONLY the data below, write 2-3 plain sentences explaining the trade-offs between the compared
models and why each suggested alternative might fit better. Do not mention any model that is not
listed below.

Compared models (scores 0-100, higher is better):
{models}

Suggested alternatives (same provider and backend as the model they replace):
{suggestions}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"advice": "<2-3 sentences>"}}
"""


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(match.group(0))


def llm_judge(response_text, rubric, creds, backend="openrouter", judge_model=None):
    prompt = JUDGE_PROMPT_TEMPLATE.format(rubric=rubric, response=response_text)

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        parsed = _extract_json(result["text"])
        score = int(parsed["score"])
        rationale = str(parsed["rationale"])
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"score": None, "rationale": "Could not parse judge response."}

    return {"score": score, "rationale": rationale}


def overall_verdict(aggregate_stats, creds, backend="openrouter", judge_model=None):
    stats_text = "\n".join(f"- {model_id}: {stats}" for model_id, stats in aggregate_stats.items())
    prompt = VERDICT_PROMPT_TEMPLATE.format(stats=stats_text)

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        parsed = _extract_json(result["text"])
        winner = str(parsed["winner"])
        rationale = str(parsed["rationale"])
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"winner": None, "rationale": "Could not parse verdict response."}

    return {"winner": winner, "rationale": rationale}


def evaluate_prompt(prompt, creds, backend="openrouter", judge_model=None):
    """Pre-run feedback on prompt quality (clarity/specificity) — an optional,
    explicitly user-triggered check, not run automatically before every comparison.
    """
    llm_prompt = PROMPT_EVAL_TEMPLATE.format(prompt=prompt)

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": llm_prompt}], creds)
        parsed = _extract_json(result["text"])
        score = int(parsed["score"])
        feedback = str(parsed["feedback"])
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"score": None, "feedback": "Could not evaluate prompt."}

    return {"score": score, "feedback": feedback}


def explain_recommendations(summary, creds, backend="openrouter", judge_model=None, disallowed_terms=()):
    models_text = "\n".join(f"- {target}: {scores}" for target, scores in summary.get("models", {}).items())
    suggestion_lines = [
        f"- instead of {target}: {s['name']} ({s['model_id']}), because of {s['reason_code']}"
        for target, s in summary.get("suggestions", {}).items() if s
    ]
    prompt = EXPLAIN_PROMPT_TEMPLATE.format(models=models_text, suggestions="\n".join(suggestion_lines) or "- none")

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        advice = str(_extract_json(result["text"])["advice"]).strip()
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return ""

    lowered = advice.lower()
    if any(term.lower() in lowered for term in disallowed_terms if term):
        return ""
    return advice
