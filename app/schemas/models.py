"""Shared data structures. Consumer-neutral: nothing here knows about any specific agent/model."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PipelineName = Literal["baseline", "graphify", "graphify_jev", "graphify_jev_opt"]
PIPELINES: tuple[str, ...] = ("baseline", "graphify", "graphify_jev", "graphify_jev_opt")
UNAVAILABLE = None  # metrics a platform does not expose are stored as null, never estimated (§43, §103)


@dataclass
class Candidate:
    candidate_id: str
    source_file: str          # vault-relative path, forward slashes
    section: str              # heading path, e.g. "Decisão > Contexto"
    snippet: str
    score: float = 0.0        # retrieval score (bm25-derived or graph-derived), higher = better
    origin: str = ""          # baseline | graphify
    token_estimate: int = 0
    content_hash: str = ""
    # filled by JEV stage
    relevance: float | None = None
    injection: float | None = None
    decision: str | None = None   # KEEP | REVIEW | DROP | QUARANTINE
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Source:
    file: str
    section: str
    score: float
    relevance: float | None = None
    decision: str | None = None
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryResult:
    query: str
    pipeline: str
    context: str
    sources: list[Source]
    metrics: dict[str, Any]
    run_id: str | None = None
    candidates: list[Candidate] = field(default_factory=list)  # internal detail; not sent to agents by default

    def to_dict(self, include_candidates: bool = False) -> dict[str, Any]:
        out = {
            "query": self.query,
            "pipeline": self.pipeline,
            "run_id": self.run_id,
            "context": self.context,
            "sources": [s.to_dict() for s in self.sources],
            "metrics": self.metrics,
        }
        if include_candidates:
            out["candidates"] = [c.to_dict() for c in self.candidates]
        return out
