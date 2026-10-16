"""Configuração guiada do JEV (botão 'Configurar JEV' do Workspace).

NÃO reimplementa o JEV: a fonte de verdade continua sendo `config/jev.py::JevConfig` (lê `JEV_*` do ambiente/.env)
e o SDK `typesafe_sdk` (lê `TYPESAFE_API_KEY` / `TYPESAFE_BASE_URL`). Este módulo só

  * lê o estado atual (`status`),
  * grava no mesmo `.env` (via `envfile.set_env_var`, atômico, só as linhas tocadas) apenas o que o usuário mudou (`save`),
  * valida a integração de ponta a ponta usando o MESMO backend do pipeline (`test_connection`).

Segredo: a chave nunca é devolvida, logada nem incluída em mensagens de erro; só `mask_secret` (últimos 4).
O endpoint é restrito (https, ou http em loopback; sem credenciais embutidas) porque a chave viaja para ele.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from urllib.parse import urlsplit

from app.services import security
from app.services.envfile import EnvValueError, set_env_var

audit = logging.getLogger("anamnesia.jev_setup.audit")  # só NOMES de campos, nunca valores de segredo

KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
KV_LAST_TEST = "jev.last_test"

# campo da UI -> (variável de ambiente, tipo). Whitelist: nenhuma outra chave do .env é gravável por aqui.
BASIC_FIELDS = {"model": ("JEV_MODEL", "model"), "base_url": (BASE_URL_ENV, "url")}
ADVANCED_FIELDS = {
    "mode": ("JEV_MODE", ("performance", "strict")),
    "relevance_threshold": ("JEV_RELEVANCE_THRESHOLD", "unit"),
    "review_threshold": ("JEV_REVIEW_THRESHOLD", "unit"),
    "injection_threshold": ("JEV_INJECTION_THRESHOLD", "unit"),
    "review_action": ("JEV_REVIEW_ACTION", ("keep", "drop")),
    "failure_mode": ("JEV_FAILURE_MODE", ("fail_open", "fail_closed")),
    "second_pass": ("JEV_SECOND_PASS", "bool"),
    "contradiction_check": ("JEV_CONTRADICTION_CHECK", "bool"),
    "timeout_s": ("JEV_TIMEOUT_S", ("float", 1.0, 300.0)),
    "max_retries": ("JEV_MAX_RETRIES", ("int", 0, 10)),
    "max_concurrent_requests": ("JEV_MAX_CONCURRENT_REQUESTS", ("int", 1, 16)),
}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class JevSetupError(ValueError):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code, self.message, self.field = code, message, field


# ------------------------------------------------------------------ validation
def validate_base_url(raw: str) -> str:
    url = (raw or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as e:
        raise JevSetupError("invalid_field", "Endpoint inválido.", "base_url") from e
    if not url or len(url) > 300 or not host:
        raise JevSetupError("invalid_field", "Endpoint inválido.", "base_url")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise JevSetupError("invalid_field", "O endpoint não pode conter usuário/senha, query ou fragmento.", "base_url")
    if not (parts.scheme == "https" or (parts.scheme == "http" and host in _LOOPBACK)):
        raise JevSetupError("invalid_field", "O endpoint deve usar https (http só em localhost).", "base_url")
    from app.services.egress import EgressBlocked, check_policy  # ANAM-004: allow-list de hosts (anti-exfiltração)
    try:
        check_policy(url, "jev_setup")
    except EgressBlocked as e:
        raise JevSetupError("host_not_allowed", str(e), "base_url") from e
    return url


def _validate(field: str, kind, value) -> str:
    """Valor normalizado (texto para o .env) ou JevSetupError."""
    bad = JevSetupError("invalid_field", f"Valor inválido para '{field}'.", field)
    if kind == "url":
        return validate_base_url(str(value))
    if kind == "model":
        v = str(value).strip()
        import re
        if not re.fullmatch(r"[A-Za-z0-9._:\-]{1,64}", v):
            raise JevSetupError("invalid_field", "Modelo inválido (use letras, números, '.', '-', '_', ':').", field)
        return v
    if kind == "unit":
        try:
            f = float(value)
        except (TypeError, ValueError):
            raise bad from None
        if not 0.0 <= f <= 1.0:
            raise JevSetupError("invalid_field", f"'{field}' deve estar entre 0 e 1.", field)
        return repr(round(f, 4))
    if kind == "bool":
        if isinstance(value, bool):
            return "true" if value else "false"
        raise bad
    if isinstance(kind, tuple) and kind and kind[0] in ("int", "float"):
        try:
            n = int(value) if kind[0] == "int" else float(value)
        except (TypeError, ValueError):
            raise bad from None
        if isinstance(value, bool) or not kind[1] <= n <= kind[2]:
            raise JevSetupError("invalid_field", f"'{field}' deve estar entre {kind[1]} e {kind[2]}.", field)
        return str(n)
    if isinstance(kind, tuple):
        if str(value) not in kind:
            raise JevSetupError("invalid_field", f"'{field}' deve ser um de: {', '.join(kind)}.", field)
        return str(value)
    raise bad


def _validate_key(value: str) -> str:
    v = (value or "").strip()
    if not v or len(v) > 2000 or any(ch in v for ch in "\r\n\x00 \t"):
        raise JevSetupError("invalid_field", "API Key inválida (vazia ou com espaços/quebras de linha).", "api_key")
    return v


# ------------------------------------------------------------------ state
def _current_cfg():
    from config.jev import JevConfig
    return JevConfig()


def _effective(env=None) -> dict:
    e = os.environ if env is None else env
    cfg = _current_cfg()
    out = {"base_url": (e.get(BASE_URL_ENV) or "").strip() or DEFAULT_BASE_URL, "model": cfg.model}
    for f in ADVANCED_FIELDS:
        out[f] = getattr(cfg, f)
    return out


def _defaults() -> dict:
    """Valores padrão do código (JevConfig sem env), para a UI saber o que foi personalizado."""
    from config.jev import JevConfig
    saved = {v[0]: os.environ.pop(v[0], None) for v in list(BASIC_FIELDS.values()) + list(ADVANCED_FIELDS.values())}
    try:
        cfg = JevConfig()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    d = {"base_url": DEFAULT_BASE_URL, "model": cfg.model}
    d.update({f: getattr(cfg, f) for f in ADVANCED_FIELDS})
    return d


def _is_local(base_url: str) -> bool:
    from app.services.jev import is_local_base_url   # ANAM-041
    return is_local_base_url(base_url)


def _fingerprint(env=None) -> str:
    e = os.environ if env is None else env
    key = e.get(KEY_ENV) or ""
    return f"{_effective(e)['base_url']}|{_effective(e)['model']}|{key[-4:]}|{len(key)}"


def status(db=None, env=None) -> dict:
    from app.services import offline
    e = os.environ if env is None else env
    key = e.get(KEY_ENV) or ""
    eff = _effective(e)
    defaults = _defaults()
    last = db.get_kv(KV_LAST_TEST) if db is not None else None
    if last and last.get("fingerprint") != _fingerprint(e):
        last = None   # a configuração mudou depois do último teste: resultado antigo não vale
    local = _is_local(eff["base_url"])
    if not key and not local:   # ANAM-041: backend loopback (Colibrì) dispensa TYPESAFE_API_KEY
        state = "not_configured"
    elif offline.offline_enabled() and not offline.is_loopback_url(eff["base_url"]):
        state = "blocked"
    elif last:
        state = last["state"]
    else:
        state = "configured"
    return {"state": state, "key_present": bool(key), "local": local, "key_masked": security.mask_secret(key) if key else None,
            "settings": eff, "defaults": defaults,
            "customized": sorted(k for k, v in eff.items() if v != defaults[k]),
            "last_test": {k: last[k] for k in ("state", "http_status", "message", "at", "latency_ms", "model")
                          if k in last} if last else None,
            "backend": _current_cfg().backend}


# ------------------------------------------------------------------ save
def save(patch: dict, *, api_key: str | None = None, db=None, env_path=None) -> dict:
    """Grava só o que mudou. Campo ausente = não mexe. Valor igual ao atual = não grava (idempotente)."""
    path = env_path or security.ENV_PATH
    changed: list[str] = []
    unchanged: list[str] = []
    unknown = [k for k in patch if k not in BASIC_FIELDS and k not in ADVANCED_FIELDS]
    if unknown:
        raise JevSetupError("invalid_field", f"Campo desconhecido: {unknown[0]}", unknown[0])
    # valida TUDO antes de gravar qualquer coisa (nada pela metade)
    plan: list[tuple[str, str, str]] = []   # (campo, env, valor)
    cur = _effective()
    for field, value in patch.items():
        if value is None:
            continue
        env_name, kind = (BASIC_FIELDS.get(field) or ADVANCED_FIELDS[field])
        norm = _validate(field, kind, value)
        cmp_new = norm
        cmp_cur = cur[field]
        if isinstance(cmp_cur, bool):
            cmp_cur = "true" if cmp_cur else "false"
        try:   # compara numericamente quando possível ("30" == 30.0)
            same = float(cmp_new) == float(cmp_cur)
        except (TypeError, ValueError):
            same = str(cmp_new) == str(cmp_cur)
        if same and (field != "base_url" or os.environ.get(BASE_URL_ENV) or norm == DEFAULT_BASE_URL):
            unchanged.append(field)
            continue
        plan.append((field, env_name, norm))
    key_plan = _validate_key(api_key) if api_key else None
    # coerência entre limiares (mesma regra de JevConfig.validate)
    merged = {**cur, **{f: _validate(f, (BASIC_FIELDS.get(f) or ADVANCED_FIELDS[f])[1], v) for f, _, v in plan}}
    try:
        rel, rev = float(merged["relevance_threshold"]), float(merged["review_threshold"])
    except (TypeError, ValueError):
        rel = rev = 0.0
    if not 0 <= rev <= rel <= 1:
        raise JevSetupError("invalid_field", "Requer limiar de revisão <= limiar de relevância.", "review_threshold")
    try:
        for field, env_name, norm in plan:
            set_env_var(path, env_name, norm)
            os.environ[env_name] = norm
            changed.append(field)
        if key_plan and key_plan != os.environ.get(KEY_ENV):
            set_env_var(path, KEY_ENV, key_plan)
            os.environ[KEY_ENV] = key_plan
            changed.append("api_key")
        elif key_plan:
            unchanged.append("api_key")
    except EnvValueError as e:
        raise JevSetupError("invalid_field", str(e)) from None
    audit.info("jev_setup_save changed=%s unchanged=%s", ",".join(changed), ",".join(unchanged))  # só nomes
    return {"changed": changed, "unchanged": unchanged, "status": status(db)}


def apply_to_gateway(gw) -> None:
    """Faz o gateway em execução enxergar a nova configuração (sem reiniciar)."""
    if gw is None:
        return
    cfg = _current_cfg()
    cfg.validate()
    gw.jev_cfg = cfg
    gw.jev = gw.make_jev(cfg)


# ------------------------------------------------------------------ connection test
def _classify(exc: Exception) -> tuple[str, int | None, str]:
    """(estado, http_status, mensagem em PT-BR). Nunca inclui chave nem corpo bruto da resposta."""
    from app.services.offline import OfflineBlocked
    if isinstance(exc, OfflineBlocked):
        return "blocked", None, "Chamadas externas bloqueadas (modo OFFLINE / ANAMNESIA_PAID_CALLS=0)."
    status_code = getattr(exc, "status", None)
    name = type(exc).__name__
    if isinstance(status_code, int):
        if status_code in (401, 403):
            return "auth_error", status_code, "Token inválido ou expirado." if status_code == 401 else "Token sem permissão."
        if status_code == 404:
            return "unavailable", status_code, "Endpoint não encontrado (confira o endereço e o modelo)."
        if status_code == 429:
            return "unavailable", status_code, "Limite de requisições atingido (429). Tente novamente em instantes."
        if status_code in (400, 422):
            return "unavailable", status_code, "O JEV recusou a requisição (modelo inválido?)."
        if status_code >= 500:
            return "unavailable", status_code, "O serviço JEV está indisponível no momento."
        return "unavailable", status_code, f"Resposta inesperada do JEV (HTTP {status_code})."
    if "Timeout" in name or isinstance(exc, TimeoutError):
        return "unavailable", None, "Tempo esgotado ao conectar ao endpoint."
    if "Connection" in name or isinstance(exc, ConnectionError):
        return "unavailable", None, "Não foi possível alcançar o endpoint (rede/DNS/endereço)."
    return "unavailable", None, f"Falha ao validar a resposta do JEV ({name})."


def test_connection(db=None, backend_factory=None) -> dict:
    """Valida configuração -> endpoint -> autenticação -> requisição aceita -> resposta válida.

    Usa o MESMO backend do pipeline (`TypeSafeBackend`, `POST {base_url}/v1/systemone`). Antes disso, se o backend
    tiver cliente SDK, lista os modelos (`GET /v1/models`, gratuito) para separar erro de auth de erro de requisição.
    """
    from app.services import offline
    from app.services.jev import JevService, TypeSafeBackend  # noqa: F401
    checks: list[dict] = []
    t0 = time.perf_counter()

    def finish(state: str, http: int | None, message: str, model: str | None = None) -> dict:
        res = {"ok": state == "connected", "state": state, "http_status": http, "message": message,
               "checks": checks, "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "model": model}
        if db is not None:
            db.set_kv(KV_LAST_TEST, {"state": state, "http_status": http, "message": message, "at": time.time(),
                                      "latency_ms": res["latency_ms"], "model": model, "fingerprint": _fingerprint()})
        audit.info("jev_setup_test state=%s http=%s", state, http)
        return res

    cfg = _current_cfg()
    try:
        cfg.validate()
        validate_base_url(os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL)
    except (ValueError, JevSetupError) as e:
        checks.append({"step": "config", "ok": False})
        return finish("not_configured", None, f"Configuração inválida: {getattr(e, 'message', e)}")
    if (cfg.backend == "typesafe" and not os.environ.get(KEY_ENV)
            and not _is_local(os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL)):
        checks.append({"step": "config", "ok": False})
        return finish("not_configured", None, "API Key não configurada.")
    checks.append({"step": "config", "ok": True})
    base = os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    try:
        offline.ensure_online("JEV test", base if cfg.backend == "typesafe" else cfg.local_host)
        backend = (backend_factory or _default_backend)(cfg)
        client = getattr(backend, "_client", None)
        if client is not None and hasattr(client, "models"):
            client.models.list()
            checks.append({"step": "endpoint_and_auth", "ok": True})
        questions = {"rel_0": {"instructions": {"candidate": {"source": "teste.md", "text": "Anamnésia usa o JEV para triagem."},
                                                "question": "Does this `candidate` help answer the `query`?"},
                              "criteria": {"true": "Relevant.", "false": "Not relevant."}}}
        answers, usage, model = backend.evaluate({"query": "O que é o Anamnésia?"}, questions)
        if not isinstance(answers.get("rel_0"), (int, float)) or not 0.0 <= float(answers["rel_0"]) <= 1.0:
            checks.append({"step": "response", "ok": False})
            return finish("unavailable", None, "O JEV respondeu, mas em formato inesperado.")
        checks.append({"step": "request_accepted", "ok": True})
        checks.append({"step": "response", "ok": True})
        return finish("connected", 200, "JEV conectado.", model)
    except Exception as e:  # noqa: BLE001 -- classificado; nunca propaga texto bruto (poderia ecoar cabeçalhos)
        state, http, msg = _classify(e)
        checks.append({"step": "auth" if state == "auth_error" else "request", "ok": False})
        return finish(state, http, msg)


def _default_backend(cfg):
    from app.services.jev import TypeSafeBackend
    from app.services.jev_ollama import make_backend
    return make_backend(cfg) or TypeSafeBackend(cfg)
