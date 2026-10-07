"""Browser E2E of the Workspace (real server + real PTY + Chromium). SKIPPED unless ANAMNESIA_E2E=1.

    ANAMNESIA_E2E=1 E2E_SERVER_PYTHON=<venv python with pywinpty> <python with playwright> -m pytest tests/e2e -q

Reuses scripts/e2e_workspace.py (same helpers/steps). Never collected as runnable in CI: no env var,
no playwright => skip.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ANAMNESIA_E2E") != "1", reason="set ANAMNESIA_E2E=1 to run browser E2E")

pytest.importorskip("playwright.sync_api")

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "e2e_workspace.py"


def _load():
    spec = importlib.util.spec_from_file_location("e2e_workspace", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def steps(tmp_path_factory):
    mod = _load()
    return mod.run_all(out=tmp_path_factory.mktemp("e2e"), keep_going=True)


def test_every_step_passes(steps):
    failed = [f"{s.name}: {s.evidence}" for s in steps if s.status == "failed"]
    assert not failed, "\n".join(failed)


def test_ran_all_steps(steps):
    mod = _load()
    assert len(steps) == len(mod.STEPS) + 1
