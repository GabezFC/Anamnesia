"""ANA-113: external corpus loader, integrity hash, per-corpus reports (synthetic fixtures)."""
import json

import pytest

from app.benchmark import external_corpus as X


def _make(d, name="ext", annotators=("A", "B"), labels_b=None):
    d.mkdir(parents=True, exist_ok=True)
    items = [
        {"id": "e1", "question": "q um", "answerable": True,
         "candidates": [{"source": "a.md", "labels": {"A": "relevant", "B": "relevant"}},
                        {"source": "b.md", "labels": {"A": "relevant", "B": "not_relevant"}}]},
        {"id": "e2", "question": "q dois", "answerable": True,
         "candidates": [{"source": "c.md", "labels": {"A": "relevant", "B": labels_b or "relevant"}},
                        {"source": "d.md", "labels": {"A": "not_relevant", "B": "not_relevant"}}]},
        {"id": "e3", "question": "sem resposta", "answerable": False, "candidates": []},
    ]
    (d / "items.jsonl").write_text("\n".join(json.dumps(i) for i in items) + "\n", encoding="utf-8")
    X.write_manifest(d, name=name, version="1", author="humano", author_kind="human", annotators=list(annotators))
    return d


def test_load_ok_and_adjudication(tmp_path):
    c = X.load(_make(tmp_path / "c"))
    assert len(c.items) == 3
    assert c.adjudicated_relevant(c.items[0]) == {"a.md"}  # b.md disagrees -> not consensus


def test_tamper_detected(tmp_path):
    d = _make(tmp_path / "c")
    p = d / "items.jsonl"
    p.write_text(p.read_text(encoding="utf-8").replace("q um", "q UM"), encoding="utf-8")
    with pytest.raises(X.CorpusIntegrityError, match="hash"):
        X.load(d)


def test_needs_two_annotators_and_valid_labels(tmp_path):
    with pytest.raises(X.CorpusIntegrityError, match="anotadores"):
        X.load(_make(tmp_path / "one", annotators=("A",)))
    with pytest.raises(X.CorpusIntegrityError, match="rótulo"):
        X.load(_make(tmp_path / "bad", labels_b="talvez"))
    with pytest.raises(X.CorpusIntegrityError):
        X.load(tmp_path / "missing")


def test_agreement_and_evaluate(tmp_path):
    c = X.load(_make(tmp_path / "c"))
    ag = X.annotator_agreement(c)
    assert ag["n"] == 4 and ag["observed_agreement"] == 0.75  # only b.md disagrees
    ranked = {"q um": ["x.md", "a.md"], "q dois": ["z.md"]}
    m = X.evaluate(c, lambda q: ranked[q], k=2)
    assert m["n_questions"] == 2 and m["hit@2"] == 0.5 and m["mrr"] == 0.25
    assert X.evaluate(c, lambda q: ranked[q], k=1)["hit@1"] == 0.0


def test_reports_are_per_corpus_never_aggregated(tmp_path):
    c1 = X.load(_make(tmp_path / "c1", name="alfa"))
    c2 = X.load(_make(tmp_path / "c2", name="beta"))
    rep = X.report_per_corpus([c1, c2], lambda q: ["a.md"])
    assert set(rep) == {"alfa@1", "beta@1"}
    assert not any("overall" in k.lower() or "total" in k.lower() for k in rep)
    with pytest.raises(ValueError):
        X.report_per_corpus([c1, c1])
