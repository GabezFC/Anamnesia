"""CLI argument parsing (§7). No gateway, no vault: only argparse wiring is under test here."""
from __future__ import annotations

from app.cli.main import build_parser
from app.schemas.models import PIPELINES


def test_search_pipeline_accepts_every_pipeline_plus_auto():
    p = build_parser()
    for pipeline in ("auto", *PIPELINES):
        a = p.parse_args(["search", "pergunta", "--pipeline", pipeline])
        assert a.pipeline == pipeline
    a = p.parse_args(["search", "pergunta"])
    assert a.pipeline == "auto"  # MOL stays the default (§1)


def test_benchmark_pipeline_accepts_every_pipeline_including_the_cascade():
    p = build_parser()
    a = p.parse_args(["benchmark", "--pipeline", "graphify_jev_opt"])
    assert a.pipeline == ["graphify_jev_opt"]
    for pipeline in PIPELINES:
        p.parse_args(["benchmark", "--pipeline", pipeline])  # must not raise
