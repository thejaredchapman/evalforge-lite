# EvalForge Lite

<!-- mcp-name: io.github.thejaredchapman/evalforge-lite -->

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

Open http://localhost:8000, paste your OpenRouter API key (never sent
anywhere but this server, never stored server-side beyond the request),
add test cases, pick models, and run. Set `PORT=<port>` to run on a
different port, or `FLASK_DEBUG=1` if you need Flask's interactive
debugger — it's off by default since this app handles live API keys.

### Try it out

1. Paste an OpenRouter API key into the "OpenRouter API key" field.
2. Add a test case: a prompt, and optionally a rubric (scored by an LLM
   judge) and/or rule-based checks (e.g. "contains", "max_length").
3. Pick two or more models, ideally from different providers, from the
   frontier list or by browsing providers.
4. Click **Run comparison** — you'll get a leaderboard with letter grades,
   per-model cost/latency, and an overall verdict, plus a per-cell view of
   every model's actual response.
5. Download a PDF report or CSV export of the run.

**Heads up before you click Run repeatedly while testing:** it's
rate-limited to 3 runs per 8 hours per browser session (resets if you
restart the server) — see [Notes](#notes).

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
OpenRouter key (never yours), so you aren't billed for their usage, but
your hosting's bandwidth/CPU is shared across everyone who uses it.

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
  rule-check pass rate, cost-efficiency, speed — cost/speed scored
  relative to the other models in the same run), and colorful charts of
  those scores in both the web view and the PDF report.
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
