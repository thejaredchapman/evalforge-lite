---
title: Troubleshooting and FAQ
nav_order: 8
---

# Troubleshooting and FAQ

This page lists the messages and situations people run into most, what causes them, and what to do. It ends with a short FAQ and notes for anyone reading the CSV or API output programmatically.

## Why this helps

- **Messages are quoted as the app shows them,** so you can search this page for the exact words you see.
- **Each entry names a cause and a fix,** not just a symptom.
- **The FAQ answers the "is it safe / is it accurate" questions** with facts from how the app is built.

## Before a run

### "Pick at least one model."

You clicked **Run comparison** with no model selected. Pick at least one model. Two to four makes a useful comparison.

### "Pick at most 4 models."

A run allows at most 4 targets. Remember that `X` and `X@bedrock` count as two. Deselect one and try again. The limit is enforced by the server as well as the page.

### "Add Amazon Bedrock credentials first." (or another backend name)

You selected a model on a backend whose credentials are empty, or the judge backend has no credentials. Open that backend's tab in the credentials panel and fill it in. See [Backends and credentials](backends-and-credentials.md). If a tab says **Provided by this server**, nothing is needed for that backend.

### "`[Backend]` credentials are required for the judge backend."

The judge (which scores answers, writes the verdict and checks your policy) always runs on the **judge backend** you chose, and that backend's credentials must be present even if none of your models use it. Either fill them in or change the judge backend to one you have credentials for.

### A message like "Bedrock region is missing or invalid." or "Vertex project is missing or invalid."

The server checks credential formats before it counts your run, so a typo does not use up an attempt. Correct the field named in the message. Formats are described in [Backends and credentials](backends-and-credentials.md#format-checks). Other messages of this kind: "Vertex credentials need an access_token or service_account_json.", "service_account_json is not valid JSON." and "Foundry credentials need exactly one of api_key or access_token."

### "OpenRouter credentials contain whitespace or control characters."

A key was pasted with a stray space or line break. Re-copy it without surrounding whitespace.

## Rate limits

### "Rate limit reached. Try again after `[time]`."

Each browser session gets **3 runs per rolling 8 hours**. The message shows when the oldest of those runs ages out. The prompt-evaluation button has its own separate allowance of 3 per 8 hours, and the MCP server has its own counters too.

The counters are in the server's memory. They reset if the server restarts, and a different browser session (or a cleared cookie) starts with a fresh allowance. Fixes: wait, or, if you run the app yourself, restart it. On a server someone else hosts, ask the operator.

### "The server's shared usage limit has been reached. Please try again later."

This appears only when the operator keeps a provider key on the server. All users share a cap, 50 uses per rolling 24 hours by default, on calls that use a server-held key. Wait, or ask the operator to raise `SERVER_KEY_DAILY_CAP`. See [Hosting and server-side keys](hosting-and-server-keys.md#the-daily-limit). If you have your own key for that backend, you cannot use it while the operator holds that backend; the server's key always wins.

## During a run

### A pop-up titled "A model call failed" or "N model calls failed"

One or more model calls returned an error. The pop-up shows the provider's error text (with your credentials redacted), plus buttons to **Copy details** and **Report an issue on GitHub**. When all the failures are on one backend it also has links to check that backend's status page or report a problem to it. You can reopen the details for one failed cell with its **Details** button, which opens a pop-up titled `[model] failed`. Other models in the same run are not affected; the failed cell shows `ERROR` and counts as no successful response.

Common causes:

- **Wrong or expired key or token.** Re-enter it. Short-lived tokens (Vertex access tokens, Foundry Entra tokens) expire quickly.
- **No access to the model.** Your account or key may lack access to that model. The provider's message usually says so.
- **"`[model]` is not available on `[backend]`."** The catalog has no route for that model on that backend. Pick a different target.
- **Timeouts.** Each model call times out after 60 seconds.
- **A provider outage.** Use the **Check status** link in the pop-up or the header's **Provider status** menu.

### A region warning (⚠) next to a model or beside Run comparison

The model is not listed for the region you chose on that backend. It is advice only and never blocks a run, because the region lists are curated snapshots that can lag behind reality. Switch to a region the warning suggests, or just run it. If it fails with a region or availability error, check the provider's own page. See [Backends and credentials](backends-and-credentials.md#regions-and-the-warning) and the **Where models run** page (`/availability`).

### A cell says it was blocked by policy

You loaded a company policy and the judge decided the prompt violates it for that model, so that model never received it. Each model's copy of a prompt is checked separately, so the same prompt can be blocked for one model and sent to another. The cell shows the clause and the reason. If the reason is **"Could not verify policy compliance."**, the check itself failed (judge unreachable, bad credentials for the judge backend, or an unreadable reply). The gate fails closed, so the prompt is blocked rather than let through. Fix the judge backend credentials and run again, or remove the policy. See [Web app guide](web-app.md#3-company-policy-optional).

Also check that the policy file was read correctly: `.pdf` files go through a PDF reader, and everything else must be valid UTF-8 text. A scanned PDF with no selectable text yields an empty policy, and with an empty policy no prompt is gated, so use a PDF with real text.

### "Could not evaluate prompt."

The **Evaluate prompt** judge call returned something unusable, or failed. Try again. If you see an error pop-up, check the judge backend's credentials.

### "Evaluation unavailable" under a response

The per-response evaluation call failed or returned something it could not parse. That response is left out of the evaluation half of the Quality score; the run is not affected. See [Comparing models](comparing-models.md).

### A score shows "N/A", or the judge note says "Could not parse judge response."

The judge's reply could not be read as the expected JSON, so there is no score for that cell. This is not counted as zero. Re-running usually fixes it.

### The run seems slow

A run makes many calls: every prompt for every target (times your repeat setting), plus judge calls. The server runs up to 8 at once. More targets, prompts, repeats, or a slow reasoning model all add time.

## Costs and scores

### Why are costs "estimates"?

OpenRouter reports its own cost per call. Bedrock, Vertex AI and Foundry do not, so EvalForge Lite estimates their cost from token counts and the per-million-token prices in its bundled catalog. They are not your cloud bill. A model with no catalog price shows as unavailable in the pre-run estimate. The pre-run **Estimated cost** is rougher still: it assumes about one token per four characters of prompt and 500 output tokens per call, and excludes judge calls. See [Comparing models](comparing-models.md#total-cost).

### Why do scores differ between runs of the same prompt?

Models do not give identical answers each time, and the judge is also a model. Response time and speed vary with network and provider load. Use **Repeat each prompt** (2x or 3x) for steadier timing; judge scoring and rule checks still use the first response only. Treat small differences as noise.

### Why did the judge favour a particular model?

If the judge comes from the same provider as one of the compared models, scores may lean toward it. The results show a bias note when this applies. For important decisions, re-run with a judge from a different provider. See [Comparing models](comparing-models.md#judge-disclosure-and-bias-note).

## Installing and starting

### "My `.env` values are not being used."

The app does not read `.env` by itself. Load it into your shell first, then start the app:

```bash
set -a; source .env; set +a
python app.py
```

### The page does not open at `http://localhost:8000`

Check that the terminal running `python app.py` is still open and shows no error. If port 8000 is taken, start it on another with `PORT=8001 python app.py` and open that port. If you are reaching the app from another machine, it must be bound to `0.0.0.0` (`HOST=0.0.0.0`); the default `127.0.0.1` is local only.

### My MCP client does not show the tools

Check that `uv` is installed and `uvx evalforge-lite` runs without errors in a terminal. In Claude Code, `claude mcp list` shows registered servers. Restart your client after adding a server. See [MCP server](mcp-server.md).

### The app is using a key I did not enter

If your shell already exports `OPENROUTER_API_KEY`, or the other variables listed in [Hosting and server-side keys](hosting-and-server-keys.md), the app treats them as operator-held server keys. (The AWS access-key variables count only together with `BEDROCK_REGION`.) Unset them in that shell, or start the app from a clean environment.

## FAQ

**Is anything saved to disk?**
No. Credentials, policy text and run history are held in memory only, and are gone when the server restarts. See [Privacy and limits](privacy-and-limits.md).

**Does it store my API keys?**
No. They are sent with each request, used for that request, and not kept. Server-side keys exist only if the operator sets them as environment variables.

**How long is my run history kept?**
The last 5 runs per browser session (or per MCP server process), in memory, until the server restarts.

**Can I add rule checks like "contains" or "max_length" in the web page?**
No, the page has only a Prompt and an optional Rubric per test case. Rule checks are available through the API (`/api/run`, `test_cases[].checks`) and the MCP `run_comparison` tool. See [MCP server](mcp-server.md#run_comparison).

**Why can't I pick more than 4 models?**
It is a fixed per-run limit, enforced by both the page and the server, to keep runs fast and costs predictable.

**Why do some catalog models stop working?**
Frontier picks for OpenAI, Anthropic and Google use OpenRouter's self-updating "latest" aliases, so they stay current. The other curated models are pinned to specific ids and can go stale when a provider retires an older version. If one stops working, check OpenRouter's live model list, or type the current id under **Custom model ID**. Region data is likewise a dated snapshot.

**Can I use the same model on two backends in one run?**
Yes. `X` and `X@bedrock` are separate targets, and both count toward the limit of 4.

**Are the curated "need" and "industry" tags benchmarks?**
No. They are a dated starting point for choosing models, not measurements.

**Where do I report a bug?**
Use the **Report an issue on GitHub** button in an error pop-up, which pre-fills the details, or see [CONTRIBUTING.md](https://github.com/thejaredchapman/evalforge-lite/blob/main/CONTRIBUTING.md). Remove any credentials before posting anything.

## Changes to exports and API fields

If you read the CSV export or the API and MCP result fields programmatically, and last looked before the four-model comparison and per-response evaluation updates, these are the differences:

- **CSV:** the `speed_score` column was renamed `response_time_score`. Two columns were added: `tokens_per_sec` (right after `latency_ms`) and `throughput_score` (right after `response_time_score`). The columns are now, in order: `prompt, model_id, status, response_text, judge_score, judge_rationale, checks_passed, checks_total, cost_usd, latency_ms, tokens, tokens_per_sec, accuracy_score, rule_checks_score, cost_efficiency_score, response_time_score, throughput_score, best_model_for_prompt, best_model_reason`, followed by seven evaluation columns: `answered_score, overall_eval, quality_score, instruction_following_score, completeness_score, helpfulness_score, safety_score`. The evaluation columns are blank for blocked or error cells, or when a response's evaluation is unavailable.
- **API and MCP:** `categories.speed` in a run result's `grades[<model>].categories` is now `categories.response_time`, and a new `categories.throughput` key sits alongside it. `categories` also gained an `evaluation` key.
- **Quality score:** `grades[<model>].score` ("Quality") may now be blended with the per-response evaluation score. See [Comparing models](comparing-models.md#how-the-grade-is-built).
- **Run result:** a new `cost` field; `stats[<model>]` gained `evaluation_avg` and `latency_vs_fastest`; each result row gained `latency_ranking`.
