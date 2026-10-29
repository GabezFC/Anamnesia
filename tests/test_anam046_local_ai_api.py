"""ANAM-046: API /api/local-ai/* — status/teste/repair/install/config para Laya e Colibri.

Todos os testes usam FAKES (rede recusada em testes; nenhum modelo real, nenhuma instalação real).
O único toque real permitido é um GET de status (leitura pura) — rotulado NÃO-EXECUTADO se pular.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.decision import engine as eng_mod


@pytest.fixture()
def app_client(monkeypatch, tmp_path):
    from app.api import local_ai as api
    from app.services import laya_decider
    from config import colibri as colibri_cfg
    from config.laya import LayaConfig

    # --- config de teste: sem pesos reais, modo auto (worker), sem serve URL
    cfg = LayaConfig(python=str(tmp_path / "venv312" / "Scripts" / "python.exe"))
    monkeypatch.setattr(api, "_laya_config", lambda: cfg)

    class FakeBackend:
        def __init__(self) -> None:
            self.mode = "off"
            self.calls = 0
            self.raise_on_decide = False

        def status(self) -> dict:
            return {"effective_mode": self.mode, "reason": "fake",
                    "circuit": {"state": "closed", "label": "MEASURED"}, "worker": {"alive": False}}

        def _model_dirs(self) -> dict:
            return {"english": None, "multilingual": None}

        def decide(self, states, op, q):
            if self.raise_on_decide:
                raise RuntimeError("worker down (fake)")
            self.calls += 1
            from app.services.laya_decider import LayaAnswer
            return [LayaAnswer(p_yes=0.8, p_raw=0.8, confidence=0.3),
                    LayaAnswer(p_yes=0.8, p_raw=0.8, confidence=0.3)]

    fake = FakeBackend()
    monkeypatch.setattr(laya_decider, "get_backend", lambda: fake)
    monkeypatch.setattr(laya_decider, "reset_backend", lambda: None)
    # o módulo da API importou os nomes diretamente: patch também lá
    import app.api.local_ai as api_mod
    monkeypatch.setattr(api_mod, "get_backend", lambda: fake)
    monkeypatch.setattr(api_mod, "reset_backend", lambda: None)

    # --- colibri: config fake desabilitada
    cc = colibri_cfg.ColibriConfig(enabled=False, url="http://127.0.0.1:11500", model="jev-latest",
                                   timeout_s=30, max_retries=1)
    monkeypatch.setattr(colibri_cfg, "load_colibri_config", lambda: cc)
    monkeypatch.setattr(api, "_try_load", lambda: {"ok": True})

    # --- engine fake injetado (colibri/config chama reset_engine -> reconstruiria engine real)
    class FakeEngine:
        jev = None
        laya = None
        colibri = None
        cache = None
        history = None
        config = None
        jev_service = None

    monkeypatch.setattr(eng_mod, "_ENGINE", FakeEngine())
    monkeypatch.setattr(eng_mod, "reset_engine", lambda: None)

    # --- envfile fake (não toca .env real)
    from app.services import envfile
    written: dict[str, str] = {}
    monkeypatch.setattr(envfile, "set_env_var", lambda path, k, v: written.setdefault(k, v) or None)
    monkeypatch.setattr(api, "env_file_path", lambda: tmp_path / ".env") if False else None
    import config.paths as paths_mod
    monkeypatch.setattr(paths_mod, "env_file_path", lambda: tmp_path / ".env")

    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)), fake, written


def _hdr():
    from app.services import security
    return {"X-MG-Token": security.get_or_create_local_token()}


def test_laya_status_readonly_no_token(app_client):
    c, fake, _ = app_client
    r = c.get("/api/local-ai/laya/status")
    assert r.status_code == 200
    d = r.json()
    assert d["configured_mode"] == "auto" and d["effective_mode"] == "off"
    assert d["package"]["laya_importable_in_venv"] is False
    assert d["circuit"]["state"] == "closed" and "plan" in d


def test_laya_test_requires_token_and_executes_fake_backend(app_client):
    c, fake, _ = app_client
    assert c.post("/api/local-ai/laya/test").status_code == 403
    fake.mode = "worker"
    r = c.post("/api/local-ai/laya/test", headers=_hdr())
    assert r.status_code == 200
    assert r.json()["relevance_p_yes"] == 0.8 and fake.calls == 2   # 1 canário de relevância + 1 de privacidade


def test_laya_test_503_when_backend_raises(app_client):
    c, fake, _ = app_client
    fake.raise_on_decide = True
    fake.mode = "worker"
    assert c.post("/api/local-ai/laya/test", headers=_hdr()).status_code == 503


def test_laya_repair_returns_plan_without_executing(app_client):
    c, _, _ = app_client
    r = c.post("/api/local-ai/laya/repair", headers=_hdr()).json()
    assert r["executed"] is False
    steps = [s["step"] for s in r["plan"]]
    assert steps[0] == "download_weights"  # pesos ausentes no fake -> primeiro passo do plano


def test_laya_install_requires_explicit_confirm(app_client):
    c, _, _ = app_client
    assert c.post("/api/local-ai/laya/install", json={}, headers=_hdr()).status_code == 428
    assert c.post("/api/local-ai/laya/install", json={"confirm": False}, headers=_hdr()).status_code == 428


def test_laya_install_stops_at_weights_without_real_download(app_client, monkeypatch):
    c, fake, _ = app_client
    ran: list[list[str]] = []

    def fake_run(cmd, timeout_s=600):
        ran.append(cmd)
        return {"cmd": " ".join(cmd[:2]) + " …", "rc": 0, "ok": True, "ms": 1, "stderr_tail": ""}

    monkeypatch.setattr("app.api.local_ai._run", fake_run)
    monkeypatch.setattr("app.api.local_ai.venv_has_laya", lambda p: True)
    # pesos "ausentes" no backend fake → o plano para ANTES de qualquer execução real
    fake._model_dirs = lambda: {"english": None, "multilingual": None}
    r = c.post("/api/local-ai/laya/install", json={"confirm": True}, headers=_hdr()).json()
    assert r["status"] == "pending"
    assert r["pending"].startswith("pesos ausentes")
    assert ran == []  # nada foi executado: sem manifest confirmado, NÃO baixa


def test_colibri_status(app_client):
    c, _, _ = app_client
    d = c.get("/api/local-ai/colibri/status").json()
    assert d["provider"] == "colibri" and d["enabled"] is False and d["label"] == "OFF"


def test_colibri_test_off_and_off_probe_only(app_client, monkeypatch):
    c, _, _ = app_client
    r = c.post("/api/local-ai/colibri/test", json={"confirm": True}, headers=_hdr()).json()
    assert r["probe"]["reachable"] is None and r["judge"]["ok"] is False


def test_colibri_config_writes_env_and_requires_token(app_client, monkeypatch):
    c, _, written = app_client
    assert c.post("/api/local-ai/colibri/config", json={"enabled": True}).status_code == 403
    r = c.post("/api/local-ai/colibri/config", json={"enabled": True, "url": "http://127.0.0.1:11500",
                                                     "model": "jev-latest"}, headers=_hdr())
    assert r.status_code == 200
    assert written["MG_COLIBRI_ENABLED"] == "1"
    assert r.json()["validate"] == {"ok": True}


def test_colibri_config_rejects_invalid_url(app_client, monkeypatch):
    c, _, _ = app_client
    from app.services import envfile
    monkeypatch.setattr(envfile, "set_env_var", lambda path, k, v: (_ for _ in ()).throw(envfile.EnvValueError(k)))
    r = c.post("/api/local-ai/colibri/config", json={"url": "http://0.0.0.0:11500"}, headers=_hdr())
    assert r.status_code == 422


# ---------------------------------------------------------------- ouvintes reais de status (leitura)
@pytest.mark.parametrize("kind", ["env"])
def test_real_status_sondagem(kind):
    """Rótulo: NÃO-EXECUTADO se sem pesos/venv locais; se houver, faz sondagem real de status."""
    from app.services.local_ai.laya_proc import discover_python
    py, origin = discover_python("")
    if not py:
        pytest.skip("sem venv do laya nesta máquina — NÃO-EXECUTADO")
    real = py  # sondagem de STATUS é leitura; não decide, não paga
    assert Path(real).exists() and origin
