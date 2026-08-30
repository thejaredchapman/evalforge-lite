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
