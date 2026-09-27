"""Compare seed-selection strategies for Graphify against the real benchmark questions.

Deterministic, zero LLM tokens. Answers one question: at which stage is the ground-truth note
lost, and does seeding from the graph JSON (instead of the CLI's own label match) recover it?

Usage:  python scripts/graphify_seed_experiment.py
"""
from __future__ import annotations

import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.graphify import GraphifyService  # noqa: E402
from app.services.obsidian import ObsidianVault  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402

STOP = set("""
a o as os um uma de do da dos das em no na nos nas por pelo pela para pra com sem e ou que qual
quais quando como onde porque se ser foi era eh sao esta estao mais menos ja ainda sobre entre ate
tambem foram tem ter fazer feito sido the of and to in is are was what how why which who for on
with be it this that usa usam use usado onde qual quais
""".split())
TOKEN = re.compile(r"[a-z0-9]{3,}")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def terms(s: str) -> set[str]:
    return {t for t in TOKEN.findall(fold(s)) if t not in STOP}


def load_graph(path: Path) -> tuple[list[dict], dict[str, list[str]]]:
    g = json.loads(path.read_text(encoding="utf-8"))
    nodes = g["nodes"]
    adj: dict[str, list[str]] = collections.defaultdict(list)
    for e in g.get("links", []):
        s, t = e.get("source"), e.get("target")
        if s is not None and t is not None:
            adj[s].append(t)
            adj[t].append(s)
    return nodes, adj


def node_text(n: dict) -> str:
    return " ".join(fold(n.get(k, "")) for k in ("label", "norm_label", "source_file"))


def lexical_seeds(nodes: list[dict], query: str, k: int = 12) -> list[dict]:
    """Score every node in the graph by query-term overlap; take the best k."""
    qt = terms(query)
    if not qt:
        return []
    scored = []
    for n in nodes:
        hay = node_text(n)
        hits = sum(1 for t in qt if t in hay)
        if not hits:
            continue
        # a page node matching by filename is a stronger signal than a deep heading
        bonus = 0.5 if n.get("node_kind") == "page" else 0.0
        scored.append((hits + bonus, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:k]]


def expand(nodes: list[dict], adj: dict, seeds: list[dict], limit: int) -> list[dict]:
    """BFS from seeds over the real graph edges, preserving discovery order."""
    by_id = {n["id"]: n for n in nodes}
    seen, order, frontier = set(), [], [n["id"] for n in seeds]
    for nid in frontier:
        if nid not in seen:
            seen.add(nid)
            order.append(nid)
    while frontier and len(order) < limit:
        nxt = []
        for nid in frontier:
            for m in adj.get(nid, []):
                if m not in seen:
                    seen.add(m)
                    order.append(m)
                    nxt.append(m)
                    if len(order) >= limit:
                        break
            if len(order) >= limit:
                break
        frontier = nxt
    return [by_id[i] for i in order if i in by_id]


def files_of(nodes: list[dict]) -> list[str]:
    out, seen = [], set()
    for n in nodes:
        f = str(n.get("source_file", "")).replace("\\", "/")
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def main() -> None:
    rc = RetrievalConfig()
    vault = ObsidianVault(rc.vault_path, rc.excluded_dirs)
    gsvc = GraphifyService(vault, rc.mirror_dir, rc.graphify_bin, rc.graphify_query_budget,
                           rc.graphify_timeout_s)
    nodes, adj = load_graph(gsvc.graph_path)
    questions = json.loads(Path("benchmark/questions.json").read_text(encoding="utf-8"))
    answerable = [q for q in questions if q.get("answerable")]

    # Strategy D needs a body-text index: the graph only knows heading labels, so an answer that
    # lives in a note's BODY (q06: port numbers, container names) is invisible to every
    # graph-only strategy. BM25 over section bodies is exactly what the baseline pipeline has.
    from app.retrieval.baseline import BaselineIndex
    bi = BaselineIndex(vault)
    bi.build()

    print(f"graph: {len(nodes)} nodes, {len(files_of(nodes))} files")
    print(f"questions: {len(answerable)} answerable\n")

    results = collections.defaultdict(lambda: [0, 0])
    rows = []
    for q in answerable:
        exp = set(q["expected_sources"])
        row = {"id": q["id"]}

        # A: current CLI behaviour
        out = gsvc.raw_query(q["question"])
        cli_nodes, _ = gsvc.parse(out)
        cli_files = [n["src"].replace("\\", "/") for n in cli_nodes]
        row["cli"] = bool(exp & set(cli_files))
        row["cli_pos"] = next((i for i, f in enumerate(cli_files) if f in exp), None)

        # B: lexical seeds over graph.json, no expansion
        seeds = lexical_seeds(nodes, q["question"])
        sf = files_of(seeds)
        row["seed"] = bool(exp & set(sf))
        row["seed_pos"] = next((i for i, f in enumerate(sf) if f in exp), None)

        # C: lexical seeds + BFS expansion over real edges
        exp_nodes = expand(nodes, adj, seeds, 100)
        ef = files_of(exp_nodes)
        row["hybrid"] = bool(exp & set(ef))
        row["hybrid_pos"] = next((i for i, f in enumerate(ef) if f in exp), None)

        # D: body-text (BM25) seeds UNION graph expansion — graph for structure, text for content
        bm = bi.search(q["question"], limit=20)
        bm_files = []
        for c in bm:
            f = c.source_file.replace("\\", "/")
            if f not in bm_files:
                bm_files.append(f)
        union = bm_files[:10] + [f for f in ef if f not in bm_files[:10]]
        row["union"] = bool(exp & set(union))
        row["union_pos"] = next((i for i, f in enumerate(union) if f in exp), None)

        for k in ("cli", "seed", "hybrid", "union"):
            results[k][0] += int(row[k])
            results[k][1] += 1
        rows.append(row)

    print(f"{'q':<5} {'CLI atual':<16} {'seeds lex':<16} {'seeds+BFS':<16} {'BM25+grafo':<16}")
    print("-" * 74)
    for r in rows:
        def cell(k):
            return ("OK pos=" + str(r[k + "_pos"])) if r[k] else "PERDEU"
        print(f"{r['id']:<5} {cell('cli'):<16} {cell('seed'):<16} {cell('hybrid'):<16} {cell('union'):<16}")

    print("\nRECALL (ground truth no pool de candidatos)")
    for k, label in (("cli", "CLI atual"), ("seed", "seeds lexicais"),
                     ("hybrid", "seeds+BFS"), ("union", "BM25+grafo")):
        hit, tot = results[k]
        print(f"  {label:<18} {hit}/{tot}  ({hit / tot * 100:.1f}%)")



if __name__ == "__main__":
    main()
