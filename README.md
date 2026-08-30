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
