"""Logging (§59, §99): application.log + JSONL streams. API keys are never logged."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from config import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs"
_lock = threading.Lock()
_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|ts[_-][A-Za-z0-9_\-]{12,}|Bearer\s+\S+|api[_-]?key\s*[=:]\s*\S+)", re.I)


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


def get_logger() -> logging.Logger:
    log = logging.getLogger("memory_gateway")
    if not log.handlers:
        LOG_DIR.mkdir(exist_ok=True)
        h = logging.FileHandler(LOG_DIR / "application.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def jsonl(stream: str, record: dict) -> None:
    """stream in {benchmark, jev, agents}."""
    LOG_DIR.mkdir(exist_ok=True)
    rec = {"ts": time.time(), **record}
    line = redact(json.dumps(rec, default=str, ensure_ascii=False))
    with _lock, open(LOG_DIR / f"{stream}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
