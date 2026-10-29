"""E2E de Conexões (servidor real + Chromium) em instalação limpa: digitar, salvar, reiniciar, remover, falha.

    <python com playwright> scripts/e2e_connections.py [--python <python do servidor>]

Isolado: ANAMNESIA_HOME = diretório temporário novo (token/.env descartáveis), porta própria (8765).
Segredo usado é fictício e nunca é impresso. Sai com código 1 se algum passo falhar.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
FAKE = "sk-ant-TESTE-0000000000000000abcd"
results: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, ev: str = "") -> None:
    results.append((name, ok, ev))
    print(("PASSOU  " if ok else "FALHOU  ") + name + (f" — {ev}" if ev else ""), flush=True)


class Server:
    def __init__(self, python: str, home: Path):
        self.python, self.home, self.proc = python, home, None

    def start(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("ANAMNESIA_ALLOW_NETWORK_TEST", "ANTHROPIC_API_KEY",
                                                                  "OPENAI_API_KEY", "OPENROUTER_API_KEY", "MG_PORT")}
        env.update(PORT=str(PORT), ANAMNESIA_HOME=str(self.home), PYTHONUTF8="1",
                   MEMORY_GATEWAY_VAULT=str(ROOT / "data" / "synthetic_vault"))
        log = open(self.home / "server.log", "wb")
        self.proc = subprocess.Popen([self.python, "-m", "app.main"], cwd=str(ROOT), env=env, stdout=log,
                                     stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 90:
            try:
                with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("servidor não ficou saudável")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
            else:
                self.proc.kill()
            self.proc.wait(timeout=15)
        time.sleep(1)


def open_keys(page):
    page.goto(f"{BASE}/#/config", wait_until="load")
    page.wait_for_selector("[data-tab='keys']", timeout=20000)
    page.click("[data-tab='keys']")
    page.wait_for_selector("input[data-env-key]", timeout=20000)


def card(page, cid: str):
    return page.locator(f".connection-card[data-connection-id='{cid}']")


def state(page, cid: str) -> str:
    return card(page, cid).locator("[data-bind=connection-state]").first.get_attribute("data-state")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=str(ROOT / ".venv" / "Scripts" / "python.exe"))
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    home = Path(tempfile.mkdtemp(prefix="anam_conn_"))
    srv = Server(args.python, home)
    try:
        srv.start()
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            ctx = br.new_context()
            page = ctx.new_page()
            page.add_init_script("""() => {}""")
            open_keys(page)

            # 1) clone limpo: nada conectado, nada configurado
            states = page.eval_on_selector_all(".connection-card [data-bind=connection-state]",
                                               "els => els.map(e => e.dataset.state)")
            step("clone limpo: nenhum cartão 'connected'/'configured'",
                 bool(states) and not any(s in ("connected", "configured", "testing") for s in states), str(sorted(set(states))))
            ls = page.evaluate("JSON.stringify({...localStorage})")
            step("clone limpo: localStorage sem conexões falsas", "connected" not in ls.lower() or "online" not in ls.lower())

            # 2) campos dos agentes são editáveis (regressão: readonly/disabled)
            for cid in ("claude-code", "hermes", "codex"):
                inp = card(page, cid).locator("input[data-env-key]").first
                ok = inp.count() == 1 and inp.is_enabled() and inp.is_editable()
                if ok:
                    inp.click(); inp.fill(""); inp.type("abc123")
                    ok = inp.input_value() == "abc123"
                    inp.fill("")
                step(f"digitar no campo de chave de {cid}", ok)

            # 3) digitação sobrevive a re-render assíncrono
            inp = card(page, "claude-code").locator("input[data-env-key]").first
            inp.click(); inp.type("PARCIAL")
            card(page, "codex").locator("[data-action=test-connection]").first.click()  # força re-render assíncrono
            time.sleep(2)
            step("digitação preservada após refresh de status", card(page, "claude-code").locator("input[data-env-key]").first.input_value() == "PARCIAL")
            card(page, "claude-code").locator("input[data-env-key]").first.fill("")

            # 4) salvar vazio -> erro útil; salvar -> mascarado, estado 'configurado'
            card(page, "claude-code").locator("[data-action=save-key]").first.click()
            page.wait_for_timeout(500)
            body = page.inner_text("body")
            step("salvar vazio mostra erro útil", "Informe a chave" in body)
            inp = card(page, "claude-code").locator("input[data-env-key]").first
            inp.fill(FAKE)
            card(page, "claude-code").locator("[data-action=save-key]").first.click()
            page.wait_for_function("(c) => document.querySelector(`.connection-card[data-connection-id='${c}'] [data-bind=connection-state]`)"
                                   "?.dataset.state !== 'not_configured'", arg="claude-code", timeout=10000)
            dom = page.content()
            val = card(page, "claude-code").locator("input[data-env-key]").first.input_value()
            leak = FAKE in dom or FAKE in val or FAKE in page.evaluate("JSON.stringify({...localStorage,...sessionStorage})")
            step("salvar: estado configurado, segredo não vaza no DOM/storage", not leak and state(page, "claude-code") in ("configured", "unavailable"),
                 state(page, "claude-code"))
            ph = card(page, "claude-code").locator("input[data-env-key]").first.get_attribute("placeholder") or ""
            step("chave mascarada na UI (termina com abcd)", ph.endswith("abcd") and FAKE not in ph, "")

            # 5) testar offline -> nunca 'connected' por chave
            card(page, "claude-code").locator("[data-action=test-connection]").first.click()
            page.wait_for_timeout(2500)
            step("testar sem rede liberada não vira 'connected' pela chave", state(page, "claude-code") != "connected", state(page, "claude-code"))
            ant = card(page, "anthropic")
            if ant.count():
                ant.locator("input[data-env-key]").first.fill(FAKE)
                ant.locator("[data-action=save-key]").first.click()
                page.wait_for_timeout(800)
                ant.locator("[data-action=test-connection]").first.click()
                page.wait_for_timeout(2000)
                step("modelo com chave e teste offline = 'configured' (não conectado)", state(page, "anthropic") == "configured", state(page, "anthropic"))

            # 6) persiste após reiniciar o servidor
            ctx.close(); srv.stop(); srv.start()
            ctx = br.new_context(); page = ctx.new_page(); open_keys(page)
            step("reiniciar: chave persiste (configured) e nada 'connected'",
                 state(page, "claude-code") in ("configured", "unavailable") and state(page, "anthropic") == "configured",
                 f"{state(page, 'claude-code')}/{state(page, 'anthropic')}")

            # 7) remover
            card(page, "claude-code").locator("[data-action=remove-key]").first.click()
            page.wait_for_timeout(1500)
            step("remover: volta a 'não configurado'", state(page, "claude-code") in ("not_configured", "unavailable"), state(page, "claude-code"))
            # ANTHROPIC_API_KEY é compartilhada entre claude-code e anthropic: remover em um limpa nos dois
            step("remover chave compartilhada: modelo também 'não configurado'", state(page, "anthropic") == "not_configured", state(page, "anthropic"))

            # 8) falha: backend recusa gravação -> erro visível
            page.route("**/api/connections/*/secret", lambda r: r.fulfill(status=500, content_type="application/json",
                                                                         body='{"detail":"falha simulada"}'))
            inp = card(page, "anthropic").locator("input[data-env-key]").first
            inp.fill(FAKE)
            card(page, "anthropic").locator("[data-action=save-key]").first.click()
            page.wait_for_timeout(1000)
            step("falha de gravação mostra erro e mantém 'não configurado'",
                 "falha simulada" in page.inner_text("body").lower() and state(page, "anthropic") == "not_configured")
            br.close()
    except Exception as e:  # noqa: BLE001
        step("execução", False, f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        srv.stop()
        envf = home / ".env"
        if envf.exists() and FAKE in envf.read_text(errors="ignore"):
            step("segredo restante no .env temporário após remover", False)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passos OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
