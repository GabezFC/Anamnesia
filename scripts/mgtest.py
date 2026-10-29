#!/usr/bin/env python3
"""Gerencia o contêiner de TESTE local da Anamnésia (projeto compose ``mgtest``, porta 8010).

Só stdlib. Funciona em Windows (PowerShell/cmd/git-bash), Linux e macOS.

    python scripts/mgtest.py up        # valida config, checa porta, build + up, espera healthy, prova imagem == código
    python scripts/mgtest.py status    # id, imagem, porta, volume, mounts, saúde, prova de código
    python scripts/mgtest.py logs [N]  # últimas N linhas (padrão 80), com token/segredos mascarados
    python scripts/mgtest.py restart   # docker compose restart (dados persistem) + espera healthy
    python scripts/mgtest.py down      # docker compose down (NUNCA usa -v: o volume de dados é preservado)
    python scripts/mgtest.py smoke     # scripts/docker_smoke.py (API + Playwright, se disponível)

Config: docker/mgtest.env (ANAMNESIA_PORT, ANAMNESIA_PROJECTS_HOST, ANAMNESIA_PATH_MAP). Sem segredos.
Variáveis: MGTEST_PROJECT (padrão mgtest), MGTEST_ENV_FILE, MGTEST_PW_PYTHON (python com playwright p/ smoke).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = os.environ.get("MGTEST_PROJECT", "mgtest")
ENV_FILE = Path(os.environ.get("MGTEST_ENV_FILE", ROOT / "docker" / "mgtest.env"))
SERVICE = "anamnesia"
CONTAINER = f"{PROJECT}-{SERVICE}-1"
HEALTH_TIMEOUT_S = 180

# Snippet idêntico no host e no contêiner: hash determinístico da árvore frontend/.
_HASH_SNIPPET = r"""
import hashlib, sys, pathlib
base = pathlib.Path(sys.argv[1]); h = hashlib.sha256(); n = 0
for p in sorted(base.rglob('*')):
    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
        h.update(p.relative_to(base).as_posix().encode()); h.update(b'\0'); h.update(p.read_bytes()); h.update(b'\0'); n += 1
print(h.hexdigest(), n)
"""


def run(cmd, check=True, env=None, capture=True, timeout=900):
    r = subprocess.run(cmd, cwd=ROOT, env=env, text=True, encoding="utf-8", errors="replace",
                       capture_output=capture, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"FALHOU ({r.returncode}): {' '.join(map(str, cmd))}\n{(r.stdout or '')}{(r.stderr or '')}")
    return r


def read_env_file() -> dict:
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def compose_base() -> list[str]:
    cmd = ["docker", "compose", "-p", PROJECT]
    if ENV_FILE.exists():
        cmd += ["--env-file", str(ENV_FILE)]
    return cmd + ["-f", str(ROOT / "docker-compose.yml")]


def port() -> int:
    return int(os.environ.get("ANAMNESIA_PORT") or read_env_file().get("ANAMNESIA_PORT") or 8000)


def base_url() -> str:
    return f"http://127.0.0.1:{port()}"


def git_commit() -> str:
    r = run(["git", "rev-parse", "HEAD"], check=False)
    sha = (r.stdout or "").strip() or "unknown"
    dirty = bool((run(["git", "status", "--porcelain", "--", "app", "frontend", "config", "anamnesia",
                       "memory_gateway", "pyproject.toml"], check=False).stdout or "").strip())
    return sha + ("+dirty" if dirty else "")


def local_frontend_hash() -> tuple[str, int]:
    r = run([sys.executable, "-c", _HASH_SNIPPET, str(ROOT / "frontend")])
    h, n = r.stdout.split()
    return h, int(n)


def container_running() -> bool:
    r = run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def port_in_use(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", p)) == 0:
            return True
    return False


def check_port_free():
    p = port()
    if container_running():
        pub = run(["docker", "port", CONTAINER, "8000/tcp"], check=False).stdout
        if f"127.0.0.1:{p}" in pub:
            print(f"[porta] {p} já publicada pelo próprio {CONTAINER} (será recriado).")
            return
    if port_in_use(p):
        raise SystemExit(f"[porta] 127.0.0.1:{p} está OCUPADA por outro processo. Nada foi alterado. "
                         f"Descubra com: netstat -ano | findstr :{p}  (não encerre processos de terceiros); "
                         f"ou escolha outra porta em {ENV_FILE}.")
    print(f"[porta] 127.0.0.1:{p} livre.")


def health_state() -> str:
    r = run(["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", CONTAINER], check=False)
    return r.stdout.strip() if r.returncode == 0 else "absent"


def http_status(path="/health") -> int:
    try:
        with urllib.request.urlopen(base_url() + path, timeout=4) as resp:
            return resp.status
    except Exception:
        return 0


def wait_healthy(timeout=HEALTH_TIMEOUT_S):
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout:
        st = health_state()
        code = http_status()
        if f"{st}/{code}" != last:
            print(f"[health] docker={st} GET /health={code}")
            last = f"{st}/{code}"
        if st == "healthy" and code == 200:
            return
        if st == "absent" or (not container_running() and time.time() - t0 > 15):
            print(run(["docker", "logs", "--tail", "40", CONTAINER], check=False).stdout)
            raise SystemExit("[health] contêiner não está rodando.")
        time.sleep(3)
    raise SystemExit(f"[health] timeout {timeout}s sem healthy+200.")


def sanitize(text: str) -> str:
    text = re.sub(r"(?i)(token|secret|password|api[_-]?key|authorization)(\s*[=:]\s*|\"\s*:\s*\")[^\s\"',;]+", r"\1\2***", text)
    text = re.sub(r"(?i)(x-mg-token['\"]?\s*[:=]\s*)\S+", r"\1***", text)
    return re.sub(r"\b[A-Fa-f0-9]{32,}\b|\bsk-[A-Za-z0-9_-]{16,}", "***", text)


def code_proof() -> bool:
    """Compara commit/labels e hash da árvore frontend/ do repo com a do contêiner. Retorna True se iguais."""
    ok = True
    lab = run(["docker", "inspect", "-f", "{{json .Config.Labels}}", CONTAINER], check=False).stdout.strip()
    try:
        labels = json.loads(lab) or {}
    except Exception:
        labels = {}
    head = git_commit()
    img_rev = labels.get("org.opencontainers.image.revision", "(sem label)")
    print(f"[código] git HEAD (repo)          : {head}")
    print(f"[código] label revision da imagem  : {img_rev}")
    r = run(["docker", "exec", CONTAINER, "python", "-c",
             "import app,pathlib;print(pathlib.Path(app.__file__).parent.parent/'frontend')"], check=False)
    cdir = r.stdout.strip()
    r2 = run(["docker", "exec", CONTAINER, "python", "-c", _HASH_SNIPPET, cdir], check=False)
    lh, ln = local_frontend_hash()
    ch, cn = (r2.stdout.split() + ["?", "0"])[:2]
    same = lh == ch
    print(f"[código] frontend sha256 repo      : {lh[:16]}… ({ln} arquivos)")
    print(f"[código] frontend sha256 contêiner : {ch[:16]}… ({cn} arquivos) em {cdir}")
    print(f"[código] frontend {'IGUAL' if same else 'DIFERENTE (rebuild necessário)'}")
    ok &= same
    if img_rev.split("+")[0] != head.split("+")[0] and img_rev != "(sem label)":
        print("[código] AVISO: commit da imagem difere do HEAD atual (pode haver mudanças não commitadas — o hash do frontend é a prova).")
    return ok


def cmd_up():
    run(["docker", "version", "-f", "{{.Server.Version}}"])
    cfg = run(compose_base() + ["config", "-q"], check=False)
    if cfg.returncode != 0:
        raise SystemExit(f"[config] inválido:\n{cfg.stderr}")
    print("[config] docker compose config OK")
    check_port_free()
    env = dict(os.environ, GIT_COMMIT=git_commit(), FRONTEND_SHA=local_frontend_hash()[0])
    print(f"[build] GIT_COMMIT={env['GIT_COMMIT']} FRONTEND_SHA={env['FRONTEND_SHA'][:16]}…")
    r = run(compose_base() + ["up", "-d", "--build"], env=env, check=False, timeout=1800)
    print(sanitize((r.stdout or "") + (r.stderr or ""))[-2500:])
    if r.returncode != 0:
        raise SystemExit("[up] falhou (nenhum volume foi tocado).")
    wait_healthy()
    cmd_status()


def cmd_status():
    if run(["docker", "inspect", CONTAINER], check=False).returncode != 0:
        raise SystemExit(f"{CONTAINER} não existe.")
    j = json.loads(run(["docker", "inspect", CONTAINER]).stdout)[0]
    print(f"contêiner : {CONTAINER}  id={j['Id'][:12]}  estado={j['State']['Status']}  saúde={health_state()}")
    print(f"imagem    : {j['Config']['Image']}  id={j['Image'][7:19]}")
    print(f"portas    : {json.dumps(j['NetworkSettings']['Ports'])}")
    for m in j["Mounts"]:
        extra = f" volume={m['Name']}" if m["Type"] == "volume" else ""
        print(f"mount     : {m['Type']:6} {m['Destination']:11} rw={m['RW']}{extra}  <- {m['Source'] if m['Type']=='bind' else ''}")
    print(f"/health   : HTTP {http_status()}  ({base_url()})")
    ok = code_proof()
    print("prova de código:", "OK" if ok else "FALHOU")


def cmd_logs(n="80"):
    r = run(compose_base() + ["logs", "--no-color", "--tail", str(n), SERVICE], check=False)
    print(sanitize((r.stdout or "") + (r.stderr or "")))


def cmd_restart():
    run(compose_base() + ["restart", SERVICE])
    wait_healthy()
    print("[restart] OK; dados do volume preservados.")


def cmd_down(*extra):
    if any(a in ("-v", "--volumes", "--rmi") for a in extra):
        raise SystemExit("Recusado: este script nunca apaga volumes/imagens.")
    r = run(compose_base() + ["down"], check=False)
    print(sanitize((r.stdout or "") + (r.stderr or "")))
    print("[down] volume de dados preservado.")


def cmd_smoke(*extra):
    py = os.environ.get("MGTEST_PW_PYTHON")
    if not py:
        cand = Path.home() / "AppData/Local/hermes/cache/scratch/pw-venv/Scripts/python.exe"
        py = str(cand) if cand.exists() else sys.executable
    r = subprocess.run([py, str(ROOT / "scripts" / "docker_smoke.py"), "--url", base_url(),
                        "--container", CONTAINER, *extra], cwd=ROOT)
    raise SystemExit(r.returncode)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    c, rest = argv[0], argv[1:]
    {"up": cmd_up, "status": cmd_status, "logs": cmd_logs, "restart": cmd_restart,
     "down": cmd_down, "smoke": cmd_smoke}.get(c, lambda *a: sys.exit(f"subcomando desconhecido: {c}"))(*rest)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
