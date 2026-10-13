"""ANA-172 / 179 / 181: registry planned flag, verified requires window, offline verify_registry. No network."""
import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.routing import RegistryError, load_registry
from app.routing.answer import SUPPORTED_PROVIDERS as ANSWER_PROVIDERS
from app.routing.registry import SUPPORTED_PROVIDERS, ModelEntry, coverage_report

ROOT = Path(__file__).resolve().parents[1]
HEAD = "version: 1\nmodels:\n"


def _vr():
    spec = importlib.util.spec_from_file_location("verify_registry", ROOT / "scripts" / "verify_registry.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["verify_registry"] = mod
    spec.loader.exec_module(mod)
    return mod


def M(id, provider="ollama", tier=1, extra="", model="m"):
    return f"  - id: {id}\n    provider: {provider}\n    model: {model}\n    tier: {tier}\n" + extra


def write(tmp_path, body):
    p = tmp_path / "m.yaml"
    p.write_text(HEAD + body, encoding="utf-8")
    return p


def test_supported_providers_mirror_answer():
    assert tuple(SUPPORTED_PROVIDERS) == tuple(ANSWER_PROVIDERS)


def test_model_entry_planned_is_last_and_default_false():
    e = ModelEntry("a", "ollama", "a", 1, None, (), False, None, False, False)   # old positional form
    assert e.planned is False


def test_default_registry_marks_huggingface_nvidia_planned_and_not_usable():
    reg = load_registry()
    planned = {m.provider for m in reg.models if m.planned}
    assert planned == {"huggingface", "nvidia"}
    ids = {m.id for m in reg.eligible(capabilities=[])}
    assert not ids & {m.id for m in reg.models if m.planned}


def test_unsupported_provider_without_planned_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="planned"):
        load_registry(write(tmp_path, M("x", "huggingface")))
    reg = load_registry(write(tmp_path, M("x", "huggingface", extra="    planned: true\n")))
    assert reg.get("x").planned is True


def test_verified_requires_context_window(tmp_path):
    with pytest.raises(RegistryError, match="context_window"):
        load_registry(write(tmp_path, M("x", extra="    verified: true\n")))
    reg = load_registry(write(tmp_path, M("x", extra="    verified: true\n    context_window: 4096\n")))
    assert reg.get("x").verified


def test_planned_cannot_be_verified(tmp_path):
    with pytest.raises(RegistryError):
        load_registry(write(tmp_path, M("x", "nvidia", extra="    planned: true\n    verified: true\n    context_window: 8\n")))


def test_coverage_report_counts_honestly():
    r = coverage_report(load_registry())
    assert r["planned"] and r["with_price"] == 0 and r["with_price_pct"] == 0.0
    assert r["context_window_null_count"] == len(r["context_window_null"]) > 0
    assert r["considered"] == r["models_total"] - len(r["planned"])


def test_verify_offline_json_and_write_preserves_everything_else(tmp_path):
    vr = _vr()
    body = (M("a", "ollama", 1, "    context_window: 4096\n    verified: false   # stale\n    local: true\n", model="qwen3:8b")
            + M("b", "ollama", 1, "    verified: false\n    local: true\n", model="llama3")
            + M("c", "anthropic", 2, "    verified: false\n", model="claude-x")
            + M("d", "nvidia", 3, "    planned: true\n"))
    p = write(tmp_path, body)
    lists = tmp_path / "lists.json"
    lists.write_text(json.dumps({"ollama": ["qwen3:8b", "llama3:latest"]}), encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    assert vr.main(["--registry", str(p), "--offline", str(lists), "--write"]) == 0
    after = p.read_text(encoding="utf-8")
    reg = load_registry(p)
    assert reg.get("a").verified is True                    # id present + window set
    assert reg.get("b").verified is False                   # id present but window null -> NOT verified
    assert reg.get("c").verified is False                   # no list for anthropic -> untouched
    assert reg.get("d").planned
    assert after.count("\n") == before.count("\n")
    assert "context_window: 4096" in after
    a_block = after.split("id: a")[1].split("id: b")[0]
    assert "verified: true" in a_block and "# stale" not in a_block      # only the verified line changed
    assert after.replace("verified: true", "verified: false") == before.replace("   # stale", "")


def test_verify_never_marks_id_missing_from_list(tmp_path):
    vr = _vr()
    p = write(tmp_path, M("a", "ollama", 1, "    context_window: 10\n    verified: true\n", model="gone"))
    reg = load_registry(p)
    res = vr.verify(reg, {"ollama": ["other"]})
    assert res["models"][0]["status"] == "id_not_in_list" and res["models"][0]["set_verified"] is False


def test_verify_report_has_no_price_claims(tmp_path, capsys):
    vr = _vr()
    assert vr.main([]) == 0
    out = capsys.readouterr().out
    assert "with price: 0.0%" in out


class _Fake(BaseHTTPRequestHandler):
    seen_auth = []

    def do_GET(self):
        type(self).seen_auth.append(self.headers.get("Authorization"))
        body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_fake_server_list_models_loopback_no_credential():
    vr = _vr()
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        ids = vr.fetch_list("openai", f"http://127.0.0.1:{srv.server_port}")
    finally:
        srv.shutdown()
    assert ids == ["fake-model"] and _Fake.seen_auth == [None]


def test_remote_host_blocked_without_flag(monkeypatch):
    vr = _vr()
    monkeypatch.delenv("ANAMNESIA_ALLOW_NETWORK_TEST", raising=False)
    with pytest.raises(PermissionError):
        vr.fetch_list("openai", "https://api.example.com/v1")
    assert os.getenv("ANAMNESIA_ALLOW_NETWORK_TEST") is None


def test_dead_local_server_means_unknown_not_crash(tmp_path):
    vr = _vr()
    assert vr.main(["--base-url", "ollama=http://127.0.0.1:9"]) == 0
