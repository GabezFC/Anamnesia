"""Colibri por API real (ANAM-041/ANAM-046): judge System One em servidor JÁ EM EXECUÇÃO.

Diferenças para o caminho `TYPESAFE_BASE_URL` (app/services/jev.TypeSafeBackend):
- a URL vem de `MG_COLIBRI_URL` (config/colibri.py), NUNCA herdada do JEV pago;
- loopback obrigatório (host.docker.internal só com MG_COLIBRI_ALLOW_DOCKER_HOST=1, para Docker);
- retry limitado por config (0..2; padrão 1) — sem loops de retry;
- `status()` faz UMA sondagem barata (GET /v1/models, sem julgamento) e rotula o resultado;
- habilitar/desabilitar por `MG_COLIBRI_ENABLED` (off por padrão).
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

from config.colibri import ColibriConfig, load_colibri_config

STATUS_LABELS = ("MEASURED", "UNAVAILABLE", "OFF")

_LOCAL_KEY_DEFAULT = "local"   # o SDK exige chave não vazia; Colibri sem COLI_API_KEY aceita qualquer


class ColibriUnavailable(RuntimeError):
    """Colibri desabilitado, fora do ar ou recusado pela política."""


class ColibriJudgeBackend:
    """Mesma interface de `JevBackend` (evaluate/close), apontando explicitamente para o Colibri."""

    def __init__(self, cfg: ColibriConfig | None = None, client_factory=None):
        self.cfg = cfg or load_colibri_config()
        self.cfg.validate()
        if not self.cfg.enabled:
            raise ColibriUnavailable("Colibri desabilitado (MG_COLIBRI_ENABLED=off)")
        self._client = None
        self._factory = client_factory   # injetável em testes: fn(base_url, api_key, model, timeout, retries)
        self.calls = 0
        self.errors = 0
        self.last_error = ""

    def _get_client(self):
        if self._client is None:
            import os
            from typesafe_sdk import RetryPolicy, TypeSafeClient
            key = (self.cfg.api_key or os.environ.get("MG_COLIBRI_API_KEY") or _LOCAL_KEY_DEFAULT)
            if self._factory is not None:
                self._client = self._factory(self.cfg.url, key, self.cfg.model, self.cfg.timeout_s,
                                             self.cfg.max_retries)
            else:
                self._client = TypeSafeClient(
                    model=self.cfg.model, retry=RetryPolicy(max_retries=self.cfg.max_retries),
                    timeout=self.cfg.timeout_s, base_url=self.cfg.url.rstrip("/"), api_key=key)
        return self._client

    @staticmethod
    def build_question(q: dict):
        """Dict de pergunta -> objeto do SDK, respeitando `type` (noul|choice|score).

        Antes só `Noul` era construído e `criteria={'A':..,'B':..}` (formato choice A/B da Laya) caía em
        NoulCriteria (só aceita 'true'/'false') -> ValidationError ANTES da rede (ANAM-046 H1).
        """
        from typesafe_sdk import Choice, Noul, NoulCriteria, Score
        kind = (q.get("type") or "noul").lower()
        crit = q.get("criteria")
        if kind == "choice":
            if not crit:
                raise ValueError("pergunta choice exige criteria {rótulo: descrição}")
            return Choice(instructions=q.get("instructions"), criteria=dict(crit))
        if kind == "score":
            if not crit:
                raise ValueError("pergunta score exige criteria [níveis]")
            return Score(instructions=q.get("instructions"), criteria=list(crit))
        if kind != "noul":
            raise ValueError(f"tipo de pergunta desconhecido: {kind!r}")
        return Noul(instructions=q.get("instructions"), criteria=NoulCriteria(**crit) if crit else None)

    @staticmethod
    def extract_answers(resp) -> dict[str, float]:
        """Contrato JevBackend: {nome: P(yes)}. noul -> noul; choice -> P('A') (convenção Laya A/B); score -> nível/(n-1)."""
        out: dict[str, float] = {name: float(a.noul) for name, a in resp.nouls.items()}
        for name, a in resp.choices.items():
            probs = a.probabilities or {}
            if "A" not in probs:
                raise ColibriUnavailable(f"resposta choice sem probabilidade 'A' para {name!r}")
            out[name] = float(probs["A"])
        for name, a in resp.scores.items():
            n = max(1, len(a.probabilities or {}) - 1)
            out[name] = float(a.score) / n
        return out

    def evaluate(self, state, questions):
        qs = {name: self.build_question(q) for name, q in questions.items()}
        self.calls += 1
        t0 = time.perf_counter()
        try:
            resp = self._get_client().system_one(state=state, questions=qs, model=self.cfg.model)
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            raise ColibriUnavailable(self.last_error) from exc
        answers = self.extract_answers(resp)
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        _ = time.perf_counter() - t0   # latência fica nas métricas do JevService (JevMetrics.latency_ms)
        return answers, usage, resp.model

    def close(self) -> None:
        c, self._client = self._client, None
        if c is not None and hasattr(c, "close"):
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass


def _probe(url: str, timeout_s: float) -> tuple[bool, str, list[str]]:
    """GET /v1/models (sem julgamento, custo 0). Retorna (ok, detalhe, modelos)."""
    try:
        import os
        import httpx
        from app.services.egress import check_egress   # destino local passa mesmo em OFFLINE=1
        check_egress(url, "colibri_status")
        headers = {}
        key = os.environ.get("MG_COLIBRI_API_KEY", "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        r = httpx.get(url.rstrip("/") + "/v1/models", headers=headers, timeout=timeout_s)
        if r.status_code == 404:   # build sem /v1/models: /health decide
            h = httpx.get(url.rstrip("/") + "/health", headers=headers, timeout=timeout_s)
            return (h.status_code == 200 and h.json().get("status") == "ok",
                    f"health={h.status_code}", [])
        r.raise_for_status()
        models = [m.get("id", "") for m in r.json().get("data", []) if isinstance(m, dict)]
        return True, "ok", models
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:160], []


def colibri_status(cfg: ColibriConfig | None = None, probe=None) -> dict:
    """Estado SEM julgar. `probe` injetável (testes). Nunca devolve a chave."""
    c = cfg or load_colibri_config()
    out = {"provider": "colibri", "enabled": c.enabled, "url_host": urlsplit(c.url).netloc,
           "model": c.model, "timeout_s": c.timeout_s, "max_retries": c.max_retries,
           "api_key_set": bool(c.api_key), "config_version": c.config_version}
    if not c.enabled:
        out.update({"label": "OFF", "available": False, "reachable": None,
                    "reason": "desabilitado (MG_COLIBRI_ENABLED=off)"})
        return out
    ok, detail, models = (probe(c.url, 5.0) if probe else _probe(c.url, 5.0))
    out.update({"label": "MEASURED" if ok else "UNAVAILABLE", "available": ok, "reachable": ok,
                "models": models[:10], "reason": detail if not ok else "",
                "quality": "NAO MEDIDO: nenhum benchmark do Anamnesia rodou com Colibri "
                           "(Cérebro IA: Anamnesia/Guias-de-usuario-2026-10-24/JEV_LOCAL.md)"})
    return out


def colibri_jev_service(cfg: ColibriConfig | None = None, backend=None):
    """JevService completo com backend Colibri (mesma pipeline/cache do JEV, custo 0)."""
    from app.services.jev import JevService
    from config.jev import JevConfig
    c = cfg or load_colibri_config()
    jc = JevConfig(model=c.model, backend="typesafe", failure_mode="fail_closed",
                   max_retries=c.max_retries, timeout_s=c.timeout_s)
    jc.validate()
    return JevService(jc, backend or ColibriJudgeBackend(c))


_jev_cache: dict = {}
_lock = threading.Lock()


def colibri_provider_factory(cfg: ColibriConfig | None = None):
    """Fábrica para o Decision Engine: devolve um JevService Colibri ou levanta ColibriUnavailable."""
    def factory():
        with _lock:
            svc = _jev_cache.get("svc")
            if svc is None:
                svc = colibri_jev_service(cfg)
                _jev_cache["svc"] = svc
            return svc
    return factory
