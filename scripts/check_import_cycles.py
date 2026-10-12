"""Import-graph checker: module-level SCCs (Tarjan) and forbidden layer edges (ANA-056/107/108/081).

Usage: python scripts/check_import_cycles.py [--package app] [--json]
Exit 1 if any SCC with >1 module exists (lazy imports inside functions are counted too, with a
flag to ignore them: --top-level-only).
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modname(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def build_graph(root: Path = ROOT, package: str = "app", top_level_only: bool = False) -> dict[str, set[str]]:
    mods: dict[str, Path] = {}
    for p in (root / package).rglob("*.py"):
        mods[_modname(p, root)] = p
    graph: dict[str, set[str]] = {m: set() for m in mods}

    def resolve(name: str) -> str | None:
        # longest known module prefix
        parts = name.split(".")
        while parts:
            cand = ".".join(parts)
            if cand in mods:
                return cand
            parts.pop()
        return None

    for m, p in mods.items():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        is_pkg = p.name == "__init__.py"
        nodes = tree.body if top_level_only else list(ast.walk(tree))
        if top_level_only:
            stack = list(tree.body)
            nodes = []
            while stack:  # include imports nested in if/try at module level, not in defs
                n = stack.pop()
                nodes.append(n)
                if isinstance(n, (ast.If, ast.Try, ast.With)):
                    for fld in ("body", "orelse", "finalbody", "handlers"):
                        for c in getattr(n, fld, []) or []:
                            stack.append(c)
                            if isinstance(c, ast.ExceptHandler):
                                stack.extend(c.body)
        for n in nodes:
            targets: list[str] = []
            if isinstance(n, ast.Import):
                targets = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    base = m.split(".")
                    if not is_pkg:
                        base = base[:-1]
                    base = base[: len(base) - (n.level - 1)]
                    mod = ".".join(base + ([n.module] if n.module else []))
                else:
                    mod = n.module or ""
                targets = [mod] + [f"{mod}.{a.name}" for a in n.names]
            for t in targets:
                r = resolve(t)
                if r and r != m and r.startswith(package):
                    graph[m].add(r)
    return graph


def tarjan_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []
    counter = [0]
    sys.setrecursionlimit(max(1000, len(graph) * 4))

    def strong(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(sorted(comp))

    for v in sorted(graph):
        if v not in index:
            strong(v)
    return out


def edges_between(graph: dict[str, set[str]], src_prefix: str, dst_prefix: str) -> list[tuple[str, str]]:
    def under(m: str, pre: str) -> bool:
        return m == pre or m.startswith(pre + ".")

    return sorted((a, b) for a, bs in graph.items() if under(a, src_prefix) for b in bs if under(b, dst_prefix))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="app")
    ap.add_argument("--top-level-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    g = build_graph(package=a.package, top_level_only=a.top_level_only)
    sccs = tarjan_sccs(g)
    if a.json:
        print(json.dumps({"modules": len(g), "sccs": sccs}, indent=2))
    else:
        print(f"modules={len(g)} sccs={len(sccs)}")
        for c in sccs:
            print("  SCC:", ", ".join(c))
    return 1 if sccs else 0


if __name__ == "__main__":
    raise SystemExit(main())
