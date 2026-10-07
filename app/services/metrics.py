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


LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3
JSONL_MAX_BYTES = 20 * 1024 * 1024


def _rotate_jsonl(path) -> None:
    """Size-based rotation for the *.jsonl streams (keeps LOG_BACKUPS older files). Caller holds _lock."""
    try:
        if path.exists() and path.stat().st_size > JSONL_MAX_BYTES:
            for i in range(LOG_BACKUPS, 0, -1):
                src = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
                dst = path.with_name(f"{path.name}.{i}")
                if src.exists():
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
    except OSError:
        pass


def get_logger() -> logging.Logger:
    log = logging.getLogger("memory_gateway")
    if not log.handlers:
        LOG_DIR.mkdir(exist_ok=True)
        from logging.handlers import RotatingFileHandler  # T0.4: bounded log growth
        h = RotatingFileHandler(LOG_DIR / "application.log", maxBytes=LOG_MAX_BYTES,
                                backupCount=LOG_BACKUPS, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def jsonl(stream: str, record: dict) -> None:
    """stream in {benchmark, jev, agents}."""
    LOG_DIR.mkdir(exist_ok=True)
    rec = {"ts": time.time(), **record}
    line = redact(json.dumps(rec, default=str, ensure_ascii=False))
    path = LOG_DIR / f"{stream}.jsonl"
    with _lock:
        _rotate_jsonl(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
