import os
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


SERVER_KEY_WINDOW_SECONDS = 24 * 60 * 60
DEFAULT_SERVER_KEY_CAP = 50
SERVER_CAP_MESSAGE = "The server's shared usage limit has been reached. Please try again later."

_server_key_calls = []


def server_key_cap():
    """Max server-key calls per rolling 24h across all users (env SERVER_KEY_DAILY_CAP, default 50).

    Unparseable or negative values fall back to the default; 0 disables server-key use.
    """
    raw = os.environ.get("SERVER_KEY_DAILY_CAP")
    if raw is None:
        return DEFAULT_SERVER_KEY_CAP
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SERVER_KEY_CAP
    return value if value >= 0 else DEFAULT_SERVER_KEY_CAP


def check_and_record_server_key(now):
    """Count one server-key call against the shared rolling-24h cap (process-local)."""
    cap = server_key_cap()
    with _lock:
        _server_key_calls[:] = [t for t in _server_key_calls if now - t < SERVER_KEY_WINDOW_SECONDS]
        if len(_server_key_calls) >= cap:
            reset_at = _server_key_calls[0] + SERVER_KEY_WINDOW_SECONDS if _server_key_calls else None
            return {"allowed": False, "reset_at": reset_at}
        _server_key_calls.append(now)
        return {"allowed": True, "reset_at": None}
