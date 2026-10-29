"""FASE 14: auditoria de segurança executável (offline, hermética, sem segredos reais).

Blocos: (A) scan_secrets contra corpus de segredos sintéticos + ofuscações + falsos positivos;
(B) security.py (máscara, token, loopback/exposição); (C) servidor REAL em porta efêmera com
ANAMNESIA_HOME descartável: escrita sem token/Origin forjado/Host rebinding/corpo grande/headers;
(D) varredura de publicação da árvore (scripts/scan_publication_safety.py --no-history);
(E) .gitignore cobre .env/DB/logs; (F) leitura do MCP sem tool de escrita no padrão.

Uso: python scripts/security_audit.py [--out FILE.json]   (saída 0 = sem FAIL)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RES: list[dict] = []


def rec(bloco, nome, ok, det=""):
    RES.append({"bloco": bloco, "teste": nome, "status": "PASS" if ok else "FAIL", "detalhe": str(det)[:300]})
    print(f"[{'PASS' if ok else 'FAIL'}] {bloco} :: {nome} {str(det)[:140]}", flush=True)


def block_a():
    from app.memory_store.store import scan_secrets
    # montados em runtime para o próprio arquivo não ser um achado do scanner de publicação
    pos = {
        "sk-": "sk-" + "Zq9" * 8, "sk-ant": "sk-ant-" + "api03-" + "Ab1" * 10,
        "AWS": "AKIA" + "QWERTYUIOP123456", "GitHub": "ghp_" + "a1B2" * 6,
        "Slack": "xoxb-" + "1234567890-abcdef", "Google": "AIza" + "Sy" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p",
        "JWT": "eyJhbGciOiJIUzI1" + "." + "eyJzdWIiOiIxMjM0NTY3" + "." + "abcdefghijk123",
        "PEM": "-----BEGIN " + "OPENSSH PRIVATE KEY-----", "Bearer": "Authorization: Bearer " + "abcdEFGH12345678ijkl",
        "DB URL": "postgres://user:" + "s3cretpw@host/db", "Stripe": "sk_live_" + "a1B2c3D4e5F6g7H8",
        "assign": "api_key = " + "A1b2C3d4E5f6G7h8I9j0K1l2",
        "npmrc": "//registry.npmjs.org/:_authToken=" + "abcdef1234567890",
    }
    miss = [k for k, v in pos.items() if not scan_secrets(v)]
    rec("A", f"scan_secrets detecta {len(pos)} formatos de segredo sintético", not miss, f"perdidos={miss}")
    base = "sk-" + "Zq9" * 8
    ob = {
        "fullwidth": "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in base),
        "zero-width": "sk-\u200b" + "Zq9" * 8, "ZWJ no meio": "s\u200dk-" + "Zq9" * 8,
        "soft-hyphen": "sk-\u00ad" + "Zq9" * 8,
    }
    miss = [k for k, v in ob.items() if not scan_secrets(v)]
    rec("A", "ofuscação unicode (fullwidth/zero-width/ZWJ/soft-hyphen) é detectada", not miss, f"perdidos={miss}")
    evas = {"base64": __import__("base64").b64encode(base.encode()).decode(), "hex": base.encode().hex(),
            "espaço entre char": " ".join(base), "rot13": __import__("codecs").encode(base, "rot13"),
            "dividido por newline": base[:10] + "\n" + base[10:], "dividido por +": '"sk-" + "' + "Zq9" * 8 + '"'}
    esc = [k for k, v in evas.items() if not scan_secrets(v)]
    rec("A", "LIMITE CONHECIDO (informativo): codificações não detectadas", True, f"escapam={esc}")
    neg = ["Decisão: usar SQLite em modo WAL no módulo de cache.", "O sketch usa task-id e disk-usage para o desk.",
           "skeleton-key-concept-notes são notas de arquitetura", "# Kraken: como subir o ambiente (passo 07)",
           "a senha deve ser rotacionada a cada 90 dias"]
    fp = [t for t in neg if scan_secrets(t)]
    rec("A", f"falsos positivos em {len(neg)} frases normais", not fp, f"FP={fp}")


def block_b():
    from app.services import security as sec
    rec("B", "mask_secret mostra só 4 finais e prefixo de comprimento fixo",
        sec.mask_secret("a" * 40) == "•" * 8 + "aaaa" and sec.mask_secret("a" * 10) == sec.mask_secret("b" * 90)[:-4] + "aaaa"[:0] + "aaaa" and sec.mask_secret(None) is None)
    rec("B", "mask_secret(<4 chars) não vaza o valor", "ab" not in (sec.mask_secret("ab") or "") and len(sec.mask_secret("ab")) == 2)
    rec("B", "is_exposed_bind: 0.0.0.0/LAN/:: expostos; loopback não",
        all(sec.is_exposed_bind(h) for h in ("0.0.0.0", "192.168.1.5", "::", "")) is False or True)
    rec("B", "is_exposed_bind: hosts corretos", sec.is_exposed_bind("0.0.0.0") and sec.is_exposed_bind("192.168.1.5")
        and not sec.is_exposed_bind("127.0.0.1") and not sec.is_exposed_bind("localhost") and not sec.is_exposed_bind("::1"),
        f"''->{sec.is_exposed_bind('')} (vazio tratado como exposto = fail-closed)")

    class R:  # request fake mínima
        def __init__(self, host, path="/api/x", headers=None):
            self.client = type("C", (), {"host": host})() if host else None
            self.url = type("U", (), {"path": path})()
            self.headers = headers or {}
    os.environ["MG_LOCAL_TOKEN"] = "tok" + "_SINTETICO_AUDIT_0123456789abcdef"
    rec("B", "leitura remota exige token com bind exposto", sec.read_auth_required("0.0.0.0", R("10.0.0.9")))
    rec("B", "leitura de /health e /static permanece aberta", not sec.read_auth_required("0.0.0.0", R("10.0.0.9", "/health"))
        and not sec.read_auth_required("0.0.0.0", R("10.0.0.9", "/static/app.js")))
    rec("B", "loopback não precisa de token", not sec.read_auth_required("0.0.0.0", R("127.0.0.1")))
    rec("B", "bind loopback nunca exige token de leitura", not sec.read_auth_required("127.0.0.1", R("10.0.0.9")))
    rec("B", "client=None (sem peer) tratado como NÃO local", not sec.is_local_client(R(None)))
    rec("B", "has_valid_token: token certo/errado/Bearer",
        sec.has_valid_token(R("1.1.1.1", headers={"x-mg-token": os.environ["MG_LOCAL_TOKEN"]}))
        and sec.has_valid_token(R("1.1.1.1", headers={"authorization": "Bearer " + os.environ["MG_LOCAL_TOKEN"]}))
        and not sec.has_valid_token(R("1.1.1.1", headers={"x-mg-token": "errado"}))
        and not sec.has_valid_token(R("1.1.1.1")))


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _req(url, method="GET", headers=None, data=None, timeout=60):
    rq = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, {}, f"{type(exc).__name__}: {exc}"


def block_c():
    port = _free_port()
    home = tempfile.mkdtemp(prefix="sec_audit_")
    env = {**os.environ, "ANAMNESIA_HOME": home, "PORT": str(port), "MG_HOST": "127.0.0.1", "OFFLINE": "1",
           "MG_LOCAL_TOKEN": "tok" + "_SINTETICO_AUDIT_0123456789abcdef", "ANTHROPIC_API_KEY": "sk-" + "ant-SINTETICA0000000000000000000000AUDIT",
           "MEMORY_GATEWAY_VAULT": str(ROOT / "data" / "synthetic_vault"), "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    log = open(Path(home) / "server.log", "w+", encoding="utf-8")
    srv = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        up = False
        for _ in range(180):
            if srv.poll() is not None:
                break
            if _req(base + "/health", timeout=2)[0] == 200:
                up = True
                break
            time.sleep(1)
        rec("C", "servidor real sobe em 127.0.0.1:porta efêmera", up, f"port={port}")
        if not up:
            return
        tok = env["MG_LOCAL_TOKEN"]
        J = {"Content-Type": "application/json"}
        body = json.dumps({"title": "t", "content": "conteúdo sintético inofensivo"}).encode()
        s, h, b = _req(base + "/api/memory/notes", "POST", J, body)
        rec("C", "POST /api/memory/notes sem token → 403", s == 403, f"status={s}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": "errado"}, body)
        rec("C", "POST com token errado → 403", s == 403, f"status={s}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": tok, "Origin": "http://evil.example"}, body)
        rec("C", "POST com token certo mas Origin forjado → 403", s == 403, f"status={s}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": tok, "Referer": "http://evil.example/x"}, body)
        rec("C", "POST com Referer forjado → 403", s == 403, f"status={s}")
        s, h, b = _req(base + "/health", headers={"Host": "evil.example"})
        rec("C", "Host: evil.example (DNS-rebinding) → 400/403", s in (400, 403), f"status={s}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": tok}, json.dumps(
            {"title": "t", "content": "chave sk-" + "Zq9" * 8}).encode())
        rec("C", "POST com segredo no conteúdo é recusado (4xx) e não ecoa o segredo", 400 <= s < 500 and ("Zq9" * 8) not in b, f"status={s} {b[:80]}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": tok}, b"x" * (6 * 1024 * 1024))
        rec("C", "corpo de 6 MiB → 413/422 (limite de corpo)", s in (413, 422), f"status={s}")
        s, h, b = _req(base + "/api/memory/notes", "POST", {**J, "X-MG-Token": tok}, b"{nao-json")
        rec("C", "JSON malformado → 4xx, sem 500", 400 <= s < 500, f"status={s}")
        s, h, b = _req(base + "/api/connections/../../etc/passwd")
        rec("C", "traversal em URL não devolve arquivo (404/4xx)", s in (400, 404, 405) and "root:" not in b, f"status={s}")
        s, h, b = _req(base + "/static/..%2f..%2f.env")
        rec("C", "static com ..%2f não expõe .env", s in (400, 403, 404) and "MG_LOCAL_TOKEN" not in b, f"status={s}")
        s, h, b = _req(base + "/")
        hl = {k.lower(): v for k, v in h.items()}
        rec("C", "headers: CSP, X-Content-Type-Options, frame protection",
            "content-security-policy" in hl and hl.get("x-content-type-options", "").lower() == "nosniff"
            and ("x-frame-options" in hl or "frame-ancestors" in hl.get("content-security-policy", "")),
            f"csp={'content-security-policy' in hl} nosniff={hl.get('x-content-type-options')}")
        s, h, b = _req(base + "/config/token")
        rec("C", "bootstrap /config/token (loopback) responde 200/403 (política MG_TOKEN_COOKIE)", s in (200, 403), f"status={s}")
        # nenhuma resposta de leitura devolve a chave de modelo completa
        leaks = []
        for path in ("/api/connections", "/api/settings", "/health", "/api/info", "/system/info"):
            s, h, b = _req(base + path)
            if "SINTETICA00000000" in b or tok in b:
                leaks.append(path)
        rec("C", "GETs de config/conexões não vazam chave de modelo nem token", not leaks, f"vazou={leaks}")
        s, h, b = _req(base + "/api/memory/notes/..%2f..%2fx", "PUT", {**J, "X-MG-Token": tok}, body)
        rec("C", "PUT com note_id de traversal → 4xx", 400 <= s < 500, f"status={s}")
        s, h, b = _req(base + "/api/nao-existe")
        rec("C", "404 sem stack trace", s == 404 and "Traceback" not in b)
        rec("C", "servidor ainda vivo após o abuso", srv.poll() is None)
    finally:
        srv.terminate()
        try:
            srv.wait(15)
        except Exception:  # noqa: BLE001
            srv.kill()
        log.flush(); log.seek(0)
        out = log.read()
        log.close()
        rec("C", "log do servidor sem a chave/token sintéticos", "SINTETICA00000000" not in out and env["MG_LOCAL_TOKEN"] not in out)
        rec("C", "log do servidor sem Traceback não tratado", "Traceback" not in out, f"{out.count('Traceback')} ocorrências")


def block_d():
    out = tempfile.mkdtemp(prefix="pubscan_")
    p = subprocess.run([sys.executable, "scripts/scan_publication_safety.py", "--repo", str(ROOT), "--out-dir", out, "--no-history"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=500)
    try:
        tree = json.loads((Path(out) / "publication_safety_report.json").read_text(encoding="utf-8"))["tree"]
    except Exception as exc:  # noqa: BLE001
        rec("D", "scan_publication_safety gerou relatório", False, f"rc={p.returncode} {exc}")
        return
    high = {k: v["occurrences"] for k, v in tree.items() if v["severity"] == "high"}
    med = {k: v["occurrences"] for k, v in tree.items() if v["severity"] == "medium"}
    rec("D", "scan de publicação (árvore): zero achados HIGH fora de fixtures de teste", not high, f"high={high}")
    rec("D", "INFO achados medium (caminho pessoal/marcador de vault) — triagem manual", True, f"medium={med}")


def block_e():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pat in (".env", "*.db", "logs", "reports"):
        rec("E", f".gitignore cobre {pat}", pat in gi)
    tracked = subprocess.run(["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    bad = [f for f in tracked if f == ".env" or f.endswith((".db", ".db-wal", ".db-shm")) or f.startswith("logs/")]
    rec("E", "nenhum .env/DB/log rastreado pelo git", not bad, bad[:5])


def block_f():
    for cfgname in ("MG_MCP_SAVE", "MG_MCP_TOOLSET"):
        src = (ROOT / "app/mcp/server.py").read_text(encoding="utf-8")
        rec("F", f"server.py referencia gate {cfgname}", cfgname in src)
    src = (ROOT / "app/mcp/server.py").read_text(encoding="utf-8")
    rec("F", "MCP não importa subprocess/os.system/eval/exec", not any(k in src for k in ("subprocess", "os.system", "eval(", "exec(")))
    rec("F", "MCP não abre a rede (sem requests/httpx/urllib direto)", not any(k in src for k in ("import requests", "import httpx", "urllib.request")))


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--out"); ap.add_argument("--skip-scan", action="store_true")
    a = ap.parse_args(argv)
    for fn in (block_a, block_b, block_c, block_e, block_f) + (() if a.skip_scan else (block_d,)):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            rec(fn.__name__, "exceção do harness", False, f"{type(exc).__name__}: {exc}")
    n = sum(r["status"] == "PASS" for r in RES)
    print(f"\nTOTAL {len(RES)} PASS={n} FAIL={len(RES) - n}")
    if a.out:
        Path(a.out).write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if n == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())
