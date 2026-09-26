# EvalForge Lite — Finish (PDF/CSV report, Flask app, frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish EvalForge Lite by building `report.py` (PDF + CSV), `app.py` (Flask routes with run history), the frontend (HTML/CSS/JS, "Quiet" visual direction), and `README.md`.

**Architecture:** `report.py` turns a `run_result` dict into PDF bytes or a CSV string. `app.py` wires `catalog`, `policy`, `limiter`, `runner`, `grading`, `judge`, and `report` together behind Flask routes, keeping the last 5 runs per session in memory. The frontend is a single-page vanilla JS app that talks to the JSON API and renders results client-side, including a run-history strip backed by the runs the browser has already fetched this page-load.

**Tech Stack:** Python 3, Flask, `fpdf2`, stdlib `csv`, vanilla HTML/CSS/JS. No new dependencies beyond what's already in `requirements.txt`.

**Spec:** `docs/superpowers/specs/2026-08-29-evalforge-lite-finish/design.md` (this repo).

## Global Constraints

- Do not modify `config.py`, `openrouter.py`, `catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`, `limiter.py`, or `runner.py` — their existing interfaces are the contract this plan builds on.
- No database or file persistence — all server-side state stays in-memory, keyed by the `evalforge_session` cookie.
- No new LLM calls beyond the one `judge.overall_verdict` call `api_run` already needs per run.
- Text models only — no image/audio/vision handling anywhere.
- Never read an OpenRouter API key from server env/config — `api_key` is always the caller-supplied value passed through explicitly.
- Rate limit stays 3 runs per 8 hours per session via `limiter.check_and_record`, unchanged.
- Run history is capped at the 5 most recent runs per session (`collections.deque(maxlen=5)`).
- UI is white background, `"Courier New", Courier, monospace` base font site-wide; provider/grade colors come from data (`providers.json` colors, grade-tier CSS classes), not hardcoded per-provider constants.
- Every test mocks LLM/HTTP calls — no live network calls anywhere in the test suite. Run with `pytest tests/ -v`.
- Error messages returned to the client must never contain the user's API key — scrub with `re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")` → `"[REDACTED]"`.
- Validate `POST /api/run`'s JSON body explicitly (missing/malformed body, missing `api_key`/`test_cases`/`models`) and return `400` before touching any of those fields — never let a malformed request reach an unhandled exception.

---

### Task 1: PDF and CSV report builder (`report.py`)

**Files:**
- Create: `evalforge-lite/report.py`
- Test: `evalforge-lite/tests/test_report.py`

**Interfaces:**
- Consumes: nothing from other modules — pure functions over the `run_result` dict shape below.
- Produces: `report.build_pdf(run_result: dict) -> bytes`, `report.build_csv(run_result: dict) -> str`.
- `run_result` shape (all keys except `results`/`grades`/`verdict` are optional, since `app.py`'s degenerate case and older test fixtures may omit them):
  ```python
  {
      "run_id": str,                # optional
      "created_at": float,          # optional, unix timestamp
      "results": list[dict],        # runner.run() output shape
      "grades": {model_id: {"score": float | None, "letter": str | None, "sentence": str}},
      "stats": {model_id: {"total_cost_usd": float, "avg_latency_ms": float}},  # optional
      "verdict": {"winner": str | None, "rationale": str},
  }
  ```

- [ ] **Step 1: Write the failing tests**

`tests/test_report.py`:
```python
import csv
import io

import report


def _sample_run_result(include_block=False, include_error=False, include_stats=False):
    cell_ok = {
        "model_id": "openai/gpt-5", "blocked": False, "error": None,
        "response_text": "Paris is the capital of France.",
        "latency_ms": 120, "cost_usd": 0.002, "tokens": 30,
        "checks": [{"check": {"type": "contains", "value": "Paris"}, "passed": True}],
        "judge_score": 5, "judge_rationale": "Accurate and concise.",
    }
    cells = {"openai/gpt-5": cell_ok}

    if include_block:
        cells["anthropic/claude-opus-4.5"] = {
            "model_id": "anthropic/claude-opus-4.5", "blocked": True,
            "policy_clause": "No medical advice.", "policy_reason": "asks for diagnosis",
        }
    if include_error:
        cells["meta-llama/llama-4-maverick"] = {
            "model_id": "meta-llama/llama-4-maverick", "blocked": False,
            "error": "rate limited",
        }

    run_result = {
        "run_id": "test-run-1",
        "created_at": 1735689600.0,
        "results": [{"test_case": {"prompt": "What is the capital of France?"}, "cells": cells}],
        "grades": {"openai/gpt-5": {"score": 100.0, "letter": "A+", "sentence": "Strong performer (A+, 100.0/100)."}},
        "verdict": {"winner": "openai/gpt-5", "rationale": "Most accurate and best formatted."},
    }
    if include_stats:
        run_result["stats"] = {"openai/gpt-5": {"total_cost_usd": 0.002, "avg_latency_ms": 120.0}}
    return run_result


def test_generates_valid_pdf_bytes_for_a_run():
    pdf_bytes = report.build_pdf(_sample_run_result())
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_report_includes_blocked_test_cases():
    pdf_bytes = report.build_pdf(_sample_run_result(include_block=True))
    assert pdf_bytes.startswith(b"%PDF")


def test_report_includes_error_cells():
    pdf_bytes = report.build_pdf(_sample_run_result(include_error=True))
    assert pdf_bytes.startswith(b"%PDF")


def test_report_reflects_overall_verdict_and_grades():
    run_result = {"results": [], "grades": {}, "verdict": {"winner": None, "rationale": "No data."}}
    pdf_bytes = report.build_pdf(run_result)
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_includes_stats_when_present():
    pdf_bytes = report.build_pdf(_sample_run_result(include_stats=True))
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_build_csv_returns_string_with_header_row():
    csv_text = report.build_csv(_sample_run_result())
    assert isinstance(csv_text, str)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == [
        "prompt", "model_id", "status", "response_text", "judge_score",
        "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens",
    ]


def test_build_csv_has_one_data_row_per_cell():
    csv_text = report.build_csv(_sample_run_result(include_block=True, include_error=True))
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 4  # header + 3 cells (ok, blocked, error)


def test_build_csv_row_values_for_ok_cell():
    csv_text = report.build_csv(_sample_run_result())
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["model_id"] == "openai/gpt-5"
    assert row["status"] == "ok"
    assert row["judge_score"] == "5"
    assert row["checks_passed"] == "1"
    assert row["checks_total"] == "1"


def test_build_csv_row_values_for_blocked_cell():
    csv_text = report.build_csv(_sample_run_result(include_block=True))
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    blocked_row = next(r for r in rows if r["model_id"] == "anthropic/claude-opus-4.5")
    assert blocked_row["status"] == "blocked"
    assert blocked_row["response_text"] == ""


def test_build_csv_handles_empty_results():
    csv_text = report.build_csv({"results": [], "grades": {}, "verdict": {"winner": None, "rationale": "No data."}})
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 1  # header only
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'report'`

- [ ] **Step 3: Write report.py**

```python
import csv
import io
from datetime import datetime

from fpdf import FPDF

_GRADE_FILL_COLORS = {
    "A": (30, 142, 62),
    "B": (249, 171, 0),
    "C": (249, 171, 0),
    "D": (217, 48, 37),
    "F": (217, 48, 37),
}

_CSV_FIELDS = [
    "prompt", "model_id", "status", "response_text", "judge_score",
    "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens",
]


def _grade_fill(letter):
    if not letter:
        return (200, 200, 200)
    return _GRADE_FILL_COLORS.get(letter[0], (200, 200, 200))


def build_pdf(run_result):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Courier", "B", 16)
    pdf.cell(0, 10, "EvalForge Lite Report", ln=True)

    created_at = run_result.get("created_at")
    if created_at:
        pdf.set_font("Courier", "", 9)
        pdf.set_text_color(120, 120, 120)
        timestamp = datetime.fromtimestamp(created_at).strftime("%Y-%m-%d %H:%M:%S")
        pdf.cell(0, 6, f"Generated {timestamp}", ln=True)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    verdict = run_result.get("verdict") or {}
    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Overall Verdict", ln=True)
    pdf.set_font("Courier", "", 10)
    winner = verdict.get("winner") or "No verdict available"
    pdf.multi_cell(0, 6, f"Winner: {winner}\n{verdict.get('rationale', '')}")
    pdf.ln(4)

    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Leaderboard", ln=True)
    grades = run_result.get("grades") or {}
    stats = run_result.get("stats") or {}
    if not grades:
        pdf.set_font("Courier", "", 10)
        pdf.multi_cell(0, 6, "No grading data available.")
    else:
        col_widths = (60, 25, 25, 35, 35)
        headers = ("Model", "Grade", "Score", "Total Cost", "Avg Latency")
        pdf.set_font("Courier", "B", 9)
        for width, header in zip(col_widths, headers):
            pdf.cell(width, 7, header, border=1)
        pdf.ln()

        pdf.set_font("Courier", "", 9)
        for model_id, grade in grades.items():
            model_stats = stats.get(model_id) or {}
            letter = grade.get("letter")

            pdf.cell(col_widths[0], 7, model_id, border=1)

            fill = _grade_fill(letter)
            pdf.set_fill_color(*fill)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(col_widths[1], 7, letter or "N/A", border=1, fill=True, align="C")
            pdf.set_text_color(0, 0, 0)

            score = grade.get("score")
            pdf.cell(col_widths[2], 7, f"{score}" if score is not None else "N/A", border=1, align="C")

            total_cost = model_stats.get("total_cost_usd")
            pdf.cell(col_widths[3], 7, f"${total_cost:.4f}" if total_cost is not None else "N/A", border=1, align="C")

            avg_latency = model_stats.get("avg_latency_ms")
            pdf.cell(col_widths[4], 7, f"{avg_latency:.0f}ms" if avg_latency is not None else "N/A", border=1, align="C")
            pdf.ln()
    pdf.ln(4)

    pdf.set_font("Courier", "B", 12)
    pdf.cell(0, 8, "Test Cases", ln=True)
    for row in run_result.get("results") or []:
        pdf.set_font("Courier", "B", 10)
        pdf.multi_cell(0, 6, f"Prompt: {row['test_case']['prompt']}")
        pdf.set_font("Courier", "", 9)
        for model_id, cell in row["cells"].items():
            if cell.get("blocked"):
                pdf.multi_cell(0, 5, f"  [{model_id}] BLOCKED - {cell.get('policy_clause')}: {cell.get('policy_reason')}")
            elif cell.get("error"):
                pdf.multi_cell(0, 5, f"  [{model_id}] ERROR: {cell.get('error')}")
            else:
                pdf.multi_cell(0, 5, f"  [{model_id}] {cell.get('response_text')}")
                if cell.get("judge_score") is not None:
                    pdf.multi_cell(0, 5, f"    judge score: {cell['judge_score']}/5 - {cell.get('judge_rationale')}")
        pdf.ln(2)

    return bytes(pdf.output())


def build_csv(run_result):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)

    for row in run_result.get("results") or []:
        prompt = row["test_case"]["prompt"]
        for model_id, cell in row["cells"].items():
            if cell.get("blocked"):
                writer.writerow([
                    prompt, model_id, "blocked", "", "",
                    f"{cell.get('policy_clause')}: {cell.get('policy_reason')}",
                    "", "", "", "", "",
                ])
            elif cell.get("error"):
                writer.writerow([
                    prompt, model_id, "error", cell.get("error"), "",
                    "", "", "", "", "", "",
                ])
            else:
                checks = cell.get("checks") or []
                checks_passed = sum(1 for c in checks if c["passed"])
                writer.writerow([
                    prompt, model_id, "ok", cell.get("response_text"),
                    cell.get("judge_score") if cell.get("judge_score") is not None else "",
                    cell.get("judge_rationale") or "",
                    checks_passed, len(checks),
                    cell.get("cost_usd"), cell.get("latency_ms"), cell.get("tokens"),
                ])

    return buffer.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_report.py -v`
Expected: PASS (10 tests). If fpdf2's `cell()`/`multi_cell()` signature in the installed version rejects a keyword used above (e.g. a `txt=`/`text=` mismatch), check `pip show fpdf2` and adjust the call to match the installed version's signature — the assertions only check for valid, non-empty PDF bytes, not exact layout.

- [ ] **Step 5: Commit**

```bash
git add report.py tests/test_report.py
git commit -m "feat: add fpdf2-based PDF report and CSV export builder"
```

---

### Task 2: Flask app (`app.py`)

**Files:**
- Create: `evalforge-lite/app.py`
- Test: `evalforge-lite/tests/test_app.py`

**Interfaces:**
- Consumes: `catalog.load_catalog() -> dict`, `catalog.frontier_models(dict) -> list[dict]`, `catalog.suggest_family(dict, str) -> list[dict]`, `policy.extract_text(filename, bytes) -> str`, `limiter.check_and_record(session_id, now) -> dict`, `runner.run(test_cases, model_ids, api_key, policy_text=None) -> list[dict]`, `grading.grade_model(judge_scores, rule_check_results, judge_rationales) -> dict`, `judge.overall_verdict(aggregate_stats, api_key) -> dict`, `report.build_pdf(run_result) -> bytes`, `report.build_csv(run_result) -> str`.
- Produces:
  - `app.app` — the Flask instance, used by tests via `app.app.test_client()`.
  - `app._policy_store` — `dict[session_id, str]`.
  - `app._run_history_store` — `dict[session_id, collections.deque]` (maxlen 5, oldest-first).
  - `app._scrub(message: str) -> str`.
  - Routes: `GET /`, `GET /api/catalog`, `GET /api/suggest`, `POST /api/policy`, `POST /api/run`, `GET /api/runs`, `GET /api/report`, `GET /api/report.csv`.
  - `/api/run` response shape (also what's appended to `_run_history_store` and read back for `/api/report*`):
    ```python
    {
        "run_id": str, "created_at": float,
        "results": list[dict], "grades": dict, "stats": dict, "verdict": dict,
    }
    ```

- [ ] **Step 1: Write the failing tests**

`tests/test_app.py`:
```python
import io
import re
from unittest.mock import patch

import app as app_module
import limiter


def _client():
    app_module.app.testing = True
    return app_module.app.test_client()


def setup_function():
    app_module._policy_store.clear()
    app_module._run_history_store.clear()
    limiter._attempts.clear()


def test_index_returns_200():
    resp = _client().get("/")
    assert resp.status_code == 200


def test_index_sets_session_cookie():
    resp = _client().get("/")
    assert "evalforge_session" in resp.headers.get("Set-Cookie", "")


def test_api_catalog_returns_providers_and_frontier():
    resp = _client().get("/api/catalog")
    body = resp.get_json()
    assert "providers" in body
    assert "frontier" in body
    assert len(body["frontier"]) > 0


def test_api_policy_upload_stores_text_for_session():
    client = _client()
    resp = client.post(
        "/api/policy",
        data={"file": (io.BytesIO(b"No medical advice."), "policy.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    session_id = re.search(r"evalforge_session=([^;]+)", resp.headers["Set-Cookie"]).group(1)
    assert app_module._policy_store[session_id] == "No medical advice."


def test_api_run_missing_api_key_returns_400():
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 400
    assert "api_key" in resp.get_json()["error"]


def test_api_run_missing_test_cases_returns_400():
    resp = _client().post("/api/run", json={"api_key": "sk-or-v1-test", "models": ["openai/gpt-5"]})
    assert resp.status_code == 400


def test_api_run_missing_models_returns_400():
    resp = _client().post("/api/run", json={"api_key": "sk-or-v1-test", "test_cases": []})
    assert resp.status_code == 400


def test_api_run_non_json_body_returns_400():
    resp = _client().post("/api/run", data="not json", content_type="text/plain")
    assert resp.status_code == 400


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_returns_results_grades_and_verdict(mock_verdict, mock_run):
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

    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1", "rubric": "be accurate"}],
        "models": ["openai/gpt-5"],
        "api_key": "sk-or-v1-test",
    })

    body = resp.get_json()
    assert resp.status_code == 200
    assert body["verdict"]["winner"] == "openai/gpt-5"
    assert body["grades"]["openai/gpt-5"]["letter"] == "A+"
    assert "run_id" in body
    assert "created_at" in body
    assert body["stats"]["openai/gpt-5"]["total_cost_usd"] == 0.01
    assert body["stats"]["openai/gpt-5"]["avg_latency_ms"] == 10.0


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_blocks_after_three_calls_in_window(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test"}

    for _ in range(3):
        resp = client.post("/api/run", json=payload)
        assert resp.status_code == 200

    fourth = client.post("/api/run", json=payload)
    assert fourth.status_code == 429


def test_api_run_error_response_scrubs_api_key():
    with patch("app.runner.run", side_effect=Exception("failed using key sk-or-v1-abcdefgh12345678")):
        resp = _client().post("/api/run", json={
            "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-abcdefgh12345678",
        })

    assert resp.status_code == 503
    body = resp.get_json()
    assert "sk-or-v1-abcdefgh12345678" not in body["error"]
    assert "[REDACTED]" in body["error"]


def test_api_report_without_a_prior_run_returns_404():
    resp = _client().get("/api/report")
    assert resp.status_code == 404


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_after_a_run_returns_pdf(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    run_resp = client.post("/api/run", json={
        "test_cases": [], "models": [], "api_key": "sk-or-v1-test",
    })
    assert run_resp.status_code == 200

    report_resp = client.get("/api/report")
    assert report_resp.status_code == 200
    assert report_resp.data.startswith(b"%PDF")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_honors_run_id_query_param(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"}

    first_resp = client.post("/api/run", json=payload)
    first_run_id = first_resp.get_json()["run_id"]
    client.post("/api/run", json=payload)  # second run becomes "latest"

    report_resp = client.get(f"/api/report?run_id={first_run_id}")
    assert report_resp.status_code == 200
    assert report_resp.data.startswith(b"%PDF")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_report_csv_after_a_run_returns_csv(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    client.post("/api/run", json={"test_cases": [], "models": [], "api_key": "sk-or-v1-test"})

    resp = client.get("/api/report.csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert resp.data.decode().startswith("prompt,model_id,status")


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_runs_returns_history_newest_first(mock_verdict, mock_run):
    mock_run.return_value = []
    client = _client()
    payload = {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"}

    mock_verdict.return_value = {"winner": "first", "rationale": ""}
    client.post("/api/run", json=payload)

    mock_verdict.return_value = {"winner": "second", "rationale": ""}
    client.post("/api/run", json=payload)

    runs_resp = client.get("/api/runs")
    runs = runs_resp.get_json()["runs"]
    assert runs[0]["winner"] == "second"
    assert runs[1]["winner"] == "first"


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_runs_history_caps_at_five(mock_verdict, mock_run):
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}

    client = _client()
    payload = {"test_cases": [], "models": [], "api_key": "sk-or-v1-test"}

    for _ in range(6):
        limiter._attempts.clear()  # bypass the 3-per-8h limit to exercise the history cap in isolation
        resp = client.post("/api/run", json=payload)
        assert resp.status_code == 200

    runs_resp = client.get("/api/runs")
    assert len(runs_resp.get_json()["runs"]) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write app.py**

```python
import io
import logging
import os
import re
import threading
import time
import uuid
from collections import deque

from flask import Flask, jsonify, render_template, request, send_file

import catalog
import grading
import judge
import limiter
import policy
import report
import runner

app = Flask(__name__)
logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")

_policy_store = {}
_run_history_store = {}
_store_lock = threading.Lock()


def _scrub(message):
    return _SECRET_RE.sub("[REDACTED]", message)


def _error_response(message, status_code):
    resp = jsonify({"error": message})
    resp.status_code = status_code
    return resp


def _get_session_id():
    return request.cookies.get("evalforge_session") or str(uuid.uuid4())


def _with_session_cookie(resp, session_id):
    resp.set_cookie("evalforge_session", session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/")
def index():
    session_id = _get_session_id()
    resp = app.make_response(render_template("index.html"))
    return _with_session_cookie(resp, session_id)


@app.route("/api/catalog")
def api_catalog():
    cat = catalog.load_catalog()
    return jsonify({"providers": cat, "frontier": catalog.frontier_models(cat)})


@app.route("/api/suggest")
def api_suggest():
    model_id = request.args.get("model_id", "")
    cat = catalog.load_catalog()
    return jsonify({"suggestions": catalog.suggest_family(cat, model_id)})


@app.route("/api/policy", methods=["POST"])
def api_policy():
    session_id = _get_session_id()
    uploaded = request.files["file"]
    text = policy.extract_text(uploaded.filename, uploaded.read())
    with _store_lock:
        _policy_store[session_id] = text
    return _with_session_cookie(jsonify({"ok": True}), session_id)


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


def _validate_run_body(body):
    if not isinstance(body, dict):
        return "Request body must be JSON."
    if not body.get("api_key") or not isinstance(body["api_key"], str):
        return "Missing required field: api_key."
    if not isinstance(body.get("test_cases"), list):
        return "Missing required field: test_cases."
    if not isinstance(body.get("models"), list):
        return "Missing required field: models."
    return None


@app.route("/api/run", methods=["POST"])
def api_run():
    session_id = _get_session_id()
    body = request.get_json(silent=True)

    error = _validate_run_body(body)
    if error:
        return _with_session_cookie(_error_response(error, 400), session_id)

    api_key = body["api_key"]
    test_cases = body["test_cases"]
    model_ids = body["models"]

    limit_result = limiter.check_and_record(session_id, time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    with _store_lock:
        policy_text = _policy_store.get(session_id)

    try:
        results = runner.run(test_cases, model_ids, api_key=api_key, policy_text=policy_text)

        agg_stats = _aggregate_stats(results, model_ids)
        grades = {
            model_id: grading.grade_model(
                s["judge_scores"], s["rule_check_results"], s["judge_rationales"]
            )
            for model_id, s in agg_stats.items()
        }
        stats = _cost_latency_stats(agg_stats)

        verdict = {"winner": None, "rationale": "No models were run."}
        if model_ids:
            verdict = judge.overall_verdict(
                {m: {"score": grades[m]["score"], "letter": grades[m]["letter"]} for m in model_ids},
                api_key=api_key,
            )
    except Exception as e:
        logger.exception("run failed")
        return _with_session_cookie(_error_response(_scrub(str(e)), 503), session_id)

    run_result = {
        "run_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "results": results,
        "grades": grades,
        "stats": stats,
        "verdict": verdict,
    }

    with _store_lock:
        history = _run_history_store.setdefault(session_id, deque(maxlen=5))
        history.append(run_result)

    return _with_session_cookie(jsonify(run_result), session_id)


@app.route("/api/runs")
def api_runs():
    session_id = _get_session_id()
    with _store_lock:
        history = list(_run_history_store.get(session_id, []))
    runs = [
        {"run_id": r["run_id"], "created_at": r["created_at"], "winner": r["verdict"].get("winner")}
        for r in reversed(history)
    ]
    return _with_session_cookie(jsonify({"runs": runs}), session_id)


def _find_run(session_id, run_id):
    with _store_lock:
        history = list(_run_history_store.get(session_id, []))
    if not history:
        return None
    if run_id is None:
        return history[-1]
    return next((r for r in history if r["run_id"] == run_id), None)


@app.route("/api/report")
def api_report():
    session_id = _get_session_id()
    run_result = _find_run(session_id, request.args.get("run_id"))
    if not run_result:
        return _with_session_cookie(_error_response("no_run_available", 404), session_id)

    pdf_bytes = report.build_pdf(run_result)
    resp = send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="evalforge-report.pdf",
    )
    return _with_session_cookie(resp, session_id)


@app.route("/api/report.csv")
def api_report_csv():
    session_id = _get_session_id()
    run_result = _find_run(session_id, request.args.get("run_id"))
    if not run_result:
        return _with_session_cookie(_error_response("no_run_available", 404), session_id)

    csv_text = report.build_csv(run_result)
    resp = app.make_response(csv_text)
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = "attachment; filename=evalforge-report.csv"
    return _with_session_cookie(resp, session_id)


def main():
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(port=5060, debug=debug)


if __name__ == "__main__":
    main()
```

Note on `_error_response`'s 404 message: it intentionally uses the same `{"error": "no_run_available"}` body the plan's original sketch used, so a client checking that literal string keeps working.

- [ ] **Step 4: Run tests to verify they pass**

`templates/index.html` doesn't exist yet (Task 3 builds it) — `render_template("index.html")` will fail until then. Create a placeholder first:

```bash
mkdir -p templates
printf '<h1>EvalForge Lite</h1>\n' > templates/index.html
pytest tests/test_app.py -v
```

Expected: PASS (17 tests).

- [ ] **Step 5: Commit**

```bash
git add app.py templates/index.html tests/test_app.py
git commit -m "feat: add Flask app with run history, stats, CSV export, and input validation"
```

---

### Task 3: Frontend (HTML/CSS/JS — "Quiet" visual direction)

**Files:**
- Modify: `evalforge-lite/templates/index.html` (replace placeholder from Task 2)
- Create: `evalforge-lite/static/style.css`
- Create: `evalforge-lite/static/app.js`

**Interfaces:**
- Consumes: `GET /api/catalog`, `GET /api/suggest?model_id=`, `POST /api/policy`, `POST /api/run`, `GET /api/runs`, `GET /api/report?run_id=`, `GET /api/report.csv?run_id=`.
- Produces: no Python interfaces — browser UI only. No automated tests (no JS test runner in this stack) — each step is build-then-manually-verify, matching how `checks.py`/`judge.py`/etc. were TDD'd but the frontend never was in the original plan either.

- [ ] **Step 1: Write templates/index.html**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>EvalForge Lite</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
  <header>
    <h1>EvalForge <span class="accent-brand">Lite</span></h1>
    <p class="tagline">Compare text LLMs across providers with your own OpenRouter key.</p>
  </header>

  <section id="api-key-section" class="card">
    <label for="api-key">OpenRouter API key</label>
    <input type="password" id="api-key" placeholder="sk-or-v1-...">
    <span id="api-key-status" class="status-text"></span>
  </section>

  <section id="catalog-section">
    <h2>Frontier models</h2>
    <div id="frontier-list" class="model-grid"></div>

    <h2>Browse by provider</h2>
    <div id="provider-list"></div>
  </section>

  <section id="policy-section" class="card">
    <h2>Company policy (optional)</h2>
    <input type="file" id="policy-file" accept=".txt,.md,.pdf">
    <span id="policy-status" class="status-text"></span>
  </section>

  <section id="testcase-section">
    <h2>Test cases</h2>
    <div id="testcase-list"></div>
    <button id="add-testcase" class="secondary">+ Add test case</button>
  </section>

  <section id="run-section">
    <button id="run-button">Run comparison</button>
    <span id="run-status" class="status-text"></span>
  </section>

  <section id="history-section" class="card" hidden>
    <h2>Recent runs</h2>
    <div id="history-strip" class="history-strip"></div>
  </section>

  <section id="results-section" hidden>
    <h2>Overall verdict</h2>
    <div id="verdict-banner" class="card"></div>

    <h2>Leaderboard</h2>
    <div id="leaderboard" class="card leaderboard"></div>

    <h2>Results</h2>
    <div id="results-grid"></div>

    <div class="download-row">
      <button id="download-report" class="secondary">Download PDF report</button>
      <button id="download-csv" class="secondary">Download CSV</button>
    </div>
  </section>

  <script src="{{ url_for('static', filename='app.js') }}"></script>
</body>
</html>
```

- [ ] **Step 2: Write static/style.css**

```css
:root {
  --bg: #ffffff;
  --fg: #2a2a2a;
  --muted: #8a8a8a;
  --border: #eeeeee;

  --grade-a: #1e8e3e;
  --grade-b: #f9ab00;
  --grade-c: #f9ab00;
  --grade-d: #d93025;
  --grade-f: #d93025;

  --status-pass: #1e8e3e;
  --status-fail: #d93025;
  --status-blocked: #d93025;
}

* { box-sizing: border-box; }

body {
  background: var(--bg);
  color: var(--fg);
  font-family: "Courier New", Courier, monospace;
  max-width: 880px;
  margin: 0 auto;
  padding: 32px 24px 64px;
  line-height: 1.6;
}

header { margin-bottom: 28px; }
header h1 { font-size: 24px; margin: 0 0 4px; }
.accent-brand { color: #10A37F; }
header .tagline { color: var(--muted); margin: 0; }

h2 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin: 0 0 10px;
}

section { margin-bottom: 28px; }

.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
}

label { display: block; margin-bottom: 6px; font-size: 13px; }

input[type="password"], input[type="text"], textarea {
  font-family: inherit;
  font-size: 13px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  width: 100%;
  max-width: 420px;
  background: #fff;
  color: var(--fg);
}

textarea { max-width: 100%; min-height: 60px; resize: vertical; }

.status-text { display: block; margin-top: 6px; font-size: 12px; color: var(--muted); }

button {
  font-family: inherit;
  font-size: 13px;
  background: var(--fg);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 9px 18px;
  cursor: pointer;
}

button:hover { opacity: 0.85; }
button.secondary { background: #fff; color: var(--fg); border: 1px solid var(--border); }

.model-grid { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }

.model-badge {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  background: #fff;
  transition: background 0.15s, color 0.15s;
}

.provider-block { margin-bottom: 16px; }
.provider-block h3 { font-size: 13px; margin: 0 0 4px; }
.provider-blurb { color: var(--muted); font-size: 12px; margin: 0 0 8px; }

.testcase-row {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.history-strip { display: flex; flex-wrap: wrap; gap: 8px; }
.history-tab {
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
  background: #fff;
  color: var(--muted);
}
.history-tab.active { color: var(--fg); border-color: var(--fg); font-weight: bold; }

.leaderboard { padding: 0; overflow: hidden; }
.leaderboard-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.leaderboard-row:last-child { border-bottom: none; }
.leaderboard-model { font-weight: bold; }
.leaderboard-meta { color: var(--muted); font-size: 11px; }
.leaderboard-sentence { color: var(--muted); font-size: 12px; flex-basis: 100%; margin-top: 2px; }

.grade-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 6px;
  color: #fff;
  font-weight: bold;
  font-size: 12px;
}

.grade-a { background: var(--grade-a); }
.grade-b { background: var(--grade-b); }
.grade-c { background: var(--grade-c); }
.grade-d { background: var(--grade-d); }
.grade-f { background: var(--grade-f); }

.status-pass { color: var(--status-pass); }
.status-fail { color: var(--status-fail); }
.status-blocked {
  display: inline-block;
  color: #fff;
  background: var(--status-blocked);
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
}

.results-cell {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  margin-bottom: 10px;
  font-size: 13px;
}

.download-row { display: flex; gap: 10px; margin-top: 16px; }
```

- [ ] **Step 3: Write static/app.js**

```javascript
const state = {
  catalog: null,
  testCases: [],
  selectedModels: new Set(),
  runs: [],       // full /api/run responses seen this page load, oldest first
  activeRunId: null,
};

function apiKey() {
  return document.getElementById("api-key").value.trim();
}

function letterToClass(letter) {
  if (!letter) return "";
  return `grade-${letter[0].toLowerCase()}`;
}

async function loadCatalog() {
  const resp = await fetch("/api/catalog");
  const data = await resp.json();
  state.catalog = data;
  renderFrontier(data.frontier);
  renderProviders(data.providers);
}

function renderFrontier(frontier) {
  const container = document.getElementById("frontier-list");
  container.innerHTML = "";
  frontier.forEach((model) => {
    const color = state.catalog.providers[model.provider].color;
    container.appendChild(modelBadge(model, color));
  });
}

function renderProviders(providers) {
  const container = document.getElementById("provider-list");
  container.innerHTML = "";
  Object.entries(providers).forEach(([providerId, provider]) => {
    const block = document.createElement("div");
    block.className = "provider-block";
    block.innerHTML = `<h3 style="color:${provider.color}">${providerId}</h3><p class="provider-blurb">${provider.blurb}</p>`;
    const grid = document.createElement("div");
    grid.className = "model-grid";
    provider.models.forEach((model) => grid.appendChild(modelBadge(model, provider.color)));
    block.appendChild(grid);
    container.appendChild(block);
  });
}

function modelBadge(model, color) {
  const el = document.createElement("div");
  el.className = "model-badge";
  el.textContent = model.name;
  el.style.borderColor = color;
  el.style.color = color;
  el.dataset.modelId = model.id;
  el.addEventListener("click", () => toggleModel(model.id, el, color));
  return el;
}

async function toggleModel(modelId, el, color) {
  if (state.selectedModels.has(modelId)) {
    state.selectedModels.delete(modelId);
    el.style.background = "#fff";
    el.style.color = color;
  } else {
    state.selectedModels.add(modelId);
    el.style.background = color;
    el.style.color = "#fff";
    const resp = await fetch(`/api/suggest?model_id=${encodeURIComponent(modelId)}`);
    const data = await resp.json();
    if (data.suggestions.length) {
      const names = data.suggestions.map((m) => m.name).join(", ");
      document.getElementById("run-status").textContent = `Also consider: ${names}`;
    }
  }
}

function addTestCase() {
  state.testCases.push({ prompt: "", rubric: "" });
  renderTestCases();
}

function renderTestCases() {
  const container = document.getElementById("testcase-list");
  container.innerHTML = "";
  state.testCases.forEach((tc, i) => {
    const row = document.createElement("div");
    row.className = "testcase-row";
    row.innerHTML = `
      <textarea placeholder="Prompt" data-idx="${i}" data-field="prompt">${tc.prompt}</textarea>
      <input type="text" placeholder="Rubric (optional)" data-idx="${i}" data-field="rubric" value="${tc.rubric}">
    `;
    container.appendChild(row);
  });
  container.querySelectorAll("[data-field]").forEach((el) => {
    el.addEventListener("input", (e) => {
      const idx = Number(e.target.dataset.idx);
      state.testCases[idx][e.target.dataset.field] = e.target.value;
    });
  });
}

async function uploadPolicy(file) {
  const formData = new FormData();
  formData.append("file", file);
  const resp = await fetch("/api/policy", { method: "POST", body: formData });
  const data = await resp.json();
  document.getElementById("policy-status").textContent = data.ok ? "Policy loaded." : "Failed to load policy.";
}

async function runComparison() {
  const runStatus = document.getElementById("run-status");
  if (!apiKey()) {
    runStatus.textContent = "Enter your OpenRouter API key first.";
    return;
  }
  if (state.selectedModels.size === 0) {
    runStatus.textContent = "Pick at least one model.";
    return;
  }

  runStatus.textContent = "Running...";
  const resp = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      test_cases: state.testCases,
      models: Array.from(state.selectedModels),
      api_key: apiKey(),
    }),
  });

  if (resp.status === 429) {
    const data = await resp.json();
    const resetDate = new Date(data.reset_at * 1000);
    runStatus.textContent = `Rate limit reached. Try again after ${resetDate.toLocaleTimeString()}.`;
    return;
  }

  if (!resp.ok) {
    const data = await resp.json();
    runStatus.textContent = `Error: ${data.error}`;
    return;
  }

  const data = await resp.json();
  runStatus.textContent = "";
  state.runs.push(data);
  showRun(data.run_id);
}

function renderHistory() {
  const section = document.getElementById("history-section");
  const strip = document.getElementById("history-strip");
  if (state.runs.length === 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  strip.innerHTML = "";
  [...state.runs].reverse().forEach((run) => {
    const tab = document.createElement("div");
    tab.className = "history-tab" + (run.run_id === state.activeRunId ? " active" : "");
    const time = new Date(run.created_at * 1000).toLocaleTimeString();
    tab.textContent = run.verdict.winner ? `${time} · ${run.verdict.winner}` : time;
    tab.addEventListener("click", () => showRun(run.run_id));
    strip.appendChild(tab);
  });
}

function showRun(runId) {
  const run = state.runs.find((r) => r.run_id === runId);
  if (!run) return;
  state.activeRunId = runId;
  renderHistory();
  renderResults(run);
}

function renderResults(data) {
  document.getElementById("results-section").hidden = false;

  const verdictEl = document.getElementById("verdict-banner");
  verdictEl.textContent = data.verdict.winner
    ? `${data.verdict.winner}: ${data.verdict.rationale}`
    : "No verdict available.";

  const leaderboardEl = document.getElementById("leaderboard");
  leaderboardEl.innerHTML = "";
  Object.entries(data.grades).forEach(([modelId, grade]) => {
    const modelStats = (data.stats && data.stats[modelId]) || {};
    const row = document.createElement("div");
    row.className = "leaderboard-row";
    const gradeClass = letterToClass(grade.letter);
    const metaBits = [];
    if (modelStats.total_cost_usd !== undefined) metaBits.push(`$${modelStats.total_cost_usd.toFixed(4)}`);
    if (modelStats.avg_latency_ms !== undefined) metaBits.push(`${Math.round(modelStats.avg_latency_ms)}ms avg`);
    row.innerHTML = `
      <span class="leaderboard-model">${modelId}</span>
      <span class="grade-badge ${gradeClass}">${grade.letter || "N/A"}</span>
      <span class="leaderboard-meta">${grade.score ?? "N/A"}/100${metaBits.length ? " · " + metaBits.join(" · ") : ""}</span>
      <span class="leaderboard-sentence">${grade.sentence}</span>
    `;
    leaderboardEl.appendChild(row);
  });

  const gridEl = document.getElementById("results-grid");
  gridEl.innerHTML = "";
  data.results.forEach((row) => {
    const promptHeader = document.createElement("h3");
    promptHeader.textContent = row.test_case.prompt;
    gridEl.appendChild(promptHeader);

    Object.entries(row.cells).forEach(([modelId, cell]) => {
      const cellEl = document.createElement("div");
      cellEl.className = "results-cell";
      if (cell.blocked) {
        cellEl.innerHTML = `<span class="status-blocked">[${modelId}] BLOCKED: ${cell.policy_clause} — ${cell.policy_reason}</span>`;
      } else if (cell.error) {
        cellEl.innerHTML = `<span class="status-fail">[${modelId}] ERROR: ${cell.error}</span>`;
      } else {
        cellEl.innerHTML = `<strong>${modelId}</strong><p>${cell.response_text}</p>`;
      }
      gridEl.appendChild(cellEl);
    });
  });
}

function downloadReport() {
  if (!state.activeRunId) return;
  window.location.href = `/api/report?run_id=${encodeURIComponent(state.activeRunId)}`;
}

function downloadCsv() {
  if (!state.activeRunId) return;
  window.location.href = `/api/report.csv?run_id=${encodeURIComponent(state.activeRunId)}`;
}

document.getElementById("add-testcase").addEventListener("click", addTestCase);
document.getElementById("run-button").addEventListener("click", runComparison);
document.getElementById("download-report").addEventListener("click", downloadReport);
document.getElementById("download-csv").addEventListener("click", downloadCsv);
document.getElementById("policy-file").addEventListener("change", (e) => {
  if (e.target.files[0]) uploadPolicy(e.target.files[0]);
});

loadCatalog();
addTestCase();
```

- [ ] **Step 4: Manually verify in browser**

```bash
cd /Users/thejaredchapman/coding_stuff/evalforge-lite
source venv/bin/activate
python app.py
```

Open `http://localhost:5060` and confirm: white background, Courier font throughout, soft rounded cards with hairline borders (no heavy black borders), frontier/provider model badges render in each provider's brand color and invert (fill + white text) on click, adding a test case shows a prompt/rubric row. Then, with a real or throwaway OpenRouter key: run a comparison with 2+ models, confirm the leaderboard shows grade pill + score + cost/latency + sentence per model, run a second comparison and confirm a "Recent runs" strip appears above the results with both runs listed newest-first and clicking an older tab re-renders that run's leaderboard/results, and confirm both "Download PDF report" and "Download CSV" produce files for whichever run is currently selected.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/style.css static/app.js
git commit -m "feat: add Quiet-direction frontend with run history and CSV/PDF export"
```

---

### Task 4: README and end-to-end smoke test

**Files:**
- Create: `evalforge-lite/README.md`

**Interfaces:**
- Consumes: nothing new — documents and verifies the full system built across all tasks (backend modules already in place, plus Tasks 1-3 here).

- [ ] **Step 1: Write README.md**

```markdown
# EvalForge Lite

Compare text LLMs across providers via OpenRouter — bring your own API key.

## Setup

    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # optional: override JUDGE_MODEL

## Run

    python app.py

Open http://localhost:5060, paste your OpenRouter API key (never sent
anywhere but this server, never stored server-side beyond the request),
add test cases, pick models, and run. Set `FLASK_DEBUG=1` before running
if you need Flask's interactive debugger — it's off by default since this
app handles live API keys.

## Test

    pytest tests/ -v

Every LLM/HTTP call is mocked — the suite needs no API key and makes no
network calls.

## Features

- Compare any combination of catalog models on a shared set of prompts,
  each scored by rule-based checks and/or an LLM judge.
- Optional company-policy gate (upload `.txt`/`.md`/`.pdf`) that blocks
  prompts violating the policy before any model is called.
- Leaderboard with letter grades, per-model cost/latency summary, and an
  overall verdict.
- Download results as a PDF report or a CSV for spreadsheet analysis.
- The last 5 runs per browser session stay available to revisit or
  re-download without re-running them.

## Notes

- `data/providers.json` model IDs are illustrative — verify against
  OpenRouter's live `/models` endpoint before relying on them for a real
  demo, since provider catalogs change over time.
- Rate-limited to 3 runs per 8 hours per browser session (in-memory,
  resets on server restart).
- All state (policy text, run history, rate-limit counters) is in-memory
  only, capped at 5 runs per session — nothing is persisted to disk.
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /Users/thejaredchapman/coding_stuff/evalforge-lite
source venv/bin/activate
pytest tests/ -v
```

Expected: all tests across all files pass (backend modules' existing tests plus `test_report.py` and `test_app.py` from this plan).

- [ ] **Step 3: Manual end-to-end smoke test**

```bash
python app.py
```

In the browser: paste a real (or throwaway test) OpenRouter API key, add one test case with a prompt and rubric, select two models from different providers, click Run, confirm the results grid, leaderboard with grades/cost/latency, and verdict banner all populate, run a second comparison to confirm the history strip appears, then download both the PDF and CSV for the older run and confirm they open and reflect that run's data (not the newer one).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add README with setup, run, test, and feature notes"
```

---

## Self-Review Notes

- **Spec coverage:** data model changes (run_id/created_at/stats/history deque) → Task 2; `report.py`'s `build_pdf`/`build_csv` → Task 1; validation/locking/debug-flag fixes → Task 2; "Quiet" visual direction → Task 3; CSV/PDF download wired to the active run → Task 3; README feature notes → Task 4.
- **Type consistency checked:** `run_result` shape (`run_id`, `created_at`, `results`, `grades`, `stats`, `verdict`) is identical across Task 1's `report.py` functions, Task 2's `app.py` construction of it, and Task 3's `app.js` consumption of the `/api/run` response. `_run_history_store`/`_policy_store` names match between Task 2's implementation and its own tests (no leftover `_last_run_store` naming from the superseded original plan).
- **No placeholders:** every step has complete, runnable code; the one explicit escape hatch (Task 1 Step 4's fpdf2 signature note) is a legitimate "verify against the installed library version" instruction, not a content placeholder.
