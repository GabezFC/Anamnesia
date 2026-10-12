"""Architecture gate (ANA-081): layer contract (scripts/layers.toml) + module-level import cycles.

Usage: python scripts/check_architecture.py [--layers scripts/layers.toml] [--root .] [--json]
Exit 1 on: (a) a module-level import that goes UP the layer contract, (b) a lazy (in-function) upward
import not whitelisted in `allowed_upward`, (c) a module-level import cycle (SCC > 1 module).
Packages without a layer are only reported (use --strict to fail on them).
AST only: nothing is imported or executed.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAYERS = Path(__file__).with_name("layers.toml")


def load_contract(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data.setdefault("roots", ["app"])
    data.setdefault("layers", {})
    data["allowed"] = {(e["edge"][0], e["edge"][1]) for e in data.get("allowed_upward", [])}
    data["allowed_cycles"] = [sorted(c["modules"]) for c in data.get("allowed_cycles", [])]
    return data


def _modname(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def collect_imports(root: Path, roots: list[str]) -> tuple[dict[str, set[str]], list[tuple[str, str, bool]]]:
    """-> (modules {name: {}}, edges [(importer, imported, is_top_level)])."""
    files: dict[str, Path] = {}
    for r in roots:
        base = root / r
        if base.is_file():
            files[r] = base
        elif base.is_dir():
            for p in base.rglob("*.py"):
                if "__pycache__" not in p.parts:
                    files[_modname(p, root)] = p
        elif (root / f"{r}.py").is_file():
            files[r] = root / f"{r}.py"
    edges: list[tuple[str, str, bool]] = []
    for mod, path in files.items():
        is_pkg = path.name == "__init__.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        top = {id(n) for n in tree.body}
        # `if TYPE_CHECKING:` blocks and try/except at module level still count as top-level.
        for n in tree.body:
            if isinstance(n, (ast.If, ast.Try)):
                for sub in ast.walk(n):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)) and not _inside_def(n, sub):
                        top.add(id(sub))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                targets = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    pkg_parts = mod.split(".") if is_pkg else mod.split(".")[:-1]
                    pkg_parts = pkg_parts[: len(pkg_parts) - (n.level - 1)] if n.level > 1 else pkg_parts
                    base = ".".join(pkg_parts + ([n.module] if n.module else []))
                else:
                    base = n.module or ""
                targets = []
                for a in n.names:
                    sub = f"{base}.{a.name}" if base else a.name
                    # `from pkg import mod` imports the submodule when it exists; otherwise just `pkg`.
                    targets.append(sub if (a.name != "*" and sub in files) else base)
            else:
                continue
            for t in dict.fromkeys(targets):
                resolved = _resolve(t, files)
                if resolved and resolved != mod:
                    edges.append((mod, resolved, id(n) in top))
    return {m: set() for m in files}, edges


def _inside_def(container: ast.AST, target: ast.AST) -> bool:
    for sub in ast.walk(container):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and any(
            x is target for x in ast.walk(sub)
        ):
            return True
    return False


def _resolve(name: str, files: dict[str, Path]) -> str | None:
    while name:
        if name in files:
            return name
        name = name.rpartition(".")[0]
    return None


def layer_of(mod: str, layers: dict[str, int]) -> tuple[str | None, int | None]:
    best = None
    for key in layers:
        if (mod == key or mod.startswith(key + ".")) and (best is None or len(key) > len(best)):
            best = key
    return (best, layers[best]) if best else (None, None)


def find_cycles(modules: dict[str, set[str]], edges: list[tuple[str, str, bool]]) -> list[list[str]]:
    graph: dict[str, set[str]] = {m: set() for m in modules}
    for a, b, top in edges:
        if top:
            graph[a].add(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    counter = [0]

    def strong(v: str) -> None:  # iterative-safe enough for ~200 modules; recursion limit is fine
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in graph[v]:
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
    return sorted(out)


def check(root: Path = ROOT, layers_path: Path = DEFAULT_LAYERS) -> dict:
    contract = load_contract(layers_path)
    layers: dict[str, int] = contract["layers"]
    modules, edges = collect_imports(root, contract["roots"])
    violations: list[dict] = []
    unmapped: set[str] = set()
    seen_allowed: set[tuple[str, str]] = set()
    for a, b, top in edges:
        ka, la = layer_of(a, layers)
        kb, lb = layer_of(b, layers)
        for m, k in ((a, ka), (b, kb)):
            if k is None:
                unmapped.add(m.split(".")[0] if m.split(".")[0] != "app" or "." not in m else ".".join(m.split(".")[:2]))
        if la is None or lb is None or lb <= la or ka == kb:
            continue
        if not top and (ka, kb) in contract["allowed"]:
            seen_allowed.add((ka, kb))
            continue
        violations.append({"importer": a, "imported": b, "from_layer": ka, "to_layer": kb,
                           "kind": "top-level" if top else "lazy"})
    stale = sorted(contract["allowed"] - seen_allowed)
    return {
        "modules": len(modules),
        "edges": len(edges),
        "violations": sorted(violations, key=lambda v: (v["importer"], v["imported"])),
        "cycles": [c for c in find_cycles(modules, edges) if c not in contract["allowed_cycles"]],
        "unmapped": sorted(unmapped),
        "stale_allowed": [list(e) for e in stale],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--layers", type=Path, default=DEFAULT_LAYERS)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="also fail on packages without a layer")
    args = ap.parse_args(argv)
    res = check(args.root, args.layers)
    bad = bool(res["violations"] or res["cycles"] or (args.strict and res["unmapped"]))
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"architecture: {res['modules']} modules, {res['edges']} import edges")
        for v in res["violations"]:
            print(f"  FORBIDDEN {v['kind']} import: {v['importer']} ({v['from_layer']}) -> {v['imported']} ({v['to_layer']})")
        for c in res["cycles"]:
            print("  CYCLE: " + " <-> ".join(c))
        for u in res["unmapped"]:
            print(f"  note: no layer for {u} (add it to scripts/layers.toml)")
        for e in res["stale_allowed"]:
            print(f"  note: allowed_upward {e} is no longer used; remove it")
        print("FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
