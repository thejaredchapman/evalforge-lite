import base64
import time
import uuid
from collections import deque

from mcp.server.mcpserver import MCPServer

import analysis
import availability
import catalog
import config
import costs
import gateway
import grading
import judge
import limiter
import report
import runner
import scrub

mcp = MCPServer("evalforge-lite")

_RATE_LIMIT_KEY = "mcp-server"
_EVALUATE_RATE_LIMIT_KEY = "mcp-server:evaluate"


def _server_cap_refusal(held, targets, judge_backend):
    """Refusal dict when this call needs a server-held backend and the shared daily cap is spent, else None."""
    if not set(held) & gateway.backends_used(targets, judge_backend):
        return None
    result = limiter.check_and_record_server_key(time.time())
    if result["allowed"]:
        return None
    return {"error": "rate_limited", "reset_at": result["reset_at"], "message": limiter.SERVER_CAP_MESSAGE}

_policy_text = None
_run_history = deque(maxlen=5)


@mcp.tool()
def list_models() -> dict:
    """List every provider and model in the catalog, plus each provider's frontier (flagship) model.

    Each model carries a `reasoning` flag (supports extended reasoning) and a `tags` list of
    curated need/industry tag ids; `tags` in the result gives their labels, one-line "why"
    explanations and the date they were verified. Tags are a starting point, not benchmarks.
    """
    cat = catalog.load_catalog()
    return {"providers": cat, "frontier": catalog.frontier_models(cat), "tags": catalog.load_tags()}


@mcp.tool()
def suggest_models(model_id: str) -> dict:
    """Suggest sibling models from the same family as the given model id."""
    cat = catalog.load_catalog()
    return {"suggestions": catalog.suggest_family(cat, model_id)}


@mcp.tool()
def list_availability() -> dict:
    """Return the current model-availability snapshot: live OpenRouter listing status
    (refreshed at most every 6 hours) plus curated Bedrock/Vertex/Foundry region coverage.
    """
    return availability.snapshot()


@mcp.tool()
def set_policy(policy_text: str) -> dict:
    """Set the company policy text used to gate prompts before any model is called."""
    global _policy_text
    _policy_text = policy_text
    return {"ok": True}


@mcp.tool()
def evaluate_prompt(prompt: str, api_key: str = "", creds: dict | None = None,
                    judge_backend: str = "openrouter") -> dict:
    """Get pre-run feedback on a prompt's clarity/specificity before running a comparison.

    An explicit, separately-triggered LLM call (uses your credentials) — not run
    automatically as part of run_comparison. Rate-limited independently from
    run_comparison's 3-per-8h budget. Pass `creds` as {"openrouter"?: str,
    "bedrock"?: {...}, "vertex"?: {...}, "foundry"?: {...}} to use Amazon Bedrock,
    Google Vertex AI, or Microsoft Foundry; a bare `api_key` is treated as an
    OpenRouter key. `judge_backend` picks which backend runs the evaluation.
    If the operator has set server-side keys for a backend (see README "Server-side keys"), those are used for it automatically and creds for it are not needed.
    """
    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(creds, api_key))
    if raw_creds is None:
        return {"error": "Missing required field: creds (or api_key)."}
    if judge_backend not in gateway.BACKENDS:
        return {"error": "Invalid judge_backend."}
    prepared, creds_error = gateway.check_run_creds(raw_creds, [], judge_backend)
    if creds_error:
        return {"error": scrub.scrub(creds_error, raw_creds)}
    limit_result = limiter.check_and_record(_EVALUATE_RATE_LIMIT_KEY, time.time())
    if not limit_result["allowed"]:
        return {"error": "rate_limited", "reset_at": limit_result["reset_at"]}
    refusal = _server_cap_refusal(held, [], judge_backend)
    if refusal:
        return refusal
    return judge.evaluate_prompt(prompt, creds=prepared, backend=judge_backend)


@mcp.tool()
def run_comparison(test_cases: list[dict], models: list[str], api_key: str = "", creds: dict | None = None,
                   judge_backend: str = "openrouter", priority: str = "balanced", repeats: int = 1) -> dict:
    """Run a set of test-case prompts against a set of models, scoring each response.

    Each test case may include an optional "rubric" (scored by an LLM judge) and/or
    "checks" (rule-based checks). Returns per-model grades, cost/latency stats, and an
    overall verdict. Rate-limited to 3 calls per 8 hours.
    Models are "<catalog id>" (OpenRouter) or "<catalog id>@bedrock" / "<catalog id>@vertex" /
    "<catalog id>@foundry"; pass matching creds ({"openrouter"?, "bedrock"?, "vertex"?, "foundry"?})
    or a bare OpenRouter api_key.
    judge_backend picks which backend runs the judge and policy gate.
    At most 4 models. priority (balanced|quality|fastest|cheapest) ranks the results;
    repeats (1-3) re-sends each prompt for timing accuracy. Returns suggestions (same
    provider and backend only), advice, ranking, and best_for_priority, plus a per-run
    `cost` total and, per cell, an `evaluation` (answered/quality/instruction_following/
    completeness/helpfulness/safety scores, strengths, weaknesses, reasoning, overall).
    If the operator has set server-side keys for a backend (see README "Server-side keys"), those are used for it automatically and creds for it are not needed.
    """
    if not isinstance(models, list) or any(not isinstance(m, str) or not m.strip() for m in models):
        return {"error": "Model ids must be non-empty strings."}
    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(creds, api_key))
    if raw_creds is None:
        return {"error": "Missing required field: creds (or api_key)."}
    if judge_backend not in gateway.BACKENDS:
        return {"error": "Invalid judge_backend."}
    if len(models) > config.MAX_MODELS:
        return {"error": f"Pick at most {config.MAX_MODELS} models."}
    if priority not in grading.PRIORITY_WEIGHTS:
        return {"error": "Invalid priority."}
    if type(repeats) is not int or repeats not in (1, 2, 3):
        return {"error": "repeats must be 1, 2, or 3."}
    prepared, creds_error = gateway.check_run_creds(raw_creds, models, judge_backend)
    if creds_error:
        return {"error": scrub.scrub(creds_error, raw_creds)}

    limit_result = limiter.check_and_record(_RATE_LIMIT_KEY, time.time())
    if not limit_result["allowed"]:
        return {"error": "rate_limited", "reset_at": limit_result["reset_at"]}
    refusal = _server_cap_refusal(held, models, judge_backend)
    if refusal:
        return refusal

    try:
        meter = costs.CostMeter()
        results = runner.run(test_cases, models, creds=prepared, policy_text=_policy_text,
                             judge_backend=judge_backend, repeats=repeats, meter=meter)
        run_result = analysis.build_run_result(results, models, prepared, judge_backend, meter=meter)
    except Exception as e:
        return {"error": scrub.scrub(str(e), raw_creds)}

    run_result = {"run_id": str(uuid.uuid4()), "created_at": time.time(), **run_result}
    run_result["priority"] = priority
    run_result["ranking"] = grading.rank_targets(run_result["grades"], run_result["stats"], priority)
    run_result["best_for_priority"] = run_result["ranking"][0] if run_result["ranking"] else None
    _run_history.append(run_result)
    return run_result


@mcp.tool()
def list_runs() -> dict:
    """List metadata for the 5 most recent runs, newest first."""
    runs = [
        {"run_id": r["run_id"], "created_at": r["created_at"], "winner": r["verdict"].get("winner")}
        for r in reversed(_run_history)
    ]
    return {"runs": runs}


def _find_run(run_id):
    if not _run_history:
        return None
    if run_id is None:
        return _run_history[-1]
    return next((r for r in _run_history if r["run_id"] == run_id), None)


@mcp.tool()
def get_report(run_id: str | None = None, priority: str | None = None) -> dict:
    """Get a PDF report (base64-encoded) for a run. Defaults to the most recent run.

    priority (balanced|quality|fastest|cheapest), if given, overrides the priority the
    run was made with for the report's priority/best-pick line; otherwise the run's own
    priority (from run_comparison) is used.
    """
    run_result = _find_run(run_id)
    if not run_result:
        return {"error": "no_run_available"}
    if priority is not None and priority not in grading.PRIORITY_WEIGHTS:
        return {"error": "Invalid priority."}
    effective_priority = priority if priority is not None else run_result.get("priority")
    pdf_bytes = report.build_pdf(run_result, priority=effective_priority)
    return {"pdf_base64": base64.b64encode(pdf_bytes).decode("ascii")}


@mcp.tool()
def get_report_csv(run_id: str | None = None) -> dict:
    """Get a CSV export for a run, one row per (test case x model) cell. Defaults to the most recent run."""
    run_result = _find_run(run_id)
    if not run_result:
        return {"error": "no_run_available"}
    return {"csv": report.build_csv(run_result)}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
