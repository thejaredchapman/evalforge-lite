# EvalForge Lite

<!-- mcp-name: io.github.thejaredchapman/evalforge-lite -->

Compare text LLMs across providers — OpenRouter, Amazon Bedrock, and Google
Vertex AI — bring your own credentials. Available as a web app and as an
MCP server.

## Setup

    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # optional: override the per-backend judge models

Requires Python 3.10+ (the `mcp` package's floor); developed and tested on 3.12.

## Web app

    python app.py

Open http://localhost:8000, add credentials for the backend(s) you want to
use (never sent anywhere but this server, never stored server-side beyond
the request), add test cases, pick models, and run. Set `PORT=<port>` to
run on a different port, or `FLASK_DEBUG=1` if you need Flask's
interactive debugger — it's off by default since this app handles live
credentials.

### Try it out

1. Open the credentials panel and fill in the backend(s) you'll use (see
   [Backends](#backends-openrouter-amazon-bedrock-google-vertex-ai) below).
2. Add a test case: a prompt, and optionally a rubric (scored by an LLM
   judge) and/or rule-based checks (e.g. "contains", "max_length").
3. Pick two to four models, ideally from different providers, from the
   frontier list or by browsing providers — click a model's Bedrock/Vertex
   chip to also run it on that backend. (`X` and `X@bedrock` count as two
   of your four.)
4. Click **Run comparison** — you'll get a side-by-side comparison and a
   leaderboard with letter grades, per-model cost/latency, and an overall
   verdict, plus a per-cell view of every model's actual response. See
   [Comparing up to 4 models](#comparing-up-to-4-models) below for how to
   read it.
5. Download a PDF report or CSV export of the run.

**Heads up before you click Run repeatedly while testing:** it's
rate-limited to 3 runs per 8 hours per browser session (resets if you
restart the server) — see [Notes](#notes).

## Backends: OpenRouter, Amazon Bedrock, Google Vertex AI

Every request carries its own credentials — nothing is read from server
env/config, and credentials are never stored beyond the request that used
them.

- **OpenRouter** — a single API key.
- **Amazon Bedrock** — either a Bedrock API key (bearer token) or an AWS
  access key id + secret access key (optionally with a session token), plus
  a region.
- **Google Vertex AI** — either an OAuth access token or a service-account
  JSON key, plus a GCP project id and a region.

A model *target* is `"<catalog id>"` for OpenRouter, or `"<catalog
id>@bedrock"` / `"<catalog id>@vertex"` to run that same model on Bedrock or
Vertex instead. In the UI, pick a target by clicking a model's Bedrock or
Vertex chip (shown under any model the catalog has a route for) rather than
typing the `@backend` suffix by hand.

The **judge backend** picker (next to the credentials panel) selects which
backend runs the LLM judge and the policy gate — it can differ from the
backend(s) the models under test run on, but needs its own credentials
filled in.

Bedrock/Vertex costs shown in the leaderboard and reports are *estimates*,
computed from the per-token prices in `data/providers.json`, not costs
reported back by AWS/GCP billing.

Some Bedrock/Vertex routes are region-restricted: Vertex's Llama MaaS
models are only offered in certain regions (e.g. `us-east5`), and Gemini
preview models may need the `global` region instead of a specific one. If a
run fails with a routing/availability error, try a different region.

## Comparing up to 4 models

Pick up to 4 models (`X` and `X@bedrock` count as two) and each run shows a
side-by-side comparison in addition to the leaderboard.

### The four metrics

- **Quality** — the model's overall grade: judge score and rule-check pass
  rate, blended 70/30 (same score as the leaderboard).
- **Response time** — how long the full answer took to arrive, scored
  relative to the other models in *this* run (lower is better).
- **Speed (tok/s)** — output tokens per second, so a model isn't penalized
  for writing a longer answer. Also relative to this run. Reasoning models
  (marked with "≈") report speed that includes hidden reasoning tokens on
  some providers, so it's approximate.
- **Cost** — relative total cost across this run's calls (lower is better).

A model with no successful responses (every cell errored or was blocked by
the policy gate) skips these bars — the column just shows the error/blocked
count instead.

### What matters most?

The priority selector (Balanced / Best quality / Fastest / Cheapest)
re-weights quality, response time, speed, and cost and re-ranks the
side-by-side columns instantly, client-side — no new run. The top column
gets a "Best for your priority" badge. Missing metrics are excluded and the
remaining weights are renormalized, so one `None` value doesn't skew the
score. The same weights drive the downloaded PDF, which shows the priority
you had selected and its best pick.

### Suggestions

Each column may suggest a same-provider, same-backend sibling model — e.g.
a faster or cheaper tier from the same provider you already used, never a
model from another provider or an OpenRouter `~latest` alias, and never a
model already in your comparison. Rules pick *which* sibling to suggest
(based on quality, response time/speed, or cost gaps); the judge model then
writes a short plain-English explanation of the trade-offs, falling back to
the rule's own one-line reason if that call fails or tries to name a model
outside the comparison. **This adds one extra judge call per run.**

Click **Try it** on a suggestion to swap that model into your selection
(it replaces the weak model, keeps your count the same) — it doesn't start
a new run automatically; click **Run comparison** again to test it.

### Repeat each prompt

Set "Repeat each prompt" to 2x or 3x to re-send each prompt multiple times
for steadier timing — response time and speed are averaged (with a spread
shown) across the repeats, while judge scoring and rule checks only run
once, on the first response. It still counts as a single run against the
rate limit, but it multiplies the number of model calls (and cost)
accordingly.

### Cost estimate

Before you run, "Estimated cost" gives a rough total: roughly
`chars / 4` input tokens plus 500 output tokens per call, times your
selected models, test cases, and repeats, priced from the catalog
(Bedrock/Vertex) or OpenRouter's live prices. It excludes judge calls and
shows "unavailable" for any selected model without pricing data. It
recalculates whenever you change your selection, test cases, or repeats.

### Judge disclosure

The side-by-side view and PDF both show "Judged by \<model\> via
\<backend\>". If the judge shares a provider with one of the models you're
comparing (e.g. an Anthropic judge scoring a Claude model), a note warns
that scores may lean in that model's favor — for important decisions,
re-run with a judge from a different provider.

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

Exposes 8 tools: `list_models`, `suggest_models`, `set_policy`, `evaluate_prompt`,
`run_comparison`, `list_runs`, `get_report`, `get_report_csv` — the same
functionality as the web app's API, minus file-upload policy support
(`set_policy` takes plain text).
State (policy, run history, rate limit) is per-process, since one stdio
connection is one client. It's a local-only interface (stdio requires the
server to run on the same machine as the client) — there's nothing to
"deploy" for it.

`run_comparison` and `evaluate_prompt` both take a `creds` argument —
`{"openrouter"?: str, "bedrock"?: {region, api_key} | {region, access_key_id,
secret_access_key, session_token?}, "vertex"?: {project, region, access_token}
| {project, region, service_account_json}}` — plus a `judge_backend` (default
`"openrouter"`) picking which backend runs the judge and policy gate. Creds for
the judge backend are always required, and malformed creds for any backend the
call uses are rejected up front, before the call counts against the rate limit. The
legacy `api_key` string argument still works and is treated as an
OpenRouter key (equivalent to `creds={"openrouter": api_key}`).

`run_comparison` also takes `models` (at most 4 — more returns `{"error":
"Pick at most 4 models."}` before the rate limiter is touched), `priority`
(`"balanced"` (default) | `"quality"` | `"fastest"` | `"cheapest"`, invalid
values error), and `repeats` (`1` (default), `2`, or `3`; anything else
errors) for repeating each prompt for steadier timing. Its result includes
everything a plain run does plus:

- `suggestions` — per-model same-provider/same-backend suggestion (or
  `null`) from the rule-based advisor.
- `advice` — the judge's plain-English explanation of the suggestions and
  trade-offs (empty string if that extra call failed or produced nothing
  usable).
- `ranking` — target ids ordered best-first for the requested `priority`
  (targets with no successful responses are excluded).
- `best_for_priority` — the first entry of `ranking`, or `null`.
- `judge` — `{"backend": ..., "model": ...}`, the backend and resolved
  model id that scored this run.
- `bias_note` — a warning string (or `""`) when the judge shares a provider
  with one of the compared models.

### Publishing to the official MCP registry

`server.json` is already prepared. Publishing itself requires your own
GitHub OAuth login, so run this yourself:

    brew install mcp-publisher   # or download a release binary
    mcp-publisher login github
    mcp-publisher publish

This registry (and its `server.json` schema) is new and evolves quickly —
check [the current publishing docs](https://github.com/modelcontextprotocol/registry)
before running the above in case anything's changed since this was written.

## Deploy (web app)

Includes a `render.yaml` for [Render](https://render.com): connect the
GitHub repo, Render auto-detects it as a Blueprint, and it deploys with
[gunicorn](https://gunicorn.org/) instead of Flask's development server.

**Must stay at `--workers 1`** (see `render.yaml`'s `startCommand`) — all
app state (policy text, run history, rate-limit counters) is a plain
in-memory dict per Python process, guarded by locks for thread-safety but
*not* shared across processes. `--threads 4` gives real concurrency within
that one process safely; adding more *workers* would let different
requests from the same browser session land on different processes with
different state, silently breaking policy gating, run history, and the
rate limit. State also resets on every restart/redeploy — expected for a
stateless-by-design demo app, not a bug.

For any other host: bind to `0.0.0.0` (not `127.0.0.1`, which is the
correct default for local-only use) — either run behind gunicorn the same
way (`gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT app:app`), or
set `HOST=0.0.0.0` if invoking `python app.py` directly. Once deployed,
the URL is reachable by anyone who has it; each visitor supplies their own
credentials for whichever backend(s) they use (never yours), so you aren't
billed for their model usage, but your hosting's bandwidth/CPU is shared
across everyone who uses it.

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
- Leaderboard with letter grades, a category breakdown (accuracy,
  rule-check pass rate, cost efficiency, response time, and speed —
  cost/response time/speed scored relative to the other models in the same
  run), and colorful charts of those scores in both the web view and the
  PDF report.
- Side-by-side comparison of up to 4 models with a "what matters most?"
  priority selector, same-provider/backend model suggestions, and a
  pre-run cost estimate — see
  [Comparing up to 4 models](#comparing-up-to-4-models).
- Per-prompt best-model recommendation: for each test case, which model
  handled that specific prompt best and why — computed from data already
  collected, no extra LLM call.
- Optional pre-run prompt quality feedback (an explicit "Evaluate prompt"
  action, not automatic) — clarity/specificity feedback before you spend
  a real run on a prompt that might need rewording.
- Download results as a PDF report or a CSV for spreadsheet analysis.
- The last 5 runs per session (browser cookie, or MCP server process)
  stay available to revisit or re-download without re-running them.
- Light and dark mode — follows your OS/browser preference by default, or
  toggle explicitly with the button in the header (persists via
  `localStorage`).
- Browse by provider shows the curated picks plus a "+N more" expansion
  (up to 10, sorted newest-first) pulled from OpenRouter's live catalog,
  so it's never limited to only the models hardcoded here.

## Notes

- `data/providers.json`'s "frontier" picks use OpenRouter's own
  self-updating `~provider/model-latest` alias ids (e.g.
  `~openai/gpt-latest`) where available, so they stay current without
  needing manual updates. The other curated (non-frontier) models are
  pinned to specific ids and, like any pinned model reference, can go
  stale as providers retire older versions — verify against OpenRouter's
  live `/models` endpoint if one stops working.
- Rate-limited to 3 runs per 8 hours per session (in-memory, resets on
  server restart) in both interfaces.
- All state is in-memory only, capped at 5 runs per session — nothing is
  persisted to disk.

## License

[MIT](LICENSE)
