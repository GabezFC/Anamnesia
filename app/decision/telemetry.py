"""Telemetria do Decision Engine: histórico por IDs/hashes (NUNCA texto de query/candidato) e métricas agregadas.

Cada registro guarda: hash da query, hash do candidato e hash do ID do candidato (o ID pode ser um caminho do
vault), decisão, provider, score/confidence, flags de cache/fallback/escalonamento. Persistência opcional em
JSONL em `<user_data_dir>/logs/decision_history.jsonl` (mesmo padrão de logs/ do projeto); falha de escrita
nunca derruba a decisão.
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from pathlib import Path

from app.decision.analysis import divergence, percentile
from app.decision.types import ESTIMATED, MEASURED, UNKNOWN, DecisionRequest, DecisionResult, labeled, sha


def default_history_path() -> Path:
    from config.paths import logs_dir
    return logs_dir() / "decision_history.jsonl"


def build_record(req: DecisionRequest, res: DecisionResult) -> dict:
    counts: dict[str, int] = {}
    for i in res.items:
        counts[i.decision] = counts.get(i.decision, 0) + 1
    return {
        "ts": round(time.time(), 3), "request_id": res.request_id, "op": res.op, "project": req.project,
        "provider": res.provider, "model": res.model or None, "strategy": res.strategy, "query_hash": sha(req.query), "schema": req.schema,
        "n_items": len(res.items), "decisions": counts, "latency_ms": round(res.latency_ms, 2),
        "calls": dict(res.calls), "jev_requests": res.jev_requests, "jev_calls_avoided": res.jev_calls_avoided,
        "cache_hits": res.cache_hits, "fallbacks": res.fallback_count,
        "errors": [sha(e, 12) + ":" + e.split(":", 1)[0][:30] for e in res.errors[:3]],  # só o tipo, nunca texto
        "items": [{"id": sha(i.candidate_id, 12), "h": i.content_hash, "d": i.decision, "p": i.provider,
                   "s": None if i.score is None else round(i.score, 4),
                   "c": None if i.confidence is None else round(i.confidence, 4),
                   "fb": i.fallback, "esc": i.escalated, "ca": i.cached,
                   "o": {k: v.get("decision") for k, v in i.others.items()} if i.others else None}
                  for i in res.items],
    }


class DecisionHistory:
    def __init__(self, size: int = 500, path: Path | None = None, persist: bool = False):
        self._buf: deque[dict] = deque(maxlen=max(10, size))
        self._lock = threading.Lock()
        self.path, self.persist = path, persist
        self.write_errors = 0
        self.total = 0

    def add(self, rec: dict) -> None:
        with self._lock:
            self._buf.append(rec)
            self.total += 1
            if self.persist and self.path is not None:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                except OSError:
                    self.write_errors += 1

    def recent(self, limit: int = 50, project: str | None = None, include_items: bool = False) -> list[dict]:
        with self._lock:
            rows = list(self._buf)
        if project is not None:
            rows = [r for r in rows if r.get("project") == project]
        rows = rows[-max(1, min(limit, 500)):][::-1]
        if include_items:
            return rows
        return [{k: v for k, v in r.items() if k != "items"} for r in rows]

    @staticmethod
    def read_persisted(path: Path, limit: int = 50, project: str | None = None) -> list[dict]:
        """Últimos registros do JSONL (sem itens). Linhas corrompidas são ignoradas, não propagadas."""
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-5000:]
        except OSError:
            return []
        rows = []
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if project is None or r.get("project") == project:
                rows.append({k: v for k, v in r.items() if k != "items"})
        return rows[-max(1, min(limit, 500)):][::-1]

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def metrics(self, project: str | None = None) -> dict:
        with self._lock:
            rows = [r for r in self._buf if project is None or r.get("project") == project]
        n = len(rows)
        if not n:
            return {"requests": labeled(0, MEASURED), "note": "histórico vazio (nada medido ainda)", "project": project}
        items = sum(r["n_items"] for r in rows)
        lat = [r["latency_ms"] for r in rows]
        by_provider: dict[str, int] = {}
        for r in rows:
            by_provider[r["provider"]] = by_provider.get(r["provider"], 0) + 1
        jev_items = sum(r["calls"].get("jev", 0) for r in rows)
        laya_items = sum(r["calls"].get("laya", 0) for r in rows)
        pairs = []
        for r in rows:
            for it in r["items"]:
                o = it.get("o") or {}
                if "laya" in o and "jev" in o:
                    pairs.append((o["laya"], o["jev"]))
        q = lambda v: None if v is None else round(v, 2)  # noqa: E731
        return {
            "project": project,
            "requests": labeled(n, MEASURED), "items": labeled(items, MEASURED),
            "by_provider": by_provider,
            "latency_ms_p50": labeled(q(percentile(lat, 0.5)), MEASURED),
            "latency_ms_p95": labeled(q(percentile(lat, 0.95)), MEASURED),
            "jev_items": labeled(jev_items, MEASURED), "laya_items": labeled(laya_items, MEASURED),
            "jev_calls_avoided": labeled(sum(r["jev_calls_avoided"] for r in rows), MEASURED),
            "jev_tokens": labeled(sum(340 * r["jev_requests"] + 209 * r["calls"].get("jev", 0) for r in rows), ESTIMATED,
                                  "340*requests+209*questions"),
            "jev_cost_usd": labeled(None, UNKNOWN, "JEV real: não medido"),
            "cache_hit_rate": labeled(round(sum(r["cache_hits"] for r in rows) / items, 4) if items else None, MEASURED),
            "fallback_rate": labeled(round(sum(r["fallbacks"] for r in rows) / items, 4) if items else None, MEASURED),
            "divergence": divergence(pairs),
            "persist_write_errors": self.write_errors,
        }
