from concurrent.futures import ThreadPoolExecutor
import statistics

import checks
import gateway
import judge
import policy
import scrub


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
