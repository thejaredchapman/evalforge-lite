import threading

import pytest

import costs


def test_add_and_totals_tracks_model_and_judge_separately():
    meter = costs.CostMeter()
    meter.add("model", 0.01)
    meter.add("model", 0.02)
    meter.add("judge", 0.001)
    assert meter.totals() == {"model_usd": 0.03, "judge_usd": 0.001, "total_usd": 0.031, "judge_calls": 1}


def test_totals_with_no_adds_is_all_zero():
    meter = costs.CostMeter()
    assert meter.totals() == {"model_usd": 0.0, "judge_usd": 0.0, "total_usd": 0.0, "judge_calls": 0}


def test_each_judge_add_increments_judge_calls():
    meter = costs.CostMeter()
    meter.add("judge", 0.0)
    meter.add("judge", 0.0)
    assert meter.totals()["judge_calls"] == 2


def test_add_rejects_unknown_kind():
    meter = costs.CostMeter()
    with pytest.raises(ValueError):
        meter.add("something-else", 0.01)


def test_add_treats_none_cost_as_zero():
    meter = costs.CostMeter()
    meter.add("model", None)
    assert meter.totals()["model_usd"] == 0.0


def test_concurrent_adds_are_thread_safe():
    meter = costs.CostMeter()
    threads = [
        threading.Thread(target=lambda: [meter.add("model", 0.0001) for _ in range(200)])
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert meter.totals()["model_usd"] == pytest.approx(0.2)
