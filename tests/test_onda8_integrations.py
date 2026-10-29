"""Onda 8 (ANA-214..224, ANA-238): integrations, MCP surface, Docker, CI, offline mode, local-first grade.

Hermetic: fake OpenAI-compatible / REST servers bind 127.0.0.1 only (allowed by the suite's network block);
agent CLIs are faked at the `_run`/`shutil.which` seam; MCP listings run in a subprocess (module-level config).
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.services import local_first, offline

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- fake servers
class _Fake:
    """Loopback HTTP server; `script(path, headers, body) -> (status, dict, extra_headers)`; records requests."""

    def __init__(self, script):
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                outer.requests.append({"method": self.command, "path": self.path,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                status, payload, extra = script(self.path, self.headers, body)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake_openai():
    def script(path, headers, body):
        if path.endswith("/models"):
            return 200, {"data": [{"id": "fake-model"}]}, None
        if path.endswith("/chat/completions"):
            if headers.get("Authorization") != "Bearer sk-fake":
                return 401, {"error": {"message": "bad key"}}, None
            if body and body["messages"][0]["content"] == "RATELIMIT":
                return 429, {"error": {"message": "slow down"}}, {"Retry-After": "7"}
            return 200, {"choices": [{"message": {"content": "pong"}}],
                         "usage": {"prompt_tokens": 11, "completion_tokens": 3}}, None
        return 404, {"error": "nope"}, None
    s = _Fake(script)
    yield s
    s.close()


# --------------------------------------------------------------------------- ANA-214
def test_openai_compatible_against_fake_server(fake_openai):
    from app.adapters.models.providers import OpenAICompatibleAdapter
    a = OpenAICompatibleAdapter(fake_openai.url + "/v1", "fake-model", "sk-fake", provider="vllm")
    assert a.list_models() == ["fake-model"]
    r = a.generate("ping", temperature=0.0, max_tokens=5)
    assert (r.answer, r.input_tokens, r.output_tokens, r.error) == ("pong", 11, 3, None)
    sent = fake_openai.requests[-1]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["body"]["model"] == "fake-model" and sent["body"]["max_tokens"] == 5
    assert sent["headers"]["authorization"] == "Bearer sk-fake"


def test_openai_compatible_error_taxonomy_against_fake_server(fake_openai):
    from app.adapters.models.providers import OpenAICompatibleAdapter
    bad = OpenAICompatibleAdapter(fake_openai.url + "/v1", "m", "wrong", provider="vllm").generate("x")
    assert bad.answer is None and bad.error_kind == "auth" and bad.status_code == 401
    rl = OpenAICompatibleAdapter(fake_openai.url + "/v1", "m", "sk-fake", provider="vllm").generate("RATELIMIT")
    assert rl.error_kind == "rate_limit" and rl.retry_after == 7


def test_generic_consumer_openai_compatible_against_fake_server(fake_openai, monkeypatch):
    from app.adapters.registry import GenericConsumer
    from config.agents import AgentsConfig
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "sk-fake")
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    cfg = AgentsConfig()
    cfg.openai_compat_base_url = fake_openai.url + "/v1"
    r = GenericConsumer("openai_compatible", "fake-model", cfg).generate("ping")
    assert r.answer == "pong" and r.provider == "openai_compatible"


# --------------------------------------------------------------------------- MCP listing helper (subprocess)
_LIST = r"""
import asyncio, json
from app.mcp import server as s
async def m():
    tools = await s.server.list_tools()
    res = await s.server.list_resources()
    tpl = await s.server.list_resource_templates()
    pr = await s.server.list_prompts()
    print("@@" + json.dumps({
        "tools": {t.name: {"ann": t.annotations.model_dump() if t.annotations else None,
                           "schema": t.output_schema} for t in tools},
        "resources": [str(r.uri) for r in res], "templates": [t.uri_template for t in tpl],
        "prompts": [p.name for p in pr]}))
asyncio.run(m())
"""


def _mcp_listing(tmp_home: Path, **env) -> dict:
    e = {k: v for k, v in os.environ.items() if not k.startswith("MG_MCP_")}
    e.update(env)
    e["PYTHONPATH"] = str(ROOT)
    e["ANAMNESIA_HOME"] = str(tmp_home)
    r = subprocess.run([sys.executable, "-c", _LIST], capture_output=True, text=True, cwd=ROOT, env=e, timeout=120)
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("@@")]
    assert line, r.stderr[-800:]
    return json.loads(line[-1][2:])


# --------------------------------------------------------------------------- ANA-215
def test_mcp_tools_have_annotations_and_output_schema(tmp_path):
    out = _mcp_listing(tmp_path, MG_MCP_TOOLSET="full", MG_MCP_SAVE="1")
    tools = out["tools"]
    assert "memory_search" in tools and "memory_get_run" in tools
    for name, t in tools.items():
        assert t["ann"] is not None, name
        assert t["ann"]["open_world_hint"] is False and t["ann"]["destructive_hint"] is False, name
    for ro in ("memory_search", "memory_get_run", "memory_stats", "memory_search_baseline"):
        assert tools[ro]["ann"]["read_only_hint"] is True, ro
    for rw in ("memory_benchmark", "memory_save"):
        if rw in tools:
            assert tools[rw]["ann"]["read_only_hint"] is False, rw
    props = tools["memory_search"]["schema"]["properties"]
    assert {"run_id", "context", "metrics"} <= set(props)
    assert tools["memory_search"]["schema"].get("additionalProperties") is True


# --------------------------------------------------------------------------- ANA-220
def test_mcp_resources_prompts_are_opt_in(tmp_path):
    default = _mcp_listing(tmp_path)
    assert default["resources"] == [] and default["templates"] == [] and default["prompts"] == []
    on = _mcp_listing(tmp_path, MG_MCP_RESOURCES="1")
    assert on["resources"] == ["anamnesia://about"] and on["templates"] == ["anamnesia://run/{run_id}"]
    assert on["prompts"] == ["recall_context"]
    assert list(on["tools"]) == ["memory_search"]   # opt-in does not change the tool surface


# --------------------------------------------------------------------------- ANA-216 / ANA-221 (static)
def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_dockerfile_base_image_pinned_by_digest_and_non_root():
    df = _read("Dockerfile")
    froms = [ln for ln in df.splitlines() if ln.startswith("FROM ")]
    assert len(froms) == 1 and re.fullmatch(r"FROM python:3\.\d+-slim@sha256:[0-9a-f]{64}", froms[0].strip()), froms
    assert re.search(r"^USER anamnesia$", df, re.M) and "ANAMNESIA_HOME=/data" in df and "HEALTHCHECK" in df


def test_compose_is_loopback_only_and_documents_bridge_and_auth():
    dc = _read("docker-compose.yml")
    # porta no host SEMPRE presa ao loopback; aceita a forma fixa ou a parametrizada (ANAMNESIA_PORT, padrão 8000)
    assert '"127.0.0.1:8000:8000"' in dc or '"127.0.0.1:${ANAMNESIA_PORT:-8000}:8000"' in dc
    assert not re.search(r'^\s*-\s*"?\$\{ANAMNESIA_PORT:-8000\}:8000"?\s*$', dc, re.M)  # sem bind em 0.0.0.0
    assert not re.search(r'^\s*-\s*"?(0\.0\.0\.0:)?8000:8000"?\s*$', dc, re.M)
    assert "MG_MCP_BRIDGE_URL" in dc and "MG_MCP_TOKEN" in dc and "MG_LOCAL_TOKEN" in dc
    assert "ANAMNESIA_ALLOW_REMOTE_TERMINALS" not in dc          # variavel morta removida (sem leitura no codigo)


# --------------------------------------------------------------------------- ANA-217 (+216 behaviour)
@pytest.fixture
def fake_rest():
    def script(path, headers, body):
        want = "Bearer s3cret-token"
        if headers.get("Authorization") != want and headers.get("X-MG-Token") is None and "needs-auth" in (body or {}).get("query", ""):
            return 401, {"detail": "token"}, None
        return 200, {"run_id": "r1", "context": "ctx", "metrics": {"pipeline": "baseline", "context_tokens": 5,
                                                                    "huge_internal": 1}, "sources": ["a.md"]}, None
    s = _Fake(script)
    yield s
    s.close()


def test_bridge_sends_bearer_only_when_configured(fake_rest, monkeypatch):
    from app.mcp.bridge import bridge_search
    monkeypatch.delenv("MG_MCP_TOKEN", raising=False)
    out = bridge_search({"query": "hello"}, url=fake_rest.url)
    assert out == {"run_id": "r1", "context": "ctx", "metrics": {"pipeline": "baseline", "context_tokens": 5}}
    assert "authorization" not in fake_rest.requests[-1]["headers"]
    monkeypatch.setenv("MG_MCP_TOKEN", "s3cret-token")
    bridge_search({"query": "hello"}, url=fake_rest.url)
    assert fake_rest.requests[-1]["headers"]["authorization"] == "Bearer s3cret-token"
    assert fake_rest.requests[-1]["path"] == "/memory/search"


def test_bridge_error_never_leaks_token(fake_rest, monkeypatch):
    from app.mcp.bridge import bridge_search
    monkeypatch.setenv("MG_MCP_TOKEN", "WRONG-TOKEN-123")
    with pytest.raises(RuntimeError) as ei:
        bridge_search({"query": "needs-auth"}, url=fake_rest.url)
    assert "401" in str(ei.value) and "WRONG-TOKEN-123" not in str(ei.value)
    with pytest.raises(RuntimeError) as ei2:
        bridge_search({"query": "x"}, url="http://127.0.0.1:9")   # closed port
    assert "WRONG-TOKEN-123" not in str(ei2.value) and "indisponível" in str(ei2.value)


def test_mcp_search_uses_bridge_when_configured(fake_rest, monkeypatch):
    from app.mcp import server
    monkeypatch.setattr(server, "BRIDGE_URL", fake_rest.url)
    out = server.memory_search("hello", max_results=3, client="codex")
    assert out["run_id"] == "r1" and out["context"] == "ctx"
    body = fake_rest.requests[-1]["body"]
    assert body["query"] == "hello" and body["max_results"] == 3 and body["client"] == "codex"


# --------------------------------------------------------------------------- ANA-219 agent adapters
class _Proc:
    def __init__(self, out=b"", err=b"", rc=0):
        self.stdout, self.stderr, self.returncode = out, err, rc


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """Replace the subprocess seam of app.adapters.agents.agents; returns the list of recorded calls."""
    from app.adapters.agents import agents as mod
    calls: list[dict] = []
    state = {"handler": lambda args, stdin: _Proc()}

    def fake_run(args, timeout, env=None, cwd=None, stdin=None):
        calls.append({"args": list(args), "stdin": stdin})
        return state["handler"](args, stdin)

    monkeypatch.setattr(mod, "_run", fake_run)
    monkeypatch.setattr(mod.shutil, "which", lambda b: f"/bin/{b}")
    monkeypatch.setattr(mod, "data_dir", lambda: tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return calls, state


def test_claude_code_adapter_available_and_generate(fake_cli):
    from app.adapters.agents.agents import ClaudeCodeAdapter
    calls, state = fake_cli

    def handler(args, stdin):
        if "--version" in args:
            return _Proc(b"2.1.0 (Claude Code)\n")
        if args[1:3] == ["auth", "status"]:
            return _Proc(b'{"loggedIn": true}')
        return _Proc(json.dumps({"subtype": "success", "result": "OK", "total_cost_usd": 0.01,
                                 "usage": {"input_tokens": 5, "cache_read_input_tokens": 3,
                                           "cache_creation_input_tokens": 2, "output_tokens": 4}}).encode())
    state["handler"] = handler
    a = ClaudeCodeAdapter()
    av = a.available()
    assert av["available"] is True and av["metrics"] == "FULL" and av["version"].startswith("2.1")
    r = a.generate("oi", model="sonnet")
    assert (r.answer, r.input_tokens, r.output_tokens, r.agent_cost, r.error) == ("OK", 10, 4, 0.01, None)
    gen = calls[-1]
    assert gen["stdin"] == "oi" and "--strict-mcp-config" in gen["args"] and "--no-session-persistence" in gen["args"]
    assert gen["args"][gen["args"].index("--model") + 1] == "sonnet"


def test_claude_code_adapter_unavailable_and_bad_output(fake_cli):
    from app.adapters.agents.agents import ClaudeCodeAdapter
    calls, state = fake_cli
    state["handler"] = lambda args, stdin: _Proc(b"", b"", 127) if "--version" in args else _Proc(b"not json")
    a = ClaudeCodeAdapter()
    assert a.available()["available"] is False
    r = a.generate("oi")
    assert r.answer is None and r.error


def test_codex_adapter_available_and_generate(fake_cli):
    from app.adapters.agents.agents import CodexAdapter
    calls, state = fake_cli
    out_files: list[Path] = []

    def handler(args, stdin):
        if "--version" in args:
            return _Proc(b"codex-cli 0.155.0\n")
        if args[1:3] == ["login", "status"]:
            return _Proc(b"Logged in using ChatGPT\n")
        o = Path(args[args.index("-o") + 1])
        o.write_text("resposta", encoding="utf-8")
        out_files.append(o)
        ev = [{"type": "turn.started"}, {"type": "turn.completed", "usage": {"input_tokens": 7, "output_tokens": 2}}]
        return _Proc("\n".join(json.dumps(e) for e in ev).encode() + b"\nlixo nao json\n")
    state["handler"] = handler
    a = CodexAdapter()
    assert a.available()["available"] is True and a.available()["metrics"] == "PARTIAL"
    r = a.generate("oi")
    assert (r.answer, r.input_tokens, r.output_tokens, r.error) == ("resposta", 7, 2, None)
    assert calls[-1]["args"][-1] == "-" and "read-only" in calls[-1]["args"] and calls[-1]["stdin"] == "oi"
    assert not out_files[0].exists()       # temp output removed


def test_codex_adapter_not_logged_in_and_nonzero_exit(fake_cli):
    from app.adapters.agents.agents import CodexAdapter
    calls, state = fake_cli
    state["handler"] = lambda args, stdin: (_Proc(b"codex 0.1\n") if "--version" in args
                                            else _Proc(b"Not logged in\n") if args[1:3] == ["login", "status"]
                                            else _Proc(b"", b"boom: quota", 1))
    a = CodexAdapter()
    av = a.available()
    assert av["available"] is False and av["reason"] == "não autenticado"
    r = a.generate("oi")
    assert r.answer is None and "quota" in (r.error or "")


def test_opencode_adapter_is_prepared_not_validated(fake_cli):
    from app.adapters.agents.agents import OpenCodeAdapter
    calls, state = fake_cli
    state["handler"] = lambda args, stdin: _Proc(b"1.18.0\n")
    a = OpenCodeAdapter()
    av = a.available()
    assert av["available"] is False and av["cli"] is True and av["metrics"] == "UNAVAILABLE"
    r = a.generate("oi")
    assert r.answer is None and "não validado" in r.error and not [c for c in calls if "-p" in c["args"]]


def test_generic_adapter_unknown_provider_and_dispatch(monkeypatch):
    from app.adapters.registry import GenericConsumer
    from app.adapters.models import providers
    with pytest.raises(ValueError):
        GenericConsumer("nope", "m")
    assert isinstance(GenericConsumer("ollama", "q").impl, providers.OllamaAdapter)
    assert isinstance(GenericConsumer("vllm", "q").impl, providers.VLLMAdapter)
    assert isinstance(GenericConsumer("openrouter", "q").impl, providers.OpenRouterAdapter)


# --------------------------------------------------------------------------- ANA-219 connections/snippets
def _conn(ctype="agent", snip=None):
    from app.connections.catalog import Connection
    return Connection("x", ctype, "X", "x", (), "", "available", snip)


def test_snippets_are_valid_in_their_formats():
    from app.connections import snippets
    cfg = json.loads(snippets.claude_json("/p"))
    assert cfg["mcpServers"]["memory-gateway"]["args"] == ["-m", "app.mcp.server"]
    tm = tomllib.loads(snippets.codex_toml("/p"))
    assert tm["mcp_servers"]["memory-gateway"]["cwd"] == "/p"
    yaml = pytest.importorskip("yaml")
    y = yaml.safe_load(snippets.hermes_yaml("/p"))
    assert y["mcp_servers"]["memory-gateway"]["args"] == ["-m", "app.mcp.server"]


def test_build_snippet_branches():
    from app.connections import snippets
    mcp = snippets.build_snippet(_conn("mcp"))
    assert mcp["status"] == "ok" and set(mcp["snippets"]) == {"hermes_yaml", "claude_json", "codex_toml"}
    ag = snippets.build_snippet(_conn("agent", "codex_toml"), "/r")
    assert ag["status"] == "ok" and ag["format"] == "codex_toml" and "/r" in ag["content"]
    assert snippets.build_snippet(_conn("agent"))["status"] == "unverified"
    assert snippets.build_snippet(_conn("model"))["status"] == "unverified"


# --------------------------------------------------------------------------- ANA-222 (opt-in, skipped by default)
@pytest.mark.skipif(not os.environ.get("ANAMNESIA_REAL_AGENT"),
                    reason="opt-in: ANAMNESIA_REAL_AGENT=claude_code|codex (uses the logged-in CLI; may cost quota)")
def test_real_agent_contract():
    from app.adapters.agents.agents import ClaudeCodeAdapter
    from app.adapters.agents.agents import CodexAdapter
    name = os.environ["ANAMNESIA_REAL_AGENT"]
    cls = {"claude_code": ClaudeCodeAdapter, "codex": CodexAdapter}[name]
    a = cls()
    av = a.available()
    assert {"agent", "available", "version", "mcp", "cli", "metrics", "reason"} <= set(av)
    if not av["available"]:
        pytest.skip(f"{name} indisponível: {av['reason']}")
    r = a.generate("Responda apenas com a palavra OK.", timeout=180)
    assert r.error is None and r.answer and r.provider == name
    assert r.latency_ms > 0


def test_real_agent_contract_is_gated_by_env_var():
    marks = [m for m in test_real_agent_contract.pytestmark if m.name == "skipif"]
    assert marks and "ANAMNESIA_REAL_AGENT" in marks[0].kwargs["reason"]


# --------------------------------------------------------------------------- ANA-223
def test_ci_has_separate_browser_e2e_job():
    wf = _read(".github/workflows/ci.yml")
    jobs = re.findall(r"^  ([a-z0-9_-]+):\s*$", wf.split("jobs:", 1)[1], re.M)
    assert "test" in jobs and "e2e-browser" in jobs
    e2e = wf.split("  e2e-browser:", 1)[1]
    assert "ANAMNESIA_E2E: '1'" in e2e and "playwright install" in e2e and "tests/e2e" in e2e
    assert "continue-on-error" not in e2e and "matrix" not in e2e
    assert "ANAMNESIA_E2E" not in wf.split("  e2e-browser:", 1)[0]     # unit job never runs the browser


# --------------------------------------------------------------------------- ANA-224
@pytest.fixture
def offline_on(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_OFFLINE", "1")
    offline.install()
    yield
    offline.uninstall()


def test_offline_flag_parsing(monkeypatch):
    for v in ("1", "true", "YES", "on"):
        assert offline.offline_enabled({"OFFLINE": v})
    assert not offline.offline_enabled({"OFFLINE": "0"}) and not offline.offline_enabled({})
    assert offline.offline_enabled({"ANAMNESIA_OFFLINE": "1"})


def test_offline_blocks_external_connect_without_opening_it(offline_on, monkeypatch):
    real_calls = []
    # innermost spy: if the guard let an external connect through, this fails the test
    orig = offline._originals["connect"]

    def spy(self, address):
        real_calls.append(address)
        raise AssertionError("socket opened to external host")
    offline._originals["connect"] = spy
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with pytest.raises(offline.OfflineBlocked):
            s.connect(("93.184.216.34", 443))
        with pytest.raises(offline.OfflineBlocked):
            s.connect_ex(("1.1.1.1", 53))
        s.close()
        with pytest.raises(offline.OfflineBlocked):
            socket.getaddrinfo("api.openai.com", 443)
        with pytest.raises(offline.OfflineBlocked):
            socket.create_connection(("example.com", 80), timeout=1)
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(offline.OfflineBlocked):
            u.sendto(b"x", ("8.8.8.8", 53))
        u.close()
        with pytest.raises(httpx.ConnectError, match="OFFLINE=1"):   # httpx wraps the OSError subclass
            httpx.get("https://example.com", timeout=1)
        assert real_calls == []
    finally:
        offline._originals["connect"] = orig


def test_offline_allows_loopback(offline_on, fake_openai):
    r = httpx.get(fake_openai.url + "/v1/models", timeout=5)
    assert r.status_code == 200
    from app.adapters.models.providers import OpenAICompatibleAdapter
    ok = OpenAICompatibleAdapter(fake_openai.url + "/v1", "m", "sk-fake", provider="vllm").generate("ping")
    assert ok.answer == "pong"


def test_offline_blocks_hosted_providers_before_any_request(monkeypatch, fake_openai):
    monkeypatch.setenv("OFFLINE", "1")
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    from app.adapters.models.providers import OpenAICompatibleAdapter
    r = OpenAICompatibleAdapter("https://api.openai.com/v1", "m", "k", provider="openai").generate("x")
    assert r.answer is None and "OFFLINE=1" in r.error and fake_openai.requests == []
    # a hosted provider pointed at a loopback fake is still hosted-by-name -> blocked by ensure_paid_allowed path
    r2 = OpenAICompatibleAdapter(fake_openai.url + "/v1", "m", "sk-fake", provider="openai").generate("ping")
    assert r2.answer is None and "OFFLINE=1" in r2.error and fake_openai.requests == []
    # local provider on loopback keeps working
    ok = OpenAICompatibleAdapter(fake_openai.url + "/v1", "m", "sk-fake", provider="vllm").generate("ping")
    assert ok.answer == "pong"


def test_offline_blocks_agent_clis(monkeypatch, fake_cli):
    from app.adapters.agents.agents import ClaudeCodeAdapter
    from app.adapters.agents.agents import CodexAdapter
    calls, _ = fake_cli
    monkeypatch.setenv("ANAMNESIA_OFFLINE", "1")
    for a in (ClaudeCodeAdapter(), CodexAdapter()):
        r = a.generate("oi")
        assert r.answer is None and "OFFLINE=1" in r.error
    assert calls == []          # the CLI was never started


def test_offline_bridge_blocks_remote_but_allows_loopback(monkeypatch, fake_rest):
    from app.mcp.bridge import bridge_search
    monkeypatch.setenv("OFFLINE", "1")
    with pytest.raises(offline.OfflineBlocked):
        bridge_search({"query": "x"}, url="https://gateway.example.com")
    assert bridge_search({"query": "x"}, url=fake_rest.url)["run_id"] == "r1"


def test_offline_install_is_idempotent_and_reversible():
    before = (socket.socket.connect, socket.getaddrinfo)
    offline.install()
    offline.install()
    assert offline.installed() and socket.socket.connect is not before[0]
    offline.uninstall()
    assert not offline.installed() and (socket.socket.connect, socket.getaddrinfo) == before


def test_install_if_enabled_only_when_flag_set(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_OFFLINE", raising=False)
    monkeypatch.delenv("OFFLINE", raising=False)
    assert offline.install_if_enabled() is False and not offline.installed()
    monkeypatch.setenv("OFFLINE", "1")
    try:
        assert offline.install_if_enabled() is True and offline.installed()
    finally:
        offline.uninstall()


def test_offline_process_level_search_makes_no_external_socket(tmp_path):
    """Whole CLI in a child process with OFFLINE=1: a baseline search over the synthetic vault, with every
    non-loopback connect/DNS turned into a hard failure by a sitecustomize-style probe."""
    code = (
        "import socket, sys\n"
        "bad = []\n"
        "_c = socket.socket.connect\n"
        "def c(self, a):\n"
        "    if isinstance(a, tuple) and a[0] not in ('127.0.0.1', '::1', 'localhost'): bad.append(a)\n"
        "    return _c(self, a)\n"
        "socket.socket.connect = c\n"
        "from anamnesia import cli\n"
        "rc = cli.main(['doctor', '--json'])\n"
        "print('@@', rc, bad)\n"
    )
    env = {**os.environ, "OFFLINE": "1", "ANAMNESIA_HOME": str(tmp_path), "PYTHONPATH": str(ROOT),
           "MEMORY_GATEWAY_VAULT": str(ROOT / "data" / "synthetic_vault")}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env, timeout=120)
    assert "@@ 0 []" in r.stdout, r.stdout[-500:] + r.stderr[-500:]
    doc = json.loads(r.stdout.split("@@")[0])
    assert doc["local_first"]["offline_enforced"] is True and doc["local_first"]["level"] >= 4


# --------------------------------------------------------------------------- ANA-238
def test_grade_jev_with_typesafe_is_at_most_l3():
    for extra in ({}, {"OFFLINE_UNRELATED": "1"}):
        g = local_first.assess({"TYPESAFE_API_KEY": "k", **extra}, which=lambda b: None)
        assert g["level"] <= 3 and g["level"] == 2
        assert g["capabilities"]["jev_judge"]["where"] == "network"


def test_grade_levels():
    none = lambda b: None  # noqa: E731
    assert local_first.assess({}, which=none)["level"] == 3
    assert local_first.assess({"OFFLINE": "1"}, which=none)["level"] == 4
    assert local_first.assess({"OFFLINE": "1"}, which=lambda b: "/x/ollama" if b == "ollama" else None)["level"] == 5
    # OFFLINE with a judge key: the judge is blocked -> not external
    g = local_first.assess({"OFFLINE": "1", "TYPESAFE_API_KEY": "k"}, which=none)
    assert g["level"] == 4 and g["capabilities"]["jev_judge"]["where"] == "off"
    # kill-switch alone also disables the judge but is not an OFFLINE guarantee
    assert local_first.assess({"ANAMNESIA_PAID_CALLS": "0", "TYPESAFE_API_KEY": "k"}, which=none)["level"] == 3
    # hosted key without block => external
    assert local_first.assess({"OPENAI_API_KEY": "k"}, which=none)["level"] == 3
    assert local_first.assess({"OFFLINE": "1", "OPENAI_API_KEY": "k"}, which=none)["level"] >= 4


def test_grade_never_leaks_secret_values():
    g = local_first.assess({"TYPESAFE_API_KEY": "SUPERSECRET", "OPENAI_API_KEY": "SUPERSECRET2"}, which=lambda b: None)
    assert "SUPERSECRET" not in json.dumps(g)


def test_doctor_prints_level_and_json(capsys, monkeypatch):
    from anamnesia import cli
    monkeypatch.setenv("TYPESAFE_API_KEY", "SECRET123")
    monkeypatch.delenv("OFFLINE", raising=False)
    monkeypatch.delenv("ANAMNESIA_OFFLINE", raising=False)
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)   # ANAM-041: juiz em loopback muda o nivel (L2 so com juiz externo)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "local-first: L2" in out and "jev_judge" in out and "SECRET123" not in out
    assert cli.main(["doctor", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is True and doc["local_first"]["level"] == 2
    assert {"retrieval", "storage", "graph", "jev_judge", "local_models", "hosted_models"} <= set(doc["local_first"]["capabilities"])
    assert any(c["name"] == "python" for c in doc["checks"])


# --------------------------------------------------------------------------- ANA-218
def test_compatibility_matrix_rows_point_to_real_tests():
    doc = _read("docs/guides/COMPATIBILITY.md")
    rows = [ln for ln in doc.splitlines() if ln.startswith("|") and "`tests/" in ln]
    assert len(rows) >= 8
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "tests").glob("*.py"))
    for ln in rows:
        m = re.search(r"`(tests/[\w./]+)::(\w+)`", ln)
        assert m, ln
        assert (ROOT / m.group(1)).is_file(), ln
        assert f"def {m.group(2)}" in (ROOT / m.group(1)).read_text(encoding="utf-8"), ln
        assert "testado" in ln.lower() or "opt-in" in ln.lower() or "estático" in ln.lower(), ln
    assert corpus  # sanity
    assert "não testado" in doc.lower() or "nao testado" in doc.lower()
