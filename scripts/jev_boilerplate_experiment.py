"""Measure whether hoisting the JEV static boilerplate into `state` changes the judgement.

Each per-candidate question currently repeats 82 static tokens (20 question + 62 criteria).
At 25-50 candidates that is 2,000-4,100 tokens of pure repetition per query. The SDK allows
`criteria=None`, so the criteria could be declared once in `state` instead.

That is only worth doing if the SCORES STAY THE SAME. This script calls the real JEV API with
both payload shapes over the same candidates and reports per-candidate score deltas plus the
routing decisions each shape produces. Nothing is changed in the pipeline: this is evidence
gathering, and a decision that alters judgement semantics must not be made by assumption.

Usage:  python scripts/jev_boilerplate_experiment.py [--candidates 12]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.gateway.token_budget import estimate_tokens  # noqa: E402
from app.services.jev import (  # noqa: E402
    INJECTION_CRITERIA,
    RELEVANCE_CRITERIA,
    RELEVANCE_QUESTION,
    JevService,
    route,
)


def build_current(svc: JevService, batch, query: str) -> tuple[dict, dict]:
    """Shape A — today: criteria repeated inside every question."""
    return {"query": query}, svc.build_questions(batch)


def build_hoisted(svc: JevService, batch, query: str) -> tuple[dict, dict]:
    """Shape B — criteria declared once in `state`, questions carry only the candidate."""
    state = {
        "query": query,
        "task": RELEVANCE_QUESTION.replace("the query", "`query`").replace("this candidate", "`candidate`"),
        "criteria": RELEVANCE_CRITERIA,
    }
    qs = {}
    for i, c in enumerate(batch):
        qs[f"rel_{i}"] = {"instructions": {"candidate": svc.candidate_payload(c, ref=i)},
                          "criteria": None}
    return state, qs


def tokens_of(state: dict, questions: dict) -> int:
    t = estimate_tokens(json.dumps(state, ensure_ascii=False))
    for q in questions.values():
        t += estimate_tokens(json.dumps(q, ensure_ascii=False))
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=12)
    ap.add_argument("--query", default="Qual driver do Postgres o Norteia usa e por que o psycopg foi descartado?")
    a = ap.parse_args()

    gw = MemoryGateway()
    gw.warm()
    from app.retrieval.pipelines import _graphify_candidates
    uniq, _ = _graphify_candidates(gw, a.query)
    batch = uniq[: a.candidates]
    print(f"query     : {a.query}")
    print(f"candidatos: {len(batch)}\n")

    svc = gw.make_jev(gw.jev_cfg, cache=False)
    backend = svc.backend

    state_a, qs_a = build_current(svc, batch, a.query)
    state_b, qs_b = build_hoisted(svc, batch, a.query)
    est_a, est_b = tokens_of(state_a, qs_a), tokens_of(state_b, qs_b)
    print(f"tokens estimados  A(atual)={est_a:,}   B(hoisted)={est_b:,}   "
          f"delta={est_a - est_b:+,} ({(est_b / est_a - 1) * 100:+.1f}%)\n")

    print("chamando a API real do JEV nas duas formas...")
    ans_a, usage_a, _ = backend.evaluate(state_a, qs_a)
    ans_b, usage_b, _ = backend.evaluate(state_b, qs_b)

    print(f"  A: input={usage_a.get('input_tokens')} output={usage_a.get('output_tokens')}")
    print(f"  B: input={usage_b.get('input_tokens')} output={usage_b.get('output_tokens')}")
    ia, ib = usage_a.get("input_tokens") or 0, usage_b.get("input_tokens") or 0
    if ia:
        print(f"  reducao real de input: {ia - ib:+,} tokens ({(ib / ia - 1) * 100:+.1f}%)\n")

    print(f"{'ref':<4} {'nota':<46} {'A':>6} {'B':>6} {'delta':>7}  {'rota A':<9} {'rota B':<9}")
    print("-" * 96)
    deltas, flips = [], 0
    for i, c in enumerate(batch):
        ra, rb = ans_a.get(f"rel_{i}"), ans_b.get(f"rel_{i}")
        if ra is None or rb is None:
            continue
        d = rb - ra
        deltas.append(abs(d))
        da = route(ra, None, svc.cfg)
        db = route(rb, None, svc.cfg)
        flips += da != db
        flag = "  <-- MUDOU" if da != db else ""
        print(f"{i:<4} {c.source_file.rsplit('/', 1)[-1][:44]:<46} {ra:>6.2f} {rb:>6.2f} {d:>+7.2f}  {da:<9} {db:<9}{flag}")

    print()
    if deltas:
        print(f"delta absoluto: media={st.mean(deltas):.4f}  mediana={st.median(deltas):.4f}  max={max(deltas):.4f}")
    print(f"decisoes de roteamento alteradas: {flips}/{len(deltas)}")
    print()
    if flips == 0 and deltas and max(deltas) < 0.10:
        print("VEREDITO: equivalente. Hoisting e seguro e economiza os tokens acima.")
    else:
        print("VEREDITO: NAO equivalente. O hoisting muda o julgamento — nao adotar so por economia.")


if __name__ == "__main__":
    main()
