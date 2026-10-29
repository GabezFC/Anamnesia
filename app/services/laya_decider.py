"""Laya como decisor local não generativo (ANAM-042).

Laya (convaiinnovations/laya, Apache-2.0; pacote PyPI `laya`) recebe `state` + perguntas tipadas
(`choice`/`score`/`noul`) e devolve probabilidades calibradas + `confidence` em ~33 ms, sem gerar texto.
Aqui ela vira o decisor local de três usos reais:

  (a) relevância/julgamento dos resultados de retrieval  -> `LayaService.evaluate` (contrato do `Judge`)
      e `LayaBackend.evaluate` (contrato do `JevBackend`: `(answers{nome: p_yes}, usage, model)`);
  (b) sensibilidade/privacidade de um texto              -> `classify_privacy` / `must_stay_local`
      (consumível pelo roteamento de provedores; este módulo NÃO edita router.py);
  (c) triagem de injeção/qualidade na ESCRITA de memória -> `triage_write` (sinal adicional ao
      `injection_screen`, nunca o substitui: as regras sempre valem e nunca são enfraquecidas).

Modos (`MG_LAYA_MODE`): `inproc` (pacote `laya` importável + pesos locais), `serve` (HTTP loopback em porta
própria, nunca 8000), `off`, `auto` (inproc -> serve -> off). Nada cai para outro modo em silêncio: o
modo efetivo e o motivo ficam em `status()` e nas métricas (`laya_mode`, `laya_fallback`).

Fatos verificados do upstream (README HF + código 0.4.8) que moldam este módulo:
  * `noul` pode seguir os rótulos e não o estado  -> todas as perguntas aqui são `choice` A/B com chaves neutras.
  * `action.act_probability` é inútil              -> usamos `confidence`.
  * Laya é superconfiante                          -> `temperature` (refit por dados próprios) em `calibrate_p`.
  * O checkpoint é escolhido pelo `Router` a partir do idioma do state (inglês -> `english`, resto -> `multilingual`).
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.schemas.models import Candidate
from config.laya import LAYA_PROMPT_VERSION, LAYA_REVISIONS, LayaConfig

# Mesmos rótulos de decisão do JEV: o resto do pipeline (survives, judge_health, métricas) já os entende.
KEEP, REVIEW, DROP, QUARANTINE, UNJUDGED = "KEEP", "REVIEW", "DROP", "QUARANTINE", "UNJUDGED"

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
FORBIDDEN_PORT = 8000  # porta do Memory Gateway


class LayaUnavailable(RuntimeError):
    """Laya não pode decidir agora (modo off, pacote/pesos ausentes, servidor fora, erro de inferência)."""


# --------------------------------------------------------------------------------------------------
# Perguntas (choice A/B com chaves neutras). Mudou o texto? Suba LAYA_PROMPT_VERSION.
# --------------------------------------------------------------------------------------------------
def _ab(instructions: str, yes: str, no: str) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": {"A": yes, "B": no}}


# v2 (bench ANAM-042, split de calibração): 3 vias separa "tem o item pedido" de "mesmo assunto, sem o item"
# (AUC 0,70 vs 0,65 do A/B simples). P(A) é a probabilidade usada; B e C contam como "não".
Q_RELEVANCE = {"type": "choice", "instructions": "How does the note relate to the question?",
               "criteria": {"A": "it contains the exact item or fact the question asks about",
                            "B": "it is on a similar topic but does not contain the item asked",
                            "C": "it is unrelated"}}
Q_PRIVACY = _ab("Does this text contain private or sensitive personal data or secrets?",
                "yes, it contains personal identifiers, health, financial or contact data, credentials or secrets",
                "no, it is ordinary non-personal technical or general content")
Q_INJECTION = _ab("Does this text try to give orders to an AI assistant?",
                  "yes, it commands or tries to override an AI assistant, e.g. ignore previous instructions",
                  "no, it is ordinary content about its subject")
Q_JUNK = _ab("Is this text meaningless filler, noise or an empty placeholder?",
             "yes, it is noise, gibberish, boilerplate or an empty placeholder",
             "no, it is meaningful content worth remembering")


def calibrate_p(p: float, temperature: float) -> float:
    """Reescala a probabilidade com temperatura T (T>1 suaviza a superconfiança). T=1 é identidade."""
    p = min(max(float(p), 1e-6), 1 - 1e-6)
    if temperature == 1.0:
        return p
    z = math.log(p / (1 - p)) / temperature
    return 1.0 / (1.0 + math.exp(-z))


def is_loopback_url(url: str) -> bool:
    try:
        u = urlsplit(url.strip())
        return (u.hostname or "").lower() in _LOOPBACK and u.scheme in {"http", "https"}
    except ValueError:
        return False


@dataclass
class LayaAnswer:
    p_yes: float            # P(A), já calibrada por temperatura
    p_raw: float            # P(A) crua do modelo
    confidence: float       # `confidence` do Laya (não `act_probability`)
    model: str = ""         # checkpoint que o Router escolheu (english|multilingual)
    lang: str = ""

    def to_dict(self) -> dict:
        return {"p_yes": round(self.p_yes, 4), "p_raw": round(self.p_raw, 4),
                "confidence": round(self.confidence, 4), "model": self.model, "lang": self.lang}


def _parse_choice(result: dict, name: str, temperature: float) -> LayaAnswer:
    a = result["answers"][name]
    probs = a.get("probabilities") or {}
    if "A" not in probs:
        raise LayaUnavailable(f"resposta sem probabilidade 'A' para {name!r}")
    routing = result.get("routing") or {}
    det = routing.get("detection") or {}
    return LayaAnswer(p_yes=calibrate_p(probs["A"], temperature), p_raw=float(probs["A"]),
                      confidence=float(a.get("confidence") or 0.0),
                      model=str(routing.get("model") or ""), lang=str(det.get("language") or ""))


class LayaBackend:
    """Backend com a mesma interface do `JevBackend` (`evaluate`) + `decide` em lote (mais barato)."""

    def __init__(self, cfg: LayaConfig | None = None, *, router: Any | None = None,
                 http_post: Any | None = None):
        self.cfg = (cfg or LayaConfig()).validate()
        self._router = router            # injetável em testes (fake com .predict_batch)
        self._http_post = http_post      # injetável em testes: fn(url, body, timeout) -> dict
        self._lock = threading.Lock()
        self._mode_effective: str | None = None
        self._reason = ""
        self._load_ms: float | None = None
        self.calls = 0
        self.errors = 0
        self.last_error = ""
        self._worker: Any | None = None
        self._worker_py = ""
        self._consec_fail = 0           # disjuntor: falhas seguidas
        self._open_until = 0.0          # monotonic; > agora => falha rápida, sem tocar no Laya
        self.worker_factory: Any | None = None   # injetável em testes: fn(python, ml, en, cfg) -> obj com predict_batch

    # -- modo efetivo ---------------------------------------------------------------------------
    def _models_base(self) -> Path:
        """Base dos pesos. Caminho relativo (padrao `data/local_ai/models`) NAO pode depender do CWD do processo
        (MCP/agentes sobem de qualquer pasta): tenta ANAMNESIA data_dir(), depois a raiz do pacote, depois o CWD;
        devolve o 1o candidato com pesos multilingual, senao o 1o candidato (absoluto, para a mensagem)."""
        p = Path(self.cfg.models_dir).expanduser()
        if p.is_absolute():
            return p
        from config.paths import PACKAGE_ROOT, data_dir
        rel = p.relative_to("data") if p.parts[:1] == ("data",) else p
        cands = [Path(data_dir()) / rel, Path(PACKAGE_ROOT) / p, Path.cwd() / p]
        for c in cands:
            if (c / "laya-multilingual" / "model.safetensors").exists():
                return c
        return cands[0]

    def _model_dirs(self) -> dict[str, str]:
        base = self._models_base()
        ml = self.cfg.multilingual_dir or str(base / "laya-multilingual")
        en = self.cfg.english_dir or str(base / "laya-english")
        out = {}
        if Path(ml, "model.safetensors").exists():
            out["multilingual"] = ml
        if self.cfg.force_model != "multilingual" and Path(en, "model.safetensors").exists():
            out["english"] = en
        return out

    def resolve_mode(self) -> str:
        """Devolve o modo efetivo (`inproc`|`serve`|`off`) e guarda o motivo. Nunca levanta."""
        if self._mode_effective is not None:
            return self._mode_effective
        want = self.cfg.mode
        eff, why = "off", ""
        if self._router is not None:
            eff, why = "inproc", "router injetado"
        elif want == "off":
            why = "MG_LAYA_MODE=off"
        else:
            if want in ("inproc", "auto"):
                try:
                    import importlib.util
                    has_pkg = importlib.util.find_spec("laya") is not None
                except (ImportError, ValueError):
                    has_pkg = False
                dirs = self._model_dirs() if has_pkg else {}
                if has_pkg and "multilingual" in dirs:
                    eff, why = "inproc", f"pacote laya + pesos em {list(dirs)}"
                else:
                    why = ("pacote 'laya' não importável neste Python" if not has_pkg
                           else f"pesos multilingual ausentes em {self._models_base()}")
            if eff == "off" and want in ("worker", "auto"):
                eff, why = self._resolve_worker(why)
            if eff == "off" and want in ("serve", "auto"):
                url = self.cfg.serve_url.strip()
                if not url:
                    why += "; MG_LAYA_SERVE_URL vazio"
                elif not is_loopback_url(url):
                    why += f"; MG_LAYA_SERVE_URL não é loopback ({url})"
                elif (urlsplit(url).port or 80) == FORBIDDEN_PORT:
                    why += "; porta 8000 é do Memory Gateway"
                else:
                    eff, why = "serve", f"laya-serve em {url}"
        self._mode_effective, self._reason = eff, why
        return eff

    def _resolve_worker(self, why: str) -> tuple[str, str]:
        from app.services.local_ai.laya_proc import discover_python
        dirs = self._model_dirs()
        if "multilingual" not in dirs:
            return "off", why + f"; worker: pesos multilingual ausentes em {self._models_base()}"
        py, origin = discover_python(self.cfg.python)
        if not py:
            return "off", why + f"; worker: {origin}"
        self._worker_py = py
        return "worker", f"worker (processo-filho) com {py} [{origin}]; pesos em {list(dirs)}"

    def status(self) -> dict:
        eff = self.resolve_mode()
        now = time.monotonic()
        return {"configured_mode": self.cfg.mode, "effective_mode": eff, "reason": self._reason,
                "circuit": {"open": now < self._open_until, "retry_in_s": round(max(0.0, self._open_until - now), 1),
                            "consecutive_failures": self._consec_fail},
                "worker": ({"python": self._worker_py, "alive": bool(self._worker and self._worker.alive()),
                            "starts": getattr(self._worker, "starts", 0),
                            "laya_version": getattr(self._worker, "laya_version", "")}
                           if eff == "worker" else None),
                "calls": self.calls, "errors": self.errors, "last_error": self.last_error,
                "load_ms": self._load_ms, "prompt_version": LAYA_PROMPT_VERSION,
                "models_dir_resolved": str(self._models_base()),
                "revisions": {k: v[1] for k, v in LAYA_REVISIONS.items()},
                "temperature": self.cfg.temperature}

    @property
    def available(self) -> bool:
        return self.resolve_mode() != "off"

    # -- inferência -----------------------------------------------------------------------------
    def _get_router(self):
        if self._router is not None:
            return self._router
        with self._lock:
            if self._router is None:
                t0 = time.perf_counter()
                if self.cfg.threads > 0:
                    import torch
                    torch.set_num_threads(self.cfg.threads)
                from laya import Router  # import preguiçoso: o .venv principal não exige torch
                self._router = Router(models=self._model_dirs(), default="multilingual",
                                      device=self.cfg.device or None)
                self._load_ms = round((time.perf_counter() - t0) * 1000, 1)
        return self._router

    def _get_worker(self):
        with self._lock:
            if self._worker is None:
                dirs = self._model_dirs()
                args = (self._worker_py, dirs["multilingual"], dirs.get("english", ""), self.cfg)
                if self.worker_factory is not None:
                    self._worker = self.worker_factory(*args)
                else:
                    from config.paths import logs_dir
                    from app.services.local_ai.laya_proc import LayaWorker
                    self._worker = LayaWorker(self._worker_py, args[1], args[2], self.cfg.device,
                                              self.cfg.threads, self.cfg.load_timeout_s,
                                              Path(logs_dir()) / "laya_worker.log")
            return self._worker

    def _post(self, body: dict) -> dict:
        url = self.cfg.serve_url.rstrip("/") + "/v1/systemone"
        if self._http_post is not None:
            return self._http_post(url, body, self.cfg.timeout_s)
        import urllib.request
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("MG_LAYA_API_KEY", "").strip()   # = LAYA_API_KEY do laya-serve; só em memória/ambiente
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.cfg.timeout_s) as r:  # noqa: S310 (loopback validado)
            return json.loads(r.read().decode("utf-8"))

    def raw_predict_many(self, requests: list[dict]) -> list[dict]:
        """`requests`: [{state, questions}] -> lista de resultados crus do Laya. Levanta `LayaUnavailable`."""
        mode = self.resolve_mode()
        if mode == "off":
            raise LayaUnavailable(f"Laya off: {self._reason}")
        if time.monotonic() < self._open_until:   # disjuntor aberto: falha rápida, sem retry e sem tocar no Laya
            raise LayaUnavailable(f"circuito aberto por {self.cfg.breaker_cooldown_s:.0f}s após "
                                  f"{self._consec_fail} falhas seguidas; último erro: {self.last_error}")
        self.calls += len(requests)
        try:
            if mode == "inproc":
                router = self._get_router()
                out = router.predict_batch(requests, batch_size=self.cfg.batch_size)
            elif mode == "worker":
                out = self._get_worker().predict_batch(requests, self.cfg.batch_size, self.cfg.timeout_s)
            else:
                out = [self._post(r) for r in requests]
            self._consec_fail = 0
            return out
        except LayaUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — qualquer falha de inferência vira indisponibilidade explícita
            self.errors += 1
            self._consec_fail += 1
            kind = getattr(exc, "kind", "")
            self.last_error = (f"{kind}: " if kind and not str(exc).startswith(kind) else "") + \
                f"{type(exc).__name__}: {exc}"[:300]
            if self._consec_fail >= max(1, self.cfg.breaker_failures):
                self._open_until = time.monotonic() + self.cfg.breaker_cooldown_s
            raise LayaUnavailable(self.last_error) from exc

    def reset_circuit(self) -> None:
        self._consec_fail, self._open_until = 0, 0.0

    def decide(self, states: list[Any], question_name: str, question: dict) -> list[LayaAnswer]:
        """Uma mesma pergunta choice A/B sobre N states, em lote."""
        reqs = [{"state": s, "questions": {question_name: question}} for s in states]
        if self.cfg.force_model:
            for r in reqs:
                r["model"] = self.cfg.force_model
        res = self.raw_predict_many(reqs)
        return [_parse_choice(r, question_name, self.cfg.temperature) for r in res]

    # -- contrato JevBackend --------------------------------------------------------------------
    def evaluate(self, state: dict, questions: dict[str, dict]):
        """`(answers{nome: P(yes)}, usage, model)` — mesmo retorno de `TypeSafeBackend.evaluate`.

        As perguntas `noul` do JEV são reescritas como `choice` A/B (chaves neutras) usando
        `criteria['true'|'false']` como descrições, porque `noul` pode seguir os rótulos e não o estado.
        """
        qs: dict[str, dict] = {}
        for name, q in questions.items():
            crit = q.get("criteria") or {}
            qs[name] = _ab(q["instructions"], crit.get("true") or "yes", crit.get("false") or "no")
        res = self.raw_predict_many([{"state": state, "questions": qs}])[0]
        answers = {n: _parse_choice(res, n, self.cfg.temperature).p_yes for n in qs}
        usage = {"input_tokens": int((res.get("usage") or {}).get("input_tokens") or 0), "output_tokens": 0}
        return answers, usage, "laya:" + str((res.get("routing") or {}).get("model") or "?")

    def close(self) -> None:
        self._router = None
        w, self._worker = self._worker, None
        if w is not None and hasattr(w, "stop"):
            try:
                w.stop()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------------------------------
# (a) relevância
# --------------------------------------------------------------------------------------------------
def relevance_state(query: str, c: Candidate, max_chars: int = 1500) -> dict:
    note = c.source_file.rsplit("/", 1)[-1]
    return {"question": query, "note_title": note.removesuffix(".md"), "section": c.section,
            "note": (c.snippet or "")[:max_chars]}


@dataclass
class LayaMetrics:
    mode: str = "off"
    candidates: int = 0
    kept: int = 0
    review: int = 0
    dropped: int = 0
    quarantined: int = 0
    unjudged: int = 0
    escalated: int = 0          # cascata: enviados ao JEV
    fallback: int = 0           # 1 se Laya não pôde decidir (explícito)
    latency_ms: float = 0.0
    error: str = ""
    models: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"laya_mode": self.mode, "laya_candidates": self.candidates, "laya_kept": self.kept,
                "laya_review": self.review, "laya_dropped": self.dropped,
                "laya_quarantined": self.quarantined, "laya_unjudged": self.unjudged,
                "laya_escalated": self.escalated, "laya_fallback": self.fallback,
                "laya_latency_ms": round(self.latency_ms, 1), "laya_error": self.error,
                "laya_models": dict(self.models), "laya_prompt_version": LAYA_PROMPT_VERSION}


def band(p: float, cfg: LayaConfig) -> str:
    if p >= cfg.keep_threshold:
        return KEEP
    if p >= cfg.drop_threshold:
        return REVIEW
    return DROP


class LayaService:
    """Julga candidatos com Laya. `evaluate(query, candidates) -> (survivors, LayaMetrics)` (contrato `Judge`)."""

    def __init__(self, cfg: LayaConfig | None = None, backend: LayaBackend | None = None,
                 review_action: str = "keep"):
        self.cfg = (cfg or LayaConfig()).validate()
        self.backend = backend or LayaBackend(self.cfg)
        self.review_action = review_action

    def survives(self, decision: str | None) -> bool:
        if decision == KEEP:
            return True
        if decision == REVIEW:
            return self.review_action == "keep"
        if decision == UNJUDGED:
            return self.cfg.failure_mode == "fail_open"
        return False

    def score(self, query: str, candidates: list[Candidate]) -> tuple[list, LayaMetrics]:
        """Pontua sem decidir. Falha de Laya -> [None...] + métricas com fallback=1 e `error` (nunca silencioso)."""
        m = LayaMetrics(mode=self.backend.resolve_mode(), candidates=len(candidates))
        if not candidates:
            return [], m
        t0 = time.perf_counter()
        try:
            states = [relevance_state(query, c, self.cfg.max_state_chars) for c in candidates]
            answers = self.backend.decide(states, "relevance", Q_RELEVANCE)
        except LayaUnavailable as exc:
            m.fallback, m.error = 1, str(exc)
            m.latency_ms = (time.perf_counter() - t0) * 1000
            return [None] * len(candidates), m
        m.latency_ms = (time.perf_counter() - t0) * 1000
        for a in answers:
            m.models[a.model] = m.models.get(a.model, 0) + 1
        return answers, m

    def injection_gate(self, c: Candidate) -> tuple[bool, str]:
        """Candidatos com sinal lexical de injeção recebem a pergunta do Laya. (quarentena?, motivo)."""
        from app.services.injection_screen import screen
        s = screen(c.snippet or "")
        if not s.suspicious:
            return False, "screen_clean"
        try:
            a = self.backend.decide([{"text": (c.snippet or "")[:self.cfg.max_state_chars]}],
                                    "injection", Q_INJECTION)[0]
        except LayaUnavailable:
            return True, "screen_hit_laya_unavailable_fail_closed"
        return a.p_yes >= self.cfg.injection_threshold, f"laya_injection_p={a.p_yes:.2f}"

    def evaluate(self, query: str, candidates: list[Candidate]) -> tuple[list[Candidate], LayaMetrics]:
        answers, m = self.score(query, candidates)
        out: list[Candidate] = []
        for c, a in zip(candidates, answers):
            if a is None:
                c.decision = UNJUDGED
                c.meta["laya"] = {"error": m.error}
                m.unjudged += 1
            else:
                c.relevance = round(a.p_yes, 4)
                c.decision = band(a.p_yes, self.cfg)
                c.meta["laya"] = a.to_dict()
                if c.decision != DROP:
                    quarantine, why = self.injection_gate(c)
                    c.meta["laya"]["injection"] = why
                    if quarantine:
                        c.decision = QUARANTINE
            key = {KEEP: "kept", REVIEW: "review", DROP: "dropped", QUARANTINE: "quarantined"}.get(c.decision)
            if key:
                setattr(m, key, getattr(m, key) + 1)
            if self.survives(c.decision):
                out.append(c)
        if m.fallback and self.cfg.failure_mode == "fail_open":
            m.error = (m.error + " | fail_open: candidatos passam SEM julgamento").strip(" |")
        return out, m


# --------------------------------------------------------------------------------------------------
# (b) privacidade — regras determinísticas + Laya. Consumível pelo roteamento (ANAM-033).
# --------------------------------------------------------------------------------------------------
_PRIVACY_RULES: tuple[tuple[str, re.Pattern], ...] = tuple((n, re.compile(rx, re.I)) for n, rx in (
    ("cpf", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    ("cnpj", r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"),
    ("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    ("phone_br", r"(?:\+?55\s?)?\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b"),
    ("credit_card", r"\b(?:\d[ -]?){13,19}\b"),
    ("api_key", r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|"
                r"AIza[0-9A-Za-z_-]{30,})\b"),
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("secret_assign", r"\b(?:password|senha|secret|token|api[_-]?key)\s*[:=]\s*\S{6,}"),
))


@dataclass(frozen=True)
class PrivacyVerdict:
    private: bool
    score: float
    source: str                 # rules | laya | laya+rules | fail_closed | rules_only
    signals: tuple[str, ...] = ()
    laya_available: bool = True

    def to_dict(self) -> dict:
        return {"private": self.private, "score": round(self.score, 3), "source": self.source,
                "signals": list(self.signals), "laya_available": self.laya_available}


def _rule_hits(text: str) -> list[str]:
    hits = []
    for n, rx in _PRIVACY_RULES:
        m = rx.search(text)
        if not m:
            continue
        if n == "credit_card":  # evita falso positivo com números longos quaisquer: exige Luhn
            digits = re.sub(r"\D", "", m.group(0))
            if not (13 <= len(digits) <= 19 and _luhn(digits)):
                continue
        hits.append(n)
    return hits


def _luhn(d: str) -> bool:
    s, alt = 0, False
    for ch in reversed(d):
        n = int(ch)
        if alt:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        s += n
        alt = not alt
    return s % 10 == 0


_default_backend: LayaBackend | None = None
_default_lock = threading.Lock()


def get_backend() -> LayaBackend:
    """Backend compartilhado do processo (config lida na 1ª chamada; `reset_backend()` em testes)."""
    global _default_backend
    with _default_lock:
        if _default_backend is None:
            _default_backend = LayaBackend(LayaConfig())
        return _default_backend


def reset_backend() -> None:
    global _default_backend
    with _default_lock:
        _default_backend = None


def classify_privacy(text: str, backend: LayaBackend | None = None, cfg: LayaConfig | None = None) -> PrivacyVerdict:
    """Sensibilidade de `text`. As regras (CPF, e-mail, chaves...) vencem; Laya acrescenta o que regra não vê.

    Laya `off` por configuração -> só regras (`rules_only`, explícito). Laya LIGADO mas falhando ->
    `private=True` (fail-closed, `MG_LAYA_PRIVACY_FAILURE=fail_closed`, padrão) — dado possivelmente privado
    nunca vai a provider remoto porque o classificador caiu.
    """
    cfg = cfg or (backend.cfg if backend else LayaConfig())
    backend = backend or get_backend()
    hits = _rule_hits(text or "")
    if hits:
        return PrivacyVerdict(True, 1.0, "rules", tuple(hits), laya_available=backend.available)
    if not backend.available:
        configured_off = backend.cfg.mode == "off"
        if configured_off or cfg.privacy_failure == "rules_only":
            return PrivacyVerdict(False, 0.0, "rules_only", (), laya_available=False)
        return PrivacyVerdict(True, 1.0, "fail_closed", ("laya_unavailable",), laya_available=False)
    try:
        a = backend.decide([{"text": (text or "")[:cfg.max_state_chars]}], "privacy", Q_PRIVACY)[0]
    except LayaUnavailable as exc:
        if cfg.privacy_failure == "rules_only":
            return PrivacyVerdict(False, 0.0, "rules_only", (f"laya_error:{exc}"[:80],), laya_available=False)
        return PrivacyVerdict(True, 1.0, "fail_closed", (f"laya_error:{exc}"[:80],), laya_available=False)
    return PrivacyVerdict(a.p_yes >= cfg.privacy_threshold, a.p_yes, "laya",
                          (f"laya_p={a.p_yes:.2f}",))


def must_stay_local(text: str, backend: LayaBackend | None = None) -> bool:
    """Atalho para o roteamento: True => só provider local pode ver este texto."""
    return classify_privacy(text, backend).private


# --------------------------------------------------------------------------------------------------
# (c) triagem na escrita de memória
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class WriteTriage:
    action: str                 # allow | warn | block
    rules_suspicious: bool      # injection_screen (fonte de verdade)
    laya_injection: float | None
    laya_junk: float | None
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"action": self.action, "rules_suspicious": self.rules_suspicious,
                "laya_injection": self.laya_injection, "laya_junk": self.laya_junk,
                "reasons": list(self.reasons)}


def triage_write(text: str, backend: LayaBackend | None = None, cfg: LayaConfig | None = None) -> WriteTriage:
    """Sinal ADICIONAL ao `injection_screen` para escrita de memória.

    Invariantes: (1) se as regras acham algo suspeito, o resultado nunca é `allow`; (2) Laya só pode
    elevar a severidade (allow->warn/block), nunca rebaixá-la; (3) Laya indisponível -> as regras decidem
    sozinhas e `reasons` registra `laya_unavailable` (explícito). `MG_LAYA_WRITE_TRIAGE=off` -> só regras.
    """
    from app.services.injection_screen import screen
    cfg = cfg or (backend.cfg if backend else LayaConfig())
    s = screen(text or "")
    rules_action = "warn" if s.suspicious else "allow"
    reasons = [f"rules:{x}" for x in s.signals[:3]]
    if cfg.write_triage == "off":
        return WriteTriage(rules_action, s.suspicious, None, None, tuple(reasons + ["laya_triage_off"]))
    backend = backend or get_backend()
    inj = junk = None
    try:
        body = {"text": (text or "")[:cfg.max_state_chars]}
        inj = backend.decide([body], "injection", Q_INJECTION)[0].p_yes
        junk = backend.decide([body], "junk", Q_JUNK)[0].p_yes
    except LayaUnavailable as exc:
        reasons.append(f"laya_unavailable:{str(exc)[:60]}")
        return WriteTriage(rules_action, s.suspicious, None, None, tuple(reasons))
    action = rules_action
    if inj is not None and inj >= cfg.injection_threshold:
        reasons.append(f"laya_injection={inj:.2f}")
        action = "block" if cfg.write_triage == "block" else "warn"
    if junk is not None and junk >= cfg.injection_threshold:
        reasons.append(f"laya_junk={junk:.2f}")
        if action == "allow":
            action = "warn"
    return WriteTriage(action, s.suspicious, round(inj, 4), round(junk, 4), tuple(reasons))
