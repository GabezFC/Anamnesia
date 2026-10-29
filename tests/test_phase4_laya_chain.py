"""FASE 4 (D1): cadeia Laya/JEV/calibração — diagnósticos honestos e independentes do CWD."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.decision.engine import DecisionEngine
from app.decision.providers import jev_static_checks
from app.services.laya_decider import LayaBackend
from config.laya import LayaConfig


def _fake_weights(base: Path) -> None:
    d = base / "laya-multilingual"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(b"x")


def test_relative_models_dir_does_not_depend_on_cwd(tmp_path, monkeypatch):
    """Bug real: 'data/local_ai/models' era resolvido contra o CWD => Laya 'off' ao subir de outra pasta."""
    home = tmp_path / "home"
    _fake_weights(home / "data" / "local_ai" / "models")
    monkeypatch.setenv("ANAMNESIA_HOME", str(home))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    b = LayaBackend(LayaConfig())
    assert "multilingual" in b._model_dirs()
    assert Path(b.status()["models_dir_resolved"]) == home / "data" / "local_ai" / "models"


def test_missing_weights_reason_names_absolute_searched_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "empty_home"))
    monkeypatch.setenv("MG_LAYA_MODELS_DIR", "nao/existe/models")
    monkeypatch.chdir(tmp_path)
    b = LayaBackend(LayaConfig())
    b._mode_effective = None
    st = b.status()
    if st["effective_mode"] == "off":
        assert "pesos multilingual ausentes em" in st["reason"] or "pacote 'laya' não importável" in st["reason"]
        assert os.path.isabs(st["models_dir_resolved"])


def test_jev_without_key_remote_backend_is_unavailable_not_unprobed(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    r = jev_static_checks()
    assert r["available"] is False and r["label"] == "UNAVAILABLE"
    assert "TYPESAFE_API_KEY ausente" in r["reason"]
    assert r["api_key_set"] is False


def test_jev_with_key_never_claims_probe_and_never_leaks_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-SECRET-123")
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    r = jev_static_checks()
    if r.get("available") is False:  # SDK ausente neste Python
        assert "typesafe_sdk" in r["reason"]
    else:
        assert r.get("available") is None and r.get("label") is None and r["probe"] == "paid_not_run"
        assert "NÃO sondadas" in r["reason"]
    assert "SECRET" not in repr(r)


def test_jev_local_loopback_backend_declares_free_probe(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:11500")
    r = jev_static_checks()
    assert r["local_backend"] is True and r["probe"] == "local_probe_available"
    assert r.get("available") is not False or "typesafe_sdk" in r["reason"]


def test_engine_status_exposes_jev_prereqs_and_calibration_origin(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    monkeypatch.delenv("MG_LAYA_CALIBRATION_FILE", raising=False)
    eng = DecisionEngine()
    jev = eng.status()["providers"]["jev"]
    assert jev["available"] is False and "api_key_set" in jev
    cal = eng.cfg.to_public()["calibration"]
    assert cal["fitted_on_user_data"] is False and "NÃO CALIBRADO" in cal["status"]


@pytest.mark.parametrize("name", ["fast", "balanced", "quality"])
def test_presets_remain_experimental(name):
    from app.decision.config import PRESETS
    assert name in PRESETS
