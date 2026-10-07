#!/usr/bin/env python
"""End-to-end browser driver for the Anamnesia Workspace (real server, real PTY, real Chromium).

Run it with a Python that has `playwright` (+ Chromium installed), NOT necessarily the project venv:

    <playwright-python> scripts/e2e_workspace.py [--out DIR] [--keep-going]

The server is started as a subprocess with a *separate* interpreter (it needs `pywinpty` on Windows):

    E2E_SERVER_PYTHON   python of a venv with requirements.txt + pywinpty (default: project .venv)
    E2E_PORT            port (default 8123; never 8000)

Isolation: ANAMNESIA_HOME = fresh temp dir (token / .env / benchmark.db are throwaway),
MEMORY_GATEWAY_VAULT = data/synthetic_vault, ANAMNESIA_ROUTING removed from the environment.
The real .env is never read. The server and every child it spawned are always stopped (finally).

Exit code 0 only when every step passed. See docs/E2E.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("E2E_PORT", "8123"))
BASE = f"http://127.0.0.1:{PORT}"
FAKE_KEY = "sk-test-1234567890abcdef"
MARKER = "e2e-anamnesia"

# Terminal captured by wrapping window.Terminal as soon as xterm.js assigns it (the app keeps its
# instances module-private); lets us read term.buffer.active without touching app code.
INIT_JS = """
(() => {
  window.__terms = [];
  let T;
  Object.defineProperty(window, 'Terminal', { configurable: true,
    get() { return T; },
    set(v) {
      if (!v || v.__wrapped) { T = v; return; }
      class Wrapped extends v { constructor(...a) { super(...a); window.__terms.push(this); } }
      Wrapped.__wrapped = true; T = Wrapped;
    } });
})();
"""
BUFFER_JS = """
() => {
  const ts = (window.__terms || []).filter((t) => t.element && t.element.isConnected);
  const t = ts[ts.length - 1];
  if (!t) return null;
  const b = t.buffer.active; const out = [];
  for (let y = 0; y < b.length; y++) { const l = b.getLine(y); out.push(l ? l.translateToString(true) : ''); }
  return { text: out.join('\\n'), cols: t.cols, rows: t.rows, count: ts.length };
}
"""


# ----------------------------------------------------------------------------- results
@dataclass
class Step:
    name: str
    status: str = "pending"          # passed | failed | skipped
    evidence: str = ""
    shots: list[str] = field(default_factory=list)


class Ctx:
    def __init__(self, out: Path):
        self.out = out
        self.steps: list[Step] = []
        self.page = None
        self.console_errors: list[str] = []
        self.http_errors: list[str] = []
        self.responses: dict[str, str] = {}
        self.costs_status: list[int] = []
        self.conn_bodies: list[str] = []
        self.project_dir: Path | None = None
        self.server_pid = 0
        self.base_pids: set[int] = set()
        self.fatal = False

    def shot(self, name: str) -> str:
        p = self.out / f"{name}.png"
        self.page.screenshot(path=str(p), full_page=False)
        return str(p)


# ----------------------------------------------------------------------------- process helpers
def port_in_use(port: int = PORT) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ps(cmd: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def process_table() -> list[dict]:
    """[{pid, ppid, name}] for every process (Windows via CIM, POSIX via ps)."""
    if os.name == "nt":
        raw = _ps("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress")
        rows = json.loads(raw or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        return [{"pid": r["ProcessId"], "ppid": r["ParentProcessId"], "name": (r["Name"] or "").lower()} for r in rows]
    out = subprocess.run(["ps", "-eo", "pid=,ppid=,comm="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "name": parts[2].lower()})
    return rows


def descendants(pid: int, table: list[dict] | None = None) -> list[dict]:
    table = table if table is not None else process_table()
    kids: dict[int, list[dict]] = {}
    for r in table:
        kids.setdefault(r["ppid"], []).append(r)
    out, stack = [], [pid]
    while stack:
        for k in kids.get(stack.pop(), []):
            out.append(k)
            stack.append(k["pid"])
    return out


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


class Server:
    def __init__(self, home: Path, log: Path):
        self.home, self.log = home, log
        self.proc: subprocess.Popen | None = None

    def env(self) -> dict:
        env = {k: v for k, v in os.environ.items()
               if k not in ("ANAMNESIA_ROUTING", "ANAMNESIA_ROUTING_PRESET", "OBSIDIAN_VAULT_PATH", "MG_PORT")}
        env.update(PORT=str(PORT), ANAMNESIA_HOME=str(self.home),
                   MEMORY_GATEWAY_VAULT=str(ROOT / "data" / "synthetic_vault"), PYTHONUTF8="1")
        return env

    def start(self, python: str, timeout: float = 90) -> None:
        if port_in_use():
            raise RuntimeError(f"port {PORT} already in use; refusing to start")
        fh = open(self.log, "wb")
        self.proc = subprocess.Popen([python, "-m", "app.main"], cwd=str(ROOT), env=self.env(),
                                     stdout=fh, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early (code {self.proc.returncode}); see {self.log}")
            try:
                with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("server did not become healthy in time")

    def stop(self) -> None:
        if self.proc is not None:
            if self.proc.poll() is None:
                kill_tree(self.proc.pid)
                try:
                    self.proc.wait(timeout=15)
                except Exception:
                    pass
        # Anything still bound to the port after that is ours: find and kill it.
        t0 = time.time()
        while port_in_use() and time.time() - t0 < 10:
            time.sleep(0.3)


# ----------------------------------------------------------------------------- page helpers
def buf(page):
    return page.evaluate(BUFFER_JS)


def wait_buffer(page, pred, timeout=20.0, desc="buffer condition"):
    t0, last = time.time(), None
    while time.time() - t0 < timeout:
        last = buf(page)
        if last and pred(last):
            return last
        time.sleep(0.25)
    tail = (last or {}).get("text", "")[-400:]
    raise AssertionError(f"timeout waiting for {desc}; buffer tail: {tail!r}")


def lines_of(b) -> list[str]:
    return [ln.rstrip() for ln in b["text"].splitlines()]


def type_in_terminal(page, text: str, enter=True):
    page.evaluate("() => { const ts=(window.__terms||[]).filter(t=>t.element&&t.element.isConnected); ts[ts.length-1].focus(); }")
    page.keyboard.type(text, delay=15)
    if enter:
        page.keyboard.press("Enter")


def settle(page, ms=400):
    page.wait_for_timeout(ms)


# ----------------------------------------------------------------------------- steps
def step_home(c: Ctx):
    p = c.page
    p.goto(BASE + "/", wait_until="networkidle")
    p.wait_for_selector("#ws", timeout=15000)
    title = p.inner_text("h1, .page-title, #page-title, main h1") if p.query_selector("h1, .page-title, #page-title, main h1") else ""
    assert "Workspace" in p.inner_text("body"), "texto 'Workspace' ausente"
    h = p.evaluate("location.hash")
    nav = p.evaluate("() => { const a=document.querySelector('[data-nav=workspace]'); return a ? (a.getAttribute('aria-current')||a.className) : null }")
    return f"hash={h!r}; #ws presente; h1={title!r}; nav workspace={nav!r}"


def step_add_project(c: Ctx):
    p = c.page
    c.project_dir = Path(tempfile.mkdtemp(prefix="e2e-proj-"))
    (c.project_dir / "README.txt").write_text("e2e readme\n", encoding="utf-8")
    p.click("details.ws-add summary")
    p.fill("#ws-add-name", "e2e-proj")
    p.fill("#ws-add-path", str(c.project_dir))
    p.click("#ws-add-form button[type=submit]")
    p.wait_for_selector("[data-pick]", timeout=10000)
    msg = p.inner_text("#ws-msg")
    assert "adicionado" in msg, f"mensagem inesperada: {msg!r}"
    names = p.eval_on_selector_all("[data-pick]", "els => els.map(e => e.textContent.trim())")
    assert "e2e-proj" in names, names
    return f"projetos={names}; msg={msg!r}; pasta={c.project_dir}"


def step_terminal(c: Ctx):
    p = c.page
    opts = p.eval_on_selector_all("#ws-profile option", "os => os.map(o => [o.value, o.disabled])")
    assert any(v == "shell" for v, _ in opts), f"perfil shell ausente: {opts}"
    p.select_option("#ws-profile", "shell")
    p.wait_for_function("() => !document.querySelector('#ws-new').disabled", timeout=5000)
    p.click("#ws-new")
    p.wait_for_selector(".ws-dot-live", timeout=20000)
    type_in_terminal(p, f"echo {MARKER}")
    b = wait_buffer(p, lambda b: MARKER in lines_of(b), desc=f"linha exata {MARKER!r}")
    c.shots.append(c.shot("01_workspace_terminal")) if hasattr(c, "shots") else None
    tail = [ln for ln in lines_of(b) if ln][-4:]
    return f"cols x rows={b['cols']}x{b['rows']}; últimas linhas do buffer={tail}"


def step_resize(c: Ctx):
    p = c.page
    before = buf(p)
    # >1100px: at <=1100px workspace.css hides the file explorer column by design.
    p.set_viewport_size({"width": 1200, "height": 720})
    wait_buffer(p, lambda b: (b["cols"], b["rows"]) != (before["cols"], before["rows"]), desc="xterm refit", timeout=10)
    settle(p, 1200)
    type_in_terminal(p, "mode con")
    # `mode con` is localised (Columns/Lines in en, Colunas/Linhas in pt-BR).
    col_re, line_re = r"(?:Columns|Colunas):\s+(\d+)", r"(?:Lines|Linhas):\s+(\d+)"
    b = wait_buffer(p, lambda b: re.search(col_re, b["text"]) is not None, desc="saída de mode con")
    cols = int(re.findall(col_re, b["text"])[-1])
    lines = int(re.findall(line_re, b["text"])[-1])
    assert cols == b["cols"] and lines == b["rows"], f"filho vê {cols}x{lines}, xterm {b['cols']}x{b['rows']}"
    return f"antes {before['cols']}x{before['rows']} -> depois xterm {b['cols']}x{b['rows']}; mode con: Columns={cols} Lines={lines}"


def step_split(c: Ctx):
    p = c.page
    n0 = p.locator(".ws-leaf").count()
    p.evaluate("() => { const ts=(window.__terms||[]).filter(t=>t.element&&t.element.isConnected); ts[ts.length-1].focus(); }")
    p.keyboard.press("Control+]")
    p.wait_for_function("() => document.querySelector('#ws-hint').classList.contains('armed')", timeout=3000)
    p.keyboard.press("h")
    p.wait_for_function("n => document.querySelectorAll('.ws-leaf').length > n", arg=n0, timeout=5000)
    n1 = p.locator(".ws-leaf").count()
    empty = p.locator(".ws-empty-pane").count()
    b = buf(p)
    assert MARKER in lines_of(b), "terminal perdeu o buffer após dividir"
    c.shot("02_split")
    return f"painéis {n0} -> {n1}; painéis vazios={empty}; terminal ainda com {MARKER!r}; prefixo Ctrl+] então h"


def step_reload(c: Ctx):
    p = c.page
    ls = p.evaluate("localStorage.getItem('anamnesia.ws.layout.v1')")
    p.reload(wait_until="networkidle")
    p.wait_for_selector(".ws-dot-live", timeout=20000)
    b = wait_buffer(p, lambda b: MARKER in lines_of(b), desc="replay do buffer após reload")
    n = p.locator(".ws-leaf").count()
    c.shot("03_after_reload")
    return f"layout salvo={ls[:80] if ls else None}...; painéis após reload={n}; replay contém {MARKER!r}; terms={b['count']}"


def step_explorer(c: Ctx):
    p = c.page
    p.fill("#ws-fq", "README")
    p.wait_for_selector("#ws-files .ws-file", timeout=8000)
    names = p.eval_on_selector_all("#ws-files .ws-file", "els => els.map(e => e.textContent.trim())")
    assert any("README.txt" in n for n in names), names
    p.fill("#ws-fq", "")
    return f"busca 'README' -> {names}"


def collect_errors(c: Ctx, label: str):
    errs = [e for e in c.console_errors if "favicon" not in e]
    http = [e for e in c.http_errors if "favicon" not in e]
    return errs, http


def step_connections(c: Ctx):
    p = c.page
    p.goto(BASE + "/#/connections")
    p.wait_for_selector("form.cx-key", timeout=15000)
    assert "Conexões" in p.inner_text("body")
    form = p.locator("form.cx-key").first
    cid, env = form.get_attribute("data-cid"), form.get_attribute("data-env")
    inp = form.locator("input[type=password]")
    assert inp.get_attribute("type") == "password"
    inp.fill(FAKE_KEY)
    form.locator("button[type=submit]").click()
    p.wait_for_function("() => /salva/.test(document.querySelector('#cx-status').textContent)", timeout=10000)
    settle(p, 500)
    c.shot("04_conexoes_saved")

    def leaks() -> dict:
        return p.evaluate("""(k) => {
          const inputs = [...document.querySelectorAll('input,textarea')].map(i => i.value).join('|');
          return { text: document.body.innerText.includes(k), html: document.documentElement.outerHTML.includes(k),
                   inputs: inputs.includes(k),
                   ls: JSON.stringify({...localStorage}).includes(k), ss: JSON.stringify({...sessionStorage}).includes(k) };
        }""", FAKE_KEY)

    l = leaks()
    assert not any(l.values()), f"CHAVE VAZOU: {l}"
    masked = p.inner_text(f"#cx-{cid}-{env}-m") if p.query_selector(f"#cx-{cid}-{env}-m") else ""
    bodies_leak = [b for b in c.conn_bodies if FAKE_KEY in b]
    assert not bodies_leak, "chave presente em resposta de /api/connections"
    # remove it again
    p.once("dialog", lambda d: d.accept())
    p.locator(f'form.cx-key[data-cid="{cid}"][data-env="{env}"] [data-remove]').click()
    p.wait_for_function("() => /removida/.test(document.querySelector('#cx-status').textContent)", timeout=10000)
    l2 = leaks()
    assert not any(l2.values()), f"vazou após remover: {l2}"
    return (f"cartão {cid}/{env}; após salvar: mascarado={masked!r}; vazamento DOM/inputs/localStorage/sessionStorage={l}; "
            f"respostas /api/connections analisadas={len(c.conn_bodies)} (sem a chave); removida OK")


def _visit(c: Ctx, hash_: str, ready: str, shot: str):
    p = c.page
    c.console_errors.clear(); c.http_errors.clear(); c.costs_status.clear()
    p.goto(BASE + "/#/" + hash_)
    p.wait_for_selector(ready, timeout=15000)
    p.wait_for_load_state("networkidle")
    settle(p, 800)
    c.shot(shot)


def step_config(c: Ctx):
    _visit(c, "config", "#main", "05_config")
    errs, http = collect_errors(c, "config")
    assert not errs and not http, f"console={errs} http={http}"
    return f"sem erros de console; document.title={c.page.title()!r}"


def step_costs(c: Ctx):
    _visit(c, "costs", "#cs-root", "06_custos")
    errs, http = collect_errors(c, "costs")
    assert 200 in c.costs_status, f"/api/costs/summary não respondeu 200: {c.costs_status}"
    assert not errs and not http, f"console={errs} http={http}"
    return f"/api/costs/summary status={c.costs_status}; sem erros de console/HTTP"


def step_health(c: Ctx):
    p = c.page
    h = json.loads(urllib.request.urlopen(BASE + "/health", timeout=5).read())
    warns = h.get("warnings") or []
    p.goto(BASE + "/#/workspace")
    p.reload(wait_until="networkidle")
    p.wait_for_selector("#ws", timeout=10000)
    settle(p, 1000)
    if not warns:
        return "SKIP: /health sem warnings (nada a exibir)", "skipped"
    hidden = p.evaluate("document.querySelector('#health-banner').hidden")
    txt = p.inner_text("#health-banner")
    assert not hidden and warns[0].get("component", "sistema") in txt, f"banner não exibido: hidden={hidden} text={txt!r}"
    c.shot("07_health_banner")
    return f"{len(warns)} warning(s) -> banner visível: {txt[:200]!r}"


def step_close_and_orphans(c: Ctx):
    p = c.page
    p.goto(BASE + "/#/workspace")
    p.reload(wait_until="networkidle")
    p.wait_for_selector("[data-kill]", timeout=10000)
    during = [d for d in descendants(c.server_pid) if d["pid"] not in c.base_pids]
    p.once("dialog", lambda d: d.accept())
    p.locator("[data-kill]").first.click()
    p.wait_for_function("() => document.querySelectorAll('[data-kill]').length === 0", timeout=10000)
    t0, left = time.time(), None
    while time.time() - t0 < 15:
        tree = descendants(c.server_pid)
        left = [d for d in tree if d["pid"] not in c.base_pids and d["name"] in ("cmd.exe", "powershell.exe", "bash", "sh", "conhost.exe", "openconsole.exe")]
        if not left:
            break
        time.sleep(0.5)
    assert not left, f"processos órfãos sob o servidor: {left}"
    return f"filhos com sessão aberta={[(d['name'], d['pid']) for d in during]}; após fechar: nenhum cmd/conhost sob o servidor (pid {c.server_pid})"


STEPS = [
    ("1 home = Workspace", step_home),
    ("2 adicionar projeto", step_add_project),
    ("3 + Terminal (shell) e echo", step_terminal),
    ("4 resize -> mode con", step_resize),
    ("5 split com prefixo", step_split),
    ("6 reload reconecta + replay", step_reload),
    ("7 explorador acha README.txt", step_explorer),
    ("8 Conexões: chave fake nunca vaza", step_connections),
    ("9 Config sem erros", step_config),
    ("10 Custos 200 + sem erros", step_costs),
    ("11 banner de /health", step_health),
    ("12 fechar terminal: sem órfãos", step_close_and_orphans),
]


# ----------------------------------------------------------------------------- orchestration
def run_all(out: Path | None = None, keep_going: bool = True, headless: bool = True) -> list[Step]:
    from playwright.sync_api import sync_playwright

    scratch = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
    out = Path(out) if out else scratch / "e2e"
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp(prefix="anamnesia-e2e-home-"))
    python = os.environ.get("E2E_SERVER_PYTHON") or str(
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    c = Ctx(out)
    c.shots = []  # type: ignore[attr-defined]
    srv = Server(home, out / "server.log")
    try:
        srv.start(python)
        c.server_pid = srv.proc.pid
        c.base_pids = {d["pid"] for d in descendants(c.server_pid)}
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            try:
                ctxb = browser.new_context(viewport={"width": 1440, "height": 900})
                ctxb.add_init_script(INIT_JS)
                page = ctxb.new_page()
                c.page = page
                page.on("console", lambda m: c.console_errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
                page.on("pageerror", lambda e: c.console_errors.append(f"pageerror: {e}"))

                def on_resp(r):
                    u = r.url
                    if r.status >= 400 and "/api/sessions" not in u:
                        c.http_errors.append(f"{r.status} {u}")
                    if "/api/costs/summary" in u:
                        c.costs_status.append(r.status)
                    if "/api/connections" in u:
                        try:
                            c.conn_bodies.append(r.text())
                        except Exception:
                            pass
                page.on("response", on_resp)
                for name, fn in STEPS:
                    st = Step(name)
                    c.steps.append(st)
                    if c.fatal and not keep_going:
                        st.status = "skipped"
                        continue
                    try:
                        res = fn(c)
                        if isinstance(res, tuple):
                            st.evidence, st.status = res[0], res[1]
                        else:
                            st.evidence, st.status = res, "passed"
                    except Exception as e:  # noqa: BLE001
                        st.status = "failed"
                        st.evidence = f"{type(e).__name__}: {e}"
                        try:
                            c.shot(f"FAIL_{name.split()[0]}")
                        except Exception:
                            pass
                        if not keep_going:
                            c.fatal = True
                        traceback.print_exc()
            finally:
                browser.close()
    finally:
        srv.stop()
        if c.project_dir:
            shutil.rmtree(c.project_dir, ignore_errors=True)
        shutil.rmtree(home, ignore_errors=True)
    free = not port_in_use()
    c.steps.append(Step("13 servidor parado e porta livre", "passed" if free else "failed", f"porta {PORT} livre={free}"))
    return c.steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--stop-on-fail", action="store_true")
    a = ap.parse_args()
    steps = run_all(a.out, keep_going=not a.stop_on_fail, headless=not a.headed)
    for s in steps:
        print(f"[{s.status.upper():7}] {s.name}\n          {s.evidence}")
    return 0 if all(s.status in ("passed", "skipped") for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
