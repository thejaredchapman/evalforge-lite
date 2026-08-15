import threading

WINDOW_SECONDS = 8 * 60 * 60
MAX_RUNS = 3

_lock = threading.Lock()
_attempts = {}


def _prune(timestamps, now):
    return [t for t in timestamps if now - t < WINDOW_SECONDS]


def check_and_record(session_id, now):
    with _lock:
        timestamps = _prune(_attempts.get(session_id, []), now)

        if len(timestamps) >= MAX_RUNS:
            _attempts[session_id] = timestamps
            return {"allowed": False, "reset_at": timestamps[0] + WINDOW_SECONDS}

        timestamps.append(now)
        _attempts[session_id] = timestamps
        return {"allowed": True, "reset_at": None}
