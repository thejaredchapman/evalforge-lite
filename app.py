import io
import logging
import os
import threading
import time
import uuid
from collections import deque

from flask import Flask, jsonify, render_template, request, send_file

import analysis
import availability
import catalog
import config
import costs
import gateway
import grading
import judge
import limiter
import policy
import report
import runner
import scrub
import server_creds

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


@app.route("/availability")
def availability_page():
    return render_template("availability.html")


@app.route("/api/catalog")
def api_catalog():
    cat = catalog.load_catalog()
    return jsonify({
        "providers": cat,
        "frontier": catalog.frontier_models(cat),
        "max_models": config.MAX_MODELS,
        "priority_weights": grading.PRIORITY_WEIGHTS,
        "priority_labels": grading.PRIORITY_LABELS,
        "regions": catalog.load_regions(),
        "tags": catalog.load_tags(),
        "provider_links": gateway.PROVIDER_LINKS,
        "server_backends": server_creds.public_summary(),
    })


@app.route("/api/suggest")
def api_suggest():
    model_id = request.args.get("model_id", "")
    cat = catalog.load_catalog()
    return jsonify({"suggestions": catalog.suggest_family(cat, model_id)})


@app.route("/api/openrouter-models")
def api_openrouter_models():
    return jsonify({"models": catalog.fetch_openrouter_models()})


@app.route("/api/availability")
def api_availability():
    return jsonify(availability.snapshot())


def _server_cap_refusal(session_id, held, targets, judge_backend):
    """429 response when this call needs a server-held backend and the shared daily cap is spent.

    Returns None when the call doesn't touch a server-held key or is still within the cap.
    """
    if not set(held) & gateway.backends_used(targets, judge_backend):
        return None
    result = limiter.check_and_record_server_key(time.time())
    if result["allowed"]:
        return None
    resp = jsonify({"error": "rate_limited", "reset_at": result["reset_at"], "message": limiter.SERVER_CAP_MESSAGE})
    resp.status_code = 429
    return _with_session_cookie(resp, session_id)


@app.route("/api/evaluate-prompt", methods=["POST"])
def api_evaluate_prompt():
    session_id = _get_session_id()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _with_session_cookie(_error_response("Request body must be JSON.", 400), session_id)
    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(body.get("creds"), body.get("api_key")))
    if not body.get("prompt") or raw_creds is None:
        return _with_session_cookie(
            _error_response("Missing required field: prompt and creds (or api_key).", 400), session_id
        )
    judge_backend = body.get("judge_backend", "openrouter")
    if judge_backend not in gateway.BACKENDS:
        return _with_session_cookie(_error_response("Invalid judge_backend.", 400), session_id)
    creds, creds_error = gateway.check_run_creds(raw_creds, [], judge_backend)
    if creds_error:
        return _with_session_cookie(_error_response(scrub.scrub(creds_error, raw_creds), 400), session_id)

    limit_result = limiter.check_and_record(f"evaluate:{session_id}", time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    refusal = _server_cap_refusal(session_id, held, [], judge_backend)
    if refusal:
        return refusal

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


def _validate_run_body(body):
    if not isinstance(body, dict):
        return "Request body must be JSON."
    if not isinstance(body.get("models"), list) or not all(isinstance(m, str) for m in body["models"]):
        return "Missing required field: models."
    if any(not m.strip() for m in body["models"]):
        return "Model ids must be non-empty strings."
    if body.get("judge_backend", "openrouter") not in gateway.BACKENDS:
        return "Invalid judge_backend."
    if not isinstance(body.get("test_cases"), list):
        return "Missing required field: test_cases."
    if len(body["models"]) > config.MAX_MODELS:
        return f"Pick at most {config.MAX_MODELS} models."
    repeats = body.get("repeats", 1)
    if type(repeats) is not int or repeats not in (1, 2, 3):
        return "repeats must be 1, 2, or 3."
    return None


@app.route("/api/run", methods=["POST"])
def api_run():
    session_id = _get_session_id()
    body = request.get_json(silent=True)

    error = _validate_run_body(body)
    if error:
        return _with_session_cookie(_error_response(error, 400), session_id)

    raw_creds, held = gateway.merge_server_creds(gateway.normalize_creds(body.get("creds"), body.get("api_key")))
    if raw_creds is None:
        return _with_session_cookie(_error_response("Missing required field: creds (or api_key).", 400), session_id)
    judge_backend = body.get("judge_backend", "openrouter")
    test_cases = body["test_cases"]
    model_ids = body["models"]
    repeats = body.get("repeats", 1)

    with _store_lock:
        policy_text = _policy_store.get(session_id)

    creds, creds_error = gateway.check_run_creds(raw_creds, model_ids, judge_backend)
    if creds_error:
        return _with_session_cookie(_error_response(scrub.scrub(creds_error, raw_creds), 400), session_id)

    limit_result = limiter.check_and_record(session_id, time.time())
    if not limit_result["allowed"]:
        resp = jsonify({"error": "rate_limited", "reset_at": limit_result["reset_at"]})
        resp.status_code = 429
        return _with_session_cookie(resp, session_id)

    refusal = _server_cap_refusal(session_id, held, model_ids, judge_backend)
    if refusal:
        return refusal

    try:
        meter = costs.CostMeter()
        results = runner.run(
            test_cases, model_ids, creds=creds, policy_text=policy_text, judge_backend=judge_backend,
            repeats=repeats, meter=meter,
        )
        run_result = analysis.build_run_result(results, model_ids, creds, judge_backend, meter=meter)
    except Exception as e:
        message = scrub.scrub(str(e), raw_creds)
        logger.error("run failed: %s", message)
        return _with_session_cookie(_error_response(message, 503), session_id)

    run_result = {"run_id": str(uuid.uuid4()), "created_at": time.time(), **run_result}

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
    priority = request.args.get("priority", "balanced")
    if priority not in grading.PRIORITY_WEIGHTS:
        return _with_session_cookie(_error_response("Invalid priority.", 400), session_id)

    run_result = _find_run(session_id, request.args.get("run_id"))
    if not run_result:
        return _with_session_cookie(_error_response("no_run_available", 404), session_id)

    pdf_bytes = report.build_pdf(run_result, priority=priority)
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
