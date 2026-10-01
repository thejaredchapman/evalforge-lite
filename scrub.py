import json
import re

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bABSK[A-Za-z0-9+/=]{20,}"),
    re.compile(r"\bbedrock-api-key-[A-Za-z0-9+/=._-]{20,}"),
    re.compile(r"\bya29\.[A-Za-z0-9._-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]

_SECRET_FIELDS = {
    "bedrock": ("api_key", "access_key_id", "secret_access_key", "session_token"),
    "vertex": ("access_token", "service_account_json"),
    "foundry": ("api_key", "access_token"),
}

_MIN_SECRET_LEN = 8


def _service_account_secrets(raw_json):
    try:
        info = json.loads(raw_json)
    except ValueError:
        return []
    key = info.get("private_key") if isinstance(info, dict) else None
    if not isinstance(key, str):
        return []
    return [key, json.dumps(key)[1:-1]]


def secret_values(creds):
    if not isinstance(creds, dict):
        return []
    values = []
    if isinstance(creds.get("openrouter"), str):
        values.append(creds["openrouter"])
    for backend, fields in _SECRET_FIELDS.items():
        backend_creds = creds.get(backend)
        if not isinstance(backend_creds, dict):
            continue
        for field in fields:
            value = backend_creds.get(field)
            if isinstance(value, str):
                values.append(value)
                if field == "service_account_json":
                    values.extend(_service_account_secrets(value))
    return [v for v in values if len(v) >= _MIN_SECRET_LEN]


def scrub(message, creds=None):
    for value in sorted(secret_values(creds), key=len, reverse=True):
        message = message.replace(value, REDACTED)
    for pattern in _PATTERNS:
        message = pattern.sub(REDACTED, message)
    return message
