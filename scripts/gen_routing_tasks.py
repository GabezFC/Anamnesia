"""Deterministically build benchmark/routing_tasks.json from synthetic questions + MANIFEST.

Difficulty = objective score (no LLM), from fields of synthetic_questions.json / MANIFEST.json:
  +2 qclass multi_hop ; +1 if >=2 gold notes ; +2 unanswerable (must abstain)
  +1 paraphrase_of set or qclass ambiguous ; +1 gold note in a duplicate group or archived
  +1 question >=25 words ; +1 question <=3 words
  score 0 -> easy, 1 -> medium, >=2 -> hard.
Extraction tasks: seeded sample of MANIFEST facts, JSON schema verifier.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261006
N_EXTRACTION = 24


def difficulty_score(q, dup, arch):
    s = 0
    if q["qclass"] == "multi_hop":
        s += 2
    if len(q["expected_sources"]) >= 2:
        s += 1
    if not q["answerable"]:
        s += 2
    if q["paraphrase_of"] or q["qclass"] == "ambiguous":
        s += 1
    if any(p in dup or p in arch for p in q["expected_sources"]):
        s += 1
    n = len(q["question"].split())
    if n >= 25:
        s += 1
    if n <= 3:
        s += 1
    return s


def label(score):
    return "easy" if score == 0 else "medium" if score == 1 else "hard"


def build():
    qs = json.loads((ROOT / "benchmark/synthetic_questions.json").read_text(encoding="utf-8"))
    man = json.loads((ROOT / "data/synthetic_vault/MANIFEST.json").read_text(encoding="utf-8"))
    dup = {p for g in man["duplicate_groups"] for p in g}
    arch = set(man["archived"])
    facts = {f["path"]: f for f in man["facts"]}
    tasks = []
    for q in sorted(qs, key=lambda x: x["id"]):
        sc = difficulty_score(q, dup, arch)
        gold = q["expected_sources"]
        if q["answerable"]:
            exp = [facts[p]["token"] for p in gold if p in facts][:1]
            gt = {"gold_notes": gold, "expected_facts": exp, "answer_hint": q["answer_hint"], "answerable": True}
            ver = {"type": "fact_match+citation", "mode": "all"}
        else:
            gt = {"gold_notes": [], "expected_facts": [], "answer_hint": q["answer_hint"], "answerable": False}
            ver = {"type": "abstention"}
        risk = "high" if not q["answerable"] else "medium" if q["qclass"] == "multi_hop" else "low"
        tasks.append({"id": f"rt-{q['id']}", "kind": "memory_qa", "query": q["question"],
                      "difficulty_label": label(sc),
                      "ground_truth": {**gt, "source_question": q["id"], "qclass": q["qclass"],
                                       "difficulty_score": sc},
                      "verifier": ver, "risk": risk})
    rng = random.Random(SEED)
    fl = sorted(man["facts"], key=lambda f: f["path"])
    for i, f in enumerate(rng.sample(fl, N_EXTRACTION)):
        schema = {"type": "object", "required": ["path", "token"],
                  "properties": {"path": {"type": "string"}, "token": {"type": "string"}}}
        tasks.append({"id": f"rt-ex{i + 1:03d}", "kind": "extraction",
                      "query": "Da nota abaixo extraia em JSON {\"path\", \"token\"} o identificador/versao citado.\n"
                               f"Nota {f['path']}: {f['fact']}.",
                      "difficulty_label": "easy" if len(f["fact"]) < 80 else "medium",
                      "ground_truth": {"expected_json": {"path": f["path"], "token": f["token"]}},
                      "verifier": {"type": "json_schema", "schema": schema, "match_expected": True},
                      "risk": "low"})
    return {"seed": SEED, "version": 1, "tasks": tasks}


def main():
    out = ROOT / "benchmark/routing_tasks.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    sys.exit(main())
