import io
import logging
import os
import re
import threading
import time
import uuid
from collections import deque

from flask import Flask, jsonify, render_template, request, send_file

import catalog
import grading
import judge
import limiter
import policy
import report
import runner

app = Flask(__name__)
logger = logging.getLogger(__name__)

_SECRET_RE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b")

_policy_store = {}
_run_history_store = {}
_store_lock = threading.Lock()


def _scrub(message):
    return _SECRET_RE.sub("[REDACTED]", message)


def _error_response(message, status_code):
    resp = jsonify({"error": message})
    resp.status_code = status_code
    return resp


def _get_session_id():
    return request.cookies.get("evalforge_session") or str(uuid.uuid4())


def _with_session_cookie(resp, session_id):
    resp.set_cookie("evalforge_session", session_id, httponly=True, samesite="Lax")
    return resp


@app.route("/")
def index():
    session_id = _get_session_id()
    resp = app.make_response(render_template("index.html"))
    return _with_session_cookie(resp, session_id)


@app.route("/api/catalog")
def api_catalog():
    cat = catalog.load_catalog()
    return jsonify({"providers": cat, "frontier": catalog.frontier_models(cat)})


@app.route("/api/suggest")
def api_suggest():
    model_id = request.args.get("model_id", "")
    cat = catalog.load_catalog()
    return jsonify({"suggestions": catalog.suggest_family(cat, model_id)})


@app.route("/api/openrouter-models")
def api_openrouter_models():
    return jsonify({"models": catalog.fetch_openrouter_models()})


@app.route("/api/policy", methods=["POST"])
def api_policy():
    session_id = _get_session_id()
    uploaded = request.files["file"]
    text = policy.extract_text(uploaded.filename, uploaded.read())
    with _store_lock:
        _policy_store[session_id] = text
    return _with_session_cookie(jsonify({"ok": True}), session_id)


def _aggregate_stats(results, model_ids):
    stats = {
        m: {
            "judge_scores": [], "rule_check_results": [], "judge_rationales": [],
            "costs": [], "latencies": [],
        }
        for m in model_ids
    }
    for row in results:
        for model_id, cell in row["cells"].items():
            if cell.get("blocked") or cell.get("error"):
                continue
            if cell.get("judge_score") is not None:
                stats[model_id]["judge_scores"].append(cell["judge_score"])
            if cell.get("judge_rationale"):
                stats[model_id]["judge_rationales"].append(cell["judge_rationale"])
            for check_result in cell.get("checks") or []:
                stats[model_id]["rule_check_results"].append(check_result["passed"])
            stats[model_id]["costs"].append(cell.get("cost_usd", 0.0))
            stats[model_id]["latencies"].append(cell.get("latency_ms", 0))
    return stats


def _cost_latency_stats(agg_stats):
    result = {}
    for model_id, s in agg_stats.items():
        total_cost = sum(s["costs"])
        avg_latency = sum(s["latencies"]) / len(s["latencies"]) if s["latencies"] else 0.0
        result[model_id] = {
            "total_cost_usd": round(total_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
        }
    return result


def _validate_run_body(body):
    if not isinstance(body, dict):
        return "Request body must be JSON."
    if not body.get("api_key") or not isinstance(body["api_key"], str):
        return "Missing required field: api_key."
    if not isinstance(body.get("test_cases"), list):
        return "Missing required field: test_cases."
    if not isinstance(body.get("models"), list):
        return "Missing required field: models."
    return None


@app.route("/api/run", methods=["POST"])
def api_run():
    session_id = _get_session_id()
    body = request.get_json(silent=True)

    error = _validate_run_body(body)
    if error:
        return _with_session_cookie(_error_response(error, 400), session_id)

    api_key = body["api_key"]
    test_cases = body["test_cases"]
    model_ids = body["models"]

    limit_result = limiter.check_and_record(session_id, time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    with _store_lock:
        policy_text = _policy_store.get(session_id)

    try:
        results = runner.run(test_cases, model_ids, api_key=api_key, policy_text=policy_text)

        agg_stats = _aggregate_stats(results, model_ids)
        grades = {
            model_id: grading.grade_model(
                s["judge_scores"], s["rule_check_results"], s["judge_rationales"]
            )
            for model_id, s in agg_stats.items()
        }
        stats = _cost_latency_stats(agg_stats)

        verdict = {"winner": None, "rationale": "No models were run."}
        if model_ids:
            verdict = judge.overall_verdict(
                {m: {"score": grades[m]["score"], "letter": grades[m]["letter"]} for m in model_ids},
                api_key=api_key,
            )
    except Exception as e:
        logger.exception("run failed")
        return _with_session_cookie(_error_response(_scrub(str(e)), 503), session_id)

    run_result = {
        "run_id": str(uuid.uuid4()),
        "created_at": time.time(),
        "results": results,
        "grades": grades,
        "stats": stats,
        "verdict": verdict,
    }

    with _store_lock:
        history = _run_history_store.setdefault(session_id, deque(maxlen=5))
        history.append(run_result)

    return _with_session_cookie(jsonify(run_result), session_id)


@app.route("/api/runs")
def api_runs():
    session_id = _get_session_id()
    with _store_lock:
        history = list(_run_history_store.get(session_id, []))
    runs = [
        {"run_id": r["run_id"], "created_at": r["created_at"], "winner": r["verdict"].get("winner")}
        for r in reversed(history)
    ]
    return _with_session_cookie(jsonify({"runs": runs}), session_id)


def _find_run(session_id, run_id):
    with _store_lock:
        history = list(_run_history_store.get(session_id, []))
    if not history:
        return None
    if run_id is None:
        return history[-1]
    return next((r for r in history if r["run_id"] == run_id), None)


@app.route("/api/report")
def api_report():
    session_id = _get_session_id()
    run_result = _find_run(session_id, request.args.get("run_id"))
    if not run_result:
        return _with_session_cookie(_error_response("no_run_available", 404), session_id)

    pdf_bytes = report.build_pdf(run_result)
    resp = send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="evalforge-report.pdf",
    )
    return _with_session_cookie(resp, session_id)


@app.route("/api/report.csv")
def api_report_csv():
    session_id = _get_session_id()
    run_result = _find_run(session_id, request.args.get("run_id"))
    if not run_result:
        return _with_session_cookie(_error_response("no_run_available", 404), session_id)

    csv_text = report.build_csv(run_result)
    resp = app.make_response(csv_text)
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = "attachment; filename=evalforge-report.csv"
    return _with_session_cookie(resp, session_id)


def main():
    debug = os.environ.get("FLASK_DEBUG") == "1"
    port = int(os.environ.get("PORT", 8000))
    app.run(port=port, debug=debug)


if __name__ == "__main__":
    main()
