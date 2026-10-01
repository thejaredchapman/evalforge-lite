---
title: Privacy and limits
nav_order: 9
---

# Privacy and limits

This page states, as plainly as possible, what happens to your data when you use EvalForge Lite, what is kept and for how long, and every limit the app enforces. It describes how the software behaves. If you use a copy hosted by someone else, that operator also controls the server, its logs and its hosting, which this page cannot describe.

## Why this helps

- **You can judge the risk before you paste anything.** Each kind of data is listed with where it goes.
- **No surprises about storage.** The app has no database and writes nothing to disk, so there is nothing to clean up.
- **Every limit is in one table,** so you can plan a run against the real numbers.

## Where your data goes

| Data | Where it goes | Kept? |
|---|---|---|
| Your credentials (API keys, tokens, service-account JSON) | Sent from your browser to the EvalForge Lite server with each request, and from there to the provider you chose (OpenRouter, AWS Bedrock, Google Vertex AI or Microsoft Foundry). | Used for that request only. Not written to disk, not saved in your browser. Exact values and common key and token formats are removed from error text sent to you or written to the log. |
| Your prompts and rubrics | Sent to every model you selected, and to the judge model, which scores answers and writes the evaluation and verdict. | Kept in memory as part of the run result, in run history (below). |
| Models' responses | Returned to you, and sent to the judge for scoring and evaluation. | Kept in memory as part of the run result. |
| Your company policy text | Held on the server for your session, and sent to the judge model so it can check compliance, once per prompt per model (each model's copy of a prompt is checked separately). | In memory for the session until the server restarts. Not written to disk. |
| Run results | Shown in the page and available to download as PDF or CSV. | The last 5 runs per session, in memory. |
| Catalog and region data | Read from files bundled with the app. The server also fetches OpenRouter's public model list, which needs no key, for browsing and the availability page. | The availability result is cached for up to 6 hours. |
| Theme choice (light or dark) | Stored by the page in your browser's `localStorage`. | Until you clear it. |
| Session cookie | The server sets a cookie named `evalforge_session` (HttpOnly, SameSite Lax) so it can recognise your browser for the policy, history and limits. | It has no expiry date set, so browsers normally drop it when they close. It holds a random id only. |

Note that your prompts, rubrics and responses go to the model providers you choose, and are handled under their terms, not this project's. Do not paste a credential or sensitive data into a Prompt, Rubric or policy unless you are comfortable with it reaching those providers. EvalForge Lite never puts your credentials into a prompt itself.

If an operator keeps provider keys on the server, those keys never reach your browser and are removed from error messages. Calls then use the operator's account, and the operator is billed. See [Hosting and server-side keys](hosting-and-server-keys.md).

## What is stored, and for how long

- **All state is in the server process's memory.** That means the policy text, each session's run history, and the rate-limit counters.
- **Nothing is written to disk.** There is no database.
- **A restart clears everything.** Restarting or redeploying the server wipes the policy, run history and limit counters.
- **The MCP server works the same way,** with one set of state per running process, since one stdio connection is one client.
- **Limits are not persistent.** The 3-runs-per-8-hours counter resets when the server restarts, and a new browser session starts with its own counter.

## Limits

| Limit | Value | Applies to |
|---|---|---|
| Targets (models) per run | 4. `X` and `X@bedrock` count as two. | Web app, API and MCP, enforced server-side. |
| Runs | 3 per rolling 8 hours per browser session (web) or per server process (MCP). | `Run comparison` and `run_comparison`. |
| Prompt evaluations | 3 per rolling 8 hours, counted separately from runs, per session or process. | **Evaluate prompt** and `evaluate_prompt`. |
| Run history | Last 5 runs per session (web) or process (MCP). | Recent runs, downloads and `list_runs`. |
| Repeats | 1, 2 or 3 per prompt. A repeat run counts as one run against the limit but multiplies the model calls. | Both interfaces. |
| Shared server-key cap | 50 per rolling 24 hours by default, shared by all users; set by the operator with `SERVER_KEY_DAILY_CAP` (`0` blocks calls that need a server-held backend). | Only when the operator holds a provider key on the server. |
| Model call timeout | 60 seconds per call. | All backends. |
| Number of test cases | No limit is set by the app, but each one multiplies the number of calls and the cost. | Both interfaces. |
| Policy file types | `.txt`, `.md`, `.pdf` in the web app (a `.pdf` is read as a PDF, anything else as UTF-8 text); plain text through `set_policy` in MCP. | Policy gate. |

The first two limits can hit before any model is called, and format errors in credentials are caught before a run is counted. The usage windows are rolling: a slot frees up 8 hours (or 24 hours for the server-key cap) after the call that used it.

## What EvalForge Lite does not do

- It does not store your credentials, and does not hold any provider key of its own. Server-side keys exist only if the operator configures them.
- It does not keep history across restarts, or share history between browsers or people.
- It does not report your actual cloud bill. Costs for Bedrock, Vertex AI and Foundry are estimates from catalog prices. See [Comparing models](comparing-models.md#total-cost).
- It does not produce benchmarks. Scores come from your prompts, a judge model and rule checks, and a judge can be biased toward its own provider. The curated need and industry tags are a dated starting point, not measurements. See [Comparing models](comparing-models.md#limits-of-these-numbers).
- It does not guarantee that a model is available in a region. Region data is a curated snapshot. See [Backends and credentials](backends-and-credentials.md#regions-and-the-warning).
- It does not provide accounts, logins or access control. Anyone who can open a hosted copy can use it, so an operator who wants a private tool should put it behind their own login or VPN.
- The policy gate is a judge model's opinion, not a legal or compliance guarantee. It fails closed, which means that when the check cannot run, the prompt is blocked.

## Related pages

- [Backends and credentials](backends-and-credentials.md): how credentials are handled per backend.
- [Hosting and server-side keys](hosting-and-server-keys.md): what an operator controls.
- [Troubleshooting and FAQ](troubleshooting-and-faq.md): what the limit messages say and what to do.
