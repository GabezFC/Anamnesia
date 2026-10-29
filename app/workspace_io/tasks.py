"""Inicialização/indexação, importação e exportação (reaproveita app.memory_store, lifecycle e o ledger de custos).

Todas as funções recebem `job` (progresso + cancelamento) e `apply`. Com apply=False NADA é gravado: o resultado é
a prévia exata do que apply=True faria. Segredos: nunca entram no índice, na nota-resumo nem em exportações.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.memory_store.store import (KINDS, InvalidNote, SavedContextError, SavedContextStore, content_digest,
                                    saved_context_dir, scan_secrets, slugify)
from app.workspace_io.jobs import Job
from app.workspace_io.scanner import DEFAULT_MAX_FILE_BYTES, ScanResult, scan_project
from config.paths import data_dir

log = logging.getLogger("anamnesia.workspace_io")
INDEX_VERSION = 1
MAX_IMPORT_ITEMS = 500
MAX_IMPORT_BYTES = 8 * 1024 * 1024
MAX_IMPORT_FILE_BYTES = 512 * 1024
IMPORT_EXT = (".md", ".markdown", ".json")
INIT_TAG = "workspace-init"


class WorkspaceIOError(Exception):
    """Erro de operação com código legível por máquina (a API o converte em {error:{code,message,hint}})."""

    def __init__(self, code: str, message: str, hint: str = "", status: int = 422):
        super().__init__(message)
        self.code, self.message, self.hint, self.status = code, message, hint, status


def in_docker() -> bool:
    return os.environ.get("MG_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


_WIN_PATH = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")


def is_windows_path(path: str) -> bool:
    return bool(_WIN_PATH.match(path or ""))


READ_ONLY_NOTE = ("raiz somente leitura: o índice, as memórias e o histórico são gravados no volume de dados "
                  "(ANAMNESIA_HOME), nunca na pasta do projeto; arquivos de ligação no projeto não serão criados.")


def project_availability(path: str) -> dict:
    """{available, code, reason, hint}: o diretório é visível e legível PARA ESTE PROCESSO? Nunca finge acesso."""
    docker = in_docker()
    if docker and is_windows_path(path) and os.name != "nt":
        return {"available": False, "code": "path_unavailable", "docker": True,
                "reason": f"caminho do Windows ({path}) não existe dentro do contêiner",
                "hint": "O Gateway roda em Docker: monte a pasta como volume (ex.: -v C:/meu-projeto:/workspace/meu-projeto) "
                        "e registre o caminho DENTRO do contêiner (/workspace/meu-projeto)."}
    p = Path(path or "")
    try:
        is_dir = p.is_dir()
    except OSError:
        is_dir = False
    if not is_dir:
        from app.terminals import path_map
        if path_map.active():
            hint = ("A pasta foi renomeada, movida ou removida no host (ou a raiz deixou de estar montada). "
                    "Remova o projeto e registre-o de novo com o caminho atual. " + path_map.RECREATE_HINT)
        else:
            hint = ("O Gateway roda em Docker e esta pasta do host não está montada no contêiner. Monte-a como volume "
                    "(ex.: -v C:/meu-projeto:/workspace/meu-projeto) e registre o caminho DENTRO do contêiner."
                    if docker else "Confirme que a pasta existe e está acessível a este processo.")
        return {"available": False, "code": "path_unavailable", "error_code": "path_not_found", "docker": docker,
                "reason": f"pasta do projeto inacessível: {path}", "hint": hint}
    if not os.access(p, os.R_OK | os.X_OK):
        return {"available": False, "code": "path_unreadable", "error_code": "path_permission", "docker": docker,
                "reason": f"sem permissão de leitura na pasta do projeto: {path}",
                "hint": "Ajuste as permissões da pasta (ou do volume montado) para o usuário que executa o Gateway."}
    try:
        next(os.scandir(p), None)
    except PermissionError:
        return {"available": False, "code": "path_unreadable", "error_code": "path_permission", "docker": docker,
                "reason": f"sem permissão para listar a pasta do projeto: {path}",
                "hint": "Ajuste as permissões da pasta (ou do volume montado) para o usuário que executa o Gateway."}
    except OSError as exc:
        return {"available": False, "code": "path_unavailable", "docker": docker,
                "reason": f"falha ao acessar a pasta: {exc.__class__.__name__}", "hint": ""}
    ro = not os.access(p, os.W_OK)
    return {"available": True, "code": "", "reason": "", "hint": "", "docker": docker, "read_only": ro,
            "read_only_note": READ_ONLY_NOTE if ro else ""}


def ensure_project_dir(path: str) -> Path:
    """O diretório do projeto precisa ser visível PARA ESTE PROCESSO. Em Docker, pastas do host não montadas não existem."""
    a = project_availability(path)
    if not a["available"]:
        raise WorkspaceIOError(a["code"], a["reason"], a["hint"], 409)
    return Path(path).resolve()


# -- histórico leve e persistente (JSONL em <data>/workspace_index/history.jsonl; só operações APLICADAS) -------
HISTORY_MAX = 200


def history_path() -> Path:
    return data_dir() / "workspace_index" / "history.jsonl"


def record_history(entry: dict) -> None:
    """Melhor-esforço: falha de disco nunca derruba a operação. Mantém só as últimas HISTORY_MAX linhas."""
    try:
        hp = history_path()
        hp.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        try:
            lines = hp.read_text(encoding="utf-8").splitlines()
        except OSError:
            pass
        lines.append(json.dumps(entry, ensure_ascii=False))
        _atomic_write(hp, ("\n".join(lines[-HISTORY_MAX:]) + "\n").encode("utf-8"))
    except OSError:
        pass


def read_history(limit: int = 20, project_id: str | None = None) -> list[dict]:
    try:
        lines = history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if project_id and d.get("project_id") not in (project_id, None):
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def summarize_result(kind: str, res: dict | None) -> str:
    """Resumo curto e honesto (sem conteúdo) do resultado, para o histórico."""
    r = res or {}
    if kind == "initialize" and r.get("index"):
        i = r["index"]
        return f"{i.get('total_after', 0)} itens indexados · {i.get('new', 0)} novos · {i.get('changed', 0)} alterados · {i.get('removed', 0)} removidos"
    if kind == "import" and r.get("counts"):
        c = r["counts"]
        return f"{c.get('imported', 0)} importadas · {c.get('duplicate', 0)} duplicadas · {c.get('invalid', 0)} inválidas"
    if kind == "export":
        return f"{r.get('records', 0)} registros · {r.get('filename', '')}".strip(" ·")
    return ""


def memory_count(project_name: str | None) -> int | None:
    """Notas ativas do projeto na memória (None se o armazenamento não responde)."""
    pname = _note_project(project_name)
    try:
        return len(_notes(import_store(), pname, False, active_only=True)[0])
    except Exception:  # noqa: BLE001
        return None


def index_status(project_id: str) -> dict:
    """Estado REAL do índice gravado: nunca inventa números."""
    try:
        d = json.loads(index_path(project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"indexed": False, "files": 0, "secret_files": 0, "updated": None}
    files = d.get("files") if d.get("version") == INDEX_VERSION and isinstance(d.get("files"), dict) else None
    if not files:
        return {"indexed": False, "files": 0, "secret_files": 0, "updated": None}
    return {"indexed": True, "files": len(files), "secret_files": sum(1 for f in files.values() if f.get("secret")),
            "updated": d.get("updated")}


def _atomic_write(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".wsio-", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _note_project(name: str | None) -> str | None:
    n = (name or "").strip()
    if len(n) > 80:
        raise WorkspaceIOError("project_name_too_long",
                               "nome do projeto acima de 80 caracteres suportados pelo SavedContextStore",
                               "Use um nome de até 80 caracteres; o nome não será truncado para isolar notas.")
    return n or None


def import_store() -> SavedContextStore:
    """Store sobre a MESMA pasta de notas, sem o limite de 30 notas/min (a importação tem teto próprio)."""
    return SavedContextStore(saved_context_dir(), rate_per_min=0)


def _after_change() -> None:
    try:
        from app.core.state import STATE
        gw = STATE.gateway
        if gw is not None:
            from app.memory_store.index import reindex
            reindex(gw)
    except Exception:  # noqa: BLE001 - reindexação é melhor-esforço
        pass


# ===================================================================================================
# Inicialização / indexação incremental
# ===================================================================================================
def index_path(project_id: str) -> Path:
    return data_dir() / "workspace_index" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', project_id)}.json"


def purge_index(project_id: str) -> bool:
    """Apaga SÓ o índice do Workspace deste projeto (em <data>, nunca na pasta do projeto). True se existia."""
    try:
        index_path(project_id).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        log.warning("não foi possível apagar o índice de %s", project_id)
        return False


def load_index(project_id: str) -> dict:
    try:
        d = json.loads(index_path(project_id).read_text(encoding="utf-8"))
        if d.get("version") == INDEX_VERSION and isinstance(d.get("files"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"version": INDEX_VERSION, "files": {}}


def _sha256_and_secret(path: Path, limit: int) -> tuple[str | None, bool]:
    data = path.read_bytes()[:limit + 1]
    text = data.decode("utf-8", errors="replace")
    if scan_secrets(text):
        return None, True
    return hashlib.sha256(data).hexdigest(), False


def _structure_note(proj_name: str, scan: ScanResult) -> tuple[str, str]:
    langs = ", ".join(l for l, _ in scan.languages.most_common(6)) or "n/d"
    lines = [f"# Estrutura do projeto {proj_name}", "",
             "Resumo gerado pela Central de Inicialização (somente estrutura; nenhum conteúdo de arquivo).", "",
             f"- Marcadores: {', '.join(scan.markers) or 'nenhum'}",
             f"- Pastas de topo: {', '.join(sorted(scan.top_dirs)[:30]) or 'nenhuma'}",
             f"- Linguagens principais: {langs}"]
    return f"Estrutura do projeto {proj_name}", "\n".join(lines)


def _index_files(scan, old: dict, job: Job) -> tuple[dict[str, dict], dict[str, int]]:
    """Compara a varredura com o índice anterior (novo/alterado/inalterado/segredo) e calcula os hashes."""
    new_files: dict[str, dict] = {}
    counts = {"new": 0, "changed": 0, "unchanged": 0, "secret_content": 0}
    total = len(scan.files)
    job.progress(0, total, "indexação")
    for i, f in enumerate(scan.files, 1):
        job.check()
        prev = old.get(f.rel)
        if prev and prev.get("size") == f.size and prev.get("mtime_ns") == f.mtime_ns:
            new_files[f.rel] = prev
            counts["unchanged"] += 1
            if prev.get("secret"):
                counts["secret_content"] += 1
        else:
            try:
                sha, secret = _sha256_and_secret(f.path, DEFAULT_MAX_FILE_BYTES)
            except OSError as exc:
                job.add_error(f.rel, f"leitura falhou: {exc.__class__.__name__}")
                continue
            ext = os.path.splitext(f.rel)[1].lower()
            new_files[f.rel] = {"size": f.size, "mtime_ns": f.mtime_ns, "sha256": sha, "secret": secret, "ext": ext}
            counts["secret_content" if secret else ("changed" if prev else "new")] += 1
        if i % 50 == 0 or i == total:
            job.progress(i, total)
    return new_files, counts


def _summary_note(proj, scan, job: Job, apply: bool, written: list) -> dict:
    """Nota-resumo idempotente: igual => nada; diferente => nova nota que SUBSTITUI (a antiga é preservada)."""
    out: dict = {}
    title, body = _structure_note(proj.name, scan)
    store = import_store()
    pname = _note_project(proj.name)
    src = f"workspace:init:{proj.id}"
    existing = next((n for n in store.list(project=pname, tag=INIT_TAG)
                     if n.source == src and (n.status or "active") == "active"), None)
    if scan_secrets(title, body):
        out = {"action": "skipped", "reason": "possível segredo no resumo"}
    elif existing and existing.content_sha256 == content_digest(body):
        out = {"action": "unchanged", "id": existing.id}
    else:
        action = "supersede" if existing else "create"
        out = {"action": action, "supersedes": existing.id if existing else None}
        if apply:
            try:
                nid = store.save(title, body, [INIT_TAG], pname, "workspace-init", "untrusted", kind="fact",
                                 source=src, supersedes=existing.id if existing else None)
                out["id"] = nid
                written.append(f"memory:{nid}")
                _after_change()
            except SavedContextError as exc:
                job.add_error("summary_note", str(exc))
                out["error"] = str(exc)
    return out


def run_initialize(proj, job: Job, *, apply: bool, install_project_files: bool = False,
                   summary_note: bool = True, max_files: int = 20000) -> dict:
    _note_project(proj.name)
    root = ensure_project_dir(proj.path)
    job.progress(0, 0, "varredura")
    scan = scan_project(root, max_files=max_files, is_cancelled=lambda: job.cancelled,
                        on_progress=lambda n, rel: job.progress(n, None, f"varredura: {rel}"))
    job.check()
    old = load_index(proj.id)["files"]
    total = len(scan.files)
    new_files, counts = _index_files(scan, old, job)
    removed = sorted(set(old) - set(new_files))
    result: dict = {
        "project": {"id": proj.id, "name": proj.name, "path": str(root)}, "dry_run": not apply,
        "structure": {"markers": scan.markers, "top_dirs": sorted(scan.top_dirs)[:50],
                      "languages": dict(scan.languages.most_common(12)), "eligible_files": total,
                      "truncated": scan.truncated},
        "skipped": dict(scan.skipped), "skipped_examples": scan.skipped_examples,
        "index": {**counts, "removed": len(removed), "total_after": len(new_files),
                  "changes": counts["new"] + counts["changed"] + len(removed)},
        "project_files": None, "summary_note": None, "written": [],
        "read_only": not os.access(root, os.W_OK), "warnings": [],
    }
    if result["read_only"]:
        result["warnings"].append(READ_ONLY_NOTE)
    job.check()
    # -- arquivos de ligação no projeto (opt-in; só cria os ausentes, nunca sobrescreve) ----------------
    if install_project_files and not os.access(root, os.W_OK):
        result["project_files"] = {"error": "read_only_root", "message": "raiz do projeto somente leitura",
                                   "hint": READ_ONLY_NOTE}
        job.add_error("project_files", "read_only_root: " + READ_ONLY_NOTE)
    elif install_project_files:
        from app.terminals import project_initializer as pi
        try:
            rep = pi.initialize(proj.path, proj.name, dry_run=not apply)
            result["project_files"] = rep.to_dict()
        except pi.InitError as exc:
            job.add_error("project_files", f"{exc.code}: {exc.message}")
            result["project_files"] = {"error": exc.code, "message": exc.message, "hint": exc.hint}
    if summary_note:
        result["summary_note"] = _summary_note(proj, scan, job, apply, result["written"])
    job.check()
    if apply:
        payload = {"version": INDEX_VERSION, "project_id": proj.id, "root": str(root), "updated": time.time(),
                   "files": new_files}
        _atomic_write(index_path(proj.id), json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        result["written"].append(f"index:{index_path(proj.id).name}")
    job.progress(total, total, "concluído")
    return result


# ===================================================================================================
# Importação (Markdown / JSON estruturados -> notas)
# ===================================================================================================
_FM = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.S)


def _parse_tags(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    s = str(raw or "").strip().strip("[]")
    return [t.strip().strip("\"'") for t in s.split(",") if t.strip().strip("\"'")]


def parse_markdown(name: str, text: str) -> dict:
    meta: dict = {}
    body = text.lstrip("\ufeff")
    m = _FM.match(body)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "-")):
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip("\"'")
        body = body[m.end():]
    body = body.strip()
    title = meta.get("title")
    if not title:
        h = re.match(r"#\s+(.+)", body)
        title = h.group(1).strip() if h else Path(name).stem
    return {"title": title[:200], "content": body, "tags": _parse_tags(meta.get("tags")), "project": meta.get("project"),
            "kind": meta.get("kind"), "source": meta.get("source")}


def parse_json_notes(name: str, text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise WorkspaceIOError("invalid_json", f"{name}: JSON inválido ({exc.msg})") from exc
    if isinstance(data, dict):
        for key in ("notes", "memories", "memorias", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise WorkspaceIOError("invalid_json", f"{name}: esperado uma lista de notas ou {{\"notes\": [...]}}")
    out = []
    for d in data:
        if not isinstance(d, dict):
            out.append({"title": "", "content": "", "_invalid": "item não é objeto"})
            continue
        invalid = next((f"{field}: esperado texto ou null" for field in
                        ("title", "content", "project", "kind", "source", "source_agent")
                        if d.get(field) is not None and not isinstance(d[field], str)), None)
        tags = d.get("tags")
        if tags is not None and not (isinstance(tags, str) or
                isinstance(tags, list) and all(isinstance(t, str) for t in tags)):
            invalid = invalid or "tags: esperado texto ou lista de textos"
        if invalid:
            out.append({"title": "", "content": "", "_invalid": invalid})
            continue
        out.append({"title": (d.get("title") or "").strip()[:200], "content": d.get("content") or "",
                    "tags": _parse_tags(tags), "project": d.get("project"),
                    "kind": d.get("kind"), "source": d.get("source")})
    return out


def gather_import_items(items: list[dict]) -> list[tuple[str, str]]:
    """[(nome, texto)] a partir de itens enviados {name, content}."""
    if len(items) > MAX_IMPORT_ITEMS:
        raise WorkspaceIOError("too_many_items", f"no máximo {MAX_IMPORT_ITEMS} arquivos por importação")
    out, total = [], 0
    for it in items:
        name = os.path.basename(str(it.get("name") or "arquivo"))
        text = str(it.get("content") or "")
        total += len(text.encode("utf-8"))
        if total > MAX_IMPORT_BYTES:
            raise WorkspaceIOError("too_large", f"importação acima de {MAX_IMPORT_BYTES // (1024 * 1024)} MB")
        out.append((name, text))
    return out


def _read_import_file(path: Path, root: Path, scan: ScanResult) -> str | None:
    """Bounded read with fresh ancestor/reparse checks; not an atomic TOCTOU boundary."""
    import stat
    from app.workspace_io.scanner import _safe_path

    try:
        for parent in (path, *path.parents):
            if not _safe_path(parent, root, str(parent.relative_to(root)), scan):
                return None
            if parent == root:
                break
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        limit = min(MAX_IMPORT_FILE_BYTES, DEFAULT_MAX_FILE_BYTES)
        with path.open("rb") as fh:
            raw = fh.read(limit + 1)
        if len(raw) > limit or b"\x00" in raw:
            return None
        return raw.decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None




def _fs_folds_case(root: Path) -> bool:
    """Detect a case-insensitive filesystem (macOS default); Windows is handled by normcase."""
    if os.name != "posix":
        return False
    try:
        for child in list(root.iterdir())[:50]:
            variant = child.with_name(child.name[:1].swapcase() + child.name[1:])
            if variant != child and variant.exists():
                return True
    except OSError:
        return False
    return False

def gather_import_path(root: Path, rel: str, job: Job) -> list[tuple[str, str]]:
    """Select imports under the ORIGINAL root policy, including explicit files."""
    from app.terminals.projects import PathEscapeError, safe_join
    try:
        target = safe_join(root, rel or "")
    except PathEscapeError as exc:
        raise WorkspaceIOError("path_escape", "caminho fora do projeto", status=403) from exc
    if not (target.is_file() or target.is_dir()):
        raise WorkspaceIOError("not_found", f"caminho não encontrado no projeto: {rel or '.'}", status=404)
    # Keep lexical selection: resolve() would erase an in-root link/junction alias.
    selected = os.path.normcase(Path((rel or ".").replace("\\", "/")).as_posix())
    if rel in ("/", "\\"):
        selected = "."
    folds = _fs_folds_case(Path(root))
    selected_lower = selected.lower()

    def include(name: str) -> bool:
        if not name.lower().endswith(IMPORT_EXT):
            return False
        matched = os.path.normcase(name)
        if selected == "." or matched == selected or matched.startswith(selected + os.sep):
            return True
        # Case-insensitive filesystems (macOS default, Windows shares) must still match.
        return folds and (matched.lower() == selected_lower
                          or matched.lower().startswith(selected_lower + os.sep.lower()))
    scan = scan_project(root, max_files=MAX_IMPORT_ITEMS * 20,
                        max_file_bytes=min(MAX_IMPORT_FILE_BYTES, DEFAULT_MAX_FILE_BYTES),
                        is_cancelled=lambda: job.cancelled, include_file=include)
    job.check()
    if scan.truncated:
        raise WorkspaceIOError("scan_limit", "varredura acima do limite de arquivos; importação não realizada")
    if len(scan.files) > MAX_IMPORT_ITEMS:
        raise WorkspaceIOError("too_many_items", f"{len(scan.files)} arquivos; máximo {MAX_IMPORT_ITEMS} por importação")
    out, total = [], 0
    for f in scan.files:
        job.check()
        text = _read_import_file(f.path, Path(root).resolve(), scan)
        if text is None:
            continue
        total += len(text.encode("utf-8"))
        if total > MAX_IMPORT_BYTES:
            raise WorkspaceIOError("too_large", "importação acima do limite total")
        out.append((f.rel, text))
    return out


def run_import(files: list[tuple[str, str]], job: Job, *, apply: bool, project_name: str | None) -> dict:
    store = import_store()
    pname = _note_project(project_name)
    existing = {(n.project, n.title.strip().lower(), content_digest(n.content)) for n in store.list()}
    cands: list[dict] = []
    job.progress(0, len(files), "leitura")
    for name, text in files:
        job.check()
        low = name.lower()
        try:
            if low.endswith(".json"):
                parsed = parse_json_notes(name, text)
            elif low.endswith((".md", ".markdown")):
                parsed = [parse_markdown(name, text)]
            else:
                cands.append({"file": name, "title": name, "status": "invalido", "reason": "formato não suportado (use .md ou .json)"})
                continue
        except WorkspaceIOError as exc:
            cands.append({"file": name, "title": name, "status": "invalido", "reason": exc.message})
            continue
        for p in parsed:
            cands.append({"file": name, **p})
    seen: set[tuple[str | None, str, str]] = set()
    counts = {"to_import": 0, "duplicate": 0, "invalid": 0, "imported": 0}
    rows: list[dict] = []
    job.progress(0, len(cands), "validação")
    for c in cands:
        job.check()
        row = {"file": c["file"], "title": c.get("title", ""), "status": c.get("status", "pendente"), "reason": c.get("reason", "")}
        if row["status"] != "invalido":
            title, content = (c.get("title") or "").strip(), c.get("content") or ""
            try:
                if c.get("_invalid"):
                    raise InvalidNote(c["_invalid"])
                origin_project = (c.get("project") or "").strip() or None
                if pname is not None and origin_project is not None and origin_project != pname:
                    raise InvalidNote("projeto da nota diverge do projeto de destino selecionado; nota rejeitada")
                proj = pname or _note_project(origin_project)
                if content.startswith("[REDATADO"):
                    raise InvalidNote("conteúdo redatado na exportação; nada a importar")
                store._validate(title, content, c.get("tags") or [], proj, None, c.get("source") or f"import:{c['file']}"[:300])
                store._v2_fields(c.get("kind"), None, None, None, None, None)
                key = (proj, title.lower(), content_digest(content))
                if key in existing or key in seen:
                    row["status"], row["reason"] = "duplicado", "já existe uma nota com o mesmo título e conteúdo"
                    counts["duplicate"] += 1
                else:
                    seen.add(key)
                    row["status"] = "importar"
                    counts["to_import"] += 1
                    c["_proj"] = proj
            except SavedContextError as exc:
                row["status"], row["reason"] = "invalido", str(exc)
                counts["invalid"] += 1
        else:
            counts["invalid"] += 1
        c["_row"] = row
        rows.append(row)
    if apply:
        todo = [c for c in cands if c["_row"]["status"] == "importar"]
        job.progress(0, len(todo), "gravando")
        for i, c in enumerate(todo, 1):
            job.check()
            row = c["_row"]
            try:
                kind = (c.get("kind") or "").strip().lower() or None
                nid = store.save(c["title"].strip(), c["content"], c.get("tags") or [], c.get("_proj"), "import", "untrusted",
                                 kind=kind, source=(c.get("source") or f"import:{c['file']}")[:300])
                row["status"], row["id"] = "importado", nid
                counts["imported"] += 1
                counts["to_import"] -= 1
            except SavedContextError as exc:
                row["status"], row["reason"] = "erro", str(exc)
                job.add_error(c["file"], str(exc))
            job.progress(i)
        if counts["imported"]:
            _after_change()
    return {"dry_run": not apply, "counts": counts, "files": len(files), "items": rows[:500],
            "truncated_items": len(rows) > 500}


# ===================================================================================================
# Exportação (memórias, contexto, índice, metadados, relatório, métricas) -> JSON / Markdown / CSV
# ===================================================================================================
EXPORT_KINDS = ("memories", "context", "metadata", "index", "report", "metrics")
EXPORT_FORMATS = ("json", "md", "csv")
_MEDIA = {"json": "application/json", "md": "text/markdown; charset=utf-8", "csv": "text/csv; charset=utf-8"}


def _csv_cell(v):
    if isinstance(v, (list, tuple, dict)):
        v = json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    s = str(v)
    return "\t" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s   # neutraliza injeção de fórmula


def to_csv(rows: list[dict]) -> str:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([_csv_cell(r.get(c)) for c in cols])
    return buf.getvalue()


def _redact_export(value: Any) -> Any:
    """Best-effort secret screening of every textual leaf, including mapping keys."""
    if isinstance(value, str):
        return "[REDATADO]" if scan_secrets(value) else value
    if isinstance(value, dict):
        return {_redact_export(k): _redact_export(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_export(v) for v in value]
    return value


def _safe_note(n, with_content: bool) -> tuple[dict, bool]:
    d = {"id": n.id, "title": n.title, "project": n.project, "tags": n.tags, "kind": n.kind, "status": n.status,
         "created": n.created, "updated": n.updated, "source": n.source, "source_agent": n.source_agent,
         "confidence": n.confidence, "expired": n.is_expired(), "content": n.content}
    safe = _redact_export(d)
    redacted = safe != d
    if with_content:
        if redacted:
            safe["content"] = "[REDATADO: possível segredo]"
    else:
        safe.pop("content")
    return safe, redacted


def _notes(store: SavedContextStore, project: str | None, with_content: bool, active_only: bool = False):
    rows, red = [], 0
    for n in store.list(project=project):
        if active_only and ((n.status or "active") != "active" or n.is_expired()):
            continue
        d, r = _safe_note(n, with_content)
        rows.append(d)
        red += int(r)
    return rows, red


def _md_notes(title: str, rows: list[dict], meta: dict) -> str:
    out = [f"# {title}", "", *(f"- **{k}**: {v}" for k, v in meta.items()), ""]
    for r in rows:
        out += [f"## {r['title']}", "",
                f"`{r['id']}` · {r.get('kind') or 'sem tipo'} · {r.get('project') or 'sem projeto'} · tags: {', '.join(r.get('tags') or []) or '—'}", "",
                r.get("content", ""), ""]
    return "\n".join(out)


def _flatten(d, prefix="") -> list[dict]:
    rows = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            rows += _flatten(v, key + ".")
        else:
            rows.append({"metric": key, "value": v})
    return rows


def _metrics(project_name: str | None) -> tuple[dict, list[dict]]:
    from app.core.state import STATE
    from app.services import costs as svc
    try:
        db = STATE.require_gateway().db
    except Exception as exc:  # noqa: BLE001
        raise WorkspaceIOError("metrics_unavailable", "banco de métricas indisponível neste processo", str(exc), 503) from exc
    now = time.time()
    rows = db.cost_rows(since=None, project=project_name)
    summary = svc.summarize(rows, "all", db.get_budgets(), svc.spend_of(db.cost_rows(since=svc.range_since("today", now), project=project_name)),
                            svc.spend_of(db.cost_rows(since=svc.range_since("30d", now), project=project_name)))
    calls = [svc.csv_row(svc.call_view(r, True), True) for r in rows[:5000]]  # só métricas: sem consulta/prompt
    return summary, calls


def _project_report(store: SavedContextStore, project_name: str) -> dict:
    """Aggregate only the selected notes; global trash has no reliable project attribution."""
    from collections import Counter
    from app.memory_store.lifecycle import DUPLICATE_THRESHOLD
    from app.services.near_dup import similarity

    notes = [n for n in store.list() if n.project == project_name]
    active = [n for n in notes if (n.status or "active") == "active"]
    duplicates = sum(any(similarity(a.content, b.content) >= DUPLICATE_THRESHOLD for b in active[:i])
                     for i, a in enumerate(active))
    audit = {"total": len(notes), "active": len(active),
             "by_kind": dict(Counter(n.kind or "(v1)" for n in notes)),
             "by_status": dict(Counter(n.status or "(v1)" for n in notes)),
             "schema_v1": sum(n.schema < 2 for n in notes), "schema_v2": sum(n.schema >= 2 for n in notes),
             "expired": sum(n.is_expired() for n in notes),
             "stale_flagged": sum(bool(n.feedback_stale) for n in notes),
             "wrong_flagged": sum(bool(n.feedback_wrong) for n in notes),
             "duplicates": duplicates, "duplicate_rate": round(duplicates / len(active), 4) if active else 0.0,
             "integrity_failures": [n.id for n in notes if n.integrity_ok() is False], "trash": None}
    useful = [{"id": n.id, "title": n.title, "useful": n.feedback_useful, "wrong": n.feedback_wrong,
               "stale": n.feedback_stale, "net": n.feedback_useful - n.feedback_wrong - n.feedback_stale}
              for n in notes if n.feedback_useful or n.feedback_wrong or n.feedback_stale]
    useful.sort(key=lambda r: (-r["net"], r["id"]))
    return {"audit": audit, "usefulness_top": useful[:20]}


def run_export(kind: str, fmt: str, job: Job, *, apply: bool, project=None, scope: str = "project") -> dict:
    if kind not in EXPORT_KINDS:
        raise WorkspaceIOError("invalid_kind", f"tipo inválido: {kind} (use {', '.join(EXPORT_KINDS)})")
    if fmt not in EXPORT_FORMATS:
        raise WorkspaceIOError("invalid_format", f"formato inválido: {fmt} (use json, md ou csv)")
    if scope not in ("project", "all"):
        raise WorkspaceIOError("invalid_scope", "escopo inválido: use project ou all explicitamente")
    if scope == "project" and (project is None or not isinstance(project.name, str) or not project.name.strip()):
        raise WorkspaceIOError("project_required", "selecione um projeto para exportar este escopo")
    pname = _note_project(project.name) if scope == "project" else None
    store = import_store()
    job.progress(0, 1, "coletando")
    redacted = 0
    meta = _redact_export({"kind": kind, "format": fmt, "scope": pname or "todos os projetos",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "secrets": "excluídos (padrão): conteúdo com possível segredo é redatado; .env/chaves nunca entram"})
    if kind in ("memories", "context", "metadata"):
        rows, redacted = _notes(store, pname, with_content=kind != "metadata", active_only=kind == "context")
        job.check()
        data: object = rows
        text_md = _md_notes({"memories": "Memórias", "context": "Contexto do projeto", "metadata": "Metadados das memórias"}[kind], rows, meta) \
            if kind != "metadata" else "\n".join([f"# Metadados das memórias", ""] + [f"- `{r['id']}` {r['title']} ({r.get('kind') or '—'}, {r.get('status') or '—'})" for r in rows])
        csv_rows = rows
    elif kind == "index":
        if project is None:
            raise WorkspaceIOError("project_required", "o índice é por projeto: selecione um projeto")
        idx = load_index(project.id)
        if not idx["files"]:
            raise WorkspaceIOError("no_index", "projeto ainda sem índice", "rode Inicializar projeto antes de exportar o índice", 409)
        rows = [{"path": p, "size": e["size"], "sha256": e.get("sha256"), "ext": e.get("ext"), "excluded": "segredo no conteúdo" if e.get("secret") else ""}
                for p, e in sorted(idx["files"].items())]
        rows = _redact_export(rows)
        data, csv_rows = rows, rows
        text_md = "\n".join([f"# Índice de arquivos — {_redact_export(project.name)}", "", f"{len(rows)} arquivos", ""] + [f"- `{r['path']}` ({r['size']} B)" for r in rows])
    elif kind == "report":
        from app.memory_store import lifecycle
        report = (_project_report(store, pname) if pname is not None else
                  {"audit": lifecycle.audit(store), "usefulness_top": lifecycle.usefulness(store)[:20]})
        if project is not None and scope == "project":
            idx = load_index(project.id)
            report["project_index"] = {"files": len(idx["files"]), "initialized": bool(idx["files"])}
        report = _redact_export(report)
        data, csv_rows = report, _flatten({"audit": report["audit"], **({"project_index": report["project_index"]} if "project_index" in report else {})})
        text_md = "\n".join([f"# Relatório de memória", "", *(f"- {k}: {v}" for k, v in meta.items()), "", "## Auditoria", "",
                             *(f"- {r['metric']}: {r['value']}" for r in _flatten(report["audit"])), ""])
    else:  # metrics
        summary, calls = _metrics(pname)
        summary, calls = _redact_export(summary), _redact_export(calls)
        data, csv_rows = {"summary": summary, "calls": calls}, calls
        text_md = "\n".join([f"# Métricas", "", f"{len(calls)} chamadas (apenas métricas; sem consultas)", "",
                             "```json", json.dumps(summary, ensure_ascii=False, indent=2, default=str), "```"])
    count = len(data) if isinstance(data, list) else len(csv_rows)
    result = {"dry_run": not apply, "kind": kind, "format": fmt, "scope": meta["scope"], "records": count,
              "redacted_records": redacted, "secrets_included": False}
    if not apply:
        return result
    job.progress(0, 1, "gerando arquivo")
    if fmt == "json":
        body = json.dumps({"meta": meta, "data": data}, ensure_ascii=False, indent=2, default=str)
    elif fmt == "md":
        body = text_md
    else:
        body = to_csv(csv_rows)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"anamnesia-{kind}-{slugify(_redact_export(pname or 'todos'), 30)}-{stamp}.{fmt}"
    job.artifact = {"filename": fname, "media_type": _MEDIA[fmt], "data": body.encode("utf-8-sig" if fmt == "csv" else "utf-8")}
    result.update({"filename": fname, "bytes": len(job.artifact["data"])})
    job.progress(1, 1, "concluído")
    return result
