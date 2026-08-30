from concurrent.futures import ThreadPoolExecutor

import checks
import judge
import openrouter
import policy


def _run_one_cell(test_case, model_id, api_key, policy_text):
    prompt = test_case["prompt"]

    if policy_text:
        policy_result = policy.check_policy(prompt, policy_text, api_key=api_key)
        if policy_result["violates"]:
            return {
                "model_id": model_id,
                "blocked": True,
                "policy_clause": policy_result["clause"],
                "policy_reason": policy_result["reason"],
            }

    try:
        response = openrouter.call_model(model_id, [{"role": "user", "content": prompt}], api_key=api_key)
    except openrouter.OpenRouterError as e:
        return {"model_id": model_id, "blocked": False, "error": str(e)}

    check_results = []
    if test_case.get("checks"):
        check_results = checks.run_checks(test_case["checks"], response["text"])

    judge_score = None
    judge_rationale = None
    if test_case.get("rubric"):
        judge_result = judge.llm_judge(response["text"], test_case["rubric"], api_key=api_key)
        judge_score = judge_result["score"]
        judge_rationale = judge_result["rationale"]

    return {
        "model_id": model_id,
        "blocked": False,
        "error": None,
        "response_text": response["text"],
        "latency_ms": response["latency_ms"],
        "cost_usd": response["cost_usd"],
        "tokens": response["tokens"],
        "checks": check_results,
        "judge_score": judge_score,
        "judge_rationale": judge_rationale,
    }


def run(test_cases, model_ids, api_key, policy_text=None):
    cells_by_tc = {i: {} for i in range(len(test_cases))}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {}
        for tc_index, test_case in enumerate(test_cases):
            for model_id in model_ids:
                future = pool.submit(_run_one_cell, test_case, model_id, api_key, policy_text)
                futures[future] = (tc_index, model_id)

        for future, (tc_index, model_id) in futures.items():
            cells_by_tc[tc_index][model_id] = future.result()

    return [
        {"test_case": test_case, "cells": cells_by_tc[tc_index]}
        for tc_index, test_case in enumerate(test_cases)
    ]
