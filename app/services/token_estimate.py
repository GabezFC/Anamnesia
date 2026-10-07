"""Token estimate with an optional, MEASURED per-language correction (T2.1 hook).

`estimate_tokens(text, lang="auto")` is, by default, EXACTLY `app.gateway.token_budget.estimate_tokens`
(heuristic max(chars/4, words*1.3) * PT_CALIBRATION_FACTOR), for every language. Nothing changes
unless a calibration file is supplied through `ANAMNESIA_TOKEN_CALIBRATION` (path to a JSON like
`{"pt": 1.25, "other": 1.0, "source": "tiktoken cl100k_base, n=...", "tokenizer": "..."}`). Factors in
that file are RELATIVE TO THE RAW heuristic (before PT_CALIBRATION_FACTOR) and replace it. The file is
produced from a real tokenizer (tiktoken) or from API-reported usage; no factor is hard-coded here
because none could be derived honestly for a Claude tokenizer offline (see docs/MEASUREMENT.md).

`detect_lang` is a cheap stopword/diacritic heuristic ("pt" | "other"), used only for `lang="auto"`
when a calibration file is active.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from app.gateway import token_budget as tb

ENV_CALIBRATION = "ANAMNESIA_TOKEN_CALIBRATION"
_PT_STOP = {"de", "do", "da", "dos", "das", "em", "no", "na", "que", "para", "com", "uma", "não", "nao",
            "os", "as", "um", "por", "foi", "são", "sao", "é", "como", "mais", "ou", "se", "ao", "pelo"}
_EN_STOP = {"the", "of", "and", "to", "in", "is", "for", "that", "with", "this", "are", "was", "on"}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def detect_lang(text: str) -> str:
    words = [w.lower() for w in _WORD.findall(text[:4000])]
    if not words:
        return "other"
    pt = sum(w in _PT_STOP for w in words)
    en = sum(w in _EN_STOP for w in words)
    accents = sum(ch in "ãõáéíóúâêôçà" for ch in text[:4000].lower())
    return "pt" if (pt > en and pt / len(words) > 0.05) or (accents / max(1, len(text[:4000])) > 0.01 and pt >= en) \
        else "other"


def load_calibration(path: str | os.PathLike | None = None) -> dict | None:
    """Factors from the JSON file (env by default); None when absent/invalid -> default behaviour."""
    p = path or os.environ.get(ENV_CALIBRATION, "").strip()
    if not p:
        return None
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ok = {k: float(v) for k, v in data.items() if k in ("pt", "other") and isinstance(v, (int, float)) and v > 0}
    return ok or None


def estimate_tokens(text: str, lang: str = "auto", calibration: dict | None = None) -> int:
    cal = calibration if calibration is not None else load_calibration()
    if not cal:
        return tb.estimate_tokens(text)  # default path: byte-identical to the legacy estimator
    if not text:
        return 0
    lg = detect_lang(text) if lang == "auto" else lang
    factor = cal.get(lg if lg in cal else "other")
    if factor is None:
        return tb.estimate_tokens(text)
    raw = max(len(text) / 4.0, len(tb._WORD.findall(text)) * 1.3)  # noqa: SLF001
    return max(1, math.ceil(raw * factor))
