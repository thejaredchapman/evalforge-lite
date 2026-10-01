import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SERVER_KEY_ENV_VARS = (
    "OPENROUTER_API_KEY",
    "BEDROCK_REGION", "BEDROCK_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "VERTEX_PROJECT", "VERTEX_REGION", "VERTEX_SERVICE_ACCOUNT_JSON",
    "FOUNDRY_RESOURCE", "FOUNDRY_REGION", "FOUNDRY_API_KEY",
    "SERVER_KEY_DAILY_CAP",
)


@pytest.fixture(autouse=True)
def _isolate_server_key_env(monkeypatch):
    """Server-held keys are opt-in via env; no test may depend on the developer's real environment."""
    for name in SERVER_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
