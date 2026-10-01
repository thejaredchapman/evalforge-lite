import threading

_VALID_KINDS = ("model", "judge")


class CostMeter:
    """Thread-safe accumulator for one run's model-call and judge-call USD costs.

    One instance is created per run (in app.py / mcp_server.py) and threaded through
    runner.run()/analysis.build_run_result() so every worker thread in the run's
    ThreadPoolExecutor can add to it safely.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model_usd = 0.0
        self._judge_usd = 0.0
        self._judge_calls = 0

    def add(self, kind, usd):
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unknown cost kind: {kind!r}")
        usd = float(usd or 0.0)
        with self._lock:
            if kind == "judge":
                self._judge_usd += usd
                self._judge_calls += 1
            else:
                self._model_usd += usd

    def totals(self):
        with self._lock:
            model_usd = round(self._model_usd, 8)
            judge_usd = round(self._judge_usd, 8)
            return {
                "model_usd": model_usd,
                "judge_usd": judge_usd,
                "total_usd": round(model_usd + judge_usd, 8),
                "judge_calls": self._judge_calls,
            }
