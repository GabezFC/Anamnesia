"""Measurements for Onda 3 memory features (ANA-151, ANA-154, ANA-155). Deterministic, local, zero tokens.

* conflict_dataset / evaluate_conflict_detector  ANA-154: labelled note pairs (new x old, copies,
  unrelated, contradictions) -> precision / recall of `lifecycle.find_similar` rules, split train/val
  so thresholds are never tuned on the split that is reported.
* temporal_corpus / temporal_arms                ANA-155: synthetic supersession corpus + "o que vale hoje"
  questions; arms A (no memory layer) / C (temporal demote) / D (strict exclude) -> `stale_on_top` rate.
* budget_curve                                   ANA-151: recall / fact-in-context x context_budget on the
  frozen golden set (BM25 baseline, no LLM).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------------------------
# ANA-154
# ---------------------------------------------------------------------------------------------
_SUBJECTS = ["cache do gateway", "fila de jobs", "provedor de email", "banco principal", "política de retenção",
             "limite de requisições", "janela de deploy", "responsável pelo billing", "versão do runtime",
             "porta do painel", "região do bucket", "tamanho do pool"]


def conflict_dataset() -> list[dict]:
    """Deterministic labelled pairs. label: duplicate | contradiction | unrelated | same_title_same_numbers."""
    out = []
    for i, s in enumerate(_SUBJECTS):
        a = f"A {s} usa o valor {10 + i} desde 2026-0{1 + i % 9}-1{i % 9}. Responsável: equipe plataforma."
        # copy: whitespace / trailing punctuation only
        out.append({"id": f"d{i}", "title_a": s, "a": a, "title_b": s, "b": a.replace(". ", ".  ") + " ", "label": "duplicate"})
        # contradiction: same subject, different number and date
        b = f"A {s} usa o valor {90 + i} desde 2026-1{i % 3}-2{i % 9}. Responsável: equipe plataforma."
        out.append({"id": f"c{i}", "title_a": s, "a": a, "title_b": s, "b": b, "label": "contradiction"})
        # unrelated: another subject entirely
        o = _SUBJECTS[(i + 5) % len(_SUBJECTS)]
        out.append({"id": f"u{i}", "title_a": s, "a": a, "title_b": f"{o} (outro)", "b":
                    f"Reunião sobre {o}: pauta curta, sem decisão numérica registrada, apenas alinhamento de agenda.",
                    "label": "unrelated"})
    return out


def split_of(item_id: str) -> str:
    """Stable 70/30 train/val split by id hash (calibrate on train, report on val)."""
    return "train" if int(hashlib.sha256(item_id.encode()).hexdigest(), 16) % 10 < 7 else "val"


def classify_pair(item: dict, threshold: float = 0.85) -> str:
    from app.memory_store.lifecycle import _norm_title, _numbers
    from app.services.near_dup import similarity
    sim = similarity(item["a"], item["b"])
    if sim >= threshold:
        return "duplicate"
    if _norm_title(item["title_a"]) == _norm_title(item["title_b"]) and _numbers(item["a"]) != _numbers(item["b"]):
        return "contradiction"
    return "unrelated"


def evaluate_conflict_detector(split: str | None = "val", threshold: float = 0.85) -> dict:
    rows = [r for r in conflict_dataset() if split is None or split_of(r["id"]) == split]
    res: dict = {"split": split, "n": len(rows), "threshold": threshold, "classes": {}}
    for cls in ("duplicate", "contradiction"):
        tp = sum(1 for r in rows if r["label"] == cls and classify_pair(r, threshold) == cls)
        fp = sum(1 for r in rows if r["label"] != cls and classify_pair(r, threshold) == cls)
        fn = sum(1 for r in rows if r["label"] == cls and classify_pair(r, threshold) != cls)
        res["classes"][cls] = {"tp": tp, "fp": fp, "fn": fn,
                               "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                               "recall": round(tp / (tp + fn), 4) if tp + fn else None}
    return res


# ---------------------------------------------------------------------------------------------
# ANA-155
# ---------------------------------------------------------------------------------------------
def temporal_corpus(root: Path, n: int = 8) -> list[dict]:
    """Write n (old, new) pairs under root/30-Projetos/Temporal. The OLD note ranks first lexically (it repeats
    the query words) so a layer that ignores supersession would deliver it on top. Returns the questions."""
    base = root / "30-Projetos" / "Temporal"
    base.mkdir(parents=True, exist_ok=True)
    qs = []
    for i in range(n):
        topic = f"sistema{i}zeta"
        old = (f"---\nid: old{i}\ntitle: Configuração do {topic}\ntype: decisao\nstatus: ativo\ncreated: 2026-01-1{i % 9}\n"
               f"updated: 2026-01-1{i % 9}\nsuperseded_by: 30-Projetos/Temporal/{topic}-novo.md\n---\n\n"
               f"# Configuração do {topic}\n\nA configuração do {topic} usa o valor antigo AAA{i}. "
               f"Configuração {topic} configuração {topic}.\n")
        new = (f"---\nid: new{i}\ntitle: Configuração do {topic} (revisada)\ntype: decisao\nstatus: ativo\ncreated: 2026-09-1{i % 9}\n"
               f"updated: 2026-09-1{i % 9}\nsupersedes: 30-Projetos/Temporal/{topic}-antigo.md\n---\n\n"
               f"# Configuração do {topic} revisada\n\nA configuração vigente do {topic} usa o valor BBB{i}.\n")
        (base / f"{topic}-antigo.md").write_text(old, encoding="utf-8")
        (base / f"{topic}-novo.md").write_text(new, encoding="utf-8")
        qs.append({"id": f"t{i}", "question": f"qual a configuração do {topic}", "current": f"30-Projetos/Temporal/{topic}-novo.md",
                   "stale": f"30-Projetos/Temporal/{topic}-antigo.md"})
    return qs


def temporal_arms(gateway, questions: list[dict], k: int = 5) -> dict:
    """Arms: A = layer off, C = temporal demote (default), D = strict exclude. Per arm: current_in_context,
    stale_on_top (old version ranked above the new one, or delivered without the new one), stale_delivered."""
    from dataclasses import replace
    out = {}
    base_cfg = gateway.optimizer.cfg
    arms = {"A_off": replace(base_cfg, temporal_demote=False, conflict_check=False),
            "C_demote": replace(base_cfg, temporal_demote=True, historical_exclude=False, conflict_check=True),
            "D_exclude": replace(base_cfg, temporal_demote=True, historical_exclude=True, conflict_check=True)}
    try:
        for name, cfg in arms.items():
            gateway.optimizer.cfg = cfg
            gateway.optimizer.cache.clear()
            cur = top = delivered = 0
            for q in questions:
                r = gateway.search(q["question"], "baseline", k, persist=False)
                files = [s.file for s in r.sources]
                cur += q["current"] in files
                delivered += q["stale"] in files
                if files and files[0] == q["stale"]:
                    top += 1
            n = len(questions)
            out[name] = {"n": n, "current_in_context": round(cur / n, 4), "stale_on_top": round(top / n, 4),
                         "stale_delivered": round(delivered / n, 4)}
    finally:
        gateway.optimizer.cfg = base_cfg
        gateway.optimizer.cache.clear()
    return out


# ---------------------------------------------------------------------------------------------
# ANA-151
# ---------------------------------------------------------------------------------------------
def budget_curve(gateway, items: list[dict], budgets: list[int], pipeline: str = "baseline", k: int = 8) -> list[dict]:
    from app.benchmark.runner import fact_in_context
    rows = []
    for b in budgets:
        hit = fact = tok = n = 0
        for it in items:
            exp = set(it.get("expected_sources") or [])
            if not exp:
                continue
            r = gateway.search(it["question"], pipeline, k, context_budget=b, persist=False)
            files = {s.file for s in r.sources}
            hit += bool(exp & files)
            f = fact_in_context(it.get("answer_hint"), r.context)
            fact += bool(f)
            tok += int(r.metrics.get("context_tokens") or 0)
            n += 1
        rows.append({"budget": b, "n": n, "recall": round(hit / n, 4) if n else None,
                     "fact_in_context": round(fact / n, 4) if n else None,
                     "mean_context_tokens": round(tok / n, 1) if n else None})
    return rows


# ---------------------------------------------------------------------------------------------
# ANA-162: precision@N of the offline contradiction detector on a LABELLED sample
# ---------------------------------------------------------------------------------------------
def contradiction_sample() -> list[dict]:
    """Labelled note pairs. `contradiction` = same subject, different number/date. The negatives are the
    cases a naive detector would flag: same subject with identical numbers (re-statement), different
    subjects that merely contain numbers, and same title in different projects."""
    rows: list[dict] = []
    for i, s in enumerate(_SUBJECTS):
        base = f"A {s} usa o valor {10 + i} desde 2026-0{1 + i % 9}-1{i % 9}. Responsável: equipe plataforma."
        rows.append({"id": f"pos{i}", "label": True, "project": "p", "title_a": s, "a": base, "title_b": s,
                     "b": f"A {s} usa o valor {90 + i} desde 2026-1{i % 3}-2{i % 9}. Responsável: equipe plataforma.",
                     "project_b": "p"})
    for i, s in enumerate(_SUBJECTS):
        base = f"A {s} usa o valor {10 + i} desde 2026-0{1 + i % 9}-1{i % 9}. Responsável: equipe plataforma."
        kind = i % 3
        if kind == 0:   # same subject, same numbers (restatement)
            rows.append({"id": f"neg{i}", "label": False, "project": "p", "title_a": s, "a": base, "title_b": s,
                         "b": base + " Revisado sem mudanças.", "project_b": "p"})
        elif kind == 1:  # unrelated subject with numbers
            rows.append({"id": f"neg{i}", "label": False, "project": "p", "title_a": s, "a": base,
                         "title_b": f"Reunião {i}", "b": f"Reunião {i} às 14:00 com 7 pessoas na sala {3 + i}; pauta curta.",
                         "project_b": "p"})
        else:           # same title, DIFFERENT project (not comparable)
            rows.append({"id": f"neg{i}", "label": False, "project": "p", "title_a": s, "a": base, "title_b": s,
                         "b": base.replace(f"valor {10 + i}", f"valor {70 + i}"), "project_b": "q"})
    return rows


def contradiction_precision(root: Path, n_top: int | None = None) -> dict:
    """Run `lifecycle.contradictions` on each labelled pair in an isolated store; precision@N over the
    flagged candidates and recall over the positives."""
    from app.memory_store import lifecycle as lc
    from app.memory_store.store import SavedContextStore
    tp = fp = fn = 0
    flagged: list[tuple[float, bool]] = []
    for r in contradiction_sample():
        st = SavedContextStore(Path(root) / r["id"] / "saved_context", rate_per_min=1_000_000)
        st.save(r["title_a"], r["a"], project=r["project"])
        st.save(r["title_b"], r["b"], project=r["project_b"])
        cands = lc.contradictions(st)
        hit = bool(cands)
        if hit:
            flagged.append((cands[0]["similarity"], r["label"]))
        tp += hit and r["label"]
        fp += hit and not r["label"]
        fn += (not hit) and r["label"]
    flagged.sort(key=lambda t: -t[0])
    top = flagged[:n_top] if n_top else flagged
    p_at_n = round(sum(1 for _, ok in top if ok) / len(top), 4) if top else None
    return {"n_pairs": len(contradiction_sample()), "flagged": len(flagged), "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None, "precision_at_n": p_at_n, "n": len(top)}
