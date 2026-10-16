"""ANAM-018 (AUD-010/011): manifesto barato do vault + reindexação incremental + diff.

`ObsidianVault.fingerprint()` percorre `list_searchable()` (os.walk + realpath por diretório +
islink por arquivo) e depois faz `os.stat` de CADA nota a cada `refresh_interval_s`. Aqui o mesmo
conjunto de arquivos é varrido com `os.scandir`, cujo `DirEntry.stat()` no Windows vem da própria
listagem do diretório (sem syscall por arquivo). O resultado é um *manifesto* {rel: (mtime_ns, size)}
que serve a três usos sem custo extra: (1) fingerprint idêntico ao do vault (mesma tupla), (2) diff
exato entre dois refreshes (adicionadas/alteradas/removidas) e (3) entrada da invalidação seletiva
de cache e da reindexação por arquivo. Somente leitura: nada é escrito no vault.

Qualquer situação exótica (symlink/junction, erro de E/S) devolve None e o chamador cai no caminho
antigo (`vault.fingerprint()` + rebuild completo), então a mudança nunca reduz a correção.
"""
from __future__ import annotations

import hashlib
import os
import unicodedata
from dataclasses import dataclass, field

# Acima disto (fração de notas alteradas) o rebuild completo é mais barato/seguro que o incremental.
INCREMENTAL_MAX_FRACTION = 0.25
INCREMENTAL_MAX_FILES = 500


@dataclass
class Manifest:
    files: dict[str, tuple[int, int]]          # rel -> (mtime_ns, size), na ordem do vault
    fp: tuple                                   # mesma tupla de ObsidianVault.fingerprint()


@dataclass
class ManifestDiff:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    @property
    def touched(self) -> list[str]:
        return self.added + self.changed

    def size(self) -> int:
        return len(self.added) + len(self.changed) + len(self.removed)


def _walk(root: str, prefix: str, skip_dirs: set[str], hide_dirs_only_dot: bool, out: dict) -> bool:
    """Varre `root`; False se achar symlink/junction (o chamador volta ao caminho antigo)."""
    stack = [root]
    while stack:
        cur = stack.pop()
        with os.scandir(cur) as it:
            for e in it:
                name = e.name
                if name.startswith("."):
                    continue
                if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                    return False
                if e.is_dir(follow_symlinks=False):
                    if not hide_dirs_only_dot and name in skip_dirs:
                        continue
                    stack.append(e.path)
                elif name.lower().endswith(".md"):
                    st = e.stat(follow_symlinks=False)
                    rel = os.path.relpath(e.path, root).replace("\\", "/")
                    out[f"{prefix}{rel}"] = (st.st_mtime_ns, st.st_size, st.st_mtime)
    return True


def scan_manifest(vault) -> Manifest | None:
    """Manifesto do vault do usuário + raízes extras; None se não for seguro usar o atalho."""
    try:
        own: dict = {}
        if not _walk(str(vault.root), "", set(vault.excluded_dirs), False, own):
            return None
        extra: dict = {}
        for prefix, root in vault.extra_roots.items():
            if root.is_dir() and not _walk(str(root), f"{prefix}/", set(), True, extra):
                return None
    except OSError:
        return None
    ordered = {k: own[k] for k in sorted(own)}
    ordered.update({k: extra[k] for k in sorted(extra)})
    paths = hashlib.sha256()
    size = 0
    newest = 0.0
    for rel, (_, sz, mt) in ordered.items():
        size += sz
        newest = max(newest, mt)
        paths.update(rel.encode("utf-8") + b"\n")
    files = {k: (v[0], v[1]) for k, v in ordered.items()}
    return Manifest(files, (len(files), size, round(newest, 3), paths.hexdigest()[:16]))


def diff_manifests(old: dict, new: dict) -> ManifestDiff:
    d = ManifestDiff()
    for rel, sig in new.items():
        prev = old.get(rel)
        if prev is None:
            d.added.append(rel)
        elif prev != sig:
            d.changed.append(rel)
    d.removed = [rel for rel in old if rel not in new]
    return d


def is_small(diff: ManifestDiff, total: int) -> bool:
    n = diff.size()
    return 0 < n <= INCREMENTAL_MAX_FILES and n <= max(1, int(total * INCREMENTAL_MAX_FRACTION))


def fold(text: str) -> str:
    """minúsculas sem acento: comparação conservadora de termos (superconjunto do unicode61)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def read_touched(vault, rels: list[str]) -> dict[str, str] | None:
    """Texto das notas adicionadas/alteradas; None se alguma sumiu no meio (cai no rebuild)."""
    out: dict[str, str] = {}
    try:
        for rel in rels:
            out[rel] = vault.read(rel)
    except Exception:  # noqa: BLE001 -- corrida com escrita/remoção: não dá para provar o diff
        return None
    return out


def reindex_incremental(baseline, diff: ManifestDiff, texts: dict[str, str], total_files: int) -> bool:
    """Atualiza o índice lexical só nas notas do diff. False -> o chamador faz `build()` completo.

    `IncrementalBaselineIndex` (MG_INCREMENTAL_INDEX=1) já indexa por arquivo no seu `build()`;
    o `BaselineIndex` em memória é atualizado aqui por DELETE/INSERT dos arquivos afetados.
    """
    if hasattr(baseline, "last_stats"):       # IncrementalBaselineIndex: build() já é por arquivo
        baseline.build()
        return True
    conn, lock = getattr(baseline, "conn", None), getattr(baseline, "_lock", None)
    if conn is None or lock is None or not hasattr(baseline, "sections_indexed"):
        return False
    from app.services.obsidian import frontmatter_status, split_sections
    try:
        with lock:
            with conn:
                for rel in diff.changed + diff.removed:
                    conn.execute("DELETE FROM sec WHERE file = ?", (rel,))
                for rel in diff.touched:
                    text = texts[rel]
                    status = frontmatter_status(text) or ""
                    for s in split_sections(text):
                        conn.execute("INSERT INTO sec VALUES (?,?,?,?,?)",
                                     (rel, s.heading_path, s.text, status, s.line))
            baseline.sections_indexed = conn.execute("SELECT COUNT(*) FROM sec").fetchone()[0]
            baseline.files_indexed = total_files
    except Exception:  # noqa: BLE001 -- transação revertida pelo `with conn`; rebuild completo
        return False
    return True


def entry_is_affected(key: tuple, value, diff: ManifestDiff, folded_new: dict[str, str]) -> bool:
    """True se a resposta em cache pode ter mudado por causa do diff (critérios 2 e 6 do relatório A2).

    Afetada se: uma nota ENTREGUE foi alterada/removida, ou alguma nota nova/alterada contém um
    termo da consulta canônica (inclui casos negativos). Sem guard -> afetada (conservador).
    """
    guard = value[4] if isinstance(value, tuple) and len(value) > 4 else None
    if not guard or "files" not in guard:
        return True
    delivered = guard["files"]
    if any(rel in delivered for rel in diff.changed + diff.removed):
        return True
    terms = [t for t in fold(str(key[1])).split() if len(t) >= 2]
    if not terms:
        return True
    return any(t in body for body in folded_new.values() for t in terms)
