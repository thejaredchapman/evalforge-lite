# EvalForge Lite — MCP Server (design)

**Status:** approved, ready for implementation planning
**Builds on:** `docs/superpowers/specs/2026-08-29-evalforge-lite-finish/design.md` — this is a second interface onto the same core modules (`catalog`, `checks`, `judge`, `grading`, `policy`, `limiter`, `runner`, `report`), alongside the existing Flask app. No business logic is duplicated.

## Goal

Expose EvalForge Lite's comparison/grading/reporting functionality as an MCP (Model Context Protocol) server, so an agent (not just a human via the browser) can drive it: list models, set a policy, run a comparison, and pull back results/PDF/CSV — with an extensive test suite (unit tests per tool plus real stdio-transport end-to-end tests) and the whole repo made public.

## Environment change

The `mcp` Python SDK requires Python 3.10+; the project's venv was 3.9.6. Resolved by moving the **entire** project (not just the MCP server) to Python 3.12 — single venv, single `requirements.txt`, going forward. The full existing test suite (106 tests) was reverified green on 3.12 before any MCP code was written.

## SDK reality check (verified empirically, not assumed)

The installed `mcp` SDK is 2.x, where `FastMCP` was renamed to `MCPServer` (`from mcp.server.mcpserver import MCPServer`) — most tutorials online reference the old 1.x `FastMCP` name, which no longer resolves. Behavior confirmed by hand before writing the implementation plan:

- `@mcp.tool()` returns the decorated function **unchanged** (it only registers it) — so unit tests can call tool functions directly as plain Python functions, no MCP machinery involved.
- A dict return value from a tool is JSON-serialized into a single `TextContent` block automatically — a caller parses it back with `json.loads`, same mental model as Flask's `jsonify`.
- Parameter type hints (`list[dict]`, `list[str]`, `str | None = None`) become the tool's JSON schema automatically via pydantic — a missing required argument is rejected by the framework itself (`ToolError`, informative message) before the function body ever runs. This means tools don't need to re-implement "is this field present/right shape" checks the way `app.py`'s `_validate_run_body` does — only *semantic* checks that a type hint can't express (e.g. `api_key` being an empty string).
- **Critical finding on error handling:** if a tool function lets an arbitrary exception propagate, `MCPServer` wraps it in a generic `UnexpectedToolError` and the real client only ever sees `isError: true` with the text `"Error executing tool <name>"` — the original exception message (which could contain a scrubbed-or-not API key) is *not* forwarded to the client. It **is**, however, printed with a full traceback to the server's stderr/log — the same trust boundary `app.py`'s `logger.exception("run failed")` already relies on (operator-visible logs vs. client-visible response). This means the framework's default swallowing is a safety net, not a design to lean on: an uncaught exception still gives the caller a useless generic message instead of the specific, actionable error `app.py` returns (e.g. `"rate_limited"` with a `reset_at`, or `"Missing required field: api_key."`). So every tool below catches its own expected failure modes and **returns** a structured `{"error": ...}` dict rather than raising, exactly mirroring `app.py`'s pattern — raising is left only for the genuinely-unexpected case, where the framework's generic wrapping is an acceptable (if uninformative) fallback.

## Architecture

`mcp_server.py` at the repo root (flat, single-responsibility, matching the project's existing style), stdio transport, process-level state (no session cookie concept — one client connection is one process for stdio):

- `_policy_text: str | None` — module-level, set by `set_policy`.
- `_run_history: collections.deque(maxlen=5)` — same 5-run cap as the web app.
- `_RATE_LIMIT_KEY = "mcp-server"` — a fixed key passed to the existing `limiter.check_and_record`, since there's exactly one logical caller per process.

## Tools

All seven mirror the Flask routes one-to-one; where a route depends on an HTTP-only concept (cookies, multipart upload), the MCP tool adapts it to a plain argument:

| Tool | Signature | Notes |
|---|---|---|
| `list_models` | `() -> dict` | `{"providers": ..., "frontier": ...}`, same as `/api/catalog`. |
| `suggest_models` | `(model_id: str) -> dict` | `{"suggestions": [...]}`. |
| `set_policy` | `(policy_text: str) -> dict` | Takes plain text directly — no file upload in MCP, so `policy.extract_text`'s PDF-parsing branch is a web-app-only concern; an MCP caller is expected to already have the policy as text. Returns `{"ok": True}`. |
| `run_comparison` | `(test_cases: list[dict], models: list[str], api_key: str) -> dict` | The core tool. Semantic checks only (type/shape are schema-enforced): non-empty `api_key`. Then rate limit (`{"error": "rate_limited", "reset_at": ...}` if exceeded). Then `runner.run()` + the same grading/stats/verdict aggregation `app.py` does, wrapped in `try/except Exception` → `{"error": scrub(str(e))}` on failure. On success, returns the full `run_result` (`run_id`, `created_at`, `results`, `grades`, `stats`, `verdict`) and appends it to `_run_history`. |
| `list_runs` | `() -> dict` | `{"runs": [{"run_id", "created_at", "winner"}, ...]}`, newest first — same shape as `/api/runs`. |
| `get_report` | `(run_id: str \| None = None) -> dict` | `{"pdf_base64": "..."}` via `report.build_pdf` + `base64.b64encode`, or `{"error": "no_run_available"}` — same lookup semantics (`run_id=None` → latest) and same error string as `/api/report`. |
| `get_report_csv` | `(run_id: str \| None = None) -> dict` | `{"csv": "..."}` via `report.build_csv`, or `{"error": "no_run_available"}`. |

Shared helpers `_scrub`, `_find_run(run_id)`, `_aggregate_stats`, `_cost_latency_stats` are re-implemented in `mcp_server.py` rather than imported from `app.py` — `app.py`'s versions are cookie/session-shaped (take a `session_id`), and duplicating ~15 lines of pure-dict-munging logic is simpler and clearer than threading a fake session id through Flask's module just to reuse it. Both modules import the same underlying `catalog`/`checks`/`judge`/`grading`/`policy`/`limiter`/`runner`/`report` — that's where the real logic dedup already lives.

## Testing

Two files, matching the "unit + one real stdio round-trip" depth agreed on:

- `tests/test_mcp_server.py` — unit tests calling tool functions **directly** (they're plain functions per the SDK behavior above), mocking `openrouter.call_model`/`judge.overall_verdict` exactly like `test_app.py` does. Covers: happy path for each tool, `run_comparison`'s empty-api_key/rate-limit/history-cap/key-scrubbing behavior (parity with `test_app.py`'s equivalent cases), `get_report`/`get_report_csv` honoring `run_id` and the no-run-available case.
- `tests/test_mcp_server_e2e.py` — a handful of `pytest-asyncio` tests that launch `mcp_server.py` as a real subprocess via `mcp.client.stdio.stdio_client` + `mcp.ClientSession`, call 2-3 representative tools (`list_models`, and `run_comparison` with `openrouter.call_model` unreachable-by-design so it exercises a real, if unmocked, network-error path — using an obviously invalid API key exactly as the manual Flask smoke test already did), and assert the round-trip actually works over the wire, not just that the Python functions work.

New dependencies added to `requirements.txt`: `mcp[cli]`, `pytest-asyncio`.

## Repo visibility

`github.com/thejaredchapman/evalforge-lite` made public (already done, ahead of this spec, since it was a simple independent action). Both interfaces (Flask app, MCP server) live in the same public repo.

## Non-goals

- No HTTP/SSE transport — stdio only.
- No change to the Flask app's routes, behavior, or session model.
- No re-implementation of PDF text extraction for MCP — policy input is plain text only there.
- No new rate-limit tier for MCP — same 3-per-8h as the web app, per the earlier decision.

## Self-review

- Placeholder scan: none — every tool's signature, return shape, and error behavior is concrete, verified against the actual installed SDK.
- Internal consistency: error strings (`"no_run_available"`, `"rate_limited"`, `"Missing required field: api_key."`-equivalent) intentionally match `app.py`'s so the two interfaces stay behaviorally parallel.
- Scope: one new file (`mcp_server.py`) plus two test files plus a `requirements.txt`/README update — no changes to existing modules.
