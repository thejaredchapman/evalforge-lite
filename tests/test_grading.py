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
