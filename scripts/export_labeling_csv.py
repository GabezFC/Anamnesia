"""ANA-109: export items from a COPY/read-only benchmark.db to CSV for human labelling, or score a labelled CSV.

  python scripts/export_labeling_csv.py export --db benchmark.db --out labels.csv [--n 200] [--seed ana109] [--pipeline X]
  python scripts/export_labeling_csv.py score  --csv labels.csv [--json out.json]

The database is opened read-only (SQLite URI mode=ro); nothing is written to it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmark import golden, labeling  # noqa: E402


class _RoDb:
    def __init__(self, path: Path):
        self.cx = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        self.cx.row_factory = sqlite3.Row

    def query(self, sql, args=()):
        return [dict(r) for r in self.cx.execute(sql, args).fetchall()]


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--db", default="benchmark.db")
    e.add_argument("--out", required=True)
    e.add_argument("--n", type=int, default=200)
    e.add_argument("--seed", default="ana109")
    e.add_argument("--pipeline")
    s = sub.add_parser("score")
    s.add_argument("--csv", required=True)
    s.add_argument("--json")
    a = ap.parse_args()
    if a.cmd == "export":
        try:
            gold = golden.load()
        except OSError:
            gold = []
        items = labeling.select_items(_RoDb(Path(a.db)), a.n, a.seed, a.pipeline, gold)
        labeling.write_csv(items, a.out)
        print(f"{len(items)} itens exportados para {a.out} (human_label vazio: preencher relevant|not_relevant)")
        return 0
    rep = labeling.jev_vs_human(labeling.read_labelled_csv(a.csv))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
