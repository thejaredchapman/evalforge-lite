from unittest.mock import patch

import pytest

import availability
import catalog


def setup_function():
    availability._cache["snapshot"] = None
    availability._cache["fetched_at"] = 0.0
    catalog._cache["data"] = None
    catalog._cache["fetched_at"] = 0.0


@pytest.fixture(autouse=True)
def _no_real_http(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("tests/test_availability.py attempted a real HTTP call")
    monkeypatch.setattr("catalog.requests.get", _blocked)


@patch("availability.catalog.fetch_openrouter_models")
def test_first_call_fetches_openrouter_models(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5", "name": "GPT-5"}]
    snap = availability.snapshot(now=1000.0)
    mock_fetch.assert_called_once()
    assert snap["openrouter"]["stale"] is False
    assert snap["openrouter"]["models"]["openai/gpt-5"]["listed"] is True
    assert snap["openrouter"]["models"]["openai/gpt-4o"]["listed"] is False


@patch("availability.catalog.fetch_openrouter_models")
def test_second_call_within_six_hours_does_not_refetch(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    availability.snapshot(now=1000.0)
    availability.snapshot(now=1000.0 + 3600)
    mock_fetch.assert_called_once()


@patch("availability.catalog.fetch_openrouter_models")
def test_call_after_six_hours_refetches(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    availability.snapshot(now=1000.0)
    availability.snapshot(now=1000.0 + availability._TTL_SECONDS + 1)
    assert mock_fetch.call_count == 2


@patch("availability.catalog.fetch_openrouter_models")
def test_failed_refresh_keeps_old_data_and_marks_stale(mock_fetch):
    mock_fetch.return_value = [{"id": "openai/gpt-5"}]
    first = availability.snapshot(now=1000.0)
    mock_fetch.return_value = []  # fetch_openrouter_models fails soft to [] on any request error
    second = availability.snapshot(now=1000.0 + availability._TTL_SECONDS + 1)
    assert second["openrouter"]["stale"] is True
    assert second["openrouter"]["models"] == first["openrouter"]["models"]


@patch("availability.catalog.fetch_openrouter_models", return_value=[])
def test_no_prior_data_and_failed_fetch_marks_everything_unlisted_and_stale(mock_fetch):
    snap = availability.snapshot(now=1000.0)
    assert snap["openrouter"]["stale"] is True
    assert all(not v["listed"] for v in snap["openrouter"]["models"].values())


@patch("availability.catalog.fetch_openrouter_models", return_value=[])
def test_backend_sections_have_curated_metadata_and_model_regions(mock_fetch):
    snap = availability.snapshot(now=1000.0)
    assert set(snap["backends"]) == {"bedrock", "vertex", "foundry"}
    bedrock_section = snap["backends"]["bedrock"]
    assert bedrock_section["label"] == "Amazon Bedrock"
    assert "us-east-1" in bedrock_section["models"]["anthropic/claude-sonnet-4.5"]
    vertex_section = snap["backends"]["vertex"]
    assert "google/gemini-2.5-pro" in vertex_section["models"]
    foundry_section = snap["backends"]["foundry"]
    assert "openai/gpt-5" in foundry_section["models"]


@patch("availability.catalog.fetch_openrouter_models", return_value=[])
def test_snapshot_includes_generated_at(mock_fetch):
    snap = availability.snapshot(now=1234.5)
    assert snap["generated_at"] == 1234.5
