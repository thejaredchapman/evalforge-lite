import pytest

import checks


def test_contains_pass():
    assert checks.run_check({"type": "contains", "value": "Paris"}, "The capital is Paris.") is True


def test_contains_fail():
    assert checks.run_check({"type": "contains", "value": "Paris"}, "The capital is London.") is False


def test_regex_pass():
    assert checks.run_check({"type": "regex", "value": r"\d{3}-\d{4}"}, "Call 555-1234 now") is True


def test_regex_fail():
    assert checks.run_check({"type": "regex", "value": r"\d{3}-\d{4}"}, "no phone number here") is False


def test_json_valid_pass():
    assert checks.run_check({"type": "json_valid"}, '{"a": 1}') is True


def test_json_valid_fail_on_malformed():
    assert checks.run_check({"type": "json_valid"}, "{a: 1,}") is False


def test_max_length_pass():
    assert checks.run_check({"type": "max_length", "value": 20}, "short response") is True


def test_max_length_fail():
    assert checks.run_check({"type": "max_length", "value": 5}, "this is too long") is False


def test_unknown_check_type_raises():
    with pytest.raises(ValueError):
        checks.run_check({"type": "nonsense"}, "irrelevant")


def test_run_checks_returns_check_and_passed_for_each():
    results = checks.run_checks(
        [{"type": "contains", "value": "Paris"}, {"type": "max_length", "value": 5}],
        "Paris is nice",
    )
    assert results == [
        {"check": {"type": "contains", "value": "Paris"}, "passed": True},
        {"check": {"type": "max_length", "value": 5}, "passed": False},
    ]
