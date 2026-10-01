# Optional Server-Side Provider Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator hold provider credentials in server environment variables so users need not paste keys into the browser; keys never reach the client, with a global daily cap on server-key usage.

**Architecture:** A new `server_creds.py` reads env vars into a creds dict shaped like the browser's. `gateway.merge_server_creds()` overlays it on the request's creds (server wins) before validation, in both the Flask app and the MCP server. `limiter.py` gains a rolling-24h global cap consulted only when a server-held backend is actually needed. `/api/catalog` exposes backend names and non-secret regions; the frontend hides inputs for server-held backends. README/.env.example document operator setup.

**Tech Stack:** Python 3.12 / Flask / pytest, vanilla JS + CSS.

Spec: `docs/superpowers/specs/2026-10-01-server-side-keys-design.md`

## Global Constraints

- Opt-in: with no server-key env vars set, behavior is identical to today. No new dependencies; no `.env` auto-loading (env vars are read from `os.environ` at call time, not import time).
- Env vars (exact names): `OPENROUTER_API_KEY`; `BEDROCK_REGION` + (`BEDROCK_API_KEY` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` [+ `AWS_SESSION_TOKEN`]); `VERTEX_PROJECT` + `VERTEX_SERVICE_ACCOUNT_JSON` [+ `VERTEX_REGION`, default `us-central1`]; `FOUNDRY_RESOURCE` + `FOUNDRY_REGION` + `FOUNDRY_API_KEY`; `SERVER_KEY_DAILY_CAP` (default 50).
- A backend is server-held only if ALL its required vars are non-empty after stripping; partial config = not configured. If both Bedrock auth styles are set, `BEDROCK_API_KEY` wins. `VERTEX_SERVICE_ACCOUNT_JSON` is the JSON text and must parse to a JSON object.
- Server value always wins over anything the client sends for that backend.
- Secrets (keys, tokens, project ids, resource names, service-account JSON) are NEVER returned to clients; `/api/catalog` `server_backends` contains only backend names and (when present) `region`.
- `scrub.scrub` must be given the MERGED creds so server secrets are redacted from error text.
- Cap refusal: HTTP 429 body `{"error": "rate_limited", "reset_at": <ts|null>, "message": "The server's shared usage limit has been reached. Please try again later."}`. Cap is consulted only when a server-held backend is needed by the call (judge backend or a target's backend), and only AFTER the per-session limiter passes.
- No live network in tests; the full pytest suite stays green. Tests must not depend on the developer's real environment (autouse fixture clears the env vars).
- All new frontend text goes in via `textContent`.

---

### Task 1: `server_creds.py` and env isolation fixture

**Files:**
- Create: `server_creds.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_server_creds.py`

**Interfaces:**
- Produces: `server_creds.ORDER: tuple[str, ...]` (`("openrouter","bedrock","vertex","foundry")`); `server_creds.load() -> dict` (backend → creds value: a str for openrouter, a dict for others; only held backends, in `ORDER`); `server_creds.held_backends() -> list[str]`; `server_creds.public_summary() -> dict` (`{"openrouter": {}, "bedrock": {"region": "..."}, ...}`); `tests/conftest.py::SERVER_KEY_ENV_VARS` tuple of all env var names.

- [ ] **Step 1: Write the failing tests** — create `tests/test_server_creds.py`:

```python
import json

import gateway
import server_creds

SA_JSON = json.dumps({"type": "service_account", "project_id": "p", "private_key": "KEYDATA"})


def test_nothing_set_means_nothing_held():
    assert server_creds.load() == {}
    assert server_creds.held_backends() == []
    assert server_creds.public_summary() == {}


def test_order_matches_gateway_backends():
    assert server_creds.ORDER == gateway.BACKENDS


def test_openrouter_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "  sk-or-v1-abc\n")
    assert server_creds.load() == {"openrouter": "sk-or-v1-abc"}


def test_whitespace_only_values_count_as_unset(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "   ")
    assert server_creds.load() == {}


def test_bedrock_api_key_style(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    assert server_creds.load()["bedrock"] == {"region": "us-east-1", "api_key": "ABSKexample"}


def test_bedrock_access_key_style_with_optional_session_token(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secretvalue")
    assert server_creds.load()["bedrock"] == {
        "region": "us-west-2", "access_key_id": "AKIAEXAMPLE", "secret_access_key": "secretvalue",
    }
    monkeypatch.setenv("AWS_SESSION_TOKEN", "tok")
    assert server_creds.load()["bedrock"]["session_token"] == "tok"


def test_bedrock_api_key_wins_over_access_keys(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secretvalue")
    assert server_creds.load()["bedrock"] == {"region": "us-east-1", "api_key": "ABSKexample"}


def test_bedrock_without_region_or_without_secret_is_not_held(monkeypatch):
    monkeypatch.setenv("BEDROCK_API_KEY", "ABSKexample")
    assert "bedrock" not in server_creds.load()
    monkeypatch.delenv("BEDROCK_API_KEY")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE")  # secret missing
    assert "bedrock" not in server_creds.load()


def test_vertex_service_account(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", SA_JSON)
    assert server_creds.load()["vertex"] == {
        "project": "my-proj", "region": "us-central1", "service_account_json": SA_JSON,
    }
    monkeypatch.setenv("VERTEX_REGION", "us-east5")
    assert server_creds.load()["vertex"]["region"] == "us-east5"


def test_vertex_invalid_or_non_object_json_is_not_held(monkeypatch):
    monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", "not json")
    assert "vertex" not in server_creds.load()
    monkeypatch.setenv("VERTEX_SERVICE_ACCOUNT_JSON", "[1, 2]")
    assert "vertex" not in server_creds.load()


def test_foundry_needs_resource_region_and_key(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    assert "foundry" not in server_creds.load()
    monkeypatch.setenv("FOUNDRY_API_KEY", "fkey")
    assert server_creds.load()["foundry"] == {"resource": "res", "region": "eastus2", "api_key": "fkey"}


def test_held_backends_follow_order(monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "fkey")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abc")
    assert server_creds.held_backends() == ["openrouter", "foundry"]


def test_public_summary_has_only_names_and_regions(monkeypatch):
    secrets = {
        "OPENROUTER_API_KEY": "sk-or-v1-TOPSECRET",
        "BEDROCK_REGION": "us-east-1", "BEDROCK_API_KEY": "ABSK-TOPSECRET",
        "VERTEX_PROJECT": "secret-project-id", "VERTEX_SERVICE_ACCOUNT_JSON": SA_JSON, "VERTEX_REGION": "us-east5",
        "FOUNDRY_RESOURCE": "secret-resource", "FOUNDRY_REGION": "eastus2", "FOUNDRY_API_KEY": "FKEY-TOPSECRET",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    summary = server_creds.public_summary()
    assert summary == {
        "openrouter": {},
        "bedrock": {"region": "us-east-1"},
        "vertex": {"region": "us-east5"},
        "foundry": {"region": "eastus2"},
    }
    text = json.dumps(summary)
    for needle in ("TOPSECRET", "secret-project-id", "secret-resource", "KEYDATA"):
        assert needle not in text
```

- [ ] **Step 2: Add the isolation fixture** — replace `tests/conftest.py` with:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SERVER_KEY_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "BEDROCK_REGION", "BEDROCK_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "VERTEX_PROJECT", "VERTEX_REGION", "VERTEX_SERVICE_ACCOUNT_JSON",
    "FOUNDRY_RESOURCE", "FOUNDRY_REGION", "FOUNDRY_API_KEY",
    "SERVER_KEY_DAILY_CAP",
)


@pytest.fixture(autouse=True)
def _isolate_server_key_env(monkeypatch):
    """Server-held keys are opt-in via env; no test may depend on the developer's real environment."""
    for name in SERVER_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
```

(Keep the existing first lines of `conftest.py` — the `sys.path.insert` — exactly; the block above includes them.)

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_server_creds.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'server_creds'`).

- [ ] **Step 4: Implement `server_creds.py`**

```python
"""Optional operator-held provider credentials, read from environment variables.

Opt-in: with none of these set, nothing is held server-side and users supply their
own credentials per request. Each loader returns a value shaped exactly like the
browser's creds for that backend, or None when the backend isn't fully configured.
Env is read at call time (not import time) so tests and restarts see current values.
"""
import json
import os

ORDER = ("openrouter", "bedrock", "vertex", "foundry")
DEFAULT_VERTEX_REGION = "us-central1"


def _env(name):
    value = os.environ.get(name)
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def _openrouter():
    return _env("OPENROUTER_API_KEY")


def _bedrock():
    region = _env("BEDROCK_REGION")
    if not region:
        return None
    api_key = _env("BEDROCK_API_KEY")
    if api_key:
        return {"region": region, "api_key": api_key}
    access_key_id = _env("AWS_ACCESS_KEY_ID")
    secret_access_key = _env("AWS_SECRET_ACCESS_KEY")
    if access_key_id and secret_access_key:
        creds = {"region": region, "access_key_id": access_key_id, "secret_access_key": secret_access_key}
        session_token = _env("AWS_SESSION_TOKEN")
        if session_token:
            creds["session_token"] = session_token
        return creds
    return None


def _vertex():
    project = _env("VERTEX_PROJECT")
    raw = _env("VERTEX_SERVICE_ACCOUNT_JSON")
    if not project or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "project": project,
        "region": _env("VERTEX_REGION") or DEFAULT_VERTEX_REGION,
        "service_account_json": raw,
    }


def _foundry():
    resource = _env("FOUNDRY_RESOURCE")
    region = _env("FOUNDRY_REGION")
    api_key = _env("FOUNDRY_API_KEY")
    if resource and region and api_key:
        return {"resource": resource, "region": region, "api_key": api_key}
    return None


_LOADERS = {"openrouter": _openrouter, "bedrock": _bedrock, "vertex": _vertex, "foundry": _foundry}


def load():
    """Backend -> creds value for every fully configured server-held backend, in ORDER."""
    held = {}
    for backend in ORDER:
        value = _LOADERS[backend]()
        if value is not None:
            held[backend] = value
    return held


def held_backends():
    return list(load())


def public_summary():
    """What the browser may know: which backends are server-held and each one's region.

    Never includes keys, tokens, project ids, resource names or service-account JSON.
    """
    summary = {}
    for backend, value in load().items():
        summary[backend] = {"region": value["region"]} if isinstance(value, dict) and "region" in value else {}
    return summary
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_server_creds.py -v && pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add server_creds.py tests/conftest.py tests/test_server_creds.py
git commit -m "feat: add optional server-held credentials loader (server_creds)"
```

---

### Task 2: `gateway.merge_server_creds` and `backends_used`

**Files:**
- Modify: `gateway.py` (imports; `check_run_creds` ~line 171; add two functions)
- Test: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `server_creds.load()` (Task 1).
- Produces: `gateway.merge_server_creds(user_creds: dict | None) -> tuple[dict | None, list[str]]` — returns `(merged, held)` where `held` is the list of server-held backends (in `BACKENDS` order); with nothing held it returns `(user_creds, [])` unchanged (including `None`). Never mutates `user_creds`. `gateway.backends_used(targets: list[str], judge_backend: str) -> set[str]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_gateway.py` (add `import server_creds` is NOT needed; use env via `monkeypatch`; ensure `import gateway` already exists at the top of that file):

```python
def test_merge_server_creds_no_server_keys_returns_input_unchanged():
    user = {"openrouter": "sk-or-v1-user"}
    merged, held = gateway.merge_server_creds(user)
    assert merged is user and held == []
    assert gateway.merge_server_creds(None) == (None, [])


def test_merge_server_creds_server_wins_and_keeps_other_backends(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-server")
    user = {"openrouter": "sk-or-v1-user", "bedrock": {"region": "us-east-1", "api_key": "ABSKuser"}}
    merged, held = gateway.merge_server_creds(user)
    assert merged["openrouter"] == "sk-or-v1-server"
    assert merged["bedrock"] == {"region": "us-east-1", "api_key": "ABSKuser"}
    assert held == ["openrouter"]
    assert user["openrouter"] == "sk-or-v1-user"  # input not mutated


def test_merge_server_creds_with_no_user_creds_returns_only_server_ones(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-server")
    assert gateway.merge_server_creds(None) == ({"openrouter": "sk-or-v1-server"}, ["openrouter"])


def test_backends_used_collects_judge_and_target_backends():
    used = gateway.backends_used(["openai/gpt-5", "openai/gpt-5@foundry", "bad@@"], "bedrock")
    assert {"bedrock", "openrouter", "foundry"} <= used
```

(`"bad@@"` must not raise — invalid targets are skipped, exactly as `check_run_creds` does today. If `parse_target("bad@@")` happens to parse, the assertion still holds because it only checks a subset.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_gateway.py -v -k "merge_server or backends_used"`
Expected: FAIL (`AttributeError`).

- [ ] **Step 3: Implement.** In `gateway.py` add `import server_creds` with the other imports. After `normalize_creds` add:

```python
def merge_server_creds(user_creds):
    """Overlay operator-held credentials (server_creds) on a request's creds. Server wins.

    Returns (merged, held_backends). With nothing held, returns (user_creds, []) unchanged.
    """
    held = server_creds.load()
    if not held:
        return user_creds, []
    merged = dict(user_creds) if isinstance(user_creds, dict) else {}
    merged.update(held)
    return merged, [backend for backend in BACKENDS if backend in held]


def backends_used(targets, judge_backend):
    """The set of backends a call needs: the judge backend plus every valid target's backend."""
    needed = {judge_backend}
    for target in targets:
        try:
            needed.add(parse_target(target)[1])
        except GatewayError:
            continue
    return needed
```

and in `check_run_creds` replace

```python
    needed = {judge_backend}
    for target in targets:
        try:
            needed.add(parse_target(target)[1])
        except GatewayError:
            continue
```

with

```python
    needed = backends_used(targets, judge_backend)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: all PASS (existing `check_run_creds` tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add gateway.py tests/test_gateway.py
git commit -m "feat: merge operator-held credentials into request creds (server wins)"
```

---

### Task 3: Global daily cap in `limiter.py`

**Files:**
- Modify: `limiter.py`
- Modify: `tests/conftest.py` (clear the cap state per test)
- Test: `tests/test_limiter.py`

**Interfaces:**
- Produces: `limiter.SERVER_KEY_WINDOW_SECONDS` (86400); `limiter.DEFAULT_SERVER_KEY_CAP` (50); `limiter.SERVER_CAP_MESSAGE` (`"The server's shared usage limit has been reached. Please try again later."`); `limiter.server_key_cap() -> int`; `limiter.check_and_record_server_key(now: float) -> {"allowed": bool, "reset_at": float | None}`; module list `limiter._server_key_calls`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_limiter.py`:

```python
def test_server_key_cap_defaults_to_50(monkeypatch):
    assert limiter.server_key_cap() == 50


def test_server_key_cap_reads_env_and_falls_back_on_bad_values(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "7")
    assert limiter.server_key_cap() == 7
    for bad in ("abc", "", "-3", "2.5"):
        monkeypatch.setenv("SERVER_KEY_DAILY_CAP", bad)
        assert limiter.server_key_cap() == 50
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "0")
    assert limiter.server_key_cap() == 0


def test_server_key_cap_allows_up_to_cap_then_refuses(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "2")
    now = 1_000_000.0
    assert limiter.check_and_record_server_key(now)["allowed"] is True
    assert limiter.check_and_record_server_key(now + 1)["allowed"] is True
    refused = limiter.check_and_record_server_key(now + 2)
    assert refused["allowed"] is False
    assert refused["reset_at"] == now + limiter.SERVER_KEY_WINDOW_SECONDS


def test_server_key_cap_window_rolls_off(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    now = 1_000_000.0
    assert limiter.check_and_record_server_key(now)["allowed"] is True
    assert limiter.check_and_record_server_key(now + 60)["allowed"] is False
    after = now + limiter.SERVER_KEY_WINDOW_SECONDS + 1
    assert limiter.check_and_record_server_key(after)["allowed"] is True


def test_server_key_cap_zero_refuses_everything(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "0")
    result = limiter.check_and_record_server_key(1_000_000.0)
    assert result == {"allowed": False, "reset_at": None}
```

- [ ] **Step 2: Add per-test state clearing** — in `tests/conftest.py`, extend the autouse fixture's body (after the `for` loop) with:

```python
    import limiter
    limiter._server_key_calls.clear()
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/test_limiter.py -v`
Expected: FAIL (`AttributeError`).

- [ ] **Step 4: Implement** — in `limiter.py` add `import os` at the top (above `import threading`) and append:

```python
SERVER_KEY_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_SERVER_KEY_CAP = 50
SERVER_CAP_MESSAGE = "The server's shared usage limit has been reached. Please try again later."

_server_key_calls = []


def server_key_cap():
    """Max server-key calls per rolling 24h across all users (env SERVER_KEY_DAILY_CAP, default 50).

    Unparseable or negative values fall back to the default; 0 disables server-key use.
    """
    raw = os.environ.get("SERVER_KEY_DAILY_CAP")
    if raw is None:
        return DEFAULT_SERVER_KEY_CAP
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SERVER_KEY_CAP
    return value if value >= 0 else DEFAULT_SERVER_KEY_CAP


def check_and_record_server_key(now):
    """Count one server-key call against the shared rolling-24h cap (process-local)."""
    cap = server_key_cap()
    with _lock:
        _server_key_calls[:] = [t for t in _server_key_calls if now - t < SERVER_KEY_WINDOW_SECONDS]
        if len(_server_key_calls) >= cap:
            reset_at = _server_key_calls[0] + SERVER_KEY_WINDOW_SECONDS if _server_key_calls else None
            return {"allowed": False, "reset_at": reset_at}
        _server_key_calls.append(now)
        return {"allowed": True, "reset_at": None}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_limiter.py -v && pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add limiter.py tests/conftest.py tests/test_limiter.py
git commit -m "feat: add global daily cap for server-held key usage"
```

---

### Task 4: Flask integration (`/api/catalog`, `/api/run`, `/api/evaluate-prompt`)

**Files:**
- Modify: `app.py` (imports; `api_catalog`; `api_evaluate_prompt`; `_validate_run_body`; `api_run`; new helper)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `server_creds.public_summary()` (Task 1); `gateway.merge_server_creds`, `gateway.backends_used` (Task 2); `limiter.check_and_record_server_key`, `limiter.SERVER_CAP_MESSAGE` (Task 3).
- Produces: `/api/catalog` JSON key `"server_backends"` (dict); helper `app._server_cap_refusal(session_id, held, targets, judge_backend) -> Response | None`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_app.py` (add `import json` to the file's imports):

```python
SERVER_KEY = "sk-or-v1-server-secret-123456"


def test_api_catalog_lists_server_backends_without_secrets(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("FOUNDRY_RESOURCE", "evalforge-secret-resource")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-secret-key")
    data = _client().get("/api/catalog").get_json()
    assert data["server_backends"] == {"openrouter": {}, "foundry": {"region": "eastus2"}}
    text = json.dumps(data)
    for needle in (SERVER_KEY, "evalforge-secret-resource", "foundry-secret-key"):
        assert needle not in text


def test_api_catalog_server_backends_empty_by_default():
    assert _client().get("/api/catalog").get_json()["server_backends"] == {}


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_uses_server_key_when_client_sends_none(mock_verdict, mock_run, mock_explain, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 200
    assert mock_run.call_args.kwargs["creds"]["openrouter"] == SERVER_KEY


@patch("analysis.judge.explain_recommendations", return_value="")
@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_ignores_client_key_for_server_held_backend(mock_verdict, mock_run, mock_explain, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-user-key",
    })
    assert resp.status_code == 200
    assert mock_run.call_args.kwargs["creds"]["openrouter"] == SERVER_KEY


def test_api_run_without_any_creds_still_400_when_nothing_server_held():
    resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 400
    assert "api_key" in resp.get_json()["error"]


def test_api_run_error_scrubs_server_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    with patch("app.runner.run", side_effect=Exception(f"failed using key {SERVER_KEY}")):
        resp = _client().post("/api/run", json={"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]})
    assert resp.status_code == 503
    error = resp.get_json()["error"]
    assert SERVER_KEY not in error and "[REDACTED]" in error


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_api_run_server_key_cap_refuses_with_message(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]}
    assert client.post("/api/run", json=payload).status_code == 200
    second = client.post("/api/run", json=payload)
    assert second.status_code == 429
    body = second.get_json()
    assert body["error"] == "rate_limited"
    assert body["message"] == "The server's shared usage limit has been reached. Please try again later."
    assert body["reset_at"] is not None


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_session_limit_refusal_does_not_consume_server_cap(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    client = _client()
    payload = {"test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"]}
    for _ in range(3):
        assert client.post("/api/run", json=payload).status_code == 200
    assert client.post("/api/run", json=payload).status_code == 429  # per-session limit
    assert len(limiter._server_key_calls) == 3


@patch("app.runner.run")
@patch("app.judge.overall_verdict")
def test_cap_not_consumed_when_held_backend_is_not_needed(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("FOUNDRY_RESOURCE", "res")
    monkeypatch.setenv("FOUNDRY_REGION", "eastus2")
    monkeypatch.setenv("FOUNDRY_API_KEY", "foundry-secret-key")
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q1"}], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-user-key",
    })
    assert resp.status_code == 200  # judge + target both OpenRouter, user-supplied
    assert limiter._server_key_calls == []


@patch("app.judge.evaluate_prompt")
def test_api_evaluate_prompt_uses_server_key_and_counts_against_cap(mock_evaluate, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_evaluate.return_value = {"score": 4, "feedback": "ok"}
    client = _client()
    assert client.post("/api/evaluate-prompt", json={"prompt": "hello"}).status_code == 200
    mock_evaluate.assert_called_once_with("hello", creds={"openrouter": SERVER_KEY}, backend="openrouter")
    second = client.post("/api/evaluate-prompt", json={"prompt": "hello again"})
    assert second.status_code == 429
    assert second.get_json()["message"].startswith("The server's shared usage limit")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_app.py -v -k "server"`
Expected: FAIL (`KeyError: 'server_backends'` and 400s).

- [ ] **Step 3: Implement.** In `app.py`:

(a) add `import server_creds` to the imports (alphabetical, after `import scrub`).

(b) in `api_catalog`'s jsonify dict add `"server_backends": server_creds.public_summary(),` after `"provider_links"`.

(c) Add the helper above `api_evaluate_prompt`:

```python
def _server_cap_refusal(session_id, held, targets, judge_backend):
    """429 response when this call needs a server-held backend and the shared daily cap is spent.

    Returns None when the call doesn't touch a server-held key or is still within the cap.
    """
    if not set(held) & gateway.backends_used(targets, judge_backend):
        return None
    result = limiter.check_and_record_server_key(time.time())
    if result["allowed"]:
        return None
    resp = jsonify({"error": "rate_limited", "reset_at": result["reset_at"], "message": limiter.SERVER_CAP_MESSAGE})
    resp.status_code = 429
    return _with_session_cookie(resp, session_id)
```

(d) In `api_evaluate_prompt` replace
`raw_creds = gateway.normalize_creds(body.get("creds"), body.get("api_key"))`
with
```python
    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(body.get("creds"), body.get("api_key")))
```
and, immediately after the existing per-session limiter block (the `if not limit_result["allowed"]:` … `return _with_session_cookie(resp, session_id)` block) and before `result = judge.evaluate_prompt(...)`, add:
```python
    refusal = _server_cap_refusal(session_id, held, [], judge_backend)
    if refusal:
        return refusal
```

(e) In `_validate_run_body` delete these two lines (creds presence is now checked after the merge in `api_run`):
```python
    if gateway.normalize_creds(body.get("creds"), body.get("api_key")) is None:
        return "Missing required field: creds (or api_key)."
```

(f) In `api_run` replace
`raw_creds = gateway.normalize_creds(body.get("creds"), body.get("api_key"))`
with
```python
    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(body.get("creds"), body.get("api_key")))
    if raw_creds is None:
        return _with_session_cookie(_error_response("Missing required field: creds (or api_key).", 400), session_id)
```
and, immediately after the per-session limiter block (before `try:`), add:
```python
    refusal = _server_cap_refusal(session_id, held, model_ids, judge_backend)
    if refusal:
        return refusal
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: all PASS (existing `test_api_run_missing_api_key_returns_400` still sees "api_key" in the message).

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: use server-held keys in /api/run and /api/evaluate-prompt; expose server_backends"
```

---

### Task 5: MCP server integration

**Files:**
- Modify: `mcp_server.py` (`evaluate_prompt`, `run_comparison`, and their docstrings)
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `gateway.merge_server_creds`, `gateway.backends_used`, `limiter.check_and_record_server_key`, `limiter.SERVER_CAP_MESSAGE`.
- Produces: both tools accept missing creds when the server holds the needed backend; refusals return `{"error": "rate_limited", "reset_at": ..., "message": ...}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_mcp_server.py`:

```python
MCP_SERVER_KEY = "sk-or-v1-server-secret-123456"


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_uses_server_key_without_client_creds(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", MCP_SERVER_KEY)
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"])
    assert "error" not in result
    assert mock_run.call_args.kwargs["creds"]["openrouter"] == MCP_SERVER_KEY


@patch("mcp_server.judge.evaluate_prompt")
def test_evaluate_prompt_uses_server_key_and_respects_cap(mock_evaluate, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", MCP_SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_evaluate.return_value = {"score": 3, "feedback": "ok"}
    assert "error" not in mcp_server.evaluate_prompt("hello")
    second = mcp_server.evaluate_prompt("hello again")
    assert second["error"] == "rate_limited"
    assert second["message"] == "The server's shared usage limit has been reached. Please try again later."


@patch("mcp_server.runner.run")
@patch("mcp_server.judge.overall_verdict")
def test_run_comparison_cap_refusal_and_session_limit_ordering(mock_verdict, mock_run, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", MCP_SERVER_KEY)
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    mock_run.return_value = []
    mock_verdict.return_value = {"winner": None, "rationale": ""}
    payload = dict(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"])
    assert "error" not in mcp_server.run_comparison(**payload)
    refused = mcp_server.run_comparison(**payload)
    assert refused["error"] == "rate_limited" and "message" in refused


def test_run_comparison_error_scrubs_server_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", MCP_SERVER_KEY)
    with patch("mcp_server.runner.run", side_effect=Exception(f"failed using key {MCP_SERVER_KEY}")):
        result = mcp_server.run_comparison(test_cases=[{"prompt": "q1"}], models=["openai/gpt-5"])
    assert MCP_SERVER_KEY not in result["error"] and "[REDACTED]" in result["error"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_mcp_server.py -v -k "server_key or cap_refusal"`
Expected: FAIL.

- [ ] **Step 3: Implement.** In `mcp_server.py`:

(a) Add a helper below `_EVALUATE_RATE_LIMIT_KEY`:

```python
def _server_cap_refusal(held, targets, judge_backend):
    """Refusal dict when this call needs a server-held backend and the shared daily cap is spent, else None."""
    if not set(held) & gateway.backends_used(targets, judge_backend):
        return None
    result = limiter.check_and_record_server_key(time.time())
    if result["allowed"]:
        return None
    return {"error": "rate_limited", "reset_at": result["reset_at"], "message": limiter.SERVER_CAP_MESSAGE}
```

(b) In both `evaluate_prompt` and `run_comparison` replace
`raw_creds = gateway.normalize_creds(creds, api_key)`
with
`raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(creds, api_key))`.

(c) In `evaluate_prompt`, after the existing per-bucket `limit_result` refusal and before `return judge.evaluate_prompt(...)`, add:
```python
    refusal = _server_cap_refusal(held, [], judge_backend)
    if refusal:
        return refusal
```

(d) In `run_comparison`, after the existing `limit_result` refusal and before the `try:`, add:
```python
    refusal = _server_cap_refusal(held, models, judge_backend)
    if refusal:
        return refusal
```

(e) Append to both tool docstrings one sentence: `If the operator has set server-side keys for a backend (see README "Server-side keys"), those are used for it automatically and creds for it are not needed.`

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add mcp_server.py tests/test_mcp_server.py
git commit -m "feat: use server-held keys in MCP tools with shared daily cap"
```

---

### Task 6: Frontend — hide inputs for server-held backends

**Files:**
- Modify: `static/app.js` (state ~line 2; `buildCreds` ~169; `missingBackends` ~223; `selectedRegion` ~246; `loadCatalogAndModels` ~395; `evaluatePrompt` ~666; 429 handling in `runComparison` ~761)
- Modify: `static/style.css` (append)

**Interfaces:**
- Consumes: `/api/catalog` → `server_backends` (`{backend: {region?}}`), and the 429 body's optional `message` (Task 4).
- Produces: `state.serverBackends`, `isServerHeld(backend)`, `applyServerBackends()`.

Note: PR #20 (model picker) also edits `static/app.js` — in `syncSelectionVisuals`, `renderProviders` and the end of `loadCatalogAndModels`. Make the edits below exactly where stated (insert after `state.catalog = catalogData;`) to keep merges clean.

- [ ] **Step 1: State and helpers.** Add `serverBackends: {},` to the `state` object. Add above `buildCreds`:

```js
function isServerHeld(backend) {
  return Object.prototype.hasOwnProperty.call(state.serverBackends, backend);
}

// Backends whose credentials the operator keeps on the server: show a note instead of inputs.
function applyServerBackends() {
  Object.entries(state.serverBackends).forEach(([backend, info]) => {
    const panel = document.getElementById(`panel-${backend}`);
    const tab = document.getElementById(`tab-${backend}`);
    if (!panel || !tab || panel.dataset.serverHeld) return;
    panel.dataset.serverHeld = "true";
    Array.from(panel.children).forEach((child) => {
      child.hidden = true;
    });
    const note = document.createElement("p");
    note.className = "server-note";
    note.textContent = info && info.region
      ? `Provided by this server (region: ${info.region}). Nothing to enter here.`
      : "Provided by this server. Nothing to enter here.";
    panel.appendChild(note);
    const mark = document.createElement("span");
    mark.className = "server-mark";
    mark.textContent = " · server";
    tab.appendChild(mark);
  });
}
```

- [ ] **Step 2: Wire it in.**
  - `loadCatalogAndModels`: directly after `state.catalog = catalogData;` add
    ```js
    state.serverBackends = catalogData.server_backends || {};
    applyServerBackends();
    ```
  - `buildCreds`: before its final `return creds;` add
    ```js
    Object.keys(state.serverBackends).forEach((backend) => {
      delete creds[backend]; // the server uses its own key; never send one
    });
    ```
  - `missingBackends`: change the filter to `.filter((backend) => !creds[backend] && !isServerHeld(backend))`.
  - `selectedRegion`: add as the first line of the function
    ```js
    if (isServerHeld(backend) && state.serverBackends[backend].region) return state.serverBackends[backend].region;
    ```
  - `evaluatePrompt`: change `if (!creds[judgeBackend()]) {` to `if (!creds[judgeBackend()] && !isServerHeld(judgeBackend())) {`.
  - `runComparison` 429 branch: replace the `runStatus.textContent = \`Rate limit reached…\`` line with
    ```js
    runStatus.textContent = data.message || `Rate limit reached. Try again after ${resetDate.toLocaleTimeString()}.`;
    ```

- [ ] **Step 3: CSS** — append to `static/style.css`:

```css
.server-note { color: var(--muted); font-size: 12px; margin: 4px 0; }
.server-mark { font-size: 10px; color: var(--muted); }
```

- [ ] **Step 4: Verify**

Run: `node --check static/app.js && pytest tests/ -q && grep -n "isServerHeld\|applyServerBackends\|serverBackends" static/app.js`
Expected: syntax OK; tests PASS; the grep shows state, helper, and the six wiring sites.

- [ ] **Step 5: Manual check** (no DOM tests exist). Run the app with `OPENROUTER_API_KEY=sk-or-v1-fake python app.py`, open http://localhost:8000: the OpenRouter tab shows "· server" and the note with no input; other tabs unchanged; with a fake model selected, Run does not say "Add OpenRouter credentials first". Without the env var everything is as before.

- [ ] **Step 6: Commit**

```bash
git add static/app.js static/style.css
git commit -m "feat: hide credential inputs for server-held backends in the UI"
```

---

### Task 7: Documentation — README, `.env.example`, CLAUDE.md

**Files:**
- Modify: `README.md` (Setup block ~lines 9-16; Web app paragraph ~lines 21-22; Backends intro ~lines 52-54; new section after the Backends section, before `## Comparing up to 4 models`)
- Modify: `.env.example`
- Modify: `CLAUDE.md` (local only — see Step 4)

- [ ] **Step 1: Fix the existing README statements.**
  - In **Setup**, replace the line `cp .env.example .env   # optional: override the per-backend judge models` and add a note, so the block reads:

    ```
        python3.12 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
        cp .env.example .env   # optional: judge-model overrides and server-side keys
    ```

    followed (after the "Requires Python 3.10+…" sentence) by a new paragraph:

    > The app does **not** read `.env` by itself. To use the values in it, load them into your shell first: `set -a; source .env; set +a`, then start the app. (Or set the variables in your host's dashboard.)

  - In **Web app**, change "(never sent anywhere but this server, never stored server-side beyond the request)" to "(sent only to this server and not stored beyond the request — unless the operator keeps keys on the server, see [Server-side keys](#server-side-keys-optional-for-operators))".
  - In **Backends**, change the intro paragraph "Every request carries its own credentials — nothing is read from server env/config, and credentials are never stored beyond the request that used them." to "By default every request carries its own credentials — nothing is read from server env/config, and credentials are never stored beyond the request that used them. Operators can optionally keep keys on the server instead; see [Server-side keys](#server-side-keys-optional-for-operators)."

- [ ] **Step 2: Add the new README section** — insert this verbatim before `## Comparing up to 4 models`:

````markdown
## Server-side keys (optional, for operators)

**Skip this section if every user brings their own key** — that is the default and needs no setup.

If you run EvalForge Lite for other people (a team, a demo), you can keep one
or more provider keys **on the server** instead. The key lives in an
environment variable, is never sent to the browser, and users just see
"Provided by this server" in place of the key box.

### How it works

- Set the environment variables for a backend (table below) and restart the app.
- That backend's tab in the credentials panel now says **Provided by this
  server** and has no input fields.
- The server's key always wins: anything a browser sends for that backend is ignored.
- Backends you do *not* set up work as before — users paste their own key.
- Your users spend your key, so there is a **shared daily limit** (see below).

### Step 1 — Choose what to set

Set **all** the variables listed for a backend, or that backend stays user-supplied.

| Backend | Variables | Notes |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | One variable. |
| Amazon Bedrock | `BEDROCK_REGION` **and** `BEDROCK_API_KEY` | Simplest option. |
| Amazon Bedrock (access keys) | `BEDROCK_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (optional `AWS_SESSION_TOKEN`) | Used only if `BEDROCK_API_KEY` is not set. |
| Google Vertex AI | `VERTEX_PROJECT` **and** `VERTEX_SERVICE_ACCOUNT_JSON` (optional `VERTEX_REGION`, default `us-central1`) | The JSON text of a service-account key. Short-lived access tokens are not supported on the server. |
| Microsoft Foundry | `FOUNDRY_RESOURCE`, `FOUNDRY_REGION`, `FOUNDRY_API_KEY` | Entra ID access tokens are not supported on the server (they expire). |
| Daily limit | `SERVER_KEY_DAILY_CAP` (optional, default `50`) | See [The daily limit](#the-daily-limit). |

### Step 2 — Set them and start the app

**On your own computer (macOS / Linux):**

    export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
    python app.py

Using the `.env` file instead: copy `.env.example` to `.env`, remove the `#`
from the lines you want and fill in your values, then load it and start:

    set -a; source .env; set +a
    python app.py

(`.env` is already git-ignored. Never commit it.)

**Bedrock example:**

    export BEDROCK_REGION="us-east-1"
    export BEDROCK_API_KEY="your-bedrock-api-key"

**Vertex AI example** (puts the whole JSON file into one variable):

    export VERTEX_PROJECT="my-gcp-project"
    export VERTEX_REGION="us-central1"
    export VERTEX_SERVICE_ACCOUNT_JSON="$(cat service-account.json)"

**Foundry example:**

    export FOUNDRY_RESOURCE="my-foundry-resource"
    export FOUNDRY_REGION="eastus2"
    export FOUNDRY_API_KEY="your-foundry-key"

**On a host such as Render:** open your service → **Environment** → **Add
Environment Variable**, add the names and values from the table (for Vertex,
paste the whole JSON as the value), then **redeploy**. **Docker:** use
`-e NAME=value` or `--env-file`. Never put keys in `render.yaml`, the
Dockerfile, or git.

### Step 3 — Check that it worked

Open the app. The credentials tab for that backend should say **Provided by
this server** and show no input boxes.

Or check from a terminal (this lists backend names and regions only — never
keys):

    curl -s http://localhost:8000/api/catalog | python -m json.tool | grep -A8 server_backends

### The daily limit

Because users spend *your* key, the server counts every run (and every prompt
check) that uses a server-held key. The default is **50 per rolling 24 hours,
shared by everyone**. When it is reached, people see "The server's shared
usage limit has been reached. Please try again later."

- Change it with `SERVER_KEY_DAILY_CAP`. `0` turns server-key use off entirely.
- The usual per-browser limit (3 runs per 8 hours) still applies on top.
- The count lives in memory: restarting the app resets it, and if you run
  several worker processes each keeps its own count (the included
  `render.yaml` uses one worker).

### MCP server

The MCP server reads the same variables from the environment it is started in,
so with them set you can call `run_comparison` and `evaluate_prompt` without
passing `creds`.

### Safety notes

- Keep keys only in environment variables or your host's secret store — not in
  code, README files, screenshots, or git.
- The key is never sent to the browser, and it is removed from error messages.
- Anyone who can open your site can spend your key (up to the daily limit). For
  a private tool, put the site behind your own login or VPN, and use a
  provider key with its own spending limit.
- To rotate a key: change the variable and restart.
- To turn the feature off: remove the variables and restart. Users go back to
  entering their own keys.

### Troubleshooting

- **The tab still shows input boxes.** A required variable is missing or empty
  (check the table), the app was not restarted, or — for Vertex — the JSON is
  not valid. Partly configured backends are ignored on purpose.
- **"Shared usage limit has been reached".** Wait, or raise `SERVER_KEY_DAILY_CAP`.
- **Bedrock still asks for a region.** `BEDROCK_REGION` must be set along with a key.

````

- [ ] **Step 3: `.env.example`** — append (all commented out, no real values):

```
# --- Optional: keep provider keys on the SERVER instead of asking users for them. ---
# Set ALL the variables for a backend or it stays user-supplied. The app does not
# read this file itself: load it with `set -a; source .env; set +a`, or set the
# variables in your host's dashboard. See README: "Server-side keys".
# OPENROUTER_API_KEY=sk-or-v1-...
# BEDROCK_REGION=us-east-1
# BEDROCK_API_KEY=...
# (or, instead of BEDROCK_API_KEY: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN)
# VERTEX_PROJECT=my-gcp-project
# VERTEX_REGION=us-central1
# VERTEX_SERVICE_ACCOUNT_JSON={"type":"service_account", ...}
# FOUNDRY_RESOURCE=my-foundry-resource
# FOUNDRY_REGION=eastus2
# FOUNDRY_API_KEY=...
# Shared cap on runs that use a server key, per rolling 24h (default 50; 0 = off).
# SERVER_KEY_DAILY_CAP=50
```

Also change the existing header comment of `.env.example` from "Users still supply their own per-backend credentials in the UI — this repo never holds any of them." to "By default users supply their own per-backend credentials in the UI; this repo never holds any (see the optional server-side keys below)."

- [ ] **Step 4: `CLAUDE.md`** (an untracked local file — edit it, but do NOT `git add` it). In "Conventions carried through the codebase" replace the first bullet's opening sentence "No server-side model credentials ever, anywhere —" with "No server-side model credentials unless the operator opts in via environment variables (`server_creds.py`, merged by `gateway.merge_server_creds`, never sent to clients, always scrubbed from error text, spend bounded by `limiter.check_and_record_server_key`) —", and add `server_creds.py` to the module list with one line describing it.

- [ ] **Step 5: Verify**

Run: `pytest tests/ -q && git diff --stat -- README.md .env.example`
Expected: PASS; README and `.env.example` changed. Skim the rendered README section for broken anchors: the link `#server-side-keys-optional-for-operators` must match the heading "Server-side keys (optional, for operators)".

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example
git commit -m "docs: README and .env.example for optional server-side keys"
```

---

## Self-Review

- **Spec coverage:** §1 loader (T1); §2 merge + call sites + scrub of merged creds + validation-after-merge (T2, T4, T5); §3 catalog `server_backends`, frontend note/inputs hidden/`buildCreds`/`missingBackends`/region (T4, T6); §4 cap incl. only-when-needed, after per-session, exact message + `message` field, frontend uses it (T3, T4, T5, T6); §5 README/.env.example/CLAUDE.md incl. the `.env`-not-auto-loaded fix (T7); §6 tests per file incl. no-secrets-in-summary, scrub, ordering (T1-T5). Frontend has a manual checklist (no DOM test).
- **Placeholders:** none; every code step shows code.
- **Type consistency:** `merge_server_creds -> (merged, held)`, `backends_used(targets, judge_backend) -> set`, `check_and_record_server_key(now) -> {allowed, reset_at}`, `SERVER_CAP_MESSAGE`, `server_creds.ORDER/load/held_backends/public_summary`, `state.serverBackends/isServerHeld/applyServerBackends` are spelled identically everywhere they're used.
- **Known interaction:** PR #20 edits `static/app.js` near `loadCatalogAndModels`; the insertion point here (right after `state.catalog = catalogData;`) is untouched by #20, so a trivial merge is expected.
