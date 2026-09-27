"""Agent consumer adapters (§32–§35, §43, §103). Business logic never depends on them.

Every adapter:  available() -> dict(available, version, mcp, cli, metrics, reason)
                generate(prompt) -> GenerationResult     (answer + tokens when the platform reports them)

Two ways an agent consumes memory:
- "context" mode (benchmark, fair comparison): the Gateway retrieves context and the agent receives the
  consumer prompt with that context. Same prompt for every pipeline; only retrieval changes (§51, §84).
- "mcp" mode (integration): the agent calls the Gateway's MCP tool itself (Hermes → MCP → Gateway).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from config import PROJECT_ROOT
from config.agents import AgentsConfig
from app.adapters.models.providers import GenerationResult

HERMES_HOME = PROJECT_ROOT / "integrations" / "hermes" / "hermes_home"     # MCP integration (agent calls tools)
HERMES_BENCH_HOME = PROJECT_ROOT / "integrations" / "hermes" / "hermes_bench"  # benchmark consumer, no tools


def _run(args: list[str], timeout: int, env: dict | None = None, cwd: str | None = None, stdin: str | None = None):
    e = dict(os.environ)
    e.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    if env:
        e.update(env)
    return subprocess.run(args, capture_output=True, timeout=timeout, env=e, cwd=cwd,
                          input=stdin.encode("utf-8") if stdin is not None else None)


def _version(binary: str, flag: str = "--version") -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    try:
        r = _run([path, flag], timeout=30)
        out = (r.stdout or r.stderr).decode("utf-8", "replace").strip().splitlines()
        return out[0] if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class HermesAdapter:
    """Hermes Agent v0.20.5 — verified commands:
    `hermes -z PROMPT --usage-file PATH [-m MODEL] [--provider P] [-t TOOLSETS]` (one-shot, JSON usage report).
    Runs with an isolated HERMES_HOME (integrations/hermes/hermes_home) so the user's profile is untouched.

    Model selection: prefer the isolated config's `model.default` (leave model empty). Verified pitfall:
    passing `-m <ollama model>` drops the config's `context_length`/`ollama_num_ctx` overrides and Hermes
    then refuses qwen3 (40,960 ctx < 64K minimum).
    """
    name = "hermes"

    def __init__(self, cfg: AgentsConfig | None = None, hermes_home: Path = HERMES_BENCH_HOME):
        self.cfg = cfg or AgentsConfig()
        self.home = Path(hermes_home)

    def available(self) -> dict:
        v = _version(self.cfg.hermes_bin)
        return {"agent": self.name, "available": v is not None, "version": v, "mcp": True, "cli": True,
                "metrics": "FULL" if v else "UNAVAILABLE",
                "reason": None if v else "hermes não encontrado no PATH",
                "home": str(self.home)}

    def generate(self, prompt: str, model: str | None = None, provider: str | None = None,
                 toolsets: str = "", timeout: int | None = None) -> GenerationResult:
        usage_path = Path(tempfile.gettempdir()) / f"mg_hermes_usage_{os.getpid()}_{time.time_ns()}.json"
        args = [shutil.which(self.cfg.hermes_bin) or self.cfg.hermes_bin, "-z", prompt,
                "--usage-file", str(usage_path), "-t", toolsets, "--reasoning", "none"]
        model = model or self.cfg.hermes_model
        provider = provider or self.cfg.hermes_provider
        if model:
            args += ["-m", model]
        if provider:
            args += ["--provider", provider]
        t0 = time.perf_counter()
        err = None
        try:
            r = _run(args, timeout=timeout or self.cfg.agent_timeout_s, env={"HERMES_HOME": str(self.home)},
                     cwd=str(PROJECT_ROOT))
            answer = r.stdout.decode("utf-8", "replace").strip() or None
            if r.returncode != 0:
                err = r.stderr.decode("utf-8", "replace")[-400:] or f"exit {r.returncode}"
        except subprocess.TimeoutExpired:
            answer, err = None, "timeout"
        lat = round((time.perf_counter() - t0) * 1000, 1)
        usage = {}
        if usage_path.exists():
            try:
                usage = json.loads(usage_path.read_text(encoding="utf-8"))
            finally:
                usage_path.unlink(missing_ok=True)
        if usage.get("failed"):
            err = err or usage.get("failure") or "hermes reported failed"
        cost = usage.get("estimated_cost_usd") if usage.get("cost_status") not in (None, "unknown") else None
        # Hermes reports prompt-cache reads/writes separately from input_tokens (verified: 23,476 input on a
        # cold cache vs ~3k input + ~20k cache_read on warm runs). Everything the model processed is input.
        inp = usage.get("input_tokens")
        if inp is not None:
            inp += (usage.get("cache_read_tokens") or 0) + (usage.get("cache_write_tokens") or 0)
        return GenerationResult(
            answer=answer, input_tokens=inp, output_tokens=usage.get("output_tokens"),
            latency_ms=lat, provider=f"hermes/{usage.get('provider') or provider or 'config'}",
            model=usage.get("model") or model or "config-default", error=err,
            agent_tokens=usage.get("total_tokens"), agent_cost=cost,
            raw_meta={k: usage.get(k) for k in ("input_tokens", "api_calls", "session_id", "cost_status",
                                                "reasoning_tokens", "cache_read_tokens", "cache_write_tokens",
                                                "completed")})


class ClaudeCodeAdapter:
    """Claude Code 2.1.x — `claude -p PROMPT --output-format json --max-turns 1` returns usage/cost.

    Verified pitfall (2026-09-24): a bare `claude -p` inherits the user's GLOBAL `~/.claude` state —
    ~14 configured MCP servers (Notion, Gmail, Drive, Linear, plugins...) whose tool schemas get loaded
    into the prompt even with `--tools ""` (measured: ~385,000 input tokens on a trivial prompt, exceeding
    the 200k context and failing most calls), AND cross-call auto-memory for this project directory
    (`~/.claude/projects/<project>/memory/`), which silently carries context between "independent"
    benchmark repetitions. `--bare` would isolate both but requires ANTHROPIC_API_KEY (this environment
    is OAuth/browser-login only). Fix used here: `--mcp-config <empty file> --strict-mcp-config` (no MCP
    tool schemas) + `--no-session-persistence` + `--settings '{"disableMemory":true}'` (no auto-memory).
    Verified: input_tokens drops from ~385k to 9 on a trivial prompt.
    """
    name = "claude_code"

    def __init__(self, cfg: AgentsConfig | None = None):
        self.cfg = cfg or AgentsConfig()
        self._empty_mcp_config = PROJECT_ROOT / "data" / "claude_empty_mcp.json"

    def available(self) -> dict:
        v = _version(self.cfg.claude_bin)
        logged = None
        if v:
            try:
                r = _run([shutil.which(self.cfg.claude_bin), "auth", "status"], timeout=30)
                logged = json.loads(r.stdout.decode("utf-8", "replace") or "{}").get("loggedIn")
            except Exception:  # noqa: BLE001
                logged = None
        ok = bool(v and (logged or os.getenv("ANTHROPIC_API_KEY")))
        return {"agent": self.name, "available": ok, "version": v, "mcp": True, "cli": True,
                "metrics": "FULL" if ok else "UNAVAILABLE",
                "reason": None if ok else ("não instalado" if not v else "não autenticado (claude auth login)")}

    def generate(self, prompt: str, model: str | None = None, timeout: int | None = None) -> GenerationResult:
        self._empty_mcp_config.parent.mkdir(parents=True, exist_ok=True)
        if not self._empty_mcp_config.exists():
            self._empty_mcp_config.write_text('{"mcpServers": {}}', encoding="utf-8")
        args = [shutil.which(self.cfg.claude_bin) or "claude", "-p", "--output-format", "json", "--max-turns", "1",
                "--tools", "", "--mcp-config", str(self._empty_mcp_config), "--strict-mcp-config",
                "--no-session-persistence", "--settings", '{"disableMemory":true}']
        if model:
            args += ["--model", model]
        t0 = time.perf_counter()
        try:
            r = _run(args, timeout=timeout or self.cfg.agent_timeout_s, stdin=prompt, cwd=str(PROJECT_ROOT))
            data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
            usage = data.get("usage") or {}
            inp = None if not usage else (usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                                          + usage.get("cache_creation_input_tokens", 0))
            return GenerationResult(data.get("result"), inp, usage.get("output_tokens"),
                                    round((time.perf_counter() - t0) * 1000, 1), "claude_code",
                                    model or "default", None if data.get("subtype") == "success" else str(data)[:300],
                                    agent_cost=data.get("total_cost_usd"))
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(None, None, None, round((time.perf_counter() - t0) * 1000, 1), "claude_code",
                                    model or "default", f"{type(exc).__name__}: {str(exc)[:300]}")


class CodexAdapter:
    """Codex CLI 0.155 — `codex exec --json -o FILE --skip-git-repo-check -s read-only -` (prompt via stdin).
    Token usage is read from the `turn.completed` JSONL event when present, else unavailable."""
    name = "codex"

    def __init__(self, cfg: AgentsConfig | None = None):
        self.cfg = cfg or AgentsConfig()

    def available(self) -> dict:
        v = _version(self.cfg.codex_bin)
        logged = False
        if v:
            try:
                r = _run([shutil.which(self.cfg.codex_bin), "login", "status"], timeout=30)
                logged = "logged in" in (r.stdout + r.stderr).decode("utf-8", "replace").lower()
            except Exception:  # noqa: BLE001
                logged = False
        ok = bool(v and logged)
        return {"agent": self.name, "available": ok, "version": v, "mcp": True, "cli": True,
                "metrics": "PARTIAL" if ok else "UNAVAILABLE",
                "reason": None if ok else ("não instalado" if not v else "não autenticado"),
                "note": "login OK não garante cota: em 2026-09-24 a conta atingiu o limite de uso até 07/10"}

    def generate(self, prompt: str, model: str | None = None, timeout: int | None = None) -> GenerationResult:
        out = Path(tempfile.gettempdir()) / f"mg_codex_{time.time_ns()}.txt"
        args = [shutil.which(self.cfg.codex_bin) or "codex", "exec", "--json", "--skip-git-repo-check",
                "-s", "read-only", "-C", tempfile.gettempdir(), "-o", str(out)]
        if model:
            args += ["-m", model]
        args.append("-")
        t0 = time.perf_counter()
        try:
            r = _run(args, timeout=timeout or self.cfg.agent_timeout_s, stdin=prompt)
            inp = outp = None
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                u = ev.get("usage") if isinstance(ev, dict) else None
                if u:
                    inp = (inp or 0) + (u.get("input_tokens") or 0)
                    outp = (outp or 0) + (u.get("output_tokens") or 0)
            answer = out.read_text(encoding="utf-8").strip() if out.exists() else None
            out.unlink(missing_ok=True)
            return GenerationResult(answer, inp, outp, round((time.perf_counter() - t0) * 1000, 1), "codex",
                                    model or "config-default", None if r.returncode == 0 else
                                    r.stderr.decode("utf-8", "replace")[-300:])
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(None, None, None, round((time.perf_counter() - t0) * 1000, 1), "codex",
                                    model or "config-default", f"{type(exc).__name__}: {str(exc)[:300]}")


class OpenCodeAdapter:
    """OpenCode 1.18 detected but with 0 credentials -> prepared, not validated."""
    name = "opencode"

    def __init__(self, cfg: AgentsConfig | None = None):
        self.cfg = cfg or AgentsConfig()

    def available(self) -> dict:
        v = _version(self.cfg.opencode_bin)
        return {"agent": self.name, "available": False, "version": v, "mcp": True, "cli": bool(v),
                "metrics": "UNAVAILABLE",
                "reason": "instalado, sem credenciais configuradas; adapter não validado" if v else "não instalado"}

    def generate(self, prompt: str, model: str | None = None, timeout: int | None = None) -> GenerationResult:
        return GenerationResult(None, None, None, 0.0, "opencode", model or "", "OpenCode adapter não validado")
