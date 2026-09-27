"""Hybrid Graphify retrieval: BM25 body text for content, graph edges for structure (§9 PIPELINE B).

WHY THIS EXISTS (measured 2026-09-27, 10 answerable benchmark questions)
-----------------------------------------------------------------------
The Graphify CLI picks its seed nodes by matching the query against node LABELS, and the graph
only contains page filenames and heading titles (1,109 nodes = 74 pages + 1,035 headings). It
never indexes body text. That produces two distinct, independently-measured failures:

  q01  the CLI truncated at --budget 6000 before reaching the right note. The note WAS reachable
       (it appears at position 124 with a larger budget), just cut off.
  q06  the answer ("qwen2.5-coder:7b", "127.0.0.1:49374") lives in the note's BODY. No label
       contains those terms, so NO graph-only strategy can find it at any budget.

Strategies compared on the same 10 questions (scripts/graphify_seed_experiment.py):

    CLI atual          8/10   80.0%
    seeds lexicais     8/10   80.0%    label match over graph.json, no expansion
    seeds + BFS        9/10   90.0%    recovers q01 (position 0)
    BM25 + grafo      10/10  100.0%    also recovers q06; ground truth at position 0 in 9/10

So the graph is the wrong tool for *finding* a note and the right tool for *relating* notes.
This module keeps both: BM25 over section bodies supplies content-addressable entry points,
graph BFS supplies structurally-related neighbours that share no vocabulary with the query.

Everything here is deterministic and costs zero model tokens.
"""
from __future__ import annotations

import collections
import json
import re
import time
import unicodedata
from pathlib import Path

from app.schemas.models import Candidate

_TOKEN = re.compile(r"[a-z0-9]{3,}")
# Function words carry no retrieval signal; they would make every node look like a partial match.
_STOP = set("""
a o as os um uma de do da dos das em no na nos nas por pelo pela para pra com sem e ou que qual
quais quando como onde porque se ser foi era sao esta estao mais menos ja ainda sobre entre ate
tambem foram tem ter fazer feito sido usa usam use usado the of and to in is are was what how why
which who for on with be it this that
""".split())


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(_fold(text)) if t not in _STOP}


class GraphIndex:
    """In-memory view of graph.json: node lookup plus an undirected adjacency map.

    Loaded once and reused; rebuilt only when the file's mtime changes.
    """

    def __init__(self, graph_path: Path):
        self.path = Path(graph_path)
        self._mtime: float | None = None
        self.nodes: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.adj: dict[str, list[str]] = {}
        self.by_file: dict[str, list[dict]] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.nodes, self.by_id, self.adj, self.by_file = [], {}, {}, {}
            return
        mtime = self.path.stat().st_mtime
        if self._mtime == mtime and self.nodes:
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.nodes = data.get("nodes", [])
        self.by_id = {n["id"]: n for n in self.nodes if "id" in n}
        adj: dict[str, list[str]] = collections.defaultdict(list)
        for link in data.get("links", []):
            s, t = link.get("source"), link.get("target")
            if s is not None and t is not None:
                adj[s].append(t)
                adj[t].append(s)
        self.adj = dict(adj)
        by_file: dict[str, list[dict]] = collections.defaultdict(list)
        for n in self.nodes:
            f = str(n.get("source_file", "")).replace("\\", "/")
            if f:
                by_file[f].append(n)
        self.by_file = dict(by_file)
        self._mtime = mtime

    @property
    def loaded(self) -> bool:
        return bool(self.nodes)

    def nodes_for_files(self, files: list[str]) -> list[str]:
        """Node ids belonging to the given files, page nodes first (they anchor the BFS)."""
        out: list[str] = []
        for f in files:
            group = self.by_file.get(f, [])
            for n in sorted(group, key=lambda x: 0 if x.get("node_kind") == "page" else 1):
                if "id" in n:
                    out.append(n["id"])
        return out

    def expand(self, seed_ids: list[str], max_files: int, exclude: set[str]) -> list[str]:
        """BFS from seeds, returning NEW related files in discovery order.

        Breadth-first matters: it surfaces direct neighbours (same note, linked notes) before
        distant ones, so a truncation keeps the closest structural context.
        """
        if not self.adj or not seed_ids:
            return []
        seen: set[str] = set(seed_ids)
        frontier = list(seed_ids)
        found: list[str] = []
        got: set[str] = set(exclude)
        while frontier and len(found) < max_files:
            nxt: list[str] = []
            for nid in frontier:
                for m in self.adj.get(nid, ()):
                    if m in seen:
                        continue
                    seen.add(m)
                    nxt.append(m)
                    node = self.by_id.get(m)
                    if not node:
                        continue
                    f = str(node.get("source_file", "")).replace("\\", "/")
                    if f and f not in got:
                        got.add(f)
                        found.append(f)
                        if len(found) >= max_files:
                            break
                if len(found) >= max_files:
                    break
            frontier = nxt
        return found

    def lexical_seed_files(self, query: str, limit: int) -> list[str]:
        """Fallback entry points from label matching, used when BM25 returns nothing."""
        qt = _terms(query)
        if not qt or not self.nodes:
            return []
        scored: list[tuple[float, str]] = []
        for n in self.nodes:
            hay = f"{_fold(n.get('label', ''))} {_fold(n.get('norm_label', ''))} {_fold(n.get('source_file', ''))}"
            hits = sum(1 for t in qt if t in hay)
            if hits:
                bonus = 0.5 if n.get("node_kind") == "page" else 0.0
                f = str(n.get("source_file", "")).replace("\\", "/")
                if f:
                    scored.append((hits + bonus, f))
        scored.sort(key=lambda x: -x[0])
        out: list[str] = []
        for _, f in scored:
            if f not in out:
                out.append(f)
            if len(out) >= limit:
                break
        return out


def hybrid_search(gw, query: str, limit: int, text_seeds: int = 10,
                  graph_expand: int = 15) -> tuple[list[Candidate], dict]:
    """BM25 entry points + graph neighbours. Returns (candidates, metrics).

    Scores are assigned so ordering is meaningful downstream: BM25 hits keep a high band
    (1.0 -> 0.55 by rank) and graph-only neighbours sit below it (0.5 -> 0.3), because a note
    found purely by structure is weaker evidence than one whose text matches the query.
    """
    t0 = time.perf_counter()
    rc = gw.retrieval_cfg
    index: GraphIndex = gw.graph_index
    index.load()

    bm = gw.baseline.search(query, limit=max(rc.max_candidates, limit))
    seed_files: list[str] = []
    for c in bm:
        f = c.source_file.replace("\\", "/")
        if f not in seed_files:
            seed_files.append(f)
        if len(seed_files) >= text_seeds:
            break
    t_text = time.perf_counter()

    if not seed_files:
        seed_files = index.lexical_seed_files(query, text_seeds)

    related = index.expand(index.nodes_for_files(seed_files), graph_expand, set(seed_files)) \
        if index.loaded else []
    t_graph = time.perf_counter()

    order = {f: i for i, f in enumerate(seed_files)}
    n_seeds = max(len(seed_files), 1)
    cands: list[Candidate] = []

    for c in bm:
        f = c.source_file.replace("\\", "/")
        if f not in order:
            continue
        rank = order[f]
        c.score = round(1.0 - 0.45 * (rank / n_seeds), 4)
        c.origin = "graphify_hybrid:text"
        c.meta = {**(c.meta or {}), "seed": True, "via": "bm25"}
        cands.append(c)

    # Graph-only notes: pull their best section through the same section splitter Graphify uses,
    # so a structurally-related note still arrives with real content rather than a bare title.
    for i, f in enumerate(related):
        node = next((n for n in index.by_file.get(f, []) if n.get("node_kind") == "page"),
                    (index.by_file.get(f) or [None])[0])
        line = 1
        if node:
            loc = node.get("source_location")
            if isinstance(loc, dict):
                line = int(loc.get("line", 1) or 1)
            elif isinstance(loc, (int, str)) and str(loc).isdigit():
                line = int(loc)
        try:
            sec, body = gw.graphify._section_for(f, line)
        except (OSError, PermissionError, ValueError):
            continue
        if sec is None:
            continue
        cands.append(Candidate(
            candidate_id=f"gx{i:03d}:{f}#L{sec.line}",
            source_file=f, section=sec.heading_path, snippet=body,
            score=round(0.5 - 0.2 * (i / max(len(related), 1)), 4),
            origin="graphify_hybrid:graph",
            meta={"seed": False, "via": "graph", "node_label": (node or {}).get("label")},
        ))

    metrics = {
        "graphify_latency_ms": round((t_graph - t0) * 1000, 1),
        "graphify_text_seed_ms": round((t_text - t0) * 1000, 1),
        "graphify_nodes_returned": len(cands),
        "graphify_seeds": len(seed_files),
        "graphify_graph_expanded": len(related),
        "graphify_graph_available": index.loaded,
        "graphify_truncated": False,
        "graphify_mode": "hybrid",
    }
    return cands[:limit], metrics
