"""Freeze benchmark/golden from benchmark/synthetic_questions.json against data/synthetic_vault (ANA-009/011).

  python scripts/freeze_golden.py            # write benchmark/golden/{retrieval.jsonl,manifest.json}
  python scripts/freeze_golden.py --check    # verify corpus + items hash (exit 1 on drift); for CI
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.benchmark import golden  # noqa: E402

VAULT = ROOT / "data" / "synthetic_vault"
QUESTIONS = ROOT / "benchmark" / "synthetic_questions.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--version", default="golden-v1")
    ap.add_argument("--owner", default="Gabriel")
    a = ap.parse_args(argv)
    if a.check:
        try:
            m = golden.verify(VAULT)
        except golden.CorpusMismatch as exc:
            print(f"DRIFT: {exc}", file=sys.stderr)
            return 1
        print(f"ok {m['version']} corpus={m['corpus_hash'][:12]} coverage={m['coverage']}")
        return 0
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    m = golden.freeze(qs, VAULT, a.version, a.owner)
    print(json.dumps(m["coverage"], ensure_ascii=False))
    if not m["coverage"]["meets_targets"]:
        print(f"AVISO: meta ANA-009 (>={golden.TARGET_MIN_ITEMS} itens, >={golden.TARGET_MIN_UNANSWERABLE} "
              "nao respondiveis) NAO atingida; veja coverage.gap_*", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
