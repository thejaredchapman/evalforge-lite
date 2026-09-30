import json
import re

import bedrock
import catalog
import openrouter
import vertex
from errors import GatewayError

BACKENDS = ("openrouter", "bedrock", "vertex")
BACKEND_LABELS = {"openrouter": "OpenRouter", "bedrock": "Bedrock", "vertex": "Vertex AI"}

_BEDROCK_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d$")
_VERTEX_REGION_RE = re.compile(r"^(global|[a-z]+-[a-z]+\d+)$")
_VERTEX_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def _known_region_ids(backend):
    return {r["id"] for r in catalog.load_regions()[backend]["regions"]}


def parse_target(target):
    if not isinstance(target, str) or not target:
        raise GatewayError("Model target must be a non-empty string.")
    model_id, sep, backend = target.rpartition("@")
    if sep and model_id and backend in BACKENDS:
        return model_id, backend
    return target, "openrouter"


def _nonempty_str(value):
    return isinstance(value, str) and bool(value)


def _clean_secret(value):
    if not _nonempty_str(value):
        return False
    if value != value.strip():
        return False
    return all(ord(c) >= 32 and ord(c) != 127 for c in value)


def _check_clean_fields(raw, fields, error_message):
    for field in fields:
        value = raw.get(field)
        if _nonempty_str(value) and not _clean_secret(value):
            raise GatewayError(error_message)


def _prepare_bedrock(raw):
    if not isinstance(raw, dict):
        raise GatewayError("Bedrock credentials must be an object.")
    region = raw.get("region")
    if not _nonempty_str(region) or not _BEDROCK_REGION_RE.match(region) or region not in _known_region_ids("bedrock"):
        raise GatewayError("Bedrock region is missing or invalid.")
    _check_clean_fields(
        raw, ("api_key", "access_key_id", "secret_access_key", "session_token"),
        "Bedrock credentials contain whitespace or control characters.",
    )
    if _nonempty_str(raw.get("api_key")):
        return {"region": region, "api_key": raw["api_key"]}
    if _nonempty_str(raw.get("access_key_id")) and _nonempty_str(raw.get("secret_access_key")):
        prepared = {
            "region": region,
            "access_key_id": raw["access_key_id"],
            "secret_access_key": raw["secret_access_key"],
        }
        if _nonempty_str(raw.get("session_token")):
            prepared["session_token"] = raw["session_token"]
        return prepared
    raise GatewayError("Bedrock credentials need an api_key, or access_key_id and secret_access_key.")


def _prepare_vertex(raw):
    if not isinstance(raw, dict):
        raise GatewayError("Vertex credentials must be an object.")
    project = raw.get("project")
    region = raw.get("region")
    if not _nonempty_str(project) or not _VERTEX_PROJECT_RE.match(project):
        raise GatewayError("Vertex project is missing or invalid.")
    if not _nonempty_str(region) or not _VERTEX_REGION_RE.match(region) or region not in _known_region_ids("vertex"):
        raise GatewayError("Vertex region is missing or invalid.")
    _check_clean_fields(
        raw, ("access_token",), "Vertex credentials contain whitespace or control characters.",
    )
    if _nonempty_str(raw.get("access_token")):
        return {"project": project, "region": region, "access_token": raw["access_token"]}
    if _nonempty_str(raw.get("service_account_json")):
        try:
            info = json.loads(raw["service_account_json"])
        except ValueError as e:
            raise GatewayError("service_account_json is not valid JSON.") from e
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise GatewayError("service_account_json is not a service-account key.")
        token = vertex.mint_token(info)
        return {"project": project, "region": region, "access_token": token}
    raise GatewayError("Vertex credentials need an access_token or service_account_json.")


def prepare_creds(creds):
    """Validate creds once per run and mint any tokens. Idempotent on its own output."""
    creds = creds if isinstance(creds, dict) else {}
    prepared = {}
    if isinstance(creds.get("openrouter"), dict) and "error" in creds["openrouter"]:
        prepared["openrouter"] = creds["openrouter"]
    elif _nonempty_str(creds.get("openrouter")):
        if _clean_secret(creds["openrouter"]):
            prepared["openrouter"] = creds["openrouter"]
        else:
            prepared["openrouter"] = {"error": "OpenRouter credentials contain whitespace or control characters."}
    for backend, prepare in (("bedrock", _prepare_bedrock), ("vertex", _prepare_vertex)):
        raw = creds.get(backend)
        if raw is None:
            continue
        if isinstance(raw, dict) and "error" in raw:
            prepared[backend] = raw
            continue
        try:
            prepared[backend] = prepare(raw)
        except GatewayError as e:
            prepared[backend] = {"error": str(e)}
    return prepared


def normalize_creds(creds=None, api_key=None):
    if isinstance(creds, dict) and creds:
        if "openrouter" not in creds and _nonempty_str(api_key):
            return {**creds, "openrouter": api_key}
        return creds
    if _nonempty_str(api_key):
        return {"openrouter": api_key}
    return None


def check_run_creds(raw_creds, targets, judge_backend):
    """Up-front check before a rate-limited call: returns (prepared_creds, error_message_or_None).

    The judge backend always needs creds (it runs the verdict, rubric judging, and policy gate).
    Prepare errors are reported only for backends this call actually uses.
    """
    if not raw_creds.get(judge_backend):
        return None, f"{BACKEND_LABELS[judge_backend]} credentials are required for the judge backend."
    prepared = prepare_creds(raw_creds)
    needed = {judge_backend}
    for target in targets:
        try:
            needed.add(parse_target(target)[1])
        except GatewayError:
            continue
    errors = [
        prepared[backend]["error"]
        for backend in BACKENDS
        if backend in needed and isinstance(prepared.get(backend), dict) and "error" in prepared[backend]
    ]
    return prepared, " ".join(errors) or None


def _creds_for(backend, creds):
    backend_creds = (creds or {}).get(backend)
    if not backend_creds:
        raise GatewayError(f"No {BACKEND_LABELS[backend]} credentials supplied.")
    if isinstance(backend_creds, dict) and "error" in backend_creds:
        raise GatewayError(backend_creds["error"])
    return backend_creds


def call_backend(backend, native_model_id, messages, creds, timeout=60):
    if backend not in BACKENDS:
        raise GatewayError(f"Unknown backend: {backend}")
    backend_creds = _creds_for(backend, prepare_creds(creds))
    if backend == "openrouter":
        return openrouter.call_model(native_model_id, messages, api_key=backend_creds, timeout=timeout)
    if backend == "bedrock":
        return bedrock.call_model(native_model_id, messages, backend_creds, timeout=timeout)
    return vertex.call_model(native_model_id, messages, backend_creds, timeout=timeout)


def estimate_cost(price, input_tokens, output_tokens):
    if not price:
        return 0.0
    return round(
        input_tokens / 1e6 * price["input_per_m"] + output_tokens / 1e6 * price["output_per_m"],
        8,
    )


def call_target(target, messages, creds, timeout=60):
    model_id, backend = parse_target(target)
    if backend == "openrouter":
        return call_backend("openrouter", model_id, messages, creds, timeout=timeout)

    route = catalog.route_for(catalog.load_catalog(), model_id, backend)
    if route is None:
        raise GatewayError(f"{model_id} is not available on {BACKEND_LABELS[backend]}.")
    result = call_backend(backend, route["id"], messages, creds, timeout=timeout)
    result["cost_usd"] = estimate_cost(
        route.get("price"), result.get("input_tokens", 0), result.get("output_tokens", 0)
    )
    return result
