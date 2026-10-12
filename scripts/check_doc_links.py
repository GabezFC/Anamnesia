"""Verificador de links relativos em Markdown (ANA-136). Sem rede, só stdlib.

    python scripts/check_doc_links.py                 # exit 1 se houver link/âncora quebrado
    python scripts/check_doc_links.py --paths         # também checa `docs/…`/`app/…` entre crases
    python scripts/check_doc_links.py --code-refs     # lista referências `docs/X.md` em comentários do código

Checa: [txt](caminho#âncora), [txt]: caminho (referência), <img src>. Ignora http(s)/mailto/tel,
blocos de código cercados e `code spans`. Âncoras são validadas contra os títulos do .md de destino
(slug estilo GitHub).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "node_modules", "graphify-out", "vendor", "__pycache__", ".pytest_cache",
             ".ruff_cache", ".mypy_cache", "build", "dist"}
# Só na raiz do repo (docs/reports/ É verificado; reports/ da raiz são saídas geradas de benchmark).
SKIP_TOP = {"data", "reports", "spikes", "logs", "integrations", "benchmark"}
MD_GLOBS = ("*.md",)
EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")
INLINE = re.compile(r"(?<!\\)!?\[(?:[^\]\\]|\\.)*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
REFDEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
HTML_SRC = re.compile(r"""<(?:img|a)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", re.I)
FENCE = re.compile(r"^\s{0,3}(```+|~~~+)")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
PATH_REF = re.compile(r"^(?:docs|app|config|scripts|tests|frontend|integrations|memory_gateway|anamnesia)/[\w./\-]+$")


def md_files(root: Path = ROOT) -> list[Path]:
    out = []
    for g in MD_GLOBS:
        for p in root.rglob(g):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts[:-1]) or (len(rel.parts) > 1 and rel.parts[0] in SKIP_TOP):
                continue
            out.append(p)
    return sorted(out)


def slug(title: str) -> str:
    t = re.sub(r"<[^>]+>", "", title)
    t = re.sub(r"[`*_~]", "", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t).strip().lower()
    t = re.sub(r"[^\w\s\-]", "", t, flags=re.UNICODE)
    return re.sub(r"\s", "-", t)


def _body_lines(text: str):
    """(nº da linha, texto) das linhas fora de blocos cercados."""
    fence = None
    for i, line in enumerate(text.splitlines(), 1):
        m = FENCE.match(line)
        if m:
            tok = m.group(1)
            if fence is None:
                fence = tok[0]
            elif tok[0] == fence:
                fence = None
            continue
        if fence is None:
            yield i, line


def anchors_of(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path in cache:
        return cache[path]
    seen: dict[str, int] = {}
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        cache[path] = out
        return out
    for _, line in _body_lines(text):
        m = HEADING.match(line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    for m in re.finditer(r"""<a\s+(?:name|id)=["']([^"']+)["']""", text, re.I):
        out.add(m.group(1))
    cache[path] = out
    return out


def targets(text: str):
    """(linha, alvo) de cada link fora de código."""
    for i, line in _body_lines(text):
        clean = CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        for rx in (INLINE, HTML_SRC):
            for m in rx.finditer(clean):
                yield i, m.group(1)
        m = REFDEF.match(clean)
        if m:
            yield i, m.group(1)


def check(root: Path = ROOT, files: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    cache: dict[Path, set[str]] = {}
    for f in files if files is not None else md_files(root):
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8")
        for line, tgt in targets(text):
            if EXTERNAL.match(tgt) or tgt.startswith("{{"):
                continue
            path_part, _, frag = tgt.partition("#")
            path_part = unquote(path_part.split("?")[0])
            dest = f if not path_part else (root / path_part.lstrip("/") if path_part.startswith("/")
                                            else (f.parent / path_part))
            try:
                dest = dest.resolve()
            except OSError:
                errors.append(f"{rel}:{line}: alvo inválido {tgt}")
                continue
            if not dest.exists():
                errors.append(f"{rel}:{line}: link quebrado -> {tgt}")
                continue
            if frag and dest.suffix.lower() == ".md" and dest.is_file():
                if unquote(frag).lower() not in anchors_of(dest, cache):
                    errors.append(f"{rel}:{line}: âncora inexistente -> {tgt}")
    return errors


def check_paths(root: Path = ROOT, files: list[Path] | None = None, prefix: str | None = "docs/") -> list[str]:
    """Caminhos de repo entre crases (`docs/X.md`, `app/y.py`) que não existem (sem globs/placeholders)."""
    errors: list[str] = []
    for f in files if files is not None else md_files(root):
        rel = f.relative_to(root).as_posix()
        text = f.read_text(encoding="utf-8")
        for i, line in _body_lines(text):
            for m in CODE_SPAN.finditer(line):
                s = m.group(2).strip().rstrip(".,:;)")
                s = s.split("::")[0].split("#")[0]
                if not PATH_REF.match(s) or "*" in s or "<" in s or "{" in s:
                    continue
                if prefix and not s.startswith(prefix):
                    continue
                if not (root / s).exists():
                    errors.append(f"{rel}:{i}: caminho citado inexistente -> {s}")
    return errors


def code_refs(root: Path = ROOT) -> list[str]:
    """`docs/NOME.md` citados em fontes .py/.js/.yml/.toml que não existem mais."""
    rx = re.compile(r"\bdocs/[A-Za-z0-9_./\-]+\.(?:md|json)\b")
    out = []
    for base in ("app", "config", "scripts", "tests", "anamnesia", "memory_gateway", "frontend/js", ".github"):
        d = root / base
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if not p.is_file() or p.suffix not in {".py", ".js", ".yml", ".yaml", ".toml", ".mjs", ".sh"}:
                continue
            if "vendor" in p.parts or "__pycache__" in p.parts or p.name == "check_doc_links.py":
                continue
            try:
                txt = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(txt.splitlines(), 1):
                for m in rx.finditer(line):
                    if "<" in m.group(0) or not (root / m.group(0)).exists():
                        out.append(f"{p.relative_to(root).as_posix()}:{i}: {m.group(0)}")
    return out


def fix_code_refs(root: Path = ROOT) -> list[str]:
    """Reescreve `docs/NOME.md` -> `docs/guides|reports/NOME.md` em comentários/docstrings do código
    (só quando NOME existir em docs/guides ou docs/reports). Preserva fins de linha. Retorna arquivos alterados."""
    loc = {p.name: f"docs/{sub}/{p.name}" for sub in ("guides", "reports") for p in (root / "docs" / sub).glob("*")
           if p.is_file()}
    rx = re.compile(r"\bdocs/([A-Za-z0-9_\-]+\.(?:md|json))\b")
    changed = []
    for ref in code_refs(root):
        rel = ref.split(":", 1)[0]
        if rel in changed or rel.startswith("scripts/check_doc_links.py"):
            continue
        p = root / rel
        raw = p.read_bytes()
        new = rx.sub(lambda m: loc.get(m.group(1), m.group(0)), raw.decode("utf-8"))
        if new.encode("utf-8") != raw:
            p.write_bytes(new.encode("utf-8"))
            changed.append(rel)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--paths", action="store_true", help="também checa caminhos docs/… entre crases")
    ap.add_argument("--code-refs", action="store_true", help="lista referências docs/… obsoletas no código (informativo)")
    ap.add_argument("--fix-code-refs", action="store_true", help="reescreve referências docs/… obsoletas no código")
    ns = ap.parse_args(argv)
    if ns.fix_code_refs:
        for r in fix_code_refs():
            print("reescrito", r)
        return 0
    errs = check()
    if ns.paths:
        errs += check_paths()
    for e in errs:
        print(e)
    if ns.code_refs:
        refs = code_refs()
        print(f"-- {len(refs)} referência(s) docs/… no código apontando para arquivo inexistente")
        for r in refs:
            print("  " + r)
    print(f"{len(md_files())} arquivos .md verificados, {len(errs)} problema(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
