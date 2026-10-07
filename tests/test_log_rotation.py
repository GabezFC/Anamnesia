"""T0.4: logs stay bounded."""
from __future__ import annotations

from app.services import metrics


def test_jsonl_rotates_when_over_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "LOG_DIR", tmp_path)
    monkeypatch.setattr(metrics, "JSONL_MAX_BYTES", 200)
    for i in range(60):
        metrics.jsonl("benchmark", {"i": i, "pad": "x" * 20})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert "benchmark.jsonl" in files and "benchmark.jsonl.1" in files
    assert len(files) <= metrics.LOG_BACKUPS + 1  # never grows without bound


def test_rotation_keeps_newest_records_in_main_file(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "LOG_DIR", tmp_path)
    monkeypatch.setattr(metrics, "JSONL_MAX_BYTES", 200)
    for i in range(30):
        metrics.jsonl("jev", {"i": i, "pad": "y" * 20})
    assert '"i": 29' in (tmp_path / "jev.jsonl").read_text(encoding="utf-8")
