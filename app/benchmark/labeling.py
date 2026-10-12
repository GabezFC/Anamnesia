"""ANA-109: offline labelling infrastructure over benchmark.db (export CSV -> human labels -> agreement).

NO labels are produced here. `select_items` + `write_csv` produce a CSV of (query, candidate, JEV
relevance, JEV decision, expected source) for a human to fill in the `human_label` column;
`jev_vs_human` computes Cohen's kappa and the JEV false-negative rate ONLY from rows a human
labelled. Without labels every metric is reported as UNKNOWN (never as 0).

Binary label vocabulary: relevant | not_relevant. The legacy `evaluator.VALID_LABELS` are accepted
and mapped (relevant_found/relevant_missed/false_negative -> relevant; false_positive -> not_relevant).
Read-only on the database.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from app.benchmark.evaluator import VALID_LABELS

LABELS = ("relevant", "not_relevant")
_LEGACY = {"relevant_found": "relevant", "relevant_missed": "relevant", "false_negative": "relevant",
           "false_positive": "not_relevant"}
JEV_POSITIVE = ("KEEP", "REVIEW")  # not dropped by the judge
JEV_NEGATIVE = ("DROP", "DROP_FALLBACK", "QUARANTINE")
CSV_FIELDS = ["item_id", "run_id", "candidate_id", "query", "source_file", "section", "pipeline",
              "jev_relevance", "jev_decision", "jev_label", "expected_sources", "source_is_expected",
              "human_label", "annotator", "notes"]
MIN_LABELS_FOR_KAPPA = 30  # below this the kappa is reported but flagged unreliable


def item_id(run_id: str, candidate_id: str) -> str:
    return hashlib.sha256(f"{run_id}|{candidate_id}".encode("utf-8")).hexdigest()[:16]


def normalize_label(raw: str | None) -> str | None:
    """'' -> None (unlabelled); legacy labels mapped; anything else raises ValueError."""
    v = (raw or "").strip().lower()
    if not v:
        return None
    if v in LABELS:
        return v
    if v in _LEGACY:
        return _LEGACY[v]
    raise ValueError(f"rótulo inválido {raw!r}; use {LABELS} (ou legado {VALID_LABELS})")


def jev_label(decision: str | None) -> str | None:
    if decision in JEV_POSITIVE:
        return "relevant"
    if decision in JEV_NEGATIVE:
        return "not_relevant"
    return None  # UNJUDGED / UNSELECTED / NULL: the judge said nothing


def select_items(db, n: int = 200, seed: str = "ana109", pipeline: str | None = None,
                 golden_items: list[dict] | None = None) -> list[dict]:
    """Deterministic, decision-stratified sample of judged candidates (round-robin over decisions,
    each ordered by sha256(seed|run|candidate)), so the CSV is reproducible and every decision class
    (incl. DROP, needed to estimate the false-negative rate) is represented."""
    sql = ("SELECT c.run_id, c.candidate_id, c.source_file, c.section, c.relevance, c.decision, r.query,"
           " r.question_id, r.pipeline FROM candidates c JOIN runs r ON r.run_id=c.run_id"
           " WHERE c.decision IN ('KEEP','REVIEW','DROP','DROP_FALLBACK','QUARANTINE')")
    args: tuple = ()
    if pipeline:
        sql += " AND r.pipeline=?"
        args = (pipeline,)
    rows = db.query(sql, args)
    exp = {str(q["id"]): list(q.get("expected_sources") or []) for q in (golden_items or [])}
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(r["decision"], []).append(r)
    for b in buckets.values():
        b.sort(key=lambda r: hashlib.sha256(f"{seed}|{r['run_id']}|{r['candidate_id']}".encode()).hexdigest())
    out: list[dict] = []
    order = sorted(buckets)
    i = 0
    while len(out) < n and any(i < len(buckets[k]) for k in order):
        for k in order:
            if i < len(buckets[k]) and len(out) < n:
                out.append(buckets[k][i])
        i += 1
    items = []
    for r in out:
        e = exp.get(str(r.get("question_id") or ""), [])
        items.append({
            "item_id": item_id(r["run_id"], r["candidate_id"]), "run_id": r["run_id"],
            "candidate_id": r["candidate_id"], "query": r["query"], "source_file": r["source_file"],
            "section": r["section"], "pipeline": r["pipeline"],
            "jev_relevance": "" if r["relevance"] is None else round(float(r["relevance"]), 4),
            "jev_decision": r["decision"], "jev_label": jev_label(r["decision"]) or "",
            "expected_sources": json.dumps(e, ensure_ascii=False) if e else "",
            "source_is_expected": ("" if not e else int(r["source_file"] in e)),
            "human_label": "", "annotator": "", "notes": ""})
    return items


def write_csv(items: list[dict], path: Path | str) -> Path:
    path = Path(path)
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    w.writerows(items)
    path.write_text(buf.getvalue(), encoding="utf-8-sig", newline="")  # BOM: opens cleanly in Excel
    return path


def read_labelled_csv(path: Path | str) -> list[dict]:
    """Rows with a valid human_label only; raises ValueError on an invalid label or missing columns."""
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        rd = csv.DictReader(fh)
        missing = {"item_id", "human_label", "jev_decision"} - set(rd.fieldnames or [])
        if missing:
            raise ValueError(f"CSV sem colunas obrigatórias: {sorted(missing)}")
        out = []
        for ln, row in enumerate(rd, start=2):
            try:
                lab = normalize_label(row.get("human_label"))
            except ValueError as exc:
                raise ValueError(f"linha {ln}: {exc}") from None
            if lab is not None:
                out.append({**row, "human_label": lab})
        return out


def cohen_kappa(a: list[str], b: list[str]) -> dict:
    """Cohen's kappa for two raters over the same items. kappa=None when undefined (n=0 or both
    raters constant and identical -> pe=1)."""
    if len(a) != len(b):
        raise ValueError("listas de tamanhos diferentes")
    n = len(a)
    if n == 0:
        return {"n": 0, "kappa": None, "observed_agreement": None, "expected_agreement": None}
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    kappa = None if pe >= 1.0 else round((po - pe) / (1 - pe), 4)
    return {"n": n, "kappa": kappa, "observed_agreement": round(po, 4), "expected_agreement": round(pe, 4)}


def jev_vs_human(rows: list[dict]) -> dict:
    """JEV x human agreement from labelled rows. Reports counts, kappa (flagged unreliable below
    MIN_LABELS_FOR_KAPPA) and the JEV false-negative rate = P(human 'relevant' | JEV dropped)."""
    pairs = [(r.get("jev_label") or jev_label(r.get("jev_decision")), r["human_label"]) for r in rows]
    pairs = [(j, h) for j, h in pairs if j in LABELS and h in LABELS]
    n = len(pairs)
    cm = Counter(pairs)
    res: dict = {"n_labelled": n, "confusion": {f"jev_{j}__human_{h}": cm[(j, h)] for j in LABELS for h in LABELS}}
    if n == 0:
        res.update(kappa=None, false_negative_rate="UNKNOWN", status="UNKNOWN: nenhum rótulo humano")
        return res
    k = cohen_kappa([j for j, _ in pairs], [h for _, h in pairs])
    dropped = cm[("not_relevant", "relevant")] + cm[("not_relevant", "not_relevant")]
    kept = cm[("relevant", "relevant")] + cm[("relevant", "not_relevant")]
    res.update(kappa=k["kappa"], observed_agreement=k["observed_agreement"], n_jev_dropped_labelled=dropped,
               n_jev_kept_labelled=kept,
               false_negative_rate=(round(cm[("not_relevant", "relevant")] / dropped, 4) if dropped else "UNKNOWN"),
               false_positive_rate=(round(cm[("relevant", "not_relevant")] / kept, 4) if kept else "UNKNOWN"),
               status="OK" if n >= MIN_LABELS_FOR_KAPPA else f"UNRELIABLE: n={n} < {MIN_LABELS_FOR_KAPPA}")
    return res
