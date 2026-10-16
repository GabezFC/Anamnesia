"""ANAM-013 / AUD-029..032, AUD-181, AUD-187, AUD-188: modelo de memória do Anamnésia.

Camada pura e determinística (zero token) sobre o `SavedContextStore`; a escrita continua passando pelo
único caminho `store._mutate` (snapshot + escrita atômica). Este módulo NÃO importa o `store` no topo
(o `store` importa as constantes daqui).

  * ciclo de vida   candidate -> active -> reinforced -> stale -> archived -> superseded -> deleted,
                    com tabela de transições validada (`validate_transition`, `transition`) e trilha
                    de eventos em `<state>/memory_events.jsonl`;
  * escopo          global | agent | project | session | task  x  visibility private | shared, `owner`;
                    `effective_scope` deriva defaults das notas antigas (sem reescrevê-las) e
                    `can_read` aplica a regra de leitura (isolamento por projeto/agente/sessão);
  * uso             `record_usage` grava em SQLite lateral `<state>/usage.db` (nunca altera o .md na
                    leitura); `usage_of` / `usage_map` leem de volta;
  * decay           `decay_plan` / `apply_decay` PROPÕEM `stale` (e `archived`) por desuso; dry-run por
                    padrão; nada `pinned`/`decision` é arquivado; nunca apaga;
  * ranking         `rank_notes`: relevância x (recência, uso, confiança, importância) x trust x escopo,
                    com `score_breakdown`. Atrás da flag `MG_MEMORY_RANK` (`v1` = desligado, padrão;
                    `v2` = composto). Pesos e meias-vidas são HIPÓTESES a calibrar por benchmark.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone

# ---------------------------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------------------------
STATES = ("candidate", "active", "reinforced", "stale", "archived", "superseded", "deleted")
LIVE_STATES = frozenset({"active", "reinforced", "stale"})         # entregáveis ao usuário
SEARCHABLE_STATES = frozenset({"active", "reinforced"})            # entram no top-k padrão
HARD_EXCLUDED_STATES = frozenset({"candidate", "archived", "superseded", "deleted"})

#: De -> {Para}. Qualquer outra transição é rejeitada. `deleted` é tombstone (só sai para `archived`).
TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"active", "deleted"}),
    "active": frozenset({"reinforced", "stale", "archived", "superseded", "deleted"}),
    "reinforced": frozenset({"active", "stale", "archived", "superseded", "deleted"}),
    "stale": frozenset({"active", "reinforced", "archived", "superseded", "deleted"}),
    "archived": frozenset({"active", "superseded", "deleted"}),
    "superseded": frozenset({"active", "archived", "deleted"}),
    "deleted": frozenset({"archived"}),
}

SCOPES = ("global", "agent", "project", "session", "task")
VISIBILITIES = ("private", "shared")
TRUSTS = ("trusted", "verified", "untrusted", "quarantined")

# Hipóteses (report_A3 §6): calibrar por benchmark antes de ligar por padrão.
HALFLIFE_DAYS = {"episodic": 14.0, "task": 30.0, "fact": 180.0, "decision": 365.0, "preference": 540.0,
                 "procedure": 365.0, "semantic": 365.0}
DEFAULT_HALFLIFE = 90.0
WEIGHTS = {"recency": 0.35, "usage": 0.25, "confidence": 0.20, "importance": 0.20}
TRUST_MULT = {"trusted": 1.0, "verified": 0.95, "untrusted": 0.6, "quarantined": 0.0}
SCOPE_MULT = {"task": 1.0, "session": 0.95, "project": 0.9, "agent": 0.8, "global": 0.7}
NEUTRAL_CONFIDENCE = 0.5      # nunca premia a ausência de confiança declarada
NEUTRAL_IMPORTANCE = 0.5
STALE_RECENCY = 0.25          # recência abaixo disso, sem uso na janela => proposta `stale`
USAGE_WINDOW_DAYS = 90.0
REINFORCE_USES = 3            # usos citados na janela para active -> reinforced
REINFORCE_WINDOW_DAYS = 30.0
WRONG_EXCLUDE_AT = 2


class ModelError(Exception):
    """Base; `.status` é o HTTP que a API usaria."""
    status = 422


class InvalidTransition(ModelError):
    pass


class InvalidScope(ModelError):
    pass


class Forbidden(ModelError):
    status = 403


def _store_errors():
    from app.memory_store import store as s
    return s


def rank_mode() -> str:
    """`MG_MEMORY_RANK`: `v1` (padrão, ranking atual intacto) ou `v2` (composto)."""
    v = os.environ.get("MG_MEMORY_RANK", "v1").strip().lower()
    return v if v in ("v1", "v2") else "v1"


# ---------------------------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------------------------
def normalize_status(status: str | None) -> str:
    """Nota v1/sem status == `active` (migração suave)."""
    return (status or "active").strip().lower()


def validate_transition(src: str | None, dst: str | None) -> str:
    """Devolve o estado destino normalizado ou levanta InvalidTransition. Mesmo estado = no-op válido."""
    a, b = normalize_status(src), (dst or "").strip().lower()
    if b not in STATES:
        raise InvalidTransition(f"status inválido: {dst!r} (use {', '.join(STATES)})")
    if a not in STATES:
        raise InvalidTransition(f"status atual desconhecido: {src!r}")
    if a != b and b not in TRANSITIONS[a]:
        raise InvalidTransition(f"transição não permitida: {a} -> {b} (permitidas: {', '.join(sorted(TRANSITIONS[a])) or '-'})")
    return b


def _events_path(store):
    return store.state_dir / "memory_events.jsonl"


def log_event(store, note_id: str, kind: str, **data) -> None:
    ev = {"ts": time.time(), "note_id": note_id, "event": kind, **data}
    p = _events_path(store)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")


def events(store, note_id: str | None = None) -> list[dict]:
    p = _events_path(store)
    out = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if note_id is None or ev.get("note_id") == note_id:
                out.append(ev)
    return out


def transition(store, note_id: str, to: str, *, actor: str = "system", reason: str | None = None):
    """Muda o estado de uma nota com validação, efeitos colaterais coerentes e evento auditável.

    * saindo de `superseded` (reativação) limpa `superseded_by` aqui e `supersedes` na nota que a
      substituía (AUD-181);
    * `deleted` grava o tombstone e move o arquivo para a lixeira (retenção MG_MEMORY_TRASH_DAYS);
    * `candidate -> active` só com a nota íntegra e sem `trust: quarantined`.
    """
    s = _store_errors()
    reason = (reason or "").strip()
    if len(reason) > 500 or "\n" in reason:
        raise s.InvalidNote("reason deve ter uma linha e até 500 caracteres")
    if s.scan_secrets(reason):
        raise s.InvalidNote("reason parece conter segredo; nada foi gravado")
    with store._lock:
        cur = store.get(note_id)
        src = normalize_status(cur.status)
        dst = validate_transition(src, to)
        if src == dst:
            return cur
        if src == "candidate" and dst == "active":
            if (cur.trust or "").lower() == "quarantined":
                raise InvalidTransition("nota em quarentena não pode ser promovida")
            if cur.integrity_ok() is False:
                raise InvalidTransition("content_sha256 não confere; promoção recusada")
        ch: dict = {"status": dst}
        if cur.schema < 2:
            ch.update(schema=s.SCHEMA_VERSION, kind=cur.kind or s.DEFAULT_KIND,
                      source=cur.source or (f"agent:{cur.source_agent}" if cur.source_agent else "manual"),
                      content_sha256=s.content_digest(cur.content))
        if src == "superseded" and dst != "superseded":
            ch["superseded_by"] = None
            if cur.superseded_by:
                try:
                    other = store.get(cur.superseded_by)
                    if other.supersedes == cur.id:
                        store._mutate(other.id, supersedes=None, updated=other.updated)
                except s.SavedContextError:
                    pass
        note = store._mutate(note_id, **ch)
        log_event(store, note_id, "transition", frm=src, to=dst, actor=(actor or "system")[:80], reason=reason)
        if dst == "deleted":
            store.delete(note_id)
        return note


def reinforce_eligible(note, usage: dict | None, *, now: float | None = None) -> bool:
    """active -> reinforced: >= REINFORCE_USES usos citados em 30 d OU >= 2 feedbacks `useful`."""
    if normalize_status(note.status) != "active":
        return False
    now = now or time.time()
    u = usage or {}
    recent = sum(1 for ts in u.get("cited_ts", []) if now - ts <= REINFORCE_WINDOW_DAYS * 86400)
    return recent >= REINFORCE_USES or (note.feedback_useful or 0) >= 2


# ---------------------------------------------------------------------------------------------
# Escopo / ownership / visibilidade
# ---------------------------------------------------------------------------------------------
def effective_scope(note) -> dict:
    """{scope, scope_id, visibility, owner} com defaults para notas antigas:
    com `project` => scope=project/scope_id=project/shared; sem => global/shared; owner = source_agent."""
    scope = (getattr(note, "scope", None) or "").strip().lower() or ("project" if note.project else "global")
    scope_id = getattr(note, "scope_id", None) or (note.project if scope == "project" else None)
    vis = (getattr(note, "visibility", None) or "").strip().lower() or "shared"
    owner = getattr(note, "owner", None) or note.source_agent
    return {"scope": scope, "scope_id": scope_id, "visibility": vis, "owner": owner}


def validate_scope(scope, scope_id, visibility, owner, project=None) -> dict:
    """Normaliza/valida os campos (None = não declarado). Levanta InvalidScope."""
    out: dict = {}
    if scope is not None:
        sc = str(scope).strip().lower()
        if sc not in SCOPES:
            raise InvalidScope(f"scope inválido: {scope!r} (use {', '.join(SCOPES)})")
        out["scope"] = sc
        sid = (str(scope_id).strip() if scope_id is not None else "") or (project if sc == "project" else "") or ""
        if sc != "global" and not sid:
            raise InvalidScope(f"scope={sc} exige scope_id")
        if len(sid) > 80 or "\n" in sid or "\r" in sid:
            raise InvalidScope("scope_id deve ter uma linha e até 80 caracteres")
        out["scope_id"] = sid or None
    elif scope_id is not None:
        raise InvalidScope("scope_id sem scope")
    if visibility is not None:
        v = str(visibility).strip().lower()
        if v not in VISIBILITIES:
            raise InvalidScope(f"visibility inválida: {visibility!r} (use {', '.join(VISIBILITIES)})")
        out["visibility"] = v
    if owner is not None:
        o = str(owner).strip()
        if len(o) > 80 or "\n" in o or "\r" in o:
            raise InvalidScope("owner deve ter uma linha e até 80 caracteres")
        out["owner"] = o or None
    return out


def can_read(note, viewer: dict | None = None) -> bool:
    """Regra de leitura. `viewer` = {agent, project, session, task, admin}. `viewer=None` == administrador
    local (comportamento anterior: tudo visível). Com viewer:

      * `private`: só o owner (viewer.agent == owner); sem owner, só admin;
      * `shared`: dentro do escopo — global: todos; project: viewer.project == scope_id; agent: viewer.agent
        == scope_id; session/task: viewer.session/task == scope_id.
    """
    if viewer is None or viewer.get("admin"):
        return True
    e = effective_scope(note)
    if e["visibility"] == "private":
        return bool(e["owner"]) and viewer.get("agent") == e["owner"]
    sc, sid = e["scope"], e["scope_id"]
    if sc == "global":
        return True
    key = {"project": "project", "agent": "agent", "session": "session", "task": "task"}[sc]
    return bool(sid) and viewer.get(key) == sid


def set_scope(store, note_id: str, *, scope=None, scope_id=None, visibility=None, owner=None, actor: str = "system"):
    cur = store.get(note_id)
    fields = validate_scope(scope, scope_id, visibility, owner, cur.project)
    if not fields:
        return cur
    s = _store_errors()
    ch = dict(fields)
    if cur.schema < 2:
        ch.update(schema=s.SCHEMA_VERSION, kind=cur.kind or s.DEFAULT_KIND, status=cur.status or "active",
                  source=cur.source or (f"agent:{cur.source_agent}" if cur.source_agent else "manual"),
                  content_sha256=s.content_digest(cur.content))
    note = store._mutate(note_id, updated=cur.updated, **ch)
    log_event(store, note_id, "scope", actor=(actor or "system")[:80], **fields)
    return note


# ---------------------------------------------------------------------------------------------
# Uso (sidecar SQLite; nunca toca o .md em leitura)
# ---------------------------------------------------------------------------------------------
_USAGE_DDL = """CREATE TABLE IF NOT EXISTS note_usage (
    note_id TEXT NOT NULL, ts REAL NOT NULL, run_id TEXT, rank INTEGER, cited INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS note_usage_id ON note_usage(note_id, ts);"""


def _usage_db(store) -> sqlite3.Connection:
    store.state_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(store.state_dir / "usage.db", timeout=30, isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_USAGE_DDL)
    return con


def record_usage(store, note_ids, *, run_id: str | None = None, cited: bool = False, now: float | None = None) -> int:
    """Registra que as notas foram entregues (e, se `cited`, citadas) numa resposta. Devolve quantas."""
    ids = [i for i in dict.fromkeys(note_ids or []) if isinstance(i, str)]
    if not ids:
        return 0
    ts = now if now is not None else time.time()
    with closing(_usage_db(store)) as con:
        con.execute("BEGIN IMMEDIATE")
        con.executemany("INSERT INTO note_usage VALUES (?,?,?,?,?)",
                        [(i, ts, run_id, k, 1 if cited else 0) for k, i in enumerate(ids)])
        con.execute("COMMIT")
    return len(ids)


def usage_map(store, *, window_days: float = USAGE_WINDOW_DAYS, now: float | None = None) -> dict[str, dict]:
    """{note_id: {usage_count, usage_count_window, cited_count, last_used, cited_ts}}."""
    if not (store.state_dir / "usage.db").is_file():
        return {}
    now = now if now is not None else time.time()
    cut = now - window_days * 86400
    out: dict[str, dict] = {}
    with closing(_usage_db(store)) as con:
        for nid, ts, cited in con.execute("SELECT note_id, ts, cited FROM note_usage ORDER BY ts"):
            u = out.setdefault(nid, {"usage_count": 0, "usage_count_window": 0, "cited_count": 0,
                                     "last_used": None, "cited_ts": []})
            u["usage_count"] += 1
            u["usage_count_window"] += 1 if ts >= cut else 0
            if cited:
                u["cited_count"] += 1
                u["cited_ts"].append(ts)
            u["last_used"] = ts
    return out


def usage_of(store, note_id: str, **kw) -> dict:
    return usage_map(store, **kw).get(note_id) or {"usage_count": 0, "usage_count_window": 0, "cited_count": 0,
                                                    "last_used": None, "cited_ts": []}


# ---------------------------------------------------------------------------------------------
# Recência / decay
# ---------------------------------------------------------------------------------------------
def _ts(value) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            dt = datetime.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).timestamp()


def halflife_days(kind: str | None) -> float:
    return HALFLIFE_DAYS.get((kind or "").lower(), DEFAULT_HALFLIFE)


def recency(note, usage: dict | None = None, *, now: float | None = None) -> float:
    """0.5 ** (dias desde max(updated, last_used) / meia-vida do kind). Sem data => 0.5 (neutro)."""
    now = now if now is not None else time.time()
    stamps = [t for t in (_ts(note.updated), _ts(note.created), (usage or {}).get("last_used")) if t]
    if not stamps:
        return 0.5
    days = max(0.0, (now - max(stamps)) / 86400.0)
    return 0.5 ** (days / halflife_days(note.kind))


def is_protected(note) -> bool:
    """Nada `pinned`/`decision` é arquivado por decay."""
    return (note.kind or "") == "decision" or "pinned" in (note.tags or [])


def decay_plan(store, *, now: float | None = None, archive_after_days: float = 90.0) -> dict:
    """Propostas por desuso (nunca delete): active/reinforced -> stale quando recência < 0,25 e sem uso na
    janela; stale há > `archive_after_days` -> archived (se não protegida); active -> reinforced por uso."""
    now = now if now is not None else time.time()
    um = usage_map(store, now=now)
    plan = {"to_stale": [], "to_archived": [], "to_reinforced": []}
    for n in store.list():
        st = normalize_status(n.status)
        u = um.get(n.id)
        if st in ("active", "reinforced"):
            if recency(n, u, now=now) < STALE_RECENCY and not (u and u["usage_count_window"]):
                plan["to_stale"].append(n.id)
            elif reinforce_eligible(n, u, now=now):
                plan["to_reinforced"].append(n.id)
        elif st == "stale" and not is_protected(n):
            idle = now - max([t for t in (_ts(n.updated), (u or {}).get("last_used")) if t] or [now])
            if idle >= archive_after_days * 86400 and not (u and u["usage_count_window"]):
                plan["to_archived"].append(n.id)
    return plan


def apply_decay(store, *, dry_run: bool = True, now: float | None = None, actor: str = "system:decay") -> dict:
    """Aplica `decay_plan` por transições validadas (versionadas). Dry-run por padrão."""
    plan = decay_plan(store, now=now)
    rep = {"dry_run": dry_run, **plan, "applied": 0}
    if dry_run:
        return rep
    for key, to in (("to_stale", "stale"), ("to_archived", "archived"), ("to_reinforced", "reinforced")):
        for nid in plan[key]:
            try:
                transition(store, nid, to, actor=actor, reason="decay")
                rep["applied"] += 1
            except ModelError:
                pass
    return rep


# ---------------------------------------------------------------------------------------------
# Ranking composto
# ---------------------------------------------------------------------------------------------
def hard_excluded(note, *, now: datetime | None = None) -> str | None:
    """Motivo da exclusão dura do top-k padrão, ou None."""
    st = normalize_status(note.status)
    if st in HARD_EXCLUDED_STATES:
        return st
    if note.is_expired(now):
        return "expired"
    if (note.feedback_wrong or 0) >= WRONG_EXCLUDE_AT:
        return "wrong"
    if (note.trust or "").lower() == "quarantined":
        return "quarantined"
    return None


def score_note(note, relevance: float, *, usage: dict | None = None, usage_max: int = 1,
               now: float | None = None) -> dict:
    """Score composto + breakdown. `relevance` em [0,1] (BM25 normalizado)."""
    rel = min(1.0, max(0.0, float(relevance)))
    rec = recency(note, usage, now=now)
    uw = (usage or {}).get("usage_count_window", 0)
    use = math.log1p(uw) / math.log1p(max(1, usage_max)) if uw else 0.0
    use = min(1.0, use)
    conf = NEUTRAL_CONFIDENCE if note.confidence is None else min(1.0, max(0.0, note.confidence))
    imp = NEUTRAL_IMPORTANCE if getattr(note, "importance", None) is None else min(1.0, max(0.0, note.importance))
    trust = (note.trust or "trusted").lower()
    tm = TRUST_MULT.get(trust, TRUST_MULT["untrusted"])
    sc = SCOPE_MULT.get(effective_scope(note)["scope"], 0.7)
    boost = (WEIGHTS["recency"] * rec + WEIGHTS["usage"] * use + WEIGHTS["confidence"] * conf
             + WEIGHTS["importance"] * imp)
    return {"score": round(rel * boost * tm * sc, 6),
            "breakdown": {"relevance": round(rel, 4), "recency": round(rec, 4), "usage": round(use, 4),
                          "confidence": round(conf, 4), "importance": round(imp, 4), "trust_mult": tm,
                          "scope_mult": sc, "boost": round(boost, 4)}}


def rank_notes(store, candidates: list[tuple[str, float]], *, viewer: dict | None = None,
               now: float | None = None, mode: str | None = None) -> list[dict]:
    """Ordena `[(note_id, relevância 0..1)]`. Aplica visibilidade (`viewer`) e exclusões duras SEMPRE.

    mode `v1` (padrão): ordem da relevância, desempate por id (ranking atual). mode `v2`: score composto.
    Cada item: {id, score, rank_mode, breakdown}. Ids inexistentes são ignorados.
    """
    mode = mode or rank_mode()
    now = now if now is not None else time.time()
    um = usage_map(store, now=now) if mode == "v2" else {}
    umax = max([u["usage_count_window"] for u in um.values()] or [1])
    out = []
    for nid, rel in candidates:
        try:
            n = store.get(nid)
        except _store_errors().SavedContextError:
            continue
        if not can_read(n, viewer) or hard_excluded(n):
            continue
        if mode == "v2":
            r = score_note(n, rel, usage=um.get(nid), usage_max=umax, now=now)
        else:
            r = {"score": round(float(rel), 6), "breakdown": {"relevance": round(float(rel), 4)}}
        out.append({"id": nid, "score": r["score"], "rank_mode": mode, "breakdown": r["breakdown"]})
    out.sort(key=lambda x: (-x["score"], x["id"]))
    return out


# ---------------------------------------------------------------------------------------------
# Pós-processamento do search (ANAM-013): rank v2 + registro de uso, atrás de MG_MEMORY_RANK=v2
# ---------------------------------------------------------------------------------------------
_NOTE_FILE_RE = re.compile(r"^saved_context/[^/]*-([0-9a-f]{10})\.md$")


def candidate_note_id(source_file: str | None) -> str | None:
    m = _NOTE_FILE_RE.match((source_file or "").replace("\\", "/"))
    return m.group(1) if m else None


def rerank_candidates(store, cands: list, *, viewer: dict | None = None, now: float | None = None) -> tuple[list, dict]:
    """Rank v2 sobre candidatos: só notas salvas (`saved_context/…-<id>.md`) recebem score composto; candidatos
    do vault mantêm a relevância normalizada. Exclusões duras valem para as notas salvas. Devolve (lista, métricas).
    Mapa de ids falha-aberto: nota ilegível/ausente fora do store não entra no rank (mantém a posição relativa)."""
    if not cands:
        return cands, {}
    top = max([float(c.score or 0.0) for c in cands] or [0.0]) or 1.0
    rel = {id(c): min(1.0, max(0.0, float(c.score or 0.0) / top)) for c in cands}
    by_id: dict[str, list] = {}
    for c in cands:
        nid = candidate_note_id(c.source_file)
        if nid:
            by_id.setdefault(nid, []).append(c)
    ranked = rank_notes(store, [(nid, max(rel[id(c)] for c in cs)) for nid, cs in by_id.items()],
                        viewer=viewer, now=now, mode="v2") if by_id else []
    scored = {r["id"]: r for r in ranked}
    dropped = [nid for nid in by_id if nid not in scored and _exists(store, nid)]
    out: list[tuple[float, int, object]] = []
    for pos, c in enumerate(cands):
        nid = candidate_note_id(c.source_file)
        if nid in dropped:
            continue
        if nid in scored:
            r = scored[nid]
            c.meta = {**(c.meta or {}), "rank_v2": r["breakdown"], "rank_v2_score": r["score"]}
            out.append((r["score"], pos, c))
        else:
            out.append((rel[id(c)], pos, c))
    out.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in out], {"memory_rank": "v2", "memory_rank_excluded": len(dropped)}


def _exists(store, nid: str) -> bool:
    try:
        store.get(nid)
        return True
    except Exception:  # noqa: BLE001
        return False


def record_delivered_usage(store, sources: list, *, run_id: str | None = None) -> int:
    """Registra uso das notas salvas entregues no contexto. Nunca levanta (telemetria consultiva)."""
    try:
        ids = [i for i in (candidate_note_id(getattr(s, "file", None)) for s in sources) if i]
        return record_usage(store, ids, run_id=run_id) if ids else 0
    except Exception:  # noqa: BLE001
        return 0
