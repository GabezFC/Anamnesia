#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verificacao independente do corpus sintetico (nao reusa a logica do gerador)."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VAULT = REPO / "data" / "synthetic_vault"
Q = REPO / "benchmark" / "synthetic_questions.json"
G = VAULT / "graphify-out" / "graph.json"
M = VAULT / "MANIFEST.json"


def fingerprint() -> str:
    h = hashlib.sha256()
    for p in sorted(VAULT.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(VAULT).as_posix().encode())
            h.update(p.read_bytes())
    h.update(Q.read_bytes())
    return h.hexdigest()


def main() -> int:
    ok = True
    mds = sorted(p for p in VAULT.rglob("*.md"))
    rel = {p.relative_to(VAULT).as_posix() for p in mds}
    raw = {r: (VAULT / r).read_text(encoding="utf-8") for r in rel}
    questions = json.loads(Q.read_text(encoding="utf-8"))
    graph = json.loads(G.read_text(encoding="utf-8"))
    manifest = json.loads(M.read_text(encoding="utf-8"))

    print(f"md files                 : {len(mds)}")
    for d in ["00-Inbox", "10-Trabalho", "20-Dev-IA", "30-Projetos",
              "40-Estudos", "50-Pessoal", "70-Daily"]:
        print(f"  {d:<14}: {sum(1 for r in rel if r.startswith(d + '/'))}")
    non_ascii = [r for r in rel if any(ord(c) > 127 for c in r)]
    print(f"paths nao-ascii          : {len(non_ascii)}")
    ok &= not non_ascii

    arq = [r for r in rel if re.search(r"^status: arquivado$", raw[r], re.M)]
    print(f"status: arquivado (grep) : {len(arq)} | manifest: {len(manifest['archived'])}")
    ok &= set(arq) == set(manifest["archived"])

    inj = [r for r in rel if "Ignore previous instructions" in raw[r]]
    print(f"notas com injecao (grep) : {len(inj)} | manifest benign+malicious: "
          f"{len(manifest['injection_notes']['benign']) + len(manifest['injection_notes']['malicious'])}")
    ok &= len(inj) == 12

    print(f"questions                : {len(questions)}")
    ok &= len(questions) == 120

    # grep real: cada pergunta answerable -> token do manifest presente na fonte
    tok_by_path = {f["path"]: f["token"] for f in manifest["facts"]}
    hits = 0
    for q in questions:
        if not q["answerable"]:
            continue
        toks = [tok_by_path[p] for p in q["expected_sources"] if p in tok_by_path]
        if toks and any(t in raw[p] for t in toks for p in q["expected_sources"]):
            hits += 1
    ans = sum(1 for q in questions if q["answerable"])
    print(f"answerable com token na fonte verificado por leitura crua: {hits}/{ans}")
    ok &= hits == ans and ans >= 100

    # schema estrito das perguntas
    QK = {"id", "question", "category", "qclass", "expected_sources",
          "answer_hint", "answerable", "paraphrase_of"}
    QC = {"factual", "technical", "navigation", "multi_hop", "ambiguous",
          "short", "long", "paraphrased", "rare_terms", "unanswerable"}
    bad = [q["id"] for q in questions if set(q) != QK or q["qclass"] not in QC]
    print(f"perguntas fora do schema : {len(bad)} {bad[:5]}")
    ok &= not bad

    # schema estrito dos nodes
    NK = {"id", "label", "norm_label", "source_file", "node_kind", "source_location"}
    badn = [n["id"] for n in graph["nodes"]
            if set(n) != NK or n["node_kind"] not in ("page", "heading")
            or set(n["source_location"]) != {"line"} or n["source_file"] not in rel]
    print(f"nodes fora do schema     : {len(badn)}")
    ok &= not badn
    badl = [l for l in graph["links"] if set(l) != {"source", "target"}]
    print(f"links fora do schema     : {len(badl)}")
    ok &= not badl

    # idempotencia: rerun + comparacao de fingerprint
    fp1 = fingerprint()
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "gen_synthetic_corpus.py")],
                       capture_output=True, text=True)
    fp2 = fingerprint()
    print(f"idempotencia (rerun)     : {'IDENTICO' if fp1 == fp2 else 'DIVERGIU'} "
          f"(exit={r.returncode})")
    ok &= fp1 == fp2 and r.returncode == 0

    print("-" * 60)
    print("CHECK INDEPENDENTE:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
