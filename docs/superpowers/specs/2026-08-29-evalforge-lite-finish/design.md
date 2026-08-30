# EvalForge Lite — Finishing the App (design)

**Status:** approved, ready for implementation planning
**Supersedes for scope:** Tasks 10-13 of `workplace_improvements/docs/superpowers/plans/2026-08-15-evalforge-lite.md` (PDF report, Flask app, frontend, README). Tasks 1-9 (all backend modules through `runner.py`) are already implemented and unchanged by this spec.

## Goal

Finish EvalForge Lite: a PDF/CSV report builder, the Flask app wiring everything together, a polished frontend, and a README — while fixing two real robustness gaps in the original plan's reference code and adding three small, genuinely useful features (cost/latency summary, CSV export, short run history) that reuse data the backend already produces.

## Non-goals

- No changes to `config.py`, `openrouter.py`, `catalog.py`, `checks.py`, `judge.py`, `grading.py`, `policy.py`, `limiter.py`, or `runner.py` — their interfaces are the contract this spec builds on.
- No database or file persistence — still in-memory per process, keyed by the `evalforge_session` cookie.
- No auth beyond the session cookie; no multi-user accounts.
- No new LLM calls beyond what `judge.overall_verdict` already makes once per run.

## Data model changes vs. the original plan

The original plan's `app.py` stored exactly one run per session (`_last_run_store[session_id] = run_result`, overwritten each time) and had no run identity. This spec changes that minimally:

- Each run result gains `run_id` (uuid4 string) and `created_at` (unix timestamp), set by `app.py` right after `runner.run()` returns.
- Each run result gains a `stats` block: `{model_id: {"total_cost_usd": float, "avg_latency_ms": float}}`, computed in the same aggregation pass that already builds `grades` from `runner.run()`'s output — pure arithmetic over `cost_usd`/`latency_ms` fields the runner already returns per cell, no new LLM or HTTP calls.
- `_last_run_store[session_id]` becomes `_run_history_store[session_id]`, a `collections.deque(maxlen=5)` of run results (newest last). Eviction is automatic via `maxlen`.

Full run result shape (what `/api/run` returns and what `report.build_pdf`/CSV consume):

```python
{
    "run_id": str,
    "created_at": float,
    "results": list[dict],       # unchanged: runner.run() output
    "grades": {model_id: {"score": float | None, "letter": str | None, "sentence": str}},
    "stats": {model_id: {"total_cost_usd": float, "avg_latency_ms": float}},
    "verdict": {"winner": str | None, "rationale": str},
}
```

## Module designs

### `report.py` — `build_pdf(run_result: dict) -> bytes`, `build_csv(run_result: dict) -> str`

Signature gains `build_csv` alongside the plan's `build_pdf`; both take the same `run_result` shape above.

**PDF structure** (fpdf2, built-in Courier core font — no font asset needed):
1. Title + `created_at` formatted as a timestamp.
2. Overall verdict paragraph (unchanged from plan).
3. **Leaderboard as an actual table** (fpdf2 `cell()` grid, not `multi_cell` text dump): columns Model / Grade / Score / Total Cost / Avg Latency. Grade cell gets a background fill color matching the letter tier (reuse the same tier→color mapping as the frontend's grade badges: A-tier green, B/C-tier amber, D/F-tier red) via `pdf.set_fill_color()`.
4. Per-test-case breakdown: prompt, then each model's cell — blocked/error/response + judge score, same content as the plan's version, kept as `multi_cell` text since it's inherently variable-length prose.

**CSV structure**: one row per (test case × model) cell, flat, for spreadsheet pivoting. Columns: `prompt, model_id, status (ok/blocked/error), response_text, judge_score, judge_rationale, checks_passed, checks_total, cost_usd, latency_ms, tokens`. A model row for a blocked/errored cell leaves the response/score columns empty and fills `status` accordingly. Built with the stdlib `csv` module writing to a `io.StringIO`, returned as `str`.

Both functions must produce valid output for the degenerate case (`results: []`, `grades: {}`, `stats: {}`) — same smoke-test requirement as the plan's `test_report.py`.

### `app.py` — Flask routes

| Route | Method | Behavior |
|---|---|---|
| `/` | GET | Renders `index.html`, sets session cookie (unchanged from plan). |
| `/api/catalog` | GET | Unchanged from plan. |
| `/api/suggest` | GET | Unchanged from plan. |
| `/api/policy` | POST | Unchanged from plan. |
| `/api/run` | POST | As plan, plus: validates body fields explicitly before use (see Error handling below); computes and attaches `run_id`, `created_at`, `stats`; appends to the session's history deque instead of overwriting. |
| `/api/runs` | GET | **New.** Returns `{"runs": [{"run_id", "created_at", "winner"}]}` for the session's history, newest first — powers the frontend's run-history strip. |
| `/api/report` | GET | As plan, plus optional `?run_id=` query param (default: most recent run in history). 404 if history is empty or `run_id` doesn't match one in it. |
| `/api/report.csv` | GET | **New.** Same lookup semantics as `/api/report`, returns `text/csv` via `build_csv`, `Content-Disposition: attachment`. |

**Error handling — the one real fix over the plan's reference code:** the plan's sketch pulls `body["api_key"]`, `body["test_cases"]`, `body["models"]` before entering any try/except, so a malformed request (missing JSON body, missing field) raises an unhandled exception. With `debug=True` that renders Flask's interactive traceback — a genuine risk since the traceback can include the request body containing the user's API key. Fix: validate `request.get_json(silent=True)` and the three required fields explicitly at the top of `api_run`, returning `400 {"error": "..."}` (no key echoed back) before anything else runs. The existing scrub-on-exception behavior for the `runner.run()` call itself is kept as-is.

**Concurrency — the other fix:** `_policy_store` and `_run_history_store` are plain dicts read/written from request-handling threads (Flask's dev server is threaded). Guard both with a single `threading.Lock()`, mirroring the pattern `limiter.py` already uses. This is a small, contained change (a lock acquired around each dict read/write), not a rearchitecture.

**Debug mode:** `main()` reads `debug = os.environ.get("FLASK_DEBUG") == "1"` (default off) instead of hardcoding `debug=True`, since this app handles live API keys and the interactive debugger should not be on by default.

### Frontend — visual design: "Quiet" hybrid

Approved via visual companion. Base skin: white background, `"Courier New", Courier, monospace` everywhere (per the original plan's constraint), soft rounded cards (`border-radius: 10px`), hairline `1px solid #eee`-style borders instead of heavy black rules, generous padding, no bracket/CLI decoration. The leaderboard is the visual centerpiece of the results view: a rounded card containing one row per model, each row ending in a pill-shaped grade badge (colored fill matching grade tier) — this is where the "scoreboard" idea from option C survives, just softened. Provider/model badges keep colored borders/text in each provider's brand color (from `providers.json`) but on white/near-white fills, not solid color blocks.

Structural changes vs. the plan's `templates/index.html`/`app.js`:
- A **run-history strip** (small row of up to 5 timestamped tabs) appears above the results section once at least one run exists; clicking a tab re-renders the leaderboard/results grid for that run's data (already held client-side from `/api/run`/`/api/runs` responses — no extra fetch needed for runs made in the current page session, but on page load `/api/runs` + per-run detail isn't re-fetched automatically since only the latest run's full detail is needed until a user clicks an older tab, at which point fetch `/api/report`... actually simplest: keep each run's full JSON response in a client-side array as runs are made this page-load; `/api/runs` is only used to know *what's available* if history outlives the page — out of scope to hydrate full old-run detail from `/api/runs` alone, so the history strip only shows full detail for runs made in the current browser tab session. This is a reasonable "lite" limit and matches the app's overall in-memory-only philosophy).
- Leaderboard rows show `stats` (total cost, avg latency) alongside the existing grade badge and sentence.
- Results section footer gets two buttons: "Download PDF report" (existing) and "Download CSV" (new), both hitting the currently-selected run's `run_id`.
- Everything else (API key input, catalog browser, policy upload, test case builder) keeps the plan's structure and behavior, restyled to the Quiet skin.

### `README.md`

Same content shape as the plan's Task 13 draft (setup/run/test/notes), updated to mention CSV export and run history, and the `FLASK_DEBUG` env var.

## Testing

- `tests/test_report.py`: plan's 4 tests (kept) + tests for `build_csv` (valid CSV string, header row present, one data row per cell, degenerate empty-results case) + a test that a PDF's leaderboard table reflects `stats` values (smoke-level: just confirm valid PDF bytes are produced when `stats` is present, matching the existing test style of not parsing PDF content).
- `tests/test_app.py`: plan's tests (adapted to the new response shape — `run_id`/`created_at`/`stats` present in `/api/run`'s response) plus: `/api/runs` returns history after N runs; history caps at 5; `/api/report`/`/api/report.csv` honor `?run_id=`; malformed `/api/run` body (missing `api_key`) returns 400 without raising; concurrent-looking sequential requests don't corrupt `_policy_store`/`_run_history_store` (a direct lock behavior test isn't practical in a single-threaded test client — rely on code review for the locking itself, not a test).
- Frontend: manual verification only, per the original plan (no JS test runner in this stack) — same as Task 12/13's approach.

## Self-review

- Placeholder scan: none found — every section specifies concrete shapes/behavior.
- Internal consistency: `run_result` shape is used identically by `report.py`, `app.py`, and the frontend section above.
- Scope: focused on the 4 remaining files; no changes to already-built modules.
- Ambiguity: history hydration limitation (full detail only for runs made in the current page load) called out explicitly above rather than left implicit.
