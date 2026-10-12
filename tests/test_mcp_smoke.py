"""ANA-082: the MCP stdio smoke runs offline, exits 0 and is fast (<30 s). marker: integration."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mcp_smoke.py"

_spec = importlib.util.spec_from_file_location("mcp_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(smoke)  # type: ignore[union-attr]


def test_validate_accepts_a_full_payload():
    payload = {"run_id": "r1", "context": "abc", "metrics": {"pipeline": "baseline"}, "sources": []}
    assert smoke.validate(["memory_search"], payload) == []


def test_validate_rejects_missing_tool_and_keys():
    problems = smoke.validate(["other"], {"context": 3, "metrics": []})
    joined = " | ".join(problems)
    assert "memory_search missing" in joined and "run_id" in joined
    assert "context is not a string" in joined and "metrics is not an object" in joined


def test_old_script_contract_was_broken_for_compact_payloads():
    """Regression: the compact (default) payload has no `pipeline`/`sources` at top level, which is what the
    original script indexed -> KeyError. validate() only demands what BOTH shapes carry."""
    compact = {"run_id": "r", "context": "c", "metrics": {"pipeline": "baseline"}}
    assert "pipeline" not in compact and "sources" not in compact
    assert smoke.validate(["memory_search"], compact) == []


@pytest.mark.integration
def test_mcp_smoke_script_exits_zero_fast_and_offline():
    t0 = time.perf_counter()
    r = subprocess.run([sys.executable, str(SCRIPT), "--timeout", "30"], capture_output=True, text=True,
                       cwd=ROOT, timeout=60)
    dt = time.perf_counter() - t0
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tools: ['memory_search'" in r.stdout
    assert '"pipeline": "baseline"' in r.stdout
    assert "context chars:" in r.stdout
    assert dt < 30, f"smoke took {dt:.1f}s (SUCCESS_METRIC: <30 s)"


@pytest.mark.integration
def test_mcp_smoke_unknown_pipeline_fails_loudly():
    r = subprocess.run([sys.executable, str(SCRIPT), "--pipeline", "does_not_exist", "--timeout", "30"],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode != 0
