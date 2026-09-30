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

_PROVIDER_STEMS = {"openai": ["OpenAI", "GPT", "ChatGPT"], "anthropic": ["Anthropic", "Claude"],
                   "google": ["Google", "Gemini", "Gemma"], "meta-llama": ["Meta", "Llama"]}
_OFF_CATALOG_VENDORS = ["DeepSeek", "Mistral", "Mixtral", "Qwen", "Grok", "xAI", "Cohere"]
_BACKEND_LABEL_TERMS = ["OpenRouter", "Amazon Bedrock", "Bedrock", "Google Vertex AI", "Vertex AI",
                        "Microsoft Foundry", "Foundry"]


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
            "avg_latency_ms": round(float(latency), 1) if latency is not None else 0.0,
            "avg_latency_stdev_ms": round(float(stdev), 1) if stdev is not None else None,
            "avg_tokens_per_sec": round(float(rate), 1) if rate is not None else None,
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
    present_providers = {catalog.find_model(catalog_dict, model_id)[0] for model_id in allowed_ids}
    terms = []
    for provider_id, provider in catalog_dict.items():
        for model in provider["models"]:
            for term in (model["id"], model["name"]):
                low = term.lower()
                if low in allowed:
                    continue
                terms.append(term)
        if provider_id not in present_providers:
            terms.extend(_PROVIDER_STEMS.get(provider_id, []))
    terms.extend(_OFF_CATALOG_VENDORS)
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
            allowed_terms=[*allowed_ids, *allowed_names, *_BACKEND_LABEL_TERMS],
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
