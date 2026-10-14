"""Build the Anamnesia desktop executable with PyInstaller (onedir): dist/Anamnesia/Anamnesia.exe.

    .venv/Scripts/python.exe packaging/build_exe.py [--onefile]

Bundles frontend/, config/*.yaml|json, data/synthetic_vault and assets/. Needs `pip install pyinstaller`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEP = ";" if sys.platform == "win32" else ":"


def main() -> int:
    onefile = "--onefile" in sys.argv
    adds = [("frontend", "frontend"), ("config", "config"), ("data/synthetic_vault", "data/synthetic_vault"),
            ("assets", "assets")]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", "Anamnesia",
           "--noconsole", "--onefile" if onefile else "--onedir",
           "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
           "--specpath", str(ROOT / "build"),
           "--collect-submodules", "app", "--collect-submodules", "config", "--collect-submodules", "memory_gateway",
           "--collect-submodules", "uvicorn", "--collect-submodules", "anamnesia"]
    for src, dst in adds:
        cmd += ["--add-data", f"{ROOT / src}{SEP}{dst}"]
    icon = ROOT / "assets" / "anamnesia.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append(str(ROOT / "packaging" / "anamnesia_launcher.py"))
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
