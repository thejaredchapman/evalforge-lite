import pytest

import grading


def test_score_normalizes_judge_score_to_100():
    # avg judge score 5/5 -> 100
    assert grading.compute_score([5, 5, 5], []) == 100.0
    # avg judge score 3/5 -> 60
    assert grading.compute_score([3, 3, 3], []) == 60.0


def test_score_blends_judge_and_rule_check_pass_rate():
    # judge avg 4/5 -> 80; rule checks 1/2 passed -> 50
    # blend: 80*0.7 + 50*0.3 = 56 + 15 = 71.0
    score = grading.compute_score([4, 4], [True, False])
    assert score == 71.0


def test_score_falls_back_to_rule_checks_when_no_rubric():
    score = grading.compute_score([], [True, True, False])
    assert score == pytest.approx(66.7, abs=0.1)


def test_score_is_none_with_no_data():
    assert grading.compute_score([], []) is None


@pytest.mark.parametrize("score,expected_letter", [
    (100, "A+"), (97, "A+"), (96, "A"), (93, "A"), (92, "A-"), (90, "A-"),
    (89, "B+"), (87, "B+"), (86, "B"), (83, "B"), (82, "B-"), (80, "B-"),
    (79, "C+"), (77, "C+"), (76, "C"), (73, "C"), (72, "C-"), (70, "C-"),
    (69, "D"), (60, "D"), (59, "F"), (0, "F"),
])
def test_letter_grade_boundaries(score, expected_letter):
    assert grading.letter_grade(score) == expected_letter


def test_summary_sentence_reflects_score_tier():
    sentence = grading.summary_sentence(95.0, "A", [True, True], [])
    assert "Strong performer" in sentence
    assert "A" in sentence
    assert "95" in sentence


def test_summary_sentence_mentions_common_failure_pattern():
    sentence = grading.summary_sentence(65.0, "D", [True, False, False], [])
    assert "Failed 2 of 3 rule checks" in sentence


def test_summary_sentence_with_no_data():
    sentence = grading.summary_sentence(None, None, [], [])
    assert "No scoring data" in sentence


def test_grade_model_combines_everything():
    result = grading.grade_model([5, 5], [True, True], ["Great answer."])
    assert result["score"] == 100.0
    assert result["letter"] == "A+"
    assert "Strong performer" in result["sentence"]


def test_grade_model_with_no_data_returns_none_score_and_letter():
    result = grading.grade_model([], [], [])
    assert result["score"] is None
    assert result["letter"] is None
    assert "No scoring data" in result["sentence"]


def test_category_scores_computes_accuracy_and_rule_checks():
    categories = grading.category_scores(
        judge_scores=[4, 4], rule_check_results=[True, False],
        cost_usd=0.01, all_costs=[0.01, 0.02], latency_ms=100, all_latencies=[100, 200],
    )
    assert categories["accuracy"] == 80.0
    assert categories["rule_checks"] == 50.0


def test_category_scores_cost_and_speed_are_relative_to_the_run():
    # cheapest/fastest in the run should score 100
    categories = grading.category_scores(
        judge_scores=[], rule_check_results=[],
        cost_usd=0.01, all_costs=[0.01, 0.05], latency_ms=100, all_latencies=[100, 500],
    )
    assert categories["cost_efficiency"] == 100.0
    assert categories["speed"] == 100.0

    # the pricier/slower one should score lower
    categories2 = grading.category_scores(
        judge_scores=[], rule_check_results=[],
        cost_usd=0.05, all_costs=[0.01, 0.05], latency_ms=500, all_latencies=[100, 500],
    )
    assert categories2["cost_efficiency"] == 0.0
    assert categories2["speed"] == 0.0


def test_category_scores_all_equal_costs_score_100():
    categories = grading.category_scores(
        judge_scores=[], rule_check_results=[],
        cost_usd=0.02, all_costs=[0.02, 0.02], latency_ms=150, all_latencies=[150, 150],
    )
    assert categories["cost_efficiency"] == 100.0
    assert categories["speed"] == 100.0


def test_category_scores_missing_data_is_none():
    categories = grading.category_scores(
        judge_scores=[], rule_check_results=[],
        cost_usd=None, all_costs=[], latency_ms=None, all_latencies=[],
    )
    assert categories == {
        "accuracy": None, "rule_checks": None, "cost_efficiency": None, "speed": None,
    }


def _cell(model_id, judge_score=None, judge_rationale=None, checks=None, latency_ms=10):
    return {
        "model_id": model_id, "blocked": False, "error": None,
        "response_text": "x", "latency_ms": latency_ms, "cost_usd": 0.001, "tokens": 5,
        "checks": checks or [], "judge_score": judge_score, "judge_rationale": judge_rationale,
    }


def test_best_model_for_test_case_picks_highest_judge_score():
    cells = {
        "model-a": _cell("model-a", judge_score=3, judge_rationale="Okay."),
        "model-b": _cell("model-b", judge_score=5, judge_rationale="Excellent and precise."),
    }
    result = grading.best_model_for_test_case(cells)
    assert result["model_id"] == "model-b"
    assert "5/5" in result["reason"]
    assert "Excellent and precise." in result["reason"]


def test_best_model_for_test_case_falls_back_to_rule_checks():
    cells = {
        "model-a": _cell("model-a", checks=[{"check": {}, "passed": True}, {"check": {}, "passed": False}]),
        "model-b": _cell("model-b", checks=[{"check": {}, "passed": True}, {"check": {}, "passed": True}]),
    }
    result = grading.best_model_for_test_case(cells)
    assert result["model_id"] == "model-b"
    assert "2/2" in result["reason"]


def test_best_model_for_test_case_falls_back_to_fastest_when_no_signal():
    cells = {
        "model-a": _cell("model-a", latency_ms=500),
        "model-b": _cell("model-b", latency_ms=50),
    }
    result = grading.best_model_for_test_case(cells)
    assert result["model_id"] == "model-b"
    assert "fastest" in result["reason"].lower()


def test_best_model_for_test_case_ignores_blocked_and_errored_cells():
    cells = {
        "model-a": {"model_id": "model-a", "blocked": True},
        "model-b": _cell("model-b", judge_score=4, judge_rationale="Good."),
    }
    result = grading.best_model_for_test_case(cells)
    assert result["model_id"] == "model-b"


def test_best_model_for_test_case_with_no_successful_cells_returns_none():
    cells = {"model-a": {"model_id": "model-a", "blocked": True}}
    result = grading.best_model_for_test_case(cells)
    assert result["model_id"] is None
