"""Estado de conexão e verificação real por provedor.

Estados (`STATES`): not_configured, configured (configurado/não testado), testing (só na UI), connected
(verificado), auth_error, unavailable, expired (verificação vencida ou invalidada por troca de chave).

Regras:
- "connected" só existe depois de uma verificação REAL: CLI do agente respondendo a `--version`, módulo MCP
  importável, ou chamada de rede ao provedor (somente com ANAMNESIA_ALLOW_NETWORK_TEST=1).
- A verificação fica só em memória (reiniciar o servidor volta a "configured") e carrega uma impressão digital
  (sha256 truncado) das chaves: trocar/remover a chave invalida o resultado. Nenhum segredo é guardado,
  logado ou devolvido.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from app.connections import secrets as secret_store
from app.connections.catalog import Connection, detect

# not_installed : agente/CLI ausente do PATH.      detected  : CLI no PATH; autenticação própria NÃO verificada.
# not_configured: provedor sem chave salva.        configured: chave salva, não testada no provedor.
# connected     : prova real (provedor aceitou a chave / serviço respondeu) = "autenticado".
# auth_error/unavailable/expired: erro. Estar no PATH NUNCA vira "connected".
STATES = ("not_installed", "detected", "not_configured", "configured", "testing", "connected", "auth_error",
          "unavailable", "expired")
TTL_ENV = "ANAMNESIA_VERIFY_TTL_S"
DEFAULT_TTL_S = 24 * 3600
_records: dict[str, dict] = {}

# Sonda por variável de chave: (url, função que monta os headers). Só hosts da allow-list de egress.
_PROBES = {
    "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1/models?limit=1",
                          lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
    "OPENAI_API_KEY": ("https://api.openai.com/v1/models", lambda k: {"Authorization": f"Bearer {k}"}),
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1/auth/key", lambda k: {"Authorization": f"Bearer {k}"}),
}


def ttl_s() -> int:
    try:
        return max(1, int(os.environ.get(TTL_ENV, DEFAULT_TTL_S)))
    except ValueError:
        return DEFAULT_TTL_S


def _fingerprint(c: Connection) -> str:
    h = hashlib.sha256()
    for k in c.key_names:
        h.update(k.encode()); h.update(b"=")
        h.update((secret_store._read(k) or "").encode()); h.update(b";")  # noqa: SLF001
    return h.hexdigest()[:16]


def reset() -> None:
    _records.clear()


def forget(cid: str) -> None:
    _records.pop(cid, None)


def _store(c: Connection, state: str, detail: str) -> dict:
    rec = {"state": state, "detail": detail, "ts": time.time(), "fp": _fingerprint(c)}
    _records[c.id] = rec
    return rec


def state_of(c: Connection) -> dict:
    """{'state', 'detail', 'verified_at'} calculado a partir do estado atual (sem rede)."""
    keys = c.key_names
    has_key = any(secret_store.has_key(k) for k in keys)
    is_detected = detect(c)
    if c.type in ("agent",) or (c.type == "model" and c.command):
        if c.command and not shutil.which(c.command.split()[0]):
            return {"state": "not_installed", "detail": f"`{c.command.split()[0]}` não encontrado no PATH", "verified_at": None}
    rec = _records.get(c.id)
    if rec:
        stamp = rec["ts"]
        if rec["fp"] != _fingerprint(c):
            return {"state": "expired", "detail": "chave alterada ou removida desde a última verificação; teste de novo",
                    "verified_at": stamp}
        if time.time() - stamp > ttl_s():
            return {"state": "expired", "detail": "verificação vencida; teste de novo", "verified_at": stamp}
        return {"state": rec["state"], "detail": rec["detail"], "verified_at": stamp}
    if keys and not has_key:
        return {"state": "not_configured", "detail": "nenhuma chave salva", "verified_at": None}
    if c.type == "mcp" and not is_detected:
        return {"state": "unavailable", "detail": "módulo MCP não importável", "verified_at": None}
    if not keys and not is_detected:
        return {"state": "not_installed", "detail": "não detectado neste computador", "verified_at": None}
    if c.type == "agent" and not keys:
        return {"state": "detected", "detail": "detectado no PATH; autenticação própria do agente não verificada",
                "verified_at": None}
    return {"state": "configured", "detail": "configurado, ainda não testado", "verified_at": None}


def _http_get(url: str, headers: dict, timeout: float = 8.0) -> int:
    """Status HTTP (4xx/5xx incluídos). Levanta OSError em falha de rede. Passa pelo gate de egress."""
    from app.services.egress import check_egress
    check_egress(url, "connection_test")
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def probe_key(env_key: str) -> tuple[str, str]:
    """Verificação real da chave no provedor -> (state, detail). Nunca inclui a chave."""
    spec = _PROBES.get(env_key)
    value = secret_store._read(env_key)  # noqa: SLF001
    if spec is None:
        return "configured", f"verificação de rede ainda não implementada para {env_key}"
    if not value:
        return "not_configured", f"{env_key} ausente"
    url, mk = spec
    try:
        code = _http_get(url, mk(value))
    except Exception as e:  # noqa: BLE001 -- rede/egress/offline: indisponível, nunca sucesso
        return "unavailable", f"provedor inalcançável ({type(e).__name__})"
    if code == 200:
        return "connected", f"{env_key} aceita pelo provedor (HTTP 200)"
    if code in (401, 403):
        return "auth_error", f"{env_key} recusada pelo provedor (HTTP {code})"
    return "unavailable", f"provedor respondeu HTTP {code}; chave não verificada"


def _cli_check(c: Connection) -> tuple[bool, str]:
    exe = (c.command or "").split()[0]
    path = shutil.which(exe)
    if not path:
        return False, f"`{exe}` não encontrado no PATH"
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"`{exe} --version` falhou ({type(e).__name__})"
    if r.returncode != 0:
        return False, f"`{exe} --version` saiu com código {r.returncode}"
    return True, f"`{exe} --version` respondeu"


def _ollama_probe(host: str | None = None) -> tuple[bool, str]:
    host = host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    if not host.startswith("http"):
        host = "http://" + host
    try:
        code = _http_get(host.rstrip("/") + "/api/tags", {}, timeout=3)
        return code == 200, f"HTTP {code}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def run_test(c: Connection) -> dict:
    """Executa a verificação real e atualiza o registro. -> {state, detail, checks, network_checked, note}."""
    network_on = os.environ.get("ANAMNESIA_ALLOW_NETWORK_TEST") == "1"
    checks: list[dict] = []
    network_checked = False
    note = "verificação local; nenhuma chamada de rede (defina ANAMNESIA_ALLOW_NETWORK_TEST=1 para testar a chave no provedor)"
    stored = [k for k in c.key_names if secret_store.has_key(k)]
    keyed_model = c.type == "model" and bool(c.key_names)

    if c.type == "mcp":
        ok = detect(c)
        checks.append({"name": "mcp_module", "ok": ok})
        rec = _store(c, "connected", "módulo MCP importável") if ok else \
            _store(c, "unavailable", "módulo MCP não importável")
        return _pack(c, rec, checks, False, note)

    if keyed_model and not stored:
        forget(c.id)
        checks.append({"name": "key_present", "ok": False})
        return _pack(c, {"state": "not_configured", "detail": "nenhuma chave salva", "ts": None}, checks, False, note)

    if c.command and c.type == "agent":
        ok, detail = _cli_check(c)
        checks.append({"name": "cli_version", "ok": ok, "detail": detail})
        if not ok:
            return _pack(c, _store(c, "not_installed", detail), checks, False, note)

    if c.id == "ollama":
        if network_on:
            ok, detail = _ollama_probe()
            checks.append({"name": "network:ollama", "ok": ok, "detail": detail})
            rec = _store(c, "connected" if ok else "unavailable",
                         "Ollama respondeu em /api/tags" if ok else f"Ollama não respondeu ({detail})")
            return _pack(c, rec, checks, True, "sonda de rede apenas para o Ollama local")
        forget(c.id)
        return _pack(c, state_of(c), checks, False, note)

    if stored:
        if not network_on:
            forget(c.id)
            for k in stored:
                checks.append({"name": f"key:{k}", "ok": True, "detail": "presente; não verificada no provedor"})
            return _pack(c, state_of(c), checks, False, note)
        results = [(k, *probe_key(k)) for k in stored]
        for k, st, d in results:
            checks.append({"name": f"network:{k}", "ok": st == "connected", "detail": d})
        network_checked = True
        note = "chave verificada no provedor"
        order = ("auth_error", "unavailable", "configured", "connected")
        worst = next(s for s in order if any(r[1] == s for r in results))
        detail = "; ".join(r[2] for r in results)
        return _pack(c, _store(c, worst, detail), checks, network_checked, note)

    # agente sem chave guardada: a própria CLI cuida da autenticação -> só "detectado", nunca "conectado"
    return _pack(c, _store(c, "detected", "CLI respondeu a --version; autenticação própria do agente não é verificada aqui"),
                 checks, False, note)


def _pack(c: Connection, rec: dict, checks: list[dict], network_checked: bool, note: str) -> dict:
    state = rec["state"]
    return {"id": c.id, "ok": state == "connected", "state": state, "detail": rec["detail"],
            "verified_at": rec.get("ts"), "detected": detect(c), "checks": checks,
            "network_checked": network_checked, "note": note}
