"""ANA-182: structured handoff between steps (handoff.json), validated by a small own schema (no jsonschema dep).

Enabled by ANAMNESIA_HANDOFF=1. `summarize_for_next` produces the compact text (plus file paths) the next prompt gets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

FIELDS = {"findings": list, "files_touched": list, "open_questions": list, "artifacts": list}
MAX_ITEMS = 50
MAX_ITEM_CHARS = 500


class HandoffInvalid(ValueError):
    pass


def handoff_enabled() -> bool:
    return os.environ.get("ANAMNESIA_HANDOFF", "").strip().lower() in ("1", "true", "on", "yes")


def validate(doc) -> dict:
    if not isinstance(doc, dict):
        raise HandoffInvalid("handoff must be an object")
    extra = set(doc) - set(FIELDS) - {"confidence"}
    if extra:
        raise HandoffInvalid(f"unknown fields: {sorted(extra)}")
    out: dict = {}
    for k, t in FIELDS.items():
        v = doc.get(k, [])
        if not isinstance(v, t) or len(v) > MAX_ITEMS or any(not isinstance(x, str) or len(x) > MAX_ITEM_CHARS for x in v):
            raise HandoffInvalid(f"{k}: list of <= {MAX_ITEMS} strings of <= {MAX_ITEM_CHARS} chars")
        out[k] = list(v)
    c = doc.get("confidence")
    if c is not None and (isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1):
        raise HandoffInvalid("confidence must be a number in [0,1] or null")
    out["confidence"] = c          # null stays null: never invented
    return out


def write(step_dir, doc) -> Path:
    p = Path(step_dir) / "handoff.json"
    p.write_text(json.dumps(validate(doc), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def read(step_dir) -> dict | None:
    p = Path(step_dir) / "handoff.json"
    if not p.is_file():
        return None
    try:
        return validate(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, HandoffInvalid):
        return None


def summarize_for_next(doc: dict | None, step_dir=None) -> str:
    if not doc:
        return ""
    lines = [f"- finding: {x}" for x in doc["findings"][:10]]
    lines += [f"- open question: {x}" for x in doc["open_questions"][:10]]
    if doc["files_touched"]:
        lines.append("- files: " + ", ".join(doc["files_touched"][:20]))
    if doc["artifacts"]:
        lines.append("- artifacts: " + ", ".join(doc["artifacts"][:20]))
    if doc.get("confidence") is not None:
        lines.append(f"- confidence: {doc['confidence']}")
    if step_dir:
        lines.append(f"- full handoff: {Path(step_dir) / 'handoff.json'}")
    return "\n".join(lines)
