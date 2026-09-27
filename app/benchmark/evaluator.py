"""Human evaluation helpers (§70, §93). Scores 1–5; labels for retrieval quality."""
from __future__ import annotations

VALID_LABELS = ("relevant_found", "relevant_missed", "false_negative", "false_positive")
SCORE_FIELDS = ("accuracy", "completeness", "groundedness", "citation_quality")


def validate_evaluation(ev: dict) -> dict:
    for f in SCORE_FIELDS:
        v = ev.get(f)
        if v is not None and not (isinstance(v, int) and 1 <= v <= 5):
            raise ValueError(f"{f} deve ser inteiro 1–5")
    if not ev.get("run_id"):
        raise ValueError("run_id obrigatório")
    return ev


def validate_label(label: str) -> str:
    if label not in VALID_LABELS:
        raise ValueError(f"label deve ser um de {VALID_LABELS}")
    return label
