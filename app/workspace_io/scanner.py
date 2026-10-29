"""Varredura segura de um projeto existente (somente leitura).

Regras (cada arquivo ignorado recebe um MOTIVO, contado no relatório):
  * respeita .gitignore (raiz e subpastas);
  * pula diretórios de dependência/build/cache (node_modules, .git, .venv, dist...), links simbólicos e
    qualquer coisa que resolva para fora da raiz;
  * pula segredos por NOME (.env*, chaves, credenciais) — e por CONTEÚDO na etapa de indexação (scan_secrets);
  * pula binários (extensão ou byte NUL) e arquivos acima do limite.
"""
from __future__ import annotations

import fnmatch
import os
import stat
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from app.workspace_io.gitignore import GitIgnore, is_ignored

SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", "dist", "build", "target", ".next", ".nuxt", ".cache", ".idea", ".vscode",
    ".gradle", ".terraform", "coverage", ".coverage", "htmlcov", "site-packages", ".eggs", ".parcel-cache",
    "bower_components", ".turbo", ".svelte-kit",
})
SECRET_NAME_PATTERNS = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.kdbx", "id_rsa*",
    "id_ed25519*", "id_ecdsa*", "id_dsa*", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "credentials",
    "credentials.*", "*secret*", "*secrets*", "*.token", ".htpasswd", "service-account*.json", "*.tfstate",
    "*.tfstate.*", "*.tfvars",
)
BINARY_EXT = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".psd", ".svgz", ".zip", ".gz", ".tgz",
    ".bz2", ".xz", ".7z", ".rar", ".tar", ".jar", ".war", ".whl", ".exe", ".dll", ".so", ".dylib", ".bin", ".o",
    ".a", ".lib", ".class", ".pyc", ".pyd", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".mp3",
    ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".db",
    ".sqlite", ".sqlite3", ".parquet", ".pkl", ".npy", ".npz", ".onnx", ".pt", ".pth", ".safetensors", ".gguf",
    ".iso", ".dmg", ".lock",
})
DOC_EXT = frozenset({".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc"})
MARKERS = (
    "package.json", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "Cargo.toml", "go.mod", "pom.xml",
    "build.gradle", "composer.json", "Gemfile", "Dockerfile", "docker-compose.yml", "Makefile", "tsconfig.json",
    "AGENTS.md", "CLAUDE.md", "README.md", ".gitignore", ".github",
)
LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".jsx": "JavaScript", ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".swift": "Swift",
    ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".md": "Markdown", ".yml": "YAML", ".yaml": "YAML", ".json": "JSON", ".toml": "TOML", ".lua": "Lua",
}

DEFAULT_MAX_FILES = 20000         # arquivos examinados
DEFAULT_MAX_FILE_BYTES = 256 * 1024
HUGE_BYTES = 5 * 1024 * 1024      # acima disto: "enorme"


def is_secret_name(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatch(low, p) for p in SECRET_NAME_PATTERNS)


def looks_binary(head: bytes) -> bool:
    return b"\x00" in head


def _is_link(path: str | os.PathLike) -> bool:
    """Symlink, Windows junction OR any reparse point; fail closed on stat errors."""
    try:
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction and isjunction(path):
            return True
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


@dataclass
class FileInfo:
    rel: str
    path: Path
    size: int
    mtime_ns: int


@dataclass
class ScanResult:
    files: list[FileInfo] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)      # motivo -> n
    skipped_examples: dict[str, list[str]] = field(default_factory=dict)
    top_dirs: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    languages: Counter = field(default_factory=Counter)    # linguagem -> n arquivos
    truncated: bool = False
    cancelled: bool = False

    def skip(self, reason: str, rel: str) -> None:
        self.skipped[reason] += 1
        ex = self.skipped_examples.setdefault(reason, [])
        if len(ex) < 5:
            ex.append(rel)


def _safe_path(path: Path, root: Path, rel: str, res: ScanResult) -> bool:
    """Validate before I/O. Path checks are best-effort, not an atomic TOCTOU boundary."""
    if _is_link(path):
        res.skip("link_simbolico", rel)
        return False
    try:
        if not path.resolve(strict=True).is_relative_to(root):
            res.skip("fora_da_raiz", rel)
            return False
    except (OSError, RuntimeError):
        res.skip("sem_permissao", rel)
        return False
    return True


def _inspect_file(e, rel: str, stack: list[GitIgnore], res: ScanResult, max_file_bytes: int,
                  root: Path) -> FileInfo | None:
    """Decide se um arquivo entra no índice; registra o motivo em `res.skip` quando não entra."""
    if e.name != ".gitignore" and is_ignored(stack, rel, False):   # .gitignore nunca é ignorado por si mesmo
        res.skip("gitignore", rel)
        return None
    if is_secret_name(e.name):
        res.skip("segredo_por_nome", rel)
        return None
    ext = os.path.splitext(e.name)[1].lower()
    if ext in BINARY_EXT:
        res.skip("binario", rel)
        return None
    try:
        st = e.stat(follow_symlinks=False)
    except OSError:
        res.skip("sem_permissao", rel)
        return None
    if st.st_size > HUGE_BYTES:
        res.skip("enorme", rel)
        return None
    if st.st_size == 0:
        res.skip("vazio", rel)
        return None
    # Recheck after callbacks/metadata checks, immediately before the content read.
    if not _safe_path(Path(e.path), root, rel, res):
        return None
    try:
        with open(e.path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        res.skip("sem_permissao", rel)
        return None
    if looks_binary(head):
        res.skip("binario", rel)
        return None
    lang = LANG_BY_EXT.get(ext)
    if lang:
        res.languages[lang] += 1
    if st.st_size > max_file_bytes:
        res.skip("acima_do_limite", rel)
        return None
    return FileInfo(rel, Path(e.path), st.st_size, st.st_mtime_ns)


def _collect_markers(root_p: Path, res: ScanResult) -> None:
    for marker in MARKERS:
        path = root_p / marker
        try:
            if not _is_link(path) and path.resolve(strict=True).is_relative_to(root_p):
                res.markers.append(marker)
        except (OSError, RuntimeError):
            pass


def _scan_root(root: str | os.PathLike, res: ScanResult) -> Path | None:
    # Check the supplied root BEFORE resolve() erases its link/reparse identity.
    supplied_root = Path(os.path.abspath(root))
    if _is_link(supplied_root):
        res.skip("link_simbolico", ".")
        return None
    try:
        return supplied_root.resolve(strict=True)
    except (OSError, RuntimeError):
        res.skip("sem_permissao", ".")
        return None


def scan_project(root: str | os.PathLike, *, max_files: int = DEFAULT_MAX_FILES,
                 max_file_bytes: int = DEFAULT_MAX_FILE_BYTES, is_cancelled: Callable[[], bool] | None = None,
                 on_progress: Callable[[int, str], None] | None = None,
                 include_file: Callable[[str], bool] | None = None) -> ScanResult:
    """Scan root policy; include_file restricts content probes, not the traversal/file budget.

    Ignore-rule metadata is still read so ancestor rules remain effective.
    """
    res = ScanResult()
    root_p = _scan_root(root, res)
    if root_p is None:
        return res
    seen = 0
    _collect_markers(root_p, res)

    def walk(directory: Path, rel_dir: str, stack: list[GitIgnore]) -> Iterator[None]:
        nonlocal seen
        if not _safe_path(directory, root_p, rel_dir or ".", res):
            return
        ignore_file = directory / ".gitignore"
        # GitIgnore.load follows links: guard its input here, including root rules.
        ignore_rejected = False
        if os.path.lexists(ignore_file):
            ignore_rejected = not _safe_path(
                ignore_file, root_p, f"{rel_dir}/.gitignore" if rel_dir else ".gitignore", res)
            if not ignore_rejected:
                child = GitIgnore.load(directory, rel_dir)
                if child:
                    stack = stack + [child]
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            res.skip("sem_permissao", rel_dir or ".")
            return
        for e in entries:
            if res.truncated or res.cancelled:
                return
            if is_cancelled and is_cancelled():
                res.cancelled = True
                return
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            if e.name == ".gitignore" and ignore_rejected:
                continue  # Already rejected/counted before loading ignore rules.
            if not _safe_path(Path(e.path), root_p, rel, res):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                res.skip("sem_permissao", rel)
                continue
            if is_dir:
                if e.name in SKIP_DIRS or e.name.endswith(".egg-info"):
                    res.skip("pasta_dependencia_ou_build", rel)
                    continue
                if is_ignored(stack, rel, True):
                    res.skip("gitignore", rel + "/")
                    continue
                if not rel_dir:
                    res.top_dirs.append(e.name)
                yield from walk(Path(e.path), rel, stack)
                continue
            seen += 1
            if seen > max_files:
                res.truncated = True
                return
            if on_progress and seen % 200 == 0:
                on_progress(seen, rel)
            if include_file is not None and not include_file(rel):
                continue
            info = _inspect_file(e, rel, stack, res, max_file_bytes, root_p)
            if info is not None:
                res.files.append(info)
        yield None

    for _ in walk(root_p, "", []):
        pass
    return res
