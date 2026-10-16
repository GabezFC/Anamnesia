"""ANAM-034/035: IA local (runtimes Colibri/Ollama, LocalProvider, download). Tudo com fakes; sem rede, sem Colibri real."""
import hashlib
import json
import os

import httpx
import pytest

from app.services.local_ai import (CmdResult, ColibriRuntime, DownloadError, LocalProvider, ModelBlocked, OllamaRuntime,
                                   RuntimeError_, download_file, ensure_model_allowed, hf_resolve_url, parse_json_tolerant,
                                   safe_join)
from app.services.local_ai import download as dl

COMMERCIAL_OK = "qwen3.5-9b"   # apache-2.0 VERIFIED no catalogo


# ---------------------------------------------------------------- parser
def test_parse_tolerant():
    assert parse_json_tolerant('banner\n{"a": 1}\ntrailer') == {"a": 1}
    assert parse_json_tolerant("\x1b[32mok\x1b[0m [1,2]") == [1, 2]
    for bad in ("", "   ", "not json", None, 5, "{broken"):
        assert parse_json_tolerant(bad) is None


# ---------------------------------------------------------------- colibri
@pytest.fixture
def colibri_home(tmp_path):
    launcher = tmp_path / "coli"
    launcher.write_text("# fake")
    (tmp_path / "setup.json").write_text(json.dumps({
        "status": "ready", "model": {"id": COMMERCIAL_OK, "name": "Fake"}, "model_dir": str(tmp_path / "m"),
        "launcher": str(launcher), "backend": "vulkan", "env": {"COLI_VULKAN": "1"}, "port": 8000}))
    (tmp_path / "install-state.json").write_text(json.dumps({"phase": "ready"}))
    return tmp_path


class FakeRunner:
    def __init__(self, outputs=None):
        self.calls, self.outputs = [], outputs or {}

    def __call__(self, cmd, timeout, env):
        self.calls.append((cmd, timeout, env))
        for sub, res in self.outputs.items():
            if sub in cmd:
                return res
        return CmdResult(0, "{}")


class FakeProc:
    pid = 4242

    def __init__(self):
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True


def test_colibri_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("COLI_SETUP_HOME", str(tmp_path / "nada"))
    rt = ColibriRuntime(home=str(tmp_path / "vazio"), runner=FakeRunner())
    assert rt.detect()["installed"] is False
    assert rt.status().state == "not_installed"
    with pytest.raises(RuntimeError_):
        rt.start()


def test_colibri_discovery_env_and_status(colibri_home, monkeypatch):
    monkeypatch.setenv("MG_COLIBRI_HOME", str(colibri_home))
    runner = FakeRunner({"status": CmdResult(0, 'noise {"configured": true, "setup": {"ready": true}} tail')})
    rt = ColibriRuntime(runner=runner, http=lambda *a: (None, None))
    d = rt.detect()
    assert d["installed"] and d["ready"] and d["backend"] == "vulkan"
    st = rt.status()
    assert st.state == "stopped" and st.details["coli_status"]["configured"] is True
    cmd, timeout, env = runner.calls[0]
    assert cmd[2:] == ["status", "--json"] and timeout == 30.0 and "COLI_API_KEY" not in env


@pytest.mark.parametrize("res", [CmdResult(0, "garbage"), CmdResult(None, timed_out=True, error="t"),
                                 CmdResult(None, error="OSError: x"), CmdResult(1, "", "boom")])
def test_colibri_plan_doctor_tolerate_bad_output(colibri_home, res):
    rt = ColibriRuntime(home=str(colibri_home), runner=FakeRunner({"plan": res, "doctor": res}))
    assert rt.plan(None, 16, 4096)["ok"] is False
    assert rt.doctor()["ok"] is False


def test_colibri_plan_and_doctor_ok(colibri_home):
    runner = FakeRunner({"plan": CmdResult(0, '{"fits": true}'), "doctor": CmdResult(0, '{"status": "error"}')})
    rt = ColibriRuntime(home=str(colibri_home), runner=runner)
    p = rt.plan(None, 16.9, 8192)
    assert p == {"ok": True, "source": "coli plan", "plan": {"fits": True}}
    argv = runner.calls[0][0]
    assert argv[2:5] == ["plan", "--json", "--model"] and argv[-4:] == ["--ram", "16", "--ctx", "8192"]
    assert rt.doctor()["ok"] is False and rt.doctor()["report_status"] == "error"


@pytest.mark.parametrize("port", [8000, 11434, 80, 70000, "x", None])
def test_colibri_rejects_bad_ports(port):
    with pytest.raises(RuntimeError_):
        ColibriRuntime(port=port)


def test_colibri_start_stop(colibri_home):
    spawned = []
    proc = FakeProc()
    runner = FakeRunner({"stop": CmdResult(0, "stopped")})
    rt = ColibriRuntime(home=str(colibri_home), runner=runner, http=lambda *a: (None, None),
                        spawner=lambda cmd, env, cwd: spawned.append((cmd, env)) or proc,
                        key_via="arg", key_factory=lambda: "K" * 43, port_free=lambda h, p: True)
    st = rt.start()
    cmd, env = spawned[0]
    assert st.state == "loading" and rt.base_url() == "http://127.0.0.1:11500/v1"
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1" and cmd[cmd.index("--port") + 1] == "11500"
    assert cmd[cmd.index("--api-key") + 1] == "K" * 43 and "8000" not in cmd
    assert env["COLI_VULKAN"] == "1"
    assert rt.api_key() == "K" * 43 and "K" * 43 not in json.dumps(st.to_dict())
    assert rt.health()["state"] == "loading"
    out = rt.stop()
    assert runner.calls[-1][0][-3:] == ["stop", "--port", "11500"] and out["terminated_child"] and rt.api_key() is None


def test_colibri_start_env_key_and_busy_port(colibri_home):
    spawned = []
    rt = ColibriRuntime(home=str(colibri_home), spawner=lambda c, e, w: spawned.append((c, e)) or FakeProc(),
                        key_via="env", key_factory=lambda: "S", port_free=lambda h, p: True)
    rt.start()
    assert "--api-key" not in spawned[0][0] and spawned[0][1]["COLI_API_KEY"] == "S"
    busy = ColibriRuntime(home=str(colibri_home), port_free=lambda h, p: False)
    with pytest.raises(RuntimeError_) as e:
        busy.start()
    assert e.value.code == "port_busy"


def test_colibri_health_ready(colibri_home):
    rt = ColibriRuntime(home=str(colibri_home), http=lambda *a: (200, {"status": "ok"}))
    assert rt.health()["ok"] is True


def test_colibri_policy_blocks_unverified_in_commercial(colibri_home, tmp_path):
    setup = json.loads((colibri_home / "setup.json").read_text())
    setup["model"] = {"id": "modelo-desconhecido", "name": "X"}
    (colibri_home / "setup.json").write_text(json.dumps(setup))
    rt = ColibriRuntime(home=str(colibri_home), spawner=lambda *a: FakeProc(), port_free=lambda h, p: True)
    with pytest.raises(ModelBlocked):
        rt.start(mode="comercial")
    assert rt.start(mode="pessoal").state == "loading"      # modo nao comercial deixa passar


# ---------------------------------------------------------------- ollama
class FakeOllamaHttp:
    def __init__(self, up=True):
        self.up, self.calls = up, []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, body))
        if not self.up:
            return None, None
        path = url.split("11434", 1)[1]
        if path == "/api/version":
            return 200, {"version": "0.34.2"}
        if path == "/api/tags":
            return 200, {"models": [{"name": "qwen3:8b", "model": "qwen3:8b", "size": 5_200_000_000}]}
        if path == "/api/ps":
            return 200, {"models": [{"name": "qwen3:8b"}]}
        if path == "/api/generate":
            return 200, {"done": True}
        return 404, None


def test_ollama_status_plan_stop():
    http = FakeOllamaHttp()
    rt = OllamaRuntime(http=http, which=lambda n: "C:/ollama.exe")
    st = rt.status()
    assert st.state == "ready" and st.details["models"] == ["qwen3:8b"] and st.model == "qwen3:8b"
    assert rt.base_url() == "http://127.0.0.1:11434/v1" and rt.health()["ok"]
    p = rt.plan("qwen3:8b", 16, 4096)
    assert p["estimated"] is True and p["estimate"]["weights_gb"] == 5.2 and p["estimate"]["fits"] is True
    assert rt.plan("nao-existe", 16, 4096)["ok"] is False
    out = rt.stop()
    assert out["unloaded"] == ["qwen3:8b"]
    assert ("POST", "http://127.0.0.1:11434/api/generate", {"model": "qwen3:8b", "keep_alive": 0}) in http.calls
    assert not any("/api/pull" in c[1] for c in http.calls)


def test_ollama_down_and_missing():
    assert OllamaRuntime(http=FakeOllamaHttp(up=False), which=lambda n: None).status().state == "not_installed"
    assert OllamaRuntime(http=FakeOllamaHttp(up=False), which=lambda n: "x").status().state == "stopped"
    spawned = []
    rt = OllamaRuntime(http=FakeOllamaHttp(up=False), which=lambda n: "ollama",
                       spawner=lambda c, e, w: spawned.append(c) or FakeProc())
    assert rt.start().state == "loading" and spawned == [["ollama", "serve"]]
    with pytest.raises(RuntimeError_):
        OllamaRuntime(url="http://example.com:11434")


def test_ollama_start_loads_model_with_policy():
    http = FakeOllamaHttp()
    rt = OllamaRuntime(http=http, which=lambda n: "o")
    with pytest.raises(ModelBlocked):
        rt.start("qwen3:8b", mode="comercial")
    rt.start("qwen3:8b", mode="comercial", aliases={"qwen3:8b": COMMERCIAL_OK})
    assert ("POST", "http://127.0.0.1:11434/api/generate", {"model": "qwen3:8b", "keep_alive": "5m"}) in http.calls


# ---------------------------------------------------------------- policy
def test_policy():
    assert ensure_model_allowed(COMMERCIAL_OK, "comercial")["catalog"]["id"] == COMMERCIAL_OK
    with pytest.raises(ModelBlocked):
        ensure_model_allowed("x/unknown", "comercial")
    assert ensure_model_allowed("x/unknown", "pessoal")["catalog"] is None


# ---------------------------------------------------------------- provider
class StubRuntime(ColibriRuntime):
    def __init__(self, url="http://127.0.0.1:11500/v1", key="sekret"):
        self._u, self._k = url, key
        self.name = "colibri"

    def base_url(self):
        return self._u

    def api_key(self):
        return self._k


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_provider_generate_and_cost():
    seen = {}

    def h(req):
        seen["auth"], seen["url"], seen["body"] = req.headers["authorization"], str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "oi"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    p = LocalProvider(StubRuntime(), COMMERCIAL_OK, client=_client(h), mode="comercial")
    r = p.generate("ola")
    assert r.answer == "oi" and (r.input_tokens, r.output_tokens) == (3, 1) and r.provider == "colibri"
    assert seen["auth"] == "Bearer sekret" and seen["url"].endswith("/v1/chat/completions")
    assert p.count_tokens("hello world")["estimated"] is True
    assert p.estimate_cost(100, 100)["api_cost_usd"] == 0.0


def test_provider_stream():
    sse = ('data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: {"choices":[{"delta":{}}]}\n\n'
           'data: garbage\n\ndata: {"choices":[{"delta":{"content":"b"}}]}\n\ndata: [DONE]\n\n')
    p = LocalProvider(StubRuntime(), COMMERCIAL_OK, client=_client(lambda r: httpx.Response(200, text=sse)), mode="comercial")
    assert list(p.stream("x")) == ["a", "b"]


def test_provider_errors_and_guards():
    p = LocalProvider(StubRuntime(), COMMERCIAL_OK, client=_client(lambda r: httpx.Response(500, text="x")), mode="comercial")
    r = p.generate("x")
    assert r.answer is None and r.error
    remote = LocalProvider(StubRuntime(url="https://api.example.com/v1"), COMMERCIAL_OK, mode="comercial",
                           client=_client(lambda r: httpx.Response(200, json={})))
    assert "not_loopback" in remote.generate("x").error
    with pytest.raises(ModelBlocked):
        LocalProvider(StubRuntime(), "desconhecido", mode="comercial")
    assert LocalProvider(StubRuntime(), "desconhecido", mode="pessoal").policy["catalog"] is None


def test_provider_offline_allows_loopback(monkeypatch):
    monkeypatch.setenv("OFFLINE", "1")
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "y"}}]})
    p = LocalProvider(StubRuntime(), COMMERCIAL_OK, client=_client(lambda r: ok), mode="comercial")
    assert p.generate("x").answer == "y"


# ---------------------------------------------------------------- download
DATA = os.urandom(5000)
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://huggingface.co/Qwen/Qwen3.5-9B/resolve/" + "a" * 40 + "/m.gguf"


class FakeServer:
    def __init__(self, data=DATA, honor_range=True, redirect_to=None, chunk=1000):
        self.data, self.honor, self.redirect, self.chunk, self.reqs = data, honor_range, redirect_to, chunk, []

    def __call__(self, url, headers):
        self.reqs.append((url, dict(headers)))
        if self.redirect and url == URL:
            return dl.Resp(302, {"location": self.redirect}, iter(()))
        start = int(headers["Range"][6:-1]) if "Range" in headers and self.honor else 0
        body = self.data[start:]
        chunks = (body[i:i + self.chunk] for i in range(0, len(body), self.chunk))
        if start:
            return dl.Resp(206, {"content-range": f"bytes {start}-{len(self.data) - 1}/{len(self.data)}"}, chunks)
        return dl.Resp(200, {}, chunks)


def _dl(tmp_path, **kw):
    args = dict(expected_sha256=SHA, expected_size=len(DATA), max_bytes=10_000, confirm=True,
                free_space=lambda p: 10**12, opener=FakeServer())
    args.update(kw)
    return download_file(URL, str(tmp_path), "m/m.gguf", **args)


def test_download_ok_and_idempotent(tmp_path):
    r = _dl(tmp_path)
    assert r["ok"] and open(r["path"], "rb").read() == DATA and not os.path.exists(r["path"] + ".part")
    assert _dl(tmp_path, opener=None)["skipped"] is True        # ja existe e confere: nao toca a rede


def test_download_requires_confirm_limit_hash(tmp_path):
    with pytest.raises(DownloadError, match="not_confirmed"):
        _dl(tmp_path, confirm=1)
    with pytest.raises(DownloadError, match="no_limit"):
        _dl(tmp_path, max_bytes=None)
    with pytest.raises(DownloadError, match="size_over_limit"):
        _dl(tmp_path, max_bytes=100)
    with pytest.raises(DownloadError, match="bad_sha256"):
        _dl(tmp_path, expected_sha256="abc")


def test_download_resume_with_range(tmp_path):
    final = tmp_path / "m" / "m.gguf"
    final.parent.mkdir()
    (tmp_path / "m" / "m.gguf.part").write_bytes(DATA[:2000])
    srv = FakeServer()
    r = _dl(tmp_path, opener=srv)
    assert srv.reqs[0][1] == {"Range": "bytes=2000-"} and r["resumed_from"] == 2000
    assert final.read_bytes() == DATA


def test_download_server_ignores_range_restarts(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "m.gguf.part").write_bytes(b"x" * 100)
    assert _dl(tmp_path, opener=FakeServer(honor_range=False))["resumed_from"] == 0
    assert (tmp_path / "m" / "m.gguf").read_bytes() == DATA


def test_download_sha_mismatch_never_renames(tmp_path):
    bad = bytes(len(DATA))
    with pytest.raises(DownloadError, match="sha256_mismatch"):
        _dl(tmp_path, opener=FakeServer(data=bad))
    assert not (tmp_path / "m" / "m.gguf").exists() and not (tmp_path / "m" / "m.gguf.part").exists()


def test_download_truncated_keeps_part_and_not_final(tmp_path):
    with pytest.raises(DownloadError, match="size_mismatch"):
        _dl(tmp_path, opener=FakeServer(data=DATA[:3000]))
    assert (tmp_path / "m" / "m.gguf.part").exists() and not (tmp_path / "m" / "m.gguf").exists()


def test_download_stream_longer_than_expected(tmp_path):
    with pytest.raises(DownloadError, match="size_over_limit"):
        _dl(tmp_path, opener=FakeServer(data=DATA + b"extra"))
    assert not (tmp_path / "m" / "m.gguf.part").exists()


def test_download_disk_space(tmp_path):
    with pytest.raises(DownloadError, match="no_space"):
        _dl(tmp_path, free_space=lambda p: 10)


@pytest.mark.parametrize("url", ["http://huggingface.co/a", "https://evil.com/a", "https://huggingface.co.evil.com/a",
                                 "https://user:pw@huggingface.co/a", "file:///etc/passwd"])
def test_download_host_allowlist(tmp_path, url):
    with pytest.raises(DownloadError):
        download_file(url, str(tmp_path), "a.bin", expected_sha256=SHA, expected_size=5000, max_bytes=9999,
                      confirm=True, opener=FakeServer())


def test_download_redirect_revalidated(tmp_path):
    ok = _dl(tmp_path, opener=FakeServer(redirect_to="https://cdn.huggingface.co/blob"))
    assert ok["ok"]
    with pytest.raises(DownloadError, match="host_not_allowed"):
        _dl(tmp_path / "o", opener=FakeServer(redirect_to="https://evil.com/blob"))


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/abs", "C:/x", "a\\b", "", ".", "a//b", "a/\0b"])
def test_safe_join_rejects(tmp_path, rel):
    with pytest.raises(DownloadError):
        safe_join(str(tmp_path), rel)


def test_safe_join_ok(tmp_path):
    assert safe_join(str(tmp_path), "a/b.bin").startswith(os.path.realpath(str(tmp_path)))


def test_hf_resolve_pins_revision():
    assert hf_resolve_url("Qwen/Qwen3.5-9B", "a" * 40, "m.gguf") == URL
    for bad in ("main", "a" * 39):
        with pytest.raises(DownloadError):
            hf_resolve_url("Qwen/Qwen3.5-9B", bad, "m.gguf")
    with pytest.raises(DownloadError):
        hf_resolve_url("Qwen/Qwen3.5-9B", "a" * 40, "../x")


def test_download_default_opener_refuses_network_in_pytest(tmp_path):
    with pytest.raises(DownloadError, match="network_in_tests"):
        _dl(tmp_path, opener=None)


def test_download_offline_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFLINE", "1")
    from app.services.offline import OfflineBlocked
    with pytest.raises(OfflineBlocked):
        _dl(tmp_path)
