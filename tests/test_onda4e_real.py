"""Onda 4e: registry fill from OpenRouter /models (offline, fake payload), registry state, report freshness."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / ("experiments" if name == "analyze_onda4e" else ".") / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


YAML = """version: 1
models:
  - id: or-a
    provider: openrouter
    model: x/a
    tier: 1
    context_window: null
    capabilities: [code]
    effort_supported: false
    price: null   # comment
    local: false
    verified: false
  - id: openai-small
    provider: openai
    model: gpt-4o-mini
    tier: 1
    context_window: null
    capabilities: [code]
    effort_supported: false
    price: null
    local: false
    verified: false
"""


def test_fill_openrouter_only_touches_openrouter_entries(tmp_path):
    vr = _load("verify_registry")
    from app.routing.registry import load_registry
    p = tmp_path / "m.yaml"
    p.write_text(YAML, encoding="utf-8", newline="")
    reg = load_registry(p)
    models = [{"id": "x/a", "context_length": 8192, "pricing": {"prompt": "0.0000005", "completion": "0.000002"}},
              {"id": "gpt-4o-mini", "context_length": 1, "pricing": {"prompt": "0", "completion": "0"}}]
    new, rep = vr.fill_openrouter(YAML, reg, models, "https://openrouter.ai/api/v1/models", "2026-10-12")
    assert {r["field"] for r in rep} == {"context_window", "price"} and all(r["id"] == "or-a" for r in rep)
    p.write_text(new, encoding="utf-8", newline="")
    reg2 = load_registry(p)
    a = reg2.get("or-a")
    assert a.context_window == 8192 and a.price.input == 0.5 and a.price.output == 2.0
    assert reg2.get("openai-small").price is None and reg2.get("openai-small").context_window is None
    # idempotent: second pass finds nothing left to fill
    again, rep2 = vr.fill_openrouter(new, reg2, models, "https://openrouter.ai/api/v1/models", "2026-10-12")
    assert again == new and rep2 == []


def test_fill_openrouter_skips_missing_or_bad_data():
    vr = _load("verify_registry")
    from app.routing.registry import load_registry
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "m.yaml"
        p.write_text(YAML, encoding="utf-8", newline="")
        reg = load_registry(p)
    new, rep = vr.fill_openrouter(YAML, reg, [{"id": "x/a", "context_length": None, "pricing": {"prompt": "?"}}], "u", "2026-10-12")
    assert new == YAML and rep == []


def test_registry_openrouter_entries_verified_with_real_price():
    from app.routing.registry import load_registry
    reg = load_registry()
    ors = [m for m in reg.models if m.provider == "openrouter"]
    assert len(ors) >= 4
    for m in ors:
        assert m.verified and m.context_window and m.price and m.price.source_url.startswith("https://openrouter.ai/")
        assert m.price.checked_at


def test_openrouter_invalid_model_400_is_model_not_found():
    from app.adapters.models.errors import kind_from_status
    assert kind_from_status(400, "openai/zzz is not a valid model ID") == "model_not_found"


@pytest.mark.skipif(not (ROOT / "data" / "onda4e_bench.json").exists(), reason="raw run data is gitignored")
def test_real_report_is_fresh():
    an = _load("analyze_onda4e")
    if not an.OUT_MD.exists():  # local-only report (data/reports-out/, ignored by Git): generate with --write
        pytest.skip("data/reports-out/ONDA4_ROUTING_REAL.md absent: run scripts/experiments/analyze_onda4e.py --write")
    assert an.main(["--check"]) == 0


def test_real_report_has_no_secret_shapes():
    import re
    for f in ("ONDA4_ROUTING_REAL.md", "ONDA4_ROUTING_REAL.json"):
        p = ROOT / "data" / "reports-out" / f
        if p.exists():
            assert not re.search(r"sk-or-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{20,}", p.read_text(encoding="utf-8"))
