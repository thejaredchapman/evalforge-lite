# Four-Model Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare up to 4 models side by side on quality, response time, speed (tokens/sec) and cost; suggest better-fitting models from the same provider and backend (rules pick them, the judge explains); and help users choose with a priority selector, "Try it" swaps, optional timing repeats, and a pre-run cost estimate.

**Architecture:** Metrics start in `runner` (per-cell tokens/sec, repeats) and `grading` (category scores, priority weights, `rank_targets`). A new pure `advisor.py` picks same-provider/same-backend siblings using catalog `tier` tags. `judge.explain_recommendations` writes guarded prose around those picks. A new `analysis.py` owns the whole post-run assembly (previously duplicated in `app.py` and `mcp_server.py`), and both entry points call it. `report.py` and the frontend render the new fields.

**Tech Stack:** Python 3.12 (Flask, fpdf2, matplotlib), vanilla JS + Chart.js, pytest with `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-26-four-model-comparison-design.md` (§8 overrides earlier sections where it says so).

## Global Constraints

- Branch `feat/four-model-comparison` (already checked out). Python: `venv/bin/python`, `venv/bin/pytest` (Python 3.12). Run the suite with `venv/bin/pytest tests/ -q`; it is green at 308 tests before Task 1.
- No test may make a live network call. Mock `requests.*`, `gateway.*` or `judge.*`.
- Commit only your task's files with a pathspec: `git add <files> && git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- <files>`. `CLAUDE.md` is untracked: never `git add` it except where Task 9 says to edit it (it still stays uncommitted).
- **Cap:** the server rejects **more than** `config.MAX_MODELS` (= 4) targets with `"Pick at most 4 models."`. An empty `models` list stays allowed server-side (legacy tests rely on it). The UI requires at least 1.
- Category keys after Task 2: `accuracy`, `rule_checks`, `cost_efficiency`, `response_time` (renamed from `speed`), `throughput`. Nothing may still read `categories["speed"]` after Task 7 (report) and Task 8 (frontend).
- Priority keys: `balanced`, `quality`, `fastest`, `cheapest`. Weights, labels and the ranking live in `grading`, and the frontend gets them from `/api/catalog`.
- Suggestions only ever name models from the **same provider**, with a route on the **same backend**, excluding `~` aliases and targets already in the run. The LLM never chooses models.
- Any model/LLM/user text inserted into HTML goes through `escapeHtml()` or `textContent`.
- Match surrounding style: no docstrings on simple functions, `_PRIVATE` module constants, openrouter.py-style error mapping.

---

### Task 1: Output tokens, tokens/sec, and timing repeats in `openrouter` + `runner`

**Files:**
- Modify: `openrouter.py`, `runner.py`
- Test: `tests/test_openrouter.py`, `tests/test_runner.py`

**Interfaces:**
- Produces:
  - `openrouter.call_model(...)` result gains `"output_tokens": int` (from `usage.completion_tokens`, default 0, non-int → 0).
  - `runner.run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter", repeats=1)`.
  - Successful cells gain `output_tokens` (first sample), `tokens_per_sec` (float rounded 1 dp, or `None`), `latency_ms_stdev` (float or `None`), and `samples` (int). `latency_ms` is the first sample's value when `samples == 1`, otherwise the mean rounded to 1 dp. `cost_usd` is the sum over samples, rounded to 8 dp.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_openrouter.py`:

```python


@patch("openrouter.requests.post")
def test_call_model_returns_output_tokens(mock_post):
    mock_post.return_value = _mock_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 30, "completion_tokens": 12, "cost": 0.0},
    })
    result = openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")
    assert result["output_tokens"] == 12


@patch("openrouter.requests.post")
def test_call_model_output_tokens_default_zero(mock_post):
    mock_post.return_value = _mock_response({
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"total_tokens": 30, "completion_tokens": "n/a"},
    })
    result = openrouter.call_model("openai/gpt-4o-mini", [{"role": "user", "content": "hi"}], api_key="sk-or-v1-test")
    assert result["output_tokens"] == 0
```

Append to `tests/test_runner.py`:

```python


def _timed_response(latency_ms, output_tokens, cost=0.001):
    return {"text": "answer", "latency_ms": latency_ms, "cost_usd": cost, "tokens": 40,
            "output_tokens": output_tokens}


@patch("runner.gateway.call_target")
def test_cell_reports_tokens_per_sec(mock_call):
    mock_call.return_value = _timed_response(2000, 100)
    cell = runner.run([{"prompt": "q"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"})[0]["cells"]["openai/gpt-5"]
    assert cell["tokens_per_sec"] == 50.0
    assert cell["output_tokens"] == 100
    assert cell["samples"] == 1
    assert cell["latency_ms"] == 2000
    assert cell["latency_ms_stdev"] is None


@patch("runner.gateway.call_target")
def test_cell_tokens_per_sec_none_without_output_tokens(mock_call):
    mock_call.return_value = _timed_response(2000, 0)
    cell = runner.run([{"prompt": "q"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"})[0]["cells"]["openai/gpt-5"]
    assert cell["tokens_per_sec"] is None


@patch("runner.judge.llm_judge", return_value={"score": 4, "rationale": "ok"})
@patch("runner.gateway.call_target")
def test_repeats_time_every_sample_but_judge_once(mock_call, mock_judge):
    mock_call.side_effect = [_timed_response(1000, 100), _timed_response(2000, 100), _timed_response(3000, 150)]
    cell = runner.run([{"prompt": "q", "rubric": "r"}], ["openai/gpt-5"],
                      creds={"openrouter": "sk-or-v1-test"}, repeats=3)[0]["cells"]["openai/gpt-5"]
    assert mock_call.call_count == 3
    assert mock_judge.call_count == 1
    assert cell["samples"] == 3
    assert cell["latency_ms"] == 2000.0
    assert cell["latency_ms_stdev"] == 816.5
    assert cell["tokens_per_sec"] == round((100.0 + 50.0 + 50.0) / 3, 1)
    assert cell["cost_usd"] == 0.003


@patch("runner.gateway.call_target")
def test_repeats_use_successful_samples_when_some_fail(mock_call):
    mock_call.side_effect = [gateway.GatewayError("flaky"), _timed_response(1000, 100)]
    cell = runner.run([{"prompt": "q"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"},
                      repeats=2)[0]["cells"]["openai/gpt-5"]
    assert cell["error"] is None
    assert cell["samples"] == 1


@patch("runner.gateway.call_target", side_effect=gateway.GatewayError("down"))
def test_repeats_all_failing_is_a_cell_error(mock_call):
    cell = runner.run([{"prompt": "q"}], ["openai/gpt-5"], creds={"openrouter": "sk-or-v1-test"},
                      repeats=2)[0]["cells"]["openai/gpt-5"]
    assert cell["error"] == "down"
    assert mock_call.call_count == 2
```

Add `import gateway` to the imports of `tests/test_runner.py` if it isn't already there.

- [ ] **Step 2: Run them to verify they fail**

Run: `venv/bin/pytest tests/test_openrouter.py tests/test_runner.py -q`
Expected: the new tests FAIL (`KeyError: 'output_tokens'` / `'tokens_per_sec'`, and `TypeError: run() got an unexpected keyword argument 'repeats'`).

- [ ] **Step 3: Implement**

`openrouter.py`: after `tokens = usage.get("total_tokens", 0)` add

```python
    output_tokens = usage.get("completion_tokens", 0)
    if not isinstance(output_tokens, int):
        output_tokens = 0
```

and add `"output_tokens": output_tokens,` to the returned dict.

`runner.py`: add `import statistics` at the top, then replace `_run_one_cell` and `run` with:

```python
def _tokens_per_sec(response):
    output_tokens = response.get("output_tokens") or 0
    latency_ms = response.get("latency_ms") or 0
    if output_tokens > 0 and latency_ms > 0:
        return output_tokens / (latency_ms / 1000)
    return None


def _run_one_cell(test_case, target, creds, policy_text, judge_backend, repeats=1):
    prompt = test_case["prompt"]

    if policy_text:
        policy_result = policy.check_policy(prompt, policy_text, creds=creds, backend=judge_backend)
        if policy_result["violates"]:
            return {
                "model_id": target,
                "blocked": True,
                "policy_clause": policy_result["clause"],
                "policy_reason": policy_result["reason"],
            }

    samples = []
    first_error = None
    for _ in range(repeats):
        try:
            samples.append(gateway.call_target(target, [{"role": "user", "content": prompt}], creds))
        except gateway.GatewayError as e:
            if first_error is None:
                first_error = scrub.scrub(str(e), creds)
    if not samples:
        return {"model_id": target, "blocked": False, "error": first_error}

    response = samples[0]
    latencies = [s["latency_ms"] for s in samples]
    rates = [r for r in (_tokens_per_sec(s) for s in samples) if r is not None]

    check_results = []
    if test_case.get("checks"):
        check_results = checks.run_checks(test_case["checks"], response["text"])

    judge_score = None
    judge_rationale = None
    if test_case.get("rubric"):
        judge_result = judge.llm_judge(response["text"], test_case["rubric"], creds=creds, backend=judge_backend)
        judge_score = judge_result["score"]
        judge_rationale = judge_result["rationale"]

    return {
        "model_id": target,
        "blocked": False,
        "error": None,
        "response_text": response["text"],
        "latency_ms": latencies[0] if len(latencies) == 1 else round(statistics.mean(latencies), 1),
        "latency_ms_stdev": round(statistics.pstdev(latencies), 1) if len(latencies) >= 2 else None,
        "tokens_per_sec": round(statistics.mean(rates), 1) if rates else None,
        "samples": len(samples),
        "cost_usd": round(sum(s["cost_usd"] for s in samples), 8),
        "tokens": response["tokens"],
        "output_tokens": response.get("output_tokens", 0),
        "checks": check_results,
        "judge_score": judge_score,
        "judge_rationale": judge_rationale,
    }


def run(test_cases, targets, creds, policy_text=None, judge_backend="openrouter", repeats=1):
    creds = gateway.prepare_creds(creds)
    cells_by_tc = {i: {} for i in range(len(test_cases))}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for tc_index, test_case in enumerate(test_cases):
            for target in targets:
                future = pool.submit(_run_one_cell, test_case, target, creds, policy_text, judge_backend, repeats)
                futures[future] = (tc_index, target)

        for future, (tc_index, target) in futures.items():
            cells_by_tc[tc_index][target] = future.result()

    return [
        {"test_case": test_case, "cells": cells_by_tc[tc_index]}
        for tc_index, test_case in enumerate(test_cases)
    ]
```

- [ ] **Step 4: Run tests**: `venv/bin/pytest tests/test_openrouter.py tests/test_runner.py -q` → PASS. Then `venv/bin/pytest tests/ -q` → all PASS.

- [ ] **Step 5: Commit**: files `openrouter.py runner.py tests/test_openrouter.py tests/test_runner.py`, subject `feat: output tokens, tokens/sec, and timing repeats per cell`.

---

### Task 2: Category scores (`response_time`, `throughput`), priority weights, `rank_targets`

**Files:**
- Modify: `grading.py`
- Test: `tests/test_grading.py`

**Interfaces:**
- Produces:
  - `grading.category_scores(judge_scores, rule_check_results, cost_usd, all_costs, latency_ms, all_latencies, tokens_per_sec=None, all_tokens_per_sec=())` → `{accuracy, rule_checks, cost_efficiency, response_time, throughput}`.
  - `grading.PRIORITY_WEIGHTS: dict[str, dict[str, float]]`, `grading.PRIORITY_LABELS: dict[str, str]`.
  - `grading.weighted_score(grade, priority) -> float | None` (rounded 1 dp, for display).
  - `grading.rank_targets(grades, stats, priority) -> list[str]`, best first.

- [ ] **Step 1: Update existing tests and add new ones**

In `tests/test_grading.py`, in the four existing `category_scores` tests, replace every `categories["speed"]` / `categories2["speed"]` with `["response_time"]`. In `test_category_scores_missing_data_is_none`, change the expected dict to
`{"accuracy": None, "rule_checks": None, "cost_efficiency": None, "response_time": None, "throughput": None}`.
Then append:

```python


def test_category_scores_throughput_is_relative_and_higher_is_better():
    fast = grading.category_scores([], [], None, [], None, [], tokens_per_sec=100.0, all_tokens_per_sec=[50.0, 100.0])
    slow = grading.category_scores([], [], None, [], None, [], tokens_per_sec=50.0, all_tokens_per_sec=[50.0, 100.0])
    assert fast["throughput"] == 100.0
    assert slow["throughput"] == 0.0


def test_category_scores_throughput_none_without_value():
    assert grading.category_scores([], [], None, [], None, [], tokens_per_sec=None, all_tokens_per_sec=[80.0])["throughput"] is None


def _grade(score, response_time=None, throughput=None, cost_efficiency=None):
    return {"score": score, "categories": {"response_time": response_time, "throughput": throughput,
                                           "cost_efficiency": cost_efficiency}}


def test_priority_weights_cover_all_priorities_and_sum_to_one():
    assert set(grading.PRIORITY_WEIGHTS) == {"balanced", "quality", "fastest", "cheapest"}
    for weights in grading.PRIORITY_WEIGHTS.values():
        assert set(weights) == {"quality", "response_time", "throughput", "cost_efficiency"}
        assert round(sum(weights.values()), 6) == 1.0
    assert set(grading.PRIORITY_LABELS) == set(grading.PRIORITY_WEIGHTS)


def test_weighted_score_renormalizes_over_missing_metrics():
    # balanced: quality .4, response_time .2, throughput .2 (missing), cost .2 (missing)
    assert grading.weighted_score(_grade(90, response_time=60), "balanced") == round((90 * 0.4 + 60 * 0.2) / 0.6, 1)


def test_weighted_score_none_when_nothing_scored():
    assert grading.weighted_score(_grade(None), "balanced") is None


def test_rank_targets_orders_by_priority():
    grades = {"a": _grade(95, response_time=0, throughput=0, cost_efficiency=0),
              "b": _grade(70, response_time=100, throughput=100, cost_efficiency=100)}
    stats = {"a": {"ok_cells": 1, "avg_latency_ms": 900}, "b": {"ok_cells": 1, "avg_latency_ms": 100}}
    assert grading.rank_targets(grades, stats, "quality") == ["a", "b"]
    assert grading.rank_targets(grades, stats, "fastest") == ["b", "a"]


def test_rank_targets_excludes_failed_and_unscored_targets():
    grades = {"a": _grade(80), "failed": _grade(None), "blocked": _grade(99)}
    stats = {"a": {"ok_cells": 1}, "failed": {"ok_cells": 0}, "blocked": {"ok_cells": 0}}
    assert grading.rank_targets(grades, stats, "balanced") == ["a"]


def test_rank_targets_tie_break_quality_then_latency_then_name():
    grades = {"z": _grade(80), "y": _grade(80), "x": _grade(80)}
    stats = {"z": {"ok_cells": 1, "avg_latency_ms": 100}, "y": {"ok_cells": 1, "avg_latency_ms": 100},
             "x": {"ok_cells": 1, "avg_latency_ms": 300}}
    assert grading.rank_targets(grades, stats, "quality") == ["y", "z", "x"]
```

- [ ] **Step 2: Verify failure**: `venv/bin/pytest tests/test_grading.py -q` → FAIL (KeyError `response_time`, AttributeError `PRIORITY_WEIGHTS`).

- [ ] **Step 3: Implement** in `grading.py`. Replace `category_scores` with:

```python
def category_scores(judge_scores, rule_check_results, cost_usd, all_costs, latency_ms, all_latencies,
                    tokens_per_sec=None, all_tokens_per_sec=()):
    """Break a model's performance into separately visible dimensions.

    accuracy/rule_checks are absolute (same math as compute_score's components).
    cost_efficiency/response_time/throughput are relative to the other models in the
    same run — a raw cost, latency, or tokens/sec number alone isn't "good" or "bad".
    """
    accuracy = None
    if judge_scores:
        accuracy = round((sum(judge_scores) / len(judge_scores)) * 20, 1)

    rule_checks = None
    if rule_check_results:
        rule_checks = round(100 * (sum(1 for r in rule_check_results if r) / len(rule_check_results)), 1)

    return {
        "accuracy": accuracy,
        "rule_checks": rule_checks,
        "cost_efficiency": _relative_score(cost_usd, all_costs, lower_is_better=True),
        "response_time": _relative_score(latency_ms, all_latencies, lower_is_better=True),
        "throughput": _relative_score(tokens_per_sec, list(all_tokens_per_sec), lower_is_better=False),
    }
```

Then add after it:

```python
PRIORITY_WEIGHTS = {
    "balanced": {"quality": 0.4, "response_time": 0.2, "throughput": 0.2, "cost_efficiency": 0.2},
    "quality": {"quality": 0.7, "response_time": 0.1, "throughput": 0.1, "cost_efficiency": 0.1},
    "fastest": {"quality": 0.2, "response_time": 0.4, "throughput": 0.4, "cost_efficiency": 0.0},
    "cheapest": {"quality": 0.3, "response_time": 0.1, "throughput": 0.1, "cost_efficiency": 0.5},
}
PRIORITY_LABELS = {"balanced": "Balanced", "quality": "Best quality", "fastest": "Fastest", "cheapest": "Cheapest"}


def _priority_metrics(grade):
    categories = grade.get("categories") or {}
    return {
        "quality": grade.get("score"),
        "response_time": categories.get("response_time"),
        "throughput": categories.get("throughput"),
        "cost_efficiency": categories.get("cost_efficiency"),
    }


def _raw_weighted_score(grade, priority):
    weights = PRIORITY_WEIGHTS[priority]
    values = _priority_metrics(grade)
    total_weight = sum(w for key, w in weights.items() if w > 0 and values[key] is not None)
    if total_weight == 0:
        return None
    return sum(values[key] * w for key, w in weights.items() if w > 0 and values[key] is not None) / total_weight


def weighted_score(grade, priority):
    raw = _raw_weighted_score(grade, priority)
    return round(raw, 1) if raw is not None else None


def rank_targets(grades, stats, priority):
    scored = {}
    for target, grade in grades.items():
        if (stats.get(target) or {}).get("ok_cells", 0) == 0:
            continue
        raw = _raw_weighted_score(grade, priority)
        if raw is not None:
            scored[target] = raw

    def sort_key(target):
        quality = grades[target].get("score")
        latency = (stats.get(target) or {}).get("avg_latency_ms")
        return (
            -scored[target],
            -(quality if quality is not None else -1),
            latency if latency is not None else float("inf"),
            target,
        )

    return sorted(scored, key=sort_key)
```

- [ ] **Step 4: Run**: `venv/bin/pytest tests/test_grading.py -q` → PASS; `venv/bin/pytest tests/ -q` → PASS (report tests still pass because they use their own fixture dicts).

- [ ] **Step 5: Commit**: `grading.py tests/test_grading.py`, subject `feat: response_time/throughput category scores, priority weights, and rank_targets`.

---

### Task 3: Catalog tiers, reasoning flags, live pricing, `MAX_MODELS`, `find_model`

**Files:**
- Modify: `data/providers.json`, `catalog.py`, `config.py`
- Test: `tests/test_catalog.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - Every curated model in `providers.json` has `"tier"` ∈ {`flagship`, `balanced`, `fast`}. The models listed below also have `"reasoning": true`.
  - `catalog.find_model(catalog_dict, model_id) -> (provider_id, model_dict) | (None, None)`.
  - `catalog.fetch_openrouter_models()` entries gain `"pricing": {"prompt": float, "completion": float} | None` (USD per token).
  - `config.MAX_MODELS = 4`.

- [ ] **Step 1: Failing tests.** Append to `tests/test_catalog.py`:

```python


EXPECTED_TIERS = {
    "~openai/gpt-latest": "flagship", "openai/gpt-5": "flagship", "openai/gpt-5-mini": "fast",
    "openai/gpt-4o": "balanced", "openai/gpt-4o-mini": "fast",
    "~anthropic/claude-opus-latest": "flagship", "anthropic/claude-opus-4.5": "flagship",
    "anthropic/claude-sonnet-4.5": "balanced", "anthropic/claude-haiku-4.5": "fast",
    "~google/gemini-pro-latest": "flagship", "google/gemini-2.5-pro": "flagship",
    "google/gemini-3.7-flash": "balanced", "google/gemini-2.5-flash": "fast",
    "meta-llama/llama-4-maverick": "flagship", "meta-llama/llama-3.3-70b-instruct": "balanced",
    "meta-llama/llama-4-scout": "fast",
}
EXPECTED_REASONING = {
    "~openai/gpt-latest", "openai/gpt-5", "openai/gpt-5-mini", "google/gemini-2.5-pro",
    "google/gemini-2.5-flash", "google/gemini-3.7-flash", "~google/gemini-pro-latest",
}


def test_every_curated_model_has_its_expected_tier():
    cat = catalog.load_catalog()
    tiers = {m["id"]: m.get("tier") for p in cat.values() for m in p["models"]}
    assert tiers == EXPECTED_TIERS


def test_reasoning_flags():
    cat = catalog.load_catalog()
    flagged = {m["id"] for p in cat.values() for m in p["models"] if m.get("reasoning")}
    assert flagged == EXPECTED_REASONING


def test_find_model():
    cat = catalog.load_catalog()
    provider_id, model = catalog.find_model(cat, "anthropic/claude-haiku-4.5")
    assert provider_id == "anthropic" and model["name"] == "Claude Haiku 4.5"
    assert catalog.find_model(cat, "nope/nope") == (None, None)


@patch("catalog.requests.get")
def test_fetch_openrouter_models_keeps_pricing(mock_get):
    catalog._cache["data"] = None
    mock_get.return_value.raise_for_status.return_value = None
    mock_get.return_value.json.return_value = {"data": [
        {"id": "a/priced", "name": "Priced", "created": 1, "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {"id": "a/free-form", "name": "Odd", "created": 2, "pricing": {"prompt": "n/a"}},
        {"id": "a/none", "name": "None", "created": 3},
    ]}
    models = {m["id"]: m for m in catalog.fetch_openrouter_models()}
    catalog._cache["data"] = None
    assert models["a/priced"]["pricing"] == {"prompt": 0.000001, "completion": 0.000002}
    assert models["a/free-form"]["pricing"] is None
    assert models["a/none"]["pricing"] is None
```

(Add `from unittest.mock import patch` to the imports if it isn't there.) Append to `tests/test_config.py`:

```python


def test_max_models_is_four():
    assert config.MAX_MODELS == 4
```

- [ ] **Step 2: Verify failure**: `venv/bin/pytest tests/test_catalog.py tests/test_config.py -q` → FAIL.

- [ ] **Step 3: Implement.**
  - `data/providers.json`: add `"tier": "<value>"` to every model object exactly per `EXPECTED_TIERS`, and `"reasoning": true` to each id in `EXPECTED_REASONING`. Put the keys after `"family"` and before any `"routes"`. Keep one model per line and validate with `venv/bin/python -c "import json; json.load(open('data/providers.json'))"`.
  - `config.py`: add `MAX_MODELS = 4` below `JUDGE_MODEL`.
  - `catalog.py`: add

```python
def _pricing(model):
    pricing = model.get("pricing") or {}
    try:
        return {"prompt": float(pricing["prompt"]), "completion": float(pricing["completion"])}
    except (KeyError, TypeError, ValueError):
        return None


def find_model(catalog_dict, model_id):
    for provider_id, provider in catalog_dict.items():
        for model in provider["models"]:
            if model["id"] == model_id:
                return provider_id, model
    return None, None
```

  and in `fetch_openrouter_models` change the list comprehension entry to
  `{"id": m["id"], "name": m.get("name", m["id"]), "created": m.get("created", 0), "pricing": _pricing(m)}`.

- [ ] **Step 4: Run**: targeted tests → PASS; `venv/bin/pytest tests/ -q` → PASS.

- [ ] **Step 5: Commit**: `data/providers.json catalog.py config.py tests/test_catalog.py tests/test_config.py`, subject `feat: catalog tiers, reasoning flags, live pricing, and MAX_MODELS`.

---

### Task 4: `advisor.py` — same-provider, same-backend suggestions

**Files:**
- Create: `advisor.py`
- Test: `tests/test_advisor.py`

**Interfaces:**
- Consumes: `catalog.find_model`, `gateway.parse_target`, `gateway.BACKEND_LABELS`, the catalog `tier` field.
- Produces: `advisor.suggest_all(grades, stats, catalog_dict) -> {target: {"model_id", "name", "reason_code", "reason"} | None}`, where `stats[target]` has `ok_cells`, `avg_latency_ms`, `avg_tokens_per_sec`, `total_cost_usd`.

- [ ] **Step 1: Failing tests.** Create `tests/test_advisor.py`:

```python
import advisor

CATALOG = {
    "anthropic": {"models": [
        {"id": "~anthropic/claude-opus-latest", "name": "Claude Opus (Latest)", "tier": "flagship"},
        {"id": "anthropic/claude-opus-4.5", "name": "Claude Opus 4.5", "tier": "flagship",
         "routes": {"bedrock": {"id": "x"}}},
        {"id": "anthropic/claude-sonnet-4.5", "name": "Claude Sonnet 4.5", "tier": "balanced",
         "routes": {"bedrock": {"id": "y"}}},
        {"id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5", "tier": "fast"},
    ]},
    "openai": {"models": [
        {"id": "openai/gpt-5", "name": "GPT-5", "tier": "flagship"},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "tier": "fast"},
    ]},
}


def _g(score, response_time=100.0, throughput=100.0, cost_efficiency=100.0):
    return {"score": score, "categories": {"response_time": response_time, "throughput": throughput,
                                           "cost_efficiency": cost_efficiency}}


def _s(latency=1000.0, tps=50.0, cost=0.001, ok=1):
    return {"ok_cells": ok, "avg_latency_ms": latency, "avg_tokens_per_sec": tps, "total_cost_usd": cost}


def test_low_quality_suggests_higher_tier_same_provider():
    out = advisor.suggest_all({"anthropic/claude-sonnet-4.5": _g(60)},
                              {"anthropic/claude-sonnet-4.5": _s()}, CATALOG)
    assert out["anthropic/claude-sonnet-4.5"]["model_id"] == "anthropic/claude-opus-4.5"
    assert out["anthropic/claude-sonnet-4.5"]["reason_code"] == "quality"


def test_quality_trailing_best_by_15_is_weak():
    grades = {"anthropic/claude-sonnet-4.5": _g(80), "openai/gpt-5": _g(96)}
    stats = {t: _s() for t in grades}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"]["reason_code"] == "quality"


def test_slow_model_suggests_faster_tier_when_gap_is_real():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=0.0),
              "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5": _s(latency=3000.0, tps=20.0), "openai/gpt-5": _s(latency=1000.0, tps=80.0)}
    out = advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"]
    assert out["model_id"] == "anthropic/claude-haiku-4.5"
    assert out["reason_code"] == "latency"


def test_small_latency_gap_is_not_flagged():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=100.0),
              "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5": _s(latency=1100.0), "openai/gpt-5": _s(latency=1000.0)}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_pricey_strong_model_suggests_cheaper_tier():
    grades = {"anthropic/claude-opus-4.5": _g(95, cost_efficiency=0.0), "openai/gpt-5": _g(93)}
    stats = {"anthropic/claude-opus-4.5": _s(cost=0.01), "openai/gpt-5": _s(cost=0.002)}
    out = advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-opus-4.5"]
    assert out["model_id"] == "anthropic/claude-sonnet-4.5"
    assert out["reason_code"] == "cost"


def test_bedrock_target_only_suggests_bedrock_routed_siblings_with_suffix():
    grades = {"anthropic/claude-sonnet-4.5@bedrock": _g(90, response_time=0.0), "openai/gpt-5": _g(92)}
    stats = {"anthropic/claude-sonnet-4.5@bedrock": _s(latency=3000.0), "openai/gpt-5": _s(latency=1000.0)}
    # Haiku (fast) has no bedrock route in this fixture, so there's no faster Bedrock sibling.
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5@bedrock"] is None
    grades = {"anthropic/claude-sonnet-4.5@bedrock": _g(60)}
    out = advisor.suggest_all(grades, {"anthropic/claude-sonnet-4.5@bedrock": _s()}, CATALOG)
    assert out["anthropic/claude-sonnet-4.5@bedrock"]["model_id"] == "anthropic/claude-opus-4.5@bedrock"
    assert "Bedrock" in out["anthropic/claude-sonnet-4.5@bedrock"]["reason"]


def test_never_suggests_aliases_other_providers_or_already_compared_targets():
    grades = {"anthropic/claude-sonnet-4.5": _g(60), "anthropic/claude-opus-4.5": _g(90)}
    stats = {t: _s() for t in grades}
    # Opus is already compared and the alias is excluded, so there's no higher-tier candidate left.
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_failed_target_and_custom_ids_get_no_suggestion():
    grades = {"anthropic/claude-sonnet-4.5": _g(None), "someone/custom-model": _g(10)}
    stats = {"anthropic/claude-sonnet-4.5": _s(ok=0), "someone/custom-model": _s()}
    out = advisor.suggest_all(grades, stats, CATALOG)
    assert out == {"anthropic/claude-sonnet-4.5": None, "someone/custom-model": None}


def test_one_model_run_only_uses_quality_rule():
    grades = {"anthropic/claude-sonnet-4.5": _g(90, response_time=0.0, throughput=0.0, cost_efficiency=0.0)}
    assert advisor.suggest_all(grades, {"anthropic/claude-sonnet-4.5": _s()}, CATALOG)["anthropic/claude-sonnet-4.5"] is None


def test_good_fit_returns_none():
    grades = {"anthropic/claude-sonnet-4.5": _g(92), "openai/gpt-5": _g(94)}
    stats = {t: _s() for t in grades}
    assert advisor.suggest_all(grades, stats, CATALOG)["anthropic/claude-sonnet-4.5"] is None
```

- [ ] **Step 2: Verify failure**: `venv/bin/pytest tests/test_advisor.py -q` → `ModuleNotFoundError: No module named 'advisor'`.

- [ ] **Step 3: Implement** `advisor.py`:

```python
import catalog
import gateway

TIER_ORDER = {"fast": 0, "balanced": 1, "flagship": 2}
QUALITY_FLOOR = 70
QUALITY_TRAIL = 15
WEAK_RELATIVE = 40
COST_STRONG_QUALITY = 85
LATENCY_GAP = 1.25
THROUGHPUT_GAP = 0.8
COST_GAP = 1.25

_PROVIDER_LABELS = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "meta-llama": "Meta"}
_REASON_TAIL = {
    "quality": "try it if answer quality matters more than speed or cost.",
    "latency": "try it if response time matters more than depth.",
    "cost": "try it for similar results at lower cost.",
}


def _positive(values):
    return [v for v in values if v]


def _weakness(target, grades, stats, successful):
    grade = grades[target]
    categories = grade.get("categories") or {}
    target_stats = stats[target]
    score = grade.get("score")

    scores = [grades[t].get("score") for t in successful if grades[t].get("score") is not None]
    if score is not None and (score < QUALITY_FLOOR or (len(scores) > 1 and max(scores) - score >= QUALITY_TRAIL)):
        return "quality"
    if len(successful) < 2:
        return None

    latencies = _positive(stats[t].get("avg_latency_ms") for t in successful)
    rates = _positive(stats[t].get("avg_tokens_per_sec") for t in successful)
    costs = _positive(stats[t].get("total_cost_usd") for t in successful)
    latency = target_stats.get("avg_latency_ms")
    rate = target_stats.get("avg_tokens_per_sec")
    cost = target_stats.get("total_cost_usd")
    response_time = categories.get("response_time")
    throughput = categories.get("throughput")
    cost_efficiency = categories.get("cost_efficiency")

    slow_latency = (response_time is not None and response_time <= WEAK_RELATIVE and latency and latencies
                    and latency >= LATENCY_GAP * min(latencies))
    slow_rate = (throughput is not None and throughput <= WEAK_RELATIVE and rate and rates
                 and rate <= THROUGHPUT_GAP * max(rates))
    if slow_latency or slow_rate:
        return "latency"

    pricey = (cost_efficiency is not None and cost_efficiency <= WEAK_RELATIVE and cost and costs
              and cost >= COST_GAP * min(costs) and score is not None and score >= COST_STRONG_QUALITY)
    if pricey:
        return "cost"
    return None


def _candidates(target, catalog_dict, taken):
    model_id, backend = gateway.parse_target(target)
    provider_id, model = catalog.find_model(catalog_dict, model_id)
    if model is None or model.get("tier") not in TIER_ORDER:
        return None, None, backend, []
    options = []
    for sibling in catalog_dict[provider_id]["models"]:
        if sibling["id"] == model_id or sibling["id"].startswith("~") or sibling.get("tier") not in TIER_ORDER:
            continue
        if backend != "openrouter" and backend not in (sibling.get("routes") or {}):
            continue
        sibling_target = sibling["id"] if backend == "openrouter" else f"{sibling['id']}@{backend}"
        if sibling_target in taken:
            continue
        options.append((sibling, sibling_target))
    return provider_id, model, backend, options


def _pick(model, options, direction):
    here = TIER_ORDER[model["tier"]]
    for step in (1, 2):
        wanted = here + direction * step
        for sibling, sibling_target in options:
            if TIER_ORDER[sibling["tier"]] == wanted:
                return sibling, sibling_target
    return None, None


def suggest_all(grades, stats, catalog_dict):
    successful = [t for t in grades if (stats.get(t) or {}).get("ok_cells", 0) > 0]
    taken = set(grades)
    suggestions = {}
    for target in grades:
        suggestions[target] = None
        if target not in successful:
            continue
        weakness = _weakness(target, grades, stats, successful)
        if weakness is None:
            continue
        provider_id, model, backend, options = _candidates(target, catalog_dict, taken)
        if model is None:
            continue
        sibling, sibling_target = _pick(model, options, 1 if weakness == "quality" else -1)
        if sibling is None:
            continue
        provider_label = _PROVIDER_LABELS.get(provider_id, provider_id)
        reason = (f"{sibling['name']} is {provider_label}'s {sibling['tier']} tier on "
                  f"{gateway.BACKEND_LABELS[backend]} — {_REASON_TAIL[weakness]}")
        suggestions[target] = {"model_id": sibling_target, "name": sibling["name"],
                               "reason_code": weakness, "reason": reason}
    return suggestions
```

- [ ] **Step 4: Run**: `venv/bin/pytest tests/test_advisor.py -q` → PASS; full suite → PASS.

- [ ] **Step 5: Commit**: `advisor.py tests/test_advisor.py`, subject `feat: advisor suggests same-provider, same-backend models by tier`.

---

### Task 5: `judge.explain_recommendations` (guarded, fail-soft)

**Files:**
- Modify: `judge.py`
- Test: `tests/test_judge.py`

**Interfaces:**
- Produces: `judge.explain_recommendations(summary, creds, backend="openrouter", judge_model=None, disallowed_terms=()) -> str`. `summary` = `{"models": {target: {quality, response_time, throughput, cost_efficiency}}, "suggestions": {target: {"model_id", "name", "reason_code"}}}`. Returns `""` on any failure, or if the advice contains any `disallowed_terms` entry (case-insensitive).

- [ ] **Step 1: Failing tests.** Append to `tests/test_judge.py`:

```python


_SUMMARY = {
    "models": {"anthropic/claude-sonnet-4.5": {"quality": 80, "response_time": 20, "throughput": 30, "cost_efficiency": 50}},
    "suggestions": {"anthropic/claude-sonnet-4.5": {"model_id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5",
                                                     "reason_code": "latency"}},
}


@patch("judge.gateway.call_backend")
def test_explain_recommendations_returns_advice(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "Sonnet was slow; Claude Haiku 4.5 should respond faster."}')
    text = judge.explain_recommendations(_SUMMARY, creds={"openrouter": "sk-or-v1-test"})
    assert text == "Sonnet was slow; Claude Haiku 4.5 should respond faster."
    prompt = mock_call.call_args[0][2][0]["content"]
    assert "Claude Haiku 4.5" in prompt and "anthropic/claude-sonnet-4.5" in prompt


@patch("judge.gateway.call_backend")
def test_explain_recommendations_rejects_disallowed_models(mock_call):
    mock_call.side_effect = _fake_call_backend('{"advice": "Try GPT-5 instead."}')
    assert judge.explain_recommendations(_SUMMARY, creds={}, disallowed_terms=["GPT-5", "openai/gpt-5"]) == ""


@patch("judge.gateway.call_backend", side_effect=gateway.GatewayError("down"))
def test_explain_recommendations_fails_soft(mock_call):
    assert judge.explain_recommendations(_SUMMARY, creds={}) == ""


@patch("judge.gateway.call_backend")
def test_explain_recommendations_unparseable_is_empty(mock_call):
    mock_call.side_effect = _fake_call_backend("no json here")
    assert judge.explain_recommendations(_SUMMARY, creds={}) == ""
```

- [ ] **Step 2: Verify failure** → `AttributeError: module 'judge' has no attribute 'explain_recommendations'`.

- [ ] **Step 3: Implement** in `judge.py` (template after `PROMPT_EVAL_TEMPLATE`, function at the end of the file):

```python
EXPLAIN_PROMPT_TEMPLATE = """You are advising a developer who just compared several LLMs.
Using ONLY the data below, write 2-3 plain sentences explaining the trade-offs between the compared
models and why each suggested alternative might fit better. Do not mention any model that is not
listed below.

Compared models (scores 0-100, higher is better):
{models}

Suggested alternatives (same provider and backend as the model they replace):
{suggestions}

Respond with ONLY a JSON object in this exact shape, no other text:
{{"advice": "<2-3 sentences>"}}
"""
```

```python
def explain_recommendations(summary, creds, backend="openrouter", judge_model=None, disallowed_terms=()):
    models_text = "\n".join(f"- {target}: {scores}" for target, scores in summary.get("models", {}).items())
    suggestion_lines = [
        f"- instead of {target}: {s['name']} ({s['model_id']}), because of {s['reason_code']}"
        for target, s in summary.get("suggestions", {}).items() if s
    ]
    prompt = EXPLAIN_PROMPT_TEMPLATE.format(models=models_text, suggestions="\n".join(suggestion_lines) or "- none")

    try:
        model = judge_model or config.JUDGE_MODELS[backend]
        result = gateway.call_backend(backend, model, [{"role": "user", "content": prompt}], creds)
        advice = str(_extract_json(result["text"])["advice"]).strip()
    except (gateway.GatewayError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return ""

    lowered = advice.lower()
    if any(term.lower() in lowered for term in disallowed_terms if term):
        return ""
    return advice
```

- [ ] **Step 4: Run** targeted tests → PASS; full suite → PASS.
- [ ] **Step 5: Commit**: `judge.py tests/test_judge.py`, subject `feat: judge-written, guarded explanation of model suggestions`.

---

### Task 6: `analysis.py` + wire into `app.py` / `mcp_server.py` (cap, repeats, priority, judge info)

**Files:**
- Create: `analysis.py`
- Modify: `app.py`, `mcp_server.py`
- Test: `tests/test_analysis.py` (new), `tests/test_app.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `analysis.build_run_result(results, targets, creds, judge_backend) -> dict` with keys `results` (each row gains `best_model`), `grades` (with 5-key `categories`), `stats` (per target: `total_cost_usd`, `avg_latency_ms`, `avg_latency_stdev_ms`, `avg_tokens_per_sec`, `ok_cells`, `error_cells`, `blocked_cells`), `verdict`, `suggestions`, `advice`, `judge` `{"backend","model"}`, and `bias_note` (str, may be `""`). Callers add `run_id`/`created_at`.
  - `analysis.judge_model_label(judge_backend, creds) -> str`: the resolved judge model id. For Bedrock, `{geo}` is resolved from the creds region when possible; otherwise it's left as-is.
  - `/api/run` and MCP `run_comparison` accept `repeats` (1/2/3) and enforce the cap. MCP also accepts `priority` and returns `ranking` + `best_for_priority`.
  - `/api/catalog` adds `max_models`, `priority_weights`, `priority_labels`.
  - `/api/report?priority=` is validated and passed to `report.build_pdf(run_result, priority=...)`. **Task 7** adds that parameter. Until then, call `report.build_pdf(run_result)` and only validate the query param. Task 7 switches the call.

- [ ] **Step 1: Write `tests/test_analysis.py`**

```python
from unittest.mock import patch

import analysis


def _ok(latency, tps, cost=0.001, score=4):
    return {"blocked": False, "error": None, "response_text": "a", "latency_ms": latency, "latency_ms_stdev": None,
            "tokens_per_sec": tps, "cost_usd": cost, "tokens": 10, "output_tokens": 5, "checks": [],
            "judge_score": score, "judge_rationale": "ok"}


RESULTS = [{"test_case": {"prompt": "q", "rubric": "r"}, "cells": {
    "anthropic/claude-sonnet-4.5": _ok(3000, 20.0, score=4),
    "openai/gpt-5": _ok(1000, 80.0, score=5),
    "meta-llama/llama-4-scout": {"blocked": False, "error": "down"},
}}]
TARGETS = ["anthropic/claude-sonnet-4.5", "openai/gpt-5", "meta-llama/llama-4-scout"]


@patch("analysis.judge.explain_recommendations", return_value="Plain advice.")
@patch("analysis.judge.overall_verdict", return_value={"winner": "openai/gpt-5", "rationale": "best"})
def test_build_run_result_shape(mock_verdict, mock_explain):
    out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "sk-or-v1-test"}, "openrouter")
    assert set(out) >= {"results", "grades", "stats", "verdict", "suggestions", "advice", "judge", "bias_note"}
    assert out["stats"]["anthropic/claude-sonnet-4.5"]["avg_tokens_per_sec"] == 20.0
    assert out["stats"]["meta-llama/llama-4-scout"] == {
        "total_cost_usd": 0.0, "avg_latency_ms": 0.0, "avg_latency_stdev_ms": None, "avg_tokens_per_sec": None,
        "ok_cells": 0, "error_cells": 1, "blocked_cells": 0,
    }
    assert set(out["grades"]["openai/gpt-5"]["categories"]) == {
        "accuracy", "rule_checks", "cost_efficiency", "response_time", "throughput"}
    assert out["suggestions"]["anthropic/claude-sonnet-4.5"]["model_id"] == "anthropic/claude-haiku-4.5"
    assert out["suggestions"]["meta-llama/llama-4-scout"] is None
    assert out["advice"] == "Plain advice."
    assert out["judge"] == {"backend": "openrouter", "model": "openai/gpt-4o-mini"}
    assert out["results"][0]["best_model"]["model_id"] == "openai/gpt-5"
    disallowed = mock_explain.call_args[1]["disallowed_terms"]
    assert "Claude Haiku 4.5" not in disallowed and "GPT-5 Mini" in disallowed


@patch("analysis.judge.explain_recommendations", return_value="x")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": ""})
def test_bias_note_when_judge_shares_a_provider(mock_verdict, mock_explain):
    out = analysis.build_run_result(RESULTS, TARGETS, {"openrouter": "sk-or-v1-test"}, "openrouter")
    assert "GPT-5" in out["bias_note"] or "openai/gpt-5" in out["bias_note"]


@patch("analysis.judge.explain_recommendations")
@patch("analysis.judge.overall_verdict", return_value={"winner": None, "rationale": "No models were run."})
def test_no_successful_targets_skips_explainer(mock_verdict, mock_explain):
    results = [{"test_case": {"prompt": "q"}, "cells": {"openai/gpt-5": {"blocked": True, "policy_clause": "c", "policy_reason": "r"}}}]
    out = analysis.build_run_result(results, ["openai/gpt-5"], {"openrouter": "k"}, "openrouter")
    assert out["advice"] == ""
    assert out["stats"]["openai/gpt-5"]["blocked_cells"] == 1
    mock_explain.assert_not_called()


def test_judge_model_label_resolves_bedrock_geo():
    assert analysis.judge_model_label("bedrock", {"bedrock": {"region": "eu-west-1", "api_key": "k"}}).startswith("eu.anthropic.")
    assert analysis.judge_model_label("bedrock", {}).startswith("{geo}.")
```

- [ ] **Step 2: Implement `analysis.py`**

```python
import statistics

import advisor
import bedrock
import catalog
import config
import gateway
import grading
import judge

_PROVIDER_ALIASES = {"openai": "openai", "anthropic": "anthropic", "google": "google",
                     "meta": "meta-llama", "meta-llama": "meta-llama"}


def _mean(values):
    return statistics.mean(values) if values else None


def _aggregate(results, targets):
    agg = {t: {"judge_scores": [], "rule_check_results": [], "judge_rationales": [], "costs": [],
               "latencies": [], "stdevs": [], "rates": [], "ok": 0, "error": 0, "blocked": 0} for t in targets}
    for row in results:
        for target, cell in row["cells"].items():
            a = agg[target]
            if cell.get("blocked"):
                a["blocked"] += 1
                continue
            if cell.get("error"):
                a["error"] += 1
                continue
            a["ok"] += 1
            if cell.get("judge_score") is not None:
                a["judge_scores"].append(cell["judge_score"])
            if cell.get("judge_rationale"):
                a["judge_rationales"].append(cell["judge_rationale"])
            for check_result in cell.get("checks") or []:
                a["rule_check_results"].append(check_result["passed"])
            a["costs"].append(cell.get("cost_usd", 0.0))
            a["latencies"].append(cell.get("latency_ms", 0))
            if cell.get("latency_ms_stdev") is not None:
                a["stdevs"].append(cell["latency_ms_stdev"])
            if cell.get("tokens_per_sec") is not None:
                a["rates"].append(cell["tokens_per_sec"])
    return agg


def _stats(agg):
    stats = {}
    for target, a in agg.items():
        latency = _mean(a["latencies"])
        stdev = _mean(a["stdevs"])
        rate = _mean(a["rates"])
        stats[target] = {
            "total_cost_usd": round(sum(a["costs"]), 6),
            "avg_latency_ms": round(latency, 1) if latency is not None else 0.0,
            "avg_latency_stdev_ms": round(stdev, 1) if stdev is not None else None,
            "avg_tokens_per_sec": round(rate, 1) if rate is not None else None,
            "ok_cells": a["ok"],
            "error_cells": a["error"],
            "blocked_cells": a["blocked"],
        }
    return stats


def _grades(agg, stats):
    ok_targets = [t for t, a in agg.items() if a["ok"]]
    all_costs = [stats[t]["total_cost_usd"] for t in ok_targets]
    all_latencies = [stats[t]["avg_latency_ms"] for t in ok_targets]
    all_rates = [stats[t]["avg_tokens_per_sec"] for t in ok_targets if stats[t]["avg_tokens_per_sec"] is not None]
    grades = {}
    for target, a in agg.items():
        grade = grading.grade_model(a["judge_scores"], a["rule_check_results"], a["judge_rationales"])
        ok = bool(a["ok"])
        grade["categories"] = grading.category_scores(
            a["judge_scores"], a["rule_check_results"],
            stats[target]["total_cost_usd"] if ok else None, all_costs,
            stats[target]["avg_latency_ms"] if ok else None, all_latencies,
            tokens_per_sec=stats[target]["avg_tokens_per_sec"] if ok else None, all_tokens_per_sec=all_rates,
        )
        grades[target] = grade
    return grades


def judge_model_label(judge_backend, creds):
    model = config.JUDGE_MODELS[judge_backend]
    region = ((creds or {}).get("bedrock") or {}).get("region") if judge_backend == "bedrock" else None
    if region:
        try:
            return bedrock.resolve_model_id(model, region)
        except gateway.GatewayError:
            return model
    return model


def _provider_of(model_id):
    for token in model_id.replace("/", ".").split("."):
        if token in _PROVIDER_ALIASES:
            return _PROVIDER_ALIASES[token]
    return None


def _bias_note(judge_model, targets, catalog_dict):
    judge_provider = _provider_of(judge_model)
    if not judge_provider:
        return ""
    same = []
    for target in targets:
        model_id, _ = gateway.parse_target(target)
        provider_id, model = catalog.find_model(catalog_dict, model_id)
        if provider_id == judge_provider:
            same.append(model["name"])
    if not same:
        return ""
    return (f"The judge ({judge_model}) is from the same family as {', '.join(same)} — "
            f"scores may lean in its favor.")


def _disallowed_terms(catalog_dict, allowed_ids, allowed_names):
    allowed = [a.lower() for a in (*allowed_ids, *allowed_names)]
    terms = []
    for provider in catalog_dict.values():
        for model in provider["models"]:
            for term in (model["id"], model["name"]):
                low = term.lower()
                if low in allowed or any(low in a for a in allowed):
                    continue
                terms.append(term)
    return terms


def build_run_result(results, targets, creds, judge_backend):
    for row in results:
        row["best_model"] = grading.best_model_for_test_case(row["cells"])

    agg = _aggregate(results, targets)
    stats = _stats(agg)
    grades = _grades(agg, stats)

    verdict = {"winner": None, "rationale": "No models were run."}
    if targets:
        verdict = judge.overall_verdict(
            {t: {"score": grades[t]["score"], "letter": grades[t]["letter"]} for t in targets},
            creds=creds, backend=judge_backend,
        )

    catalog_dict = catalog.load_catalog()
    suggestions = advisor.suggest_all(grades, stats, catalog_dict)

    advice = ""
    ok_targets = [t for t in targets if stats[t]["ok_cells"]]
    if ok_targets:
        summary = {
            "models": {t: {"quality": grades[t]["score"], **{k: grades[t]["categories"][k]
                           for k in ("response_time", "throughput", "cost_efficiency")}} for t in ok_targets},
            "suggestions": {t: {k: s[k] for k in ("model_id", "name", "reason_code")}
                            for t, s in suggestions.items() if s},
        }
        allowed_ids = [gateway.parse_target(t)[0] for t in targets] + [
            gateway.parse_target(s["model_id"])[0] for s in suggestions.values() if s]
        allowed_names = [s["name"] for s in suggestions.values() if s] + [
            m["name"] for m in (catalog.find_model(catalog_dict, i)[1] for i in allowed_ids) if m]
        advice = judge.explain_recommendations(
            summary, creds=creds, backend=judge_backend,
            disallowed_terms=_disallowed_terms(catalog_dict, allowed_ids, allowed_names),
        )

    judge_model = judge_model_label(judge_backend, creds)
    return {
        "results": results,
        "grades": grades,
        "stats": stats,
        "verdict": verdict,
        "suggestions": suggestions,
        "advice": advice,
        "judge": {"backend": judge_backend, "model": judge_model},
        "bias_note": _bias_note(judge_model, targets, catalog_dict),
    }
```

Run `venv/bin/pytest tests/test_analysis.py -q` → PASS.

- [ ] **Step 3: Wire `app.py`.**
  - Add `import analysis` and `import config`. Delete `_aggregate_stats`, `_cost_latency_stats`, and `_category_scores_by_model`.
  - In `_validate_run_body`, after the `models` type check, add:

```python
    if len(body["models"]) > config.MAX_MODELS:
        return f"Pick at most {config.MAX_MODELS} models."
    repeats = body.get("repeats", 1)
    if isinstance(repeats, bool) or repeats not in (1, 2, 3):
        return "repeats must be 1, 2, or 3."
```

  - In `api_run`, read `repeats = body.get("repeats", 1)` next to `model_ids`. Replace everything inside the `try:` with:

```python
        results = runner.run(
            test_cases, model_ids, creds=creds, policy_text=policy_text, judge_backend=judge_backend,
            repeats=repeats,
        )
        run_result = analysis.build_run_result(results, model_ids, creds, judge_backend)
```

    Keep the existing `except` block unchanged. After it, replace the `run_result = {...}` literal with
    `run_result = {"run_id": str(uuid.uuid4()), "created_at": time.time(), **run_result}`.
  - `api_catalog` returns
    `{"providers": cat, "frontier": ..., "max_models": config.MAX_MODELS, "priority_weights": grading.PRIORITY_WEIGHTS, "priority_labels": grading.PRIORITY_LABELS}`.
  - `api_report`: read `priority = request.args.get("priority", "balanced")`. If it isn't in `grading.PRIORITY_WEIGHTS`, return `_error_response("Invalid priority.", 400)` (with the session cookie) before looking up the run.

- [ ] **Step 4: Wire `mcp_server.py`.**
  - Add `import analysis`, `import config`, `import grading`. Delete its `_aggregate_stats`, `_cost_latency_stats`, and `_category_scores_by_model`.
  - Change the signature to `run_comparison(test_cases: list[dict], models: list[str], api_key: str = "", creds: dict | None = None, judge_backend: str = "openrouter", priority: str = "balanced", repeats: int = 1) -> dict`.
  - Append this sentence to the docstring: `At most 4 models. priority (balanced|quality|fastest|cheapest) ranks the results; repeats (1-3) re-sends each prompt for timing accuracy. Returns suggestions (same provider and backend only), advice, ranking, and best_for_priority.`
  - After the `judge_backend` validation, add:

```python
    if len(models) > config.MAX_MODELS:
        return {"error": f"Pick at most {config.MAX_MODELS} models."}
    if priority not in grading.PRIORITY_WEIGHTS:
        return {"error": "Invalid priority."}
    if isinstance(repeats, bool) or repeats not in (1, 2, 3):
        return {"error": "repeats must be 1, 2, or 3."}
```

  - Replace the `try:` body with
    `results = runner.run(test_cases, models, creds=prepared, policy_text=_policy_text, judge_backend=judge_backend, repeats=repeats)`
    and `run_result = analysis.build_run_result(results, models, prepared, judge_backend)`. Keep the `except` block.
  - Build the final dict as `{"run_id": ..., "created_at": ..., **run_result}` and then add
    `run_result["ranking"] = grading.rank_targets(run_result["grades"], run_result["stats"], priority)` and
    `run_result["best_for_priority"] = run_result["ranking"][0] if run_result["ranking"] else None`, before appending to `_run_history`.

- [ ] **Step 5: Append to `tests/test_app.py`:**

```python


def test_api_run_rejects_more_than_four_models():
    resp = _client().post("/api/run", json={
        "test_cases": [{"prompt": "q"}], "models": ["a/1", "a/2", "a/3", "a/4", "a/5"], "api_key": "sk-or-v1-test"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "Pick at most 4 models."
    assert all(len(v) == 0 for v in limiter._attempts.values())


@pytest.mark.parametrize("repeats", [0, 4, "2", True])
def test_api_run_rejects_bad_repeats(repeats):
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test", "repeats": repeats})
    assert resp.status_code == 400


@patch("app.analysis.build_run_result")
@patch("app.runner.run")
def test_api_run_passes_repeats_and_returns_analysis_fields(mock_run, mock_build):
    mock_run.return_value = []
    mock_build.return_value = {"results": [], "grades": {}, "stats": {}, "verdict": {"winner": None, "rationale": ""},
                               "suggestions": {}, "advice": "", "judge": {"backend": "openrouter", "model": "m"},
                               "bias_note": ""}
    resp = _client().post("/api/run", json={
        "test_cases": [], "models": ["openai/gpt-5"], "api_key": "sk-or-v1-test", "repeats": 3})
    assert resp.status_code == 200
    assert mock_run.call_args[1]["repeats"] == 3
    body = resp.get_json()
    assert {"run_id", "created_at", "suggestions", "advice", "judge", "bias_note"} <= set(body)


def test_api_catalog_exposes_cap_and_priority_weights():
    body = _client().get("/api/catalog").get_json()
    assert body["max_models"] == 4
    assert set(body["priority_weights"]) == {"balanced", "quality", "fastest", "cheapest"}
    assert body["priority_labels"]["fastest"] == "Fastest"


def test_api_report_rejects_invalid_priority():
    assert _client().get("/api/report?priority=vibes").status_code == 400
```

(Add `import pytest` at the top if it isn't there.) Existing app tests that mock `app.judge.overall_verdict` keep working because `analysis` calls `judge.overall_verdict` on the same module object. **However**, `analysis.build_run_result` also calls `judge.explain_recommendations`. For any existing test that mocks `app.runner.run` to return non-empty results with successful cells, also patch `analysis.judge.explain_recommendations` (return `""`) so no network is attempted. Run the suite and fix only those tests.

Append to `tests/test_mcp_server.py`:

```python


def test_run_comparison_rejects_more_than_four_models():
    result = mcp_server.run_comparison(test_cases=[], models=["a/1", "a/2", "a/3", "a/4", "a/5"], api_key="sk-or-v1-test")
    assert result == {"error": "Pick at most 4 models."}


def test_run_comparison_rejects_invalid_priority_and_repeats():
    assert mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test", priority="vibes") == {"error": "Invalid priority."}
    assert mcp_server.run_comparison(test_cases=[], models=[], api_key="sk-or-v1-test", repeats=5) == {"error": "repeats must be 1, 2, or 3."}


@patch("mcp_server.analysis.build_run_result")
@patch("mcp_server.runner.run", return_value=[])
def test_run_comparison_returns_ranking_for_priority(mock_run, mock_build):
    mock_build.return_value = {
        "results": [], "verdict": {"winner": None, "rationale": ""}, "suggestions": {}, "advice": "",
        "judge": {"backend": "openrouter", "model": "m"}, "bias_note": "",
        "grades": {"a/x": {"score": 95, "categories": {"response_time": 0, "throughput": 0, "cost_efficiency": 0}},
                   "a/y": {"score": 70, "categories": {"response_time": 100, "throughput": 100, "cost_efficiency": 100}}},
        "stats": {"a/x": {"ok_cells": 1, "avg_latency_ms": 900}, "a/y": {"ok_cells": 1, "avg_latency_ms": 100}},
    }
    result = mcp_server.run_comparison(test_cases=[], models=["a/x", "a/y"], api_key="sk-or-v1-test", priority="fastest", repeats=2)
    assert result["ranking"] == ["a/y", "a/x"]
    assert result["best_for_priority"] == "a/y"
    assert mock_run.call_args[1]["repeats"] == 2
```

- [ ] **Step 6: Run** `venv/bin/pytest tests/ -q` → all PASS, including the MCP e2e tests. Also check that `grep -n "_aggregate_stats\|_cost_latency_stats\|_category_scores_by_model" app.py mcp_server.py` prints nothing.

- [ ] **Step 7: Commit**: `analysis.py app.py mcp_server.py tests/test_analysis.py tests/test_app.py tests/test_mcp_server.py`, subject `feat: shared run analysis with suggestions, advice, judge disclosure; 4-model cap, repeats, priority`.

---

### Task 7: Reports — new categories, tok/s, priority, judge line, suggestions

**Files:**
- Modify: `report.py`, `app.py` (switch the `build_pdf` call to pass `priority`)
- Test: `tests/test_report.py`

**Interfaces:**
- Produces: `report.build_pdf(run_result, priority=None) -> bytes`; CSV columns per below.

- [ ] **Step 1: Update tests.** In `tests/test_report.py`, rename every `"speed"` category key in the fixtures to `"response_time"` and add `"throughput": 75.0` next to it. In `test_build_csv_returns_string_with_header_row`, change the expected header list to:

```python
        "prompt", "model_id", "status", "response_text", "judge_score",
        "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens", "tokens_per_sec",
        "accuracy_score", "rule_checks_score", "cost_efficiency_score", "response_time_score", "throughput_score",
        "best_model_for_prompt", "best_model_reason",
```

Fix `test_build_csv_row_values_for_ok_cell` / `..._blocked_cell` for the extra columns: `tokens_per_sec` goes right after `tokens` (empty string when absent), and `throughput_score` goes after `response_time_score`. Then append:

```python


def test_pdf_includes_priority_judge_suggestions_and_bias_note():
    run = dict(_sample_run())
    run["judge"] = {"backend": "openrouter", "model": "openai/gpt-4o-mini"}
    run["suggestions"] = {next(iter(run["grades"])): {"model_id": "anthropic/claude-haiku-4.5", "name": "Claude Haiku 4.5",
                                                      "reason_code": "latency", "reason": "Faster tier."}}
    run["advice"] = "Pick the faster one."
    run["bias_note"] = "The judge is from the same family."
    pdf_bytes = report.build_pdf(run, priority="fastest")
    text = _pdf_text(pdf_bytes)
    assert "Priority: Fastest" in text
    assert "Judged by openai/gpt-4o-mini via OpenRouter" in text
    assert "Claude Haiku 4.5" in text and "Pick the faster one." in text and "same family" in text


def test_build_csv_includes_tokens_per_sec():
    run = _sample_run()
    first_cell = next(iter(run["results"][0]["cells"].values()))
    first_cell["tokens_per_sec"] = 42.5
    assert "42.5" in report.build_csv(run)
```

If the file has no `_sample_run()` / `_pdf_text()` helpers, name the existing run fixture function accordingly, or add

```python
def _pdf_text(pdf_bytes):
    import io
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
```

- [ ] **Step 2: Verify failure**: `venv/bin/pytest tests/test_report.py -q` → FAIL.

- [ ] **Step 3: Implement** in `report.py`:
  - `import catalog`, `import gateway`, `import grading`.
  - `_CATEGORY_COLORS` keys: `accuracy`, `rule_checks`, `cost_efficiency`, `response_time` (`#f9ab00`), `throughput` (`#e8710a`). `_CATEGORY_LABELS`: `"response_time": "Response Time"`, `"throughput": "Speed (tok/s)"`.
  - `_CSV_FIELDS` as in the test, with row values in the same order. `tokens_per_sec` is the cell's value or `""`. Blocked/error rows put `""` there.
  - `_is_reasoning(target)`: `model_id, _ = gateway.parse_target(target); _, m = catalog.find_model(catalog.load_catalog(), model_id); return bool(m and m.get("reasoning"))`.
  - `build_pdf(run_result, priority=None)`: after the timestamp, if `run_result.get("judge")` print
    `f"Judged by {judge['model']} via {gateway.BACKEND_LABELS.get(judge['backend'], judge['backend'])}"`. If `priority` is set, print
    `f"Priority: {grading.PRIORITY_LABELS[priority]} - best pick: {ranking[0] if ranking else 'n/a'}"` using `grading.rank_targets(grades, stats, priority)`.
  - Leaderboard columns `(55, 20, 20, 30, 30, 25)` with header `"Tok/s"`. The value is `stats avg_tokens_per_sec`, prefixed `"~"` for reasoning targets, or `"N/A"`.
  - Category table: 6 columns `("Model", "Accuracy", "Checks", "Cost Eff.", "Resp. Time", "Speed")`, widths `(55, 25, 25, 25, 25, 25)`, keys in `_CATEGORY_COLORS` order.
  - After the chart, if any suggestion, advice, or bias note exists, add a "Suggestions" section: one line per target, `"{target}: try {name} - {reason}"` or `"{target}: good fit - no better option in this catalog"` (skip targets with no stats). Then the advice paragraph, then the bias note. Add a footnote line `"~ = approximate: includes hidden reasoning tokens on some providers."` if any reasoning target is present.
  - Keep Courier fonts. Replace `—` with `-` in PDF strings (core fonts are Latin-1).
  - `app.py` `api_report`: call `report.build_pdf(run_result, priority=priority)`.

- [ ] **Step 4: Run** `venv/bin/pytest tests/test_report.py -q` → PASS; full suite → PASS; `grep -n '"speed"' report.py` prints nothing.
- [ ] **Step 5: Commit**: `report.py app.py tests/test_report.py`, subject `feat: reports show response time, speed, priority pick, judge, and suggestions`.

---

### Task 8: Frontend — cap, side-by-side view, priority, Try it, repeats, cost estimate, help

**Files:**
- Modify: `templates/index.html`, `static/style.css`, `static/app.js`

**Interfaces:**
- Consumes: `/api/catalog` (`max_models`, `priority_weights`, `priority_labels`, model `tier`/`reasoning`/`routes`), `/api/openrouter-models` (`pricing`), `/api/run` (`repeats`, and the response fields from Task 6), `/api/report?priority=`.

- [ ] **Step 1: `templates/index.html`.** Replace the `#run-section` contents with:

```html
  <section id="run-section">
    <div class="run-options">
      <label for="priority">What matters most?</label>
      <select id="priority">
        <option value="balanced" selected>Balanced</option>
        <option value="quality">Best quality</option>
        <option value="fastest">Fastest</option>
        <option value="cheapest">Cheapest</option>
      </select>
      <label for="repeats">Repeat each prompt</label>
      <select id="repeats" aria-describedby="repeats-hint">
        <option value="1" selected>1×</option>
        <option value="2">2×</option>
        <option value="3">3×</option>
      </select>
      <span id="repeats-hint" class="status-text">More accurate timing; multiplies model calls and cost.</span>
    </div>
    <p class="run-meta"><span id="selection-count">Selected 0 / 4</span> <span id="cost-estimate" class="status-text"></span></p>
    <button id="run-button">Run comparison</button>
    <span id="run-status" class="status-text"></span>
  </section>
```

In `#results-section`, directly after the `#verdict-banner` div, insert:

```html
    <h2>Side-by-side</h2>
    <p id="judge-line" class="status-text"></p>
    <div id="compare-grid" class="compare-grid"></div>
    <div id="advice-box" class="card advice-box" hidden></div>
    <details class="card help-box">
      <summary>How to read this</summary>
      <ul>
        <li><strong>Chat and interactive UIs</strong> — prioritize <em>Response time</em> (how long until the full answer arrives).</li>
        <li><strong>Long outputs</strong> (reports, code) — prioritize <em>Speed</em> (tokens per second).</li>
        <li><strong>Accuracy-critical work</strong> — choose <em>Best quality</em>.</li>
        <li>If two models are within ~5 quality points, prefer the faster or cheaper one.</li>
        <li>Run 3+ representative prompts before deciding — one prompt is noisy. Use "Repeat each prompt" for steadier timing.</li>
        <li>Suggestions only name models from the <em>same provider</em> on the backend you used.</li>
        <li>A judge can favor its own model family — for important decisions, re-run with a judge from a different provider.</li>
        <li>"≈" speeds include hidden reasoning tokens on some providers and are approximate.</li>
      </ul>
    </details>
```

- [ ] **Step 2: `static/style.css`.** Append:

```css

.run-options { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-bottom: 8px; }
.run-options label { margin: 0; }
#priority, #repeats {
  font-family: inherit; font-size: 13px; padding: 4px 8px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--fg);
}
.run-meta { margin: 0 0 8px; font-size: 12px; color: var(--muted); }
.compare-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 12px; }
.compare-col { border: 1px solid var(--border); border-radius: 10px; padding: 12px; background: var(--surface); }
.compare-col.best { border-color: var(--grade-a); box-shadow: 0 0 0 1px var(--grade-a) inset; }
.compare-title { font-weight: bold; font-size: 13px; word-break: break-all; margin: 0 0 6px; }
.best-badge { display: inline-block; font-size: 10px; padding: 1px 8px; border-radius: 999px; background: var(--grade-a); color: #fff; margin-bottom: 6px; }
.metric { margin: 6px 0; font-size: 12px; }
.metric-bar { height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; margin-top: 2px; }
.metric-fill { height: 100%; background: var(--fg); }
.compare-raw { font-size: 11px; color: var(--muted); margin: 6px 0; }
.compare-suggestion { font-size: 12px; margin-top: 8px; }
.compare-suggestion button { margin-top: 4px; }
.advice-box { font-size: 13px; margin-bottom: 12px; }
.help-box summary { cursor: pointer; font-size: 13px; }
.help-box ul { font-size: 12px; margin: 8px 0 0; padding-left: 18px; }
```

- [ ] **Step 3: `static/app.js`: selection cap, visual sync, `data-target`.**
  - In `modelBadge`, add `el.dataset.target = model.id;`. In the chip loop, add `chip.dataset.target = \`${model.id}@${backend}\`;`.
  - Add near the top (after `escapeHtml`):

```javascript
function maxModels() {
  return (state.catalog && state.catalog.max_models) || 4;
}

function capMessage() {
  return `You can compare up to ${maxModels()} models — deselect one first.`;
}

function atCap() {
  return state.selectedModels.size >= maxModels();
}

function syncSelectionVisuals() {
  document.querySelectorAll(".model-badge[data-target], .backend-chip[data-target]").forEach((el) => {
    el.classList.toggle("selected", state.selectedModels.has(el.dataset.target));
  });
}
```

  - In `toggleBackendTarget`, `toggleModel`, and `addCustomModel`, before adding a new target, add:
    `if (atCap()) { document.getElementById("run-status").textContent = capMessage(); return; }`.
    Replace their per-element `classList.add/remove("selected")` calls with a call to `syncSelectionVisuals()`, so duplicate badges (frontier and provider list) stay in sync. At the end of each of those functions, and in `removeCustomModel`, call `updateSelectionMeta()`.

- [ ] **Step 4: `static/app.js`: cost estimate.** Add:

```javascript
const OUTPUT_TOKENS_GUESS = 500;

function catalogModel(modelId) {
  if (!state.catalog) return null;
  for (const provider of Object.values(state.catalog.providers)) {
    const model = provider.models.find((m) => m.id === modelId);
    if (model) return model;
  }
  return null;
}

function splitTarget(target) {
  const backend = targetBackend(target);
  return { backend, modelId: backend === "openrouter" ? target : target.slice(0, target.lastIndexOf("@")) };
}

function priceForTarget(target) {
  const { backend, modelId } = splitTarget(target);
  if (backend !== "openrouter") {
    const model = catalogModel(modelId);
    const price = model && model.routes && model.routes[backend] && model.routes[backend].price;
    return price ? { input: price.input_per_m / 1e6, output: price.output_per_m / 1e6 } : null;
  }
  const live = state.allModels.find((m) => m.id === modelId);
  return live && live.pricing ? { input: live.pricing.prompt, output: live.pricing.completion } : null;
}

function estimateCost() {
  const repeats = Number(document.getElementById("repeats").value || 1);
  let total = 0;
  const unpriced = [];
  state.selectedModels.forEach((target) => {
    const price = priceForTarget(target);
    if (!price) {
      unpriced.push(target);
      return;
    }
    state.testCases.forEach((tc) => {
      const inputTokens = Math.ceil((tc.prompt || "").length / 4);
      total += repeats * (inputTokens * price.input + OUTPUT_TOKENS_GUESS * price.output);
    });
  });
  return { total, unpriced };
}

function updateSelectionMeta() {
  document.getElementById("selection-count").textContent = `Selected ${state.selectedModels.size} / ${maxModels()}`;
  const el = document.getElementById("cost-estimate");
  if (state.selectedModels.size === 0) {
    el.textContent = "";
    return;
  }
  const { total, unpriced } = estimateCost();
  let text = `· Estimated cost: ~$${total.toFixed(4)} (rough; excludes judge calls)`;
  if (unpriced.length) text += ` · unavailable for ${unpriced.length} model(s)`;
  el.textContent = text;
}
```

  Call `updateSelectionMeta()` at the end of `loadCatalogAndModels()`, inside the `renderTestCases` input listener (after updating state), in `addTestCase`, and on `#repeats` change (`document.getElementById("repeats").addEventListener("change", updateSelectionMeta);` next to the other listeners at the bottom).

- [ ] **Step 5: `static/app.js`: ranking (must match `grading.rank_targets`).** Add:

```javascript
function rawWeightedScore(grade, priority) {
  const weights = state.catalog.priority_weights[priority];
  const cats = grade.categories || {};
  const values = { quality: grade.score, response_time: cats.response_time, throughput: cats.throughput, cost_efficiency: cats.cost_efficiency };
  let total = 0;
  let sum = 0;
  Object.entries(weights).forEach(([key, w]) => {
    if (w > 0 && values[key] !== null && values[key] !== undefined) {
      total += w;
      sum += values[key] * w;
    }
  });
  return total ? sum / total : null;
}

function rankTargets(data, priority) {
  const scored = Object.keys(data.grades).filter((t) => {
    const s = data.stats[t] || {};
    return (s.ok_cells || 0) > 0 && rawWeightedScore(data.grades[t], priority) !== null;
  });
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  return scored.sort((a, b) => {
    const diff = rawWeightedScore(data.grades[b], priority) - rawWeightedScore(data.grades[a], priority);
    if (diff !== 0) return diff;
    const qa = data.grades[a].score ?? -1;
    const qb = data.grades[b].score ?? -1;
    if (qa !== qb) return qb - qa;
    const la = data.stats[a].avg_latency_ms ?? Infinity;
    const lb = data.stats[b].avg_latency_ms ?? Infinity;
    if (la !== lb) return la - lb;
    return cmp(a, b);
  });
}
```

- [ ] **Step 6: `static/app.js`: side-by-side view, advice, Try it.** Add:

```javascript
const COMPARE_METRICS = [["quality", "Quality"], ["response_time", "Response time"], ["throughput", "Speed"], ["cost_efficiency", "Cost"]];

function metricRow(label, value) {
  const wrap = document.createElement("div");
  wrap.className = "metric";
  const text = value === null || value === undefined ? `${label} n/a` : `${label} ${Math.round(value)}/100`;
  wrap.textContent = text;
  const bar = document.createElement("div");
  bar.className = "metric-bar";
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", text);
  const fill = document.createElement("div");
  fill.className = "metric-fill";
  fill.style.width = `${value === null || value === undefined ? 0 : Math.max(0, Math.min(100, value))}%`;
  bar.appendChild(fill);
  wrap.appendChild(bar);
  return wrap;
}

function renderCompareGrid(data) {
  const grid = document.getElementById("compare-grid");
  grid.innerHTML = "";
  const priority = document.getElementById("priority").value;
  const ranking = rankTargets(data, priority);
  const best = ranking.length > 1 ? ranking[0] : null;

  Object.entries(data.grades).forEach(([target, grade]) => {
    const stats = data.stats[target] || {};
    const cats = grade.categories || {};
    const col = document.createElement("div");
    col.className = "compare-col" + (target === best ? " best" : "");

    if (target === best) {
      const badge = document.createElement("span");
      badge.className = "best-badge";
      badge.textContent = `Best for ${state.catalog.priority_labels[priority]}`;
      col.appendChild(badge);
    }
    const title = document.createElement("p");
    title.className = "compare-title";
    title.textContent = `${target} · ${grade.letter || "N/A"}`;
    col.appendChild(title);

    if ((stats.ok_cells || 0) === 0) {
      const none = document.createElement("p");
      none.className = "status-fail";
      none.textContent = `No successful responses (${stats.error_cells || 0} errors, ${stats.blocked_cells || 0} blocked)`;
      col.appendChild(none);
      grid.appendChild(col);
      return;
    }

    COMPARE_METRICS.forEach(([key, label]) => col.appendChild(metricRow(label, key === "quality" ? grade.score : cats[key])));

    const model = catalogModel(splitTarget(target).modelId);
    const approx = model && model.reasoning ? "≈ " : "";
    const raw = document.createElement("p");
    raw.className = "compare-raw";
    const latency = `${Math.round(stats.avg_latency_ms)} ms${stats.avg_latency_stdev_ms ? ` ± ${Math.round(stats.avg_latency_stdev_ms)}` : ""}`;
    const speed = stats.avg_tokens_per_sec ? `${approx}${stats.avg_tokens_per_sec} tok/s` : "speed n/a";
    raw.textContent = `${latency} · ${speed} · $${(stats.total_cost_usd || 0).toFixed(4)}`;
    col.appendChild(raw);

    const suggestion = (data.suggestions || {})[target];
    const sugEl = document.createElement("div");
    sugEl.className = "compare-suggestion";
    if (suggestion) {
      const text = document.createElement("p");
      text.textContent = `Try ${suggestion.name}: ${suggestion.reason}`;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = "Try it";
      button.setAttribute("aria-label", `Swap ${target} for ${suggestion.model_id} in your selection`);
      button.addEventListener("click", () => tryIt(target, suggestion.model_id));
      sugEl.append(text, button);
    } else {
      sugEl.textContent = "Good fit — no better option in this catalog.";
    }
    col.appendChild(sugEl);
    grid.appendChild(col);
  });

  const judgeLine = document.getElementById("judge-line");
  judgeLine.textContent = data.judge ? `Judged by ${data.judge.model} via ${BACKEND_LABELS[data.judge.backend] || data.judge.backend}` : "";

  const adviceBox = document.getElementById("advice-box");
  adviceBox.innerHTML = "";
  const lines = [];
  if (data.advice) {
    lines.push(data.advice);
  } else {
    Object.values(data.suggestions || {}).filter(Boolean).forEach((s) => lines.push(s.reason));
  }
  if (data.bias_note) lines.push(data.bias_note);
  lines.forEach((line) => {
    const p = document.createElement("p");
    p.textContent = line;
    adviceBox.appendChild(p);
  });
  adviceBox.hidden = lines.length === 0;
}

function tryIt(oldTarget, newTarget) {
  const status = document.getElementById("run-status");
  if (state.selectedModels.has(newTarget)) {
    status.textContent = `${newTarget} is already selected.`;
    return;
  }
  if (!state.selectedModels.has(oldTarget) && atCap()) {
    status.textContent = capMessage();
    return;
  }
  state.selectedModels.delete(oldTarget);
  state.selectedModels.add(newTarget);
  syncSelectionVisuals();
  updateSelectionMeta();
  status.textContent = `Swapped ${oldTarget} → ${newTarget}. Click Run comparison to test it.`;
}
```

  - In `renderResults(data)`, after the verdict line, call `renderCompareGrid(data);`.
  - Add a listener: `document.getElementById("priority").addEventListener("change", () => { const run = state.runs.find((r) => r.run_id === state.activeRunId); if (run) renderCompareGrid(run); });`.
  - `CATEGORY_LABELS`: replace the `speed` entry with `response_time: ["Resp. Time", "#f9ab00"],` and add `throughput: ["Speed", "#e8710a"],`.
  - `runComparison`: after the "Pick at least one model." check, add
    `if (state.selectedModels.size > maxModels()) { runStatus.textContent = capMessage(); return; }`
    and add `repeats: Number(document.getElementById("repeats").value || 1),` to the JSON body.
  - `downloadReport`: append `&priority=${encodeURIComponent(document.getElementById("priority").value)}` to the URL.

- [ ] **Step 7: Verify**

```bash
node --check static/app.js
grep -n "categories\[\"speed\"\]\|speed: \[" static/app.js
venv/bin/pytest tests/ -q
venv/bin/python -c "import app; c = app.app.test_client(); r = c.get('/'); assert r.status_code == 200 and b'compare-grid' in r.data and b'id=\"priority\"' in r.data and b'id=\"repeats\"' in r.data; print('index renders')"
```

Expected: `node --check` is silent, the grep prints nothing, the suite passes, and the script prints `index renders`.

- [ ] **Step 8: Commit**: `templates/index.html static/style.css static/app.js`, subject `feat: side-by-side 4-model view with priority ranking, suggestions, Try it, repeats, and cost estimate`.

---

### Task 9: Docs

**Files:**
- Modify: `README.md`; `CLAUDE.md` (untracked — edit, don't commit)

- [ ] **Step 1: README.** Add a section `## Comparing up to 4 models` after the Backends section. It should cover:
  - the four metrics and what each means (Quality = judge + checks; Response time = full-answer latency; Speed = output tokens/sec, "≈" for reasoning models; Cost = relative total cost);
  - the "What matters most?" priority selector and the "Best for …" badge;
  - suggestions (same provider and backend only, rules pick them, the judge writes the explanation, and it **adds one extra judge call per run**);
  - Try it; Repeat each prompt (1–3×, timing only, still one run against the rate limit);
  - the rough cost estimate (500 output tokens per call, excludes judge calls);
  - the judge-bias caveat.

  In the MCP section, document `priority`, `repeats`, and the returned `suggestions`, `advice`, `ranking`, `best_for_priority`, `judge`, `bias_note`, plus the 4-model limit.
- [ ] **Step 2: CLAUDE.md.** Add `advisor.py` and `analysis.py` to the "All modules are built" list. Add Architecture bullets:
  - **`analysis.py`**: owns post-run assembly for both app.py and mcp_server.py (stats, grades, verdict, suggestions, advice, judge disclosure).
  - **`advisor.py`**: pure, rule-based same-provider/same-backend suggestions using catalog `tier`.

  Note the category keys `response_time`/`throughput` and the 4-model cap under Conventions.
- [ ] **Step 3: Verify**: `venv/bin/pytest tests/ -q` → PASS (docs only).
- [ ] **Step 4: Commit**: `README.md` only, subject `docs: document 4-model comparison, priorities, suggestions, repeats, and cost estimate`.
