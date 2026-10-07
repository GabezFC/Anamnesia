"""Shared helpers for orchestration tests (no network, no real models)."""
from __future__ import annotations

from app.orchestration.config import load_config, parse_config
from app.orchestration.launchers import FakeLauncher
from app.orchestration.orchestrator import Orchestrator
from app.routing import load_registry
from app.routing.registry import _parse_yaml
from pathlib import Path

HEAD = "version: 1\nmodels:\n"
PRICE = ("    price:\n      input: {i}\n      output: {o}\n"
         "      source_url: https://example.test/p\n      checked_at: 2026-10-06\n")


def M(id, tier, provider="anthropic", price=None, local=False):
    p = PRICE.format(i=price[0], o=price[1]) if price else "    price: null\n"
    return (f"  - id: {id}\n    provider: {provider}\n    model: m-{id}\n    tier: {tier}\n"
            f"    context_window: null\n    capabilities: [code]\n    effort_supported: false\n"
            f"    local: {str(local).lower()}\n" + p)


def make_registry(tmp_path, *entries, name="r.yaml"):
    p = tmp_path / name
    p.write_text(HEAD + "".join(entries), encoding="utf-8")
    return load_registry(p)


def three(tmp_path, price=True):
    pr = lambda a, b: (a, b) if price else None  # noqa: E731
    return make_registry(tmp_path, M("t1", 1, price=pr(1, 2)), M("t2", 2, price=pr(3, 6)),
                         M("t3", 3, price=pr(15, 30)))


def five(tmp_path):
    return make_registry(tmp_path, *[M(f"t{i}", i, price=(i, i)) for i in range(1, 6)])


def cfg(**limits):
    doc = _parse_yaml((Path(__file__).resolve().parents[1] / "config" / "orchestration.yaml").read_text("utf-8"))
    doc["limits"].update({"poll_interval_s": 0.01, "step_timeout_s": 5}, **limits)
    return parse_config(doc)


def orch(tmp_path, registry=None, launcher=None, sync=True, **limits):
    launcher = launcher or FakeLauncher(input_tokens=100, output_tokens=50)
    return Orchestrator(launcher, registry=registry or three(tmp_path), config=cfg(**limits), sync=sync), launcher


def project(tmp_path):
    d = tmp_path / "proj"
    d.mkdir(exist_ok=True)
    return d


__all__ = ["M", "make_registry", "three", "five", "cfg", "orch", "project", "load_config"]
