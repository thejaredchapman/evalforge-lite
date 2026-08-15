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
