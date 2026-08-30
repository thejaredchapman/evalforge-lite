import csv
import io

import report


def _sample_run_result(
    include_block=False, include_error=False, include_stats=False,
    include_categories=False, include_best_model=False,
):
    cell_ok = {
        "model_id": "openai/gpt-5", "blocked": False, "error": None,
        "response_text": "Paris is the capital of France.",
        "latency_ms": 120, "cost_usd": 0.002, "tokens": 30,
        "checks": [{"check": {"type": "contains", "value": "Paris"}, "passed": True}],
        "judge_score": 5, "judge_rationale": "Accurate and concise.",
    }
    cells = {"openai/gpt-5": cell_ok}

    if include_block:
        cells["anthropic/claude-opus-4.5"] = {
            "model_id": "anthropic/claude-opus-4.5", "blocked": True,
            "policy_clause": "No medical advice.", "policy_reason": "asks for diagnosis",
        }
    if include_error:
        cells["meta-llama/llama-4-maverick"] = {
            "model_id": "meta-llama/llama-4-maverick", "blocked": False,
            "error": "rate limited",
        }

    result_row = {"test_case": {"prompt": "What is the capital of France?"}, "cells": cells}
    if include_best_model:
        result_row["best_model"] = {"model_id": "openai/gpt-5", "reason": "Judge score 5/5 - Accurate and concise."}

    grade = {"score": 100.0, "letter": "A+", "sentence": "Strong performer (A+, 100.0/100)."}
    if include_categories:
        grade["categories"] = {
            "accuracy": 100.0, "rule_checks": 100.0, "cost_efficiency": 100.0, "speed": 100.0,
        }

    run_result = {
        "run_id": "test-run-1",
        "created_at": 1735689600.0,
        "results": [result_row],
        "grades": {"openai/gpt-5": grade},
        "verdict": {"winner": "openai/gpt-5", "rationale": "Most accurate and best formatted."},
    }
    if include_stats:
        run_result["stats"] = {"openai/gpt-5": {"total_cost_usd": 0.002, "avg_latency_ms": 120.0}}
    return run_result


def test_generates_valid_pdf_bytes_for_a_run():
    pdf_bytes = report.build_pdf(_sample_run_result())
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_report_includes_blocked_test_cases():
    pdf_bytes = report.build_pdf(_sample_run_result(include_block=True))
    assert pdf_bytes.startswith(b"%PDF")


def test_report_includes_error_cells():
    pdf_bytes = report.build_pdf(_sample_run_result(include_error=True))
    assert pdf_bytes.startswith(b"%PDF")


def test_report_reflects_overall_verdict_and_grades():
    run_result = {"results": [], "grades": {}, "verdict": {"winner": None, "rationale": "No data."}}
    pdf_bytes = report.build_pdf(run_result)
    assert pdf_bytes.startswith(b"%PDF")


def test_pdf_includes_stats_when_present():
    pdf_bytes = report.build_pdf(_sample_run_result(include_stats=True))
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_pdf_includes_category_breakdown_when_present():
    pdf_bytes = report.build_pdf(_sample_run_result(include_categories=True))
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_pdf_includes_best_model_recommendation_when_present():
    pdf_bytes = report.build_pdf(_sample_run_result(include_best_model=True))
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 100


def test_build_csv_returns_string_with_header_row():
    csv_text = report.build_csv(_sample_run_result())
    assert isinstance(csv_text, str)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    assert header == [
        "prompt", "model_id", "status", "response_text", "judge_score",
        "judge_rationale", "checks_passed", "checks_total", "cost_usd", "latency_ms", "tokens",
        "accuracy_score", "rule_checks_score", "cost_efficiency_score", "speed_score",
        "best_model_for_prompt", "best_model_reason",
    ]


def test_build_csv_includes_category_scores_when_present():
    csv_text = report.build_csv(_sample_run_result(include_categories=True))
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["accuracy_score"] == "100.0"
    assert row["cost_efficiency_score"] == "100.0"


def test_build_csv_includes_best_model_for_prompt_when_present():
    csv_text = report.build_csv(_sample_run_result(include_best_model=True))
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["best_model_for_prompt"] == "openai/gpt-5"
    assert "Judge score 5/5" in row["best_model_reason"]


def test_build_csv_has_one_data_row_per_cell():
    csv_text = report.build_csv(_sample_run_result(include_block=True, include_error=True))
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 4  # header + 3 cells (ok, blocked, error)


def test_build_csv_row_values_for_ok_cell():
    csv_text = report.build_csv(_sample_run_result())
    reader = csv.DictReader(io.StringIO(csv_text))
    row = next(reader)
    assert row["model_id"] == "openai/gpt-5"
    assert row["status"] == "ok"
    assert row["judge_score"] == "5"
    assert row["checks_passed"] == "1"
    assert row["checks_total"] == "1"


def test_build_csv_row_values_for_blocked_cell():
    csv_text = report.build_csv(_sample_run_result(include_block=True))
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    blocked_row = next(r for r in rows if r["model_id"] == "anthropic/claude-opus-4.5")
    assert blocked_row["status"] == "blocked"
    assert blocked_row["response_text"] == ""


def test_build_csv_handles_empty_results():
    csv_text = report.build_csv({"results": [], "grades": {}, "verdict": {"winner": None, "rationale": "No data."}})
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 1  # header only
