"""Test-infrastructure helpers used by tests/conftest.py (kept importable so they are unit-tested).

ANA-084 tree fingerprint, ANA-105 network block, ANA-127 auto markers, ANA-129 deterministic shuffle.
Nothing here imports product code.
"""
from __future__ import annotations

import ipaddress
import os
import random
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# ----------------------------------------------------------------------------------------------
# ANA-084: the suite must not alter the working tree (real DBs, local token, local settings, data/).
# ----------------------------------------------------------------------------------------------
WATCHED = ("benchmark.db", "anamnesia.db", ".env", "config/local_settings.json", "data", "logs")
_SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def fingerprint(root: Path, rels: tuple[str, ...] = WATCHED) -> dict[str, tuple[int, int] | None]:
    """{relative file path: (size, mtime_ns)}; a watched path that does not exist maps to None."""
    out: dict[str, tuple[int, int] | None] = {}
    for rel in rels:
        p = root / rel
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not (_SKIP_PARTS & set(f.relative_to(root).parts)):
                    st = f.stat()
                    out[f.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
        elif p.is_file():
            st = p.stat()
            out[rel] = (st.st_size, st.st_mtime_ns)
        else:
            out[rel] = None
    return out


def diff_fingerprints(before: dict, after: dict) -> list[str]:
    """Human-readable list of created / deleted / modified paths."""
    changes = []
    for k in sorted(set(before) | set(after)):
        b, a = before.get(k), after.get(k)
        if b == a:
            continue
        if b is None and a is not None:
            changes.append(f"created: {k}")
        elif a is None and b is not None:
            changes.append(f"deleted: {k}")
        else:
            changes.append(f"modified: {k}")
    return changes


# ----------------------------------------------------------------------------------------------
# ANA-105: block outbound non-loopback sockets (offline proof). Opt-in via --block-network.
# ----------------------------------------------------------------------------------------------
class NetworkBlocked(RuntimeError):
    """Raised on any attempt to reach a non-loopback address while the block is active."""


def is_loopback_host(host: object) -> bool:
    if not isinstance(host, str) or not host:
        return True  # unix path / bytes / wildcard bind: not an external host
    h = host.strip("[]").split("%")[0].lower()
    if h in {"localhost", "localhost.localdomain", "ip6-localhost", "0.0.0.0", "::", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


@contextmanager
def block_network() -> Iterator[None]:
    """Patch socket connect/connect_ex/getaddrinfo so external destinations raise NetworkBlocked."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def _check(address: object) -> None:
        if isinstance(address, tuple) and address and not is_loopback_host(address[0]):
            raise NetworkBlocked(f"external network access blocked (ANA-105): {address[0]!r}")

    def connect(self, address):  # noqa: ANN001
        _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):  # noqa: ANN001
        _check(address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, *a, **kw):  # noqa: ANN001
        if not is_loopback_host(host):
            raise NetworkBlocked(f"external DNS lookup blocked (ANA-105): {host!r}")
        return real_getaddrinfo(host, *a, **kw)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = real_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = real_getaddrinfo  # type: ignore[assignment]


# ----------------------------------------------------------------------------------------------
# ANA-129: deterministic random order without an extra plugin (pytest-randomly is not installed on purpose).
# ----------------------------------------------------------------------------------------------
def resolve_seed(value: str | None) -> int | None:
    """None/'' -> disabled; 'random' -> fresh seed; digits -> that seed."""
    if value in (None, "", "off", "0-off"):
        return None
    if str(value).lower() in {"random", "auto"}:
        return random.SystemRandom().randrange(1, 2**31)
    return int(value)  # type: ignore[arg-type]


def shuffled(items: list, seed: int, key=lambda it: it.module.__name__ if getattr(it, "module", None) else "") -> list:
    """Shuffle modules, then tests within each module (module-scoped fixtures stay contiguous)."""
    rnd = random.Random(seed)
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(key(it), []).append(it)
    names = sorted(groups)
    rnd.shuffle(names)
    out: list = []
    for n in names:
        g = list(groups[n])
        rnd.shuffle(g)
        out.extend(g)
    return out


# ----------------------------------------------------------------------------------------------
# ANA-127: path-based automatic markers (replaces ad-hoc skipif/ENV gating for selection purposes).
# ----------------------------------------------------------------------------------------------
AUTO_MARKERS: dict[str, tuple[str, ...]] = {
    "e2e/": ("e2e", "slow"),
    "test_terminals_jobobject.py": ("windows_only",),
    "test_pty_posix.py": ("posix_only",),
}


def auto_markers_for(nodeid_path: str) -> list[str]:
    p = nodeid_path.replace(os.sep, "/")
    found: list[str] = []
    for needle, marks in AUTO_MARKERS.items():
        if needle in p:
            found.extend(marks)
    return found
