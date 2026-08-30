# EvalForge Lite — MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an MCP server interface (`mcp_server.py`) onto the same core modules the Flask app uses, with a full unit test suite plus real stdio-transport end-to-end tests, and move the project to Python 3.12 (required by the `mcp` SDK).

**Architecture:** One new file, `mcp_server.py`, using the official `mcp` SDK's `MCPServer` (stdio transport) to expose 7 tools that call straight into `catalog`/`checks`/`judge`/`grading`/`policy`/`limiter`/`runner`/`report` — the exact modules `app.py` already uses. No cookie/session concept: process-level module state stands in for what `app.py` keys by session cookie, since one stdio server process serves exactly one client connection.

**Tech Stack:** Python 3.12, the `mcp` SDK (2.x — `MCPServer`, formerly `FastMCP` in 1.x), `pytest-asyncio` for the end-to-end tests.

**Spec:** `docs/superpowers/specs/2026-08-29-evalforge-lite-mcp-server/design.md` (this repo).

## Global Constraints

- Do not modify `catalog.py`, `checks.py`, `config.py`, `grading.py`, `judge.py`, `limiter.py`, `openrouter.py`, `policy.py`, `runner.py`, `report.py`, or `app.py` — `mcp_server.py` is a new, independent consumer of their existing interfaces.
- Every test — including the end-to-end ones — makes zero live network calls. The existing project-wide rule ("every test mocks LLM/HTTP calls") holds for the new end-to-end suite too: it proves the real stdio/subprocess/schema-validation wiring works, not real OpenRouter connectivity (that's `test_openrouter.py`'s job, and was separately verified live and manually for the Flask app already). Achieve this by only exercising `run_comparison` end-to-end with `test_cases: []` / `models: []` — the same short-circuit `runner.run()`/`judge.overall_verdict` already take when there's nothing to call.
- No session cookies, no HTTP concepts anywhere in `mcp_server.py` — process-level module state only.
- Same rate limit as the web app: 3 runs per 8 hours, via the existing `limiter.check_and_record`, keyed by a fixed constant since one process = one caller.
- Same run-history cap as the web app: 5 most recent runs (`collections.deque(maxlen=5)`).
- API keys never appear in any error text a tool returns — reuse the scrub pattern `re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")` → `"[REDACTED]"`.
- `set_policy` takes plain text only — no PDF/file-upload handling in the MCP interface (that stays a web-app-only concern via `policy.extract_text`).
- Tools return structured `{"error": ...}` dicts for every *expected* failure mode (missing api_key, rate limited, run not found, any exception from `runner.run()`/`judge.overall_verdict`) rather than raising — raising is reserved for genuinely unexpected bugs, where the SDK's own generic `UnexpectedToolError` wrapping is an acceptable fallback (verified: it does not leak the original exception text to the client, only to server-side logs).

---

### Task 1: MCP server core — all 7 tools, full unit test suite

**Files:**
- Create: `evalforge-lite/.python-version`
- Modify: `evalforge-lite/requirements.txt`
- Create: `evalforge-lite/mcp_server.py`
- Test: `evalforge-lite/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `catalog.load_catalog() -> dict`, `catalog.frontier_models(dict) -> list[dict]`, `catalog.suggest_family(dict, str) -> list[dict]`, `limiter.check_and_record(key, now) -> dict`, `runner.run(test_cases, model_ids, api_key, policy_text=None) -> list[dict]`, `grading.grade_model(judge_scores, rule_check_results, judge_rationales) -> dict`, `judge.overall_verdict(aggregate_stats, api_key) -> dict`, `report.build_pdf(run_result) -> bytes`, `report.build_csv(run_result) -> str`.
- Produces: the MCP server instance `mcp_server.mcp`, module state `mcp_server._policy_text`, `mcp_server._run_history` (a `deque`), and 7 plain-Python functions (decorated with `@mcp.tool()`, which — per SDK behavior verified before writing this plan — returns them unchanged, so they're callable directly in tests): `list_models() -> dict`, `suggest_models(model_id: str) -> dict`, `set_policy(policy_text: str) -> dict`, `run_comparison(test_cases: list[dict], models: list[str], api_key: str) -> dict`, `list_runs() -> dict`, `get_report(run_id: str | None = None) -> dict`, `get_report_csv(run_id: str | None = None) -> dict`.
- `run_comparison`'s success return shape (also what's appended to `_run_history`):
  ```python
  {
      "run_id": str, "created_at": float,
      "results": list[dict], "grades": dict, "stats": dict, "verdict": dict,
  }
  ```

- [ ] **Step 1: Pin Python 3.12 and update dependencies**

The `mcp` SDK requires Python 3.10+; this project's venv was 3.9.6.

```bash
cd /Users/thejaredchapman/coding_stuff/evalforge-lite/.claude/worktrees/finish-evalforge-lite
echo "3.12" > .python-version
rm -rf venv
/opt/homebrew/bin/python3.12 -m venv venv
./venv/bin/pip install --upgrade pip
```

Edit `requirements.txt` to:
```
flask
requests
fpdf2
pdfplumber
pytest
mcp[cli]
pytest-asyncio
```

```bash
./venv/bin/pip install -r requirements.txt
pytest tests/ -v
```

Expected: all 106 existing tests still PASS on Python 3.12 before any new code is written. If anything fails here, stop and investigate — it means the Python version bump broke something pre-existing, not the new work.

- [ ] **Step 2: Write the failing tests**

`tests/test_mcp_server.py`:
```python
import base64
from unittest.mock import patch

import limiter
import mcp_server


def setup_function():
    mcp_server._policy_text = None
    mcp_server._run_history.clear()
    limiter._attempts.clear()


def test_list_models_returns_providers_and_frontier():
    result = mcp_server.list_models()
    assert "providers" in result
    assert "frontier" in result
    assert len(result["frontier"]) > 0


def test_suggest_models_returns_family_suggestions():
    result = mcp_server.suggest_models("openai/gpt-5")
    assert "suggestions" in result
    assert any(m["id"] == "openai/gpt-5-mini" for m in result["suggestions"])


def test_set_policy_stores_text():
    result = mcp_server.set_policy("No medical advice.")
    assert result == {"ok": True}
    assert mcp_server._policy_text == "No medical advice."


def test_run_comparison_missing_api_key_returns_error():
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="")
    assert "error" in result
    assert "api_key" in result["error"]


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_returns_results_grades_and_verdict(mock_verdict, mock_run):
    mock_run.return_value = [{
        "test_case": {"prompt": "q1"},
        "cells": {
            "openai/gpt-5": {
                "model_id": "openai/gpt-5", "blocked": False, "error": None,
                "response_text": "answer", "latency_ms": 10, "cost_usd": 0.01, "tokens": 5,
                "checks": [], "judge_score": 5, "judge_rationale": "great",
            }
        },
    }]
    mock_verdict.return_value = {"winner": "openai/gpt-5", "rationale": "best"}

    result = mcp_server.run_comparison(
        test_cases=[{"prompt": "q1", "rubric": "be accurate"}],
        models=["openai/gpt-5"],
        api_key="sk-or-v1-test",
    )

    assert result["verdict"]["winner"] == "openai/gpt-5"
    assert result["grades"]["openai/gpt-5"]["letter"] == "A+"
    assert "run_id" in result
    assert "created_at" in result
    assert result["stats"]["openai/gpt-5"]["total_cost_usd"] == 0.01
    assert result["stats"]["openai/gpt-5"]["avg_latency_ms"] == 10.0


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_blocks_after_three_calls_in_window(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    payload = dict(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="sk-or-v1-test")

    for _ in range(3):
        result = mcp_server.run_comparison(**payload)
        assert "error" not in result

    fourth = mcp_server.run_comparison(**payload)
    assert fourth["error"] == "rate_limited"
    assert "reset_at" in fourth


def test_run_comparison_scrubs_api_key_on_error():
    with patch("mcp_server.runner.run", side_effect=Exception("failed using key sk-or-v1-abcdefgh12345678")):
        result = mcp_server.run_comparison(
            test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"], api_key="sk-or-v1-abcdefgh12345678",
        )
    assert "sk-or-v1-abcdefgh12345678" not in result["error"]
    assert "[REDACTED]" in result["error"]


def test_get_report_without_a_prior_run_returns_error():
    assert mcp_server.get_report() == {"error": "no_run_available"}


def test_get_report_csv_without_a_prior_run_returns_error():
    assert mcp_server.get_report_csv() == {"error": "no_run_available"}


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_after_a_run_returns_pdf_base64(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report()
    pdf_bytes = base64.b64decode(result["pdf_base64"])
    assert pdf_bytes.startswith(b"%PDF")


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_honors_run_id(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    first = mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report(run_id=first["run_id"])
    assert "pdf_base64" in result


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_get_report_csv_after_a_run_returns_csv(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test")

    result = mcp_server.get_report_csv()
    assert result["csv"].startswith("prompt,model_id,status")


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_list_runs_returns_history_newest_first(mock_verdict, mock_run):
    mock_run.return_value = []
    payload = dict(test_cases=[], models=["openai/gpt-5"], api_key="sk-or-v1-test")

    mock_verdict.return_value = {"winner": "first", "rationale": ""}
    mcp_server.run_comparison(**payload)

    mock_verdict.return_value = {"winner": "second", "rationale": ""}
    mcp_server.run_comparison(**payload)

    runs = mcp_server.list_runs()["runs"]
    assert runs[0]["winner"] == "second"
    assert runs[1]["winner"] == "first"


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_history_caps_at_five(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    payload = dict(test_cases=[], models=[], api_key="sk-or-v1-test")

    for _ in range(6):
        limiter._attempts.clear()  # bypass the 3-per-8h limit to exercise the history cap in isolation
        mcp_server.run_comparison(**payload)

    assert len(mcp_server.list_runs()["runs"]) == 5
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server'`

- [ ] **Step 4: Write mcp_server.py**

```python
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
import policy
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
```

Note: `policy` is imported but only used by the web app's `/api/policy` route today — it's not called from `mcp_server.py` itself (policy text arrives as a plain string here, no extraction needed). Remove the unused `import policy` line if your editor/linter flags it; it was left out of the reference above intentionally — **do not add it back**.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (14 tests).

- [ ] **Step 6: Commit**

```bash
git add .python-version requirements.txt mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add MCP server exposing catalog/run/report tools over stdio"
```

---

### Task 2: End-to-end stdio transport tests

**Files:**
- Test: `evalforge-lite/tests/test_mcp_server_e2e.py`

**Interfaces:**
- Consumes: `mcp_server.py` as a subprocess (via `mcp.client.stdio.stdio_client` + `mcp.ClientSession`), started with `sys.executable` (the venv's own Python) so the subprocess has the same installed packages as the test runner.
- Produces: no new interfaces — these tests exercise the real transport/schema-validation layer that Task 1's direct-function-call unit tests bypass.

- [ ] **Step 1: Write the tests**

`tests/test_mcp_server_e2e.py`:
```python
import base64
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

_SERVER_PATH = str(Path(__file__).resolve().parent.parent / "mcp_server.py")


def _parse(result):
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_full_workflow_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            catalog_result = _parse(await session.call_tool("list_models", {}))
            assert len(catalog_result["frontier"]) > 0

            suggest_result = _parse(await session.call_tool("suggest_models", {"model_id": "openai/gpt-5"}))
            assert "suggestions" in suggest_result

            policy_result = _parse(await session.call_tool("set_policy", {"policy_text": "No medical advice."}))
            assert policy_result == {"ok": True}

            # Empty test_cases/models short-circuits runner.run()/judge.overall_verdict entirely
            # (no models to iterate, no verdict call needed) — this is a real end-to-end round
            # trip with zero network calls, matching the project-wide "no live calls in tests" rule.
            run_result = _parse(await session.call_tool(
                "run_comparison", {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"},
            ))
            assert "run_id" in run_result
            run_id = run_result["run_id"]

            runs_result = _parse(await session.call_tool("list_runs", {}))
            assert runs_result["runs"][0]["run_id"] == run_id

            report_result = _parse(await session.call_tool("get_report", {"run_id": run_id}))
            pdf_bytes = base64.b64decode(report_result["pdf_base64"])
            assert pdf_bytes.startswith(b"%PDF")

            csv_result = _parse(await session.call_tool("get_report_csv", {"run_id": run_id}))
            assert csv_result["csv"].startswith("prompt,model_id,status")


@pytest.mark.asyncio
async def test_missing_required_argument_is_rejected_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("suggest_models", {})
            assert result.is_error is True


@pytest.mark.asyncio
async def test_get_report_without_a_prior_run_returns_error_over_real_stdio_transport():
    params = StdioServerParameters(command=sys.executable, args=[_SERVER_PATH])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = _parse(await session.call_tool("get_report", {}))
            assert result == {"error": "no_run_available"}
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/test_mcp_server_e2e.py -v`
Expected: PASS (3 tests). Each test spawns a real subprocess running `mcp_server.py` and talks to it over actual stdio pipes — if a test hangs instead of failing cleanly, check that `mcp_server.py`'s `if __name__ == "__main__": mcp.run()` guard is intact (the subprocess must actually start the server loop when invoked directly).

- [ ] **Step 3: Run the full suite together**

Run: `pytest tests/ -v`
Expected: PASS (123 tests: 106 pre-existing + 14 from Task 1 + 3 from Task 2).

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_server_e2e.py
git commit -m "test: add real stdio-transport end-to-end tests for the MCP server"
```

---

### Task 3: README update and manual verification

**Files:**
- Modify: `evalforge-lite/README.md`

**Interfaces:**
- Consumes: nothing new — documents both interfaces (Flask app, MCP server) built across this plan and the prior "finish" plan.

- [ ] **Step 1: Update README.md**

Replace the file's contents with:

```markdown
# EvalForge Lite

Compare text LLMs across providers via OpenRouter — bring your own API key.
Available as a web app and as an MCP server.

## Setup

    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # optional: override JUDGE_MODEL

Requires Python 3.10+ (the `mcp` package's floor); developed and tested on 3.12.

## Web app

    python app.py

Open http://localhost:5060, paste your OpenRouter API key (never sent
anywhere but this server, never stored server-side beyond the request),
add test cases, pick models, and run. Set `FLASK_DEBUG=1` before running
if you need Flask's interactive debugger — it's off by default since this
app handles live API keys.

## MCP server

    python mcp_server.py

Runs over stdio — add it to an MCP client's config (e.g. Claude Desktop or
Claude Code) pointing at this venv's Python and this file:

```json
{
  "mcpServers": {
    "evalforge-lite": {
      "command": "/absolute/path/to/evalforge-lite/venv/bin/python",
      "args": ["/absolute/path/to/evalforge-lite/mcp_server.py"]
    }
  }
}
```

Exposes 7 tools: `list_models`, `suggest_models`, `set_policy`, `run_comparison`,
`list_runs`, `get_report`, `get_report_csv` — the same functionality as the web
app's API, minus file-upload policy support (`set_policy` takes plain text).
State (policy, run history, rate limit) is per-process, since one stdio
connection is one client.

## Test

    pytest tests/ -v

Every LLM/HTTP call is mocked (or, for the MCP end-to-end tests, exercised
with an empty test-case/model list that never reaches the network) — the
suite needs no API key and makes no network calls.

## Features

- Compare any combination of catalog models on a shared set of prompts,
  each scored by rule-based checks and/or an LLM judge.
- Optional company-policy gate that blocks prompts violating the policy
  before any model is called (upload `.txt`/`.md`/`.pdf` in the web app;
  pass plain text via the `set_policy` MCP tool).
- Leaderboard with letter grades, per-model cost/latency summary, and an
  overall verdict.
- Download results as a PDF report or a CSV for spreadsheet analysis.
- The last 5 runs per session (browser cookie, or MCP server process)
  stay available to revisit or re-download without re-running them.

## Notes

- `data/providers.json` model IDs are illustrative — verify against
  OpenRouter's live `/models` endpoint before relying on them for a real
  demo, since provider catalogs change over time.
- Rate-limited to 3 runs per 8 hours per session (in-memory, resets on
  server restart) in both interfaces.
- All state is in-memory only, capped at 5 runs per session — nothing is
  persisted to disk.
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /Users/thejaredchapman/coding_stuff/evalforge-lite/.claude/worktrees/finish-evalforge-lite
pytest tests/ -v
```

Expected: 123 tests pass.

- [ ] **Step 3: Manual verification of the MCP server**

Run the server and drive it with a short ad-hoc script using the same client SDK the e2e tests use, confirming a real client sees sensible output for a couple of tools:

```bash
python -c "
import asyncio, json, sys
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=['mcp_server.py'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool('list_models', {})
            print(json.loads(result.content[0].text)['frontier'][0])

asyncio.run(main())
"
```

Expected: prints a dict for one frontier model (e.g. `{'id': 'openai/gpt-5', 'name': 'GPT-5', ...}`), confirming the server starts, initializes, and responds correctly outside of the test harness.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the MCP server alongside the web app in README"
```

---

## Self-Review Notes

- **Spec coverage:** environment migration (Task 1 Step 1) → all 7 tools + process-level state (Task 1) → real stdio verification (Task 2) → docs for both interfaces (Task 3). The design doc's "SDK reality check" findings (decorator returns fn unchanged, dict-to-JSON-text conversion, exception-wrapping behavior) are all directly reflected in `mcp_server.py`'s error-handling design (catch-and-return-dict, not raise) and in how unit tests call tools directly rather than through `call_tool`.
- **Type consistency checked:** `run_comparison`'s return shape (`run_id`, `created_at`, `results`, `grades`, `stats`, `verdict`) matches exactly what `get_report`/`get_report_csv`/`list_runs` read from `_run_history`, and matches the equivalent shape in the Flask app's `run_result` (same field names) even though the two implementations don't share code — verified field-by-field against `app.py` while writing this plan.
- **No placeholders:** every step has complete, runnable code. The README's example JSON config path (`/absolute/path/to/evalforge-lite/...`) is expected end-user substitution in documentation, not a plan placeholder.
- **One deviation from the approved design doc, made and justified in Global Constraints above:** the design doc suggested the end-to-end `run_comparison` test use "an obviously invalid API key exactly as the manual Flask smoke test already did" — that would make a real, unmocked network call from inside the test suite, contradicting this project's own hard rule (enforced in every other test file) that the suite makes zero live network calls. Task 2 instead exercises `run_comparison` with empty `test_cases`/`models`, which takes the same real code path through the MCP tool, JSON serialization, and history/report machinery, without ever reaching `runner.run()`'s per-model network call.
