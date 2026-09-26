# EvalForge Lite — Amazon Bedrock & Google Vertex AI Backends

**Date:** 2026-09-25
**Status:** Design (pending user review)
**Depends on:** existing backend modules; amends `2026-08-29-evalforge-lite-finish/design.md` (app + frontend).

## Goal

Let any catalog model run through one of three **backends** — OpenRouter (today's only path),
Amazon Bedrock, or Google Vertex AI — using credentials the user supplies per request. The eval,
judge, policy gate, grading, and report flow is identical regardless of backend, and the same
model can appear twice in one run (e.g. Claude Sonnet via OpenRouter vs. via Bedrock).

## Decisions (from brainstorming)

- Bedrock/Vertex are **alternate backends**, not new catalog providers.
- **Both** auth forms per cloud: Bedrock API key *or* AWS access keys (SigV4); Vertex access
  token *or* service-account JSON.
- The **judge/policy backend is user-selectable**; an all-Bedrock or all-Vertex run needs no
  OpenRouter key.
- Out of scope: Claude-on-Vertex (needs Anthropic-format `rawPredict`), streaming, arbitrary
  model IDs not in the catalog.

## 1. Modules

### `gateway.py` (new) — dispatch + credential prep

```python
class GatewayError(Exception): ...          # openrouter.OpenRouterError now subclasses this

BACKENDS = ("openrouter", "bedrock", "vertex")

def parse_target(target) -> (model_id, backend)
    # "anthropic/claude-sonnet-4.5"          -> ("anthropic/claude-sonnet-4.5", "openrouter")
    # "anthropic/claude-sonnet-4.5@bedrock"  -> (..., "bedrock")
    # rsplit("@", 1); suffix must be in BACKENDS, else the whole string is the model id
    # (openrouter). Raises GatewayError on unknown/empty.

def prepare_creds(creds) -> creds
    # Called ONCE per run, before thread fan-out. Validates shapes/format (see §4) and
    # exchanges a Vertex service-account JSON for an access token. Returns a new dict;
    # a backend whose creds are missing/invalid maps to {"error": "<safe message>"}.

def call_backend(backend, native_model_id, messages, creds) -> {text, latency_ms, cost_usd, tokens}
    # Low level: native id (used by judge/policy with per-backend judge models).

def call_target(target, messages, creds) -> {text, latency_ms, cost_usd, tokens}
    # High level: parse target, resolve native route id + price via catalog, call_backend,
    # fill cost_usd from price table for non-OpenRouter backends.
```

Missing/errored creds for a backend → `GatewayError("No Bedrock credentials supplied")` (or the
prep error), never a `KeyError`.

### `bedrock.py` (new) — Converse API

- `POST https://bedrock-runtime.{region}.amazonaws.com/model/{quote(model_id, safe="")}/converse`
  (IDs contain `:`, which must be percent-encoded — and the signed URL must be byte-identical to
  the sent URL).
- Request body: messages converted to Converse shape — `{"role", "content": [{"text": ...}]}`;
  any `system` role messages lifted into the top-level `"system": [{"text": ...}]` field.
  Body is serialized once to bytes and sent with `data=` (not `json=`) so the SigV4 signature
  matches.
- Auth:
  - `{"region", "api_key"}` → `Authorization: Bearer <api_key>`.
  - `{"region", "access_key_id", "secret_access_key", "session_token"?}` → sign an
    `botocore.awsrequest.AWSRequest` with `botocore.auth.SigV4Auth(Credentials(...), "bedrock", region)`
    and send its headers via `requests.post`. (botocore only — no boto3.)
- Response: `output.message.content` → text of the **first block that has a `"text"` key**
  (reasoning models may emit a `reasoningContent` block first). Tokens from
  `usage.totalTokens`. Same error mapping as `openrouter.py` (RequestException / bad JSON /
  bad shape → `GatewayError` subclass `BedrockError`).

### `vertex.py` (new) — OpenAI-compatible endpoint

- Host: `https://{region}-aiplatform.googleapis.com`, **except** `region == "global"` →
  `https://aiplatform.googleapis.com` (Gemini 3 preview models are global-only).
- `POST {host}/v1/projects/{project}/locations/{region}/endpoints/openapi/chat/completions`,
  body `{"model": "google/gemini-2.5-flash", "messages": [...]}`, `Authorization: Bearer <token>`.
- Response parsed exactly like OpenRouter's (`choices[0].message.content`, `usage.total_tokens`).
- `mint_token(service_account_info)` → uses `google.oauth2.service_account.Credentials
  .from_service_account_info(info, scopes=["https://www.googleapis.com/auth/cloud-platform"])`
  then `.refresh(google.auth.transport.requests.Request())`. **Before** building credentials,
  `info["token_uri"]` is overwritten with `https://oauth2.googleapis.com/token` (a user-supplied
  `token_uri` would otherwise make the server POST a signed JWT to an arbitrary URL — SSRF).
  Called only from `gateway.prepare_creds`, once per run.

### `openrouter.py` — minimal change

`OpenRouterError` subclasses `gateway.GatewayError` (import direction: `openrouter` imports
`GatewayError` from a tiny `errors.py` to avoid a cycle with `gateway`). No behavior change.

## 2. Catalog: routes and prices

Models in `data/providers.json` gain an optional `routes` map. OpenRouter is implicit (the
catalog `id` *is* the OpenRouter id and OpenRouter returns cost itself).

```json
{"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "family": "claude-sonnet",
 "routes": {
   "bedrock": {"id": "{geo}.anthropic.claude-sonnet-4-5-20250929-v1:0",
               "price": {"input_per_m": 3.0, "output_per_m": 15.0}}
 }}
{"id": "google/gemini-2.5-flash", ...,
 "routes": {"vertex": {"id": "google/gemini-2.5-flash",
                       "price": {"input_per_m": 0.30, "output_per_m": 2.50}}}}
```

- A literal `{geo}` in a Bedrock id is replaced at call time with the cross-region
  inference-profile geography derived from the region: `us-gov-*`→`us-gov`, `us-*`→`us`,
  `eu-*`→`eu`, `ap-*`→`apac` (hard-coding `us.` would break EU users). Unknown geography →
  `GatewayError`. The same template works for `config.JUDGE_MODELS["bedrock"]`, so there is
  one mechanism for catalog routes and judge ids alike.
- Price is per route (backend pricing differs). Cost = `in_tok/1e6*input + out_tok/1e6*output`;
  requires input/output token split, so clients return `input_tokens`/`output_tokens`
  internally. No price entry → `0.0`.
- `catalog.py` adds `route_for(catalog_dict, model_id, backend) -> dict | None` (same
  `catalog_dict`-first style as `suggest_family`). No separate `backends` field: `/api/catalog`
  already returns each model's `routes`, and the frontend derives
  `["openrouter", ...Object.keys(model.routes || {})]` itself.
- Target naming a backend the model has no route for → cell error `"<model> is not available on
  Bedrock"`.

## 3. Credentials, runner, judge, policy

`api_key` becomes `creds` everywhere it's threaded (runner, judge, policy):

```python
creds = {
  "openrouter": "sk-or-...",                                   # optional
  "bedrock": {"region": "us-east-1", "api_key": "ABSK..."}     # or access_key_id/secret_access_key/session_token
  "vertex":  {"project": "my-proj", "region": "us-central1",
              "access_token": "ya29..."}                       # or "service_account_json": "<json string>"
}
```

- `gateway.prepare_creds` is idempotent on its own output (error entries and already-minted
  tokens pass through), so `app.py` prepares once and hands the same prepared creds to both
  `runner.run` and `judge.overall_verdict` without a second token exchange.
- `runner.run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter")`:
  calls `gateway.prepare_creds(creds)` once, then fans out as today using
  `gateway.call_target`. Results keyed by the **target string**, so the same model on two
  backends is two leaderboard columns.
- `judge.llm_judge(response_text, rubric, creds, backend="openrouter", judge_model=None)`,
  `judge.overall_verdict(aggregate_stats, creds, backend="openrouter", judge_model=None)`,
  `policy.check_policy(prompt, policy_text, creds, backend="openrouter", judge_model=None)` —
  all call `gateway.call_backend(backend, model, ...)` and catch `GatewayError` (which still
  covers `OpenRouterError`).
- `config.JUDGE_MODELS = {"openrouter": env JUDGE_MODEL or "openai/gpt-4o-mini",
  "bedrock": env BEDROCK_JUDGE_MODEL or "{geo}.anthropic.claude-haiku-4-5-20251001-v1:0",
  "vertex": env VERTEX_JUDGE_MODEL or "google/gemini-2.5-flash"}`. `config.JUDGE_MODEL` kept as
  an alias for the openrouter entry.
- Nothing is stored or logged; `creds` lives only for the request.

## 4. Validation, errors, security

- **Input validation (SSRF guard).** Region and project are interpolated into hostnames/paths,
  so `prepare_creds` rejects anything not matching:
  - Bedrock region: `^[a-z]{2}(-[a-z]+)+-\d$`
  - Vertex region: `^(global|[a-z]+-[a-z]+\d+)$`
  - Vertex project: `^[a-z][a-z0-9-]{4,28}[a-z0-9]$`
  - service-account JSON must parse to a dict with `type == "service_account"`.
- **Missing creds:** target cells error; nothing raises. The **policy gate still fails closed**
  (missing/invalid judge-backend creds ⇒ violation). Additionally `app.py` returns `400` up
  front when a policy is set and the chosen judge backend has no creds, so users see a clear
  message instead of every prompt "blocked".
- **Scrubbing** lives in its own `scrub.py` (`scrub(message, creds=None) -> str`) so it is
  tested now, before `app.py` exists; `app.py` uses it for error responses **and** log lines
  (the finish plan's `logger.exception` would otherwise write secrets from exception text to
  the log). Two layers:
  1. Exact-value replacement of every secret string present in the request's `creds`
     (catches AWS secret keys, which have no reliable regex).
  2. Regex, extended from `\b(sk|pk)-[A-Za-z0-9_-]{8,}\b` to also cover
     `\b(AKIA|ASIA)[A-Z0-9]{16}\b`, `\bABSK[A-Za-z0-9+/=]{20,}`,
     `\bbedrock-api-key-[A-Za-z0-9+/=._-]{20,}`, `\bya29\.[A-Za-z0-9._-]+`, and
     `-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----` (DOTALL).
  All → `"[REDACTED]"`.

## 5. Testing (no network — `requests.post` and google-auth refresh always mocked)

- `test_gateway.py`: `parse_target` cases (plain, `@bedrock`, `@vertex`, unknown suffix);
  dispatch to the right client; missing creds → `GatewayError`; region/project validation
  rejects `"x.evil.com#"`-style inputs; prepare mints a Vertex token once for N cells; cost
  computed from route price; missing route → error.
- `test_bedrock.py`: bearer header; SigV4 header starts `AWS4-HMAC-SHA256` and includes
  `X-Amz-Security-Token` when a session token is given; URL percent-encodes `:`; system message
  lifting; first-text-block extraction skipping `reasoningContent`; inference-profile prefix
  by region (us/eu/apac/unknown); error mapping.
- `test_vertex.py`: regional vs. global host; bearer header; response parsing; `token_uri`
  overridden before credential construction.
- Existing `test_judge.py` / `test_policy.py` / `test_runner.py` updated from `api_key=` to
  `creds=`; add a runner test with the same model on two backends; a policy test that
  missing judge-backend creds fails closed.
- `test_scrub` (in the app tests): each new pattern and exact-value scrubbing.

## 6. Dependencies & sequencing

- `requirements.txt`: add `botocore` and `google-auth` (verified to resolve on the project's
  Python 3.9.6 venv: botocore 1.42.97, google-auth 2.50.0).
- Order: `errors.py` + `gateway.py` → `bedrock.py` → `vertex.py` → catalog routes →
  judge/policy/runner `creds` migration → amend the finish spec: `app.py` accepts `creds` +
  `judge_backend`, applies the up-front 400 and the new scrubber; frontend gets a
  three-tab credentials panel (OpenRouter / Bedrock / Vertex, each with an auth-form toggle),
  per-model backend chips (only for backends in `backends`), and a judge-backend select.
- CLAUDE.md conventions updated: "no server-side key" generalizes to "no server-side cloud
  credentials of any kind"; every OpenRouter/Bedrock/Vertex call site takes explicit `creds`.
