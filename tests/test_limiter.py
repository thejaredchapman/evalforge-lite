import limiter


def setup_function():
    limiter._attempts.clear()


def test_allows_up_to_three_runs_in_window():
    now = 1_000_000.0
    for _ in range(3):
        result = limiter.check_and_record("session-a", now)
        assert result["allowed"] is True


def test_blocks_fourth_run_within_8h():
    now = 1_000_000.0
    for _ in range(3):
        limiter.check_and_record("session-a", now)

    result = limiter.check_and_record("session-a", now + 60)

    assert result["allowed"] is False
    assert result["reset_at"] is not None


def test_allows_run_after_oldest_timestamp_expires():
    now = 1_000_000.0
    for _ in range(3):
        limiter.check_and_record("session-a", now)

    later = now + limiter.WINDOW_SECONDS + 1
    result = limiter.check_and_record("session-a", later)

    assert result["allowed"] is True


def test_separate_sessions_have_independent_limits():
    now = 1_000_000.0
    for _ in range(3):
        limiter.check_and_record("session-a", now)

    result = limiter.check_and_record("session-b", now)

    assert result["allowed"] is True


def test_429_reset_time_is_oldest_timestamp_plus_window():
    now = 1_000_000.0
    limiter.check_and_record("session-a", now)
    limiter.check_and_record("session-a", now + 10)
    limiter.check_and_record("session-a", now + 20)

    result = limiter.check_and_record("session-a", now + 30)

    assert result["reset_at"] == now + limiter.WINDOW_SECONDS


def test_server_key_cap_defaults_to_50(monkeypatch):
    assert limiter.server_key_cap() == 50


def test_server_key_cap_reads_env_and_falls_back_on_bad_values(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "7")
    assert limiter.server_key_cap() == 7
    for bad in ("abc", "", "-3", "2.5"):
        monkeypatch.setenv("SERVER_KEY_DAILY_CAP", bad)
        assert limiter.server_key_cap() == 50
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "0")
    assert limiter.server_key_cap() == 0


def test_server_key_cap_allows_up_to_cap_then_refuses(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "2")
    now = 1_000_000.0
    assert limiter.check_and_record_server_key(now)["allowed"] is True
    assert limiter.check_and_record_server_key(now + 1)["allowed"] is True
    refused = limiter.check_and_record_server_key(now + 2)
    assert refused["allowed"] is False
    assert refused["reset_at"] == now + limiter.SERVER_KEY_WINDOW_SECONDS


def test_server_key_cap_window_rolls_off(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "1")
    now = 1_000_000.0
    assert limiter.check_and_record_server_key(now)["allowed"] is True
    assert limiter.check_and_record_server_key(now + 60)["allowed"] is False
    after = now + limiter.SERVER_KEY_WINDOW_SECONDS + 1
    assert limiter.check_and_record_server_key(after)["allowed"] is True


def test_server_key_cap_zero_refuses_everything(monkeypatch):
    monkeypatch.setenv("SERVER_KEY_DAILY_CAP", "0")
    result = limiter.check_and_record_server_key(1_000_000.0)
    assert result == {"allowed": False, "reset_at": None}
