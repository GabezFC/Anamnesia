"""ANAM-026: license allow-list (not legal advice; verify upstream before shipping).

* ALLOWED  - permissive licenses: fine for runtime, models and redistribution.
* WEAK_COPYLEFT - file-level copyleft, fine as an unmodified dependency.
* RESTRICTED - usable only with an explicit, informed opt-in (never default-on, never bundled):
  Qwen Community License (usage thresholds / attribution terms).
* NON_COMMERCIAL - optional-only, off by default, user-warned: CC BY-NC-ND (Provence).
Anything else (or unknown/None) is not allowed in the shipped set.
"""
from __future__ import annotations

import re

ALLOWED = frozenset({"apache-2.0", "mit", "bsd-3-clause", "bsd-2-clause", "psf-2.0", "isc"})
WEAK_COPYLEFT = frozenset({"mpl-2.0"})
RESTRICTED = frozenset({"qwen", "qwen-community", "qwen-research", "tongyi-qianwen", "llama3.3", "gemma"})
NON_COMMERCIAL = frozenset({"cc-by-nc-nd-4.0", "cc-by-nc-4.0", "cc-by-nc-sa-4.0"})

# Optional stages whose license forbids commercial use: must stay False in every shipped default.
NON_COMMERCIAL_STAGES = ("provence",)


def normalize(lic: str | None) -> str:
    return re.sub(r"\s+", "-", (lic or "").strip().lower())


def classify(lic: str | None) -> str:
    """'allowed' | 'weak_copyleft' | 'restricted' | 'non_commercial' | 'unknown'."""
    n = normalize(lic)
    if n in ALLOWED:
        return "allowed"
    if n in WEAK_COPYLEFT:
        return "weak_copyleft"
    if n in RESTRICTED:
        return "restricted"
    if n in NON_COMMERCIAL:
        return "non_commercial"
    return "unknown"


_ALIASES = {
    "apache-2.0": "apache-2.0", "apache-software-license": "apache-2.0",
    "mit-license": "mit", "bsd-license": "bsd-3-clause",
    "psf": "psf-2.0", "python-software-foundation-license": "psf-2.0",
    "mozilla-public-license-2.0-(mpl-2.0)": "mpl-2.0",
}


def classify_metadata_string(raw: str) -> str:
    """Classify a license string from package metadata (e.g. 'MIT (MIT License)', 'MIT OR Apache-2.0').

    'A OR B' is acceptable if any alternative is acceptable (dual-licensed: the user picks).
    """
    head = raw.split("(")[0].strip()
    results = []
    for alt in re.split(r"\s+OR\s+", head):
        n = normalize(alt)
        results.append(classify(_ALIASES.get(n, n)))
    for good in ("allowed", "weak_copyleft"):
        if good in results:
            return good
    return results[0] if results else "unknown"
