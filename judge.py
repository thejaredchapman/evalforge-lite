import json
import re

import config
import openrouter

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


def _extract_json(text):
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(match.group(0))


def llm_judge(response_text, rubric, api_key, judge_model=None):
    model = judge_model or config.JUDGE_MODEL
    prompt = JUDGE_PROMPT_TEMPLATE.format(rubric=rubric, response=response_text)

    try:
        result = openrouter.call_model(model, [{"role": "user", "content": prompt}], api_key=api_key)
        parsed = _extract_json(result["text"])
        score = int(parsed["score"])
        rationale = str(parsed["rationale"])
    except (openrouter.OpenRouterError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"score": None, "rationale": "Could not parse judge response."}

    return {"score": score, "rationale": rationale}


def overall_verdict(aggregate_stats, api_key, judge_model=None):
    model = judge_model or config.JUDGE_MODEL
    stats_text = "\n".join(f"- {model_id}: {stats}" for model_id, stats in aggregate_stats.items())
    prompt = VERDICT_PROMPT_TEMPLATE.format(stats=stats_text)

    try:
        result = openrouter.call_model(model, [{"role": "user", "content": prompt}], api_key=api_key)
        parsed = _extract_json(result["text"])
        winner = str(parsed["winner"])
        rationale = str(parsed["rationale"])
    except (openrouter.OpenRouterError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"winner": None, "rationale": "Could not parse verdict response."}

    return {"winner": winner, "rationale": rationale}


def evaluate_prompt(prompt, api_key, judge_model=None):
    """Pre-run feedback on prompt quality (clarity/specificity) — an optional,
    explicitly user-triggered check, not run automatically before every comparison.
    """
    model = judge_model or config.JUDGE_MODEL
    llm_prompt = PROMPT_EVAL_TEMPLATE.format(prompt=prompt)

    try:
        result = openrouter.call_model(model, [{"role": "user", "content": llm_prompt}], api_key=api_key)
        parsed = _extract_json(result["text"])
        score = int(parsed["score"])
        feedback = str(parsed["feedback"])
    except (openrouter.OpenRouterError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {"score": None, "feedback": "Could not evaluate prompt."}

    return {"score": score, "feedback": feedback}
