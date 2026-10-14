"""Golden evaluation set (ANA-009) with a frozen deterministic split (ANA-011).

* split: 60/20/20 train/val/test decided by sha256(question id) - stable when questions are added,
  never reshuffled. Calibrate only on "train"; report only on "test" (with Wilson CIs).
* golden: benchmark/golden/retrieval.jsonl + manifest.json carrying the corpus hash, a version and an
  owner. `verify()` raises when the corpus the run is about to use differs from the hash that was frozen,
  so a drifted vault can never be compared against old numbers.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = ROOT / "benchmark" / "golden"
SPLIT_FRACTIONS = (("train", 60), ("val", 20), ("test", 20))
TARGET_MIN_ITEMS = 150
TARGET_MIN_UNANSWERABLE = 30
SPLIT_SALT = "anamnesia-eval-v1"


class CorpusMismatch(RuntimeError):
    """The corpus on disk is not the one the golden set was frozen against."""


def split_of(question_id: str) -> str:
    """Deterministic bucket for an id: independent of order and of how many questions exist."""
    h = int(hashlib.sha256(f"{SPLIT_SALT}:{question_id}".encode("utf-8")).hexdigest(), 16) % 100
    edge = 0
    for name, pct in SPLIT_FRACTIONS:
        edge += pct
        if h < edge:
            return name
    return "test"


def split_questions(questions: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {n: [] for n, _ in SPLIT_FRACTIONS}
    for q in sorted(questions, key=lambda q: str(q["id"])):
        out[split_of(str(q["id"]))].append(q)
    return out


def corpus_hash(vault: Path) -> str:
    """sha256 over (relative path, file bytes) of every .md in the vault, sorted. Ignores graphify-out and dotdirs."""
    vault = Path(vault)
    h = hashlib.sha256()
    for p in sorted(vault.rglob("*.md")):
        rel = p.relative_to(vault).as_posix()
        if rel.startswith("graphify-out/") or any(part.startswith(".") for part in p.relative_to(vault).parts):
            continue
        h.update(rel.encode("utf-8") + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def coverage(questions: list[dict]) -> dict:
    n = len(questions)
    un = sum(1 for q in questions if not q.get("answerable", True))
    sp = split_questions(questions)
    return {"n": n, "unanswerable": un, "splits": {k: len(v) for k, v in sp.items()},
            "meets_targets": n >= TARGET_MIN_ITEMS and un >= TARGET_MIN_UNANSWERABLE,
            "gap_items": max(0, TARGET_MIN_ITEMS - n), "gap_unanswerable": max(0, TARGET_MIN_UNANSWERABLE - un)}


def freeze(questions: list[dict], vault: Path, version: str, owner: str, out_dir: Path = GOLDEN_DIR) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for q in sorted(questions, key=lambda q: str(q["id"])):
        rows.append({**q, "split": split_of(str(q["id"]))})
    (out_dir / "retrieval.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows) + "\n",
                                             encoding="utf-8")
    body = (out_dir / "retrieval.jsonl").read_bytes().replace(b"\r\n", b"\n")  # EOL-agnostic (checkout no Windows)
    manifest = {"version": version, "owner": owner, "corpus_hash": corpus_hash(vault),
                "items_sha256": hashlib.sha256(body).hexdigest(), "split_salt": SPLIT_SALT,
                "coverage": coverage(questions)}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                           encoding="utf-8")
    return manifest


def load(out_dir: Path = GOLDEN_DIR, split: str | None = None) -> list[dict]:
    rows = [json.loads(ln) for ln in (Path(out_dir) / "retrieval.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def verify(vault: Path, out_dir: Path = GOLDEN_DIR) -> dict:
    """Raise CorpusMismatch if the vault or the items drifted from the frozen manifest."""
    out_dir = Path(out_dir)
    m = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256((out_dir / "retrieval.jsonl").read_bytes().replace(b"\r\n", b"\n")).hexdigest() != m["items_sha256"]:
        raise CorpusMismatch("golden items were edited after freezing; bump the version and re-freeze")
    got = corpus_hash(vault)
    if got != m["corpus_hash"]:
        raise CorpusMismatch(f"corpus hash {got[:12]} != frozen {m['corpus_hash'][:12]}; "
                             "numbers from this golden set are not comparable on this corpus")
    return m
