"""Optional operator-held provider credentials, read from environment variables.

Opt-in: with none of these set, nothing is held server-side and users supply their
own credentials per request. Each loader returns a value shaped exactly like the
browser's creds for that backend, or None when the backend isn't fully configured.
Env is read at call time (not import time) so tests and restarts see current values.
"""
import json
import os

ORDER = ("openrouter", "bedrock", "vertex", "foundry")
DEFAULT_VERTEX_REGION = "us-central1"


def _env(name):
    value = os.environ.get(name)
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def _openrouter():
    return _env("OPENROUTER_API_KEY")


def _bedrock():
    region = _env("BEDROCK_REGION")
    if not region:
        return None
    api_key = _env("BEDROCK_API_KEY")
    if api_key:
        return {"region": region, "api_key": api_key}
    access_key_id = _env("AWS_ACCESS_KEY_ID")
    secret_access_key = _env("AWS_SECRET_ACCESS_KEY")
    if access_key_id and secret_access_key:
        creds = {"region": region, "access_key_id": access_key_id, "secret_access_key": secret_access_key}
        session_token = _env("AWS_SESSION_TOKEN")
        if session_token:
            creds["session_token"] = session_token
        return creds
    return None


def _vertex():
    project = _env("VERTEX_PROJECT")
    raw = _env("VERTEX_SERVICE_ACCOUNT_JSON")
    if not project or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {
        "project": project,
        "region": _env("VERTEX_REGION") or DEFAULT_VERTEX_REGION,
        "service_account_json": raw,
    }


def _foundry():
    resource = _env("FOUNDRY_RESOURCE")
    region = _env("FOUNDRY_REGION")
    api_key = _env("FOUNDRY_API_KEY")
    if resource and region and api_key:
        return {"resource": resource, "region": region, "api_key": api_key}
    return None


_LOADERS = {"openrouter": _openrouter, "bedrock": _bedrock, "vertex": _vertex, "foundry": _foundry}


def load():
    """Backend -> creds value for every fully configured server-held backend, in ORDER."""
    held = {}
    for backend in ORDER:
        value = _LOADERS[backend]()
        if value is not None:
            held[backend] = value
    return held


def held_backends():
    return list(load())


def public_summary():
    """What the browser may know: which backends are server-held and each one's region.

    Never includes keys, tokens, project ids, resource names or service-account JSON.
    """
    summary = {}
    for backend, value in load().items():
        summary[backend] = {"region": value["region"]} if isinstance(value, dict) and "region" in value else {}
    return summary


def identifiers():
    """Non-secret-looking but private server-held values (Vertex project id and service-account
    client_email, Foundry resource name) that must still never reach a client."""
    held = load()
    out = []
    if "vertex" in held:
        out.append(held["vertex"]["project"])
        try:
            email = json.loads(held["vertex"]["service_account_json"]).get("client_email")
        except ValueError:
            email = None
        if isinstance(email, str):
            out.append(email)
    if "foundry" in held:
        out.append(held["foundry"]["resource"])
    return [v for v in out if len(v) >= 3]
