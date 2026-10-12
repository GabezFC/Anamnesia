"""ANA-044 / 045 / 047 / 049 / 051: small hardening helpers (logs, path redaction, provider URLs, PTY
resource limits, race-free file open). Each has an env rollback; defaults are safe-but-compatible.

  MG_LOG_REDACT=0            disable access-log query redaction (ANA-044)
  MG_REDACT_PATHS=always|lan|off   default `lan`: absolute paths hidden for non-loopback clients (ANA-045)
  MG_PROVIDER_URL_GUARD=enforce|warn|off  default `enforce` (ANA-047); MG_ALLOW_REMOTE_PROVIDERS=1 opts in
  MG_PTY_LIMITS=on|off, MG_PTY_AGENT_IDLE_SECONDS (ANA-049)
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger("anamnesia.security")


# ---- ANA-044 -----------------------------------------------------------------------------------
_ABS_WIN = re.compile(r"(?i)\b[a-z]:[\\/][^\s'\"<>|]+")
_ABS_POSIX = re.compile(r"(?<![\w.])/(?:home|Users|root|mnt|var|etc|opt)/[^\s'\"<>|]+")


def scrub_text(text: str) -> str:
    return _ABS_POSIX.sub("<path>", _ABS_WIN.sub("<path>", text))


class AccessLogRedactor(logging.Filter):
    """uvicorn.access logs `GET /memory/search?q=... HTTP/1.1`: drop the query string and any path."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            a = list(args)
            a[2] = a[2].split("?", 1)[0]
            record.args = tuple(a)
        elif isinstance(record.msg, str) and "?" in record.msg:
            record.msg = re.sub(r"\?[^\s\"]*", "?<redacted>", record.msg)
        return True


class PathScrubFilter(logging.Filter):
    """INFO-and-below records never carry absolute filesystem paths."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno <= logging.INFO:
            try:
                msg = record.getMessage()
            except Exception:  # noqa: BLE001
                return True
            scrubbed = scrub_text(msg)
            if scrubbed != msg:
                record.msg, record.args = scrubbed, None
        return True


def install_log_redaction() -> None:
    if os.environ.get("MG_LOG_REDACT", "1").strip().lower() in {"0", "false", "off", "no"}:
        return
    for name in ("uvicorn.access",):
        lg = logging.getLogger(name)
        if not any(isinstance(f, AccessLogRedactor) for f in lg.filters):
            lg.addFilter(AccessLogRedactor())
    lg = logging.getLogger("anamnesia")
    if not any(isinstance(f, PathScrubFilter) for f in lg.filters):
        lg.addFilter(PathScrubFilter())


# ---- ANA-045 -----------------------------------------------------------------------------------
def redact_path(p: str | os.PathLike, root: str | os.PathLike | None = None) -> str:
    """vault-relative when under `root`, otherwise just the final component. Never an absolute path."""
    s = str(p)
    if root:
        try:
            return Path(s).resolve().relative_to(Path(root).resolve()).as_posix() or "."
        except (ValueError, OSError):
            pass
    return Path(s).name or "."


def should_redact_paths(client_is_local: bool) -> bool:
    m = os.environ.get("MG_REDACT_PATHS", "lan").strip().lower()
    return m == "always" or (m == "lan" and not client_is_local)


def redact_info(info: dict, vault_root: str | None) -> dict:
    out = dict(info)
    for k in ("vault", "graph_path", "db", "vault_path"):
        if isinstance(out.get(k), str):
            out[k] = redact_path(out[k], vault_root) if k != "db" else Path(out[k]).name
    if isinstance(out.get("settings"), dict):
        out["settings"] = redact_info(out["settings"], vault_root)
    return out


# ---- ANA-047 -----------------------------------------------------------------------------------
class ProviderURLError(ValueError):
    pass


_META_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


def _mode() -> str:
    m = os.environ.get("MG_PROVIDER_URL_GUARD", "enforce").strip().lower()
    return m if m in {"enforce", "warn", "off"} else "enforce"


def validate_provider_url(url: str, name: str = "BASE_URL") -> str:
    """http/https only; cloud-metadata endpoints always refused; non-loopback hosts need
    MG_ALLOW_REMOTE_PROVIDERS=1. Returns the URL (empty string passes: provider simply unconfigured)."""
    if not url:
        return url
    mode = _mode()
    if mode == "off":
        return url
    problem = None
    try:
        u = urlsplit(url.strip())
        host = (u.hostname or "").lower()
    except ValueError:
        u, host = None, ""
    if u is None or u.scheme not in {"http", "https"} or not host:
        problem = "esquema deve ser http/https com host"
    elif host in _META_HOSTS:
        problem = "endpoint de metadata de nuvem bloqueado"
    else:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (ip.is_link_local or str(ip) in {"169.254.169.254", "fd00:ec2::254"}):
            problem = "endpoint de metadata/link-local bloqueado"
        elif host not in {"localhost", "127.0.0.1", "::1"} and not (ip and ip.is_loopback):
            if os.environ.get("MG_ALLOW_REMOTE_PROVIDERS", "").strip().lower() not in {"1", "true", "yes", "on"}:
                problem = "host nao-loopback exige MG_ALLOW_REMOTE_PROVIDERS=1"
    if problem:
        log.warning("provider url %s rejeitada (%s)", name, problem)
        if mode == "enforce":
            raise ProviderURLError(f"{name}: {problem}")
    return url


_seen_urls: dict[str, str] = {}


def note_url_change(name: str, url: str) -> bool:
    """Warn once when a provider URL changes during the process lifetime. True if it changed."""
    old = _seen_urls.get(name)
    _seen_urls[name] = url
    if old is not None and old != url:
        log.warning("provider url %s alterada em runtime", name)
        return True
    return False


# ---- ANA-049 -----------------------------------------------------------------------------------
AGENT_IDLE_SECONDS = 2 * 3600  # agents (non-shell) without a client: 2 h instead of 12 h


def agent_idle_seconds(default: float) -> float:
    try:
        v = float(os.environ.get("MG_PTY_AGENT_IDLE_SECONDS", ""))
        return v if v > 0 else min(default, AGENT_IDLE_SECONDS)
    except ValueError:
        return min(default, AGENT_IDLE_SECONDS)


def job_limits() -> tuple[int, int] | None:
    """(memory_mb, max_processes) for the PTY Job Object, or None when MG_PTY_LIMITS=off.
    Defaults are generous (4 GiB, 256 processes): they contain a fork bomb / runaway agent, not normal builds."""
    if os.environ.get("MG_PTY_LIMITS", "on").strip().lower() in {"0", "off", "false", "no"}:
        return None

    def _i(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, "")))
        except ValueError:
            return default
    return _i("MG_PTY_MEM_MB", 4096), _i("MG_PTY_MAX_PROCS", 256)


# ---- ANA-051 -----------------------------------------------------------------------------------
def open_confined(path: str | os.PathLike, root: str | os.PathLike, mode: str = "rb"):
    """Open `path` and verify, on the OPEN HANDLE, that it still lives under `root` (closes the window
    between resolve() and open()). POSIX: O_NOFOLLOW + /proc|fstat path check; Windows: compare
    GetFinalPathNameByHandle after opening. Raises PermissionError when the opened file escapes."""
    root_r = Path(root).resolve()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    try:
        final = _final_path(fd)
        if final is not None:
            fp = Path(final).resolve()
            if fp != root_r and root_r not in fp.parents:
                raise PermissionError("caminho resolvido fora da raiz (TOCTOU)")
        else:  # no handle->path API: fall back to a post-open re-resolve
            fp = Path(path).resolve()
            if fp != root_r and root_r not in fp.parents:
                raise PermissionError("caminho resolvido fora da raiz")
        return os.fdopen(fd, mode)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _final_path(fd: int) -> str | None:
    if os.name == "nt":
        try:
            import ctypes
            import msvcrt
            from ctypes import wintypes
            h = msvcrt.get_osfhandle(fd)
            f = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
            f.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            buf = ctypes.create_unicode_buffer(32768)
            n = f(h, buf, 32768, 0)
            if n:
                s = buf.value
                return s[4:] if s.startswith("\\\\?\\") else s
        except Exception:  # noqa: BLE001
            return None
        return None
    for cand in (f"/proc/self/fd/{fd}", ):
        try:
            return os.readlink(cand)
        except OSError:
            pass
    return None
