GRADE_BOUNDARIES = [
    (97, "A+"), (93, "A"), (90, "A-"),
    (87, "B+"), (83, "B"), (80, "B-"),
    (77, "C+"), (73, "C"), (70, "C-"),
    (60, "D"), (0, "F"),
]


def letter_grade(score):
    for threshold, letter in GRADE_BOUNDARIES:
        if score >= threshold:
            return letter
    return "F"


def compute_score(judge_scores, rule_check_results):
    judge_component = None
    if judge_scores:
        judge_component = (sum(judge_scores) / len(judge_scores)) * 20

    rule_component = None
    if rule_check_results:
        rule_component = 100 * (sum(1 for r in rule_check_results if r) / len(rule_check_results))

    if judge_component is not None and rule_component is not None:
        return round(judge_component * 0.7 + rule_component * 0.3, 1)
    if judge_component is not None:
        return round(judge_component, 1)
    if rule_component is not None:
        return round(rule_component, 1)
    return None


def summary_sentence(score, letter, rule_check_results, judge_rationales):
    if score is None:
        return "No scoring data available for this model."

    if letter in ("A+", "A", "A-"):
        tier_phrase = "Strong performer"
    elif letter in ("B+", "B", "B-"):
        tier_phrase = "Solid performer"
    elif letter in ("C+", "C", "C-"):
        tier_phrase = "Middling performer"
    elif letter == "D":
        tier_phrase = "Weak performer"
    else:
        tier_phrase = "Poor performer"

    detail = ""
    if rule_check_results:
        fail_count = sum(1 for r in rule_check_results if not r)
        if fail_count > 0:
            detail = f" Failed {fail_count} of {len(rule_check_results)} rule checks."
        else:
            detail = " Passed all rule checks."
    elif judge_rationales:
        detail = f" {judge_rationales[0]}"

    return f"{tier_phrase} ({letter}, {score}/100).{detail}"


def grade_model(judge_scores, rule_check_results, judge_rationales):
    score = compute_score(judge_scores, rule_check_results)
    if score is None:
        return {"score": None, "letter": None, "sentence": "No scoring data available for this model."}
    letter = letter_grade(score)
    sentence = summary_sentence(score, letter, rule_check_results, judge_rationales)
    return {"score": score, "letter": letter, "sentence": sentence}


def _relative_score(value, values, lower_is_better):
    if value is None or not values:
        return None
    lo, hi = min(values), max(values)
    if hi == lo:
        return 100.0
    fraction = (hi - value) / (hi - lo) if lower_is_better else (value - lo) / (hi - lo)
    return round(100 * fraction, 1)


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


def best_model_for_test_case(cells):
    """Pick the best-performing model for one specific prompt, with a reason.

    Purely data-driven from what runner.run() already collected — no extra LLM
    call. Prefers judge score (if a rubric was used), falls back to rule-check
    pass rate, falls back to fastest response as a neutral tiebreaker when
    neither scoring signal is available.
    """
    candidates = [
        (model_id, cell) for model_id, cell in cells.items()
        if not cell.get("blocked") and not cell.get("error")
    ]
    if not candidates:
        return {"model_id": None, "reason": "No successful responses to compare for this prompt."}

    if any(cell.get("judge_score") is not None for _, cell in candidates):
        def judge_key(item):
            _, cell = item
            score = cell.get("judge_score") if cell.get("judge_score") is not None else -1
            passed = sum(1 for r in (cell.get("checks") or []) if r["passed"])
            return (-score, -passed, cell.get("latency_ms", float("inf")))

        model_id, cell = min(candidates, key=judge_key)
        rationale = cell.get("judge_rationale") or "highest judge score among the models compared."
        return {"model_id": model_id, "reason": f"Judge score {cell['judge_score']}/5 - {rationale}"}

    if any(cell.get("checks") for _, cell in candidates):
        def checks_key(item):
            _, cell = item
            checks = cell.get("checks") or []
            rate = (sum(1 for r in checks if r["passed"]) / len(checks)) if checks else 0
            return (-rate, cell.get("latency_ms", float("inf")))

        model_id, cell = min(candidates, key=checks_key)
        checks = cell.get("checks") or []
        passed = sum(1 for r in checks if r["passed"])
        return {
            "model_id": model_id,
            "reason": f"Passed {passed}/{len(checks)} rule checks, {cell.get('latency_ms')}ms response time.",
        }

    model_id, cell = min(candidates, key=lambda item: item[1].get("latency_ms", float("inf")))
    return {
        "model_id": model_id,
        "reason": (
            "No rubric or rule checks were defined for this prompt, so this is just the "
            "fastest response — add a rubric or checks for a substantive comparison."
        ),
    }
