"""Download resumivel e seguro de pesos (ANAM-035). Nunca roda sozinho: exige ``confirm=True`` e um limite declarado.

Garantias: host em allow-list (default ``huggingface.co`` + subdominios; redirects revalidados a cada salto), somente
https, caminho de destino confinado a ``dest_dir`` (anti path-traversal), checagem de espaco livre, escrita em
``<nome>.part`` com resume por ``Range``, e ``os.replace`` para o nome final SO apos tamanho E sha256 conferirem.
Em pytest, sem ``opener`` injetado, a rede real e recusada.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from typing import Callable, Iterator, Optional
from urllib.parse import quote, urljoin, urlsplit

from app.services.offline import ensure_online

DEFAULT_ALLOW_HOSTS = ("huggingface.co",)
ALLOW_ENV = "MG_LOCAL_AI_DL_HOSTS"      # extensao opcional, separada por virgula (ex.: CDN de redirect)
MIN_FREE_MARGIN = 256 * 1024 * 1024
CHUNK = 1024 * 1024
MAX_REDIRECTS = 5


class DownloadError(Exception):
    def __init__(self, code: str, msg: str = ""):
        super().__init__(f"{code}: {msg}" if msg else code)
        self.code = code


@dataclass
class Resp:
    status: int
    headers: dict                      # chaves em minusculas
    chunks: Iterator[bytes]
    close: Callable[[], None] = lambda: None


Opener = Callable[[str, dict], Resp]


def allowed_hosts(extra: Optional[tuple] = None) -> tuple:
    env = tuple(h.strip().lower() for h in os.environ.get(ALLOW_ENV, "").split(",") if h.strip())
    return tuple(DEFAULT_ALLOW_HOSTS) + env + tuple(extra or ())


def check_url(url: str, hosts: tuple) -> str:
    p = urlsplit(url)
    if p.scheme != "https":
        raise DownloadError("bad_scheme", "somente https")
    if p.username or p.password:
        raise DownloadError("bad_url", "credenciais na URL")
    host = (p.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in hosts):
        raise DownloadError("host_not_allowed", host)
    return host


def hf_resolve_url(repo: str, revision_sha: str, filename: str) -> str:
    """URL ``https://huggingface.co/<repo>/resolve/<sha>/<file>`` com revisao FIXA (40 hex)."""
    if not (len(revision_sha) == 40 and all(c in "0123456789abcdef" for c in revision_sha)):
        raise DownloadError("bad_revision", "exige SHA-1 de 40 hex (nada de 'main')")
    if repo.count("/") != 1 or ".." in repo or repo.startswith("/"):
        raise DownloadError("bad_repo", repo)
    safe_join("/x", filename)  # valida o nome relativo
    return f"https://huggingface.co/{quote(repo, safe='/')}/resolve/{revision_sha}/{quote(filename, safe='/')}"


def safe_join(dest_dir: str, rel: str) -> str:
    """Junta ``rel`` a ``dest_dir`` recusando absoluto, ``..``, drive, backslash, NUL e escape por symlink."""
    if not rel or "\0" in rel or "\\" in rel or rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
        raise DownloadError("bad_path", repr(rel))
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise DownloadError("bad_path", repr(rel))
    root = os.path.realpath(dest_dir)
    target = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, target]) != root or target == root:
        raise DownloadError("bad_path", "escapa do destino")
    return target


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def _default_opener(url: str, headers: dict) -> Resp:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise DownloadError("network_in_tests", "injete opener fake")
    import httpx
    client = httpx.Client(timeout=60, follow_redirects=False)
    cm = client.stream("GET", url, headers=headers)
    r = cm.__enter__()

    def close():
        cm.__exit__(None, None, None)
        client.close()
    return Resp(r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.iter_bytes(CHUNK), close)


def _validate_args(confirm, max_bytes, expected_size, expected_sha256) -> str:
    """Fail-closed argument checks; returns the normalized (lowercase) expected sha256."""
    if confirm is not True:
        raise DownloadError("not_confirmed", "passe confirm=True explicitamente")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise DownloadError("no_limit", "declare max_bytes > 0")
    if not isinstance(expected_size, int) or expected_size <= 0 or expected_size > max_bytes:
        raise DownloadError("size_over_limit", f"expected_size={expected_size} max_bytes={max_bytes}")
    sha = (expected_sha256 or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise DownloadError("bad_sha256", "sha256 esperado obrigatorio (64 hex)")
    return sha


def download_file(url: str, dest_dir: str, rel_name: str, *, expected_sha256: str, expected_size: int,
                  max_bytes: Optional[int] = None, confirm: bool = False, opener: Optional[Opener] = None,
                  free_space: Optional[Callable[[str], int]] = None, hosts: Optional[tuple] = None,
                  min_free_margin: int = MIN_FREE_MARGIN, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    sha = _validate_args(confirm, max_bytes, expected_size, expected_sha256)
    allow = allowed_hosts(hosts)
    check_url(url, allow)
    ensure_online("local_ai.download", url)
    final = safe_join(dest_dir, rel_name)
    part = final + ".part"
    os.makedirs(os.path.dirname(final), exist_ok=True)

    if os.path.isfile(final) and os.path.getsize(final) == expected_size and sha256_file(final) == sha:
        return {"ok": True, "path": final, "skipped": True, "bytes": expected_size}

    have = os.path.getsize(part) if os.path.isfile(part) else 0
    if have > expected_size:
        os.remove(part)
        have = 0
    free = (free_space or (lambda p: shutil.disk_usage(p).free))(os.path.dirname(final))
    need = expected_size - have + min_free_margin
    if free < need:
        raise DownloadError("no_space", f"livre={free} necessario={need}")

    opener = opener or _default_opener
    resumed_from = have
    if have < expected_size:
        cur = url
        for _ in range(MAX_REDIRECTS + 1):
            resp = opener(cur, {"Range": f"bytes={have}-"} if have else {})
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                resp.close()
                if not loc:
                    raise DownloadError("bad_redirect")
                cur = urljoin(cur, loc)
                check_url(cur, allow)
                continue
            break
        else:
            raise DownloadError("too_many_redirects")
        try:
            if resp.status == 206:
                cr = resp.headers.get("content-range", "")
                if not cr.startswith(f"bytes {have}-"):
                    raise DownloadError("bad_range", cr)
                mode = "ab"
            elif resp.status == 200:
                have, mode = 0, "wb"      # servidor ignorou Range: recomeca
                resumed_from = 0
            else:
                raise DownloadError("http_status", str(resp.status))
            with open(part, mode) as f:
                for chunk in resp.chunks:
                    have += len(chunk)
                    if have > expected_size or have > max_bytes:
                        f.close()
                        os.remove(part)
                        raise DownloadError("size_over_limit", "fluxo excedeu o tamanho esperado")
                    f.write(chunk)
                    if progress:
                        progress(have, expected_size)
        finally:
            resp.close()

    size = os.path.getsize(part)
    if size != expected_size:
        raise DownloadError("size_mismatch", f"{size} != {expected_size} (.part mantido para resume)")
    if sha256_file(part) != sha:
        os.remove(part)
        raise DownloadError("sha256_mismatch", ".part descartado")
    os.replace(part, final)
    return {"ok": True, "path": final, "skipped": False, "bytes": size, "resumed_from": resumed_from}
