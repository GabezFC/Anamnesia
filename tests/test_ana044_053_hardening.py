"""ANA-044..053 hardening regressions."""
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.state import STATE
from app.services import hardening
from app.memory_store.store import scan_secrets

ROOT = Path(__file__).resolve().parents[1]


# -- ANA-044 --------------------------------------------------------------------------------------
def test_access_log_has_no_query_string():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", "/memory/search?q=segredo+do+cliente", "1.1", 200), None)
    hardening.AccessLogRedactor().filter(rec)
    assert "segredo" not in rec.getMessage() and "/memory/search" in rec.getMessage()


def test_info_logs_scrub_absolute_paths(caplog):
    lg = logging.getLogger("anamnesia.test044")
    f = hardening.PathScrubFilter()
    lg.addFilter(f)
    rec = lg.makeRecord("anamnesia.test044", logging.INFO, "", 0, "vault em %s", ("C:\\Data\\fulano\\Cerebro\\x.md",), None)
    f.filter(rec)
    assert "fulano" not in rec.getMessage()


# -- ANA-045 --------------------------------------------------------------------------------------
def test_system_info_redacted_for_lan(monkeypatch, tiny_vault, tmp_path):
    from app.gateway.memory_gateway import MemoryGateway
    from app.main import app
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig
    rc = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bc = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False)
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc)
    monkeypatch.setattr(STATE, "gateway", gw)
    monkeypatch.setenv("MG_REDACT_PATHS", "always")
    c = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    r = c.get("/system/info")
    assert r.status_code == 200
    assert str(tiny_vault) not in r.text and str(tiny_vault).replace("\\", "\\\\") not in r.text
    monkeypatch.setenv("MG_REDACT_PATHS", "off")
    assert str(tiny_vault).replace("\\", "\\\\") in c.get("/system/info").text


def test_redact_path_relative():
    assert hardening.redact_path("C:/a/b/c.md", "C:/a") == "b/c.md"
    assert hardening.redact_path("D:/zzz/x.md", "C:/a") == "x.md"


# -- ANA-046 --------------------------------------------------------------------------------------
def test_pty_env_never_has_local_token():
    from app.terminals.manager import build_env
    env = build_env(("MG_LOCAL_TOKEN", "OPENAI_API_KEY"), {"PATH": "x", "MG_LOCAL_TOKEN": "t", "OPENAI_API_KEY": "k"})
    assert "MG_LOCAL_TOKEN" not in env and env["OPENAI_API_KEY"] == "k"


def test_pty_env_no_home_option(monkeypatch):
    from app.terminals.manager import build_env
    monkeypatch.setenv("MG_PTY_NO_HOME", "1")
    env = build_env((), {"PATH": "x", "HOME": "/h", "USERPROFILE": "C:/u"})
    assert "HOME" not in env and "USERPROFILE" not in env


# -- ANA-047 --------------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["http://169.254.169.254/latest", "http://metadata.google.internal/", "file:///etc/passwd",
                                 "ftp://x", "http://10.0.0.5:11434"])
def test_provider_url_rejected(url, monkeypatch):
    monkeypatch.delenv("MG_ALLOW_REMOTE_PROVIDERS", raising=False)
    with pytest.raises(hardening.ProviderURLError):
        hardening.validate_provider_url(url)


def test_provider_url_ok_and_opt_in(monkeypatch):
    assert hardening.validate_provider_url("http://localhost:11434") == "http://localhost:11434"
    monkeypatch.setenv("MG_ALLOW_REMOTE_PROVIDERS", "1")
    assert hardening.validate_provider_url("https://api.example.com/v1")
    with pytest.raises(hardening.ProviderURLError):  # metadata is refused even with opt-in
        hardening.validate_provider_url("http://169.254.169.254")


def test_agents_config_falls_back(monkeypatch):
    from config.agents import AgentsConfig
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://169.254.169.254")
    assert AgentsConfig().ollama_base_url == "http://localhost:11434"


# -- ANA-048 --------------------------------------------------------------------------------------
def test_publication_scan_clean_tree():
    out = subprocess.run([sys.executable, str(ROOT / "scripts/scan_publication_safety.py"), "--no-history",
                          "--fail-on-findings", "--out-dir", str(ROOT / "reports" / "_t048")],
                         capture_output=True, text=True, cwd=ROOT)
    assert out.returncode == 0, out.stdout[-800:]
    md = (ROOT / "reports" / "_t048" / "publication_safety_report.md").read_text(encoding="utf-8")
    assert str(ROOT) not in md


# -- ANA-049 --------------------------------------------------------------------------------------
def test_job_limits_defaults_and_off(monkeypatch):
    assert hardening.job_limits() == (4096, 256)
    monkeypatch.setenv("MG_PTY_LIMITS", "off")
    assert hardening.job_limits() is None


def test_agent_sessions_expire_sooner():
    assert hardening.agent_idle_seconds(12 * 3600) == 2 * 3600
    assert hardening.agent_idle_seconds(10) == 10


# -- ANA-050 --------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "AccountKey=abcdefghijklmnopqrstuvwxyz0123456789ABCD==", "postgres://admin:hunter22pw@db.local/x",
    '{"type": "service_account", "x": 1}', "//registry.npmjs.org/:_authToken=npm_abcdefghij1234",
    "\uff53\uff4b-abcdefghijklmnopqrstuvwx", "sk-abc\u200bdefghijklmnopqrstuvwx",
    "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5",
])
def test_scan_secrets_recall(text):
    assert scan_secrets(text)


@pytest.mark.parametrize("text", ["O gateway usa FTS5 para busca lexical", "commit 0a5a779b4c1e8f2d3a4b5c6d7e8f9a0b1c2d3e4f",
                                  "123e4567-e89b-12d3-a456-426614174000"])
def test_scan_secrets_precision(text):
    assert scan_secrets(text) == []


# -- ANA-051 --------------------------------------------------------------------------------------
def test_open_confined_inside_and_outside(tmp_path):
    root = tmp_path / "v"
    root.mkdir()
    (root / "a.md").write_text("ok", encoding="utf-8")
    outside = tmp_path / "o.md"
    outside.write_text("no", encoding="utf-8")
    with hardening.open_confined(root / "a.md", root) as fh:
        assert fh.read() == b"ok"
    with pytest.raises(PermissionError):
        hardening.open_confined(outside, root)


@pytest.mark.skipif(os.name != "nt", reason="junction swap is a Windows scenario")
def test_open_confined_junction_race(tmp_path):
    root = tmp_path / "v"
    (root / "d").mkdir(parents=True)
    (root / "d" / "a.md").write_text("ok", encoding="utf-8")
    secret = tmp_path / "s"
    secret.mkdir()
    (secret / "a.md").write_text("SECRET", encoding="utf-8")
    p = root / "d" / "a.md"
    assert hardening.open_confined(p, root).read() == b"ok"  # resolve-time state is fine
    (root / "d" / "a.md").unlink()
    (root / "d").rmdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "d"), str(secret)], capture_output=True)
    if not (root / "d").exists():
        pytest.skip("mklink /J indisponivel")
    with pytest.raises(PermissionError):  # swapped between resolve and open
        hardening.open_confined(p, root)


# -- ANA-052 --------------------------------------------------------------------------------------
def test_no_pickle_in_repo():
    bad = []
    for base in ("app", "scripts", "config", "memory_gateway"):
        for f in (ROOT / base).rglob("*.py"):
            if "import pickle" in f.read_text(encoding="utf-8", errors="ignore"):
                bad.append(str(f.relative_to(ROOT)))
    assert not bad, bad


# -- ANA-053 --------------------------------------------------------------------------------------
def test_keyring_backend_and_audit(tmp_path, monkeypatch, caplog):
    from app.connections import secrets as sec
    store = {}

    class KR:
        def set_password(self, s, k, v): store[(s, k)] = v
        def get_password(self, s, k): return store.get((s, k))
        def delete_password(self, s, k): store.pop((s, k), None)

    monkeypatch.setenv("MG_SECRETS_BACKEND", "keyring")
    monkeypatch.setattr(sec, "_keyring", lambda: KR())
    monkeypatch.setattr(sec.security, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("TEST_KEY_053", raising=False)
    with caplog.at_level(logging.INFO, logger="anamnesia.secrets.audit"):
        sec.set_key("TEST_KEY_053", "valor-super-secreto-123456")
        monkeypatch.delenv("TEST_KEY_053", raising=False)
        assert sec.has_key("TEST_KEY_053")
        assert not (tmp_path / ".env").exists() or "valor-super" not in (tmp_path / ".env").read_text()
        assert sec.delete_key("TEST_KEY_053")
    assert "valor-super-secreto" not in caplog.text and "secret_set key=TEST_KEY_053" in caplog.text
