"""ANA-009 / ANA-011: frozen golden set, deterministic split, corpus-hash gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.benchmark import golden

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = json.loads((ROOT / "benchmark" / "synthetic_questions.json").read_text(encoding="utf-8"))


def test_split_is_deterministic_and_order_independent():
    a = golden.split_questions(QUESTIONS)
    b = golden.split_questions(list(reversed(QUESTIONS)))
    assert {k: [q["id"] for q in v] for k, v in a.items()} == {k: [q["id"] for q in v] for k, v in b.items()}


def test_split_is_partition_with_roughly_60_20_20():
    sp = golden.split_questions(QUESTIONS)
    assert sum(len(v) for v in sp.values()) == len(QUESTIONS)
    ids = [q["id"] for v in sp.values() for q in v]
    assert len(ids) == len(set(ids))
    n = len(QUESTIONS)
    assert abs(len(sp["train"]) / n - 0.6) < 0.12
    assert abs(len(sp["test"]) / n - 0.2) < 0.12


def test_adding_questions_never_moves_existing_ones():
    before = {q["id"]: golden.split_of(q["id"]) for q in QUESTIONS}
    after = {q["id"]: golden.split_of(q["id"]) for q in QUESTIONS + [{"id": "zz999"}]}
    assert all(after[k] == v for k, v in before.items())


def test_corpus_hash_changes_with_content(tmp_path):
    (tmp_path / "a.md").write_text("um", encoding="utf-8")
    h1 = golden.corpus_hash(tmp_path)
    (tmp_path / "a.md").write_text("dois", encoding="utf-8")
    assert golden.corpus_hash(tmp_path) != h1
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "x.md").write_text("ruido", encoding="utf-8")
    (tmp_path / "a.md").write_text("um", encoding="utf-8")
    assert golden.corpus_hash(tmp_path) == h1       # generated output does not count


def test_freeze_verify_and_drift(tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "n.md").write_text("conteudo", encoding="utf-8")
    out = tmp_path / "g"
    m = golden.freeze(QUESTIONS[:20], vault, "t1", "owner", out)
    assert m["version"] == "t1" and golden.verify(vault, out)["corpus_hash"] == m["corpus_hash"]
    assert {r["split"] for r in golden.load(out)} <= {"train", "val", "test"}
    (vault / "n.md").write_text("mudou", encoding="utf-8")
    with pytest.raises(golden.CorpusMismatch):
        golden.verify(vault, out)


def test_edited_items_are_detected(tmp_path):
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "n.md").write_text("x", encoding="utf-8")
    out = tmp_path / "g"
    golden.freeze(QUESTIONS[:5], vault, "t1", "o", out)
    f = out / "retrieval.jsonl"
    f.write_text(f.read_text(encoding="utf-8").replace('"split"', '"splat"', 1), encoding="utf-8")
    with pytest.raises(golden.CorpusMismatch):
        golden.verify(vault, out)


def test_repo_golden_matches_synthetic_vault():
    """CI gate: the committed golden set must still match data/synthetic_vault."""
    m = golden.verify(ROOT / "data" / "synthetic_vault")
    assert m["coverage"]["n"] == len(QUESTIONS)


def test_coverage_reports_gap_honestly():
    c = golden.coverage(QUESTIONS)
    assert c["n"] == len(QUESTIONS)
    assert c["meets_targets"] == (c["gap_items"] == 0 and c["gap_unanswerable"] == 0)
