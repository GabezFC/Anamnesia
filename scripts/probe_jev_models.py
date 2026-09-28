"""Probe: list the JEV models available on the configured TypeSafe account (GET /v1/models).

Cited by docs/JEV_API.md as the reproducible source of the model list. Requires TYPESAFE_API_KEY."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from typesafe_sdk import TypeSafeClient

c = TypeSafeClient()
ms = c.models.list()
data = getattr(ms, "data", ms)
for m in data:
    print(json.dumps(m.model_dump() if hasattr(m, "model_dump") else str(m), default=str))
