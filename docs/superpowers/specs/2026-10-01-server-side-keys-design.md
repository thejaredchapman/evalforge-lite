# EvalForge Lite — Optional Server-Side Provider Keys

**Date:** 2026-10-01
**Status:** Design (approved in conversation; pending written-spec review)
**Branch:** `feat/server-keys` (from `origin/main` @ d01e2f8)

## Goal

Let an operator keep provider credentials on the server, in environment variables, so users don't have to paste keys into the browser. A server-held key is never sent to the browser. This is **opt-in**: with no env vars set, behavior is exactly as today (browser-supplied credentials, nothing held server-side).

## Decisions (from brainstorming)

- **Backends:** all four (OpenRouter, Bedrock, Vertex, Foundry), each handled independently. Any mix of server-held and user-supplied works.
- **Override:** the server key wins. For a server-held backend, the credentials tab shows "Provided by this server" with no inputs, and anything a client sends for that backend is ignored.
- **Abuse control:** keep the per-session limiter and add a **global rolling-24h cap** on calls that use a server-held key (`SERVER_KEY_DAILY_CAP`, default 50).

## 1. `server_creds.py` (new)

Reads `os.environ` at call time (not import time, so tests can monkeypatch) and returns a dict shaped exactly like the browser's `creds`.

| Backend | Env vars | Resulting creds value |
|---|---|---|
| openrouter | `OPENROUTER_API_KEY` | `"<key>"` |
| bedrock | `BEDROCK_REGION` + `BEDROCK_API_KEY` | `{"region", "api_key"}` |
| bedrock | `BEDROCK_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ optional `AWS_SESSION_TOKEN`) | `{"region", "access_key_id", "secret_access_key"[, "session_token"]}` |
| vertex | `VERTEX_PROJECT` + `VERTEX_SERVICE_ACCOUNT_JSON` (+ optional `VERTEX_REGION`, default `us-central1`) | `{"project", "region", "service_account_json"}` |
| foundry | `FOUNDRY_RESOURCE` + `FOUNDRY_REGION` + `FOUNDRY_API_KEY` | `{"resource", "region", "api_key"}` |

- If both Bedrock auth styles are set, `BEDROCK_API_KEY` wins.
- A backend is *server-held* only if all its required variables are non-empty after stripping. Partially configured backends are treated as not configured (never half-used).
- Vertex access tokens and Foundry Entra tokens expire, so they are **not** supported server-side; only service-account JSON / API keys are.
- `VERTEX_SERVICE_ACCOUNT_JSON` holds the JSON text itself (not a path). It must parse as a JSON object, else the backend is treated as not configured.

Public interface:

```python
def load() -> dict                      # backend -> creds value, server-held backends only
def held_backends() -> list[str]        # ordered subset of gateway.BACKENDS
def public_summary() -> dict            # {"openrouter": {}, "bedrock": {"region": "..."}, ...}; names + non-secret region only
```

`public_summary()` never contains keys, tokens, project ids, resource names, or service-account JSON. Region is included so the frontend's existing ⚠ region warnings keep working for server-held backends.

## 2. Merging (`gateway.py`)

```python
def merge_server_creds(user_creds: dict | None) -> tuple[dict | None, list[str]]
```

Returns `(merged, used_server_backends)`. For every server-held backend the server value replaces whatever the user sent; user values for other backends are kept. If the user sent nothing and no backend is server-held, returns `(None, [])` so existing "missing creds" handling is unchanged.

Call sites, always **before** `gateway.check_run_creds` and **before** building the scrub list:

- `app.py`: `/api/run`, `/api/evaluate-prompt` (and the `normalize_creds` presence checks at ~lines 98 and 136, so a request with no creds is valid when the server holds the needed backend).
- `mcp_server.py`: `evaluate_prompt`, `run_comparison`. (The stdio MCP server runs under the operator's own environment, so the same env vars apply.)

`scrub.scrub(message, raw_creds)` must receive the **merged** dict so server-held secrets are redacted from every error message sent to clients or logs.

Required-field validation: `/api/run` currently demands a `prompt` and creds; "creds required" becomes "creds required unless the server holds the needed backend", i.e. validation happens after the merge.

## 3. API and frontend

- `/api/catalog` gains `"server_backends": server_creds.public_summary()`.
- `static/app.js`:
  - For each backend in `server_backends`, the matching `.cred-panel` shows a short "Provided by this server" note (plus the region when present) and hides its inputs. The tab gets a "server" marker.
  - `buildCreds()` omits server-held backends (the server ignores them anyway).
  - The "Add … credentials first" check (`missingBackends`) treats server-held backends as configured.
  - `selectedRegion(backend)` returns the server's region for a server-held backend, so ⚠ warnings still work.
- All new text goes in via `textContent`.

## 4. Global daily cap (`limiter.py`)

```python
SERVER_KEY_WINDOW_SECONDS = 24 * 60 * 60
def server_key_cap() -> int                       # int(os.environ.get("SERVER_KEY_DAILY_CAP", 50)); invalid/negative -> 50; 0 disables server-key runs
def check_and_record_server_key(now) -> dict      # {"allowed": bool, "reset_at": float | None}, same shape as check_and_record
```

- One rolling window shared by all users, lock-guarded like the existing limiter. Process-local, the same accepted limitation as the per-session limiter.
- It is consulted **only** when `used_server_backends` is non-empty, in `/api/run`, `/api/evaluate-prompt`, and the two MCP tools, **after** the per-session check passes (so a session-limited request doesn't burn the global budget).
- A refused request returns a 429 in the same shape as today's rate-limit response, with the exact message "The server's shared usage limit has been reached. Please try again later." (No "use your own key" hint: the user cannot override a server-held backend.) Tests assert this exact wording.
- Each `/api/run`, `/api/evaluate-prompt` call counts as 1.

## 5. Documentation and convention

- **README** (detailed, simple instructions — this is a deliverable of this sub-project): a new "Server-side keys (optional, for operators)" section with the env var table, copy-paste `export` examples per backend, how to verify it's working, the daily cap, the Render/Docker/`gunicorn` notes, security notes (never commit keys; keys never reach the browser; use your host's secret store), and how to turn it off. Fix the existing Setup text: `.env` is **not** auto-loaded — show `set -a; source .env; set +a` (or the host's dashboard). Update the sentences that say "nothing is read from server env/config" to say "unless the operator opts in".
- **`.env.example`**: commented-out placeholder lines for every variable above (no real values).
- **`CLAUDE.md`** convention line: "No server-side model credentials unless the operator opts in via environment variables (see `server_creds.py`); they are never sent to clients and are always scrubbed from error text."

## 6. Testing (no live network)

- `test_server_creds.py`: each backend's variable combinations (complete, partial, whitespace-only, Bedrock both styles, invalid Vertex JSON), `held_backends` order, `public_summary` contains no secrets (assert none of the fake secret strings appear anywhere in its `json.dumps`).
- `test_gateway.py`: `merge_server_creds` — server wins over user value, user value kept for non-held backend, `(None, [])` with nothing, no mutation of the input dict.
- `test_app.py`: with env patched, `/api/catalog` lists `server_backends` with no secrets; `/api/run` and `/api/evaluate-prompt` succeed with no client creds when the server holds the backend (mocking `gateway.call_backend` as the existing tests do); a client-sent key for a server-held backend is ignored (the mocked call sees the server key); an error message containing the server key is scrubbed in the response.
- `test_limiter.py`: cap allows N then refuses, rolling window expiry, `0` disables, invalid env falls back to 50, per-session refusal does not consume global budget (app-level test).
- `test_mcp_server.py`: the same merge/cap behavior for both tools.
- Frontend: `node --check static/app.js`; no DOM test exists, so the manual checklist (server-held tab shows the note and no inputs; ⚠ warnings still appear using the server region; "add credentials first" does not fire for a server-held backend) is listed in the PR.
- The full pytest suite stays green.

## Out of scope

Per-user access codes, server-held expiring tokens (Vertex access token, Foundry Entra token), persistent/shared cap storage across processes, a settings UI for the operator, and key rotation tooling.
