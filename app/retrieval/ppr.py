"""Personalized PageRank over `graph.json`, HippoRAG-style (§5.5 da proposta 2026-09-28).

WHY THIS EXISTS
----------------
`GraphIndex.expand()` (app/retrieval/graphify_hybrid.py) walks the graph breadth-first from the
BM25 seed nodes and returns the first `graph_expand` NEW files it touches, in discovery order. BFS
treats every edge as equally important and every seed as equally important, so a seed with a weak
BM25 score pollutes the frontier exactly as much as the strongest one, and a node reachable through
many short paths (a hub) is not preferred over one reachable through a single long path.

HippoRAG (Gutiérrez et al. 2024) showed that running Personalized PageRank from the retrieval seeds,
weighted by how confident the seed match was, recovers multi-hop answers a fixed-depth BFS misses:
mass concentrates on nodes that are well-connected to MULTIPLE strong seeds, which is exactly the
"combine facts scattered across two notes" shape of a multi-hop question. This module is a pure,
deterministic, dependency-free re-implementation of that idea over the graph Graphify already
builds (no new node types, no new data — the same `adj` map `GraphIndex` already loads).

DETERMINISM
------------
Plain power iteration over Python dicts, sorted node order at every ranking step, no randomness,
no external library. Same graph + same seeds + same parameters -> byte-identical output, every
run, on any machine. Behind `PPR_ENABLED` (default False, see config/retrieval.py): the flag off
reproduces the exact BFS behaviour this module never touches.
"""
from __future__ import annotations


def personalized_pagerank(adj: dict[str, list[str]], seed_weights: dict[str, float],
                          alpha: float = 0.85, iters: int = 30) -> dict[str, float]:
    """Power iteration for Personalized PageRank on an undirected graph given as an adjacency map.

    `seed_weights` is the (unnormalized) restart/personalization distribution: mass teleports back
    to these nodes, proportionally to their weight, every iteration. Dangling nodes (no outgoing
    edges) redistribute their mass to the restart distribution rather than vanishing, so total mass
    is conserved across iterations (sums to 1.0, modulo float error) regardless of graph shape.

    Returns {} if there are no positive-weight seeds or no graph to walk.
    """
    total = sum(w for w in seed_weights.values() if w > 0)
    if total <= 0 or not adj:
        return {}
    restart = {n: w / total for n, w in seed_weights.items() if w > 0}
    nodes = sorted(set(adj) | set(restart))
    p = {n: restart.get(n, 0.0) for n in nodes}
    a = max(0.0, min(1.0, alpha))
    for _ in range(max(0, iters)):
        nxt = {n: 0.0 for n in nodes}
        dangling = 0.0
        for n in nodes:
            pn = p.get(n, 0.0)
            if pn <= 0.0:
                continue
            neighbors = adj.get(n) or []
            if not neighbors:
                dangling += pn
                continue
            share = pn / len(neighbors)
            for m in neighbors:
                nxt[m] = nxt.get(m, 0.0) + share
        for n in nodes:
            nxt[n] = a * (nxt[n] + dangling * restart.get(n, 0.0)) + (1 - a) * restart.get(n, 0.0)
        p = nxt
    return p


def seed_weights_from_files(index, seed_files: list[str], scores: dict[str, float]) -> dict[str, float]:
    """Map BM25 seed files to graph node weights, anchored on each file's PAGE node.

    `GraphIndex.nodes_for_files` already orders page nodes before heading nodes for a file, so the
    first id is the anchor. A file with no positive score (e.g. missing from `scores`) still seeds
    with a small floor weight so it can participate in the walk — PPR needs every seed to carry some
    positive mass, unlike BFS which only needs a starting node.
    """
    weights: dict[str, float] = {}
    for f in seed_files:
        node_ids = index.nodes_for_files([f])
        if not node_ids:
            continue
        w = max(float(scores.get(f, 0.0)), 1e-4)
        anchor = node_ids[0]
        weights[anchor] = weights.get(anchor, 0.0) + w
    return weights


def expand(index, seed_files: list[str], scores: dict[str, float], top_n: int,
          alpha: float, iters: int, exclude: set[str]) -> list[str]:
    """Drop-in PPR replacement for `GraphIndex.expand`: returns NEW related files, best score first.

    Same contract as the BFS version (a list of up to `top_n` file paths not already in `exclude`),
    so callers can switch between the two with no other code change.
    """
    if not index.adj or not seed_files:
        return []
    weights = seed_weights_from_files(index, seed_files, scores)
    if not weights:
        return []
    scored = personalized_pagerank(index.adj, weights, alpha=alpha, iters=iters)
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    seen = set(exclude)
    out: list[str] = []
    for node_id, _score in ranked:
        node = index.by_id.get(node_id)
        if not node:
            continue
        f = str(node.get("source_file", "")).replace("\\", "/")
        if not f or f in seen:
            continue
        seen.add(f)
        out.append(f)
        if len(out) >= top_n:
            break
    return out
