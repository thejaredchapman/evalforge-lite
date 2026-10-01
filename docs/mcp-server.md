---
title: MCP server
nav_order: 6
---

# MCP server

EvalForge Lite includes an MCP server. MCP (Model Context Protocol) is a standard way for an AI assistant, such as Claude, to call tools. With the server installed, you can ask your assistant to compare models, and it runs the comparison and reads the results back to you in the same conversation. It offers the same engine as the web app through 9 tools.

The server runs on your own machine and talks to the assistant over standard input and output (stdio). It is not a website and there is nothing to deploy for it.

## Why this helps

- **Run comparisons from inside an AI assistant.** Describe what you want to test in plain language; the assistant builds the test cases, calls `run_comparison`, and explains the result.
- **Results stay in the conversation.** The full run result comes back to the assistant, so you can ask follow-up questions ("which one was cheapest?", "why did model B lose on prompt 2?") without leaving the chat.
- **One-line install.** With `uv` installed, `uvx evalforge-lite` needs no checkout and no virtual environment.
- **Rule checks are available here.** The web page has no boxes for rule-based checks (`contains`, `regex`, `json_valid`, `max_length`), but each test case you pass to `run_comparison` can carry a `checks` list.
- **Same safeguards.** Credentials are scrubbed from error text, the 4-model cap and the run limit apply, and the optional policy gate works.

## Install

You need [`uv`](https://docs.astral.sh/uv/) for the first three options.

### Run it directly

```bash
uvx evalforge-lite
```

This starts the server on stdio. You normally do not run it by hand; your assistant starts it for you using one of the options below.

### Add it to Claude Code

```bash
claude mcp add evalforge-lite -- uvx evalforge-lite
```

### Install the Claude Code plugin

The plugin bundles the same server.

```bash
claude plugin marketplace add thejaredchapman/evalforge-lite
claude plugin install evalforge-lite@evalforge
```

### Claude Desktop or another MCP client

Add this to the client's MCP configuration (for Claude Desktop, its `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "evalforge-lite": {
      "command": "uvx",
      "args": ["evalforge-lite"]
    }
  }
}
```

### Latest code from GitHub

```bash
uvx --from git+https://github.com/thejaredchapman/evalforge-lite evalforge-lite
```

### From a checkout

If you already followed [Getting started](getting-started.md), you can point a client at your virtual environment's Python and the `mcp_server.py` file. Use absolute paths:

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

Requires Python 3.10 or newer.

## The 9 tools

| Tool | What it does | Needs credentials? |
|---|---|---|
| `list_models` | Lists every provider and model in the catalog, each provider's frontier (flagship) model, and the curated need/industry tags. | No |
| `suggest_models` | Given a `model_id`, returns sibling models from the same family. | No |
| `list_availability` | Returns the availability snapshot: live OpenRouter listing status (refreshed at most every 6 hours) plus curated Bedrock, Vertex and Foundry region coverage. Same data as the web app's `/availability` page. | No |
| `set_policy` | Sets the company policy text (`policy_text`, plain text) used to gate prompts before any model is called. Returns `{"ok": true}`. | No |
| `evaluate_prompt` | Gets pre-run feedback on a prompt's clarity and specificity. | Yes (judge backend) |
| `run_comparison` | Runs test cases against models and scores them. | Yes |
| `list_runs` | Lists metadata (run id, time, winner) for the 5 most recent runs, newest first. | No |
| `get_report` | Returns a PDF report for a run, base64-encoded, as `pdf_base64`. | No |
| `get_report_csv` | Returns a CSV export for a run as `csv`, one row per prompt and model. | No |

**Why it helps:** the free tools (`list_models`, `suggest_models`, `list_availability`) let the assistant pick sensible models and check regions before it spends a run.

### `run_comparison`

Arguments:

| Argument | Meaning |
|---|---|
| `test_cases` | A list of objects. Each has a `prompt` and, optionally, a `rubric` (a description of a good answer, scored 1 to 5 by the judge) and/or `checks` (a list of rule checks, below). |
| `models` | A list of targets: `"<catalog id>"` for OpenRouter, or `"<catalog id>@bedrock"`, `"<catalog id>@vertex"` or `"<catalog id>@foundry"`. At most 4. |
| `creds` | Credentials, by backend (see below). |
| `api_key` | Legacy shortcut: a bare OpenRouter key, same as `creds={"openrouter": "..."}`. |
| `judge_backend` | Which backend runs the judge and policy gate: `"openrouter"` (default), `"bedrock"`, `"vertex"` or `"foundry"`. |
| `priority` | `"balanced"` (default), `"quality"`, `"fastest"` or `"cheapest"`. Used to rank the targets. |
| `repeats` | `1` (default), `2` or `3`. Re-sends each prompt for steadier timing. |

Rule checks look like this, and are run locally against each response with no extra model call:

```json
[
  {"type": "contains", "value": "refund"},
  {"type": "regex", "value": "^\\d{4}-\\d{2}-\\d{2}$"},
  {"type": "json_valid"},
  {"type": "max_length", "value": 500}
]
```

`max_length` is a number of characters. See [Comparing models](comparing-models.md) for how check results feed the grade.

The result includes everything a web run does, such as `grades`, `stats`, `results` and `verdict`, plus:

- `run_id` and `created_at`.
- `suggestions`: per target, a same-provider, same-backend suggestion or `null`.
- `advice`: the judge's plain-English explanation of the suggestions (an empty string if that call failed).
- `priority`, `ranking` (target ids best-first for the priority; targets with no successful response are left out) and `best_for_priority` (the first of `ranking`, or `null`).
- `judge`: the backend and resolved model id that scored the run.
- `bias_note`: a warning when the judge shares a provider with a compared model, otherwise an empty string.
- `cost`: `model_usd`, `judge_usd`, `total_usd` and `judge_calls` for the whole run (estimated for Bedrock, Vertex and Foundry).
- Per successful result cell, an `evaluation` (the per-response evaluation, or `{"available": false, "reason": "Evaluation unavailable."}`). Blocked and error cells have no `evaluation`.
- `stats[<target>]` gains `evaluation_avg` and `latency_vs_fastest`; each result row gains `latency_ranking`.

Errors come back as `{"error": "..."}` and do not use up a run when they are about the request itself, such as "Pick at most 4 models.", "Invalid priority.", "repeats must be 1, 2, or 3.", "Invalid judge_backend." or malformed credentials. The check happens before the run limit is touched.

### `evaluate_prompt`

Arguments: `prompt`, plus `creds` (or `api_key`) and `judge_backend` exactly as for `run_comparison`. It is a separate, explicit judge call and is never run automatically. It has its own allowance of 3 per 8 hours, separate from `run_comparison`'s. It returns a score out of 5 and feedback.

### `get_report` and `get_report_csv`

Both default to the most recent run; pass a `run_id` (from `list_runs` or the run result) to pick another. `get_report` also takes an optional `priority` to override the priority shown in the PDF's best-pick line. With no run available they return `{"error": "no_run_available"}`. The PDF comes back as base64 text, so the assistant needs to decode and save it for you; the CSV comes back as plain text.

## The `creds` shapes

`creds` is an object with one key per backend you use. Fill in only the ones you need:

```json
{
  "openrouter": "sk-or-v1-your-key-here",
  "bedrock": {"region": "us-east-1", "api_key": "your-bedrock-api-key"},
  "vertex": {"project": "my-gcp-project", "region": "us-central1", "access_token": "ya29.your-token"},
  "foundry": {"resource": "my-foundry-resource", "region": "eastus2", "api_key": "your-foundry-key"}
}
```

Alternatives per backend:

| Backend | Option A | Option B |
|---|---|---|
| Bedrock | `{region, api_key}` | `{region, access_key_id, secret_access_key, session_token?}` |
| Vertex AI | `{project, region, access_token}` | `{project, region, service_account_json}` |
| Foundry | `{resource, region, api_key}` | `{resource, region, access_token}` |

The judge backend's credentials are always required, unless the operator keeps that backend's credentials on the server (see [Server-side keys](#server-side-keys)). Credentials for any other backend are required only if one of your models uses it. Formats are checked up front; see [Backends and credentials](backends-and-credentials.md) for where to get each value and what the formats are.

## Limits and state

- **Run limit:** `run_comparison` is limited to 3 calls per rolling 8 hours. When you hit it, you get `{"error": "rate_limited", "reset_at": <unix time in seconds>}`.
- **Prompt-evaluation limit:** `evaluate_prompt` has its own 3 per 8 hours.
- **Models:** at most 4 per run.
- **State is per process.** The policy, the last 5 runs and both limits live in the memory of the running server. Restarting it (or your client restarting it) clears them. Nothing is written to disk.
- **Policy:** `set_policy` takes plain text only; there is no file upload in the MCP server.

See [Privacy and limits](privacy-and-limits.md) for all limits in one place.

## Server-side keys

If you set the operator environment variables described in [Hosting and server-side keys](hosting-and-server-keys.md) in the environment the MCP server starts in, then the tools use those credentials for the matching backends automatically, and you can call `run_comparison` and `evaluate_prompt` without passing `creds` for them. The server's credentials always win over anything you pass for that backend. Calls that use a server-held backend also count toward the shared daily cap (default 50 per rolling 24 hours); when it is spent you get `{"error": "rate_limited", ..., "message": "The server's shared usage limit has been reached. Please try again later."}`.

Note that if you already export something like `OPENROUTER_API_KEY` in your shell for other tools, the MCP server started from that shell will pick it up as a server-held key.

## Example prompts to type

Once the server is added, you can ask your assistant things like:

1. "List the EvalForge models that support reasoning and are tagged for coding."
2. "Using my OpenRouter key `<paste key>`, compare the Claude and GPT frontier models on this prompt: 'Summarize our refund policy in three sentences.' Use the rubric 'Accurate, under 60 words, no jargon.'"
3. "Run that again, but add `max_length` 400 and a `contains` check for the word 'refund', and rank by cheapest."
4. "Run one model on OpenRouter and the same model on Bedrock in us-east-1 (use the `@bedrock` target), and tell me which is faster."
5. "List my recent runs, then fetch the PDF report for the latest one."

Pasting a key into a chat sends it to the assistant provider as part of the conversation. If that concerns you, set the keys as environment variables in the environment that starts the MCP server instead (see above), which keeps them out of the conversation.

## Next steps

- [Comparing models](comparing-models.md) explains the grades and metrics in the result.
- [Backends and credentials](backends-and-credentials.md) covers where to get keys.
- [Troubleshooting and FAQ](troubleshooting-and-faq.md) lists common error messages.
