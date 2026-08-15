import json
import os
from pathlib import Path

JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "openai/gpt-4o-mini")

_DATA_DIR = Path(__file__).parent / "data"
_PROVIDERS_PATH = _DATA_DIR / "providers.json"


def load_providers():
    with open(_PROVIDERS_PATH) as f:
        return json.load(f)
