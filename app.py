import io
import logging
import os
import threading
import time
import uuid
from collections import deque

from flask import Flask, jsonify, render_template, request, send_file

import catalog
import gateway
import grading
import judge
import limiter
import policy
import report
import runner
import scrub

app = Flask(__name__)
logger = logging.getLogger(__name__)

_policy_store = {}
_run_history_store = {}
_store_lock = threading.Lock()


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


@app.route("/api/evaluate-prompt", methods=["POST"])
def api_evaluate_prompt():
    session_id = _get_session_id()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _with_session_cookie(_error_response("Request body must be JSON.", 400), session_id)
    raw_creds = gateway.normalize_creds(body.get("creds"), body.get("api_key"))
    if not body.get("prompt") or raw_creds is None:
        return _with_session_cookie(
            _error_response("Missing required field: prompt and creds (or api_key).", 400), session_id
        )
    judge_backend = body.get("judge_backend", "openrouter")
    if judge_backend not in gateway.BACKENDS:
        return _with_session_cookie(_error_response("Invalid judge_backend.", 400), session_id)
    creds, creds_error = gateway.check_run_creds(raw_creds, [], judge_backend)
    if creds_error:
        return _with_session_cookie(_error_response(creds_error, 400), session_id)

    limit_result = limiter.check_and_record(f"evaluate:{session_id}", time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    result = judge.evaluate_prompt(body["prompt"], creds=creds, backend=judge_backend)
    return _with_session_cookie(jsonify(result), session_id)


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


def _category_scores_by_model(agg_stats, stats):
    all_costs = [stats[m]["total_cost_usd"] for m, s in agg_stats.items() if s["costs"]]
    all_latencies = [stats[m]["avg_latency_ms"] for m, s in agg_stats.items() if s["latencies"]]

    result = {}
    for model_id, s in agg_stats.items():
        cost = stats[model_id]["total_cost_usd"] if s["costs"] else None
        latency = stats[model_id]["avg_latency_ms"] if s["latencies"] else None
        result[model_id] = grading.category_scores(
            s["judge_scores"], s["rule_check_results"], cost, all_costs, latency, all_latencies
        )
    return result


def _validate_run_body(body):
    if not isinstance(body, dict):
        return "Request body must be JSON."
    if gateway.normalize_creds(body.get("creds"), body.get("api_key")) is None:
        return "Missing required field: creds (or api_key)."
    if body.get("judge_backend", "openrouter") not in gateway.BACKENDS:
        return "Invalid judge_backend."
    if not isinstance(body.get("test_cases"), list):
        return "Missing required field: test_cases."
    if not isinstance(body.get("models"), list) or not all(isinstance(m, str) for m in body["models"]):
        return "Missing required field: models."
    return None


@app.route("/api/run", methods=["POST"])
def api_run():
    session_id = _get_session_id()
    body = request.get_json(silent=True)

    error = _validate_run_body(body)
    if error:
        return _with_session_cookie(_error_response(error, 400), session_id)

    raw_creds = gateway.normalize_creds(body.get("creds"), body.get("api_key"))
    judge_backend = body.get("judge_backend", "openrouter")
    test_cases = body["test_cases"]
    model_ids = body["models"]

    with _store_lock:
        policy_text = _policy_store.get(session_id)

    creds, creds_error = gateway.check_run_creds(raw_creds, model_ids, judge_backend)
    if creds_error:
        return _with_session_cookie(_error_response(creds_error, 400), session_id)

    limit_result = limiter.check_and_record(session_id, time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    try:
        results = runner.run(
            test_cases, model_ids, creds=creds, policy_text=policy_text, judge_backend=judge_backend
        )

        for row in results:
            row["best_model"] = grading.best_model_for_test_case(row["cells"])

        agg_stats = _aggregate_stats(results, model_ids)
        grades = {
            model_id: grading.grade_model(
                s["judge_scores"], s["rule_check_results"], s["judge_rationales"]
            )
            for model_id, s in agg_stats.items()
        }
        stats = _cost_latency_stats(agg_stats)
        categories = _category_scores_by_model(agg_stats, stats)
        for model_id in grades:
            grades[model_id]["categories"] = categories[model_id]

        verdict = {"winner": None, "rationale": "No models were run."}
        if model_ids:
            verdict = judge.overall_verdict(
                {m: {"score": grades[m]["score"], "letter": grades[m]["letter"]} for m in model_ids},
                creds=creds,
                backend=judge_backend,
            )
    except Exception as e:
        message = scrub.scrub(str(e), raw_creds)
        logger.error("run failed: %s", message)
        return _with_session_cookie(_error_response(message, 503), session_id)

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
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
