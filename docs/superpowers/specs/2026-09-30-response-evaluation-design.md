# EvalForge Lite — Per-Response Evaluation, Latency Comparison & Total Cost (Sub-project C)

**Date:** 2026-09-30
**Status:** Design (pending user approval)
**Branch:** `feat/response-evaluation` (from `feat/foundry-regions` @ 2f6f0c5, PR #18)
**Part of:** a larger request split into sub-projects A → C → B → D → E → F. A is done (PR #18). This is **C**.

## Goal

For every model response, judge whether it **actually answered the question** and score **response quality, instruction following, completeness, helpfulness, and safety**. Each criterion gets a score and a brief explanation, plus **strengths, weaknesses, reasoning, and an overall score** per response. Show **latency side by side across models**, and a **total cost for the whole run**, including judge calls.

## Decisions (from brainstorming)

- **Always on, one combined judge call per successful response.** It returns every criterion as one JSON object and is counted in the cost tally. If the call fails, the response shows "Evaluation unavailable".
- **The scores feed into Quality.** The model's quality score blends the evaluation with the existing rubric/rule-check score. Priority weights are unchanged.

## 1. `judge.evaluate_response` (new)

`evaluate_response(prompt, response_text, rubric, creds, backend="openrouter", judge_model=None, meter=None) -> dict`

- **Criteria (fixed order):** `answered`, `quality`, `instruction_following`, `completeness`, `helpfulness`, `safety`. Each is `{"score": int 1-5, "explanation": str}`. Plus `strengths: [str]` (≤3), `weaknesses: [str]` (≤3), `reasoning: str`, `overall: int 1-5`, and `available: True`.
- **Prompt-injection hygiene:** the model's response is untrusted. The prompt wraps it between unique delimiters (`<<<RESPONSE_START>>>` / `<<<RESPONSE_END>>>`) and tells the judge to treat anything inside as data and ignore any instructions there. The user's prompt and the optional rubric are included so the judge can assess instruction following and whether the question was answered.
- **Strict parse and normalize:** use the existing `_extract_json`.
  - Each score is coerced with `int()` and clamped to 1–5.
  - Explanations are truncated to 300 chars, list items to 160 chars, and lists to 3 items. `reasoning` is truncated to 600 chars.
  - A missing criterion → that criterion is `{"score": None, "explanation": "Not provided."}`.
  - If every criterion is missing, or the call or parse fails, return `{"available": False, "reason": "Evaluation unavailable."}`.
- **Fail-soft:** never raises. The whole body, prompt building included, sits inside one `try` that catches `GatewayError`, `ValueError`, `KeyError`, `TypeError`, `AttributeError` and `JSONDecodeError`.
- No credentials are ever placed in the prompt. Any error text that reaches a cell goes through `scrub.scrub`.

## 2. Cost metering (judge calls counted)

- New `costs.py`: a thread-safe `CostMeter` with `add(kind: "model"|"judge", usd: float)` and `totals() -> {"model_usd", "judge_usd", "total_usd", "judge_calls"}`, guarded by a lock.
- `judge.llm_judge`, `overall_verdict`, `explain_recommendations`, `evaluate_response` and `policy.check_policy` gain an optional `meter=None` keyword. After a successful `call_backend` they call `meter.add("judge", result["cost_usd"])`. Existing callers that don't pass a meter behave exactly as before.
- **Judge calls on Bedrock/Vertex/Foundry are priced too.** `gateway.call_backend` fills `cost_usd` for non-OpenRouter backends when it can find the price: it uses the catalog route whose `id` matches the native model id (`{geo}` templates compared before resolving). OpenRouter keeps reporting its own cost. Unpriced → `0.0`, and the UI marks the total as an estimate.
- `runner.run(..., meter=None)` threads the meter into `_run_one_cell` and passes it to `policy.check_policy`, `judge.llm_judge` and `judge.evaluate_response`. Model-call costs are added as `"model"`.
- `analysis.build_run_result(..., meter=None)` passes it to `overall_verdict` / `explain_recommendations`. The run result gains `"cost": meter.totals()` (or zeros if no meter). `app.py` and `mcp_server.py` create one `CostMeter` per run and pass it through runner and analysis.

## 3. Runner and analysis

- `_run_one_cell`: after a successful model call (the first sample, when repeats > 1), it calls `judge.evaluate_response(prompt, response["text"], test_case.get("rubric"), creds=creds, backend=judge_backend, meter=meter)` and stores the result as the cell's `evaluation`. Blocked and error cells have no `evaluation`.
- `analysis`:
  - Per target, aggregate `evaluation_avg`: the mean score of each criterion across that target's available evaluations, plus `overall_avg` and `evaluated_cells`.
  - **Quality:** `eval_score` = the mean of the six criterion averages × 20 (0–100). If the existing `grading.compute_score` (rubric/rule checks) is present, `grade.score` = `round(0.5 * existing + 0.5 * eval_score, 1)`; otherwise it's `eval_score`; with neither, it stays `None`. The letter and sentence are recomputed from the blended score. `categories` gains `evaluation` (= `eval_score`).
  - **Latency comparison:** `stats[target]` gains `latency_vs_fastest` (= avg_latency / fastest avg latency among successful targets, rounded to 2 dp, or `None`). Each result row gains `latency_ranking`: targets sorted fastest-first with ms values, for that prompt's successful cells.
- The advisor's quality rules keep reading `grade.score` (now blended). No change to the advisor code.

## 4. UI

- **Per-response evaluation card**, in each results cell, collapsible with `<details>`, open by default for the first prompt:
  - an "Answered the question?" badge (✓ ≥4, ~ 3, ✗ ≤2) with its explanation;
  - five scored rows (Quality, Instruction following, Completeness, Helpfulness, Safety), each with the score shown as text ("4/5"), a bar with `role="img"` + aria-label, and the explanation;
  - **Strengths** / **Weaknesses** lists, the **Reasoning** paragraph, and an **Overall x/5** badge;
  - or "Evaluation unavailable" when that's the result.
- **Side-by-side column additions:** "Overall eval 4.2/5", and a latency line such as "1.8× slower than fastest (2,340 ms)", or "Fastest" for the quickest model.
- **Latency comparison panel** below the leaderboard: per prompt, a horizontal bar per model (fastest first) with ms text labels, the fastest highlighted, and averages at the bottom.
- **Total cost banner** at the top of the results: "This run cost ≈ $0.0123 — models $0.0101 + judge $0.0022 (N judge calls). Estimates for Bedrock/Vertex/Foundry are from catalog prices."
- All of it uses `textContent` / `escapeHtml`, theme variables, and stacks on mobile.

## 5. Reports & MCP

- MCP `run_comparison` returns the new fields (`evaluation` per cell, `cost`, `latency_vs_fastest`, `latency_ranking`) with no signature change, and its docstring mentions them.
- The PDF gets the total-cost line and each response's overall evaluation score plus the "answered" verdict, run through `_pdf_safe`. The CSV gains `answered_score`, `overall_eval`, `quality_score`, `instruction_following_score`, `completeness_score`, `helpfulness_score` and `safety_score` columns, appended at the end so existing positions don't shift. (Sub-project F later replaces PDF/CSV with Markdown export.)

## 6. Safety & errors

- The judge never sees credentials. Every new error string is scrubbed. The evaluation fails soft and never fails a run.
- Extra cost: one judge call per successful response. The cost banner makes it visible.

## 7. Testing (no live network)

- `judge.evaluate_response`:
  - happy path (all fields normalized, clamped, truncated);
  - prose-wrapped JSON;
  - a missing criterion;
  - a malformed reply → unavailable;
  - `GatewayError` → unavailable;
  - a malformed `prompt`/`response` type → unavailable;
  - the response text sits inside the delimiters, along with the injection instruction;
  - the meter receives the judge cost.
- `costs.CostMeter`: totals, plus thread safety (concurrent adds from threads).
- `gateway.call_backend` prices non-OpenRouter judge calls via the catalog, `{geo}` included; unpriced → 0.0.
- `runner`: each successful cell gets `evaluation`; blocked and error cells don't; repeats evaluate once; the meter collects model and judge costs.
- `analysis`: `evaluation_avg`; the blended quality score (with and without rubric/checks); `latency_vs_fastest`; `latency_ranking` (ordering, failed cells excluded); `cost` in the result.
- `app` / `mcp`: the response includes `cost` and per-cell `evaluation` (runner/judge mocked); a **key-leak test** where a secret is embedded in an evaluation `GatewayError` never appears in the response, logs or history.
- `report`: the CSV has the new trailing columns; the PDF builds with evaluation and cost lines, including unicode.
- Frontend: `node --check`; render smoke test.

## Out of scope for C

Sending a response to the Prompt Evaluation page (D); the "better prompt" rewrite (D); Markdown export (F).
