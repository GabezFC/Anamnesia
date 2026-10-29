#!/usr/bin/env python3
"""Smoke reproduzível do contêiner Anamnésia (API + UI). Não conserta nada: só relata PASS/FAIL.

    python scripts/docker_smoke.py --url http://127.0.0.1:8010 --container mgtest-anamnesia-1
    (UI exige Playwright: use um Python com `playwright` + chromium; sem ele, as checagens de UI saem como SKIP)

Evidências (screenshots) em data/reports-out/evidence/. Exit code 1 se qualquer checagem FAIL.
O token local é lido de /data/.env DENTRO do contêiner, usado só em memória e nunca impresso.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, str, str]] = []


def rec(name, ok, detail=""):
    RESULTS.append((name, "PASS" if ok is True else ("SKIP" if ok is None else "FAIL"), detail))
    print(f"[{RESULTS[-1][1]}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def http(url, headers=None, method="GET", body=None, timeout=10):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def read_token(container):
    r = subprocess.run(["docker", "exec", container, "sh", "-c", "grep '^MG_LOCAL_TOKEN=' /data/.env"],
                       capture_output=True, text=True)
    m = re.match(r"MG_LOCAL_TOKEN=(.+)", r.stdout.strip())
    return m.group(1).strip().strip('"') if m else None


def api_checks(base, container):
    st, _ = http(base + "/health")
    rec("API /health 200", st == 200, f"HTTP {st}")
    st, html = http(base + "/")
    rec("UI / 200", st == 200, f"HTTP {st}")
    html = html.decode("utf-8", "replace")
    for bad in ("/static/js/terminals.js", "/static/vendor/xterm", "/static/css/xterm-dom.css",
                "/static/js/components/terminal-view.js"):
        st, _ = http(base + bad)
        rec(f"frontend NÃO serve {bad}", st == 404, f"HTTP {st}")
    rec("index.html sem referência a xterm/terminals.js", not re.search(r"xterm|terminals\.js", html, re.I))
    st, wjs = http(base + "/static/js/pages/workspace.js")
    rec("frontend serve workspace.js com workspace/io", st == 200 and b"workspace/io" in wjs, f"HTTP {st}")
    st, cjs = http(base + "/static/js/pages/config.js")
    cj = cjs.decode("utf-8", "replace")
    tabs = re.search(r"const tabs = \[(.*?)\];", cj, re.S)
    rec("config.js sem aba 'keys' na lista de abas", st == 200 and bool(tabs) and "'keys'" not in tabs.group(1),
        "abas: " + ", ".join(re.findall(r"\['(\w+)'", tabs.group(1))) if tabs else "lista não encontrada")
    st, cap = http(base + "/api/workspace/io/capabilities")
    rec("API /api/workspace/io/capabilities 200", st == 200, f"HTTP {st}")
    # sem token, escrita deve ser negada
    st, _ = http(base + "/api/projects", method="POST", headers={"Content-Type": "application/json"},
                 body=b'{"name":"x","path":"/projects"}')
    rec("escrita sem token/Origin negada (403)", st == 403, f"HTTP {st}")
    return st


def mounts_checks(container):
    r = subprocess.run(["docker", "inspect", container], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)[0]
    except Exception:
        rec("docker inspect", False, "contêiner ausente")
        return
    mounts = {m["Destination"]: m for m in j["Mounts"]}
    d = mounts.get("/data")
    rec("volume em /data é o nomeado do projeto", bool(d) and d["Type"] == "volume" and d["Name"].endswith("_anamnesia-data"),
        f"{d['Name'] if d else 'ausente'}")
    p = mounts.get("/projects")
    rec("/projects é bind READ-ONLY", bool(p) and p["Type"] == "bind" and p["RW"] is False,
        f"origem={p['Source'] if p else 'ausente'}")
    rec("sem privileged / docker.sock",
        not j["HostConfig"].get("Privileged") and not any("docker.sock" in m["Source"] for m in j["Mounts"]))
    t = subprocess.run(["docker", "exec", container, "sh", "-c", "touch /projects/.mg_write_test 2>&1; echo rc=$?"],
                       capture_output=True, text=True)
    rec("escrita em /projects falha (somente leitura)", "rc=0" not in t.stdout, t.stdout.strip().replace("\n", " ")[:120])


def persistence_check(base, container, restart_cmd):
    """Registra projeto de teste, reinicia o contêiner, confirma que persiste e remove."""
    tok = read_token(container)
    if not tok:
        rec("persistência: token em /data/.env", False, "token não encontrado")
        return
    hdr = {"X-MG-Token": tok, "Origin": base, "Referer": base + "/", "Content-Type": "application/json"}
    probe = "/projects"
    st, body = http(base + "/api/projects", method="POST", headers=hdr,
                    body=json.dumps({"name": "mgtest-smoke", "path": probe}).encode())
    if st != 201:
        rec("persistência: POST /api/projects", False, f"HTTP {st} {body[:200].decode('utf-8','replace')}")
        return
    pid = json.loads(body).get("id")
    rec("persistência: projeto de teste registrado", bool(pid), f"id={pid}")
    subprocess.run(restart_cmd, check=False, capture_output=True)
    import time
    for _ in range(60):
        if http(base + "/health")[0] == 200:
            break
        time.sleep(2)
    st, body = http(base + "/api/projects")
    found = any(p.get("id") == pid for p in (json.loads(body).get("projects", []) if st == 200 else []))
    rec("persistência: projeto sobrevive ao restart", found, f"HTTP {st}")
    st, _ = http(base + f"/api/projects/{pid}", method="DELETE", headers=hdr)
    rec("persistência: projeto de teste removido", st == 200, f"HTTP {st}")


def ui_checks(base, evidence: Path, tag: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        rec("UI (Playwright)", None, "playwright não instalado neste Python; use MGTEST_PW_PYTHON")
        return
    evidence.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        for vw, vh in ((1400, 900), (800, 700)):
            ctx = br.new_context(viewport={"width": vw, "height": vh})
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            for route in ("workspace", "config", "connections"):
                label = f"{route}@{vw}x{vh}"
                page.goto(f"{base}/#/{route}")
                page.wait_for_timeout(2500)
                shot = evidence / f"{tag}_{route}_{vw}x{vh}.png"
                page.screenshot(path=str(shot), full_page=False)
                text = page.inner_text("body")
                rec(f"[{label}] página renderiza conteúdo", len(text.strip()) > 80, f"{len(text)} chars; screenshot {shot.name}")
                m = re.search(r".{0,30}terminal.{0,30}", text, re.I | re.S)
                rec(f"[{label}] sem texto 'terminal' embutido", m is None, repr(m.group(0)) if m else "")
                banner = page.locator("[data-bind='demo-banner']")
                rec(f"[{label}] sem banner 'Dados de demonstração'",
                    banner.count() == 0 and "Dados de demonstração" not in text,
                    banner.first.inner_text().strip() if banner.count() else "")
                if route == "config":
                    keys = page.locator("[role=tab][data-tab='keys']").count()
                    named = [t for t in page.locator("[role=tab]").all_inner_texts() if re.fullmatch(r"\s*chaves\s*", t, re.I)]
                    rec(f"[{label}] sem sub-aba Chaves", keys == 0 and not named,
                        "abas: " + " | ".join(x.strip() for x in page.locator("[role=tab]").all_inner_texts()))
                if route == "connections":
                    info = page.evaluate("""() => {
                      const el = [...document.querySelectorAll('*')].filter(e => e.children.length < 6 && /opencode/i.test(e.textContent || '') && e.textContent.length < 60);
                      if (!el.length) return {found:false};
                      let c = el[0].closest('.connection-card'); if (!c) { c = el[0]; } if (!el[0].closest('.connection-card')) for (let i=0;i<8 && c.parentElement;i++){ c=c.parentElement; if (c.querySelectorAll('input,select,textarea').length || /card|section|article/i.test(c.className+c.tagName)) break; }
                      const fields = [...c.querySelectorAll('input,select,textarea')].map(i => [i.name,i.id,i.placeholder,i.getAttribute('aria-label'),(i.labels&&i.labels[0]||{}).textContent].join(' '));
                      return {found:true, tag:c.tagName, cls:c.className, fields};
                    }""")
                    if not info.get("found"):
                        rec(f"[{label}] OpenCode encontrado", False, "nenhum elemento 'OpenCode'")
                    else:
                        bad = [f for f in info["fields"] if re.search(r"anthropic|openai", f, re.I)]
                        rec(f"[{label}] OpenCode sem campos Anthropic/OpenAI", not bad,
                            f"{len(info['fields'])} campos no contêiner <{info['tag']} class='{info['cls'][:40]}'>" + (f"; ofensores: {bad}" if bad else ""))
            rec(f"[{vw}x{vh}] sem exceções JS na página", not errs, "; ".join(errs)[:200])
            ctx.close()
        br.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--container", default="mgtest-anamnesia-1")
    ap.add_argument("--project", default="mgtest")
    ap.add_argument("--evidence", default=str(ROOT / "data" / "reports-out" / "evidence"))
    ap.add_argument("--tag", default="docker_smoke")
    ap.add_argument("--no-persistence", action="store_true", help="não reinicia o contêiner nem cria projeto de teste")
    ap.add_argument("--no-ui", action="store_true")
    a = ap.parse_args()
    api_checks(a.url, a.container)
    mounts_checks(a.container)
    if not a.no_persistence:
        persistence_check(a.url, a.container, ["docker", "restart", a.container])
    if not a.no_ui:
        ui_checks(a.url, Path(a.evidence), a.tag)
    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\nRESUMO: {sum(r[1]=='PASS' for r in RESULTS)} PASS, {len(fails)} FAIL, {sum(r[1]=='SKIP' for r in RESULTS)} SKIP")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
