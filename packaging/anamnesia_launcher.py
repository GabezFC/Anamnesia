"""Double-click launcher for Anamnesia (PyInstaller entry point).

Starts the local server (loopback only by default), waits for /health and opens the dashboard in the default
browser. If an instance is already answering on the port it just opens the browser. Console-less: all output
goes to <data dir>/logs/launcher.log. State lives in the per-user data dir (config/paths.py), never next to the exe.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


def _alive(port: int) -> bool:
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5).status == 200
    except Exception:
        return False


def _redirect_output() -> None:
    from config.paths import logs_dir
    d = logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / "launcher.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = fh


def main() -> int:
    if getattr(sys, "frozen", False):
        sys.path.insert(0, getattr(sys, "_MEIPASS", str(Path(sys.executable).parent)))
    if "--version" in sys.argv:
        print("anamnesia launcher"); return 0
    from config.paths import user_data_dir
    user_data_dir().mkdir(parents=True, exist_ok=True)
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False):
        _redirect_output()
    port = int(os.environ.get("PORT", "8000"))
    url = f"http://127.0.0.1:{port}/"
    if _alive(port):
        webbrowser.open(url)
        return 0
    from app.main import main as app_main
    t = threading.Thread(target=app_main, daemon=True, name="anamnesia-server")
    t.start()
    for _ in range(120):
        if _alive(port):
            webbrowser.open(url)
            break
        if not t.is_alive():
            return 1
        time.sleep(0.5)
    while t.is_alive():
        t.join(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
