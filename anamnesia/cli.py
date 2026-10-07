"""`anamnesia` CLI: version | doctor | start.

`doctor` is offline (no network calls) and never prints secret values: only yes/no.
`start` reuses `app.main.main` (the same server as `python -m app.main`).
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import shutil
import socket
import sys
from pathlib import Path

from anamnesia import __version__

MIN_PYTHON = (3, 12)
PORT = 8000


def _yn(ok: bool) -> str:
    return "yes" if ok else "no"


def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _token_present() -> bool:
    if os.environ.get("MG_LOCAL_TOKEN"):
        return True
    try:
        from config import PROJECT_ROOT
        env = Path(PROJECT_ROOT) / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, val = line.partition("=")
                if key.strip() == "MG_LOCAL_TOKEN" and val.strip():
                    return True
    except Exception:
        pass
    return False


def collect_checks() -> list[tuple[str, str, bool, bool]]:
    """Return (name, detail, ok, fatal) rows. No network, no secret values."""
    rows: list[tuple[str, str, bool, bool]] = []
    py_ok = sys.version_info[:2] >= MIN_PYTHON
    rows.append(("python", f"{sys.version.split()[0]} (requires >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})", py_ok, True))

    try:
        from config.retrieval import resolve_vault_path
        vault = resolve_vault_path()
        rows.append(("vault", f"{vault} exists={_yn(vault.is_dir())}", vault.is_dir(), True))
    except Exception as e:  # noqa: BLE001
        rows.append(("vault", f"unresolved ({type(e).__name__})", False, True))

    g = shutil.which("graphify")
    rows.append(("graphify", "found" if g else "not found (optional)", bool(g), False))
    rows.append(("TYPESAFE_API_KEY", _yn(bool(os.environ.get("TYPESAFE_API_KEY"))), bool(os.environ.get("TYPESAFE_API_KEY")), False))
    tok = _token_present()
    rows.append(("local token (MG_LOCAL_TOKEN)", _yn(tok) + ("" if tok else " (created on first `start`)"), tok, False))

    try:
        from config.benchmark import BenchmarkConfig
        db = Path(BenchmarkConfig().db_path)
        if db.is_file():
            rows.append(("benchmark.db", f"{db.stat().st_size / 1024 / 1024:.2f} MB", True, False))
        else:
            rows.append(("benchmark.db", "absent (created on demand)", False, False))
    except Exception as e:  # noqa: BLE001
        rows.append(("benchmark.db", f"unknown ({type(e).__name__})", False, False))

    free = _port_free(PORT)
    rows.append((f"port {PORT}", "free" if free else "in use", free, False))

    if sys.platform == "win32":
        has = importlib.util.find_spec("winpty") is not None
        rows.append(("pywinpty (optional)", _yn(has), has, False))
    return rows


def cmd_version(_args) -> int:
    print(f"anamnesia {__version__}")
    return 0


def cmd_doctor(_args) -> int:
    rows = collect_checks()
    w = max(len(r[0]) for r in rows)
    print(f"{'check'.ljust(w)}  status  detail")
    for name, detail, ok, fatal in rows:
        status = "OK" if ok else ("FAIL" if fatal else "warn")
        print(f"{name.ljust(w)}  {status.ljust(6)}  {detail}")
    return 1 if any(fatal and not ok for _, _, ok, fatal in rows) else 0


def cmd_start(_args) -> int:
    from app.main import main as app_main
    app_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anamnesia", description="Anamnésia / Memory Gateway")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="print version").set_defaults(func=cmd_version)
    sub.add_parser("doctor", help="offline environment checks").set_defaults(func=cmd_doctor)
    sub.add_parser("start", help="start REST API + dashboard (same as python -m app.main)").set_defaults(func=cmd_start)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
