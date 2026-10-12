"""ANA-009/011: append 30 deterministic unanswerable questions (sq121..sq150) to benchmark/synthetic_questions.json.

Each asks about an invented entity that must NOT exist in data/synthetic_vault (asserted here). Idempotent.
Then run: scripts/gen_routing_tasks.py and scripts/freeze_golden.py to propagate.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QPATH = ROOT / "benchmark" / "synthetic_questions.json"
VAULT = ROOT / "data" / "synthetic_vault"

TEMPLATES = [
    "Onde esta documentado o procedimento de rollback do servico {x}?",
    "Qual foi a decisao registrada sobre a migracao do modulo {x}?",
    "Que versao da biblioteca {x} o projeto adotou?",
    "Quem e o responsavel pelo componente {x} segundo as notas?",
    "Qual o limite de requisicoes configurado para o gateway {x}?",
    "Em que nota esta o post-mortem do incidente {x}?",
]
INVENTED = ["Quorblax", "Zimtrel", "Vandorqui", "Plixomar", "Ghentoru", "Fyrnadel", "Mosquivar", "Ulthrenix",
            "Dravopeq", "Kellumbra", "Xandyrol", "Brivoshka", "Ostrelwin", "Jandupel", "Nuvrelka", "Tharsolin",
            "Wexorbit", "Yamplequ", "Cindrovak", "Hulbaxen", "Ibrathel", "Lopquenar", "Mervitzo", "Qasdrubal",
            "Rumbelot", "Svintarex", "Tolquimar", "Urvadenko", "Valxorin", "Zephrodak"]


def main() -> int:
    qs = json.loads(QPATH.read_text(encoding="utf-8"))
    have = {q["id"] for q in qs}
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in VAULT.rglob("*.md"))
    added = 0
    for i, word in enumerate(INVENTED):
        qid = f"sq{121 + i}"
        if qid in have:
            continue
        if word.lower() in corpus:
            raise SystemExit(f"{word} exists in the vault; pick another invented name")
        qs.append({"id": qid, "question": TEMPLATES[i % len(TEMPLATES)].format(x=word), "category": "projetos",
                   "qclass": "unanswerable", "expected_sources": [],
                   "answer_hint": "Nao existe nota no vault sintetico com essa informacao.",
                   "answerable": False, "paraphrase_of": None})
        added += 1
    QPATH.write_text(json.dumps(qs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("added", added, "total", len(qs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
