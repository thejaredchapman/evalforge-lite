# EvalForge Lite

<!-- mcp-name: io.github.thejaredchapman/evalforge-lite -->

Compare text LLMs across providers — OpenRouter, Amazon Bedrock, Google
Vertex AI, and Microsoft Foundry — bring your own credentials (or let the server hold them). Available as
a web app and as an MCP server.

## Setup

    python3.12 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # optional: judge-model overrides and server-side keys

Requires Python 3.10+ (the `mcp` package's floor); developed and tested on 3.12.

The app does **not** read `.env` by itself. To use the values in it, load them into your shell first: `set -a; source .env; set +a`, then start the app. (Or set the variables in your host's dashboard.)

## Web app

    python app.py

Open http://localhost:8000, add credentials for the backend(s) you want to
use (sent only to this server and not stored beyond the request — unless the
operator keeps keys on the server, see
[Server-side keys](#server-side-keys-optional-for-operators)), add test cases, pick models, and run. Set `PORT=<port>` to
run on a different port, or `FLASK_DEBUG=1` if you need Flask's
interactive debugger — it's off by default since this app handles live
credentials.

### Try it out

1. Open the credentials panel and fill in the backend(s) you'll use (see
   [Backends](#backends-openrouter-amazon-bedrock-google-vertex-ai-microsoft-foundry) below).
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

## Backends: OpenRouter, Amazon Bedrock, Google Vertex AI, Microsoft Foundry

By default every request carries its own credentials — nothing is read from
server env/config, and credentials are never stored beyond the request that
used them. Operators can optionally keep keys on the server instead; see
[Server-side keys](#server-side-keys-optional-for-operators).

- **OpenRouter** — a single API key.
- **Amazon Bedrock** — either a Bedrock API key (bearer token) or an AWS
  access key id + secret access key (optionally with a session token), plus
  a region.
- **Google Vertex AI** — either an OAuth access token or a service-account
  JSON key, plus a GCP project id and a region.
- **Microsoft Foundry** — either an API key or a Microsoft Entra ID access
  token, plus an Azure AI Foundry resource name and a region.

A model *target* is `"<catalog id>"` for OpenRouter, or `"<catalog
id>@bedrock"` / `"<catalog id>@vertex"` / `"<catalog id>@foundry"` to run
that same model on Bedrock, Vertex, or Foundry instead. In the UI, pick a
target by clicking a model's Bedrock, Vertex, or Foundry chip (shown under
any model the catalog has a route for) rather than typing the `@backend`
suffix by hand.

The **judge backend** picker (next to the credentials panel) selects which
backend runs the LLM judge and the policy gate — it can differ from the
backend(s) the models under test run on, but needs its own credentials
filled in.

Bedrock/Vertex/Foundry costs shown in the leaderboard and reports are
*estimates*, computed from the per-token prices in `data/providers.json`,
not costs reported back by AWS/GCP/Azure billing.

Some Bedrock/Vertex/Foundry routes are region-restricted: Vertex's Llama
MaaS models are only offered in certain regions (e.g. `us-east5`), Gemini
preview models may need the `global` region instead of a specific one, and
Foundry's Llama routes are only curated for a handful of regions. The
region dropdowns warn with a ⚠ when a selected model isn't listed for your
chosen region on that backend, and suggest which regions it is listed in —
see [Where models run](#where-models-run) below for the full picture.

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

(`.env` is already git-ignored. Never commit it.) In `.env`, keep the Vertex
JSON on one line inside single quotes, like `.env.example` shows. (Or use the
`export VERTEX_SERVICE_ACCOUNT_JSON="$(cat service-account.json)"` form below.)

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
`-e NAME=value` or `--env-file`. Never put keys in `render.yaml`, any
Dockerfile you write, or git.

### Step 3 — Check that it worked

Open the app. The credentials tab for that backend should say **Provided by
this server** and show no input boxes.

Or check from a terminal (this lists backend names and regions only — never
keys):

    curl -s http://localhost:8000/api/catalog | python3 -m json.tool | grep -A8 server_backends

### The daily limit

Because users spend *your* key, the server counts every run (and every prompt
check) that uses a server-held key. The default is **50 per rolling 24 hours,
shared by everyone**. When it is reached, people see "The server's shared
usage limit has been reached. Please try again later."

- Change it with `SERVER_KEY_DAILY_CAP`. `0` blocks every call that needs a server-held backend. To let users enter their own keys again, unset that backend's variables.
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
- **The app uses a key you did not set up.** If you already export `OPENROUTER_API_KEY` (or the AWS/other variables above) in your shell for other tools, this app will pick it up and use it as a server key. Unset it first if you did not mean that.
- **Bedrock still asks for a region.** `BEDROCK_REGION` must be set along with a key.


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
re-weights quality, response time, speed, and cost instantly, client-side —
no new run. It does **not** reorder the side-by-side columns; instead the
column that scores best for the selected priority gets a "Best for
\<priority\>" badge, shown only once at least 2 models have successful
results (with a single result there's nothing to compare, so no badge is
shown). Missing metrics are excluded and the remaining weights are
renormalized, so one `None` value doesn't skew the score. The same weights
drive the downloaded PDF, which shows the priority you had selected and its
best pick.

### Suggestions

Each column may suggest a same-provider, same-backend sibling model — e.g.
a faster or cheaper tier from the same provider you already used, never a
model from another provider or an OpenRouter `~latest` alias, and never a
model already in your comparison. Rules pick *which* sibling to suggest
(based on quality, response time/speed, or cost gaps); the judge model then
writes a short plain-English explanation of the trade-offs, falling back to
the rule's own one-line reason if that call fails or tries to name a model
outside the comparison. **This adds one extra judge call per run.**

Click **Try it** on a suggestion to swap it into your selection: if the
weak model it's replacing is still selected, the suggestion takes its place
(your count stays the same); if you've already deselected that model, the
suggestion is just added instead, subject to the 4-model cap. It doesn't
start a new run automatically — click **Run comparison** again to test it.

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
After the run, the cost banner above the leaderboard shows the actual
total instead, judge calls included — see
[Per-response evaluation, latency comparison & total cost](#per-response-evaluation-latency-comparison--total-cost).

### Judge disclosure

The side-by-side view and PDF both show "Judged by \<model\> via
\<backend\>". If the judge shares a provider with one of the models you're
comparing (e.g. an Anthropic judge scoring a Claude model), a note warns
that "the judge ... is from the same family as ..." and that scores may
lean in that model's favor — for important decisions, re-run with a judge
from a different provider.

### Per-response evaluation, latency comparison & total cost

Every successful response gets a combined judge call that scores six
criteria 1-5: whether it **answered the question**, **quality**,
**instruction following**, **completeness**, **helpfulness**, and
**safety** — plus strengths, weaknesses, a short reasoning paragraph, and
an overall 1-5 score. It's collapsible under each response
("Evaluation"), open by default for the first prompt. These scores blend
into **Quality**: if a rubric or rule checks were also used, that
judge-score/rule-check blend is further averaged 50/50 with the
evaluation's score; with neither, Quality *is* the evaluation score; with
no successful evaluation either, Quality stays unscored ("N/A"). If a
response's evaluation call fails or returns something unparseable, its
card shows "Evaluation unavailable" and that response is simply excluded
from the evaluation half of Quality — it never fails the run.

Each side-by-side column also shows "Overall eval x/5" and how its average
response time compares to the fastest model in the run (e.g. "1.8x slower
than fastest (2,340 ms)", or "Fastest"). A **Latency comparison** panel
below the leaderboard shows this per-prompt as a bar per model (fastest
highlighted), with the run's averages at the bottom.

A **cost banner** at the top of the results totals the whole run: model
calls plus every judge call (the rubric judge, the per-response
evaluation, the policy gate, the overall verdict, and the suggestion
explainer) — e.g. "This run cost ≈ $0.0123 — models $0.0101 + judge
$0.0022 (6 judge calls)." As with the Bedrock/Vertex/Foundry model costs
elsewhere in this app, judge costs on those backends are estimates from
catalog prices, not provider billing; the banner notes this whenever any
compared model uses one of those backends.

## Where models run

The `/availability` page (linked from the header) shows, for every catalog
model: whether it's currently listed on OpenRouter (checked live, cached
for up to 6 hours) and which regions it's curated for on Bedrock, Vertex,
and Foundry. It's filterable by model/provider name, backend, and region,
and sortable by clicking any column header. Curated region data is
dated and sourced — it can lag reality, so verify on the provider's own
page before relying on it for a production decision.

## Provider status & reporting problems

The header's "Provider status" menu links to each backend's live status
page (OpenRouter, AWS, Google Cloud, Azure), and the footer links to each
backend's own place to report a problem (GitHub issues for this app itself,
plus each cloud provider's support/feedback page). When a model call fails,
the error popup also adds "Check \<backend\> status" and "Report to
\<backend\>" links for the specific backend that failed.

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

Exposes 9 tools: `list_models`, `suggest_models`, `set_policy`, `evaluate_prompt`,
`run_comparison`, `list_availability`, `list_runs`, `get_report`, `get_report_csv`
— the same functionality as the web app's API, minus file-upload policy support
(`set_policy` takes plain text).
State (policy, run history, rate limit) is per-process, since one stdio
connection is one client. It's a local-only interface (stdio requires the
server to run on the same machine as the client) — there's nothing to
"deploy" for it.

`run_comparison` and `evaluate_prompt` both take a `creds` argument —
`{"openrouter"?: str, "bedrock"?: {region, api_key} | {region, access_key_id,
secret_access_key, session_token?}, "vertex"?: {project, region, access_token}
| {project, region, service_account_json}, "foundry"?: {resource, region, api_key}
| {resource, region, access_token}}` — plus a `judge_backend` (default
`"openrouter"`) picking which backend runs the judge and policy gate. Creds for
the judge backend are always required (unless the operator holds that backend's credentials on the server, see [Server-side keys](#server-side-keys-optional-for-operators)), and malformed creds for any backend the
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
- `cost` — `{"model_usd", "judge_usd", "total_usd", "judge_calls"}` for the
  whole run (estimated for Bedrock/Vertex/Foundry calls, both model and
  judge).
- Each successful result cell gains `evaluation` — the per-response
  evaluation (or `{"available": false, "reason": "Evaluation unavailable."}`
  if that call failed or was unparseable). Blocked and error cells have no
  `evaluation` key.
- `stats[<model>]` gains `evaluation_avg` and `latency_vs_fastest`.
- Each result row gains `latency_ranking` — that prompt's successful
  targets ordered fastest-first with their latency in ms.
- `list_availability` returns the same snapshot as `/api/availability`: live
  OpenRouter listing status (6-hour cache) plus curated Bedrock/Vertex/Foundry
  region coverage.

### Install the MCP server (for users)

Once the package is on PyPI you don't need a checkout or a virtualenv. With
[`uv`](https://docs.astral.sh/uv/) installed:

    uvx evalforge-lite

Add it to Claude Code in one line:

    claude mcp add evalforge-lite -- uvx evalforge-lite

Or, from Claude Code, install the plugin (it bundles the same server):

    claude plugin marketplace add thejaredchapman/evalforge-lite
    claude plugin install evalforge-lite@evalforge

To use the latest code from GitHub before a release is on PyPI:
`uvx --from git+https://github.com/thejaredchapman/evalforge-lite evalforge-lite`.

### Publishing (for the maintainer)

Everything below needs *your* accounts, so none of it is automated. The files
are already in the repo: `pyproject.toml`, `server.json`, and
`.claude-plugin/` (`plugin.json`, `marketplace.json`) plus `.mcp.json`. The
packaging layout and its reasons are explained at the top of `pyproject.toml`.

**Before every release**, bump the version in all four places and keep them
identical: `pyproject.toml`, `server.json` (twice: the top-level `version` and
`packages[0].version`), and `.claude-plugin/plugin.json`. `pytest` checks that
they agree (`tests/test_packaging.py`).

**1. Publish to PyPI** (the registry only stores a pointer to this package):

    pip install build twine
    python -m build
    twine upload dist/*      # asks for your PyPI API token

Check the new project page, then try it: `uvx evalforge-lite`. The README
carries the `mcp-name: io.github.thejaredchapman/evalforge-lite` marker that
proves to the MCP registry that you own this PyPI package — don't remove it.

**2. Publish to the official MCP registry** (after step 1 is live):

    brew install mcp-publisher     # or download a release binary
    mcp-publisher validate         # checks server.json
    mcp-publisher login github     # opens a browser for GitHub sign-in
    mcp-publisher publish

The name must start with `io.github.thejaredchapman/`, which it does. This
registry is new and changes quickly — check
[the current publishing docs](https://github.com/modelcontextprotocol/registry)
if a command above stops working.

**3. Your own Claude Code marketplace** (nothing to submit; pushing to GitHub
is enough). Before pushing, check the files:

    claude plugin validate --strict .

Then anyone can run the two `claude plugin ...` commands shown in
[Install the MCP server](#install-the-mcp-server-for-users). The plugin runs
`uvx evalforge-lite`, so step 1 must be done first.

**4. Anthropic's directory** (claude.ai and Cowork). Submit from
<https://claude.ai/directory/manage> (needs a paid claude.ai plan). Run
`claude plugin validate --strict .` and read the
[pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist)
first; each version is reviewed.

**Before making it public:** by default every user brings their own provider
key, which is the safe setup for a public tool. Do not set the server-side key
variables on a deployment you share publicly unless you want to pay for your
users' calls (see [Server-side keys](#server-side-keys-optional-for-operators)).

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
billed for their model usage — unless you set server-side keys (see
[Server-side keys](#server-side-keys-optional-for-operators)), in which case
your key is used and billed, up to the daily limit. Either way, your hosting's bandwidth/CPU is shared
across everyone who uses it.

## Test

    pytest tests/ -v

Every LLM/HTTP call is mocked (or, for the MCP end-to-end tests, exercised
with an empty test-case/model list that never reaches the network) — the
suite needs no API key and makes no network calls.

## Upgrading

If you're integrating against the CSV export or the API/MCP `categories`
field from before the 4-model comparison work, note:

- CSV: the `speed_score` column was renamed `response_time_score`. Two
  columns were added: `tokens_per_sec` (right after `latency_ms`) and
  `throughput_score` (right after `response_time_score`). Current column
  order is `..., latency_ms, tokens, tokens_per_sec, accuracy_score,
  rule_checks_score, cost_efficiency_score, response_time_score,
  throughput_score, best_model_for_prompt, best_model_reason`.
- API/MCP: `categories.speed` in a run result's `grades[<model>].categories`
  is now `categories.response_time`, and a new `categories.throughput` key
  was added alongside it.
- CSV: 7 trailing columns were added after `best_model_reason`:
  `answered_score, overall_eval, quality_score, instruction_following_score,
  completeness_score, helpfulness_score, safety_score` (blank for
  blocked/error cells or when a response's evaluation is unavailable).
- API/MCP: `grades[<model>].categories` gained an `evaluation` key, and
  `grades[<model>].score` ("Quality") may now be blended with the
  per-response evaluation score — see
  [Per-response evaluation, latency comparison & total cost](#per-response-evaluation-latency-comparison--total-cost).
  A run result gained `cost`; `stats[<model>]` gained `evaluation_avg` and
  `latency_vs_fastest`; each result row gained `latency_ranking`.

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
- Per-response evaluation (answered/quality/instruction following/
  completeness/helpfulness/safety, strengths, weaknesses, reasoning,
  overall score), a latency comparison panel, and a total-cost banner for
  the whole run (model calls plus every judge call) — see
  [Per-response evaluation, latency comparison & total cost](#per-response-evaluation-latency-comparison--total-cost).
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
- Bedrock/Vertex/Foundry region data in `data/regions.json` and each
  model's `routes.<backend>.regions` in `data/providers.json` are curated
  snapshots (dated, with a source link on the `/availability` page) — not
  a live per-account listing. They can go stale as providers add or drop
  regions; verify on the provider's own page if a run fails with a
  region/availability error.
- All state is in-memory only, keeping the last 5 runs per session — nothing is
  persisted to disk.

## Contributing

Contributions are welcome: bug reports, model-catalog updates, new checks,
docs, and new backends. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup,
tests, and the pull request process. When the app shows an error, the popup's
**Report an issue on GitHub** button opens a pre-filled bug report.

## License

[MIT](LICENSE)
