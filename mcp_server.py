import base64
import re
import time
import uuid
from collections import deque

from mcp.server.mcpserver import MCPServer

import catalog
import grading
import judge
import limiter
import report
import runner

mcp = MCPServer("evalforge-lite")

_SECRET_RE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")
_RATE_LIMIT_KEY = "mcp-server"

_policy_text = None
_run_history = deque(maxlen=5)


def _scrub(message):
    return _SECRET_RE.sub("[REDACTED]", message)


@mcp.tool()
def list_models() -> dict:
    """List every provider and model in the catalog, plus each provider's frontier (flagship) model."""
    cat = catalog.load_catalog()
    return {"providers": cat, "frontier": catalog.frontier_models(cat)}


@mcp.tool()
def suggest_models(model_id: str) -> dict:
    """Suggest sibling models from the same family as the given model id."""
    cat = catalog.load_catalog()
    return {"suggestions": catalog.suggest_family(cat, model_id)}


@mcp.tool()
def set_policy(policy_text: str) -> dict:
    """Set the company policy text used to gate prompts before any model is called."""
    global _policy_text
    _policy_text = policy_text
    return {"ok": True}


def _aggregate_stats(results, model_ids):
    stats = {
        m: {
            "judge_scores": [], "rule_check_results": [], "judge_rationales": [],
            "costs": [], "latencies": [],
        }
        for m in model_ids
    }
    for row in results:
        for model_id, cell in row["cells"].items():
            if cell.get("blocked") or cell.get("error"):
                continue
            if cell.get("judge_score") is not None:
                stats[model_id]["judge_scores"].append(cell["judge_score"])
            if cell.get("judge_rationale"):
                stats[model_id]["judge_rationales"].append(cell["judge_rationale"])
            for check_result in cell.get("checks") or []:
                stats[model_id]["rule_check_results"].append(check_result["passed"])
            stats[model_id]["costs"].append(cell.get("cost_usd", 0.0))
            stats[model_id]["latencies"].append(cell.get("latency_ms", 0))
    return stats


def _cost_latency_stats(agg_stats):
    result = {}
    for model_id, s in agg_stats.items():
        total_cost = sum(s["costs"])
        avg_latency = sum(s["latencies"]) / len(s["latencies"]) if s["latencies"] else 0.0
        result[model_id] = {
            "total_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
        }
    return result


@mcp.tool()
def run_comparison(test_cases: list[dict], models: list[str], api_key: str) -> dict:
    """Run a set of test-case prompts against a set of models, scoring each response.

    Each test case may include an optional "rubric" (scored by an LLM judge) and/or
    "checks" (rule-based checks). Returns per-model grades, cost/latency stats, and an
    overall verdict. Rate-limited to 3 calls per 8 hours.
    """
    if not api_key:
        return {"error": "Missing required field: api_key."}

    limit_result = limiter.check_and_record(_RATE_LIMIT_KEY, time.time())
    if not limit_result["allowed"]:
        return {"error": "rate_limited", "reset_at": limit_result["reset_at"]}

    try:
        results = runner.run(test_cases, models, api_key=api_key, policy_text=_policy_text)

        agg_stats = _aggregate_stats(results, models)
        grades = {
            model_id: grading.grade_model(
                s["judge_scores"], s["rule_check_results"], s["judge_rationales"]
            )
            for model_id, s in agg_stats.items()
        }
        stats = _cost_latency_stats(agg_stats)

        verdict = {"winner": None, "rationale": "No models were run."}
        if models:
            verdict = judge.overall_verdict(
                {m: {"score": grades[m]["score"], "letter": grades[m]["letter"]} for m in models},
                api_key=api_key,
            )
    except Exception as e:
        return {"error": _scrub(str(e))}

    run_result = {
        "run_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "results": results,
        "grades": grades,
        "stats": stats,
        "verdict": verdict,
    }
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
def get_report(run_id: str | None = None) -> dict:
    """Get a PDF report (base64-encoded) for a run. Defaults to the most recent run."""
    run_result = _find_run(run_id)
    if not run_result:
        return {"error": "no_run_available"}
    pdf_bytes = report.build_pdf(run_result)
    return {"pdf_base64": base64.b64encode(pdf_bytes).decode("ascii")}


@mcp.tool()
def get_report_csv(run_id: str | None = None) -> dict:
    """Get a CSV export for a run, one row per (test case x model) cell. Defaults to the most recent run."""
    run_result = _find_run(run_id)
    if not run_result:
        return {"error": "no_run_available"}
    return {"csv": report.build_csv(run_result)}


if __name__ == "__main__":
    mcp.run()
