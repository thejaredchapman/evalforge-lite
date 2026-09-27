# EvalForge Lite — Four-Model Comparison, Speed/Quality Metrics & Same-Provider Suggestions

**Date:** 2026-09-26
**Status:** Design (pending user review) — revised with review additions §8
**Branch:** `feat/four-model-comparison` (stacked on `feat/bedrock-vertex-backends` / PR #17)

## Goal

Let a user compare **up to four** models side by side on **quality**, **response time**, **speed**
(throughput), and cost, then get **suggestions for a better-fitting model from the same provider and
the same backend catalog** — never a model from another provider. Help the user pick by letting them
say what matters most and explaining how to read the results.

## Decisions (from brainstorming)

- **Cap at 4** selected targets, plus a dedicated side-by-side results view. `X` and `X@bedrock` count
  as two targets.
- **Response time** = average end-to-end latency (ms). **Speed** = output tokens per second
  (throughput), so a model isn't penalized for writing a longer answer.
- **Suggestions: both.** Deterministic rules choose *which* sibling to suggest. The judge model then
  writes a short plain-English explanation around those rule-chosen picks. The LLM never chooses
  models.
- **Priority selector** (Balanced / Best quality / Fastest / Cheapest) re-ranks results client-side
  and marks a "Best for your priority" pick. Also a "How to read this" help box.

## 1. Four-model cap

- `app.py` `_validate_run_body`: `models` must have 1–4 entries → otherwise `400 "Pick between 1 and 4 models."`
  (checked before creds and the rate limiter, like the other validation).
- `mcp_server.run_comparison`: same rule, same message, returned as `{"error": ...}`.
- A shared constant `config.MAX_MODELS = 4` is used by both, and exposed to the page via `/api/catalog`
  (`"max_models": 4`) so the frontend doesn't hard-code it.
- Frontend: a "Selected N / 4" counter near the Run button. Clicking a 5th badge or chip does not
  select it and shows "You can compare up to 4 models — deselect one first." in `#run-status`.

## 2. Metrics

`grading.category_scores` keeps its absolute `accuracy` and `rule_checks`, **renames** the relative
latency score from `speed` to **`response_time`**, and **adds** a relative **`throughput`** score:

| Key | Label in UI/report | Source | Better |
|---|---|---|---|
| `accuracy` | Accuracy | judge avg × 20 (unchanged) | higher |
| `rule_checks` | Rule Checks | pass rate × 100 (unchanged) | higher |
| `cost_efficiency` | Cost Efficiency | relative total cost (unchanged) | lower cost |
| `response_time` | Response Time | relative avg latency (was `speed`) | lower latency |
| `throughput` | Speed (tok/s) | relative avg output tokens/sec | higher |

- Every client returns `output_tokens`. Bedrock and Vertex already do; `openrouter.call_model` adds
  `output_tokens` from `usage.completion_tokens` (default `0`). `runner` stores `output_tokens` on each
  successful cell.
- Per-cell `tokens_per_sec = output_tokens / (latency_ms / 1000)`, **only when both are > 0**;
  otherwise `None`. A model's throughput is the mean over its cells that have a value. If none do,
  its `throughput` score is `None` and the UI shows "n/a".
- `app.py` / `mcp_server.py` stats gain `avg_tokens_per_sec` (rounded to 1 decimal, or `None`).
- **Quality** shown in the side-by-side view is the existing overall `grade.score` (judge and checks,
  70/30).
- The rename is applied everywhere `speed` is read today: `report.py` (colors, labels, CSV column
  `speed_score` → `response_time_score`, plus a new `throughput_score` and `tokens_per_sec`),
  `static/app.js` category chips and chart, and tests.

## 3. Suggestions

### 3a. Catalog tiers
Every curated model in `data/providers.json` gets `"tier": "flagship" | "balanced" | "fast"`:

| Provider | flagship | balanced | fast |
|---|---|---|---|
| openai | `~openai/gpt-latest`, `openai/gpt-5` | `openai/gpt-4o` | `openai/gpt-5-mini`, `openai/gpt-4o-mini` |
| anthropic | `~anthropic/claude-opus-latest`, `anthropic/claude-opus-4.5` | `anthropic/claude-sonnet-4.5` | `anthropic/claude-haiku-4.5` |
| google | `~google/gemini-pro-latest`, `google/gemini-2.5-pro` | `google/gemini-3.7-flash` | `google/gemini-2.5-flash` |
| meta-llama | `meta-llama/llama-4-maverick` | `meta-llama/llama-3.3-70b-instruct` | `meta-llama/llama-4-scout` |

Tier order: `fast` (0) < `balanced` (1) < `flagship` (2).

### 3b. `advisor.py` (new, pure, no I/O)
`suggest(target, categories, all_categories, catalog) -> {"suggestion": {...} | None}` per model, and
`suggest_all(grades, catalog) -> {target: suggestion_or_None}`.

- **Candidate pool** for target `id@backend`: models of the **same provider** whose ids differ from
  `id`, excluding `~`-prefixed aliases. If `backend != "openrouter"`, only models with a `routes[backend]`
  entry. So a Bedrock target only suggests Bedrock-routed siblings. Models not in the catalog (custom
  ids) → `None`.
- **Weakness** (using that model's category scores; `None` scores are ignored):
  1. `quality_weak`: overall `grade.score` < 70, or it is ≥ 15 points below the **best** `grade.score`
     in the run → want a **higher** tier. (If `grade.score` is `None` — no rubric and no checks — this
     rule is skipped, and so is rule 3.)
  2. else `latency_weak`: `response_time` ≤ 40 or `throughput` ≤ 40 (i.e. among the slowest in this
     run) → want a **lower** (faster) tier.
  3. else `cost_weak`: `cost_efficiency` ≤ 40 and `grade.score` ≥ 85 → want a **lower** (cheaper) tier.
  4. else → `None` (it's already a good fit).
- **Pick**: the candidate whose tier is the closest one step in the wanted direction (prefer adjacent
  tier, then two steps). Tie → first in catalog order. No candidate in that direction → `None`.
- **Output**: `{"model_id": "<target of suggested sibling, same @backend suffix>", "name": "<display
  name>", "reason_code": "quality" | "latency" | "cost", "reason": "<one-line rule text>"}`, e.g.
  `"Claude Haiku 4.5 is Anthropic's fast tier on Bedrock — try it if response time matters more than depth."`

### 3c. Judge-written explanation
`judge.explain_recommendations(summary, creds, backend="openrouter", judge_model=None) -> str`.
- `summary` = per-target scores (quality, response_time, throughput, cost_efficiency) plus the
  advisor's suggestions (ids, names, reason codes).
- The prompt asks for 2–3 plain sentences explaining trade-offs and the suggestions, and forbids
  naming any model not present in `summary`.
- Output guard: if the text mentions a catalog model id or name not present in `summary`, discard it.
  On any `GatewayError` or parse problem, return `""`. The UI then shows the advisor's rule `reason`
  lines instead. It fails soft and never raises.
- Called once per run in `app.py`/`mcp_server.py` after the verdict, on the same `judge_backend` and
  prepared creds. It adds one LLM call per run.

### 3d. Run result shape (additions)
```
"stats": {target: {..., "avg_tokens_per_sec": float|None}},
"grades": {target: {..., "categories": {accuracy, rule_checks, cost_efficiency, response_time, throughput}}},
"suggestions": {target: {model_id, name, reason_code, reason} | None},
"advice": "<judge-written text or empty string>"
```

## 4. Frontend: side-by-side view, priority selector, help

- **Side-by-side view** (new `#compare-grid`, shown above the existing leaderboard and results).
  Up to 4 equal columns, stacking to one column on narrow screens. Each column shows: model id and
  provider color; letter grade; four labelled bars (Quality, Response Time, Speed, Cost); raw numbers
  (avg ms, tok/s, $); and the advisor suggestion ("Try Claude Haiku 4.5 →" + reason) or
  "Good fit — no better option in this catalog." All strings go through `escapeHtml` / `textContent`.
- **Priority selector** `#priority` with weights over (quality, response_time, throughput,
  cost_efficiency):
  - Balanced 0.40 / 0.20 / 0.20 / 0.20
  - Best quality 0.70 / 0.10 / 0.10 / 0.10
  - Fastest 0.20 / 0.40 / 0.40 / 0.00
  - Cheapest 0.30 / 0.10 / 0.10 / 0.50

  The weighted score ignores `None` metrics (renormalizing the remaining weights). The top column gets
  a "Best for your priority" badge. Changing the selector re-ranks instantly with no new request.
  The choice is remembered for the page session only.
- **Advice box**: shows `advice` when non-empty, otherwise the list of rule `reason`s.
- **"How to read this"** collapsible help (`<details>`):
  - Chat and interactive UIs → prioritize Response Time.
  - Long outputs (reports, code) → prioritize Speed.
  - Accuracy-critical work → Best quality.
  - Within about 5 quality points, prefer the faster or cheaper model.
  - Run 3+ representative prompts before deciding; one prompt is noisy.
  - Suggestions only name models from the same provider on the backend you used.
- **Cap UI**: "Selected N / 4" counter, and a blocked 5th click, as in §1.

## 5. Reports & MCP

- PDF: category table uses the new keys and labels; add a "Suggestions" section (one line per model,
  then the advice paragraph if present).
- CSV: rename `speed_score` → `response_time_score`; add `throughput_score` and `tokens_per_sec`
  per cell.
- MCP `run_comparison` returns `suggestions` and `advice`, and enforces the cap. The docstring
  mentions both.

## 6. Error handling & safety

- The advisor is pure and can't fail on well-formed grades. `None` inputs → `None` suggestion.
- The explainer fails soft (`""`) and is guarded against naming out-of-list models.
- The cap is validated server-side regardless of the UI.
- No new user input reaches HTML unescaped. No credentials are involved beyond the existing judge call.

## 7. Testing (no live network)

- `grading`: `response_time` rename; `throughput` relative scoring, including all-equal → 100 and
  `None` handling.
- `openrouter`: `output_tokens` parsed, default 0. `runner`: `output_tokens` on cells.
- `advisor`: each weakness branch; same-provider-only; Bedrock target only suggests Bedrock-routed
  siblings; aliases excluded; custom id → None; no candidate in that direction → None; `@backend`
  suffix preserved.
- `judge.explain_recommendations`: happy path; GatewayError → ""; mentions an out-of-list model → "".
- `app`/`mcp`: 5 models → 400/error before the rate limiter; 4 allowed; response includes
  `suggestions`, `advice`, `avg_tokens_per_sec`.
- `report`: new CSV columns; PDF builds with suggestions.
- Frontend: `node --check`, plus a browser check of the cap, side-by-side view, and priority re-rank
  (manual, against mocked or real runs).

## 8. Additions from spec review (these override earlier sections where noted)

### 8.1 Don't suggest models already being compared (changes §3b "Candidate pool")
Remove from the candidate pool every model whose resulting target (same `@backend` suffix) is already
one of the run's targets. If that leaves no candidate in the wanted direction, the suggestion is `None`.

### 8.2 Minimum real gap before flagging slow/pricey (changes §3b rules 2–3)
The relative score alone is too trigger-happy with 2–3 models. Flag it only when the absolute gap is
real too:
- `latency_weak` requires (`response_time` ≤ 40 **and** avg latency ≥ 1.25 × the fastest model's avg
  latency) **or** (`throughput` ≤ 40 **and** avg tok/s ≤ 0.8 × the best model's avg tok/s).
- `cost_weak` additionally requires total cost ≥ 1.25 × the cheapest model's total cost.
- Constants live in `advisor.py`: `LATENCY_GAP = 1.25`, `THROUGHPUT_GAP = 0.8`, `COST_GAP = 1.25`.

### 8.3 Failed/blocked models
A target with **no successful cells** (all errored or policy-blocked):
- advisor → `None`;
- excluded from the priority ranking and the "Best for your priority" badge;
- side-by-side column shows the grade (if any) plus "No successful responses (E errors, B blocked)"
  instead of bars.

`stats[target]` gains `ok_cells`, `error_cells`, `blocked_cells` counts to drive this.

### 8.4 Priority weights shared server-side; PDF knows the priority (changes §4, §5)
- `grading.PRIORITY_WEIGHTS = {"balanced": ..., "quality": ..., "fastest": ..., "cheapest": ...}`
  (values from §4) and
  `grading.rank_targets(grades, stats, priority) -> [target, ...]`, best first. It renormalizes over
  non-`None` metrics, excludes targets with `ok_cells == 0`, and breaks ties by
  (higher quality, lower avg latency, target string).
- `/api/catalog` returns `"priority_weights"` so the frontend uses the same numbers. The JS ranking
  must match `rank_targets` (same renormalization and tie-break).
- `/api/report?run_id=…&priority=<balanced|quality|fastest|cheapest>` (default `balanced`; an invalid
  value → 400). The PDF header shows "Priority: <label> — best pick: <target>" using `rank_targets`.
  The frontend's download buttons pass the current `#priority` value. The CSV is unchanged
  (priority-independent).

### 8.5 Judge disclosure and bias warning
- The run result gains `"judge": {"backend": <judge_backend>, "model": <resolved judge model id>}`.
- The side-by-side view shows "Judged by <model> via <backend>". The PDF shows the same line.
- If the judge model's provider matches a compared target's provider (e.g. an Anthropic judge scoring
  Claude), show the note "The judge is from the same family as <model> — scores may lean in its
  favor." in the advice box and in the PDF.
- The help box gains: "A judge can favor its own model family — for important decisions, re-run with
  a judge from a different provider."

### 8.6 Tie-break and one-model runs (changes §3b, §4)
- Tie-break: see 8.4.
- With exactly **one** successful target, the relative rules (latency, cost) are skipped. Only the
  absolute quality rule (`grade.score` < 70) can produce a suggestion. The priority badge is hidden.

### 8.7 One-click "Try it"
Each suggestion in the side-by-side view has a **Try it** button:
1. Remove the weak target from `state.selectedModels`, add the suggested target, and update the
   badge/chip visuals. Chips and badges carry `data-target` for this.
2. Honor the cap. A swap never changes the count.
3. Set `#run-status` to "Swapped <old> → <new>. Click Run comparison to test it." It does **not** start
   a run automatically.

### 8.8 Optional repeats for timing accuracy
- `/api/run` and MCP `run_comparison` accept `repeats` ∈ {1, 2, 3} (default 1; anything else → 400/error).
- `runner.run(..., repeats=1)`: each (test case, target) is called `repeats` times **for timing only**.
  Checks and the judge run on the **first** successful response. The policy gate runs once per cell.
- The cell records `latency_ms` (mean), `latency_ms_stdev` (population stdev, `None` when fewer than
  2 samples), and `tokens_per_sec` (mean of samples with a value). Cost sums all samples.
- The whole run still counts as **one** run against the rate limit. The UI has a "Repeat each prompt"
  select (1/2/3) with the hint "More accurate timing; multiplies model calls and cost."
- Side-by-side shows "avg ± stdev ms" when available.

### 8.9 Reasoning models: approximate speed
- Catalog models get an optional `"reasoning": true`: `~openai/gpt-latest`, `openai/gpt-5`,
  `openai/gpt-5-mini`, `google/gemini-2.5-pro`, `google/gemini-2.5-flash`, `google/gemini-3.7-flash`,
  `~google/gemini-pro-latest`.
- For those targets the UI and PDF show speed as "≈ N tok/s", with a tooltip/footnote: "Includes hidden
  reasoning tokens on some providers — approximate."

### 8.10 Pre-run cost estimate
- `catalog.fetch_openrouter_models()` also keeps `pricing` (`prompt`/`completion`, USD per token, as
  floats) when OpenRouter provides it.
- `/api/catalog` curated routes already carry Bedrock/Vertex prices (per 1M tokens).
- Frontend `estimateCost()`: for each selected target × test case × repeats, estimate
  input ≈ ceil(len(prompt)/4) tokens and output = 500 tokens, priced from the route (Bedrock/Vertex)
  or the live OpenRouter pricing. Show "Estimated cost: ~$0.0042 (rough; excludes judge calls)" next to
  Run. If any selected target has no price, show "Estimated cost: unavailable for <n> model(s)" for
  those and sum the rest. It recalculates on every selection, test-case, or repeats change.

### 8.11 Accessibility and phones
- Every metric bar shows its numeric value as text ("Quality 82/100") and has an `aria-label`. Color
  is never the only signal.
- `#compare-grid` is a CSS grid, `repeat(auto-fit, minmax(200px, 1fr))`, so columns stack on phones.
- The priority `<select>`, repeats `<select>`, and Try-it buttons have visible labels / `aria-label`s.

### 8.12 MCP priority
`run_comparison(..., priority="balanced", repeats=1)` validates `priority` against
`grading.PRIORITY_WEIGHTS` and returns `"ranking"` (from `rank_targets`) and
`"best_for_priority"` (first element or `None`).

### 8.13 Docs
- README: a "Comparing up to 4 models" section covering the metrics and what each means, the priority
  selector, suggestions (same provider and backend only; judge-written explanation), Try it, repeats,
  the cost estimate, and the judge-bias caveat. Note that each run makes **one extra judge call** for
  the explanation.
- MCP section documents `priority`, `repeats`, `suggestions`, `advice`, `ranking`, `best_for_priority`.
- CLAUDE.md (untracked, local): add `advisor.py` to the module list and the new run-result fields.

### 8.14 Testing additions
- advisor: already-compared exclusion; the gap thresholds (a model 10% slower is NOT flagged, one 30%
  slower IS); a failed target → `None`; one-model run → only the quality rule applies.
- grading: `rank_targets` weights, renormalization with `None` metrics, excluding failed targets, and
  tie-break order.
- runner: `repeats=3` makes 3 model calls per cell but 1 judge call; mean/stdev math; cost sums samples.
- app/mcp: `repeats` validation; `priority` validation (report 400 and MCP error); `judge` field
  present; `ranking`/`best_for_priority` in MCP.
- report: the PDF builds with a priority line, judge line, and bias note; `?priority=` is honored.
- catalog: `fetch_openrouter_models` keeps pricing (mocked `requests.get`).
- Frontend (browser check): cap, Try it swap, priority re-rank matches the server ranking for the
  same run, cost estimate updates, stacked layout at phone width.

## Out of scope

Time-to-first-token (needs streaming); suggesting models from OpenRouter's live catalog (they have no
tier data); persisting the priority choice across sessions.
