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
