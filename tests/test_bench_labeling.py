"""ANA-109: labelling export + Cohen kappa + JEV x human agreement (synthetic data only)."""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

from app.benchmark import labeling as L
from app.database.db import Database

ROOT = Path(__file__).resolve().parents[1]


def test_kappa_known_values():
    assert L.cohen_kappa(["a", "b"] * 5, ["a", "b"] * 5)["kappa"] == 1.0
    # po=0.7, pe=0.7*0.6+0.3*0.4=0.54 -> (0.7-0.54)/0.46 = 0.3478
    a = ["y"] * 25 + ["y"] * 10 + ["n"] * 5 + ["n"] * 10
    b = ["y"] * 25 + ["n"] * 10 + ["y"] * 5 + ["n"] * 10
    r = L.cohen_kappa(a, b)
    assert r["n"] == 50 and r["observed_agreement"] == 0.7
    assert r["kappa"] == pytest.approx(0.3478, abs=1e-4)
    assert L.cohen_kappa([], [])["kappa"] is None
    assert L.cohen_kappa(["y", "y"], ["y", "y"])["kappa"] is None  # pe=1: undefined
    with pytest.raises(ValueError):
        L.cohen_kappa(["y"], [])


def test_normalize_label():
    assert L.normalize_label("") is None and L.normalize_label(None) is None
    assert L.normalize_label(" Relevant ") == "relevant"
    assert L.normalize_label("false_negative") == "relevant"
    assert L.normalize_label("false_positive") == "not_relevant"
    with pytest.raises(ValueError):
        L.normalize_label("talvez")


def test_unknown_without_labels():
    r = L.jev_vs_human([])
    assert r["kappa"] is None and r["false_negative_rate"] == "UNKNOWN" and r["status"].startswith("UNKNOWN")


def test_jev_vs_human_fn_rate_and_flag():
    rows = ([{"jev_decision": "DROP", "human_label": "relevant"}] * 2
            + [{"jev_decision": "DROP", "human_label": "not_relevant"}] * 6
            + [{"jev_decision": "KEEP", "human_label": "relevant"}] * 8
            + [{"jev_decision": "REVIEW", "human_label": "not_relevant"}] * 4
            + [{"jev_decision": "UNJUDGED", "human_label": "relevant"}])  # ignored: judge silent
    r = L.jev_vs_human(rows)
    assert r["n_labelled"] == 20
    assert r["false_negative_rate"] == 0.25 and r["false_positive_rate"] == pytest.approx(0.3333, abs=1e-4)
    assert r["status"].startswith("UNRELIABLE")  # n=20 < 30
    assert L.jev_vs_human(rows * 2)["status"] == "OK"


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "b.db")
    for i, dec in enumerate(["KEEP", "DROP", "DROP", "REVIEW", "UNJUDGED", "DROP_FALLBACK"]):
        run = f"r{i % 2}"
        d._exec("INSERT OR IGNORE INTO runs (run_id, question_id, query, pipeline) VALUES (?,?,?,?)",
                (run, f"q{i % 2}", f"pergunta {i % 2}", "C"))
        d._exec("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
                (run, f"c{i}", f"n{i}.md", "sec", 1.0, 0.1 * i, 0.0, dec, 10))
    return d


def test_select_items_deterministic_and_filters_unjudged(db):
    a = L.select_items(db, n=10, golden_items=[{"id": "q0", "expected_sources": ["n1.md"]}])
    b = L.select_items(db, n=10, golden_items=[{"id": "q0", "expected_sources": ["n1.md"]}])
    assert a == b and len(a) == 5  # UNJUDGED excluded
    assert {i["jev_decision"] for i in a} == {"KEEP", "DROP", "REVIEW", "DROP_FALLBACK"}
    assert len(L.select_items(db, n=2)) == 2
    by = {i["candidate_id"]: i for i in a}
    # c2 -> run r0 -> question q0 (expected n1.md); its source n2.md is not expected; c1 -> r1 -> no golden
    assert by["c2"]["source_is_expected"] == 0 and by["c2"]["expected_sources"] == '["n1.md"]'
    assert by["c1"]["source_is_expected"] == "" and by["c1"]["expected_sources"] == ""
    assert all(i["human_label"] == "" for i in a)


def test_csv_roundtrip_and_validation(db, tmp_path):
    items = L.select_items(db, n=10)
    p = L.write_csv(items, tmp_path / "x.csv")
    assert L.read_labelled_csv(p) == []  # nothing labelled yet
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig", newline="")))
    rows[0]["human_label"] = "relevant"
    rows[1]["human_label"] = "not_relevant"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=L.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    got = L.read_labelled_csv(p)
    assert [g["human_label"] for g in got] == ["relevant", "not_relevant"]
    rows[2]["human_label"] = "xyz"
    with open(p, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=L.CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(ValueError, match="linha 4"):
        L.read_labelled_csv(p)


def test_cli_export_is_read_only(db, tmp_path):
    out = tmp_path / "o.csv"
    before = (tmp_path / "b.db").read_bytes()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_labeling_csv.py"), "export",
                        "--db", str(tmp_path / "b.db"), "--out", str(out), "--n", "4"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert len(list(csv.DictReader(open(out, encoding="utf-8-sig")))) == 4
    r2 = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_labeling_csv.py"), "score", "--csv", str(out)],
                        capture_output=True, text=True, cwd=ROOT)
    assert r2.returncode == 0 and "UNKNOWN" in r2.stdout
    assert (tmp_path / "b.db").read_bytes()[:16] == before[:16]  # mode=ro: still a valid, untouched sqlite file
