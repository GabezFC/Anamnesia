"""ANA-238: local-first grade (L0-L5) published by `anamnesia doctor`. Pure, offline, no secret values.

The scale is NOT defined elsewhere in the repo, so it is defined here (and in Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/ENVIRONMENT.md)):

  L0  reserved: retrieval/storage would depend on a remote service (never true for this product).
  L1  reserved: storage local but retrieval needs a network service (never true: FTS5/BM25 is local).
  L2  local retrieval/storage, but an EXTERNAL inference (the JEV judge, `typesafe_sdk`) is active in the
      promoted path -> data may leave the machine.
  L3  everything default runs locally and nothing external is configured, but nothing PREVENTS an external call
      (OFFLINE not enforced).
  L4  as L3 AND the OFFLINE=1 guard is active (ANA-224): no external call can leave the process.
  L5  as L4 AND a local inference runtime (Ollama/vLLM) is present, so answer/judge can also be local.

Hard rule (tested): an active JEV judge (TYPESAFE_API_KEY set, calls not blocked) => level <= L3 (it is L2).
"""
from __future__ import annotations

import os
import shutil

from app.services.offline import offline_enabled

LEVELS = {
    0: "L0 reservado (recuperação remota)",
    1: "L1 reservado (armazenamento local, recuperação remota)",
    2: "L2 recuperação local; inferência externa (juiz JEV) ativa",
    3: "L3 tudo local por configuração; sem garantia OFFLINE",
    4: "L4 local com OFFLINE=1 garantido",
    5: "L5 local com OFFLINE=1 e runtime de modelo local",
}
_OFF = {"0", "false", "no", "off"}
_HOSTED_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")


def _paid_blocked(env) -> bool:
    return str(env.get("ANAMNESIA_PAID_CALLS", "")).strip().lower() in _OFF


def assess(env: dict | None = None, which=shutil.which) -> dict:
    """Capabilities (local / network / off) and the resulting level. Never includes secret values."""
    e = os.environ if env is None else env
    offline = offline_enabled(e)
    blocked = offline or _paid_blocked(e)
    jev_key = bool(e.get("TYPESAFE_API_KEY"))
    from app.services.jev import is_local_base_url   # ANAM-041: juiz em loopback nao e inferencia externa
    jev_local = is_local_base_url(e.get("TYPESAFE_BASE_URL"))
    jev_active = jev_key and not blocked and not jev_local
    local_runtime = bool(which("ollama") or e.get("VLLM_BASE_URL") or e.get("OLLAMA_HOST"))
    hosted = [k for k in _HOSTED_KEYS if e.get(k)]

    caps = {
        "retrieval": {"where": "local", "detail": "SQLite FTS5/BM25 no disco"},
        "storage": {"where": "local", "detail": "SQLite + pasta própria; vault somente leitura"},
        "graph": {"where": "local" if which("graphify") else "off",
                  "detail": "graphify local" if which("graphify") else "graphify ausente (opcional)"},
        "jev_judge": {"where": "local" if jev_local else "network" if jev_active else "off",
                      "detail": ("juiz JEV em loopback (TYPESAFE_BASE_URL local; chave dispensada)" if jev_local else
                                 "typesafe_sdk (inferência externa) ativo" if jev_active else
                                 "bloqueado por OFFLINE/PAID_CALLS=0" if jev_key else "sem TYPESAFE_API_KEY")},
        "local_models": {"where": "local" if local_runtime else "off",
                         "detail": "runtime local detectado (sem sondar a rede)" if local_runtime
                         else "nenhum runtime local detectado"},
        "hosted_models": {"where": "network" if (hosted and not blocked) else "off",
                          "detail": ("chaves de provedor configuradas: " + ", ".join(hosted)) if hosted
                          else "sem chave de provedor hospedado"},
    }
    external_active = jev_active or bool(hosted and not blocked)
    if jev_active:
        level = 2
    elif external_active:
        level = 3
    elif offline:
        level = 5 if local_runtime else 4
    else:
        level = 3
    if level > 3 and external_active:  # defensive: the rule can never be broken by a later edit
        level = 3
    return {"level": level, "label": LEVELS[level], "offline_enforced": offline, "capabilities": caps}
