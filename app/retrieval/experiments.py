"""Onda 9 retrieval experiments (ANA-226..237), every one behind a flag that defaults to OFF.

Why one module: the experiments all touch the same two places (the lexical entry point and the
post-dedup list), they are measured together by `scripts/measure_onda9.py`, and each one needs a
single, greppable "is it on?" switch.  With every flag at its default the code paths are the
pre-Onda-9 ones, byte for byte (`lexical_search` calls `gw.baseline.search(query, limit)` untouched).

The FROZEN pipeline (`graphify_jev`) never sees these flags: callers pass `frozen=True`.

Flags (env, all default OFF / legacy value) -- read by `RetrievalExperiments.from_env()`:

  MG_EXP_BM25_SECTION_WEIGHT  ANA-226  weight of the `section` column in bm25() (unset = DEFAULT_SECTION_WEIGHT)
  MG_EXP_SCOPE_BEFORE_TOPN    ANA-227  apply the scope while walking the ranked rows, before top-N
  MG_EXP_UNIFIED_TOKENS       ANA-228  query terms from app.services.query_fp.tokens (one tokenizer)
  MG_EXP_PREFIX_MIN_LEN       ANA-229  >0: terms with >= N letters become FTS5 prefix queries
  MG_EXP_STEM_PREFIX          ANA-229  prefix is taken on the light stem (needs PREFIX_MIN_LEN>0)
  MG_EXP_HYBRID_SCORE         ANA-230  rank (legacy) | magnitude | rrf
  MG_EXP_COMPLEX_DEDUP_MAX    ANA-231  >0: dedup_max_per_note used for COMPLEX queries
  MG_EXP_LEX_RERANK_TOP       ANA-232  >0: deterministic lexical reranker over the top-N
  MG_EXP_REL_CUTOFF           ANA-233  >0: drop candidates scoring < cutoff * best (keeps >= 3)
  MG_EXP_SEMANTIC_RRF         ANA-235  fuse a LOCAL embedding channel with RRF (Ollama only)
  MG_EXP_QUERY_REWRITE        ANA-236  deterministic query rewriting (carrier words out, quotes kept)
  MG_EXP_BUDGET_FIT           ANA-237  query-aware fitting instead of dropping a block (builder)

Pure functions here have no I/O except `OllamaEmbedder`, which only ever talks to a loopback host.
"""
from __future__ import annotations

import json
import math
import re
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from typing import Callable, Iterable, Protocol

from config import env_bool, env_float, env_int, env_str
from app.schemas.models import Candidate
from app.services.query_fp import CARRIER, classify, fold, stem, tokens

# ANA-226: the legacy expression `bm25(sec, 2.0, 1.0)` put 2.0 on the UNINDEXED `file` column, i.e. the heading
# was never boosted.  Measured neutral on the golden set (docs/reports/ONDA9_EXPERIMENTOS.md), so the intended 2.0
# on `section` is now the default; MG_EXP_BM25_SECTION_WEIGHT=1.0 reproduces the old ranking exactly.
DEFAULT_SECTION_WEIGHT = 2.0
HYBRID_MODES = ("rank", "magnitude", "rrf")


@dataclass(frozen=True)
class RetrievalExperiments:
    bm25_section_weight: float | None = None
    scope_before_topn: bool = False
    unified_tokens: bool = False
    prefix_min_len: int = 0
    stem_prefix: bool = False
    hybrid_score: str = "rank"
    rrf_k: int = 60
    rrf_graph_weight: float = 0.5
    complex_dedup_max: int = 0
    lex_rerank_top: int = 0
    lex_rerank_alpha: float = 0.5
    rel_cutoff: float = 0.0
    rel_cutoff_min_keep: int = 3
    semantic_rrf: bool = False
    semantic_model: str = "nomic-embed-text"
    query_rewrite: bool = False
    budget_fit: bool = False

    @classmethod
    def from_env(cls) -> "RetrievalExperiments":
        mode = env_str("MG_EXP_HYBRID_SCORE", "rank").strip().lower()
        return cls(
            bm25_section_weight=(env_float("MG_EXP_BM25_SECTION_WEIGHT", DEFAULT_SECTION_WEIGHT)
                                 if env_str("MG_EXP_BM25_SECTION_WEIGHT") else None),
            scope_before_topn=env_bool("MG_EXP_SCOPE_BEFORE_TOPN", False),
            unified_tokens=env_bool("MG_EXP_UNIFIED_TOKENS", False),
            prefix_min_len=env_int("MG_EXP_PREFIX_MIN_LEN", 0),
            stem_prefix=env_bool("MG_EXP_STEM_PREFIX", False),
            hybrid_score=mode if mode in HYBRID_MODES else "rank",
            rrf_k=env_int("MG_EXP_RRF_K", 60),
            rrf_graph_weight=env_float("MG_EXP_RRF_GRAPH_WEIGHT", 0.5),
            complex_dedup_max=env_int("MG_EXP_COMPLEX_DEDUP_MAX", 0),
            lex_rerank_top=env_int("MG_EXP_LEX_RERANK_TOP", 0),
            lex_rerank_alpha=env_float("MG_EXP_LEX_RERANK_ALPHA", 0.5),
            rel_cutoff=env_float("MG_EXP_REL_CUTOFF", 0.0),
            semantic_rrf=env_bool("MG_EXP_SEMANTIC_RRF", False),
            semantic_model=env_str("MG_EXP_SEMANTIC_MODEL", "nomic-embed-text"),
            query_rewrite=env_bool("MG_EXP_QUERY_REWRITE", False),
            budget_fit=env_bool("MG_EXP_BUDGET_FIT", False),
        )

    def active(self) -> list[str]:
        """Names of the experiments that differ from the legacy behaviour."""
        base = RetrievalExperiments()
        return sorted(k for k, v in asdict(self).items() if v != getattr(base, k)
                      and k not in ("rrf_k", "rrf_graph_weight", "lex_rerank_alpha", "semantic_model",
                                "rel_cutoff_min_keep"))

    def digest(self) -> dict:
        return asdict(self)

    @property
    def lexical_active(self) -> bool:
        return bool(self.bm25_section_weight is not None or self.scope_before_topn or self.unified_tokens
                    or self.prefix_min_len > 0 or self.query_rewrite)


def get_flags(gw) -> RetrievalExperiments:
    """Flags of a gateway: `gw.experiments` when set (benchmarks), else the environment."""
    exp = getattr(gw, "experiments", None)
    return exp if isinstance(exp, RetrievalExperiments) else RetrievalExperiments.from_env()


# --------------------------------------------------------------------------- ANA-228/229/236 query side
_QUOTED = re.compile(r'["“”]([^"“”]{2,80})["“”]')


def rewrite_query(query: str) -> str:
    """ANA-236: deterministic rewrite for the lexical channel.

    Keeps quoted spans verbatim (an exact identifier the user took the trouble to quote), keeps every
    identifier-shaped token, and drops "carrier" vocabulary (how the question is asked, not what it is
    about: "registro", "vault", "nota", "diz", ...).  Never returns an empty rewrite: when nothing
    would be left the original query is returned.  Negators are kept (qn-v3).
    """
    quoted = [m.strip() for m in _QUOTED.findall(query)]
    rest = _QUOTED.sub(" ", query)
    kept: list[str] = []
    for t in tokens(rest):
        if any(ch.isdigit() for ch in t) or any(ch in t for ch in ".:_"):
            kept.append(t)            # identifier: never a carrier
        elif stem(t) in CARRIER:
            continue
        else:
            kept.append(t)
    out = " ".join([*quoted, *kept]).strip()
    return out or query


def _dedup(seq: Iterable[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


def fts_match(query: str, exp: RetrievalExperiments, legacy_terms: Callable[[str], list[str]]) -> str:
    """FTS5 MATCH expression for the experimental lexical path ('' = no usable terms)."""
    q = rewrite_query(query) if exp.query_rewrite else query
    terms = _dedup(tokens(q)) if exp.unified_tokens else legacy_terms(q)
    parts: list[str] = []
    for t in terms:
        t = t.replace('"', "")
        if not t:
            continue
        use, prefix = t, False
        if exp.prefix_min_len > 0 and t.isalpha():
            use = stem(fold(t)) if exp.stem_prefix else t
            prefix = len(use) >= min(exp.prefix_min_len, 4) and len(t) >= exp.prefix_min_len
        parts.append(f'"{use}"' + (" *" if prefix else ""))
    return " OR ".join(parts)


def bm25_expr(exp: RetrievalExperiments | None) -> str:
    """Column order of `sec`: file(UNINDEXED) section body status(UNINDEXED) line(UNINDEXED).

    Legacy `bm25(sec, 2.0, 1.0)` gave 2.0 to `file` (unindexed, contributes nothing) and 1.0 to `section`,
    so the intended "heading counts double" never happened (ANA-226).  The explicit form puts the weight on
    the right column.  weight 1.0 is rank-identical to the old expression.
    """
    w = DEFAULT_SECTION_WEIGHT if exp is None or exp.bm25_section_weight is None else float(exp.bm25_section_weight)
    return f"bm25(sec, 0.0, {w!r}, 1.0, 0.0, 0.0)"


# --------------------------------------------------------------------------- ANA-230 fusion
def rrf_scores(rankings: list[tuple[list[str], float]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: sum of weight/(k+rank+1) across weighted rankings."""
    out: dict[str, float] = {}
    for ranking, weight in rankings:
        for pos, key in enumerate(ranking):
            out[key] = out.get(key, 0.0) + weight / (k + pos + 1)
    return out


def hybrid_text_scores(mode: str, bm: list[Candidate], seed_files: list[str], related: list[str],
                       label_files: list[str], exp: RetrievalExperiments) -> tuple[dict[str, float], dict[str, float]]:
    """Score for seed files and for graph-only files under `magnitude` / `rrf`.

    Returns (per-candidate-id text score, per-file graph score).  `rank` is handled by the legacy code.
    """
    text: dict[str, float] = {}
    graph: dict[str, float] = {}
    seeds = set(seed_files)
    in_seed = [c for c in bm if c.source_file.replace("\\", "/") in seeds]
    if mode == "magnitude":
        best = max((c.score for c in in_seed), default=0.0)
        for c in in_seed:
            rel = (c.score / best) if best > 0 else 0.0
            text[c.candidate_id] = round(0.55 + 0.45 * max(0.0, min(1.0, rel)), 4)
        for i, f in enumerate(related):
            graph[f] = round(0.5 - 0.2 * (i / max(len(related), 1)), 4)
        return text, graph
    # rrf
    fused = rrf_scores([(seed_files, 1.0), (_dedup([*label_files, *related]), exp.rrf_graph_weight)], exp.rrf_k)
    top = max(fused.values(), default=1.0) or 1.0
    for c in in_seed:
        text[c.candidate_id] = round(fused.get(c.source_file.replace("\\", "/"), 0.0) / top, 4)
    for f in related:
        graph[f] = round(fused.get(f, 0.0) / top, 4)
    return text, graph


# --------------------------------------------------------------------------- ANA-232 reranker
def _min_window(positions: list[list[int]]) -> int:
    """Smallest token span containing at least one position of every non-empty list."""
    lists = [p for p in positions if p]
    if not lists:
        return 0
    if len(lists) == 1:
        return 1
    flat = sorted((pos, i) for i, p in enumerate(lists) for pos in p)
    need, have, left, best = len(lists), {}, 0, 10 ** 9
    for right, (pos, i) in enumerate(flat):
        have[i] = have.get(i, 0) + 1
        while len(have) == need:
            best = min(best, pos - flat[left][0] + 1)
            li = flat[left][1]
            have[li] -= 1
            if not have[li]:
                del have[li]
            left += 1
    return best if best < 10 ** 9 else 0


def lexical_features(query: str, c: Candidate) -> dict[str, float]:
    qs = {stem(t) for t in tokens(query)}
    if not qs:
        return {"coverage": 0.0, "heading": 0.0, "proximity": 0.0}
    body_toks = [stem(t) for t in tokens(f"{c.section} {c.snippet}")]
    head = {stem(t) for t in tokens(c.section)}
    present = qs & set(body_toks)
    pos = [[i for i, t in enumerate(body_toks) if t == q] for q in present]
    span = _min_window(pos)
    prox = (len(present) / span) if span else 0.0
    return {"coverage": len(present) / len(qs), "heading": len(qs & head) / len(qs),
            "proximity": min(1.0, prox)}


def lexical_rerank(query: str, cands: list[Candidate], top_n: int, alpha: float = 0.5) -> list[Candidate]:
    """ANA-232: reorder the top-N by query-term coverage/heading/proximity blended with the original rank.

    Deterministic, dependency-free, zero model tokens.  Items past N keep their order.  Sets
    `meta['rerank_rank']` on EVERY candidate (ModelContextBuilder.rank sorts by it first).
    """
    if top_n <= 1 or len(cands) < 2:
        return cands
    head, tail = cands[:top_n], cands[top_n:]
    n = len(head)
    scored = []
    for i, c in enumerate(head):
        f = lexical_features(query, c)
        lex = 0.6 * f["coverage"] + 0.15 * f["heading"] + 0.25 * f["proximity"]
        orig = 1.0 - i / n
        scored.append((alpha * orig + (1 - alpha) * lex, -i, c))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    out = [c for _, _, c in scored] + tail
    for pos, c in enumerate(out):
        c.meta = {**(c.meta or {}), "rerank_rank": pos, "rerank": "lexical"}
    return out


# --------------------------------------------------------------------------- ANA-235 semantic channel (local only)
class EmbeddingBackend(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _is_loopback(host: str) -> bool:
    m = re.match(r"^https?://([^/:]+)(?::\d+)?(?:/|$)", host)
    return bool(m) and m.group(1) in ("127.0.0.1", "localhost", "::1", "[::1]")


class OllamaEmbedder:
    """Local embeddings via Ollama `/api/embed`.  Refuses any non-loopback host: never a paid API."""

    def __init__(self, model: str, host: str = "http://127.0.0.1:11434", timeout_s: float = 30.0):
        if not _is_loopback(host):
            raise ValueError(f"semantic channel is local-only; refusing host {host!r}")
        self.model, self.host, self.timeout_s = model, host.rstrip("/"), timeout_s

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=2) as r:
                names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
            return any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)
        except Exception:  # noqa: BLE001
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model, "input": texts}).encode()
        req = urllib.request.Request(f"{self.host}/api/embed", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
            return json.loads(r.read())["embeddings"]


def cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


@dataclass
class SemanticIndex:
    """Section embeddings kept in memory, rebuilt when the baseline index size changes."""
    backend: EmbeddingBackend
    key: tuple = ()
    rows: list[tuple[str, str, str, int]] = field(default_factory=list)   # file, section, body, line
    vecs: list[list[float]] = field(default_factory=list)

    def ensure(self, baseline) -> None:
        key = (baseline.files_indexed, baseline.sections_indexed)
        if key == self.key and self.rows:
            return
        with baseline._lock:
            rows = baseline.conn.execute("SELECT file, section, body, line FROM sec").fetchall()
        texts = [f"{s}\n{b}"[:1200] for _, s, b, _ in rows]
        vecs: list[list[float]] = []
        for i in range(0, len(texts), 64):
            vecs.extend(self.backend.embed(texts[i:i + 64]))
        self.rows, self.vecs, self.key = [tuple(r) for r in rows], vecs, key

    def search(self, query: str, limit: int, accept: Callable[[str], bool] | None = None) -> list[Candidate]:
        qv = self.backend.embed([query])[0]
        scored = sorted(((cosine(qv, v), i) for i, v in enumerate(self.vecs)), reverse=True)
        out: list[Candidate] = []
        for s, i in scored:
            f, sec, body, line = self.rows[i]
            if accept is not None and not accept(f):
                continue
            out.append(Candidate(candidate_id=f"s{len(out):03d}:{f}#L{line}", source_file=f, section=sec,
                                 snippet=body, score=float(s), origin="semantic", meta={"line": line}))
            if len(out) >= limit:
                break
        return out


def semantic_fuse(lexical: list[Candidate], semantic: list[Candidate], limit: int, k: int = 60) -> list[Candidate]:
    """RRF of the lexical and semantic rankings (keyed by file#line); scores rescaled to the lexical scale."""
    def key(c: Candidate) -> str:
        return f"{c.source_file}#{(c.meta or {}).get('line')}"
    by_key = {key(c): c for c in semantic}
    by_key.update({key(c): c for c in lexical})          # lexical object wins (carries bm25 meta)
    fused = rrf_scores([([key(c) for c in lexical], 1.0), ([key(c) for c in semantic], 1.0)], k)
    scale = max((c.score for c in lexical), default=1.0) / (max(fused.values(), default=1.0) or 1.0)
    out = []
    for kx, sc in sorted(fused.items(), key=lambda kv: -kv[1])[:limit]:
        c = by_key[kx]
        c.score = sc * scale
        c.meta = {**(c.meta or {}), "via_semantic": kx in {key(s) for s in semantic}}
        out.append(c)
    return out


_SEM_INDEX: dict[int, SemanticIndex] = {}


def resolve_embedder(gw, exp: RetrievalExperiments) -> EmbeddingBackend | None:
    emb = getattr(gw, "embedder", None)
    if emb is not None:
        return emb
    try:
        e = OllamaEmbedder(exp.semantic_model)
    except ValueError:
        return None
    return e if e.available() else None


# --------------------------------------------------------------------------- entry points used by the pipelines
def lexical_search(gw, query: str, limit: int, *, frozen: bool = False) -> list[Candidate]:
    """The single lexical entry point.  No active experiment (or frozen) == the legacy call."""
    exp = None if frozen else get_flags(gw)
    if exp is None or not (exp.lexical_active or exp.semantic_rrf):
        return gw.baseline.search(query, limit)
    scope = getattr(gw, "active_scope", None) if exp.scope_before_topn else None
    lex = gw.baseline.search(query, limit, exp=exp, scope=scope)
    if exp.semantic_rrf:
        emb = resolve_embedder(gw, exp)
        if emb is None:
            gw.log.warning("semantic channel requested but no local embedder available; lexical only")
            return lex
        idx = _SEM_INDEX.setdefault(id(gw), SemanticIndex(emb))
        idx.backend = emb
        idx.ensure(gw.baseline)
        accept = (lambda f: scope.matches(f)) if (scope is not None and not scope.is_global) else None
        return semantic_fuse(lex, idx.search(query, limit, accept), limit, exp.rrf_k)
    return lex


def dedup_limit(gw, query: str, default: int, *, frozen: bool = False) -> int:
    """ANA-231: dedup_max_per_note for COMPLEX queries (flag), else the configured value."""
    if frozen:
        return default
    exp = get_flags(gw)
    if exp.complex_dedup_max > 0:
        try:
            if classify(query).complexity == "COMPLEX":
                return max(default, exp.complex_dedup_max)
        except Exception:  # noqa: BLE001 -- advisory
            pass
    return default


def post_dedup(gw, query: str, cands: list[Candidate], *, frozen: bool = False) -> list[Candidate]:
    """ANA-232 hook, applied after dedup and before the max_results cut."""
    if frozen:
        return cands
    exp = get_flags(gw)
    if exp.lex_rerank_top > 0:
        cands = lexical_rerank(query, cands, exp.lex_rerank_top, exp.lex_rerank_alpha)
    if exp.rel_cutoff > 0:
        cands = relative_cutoff(cands, exp.rel_cutoff, exp.rel_cutoff_min_keep)
    return cands


def relative_cutoff(cands: list[Candidate], cutoff: float, min_keep: int = 3) -> list[Candidate]:
    """ANA-233: keep candidates whose score is >= cutoff * best score (never fewer than `min_keep`)."""
    if not cands or cutoff <= 0:
        return cands
    best = max(c.score for c in cands)
    if best <= 0:
        return cands
    kept = [c for c in cands if c.score >= cutoff * best]
    if len(kept) < min_keep:
        kept = sorted(cands, key=lambda c: -c.score)[:min_keep]
        kept = [c for c in cands if c in kept]
    return kept


def with_flags(base: RetrievalExperiments | None = None, **kw) -> RetrievalExperiments:
    return replace(base or RetrievalExperiments(), **kw)
