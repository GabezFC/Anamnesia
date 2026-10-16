"""ANAM-027/028: E2E de teclado (Playwright) contra o servidor de dev. Uso: ANAMNESIA_HOME=<tmp> PORT=8765 python -m app.main; python scripts/e2e_a11y_keyboard.py (BASE em :8765, nunca :8000)."""
import json, sys, os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765/"
OUT = os.environ.get("A11Y_OUT", "./a11y_shots")
import os; os.makedirs(OUT, exist_ok=True)
res = []

def check(name, cond, extra=""):
    res.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name, extra)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1366, "height": 800})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "favicon" not in m.text else None)
    pg.goto(BASE + "#/workspace"); pg.wait_for_selector("#main-content", timeout=15000); pg.wait_for_timeout(800)
    check("title workspace", "Anamnésia" in pg.title() and pg.title().startswith("Workspace"), pg.title())

    # --- Palette
    pg.evaluate("document.querySelector('#main-content').dataset.marker='keep'")
    pg.keyboard.press("Control+k"); pg.wait_for_selector("#palette-root [role=dialog]")
    check("Ctrl+K não re-renderiza o app", pg.evaluate("document.querySelector('#main-content').dataset.marker") == "keep")
    check("palette em #palette-root fora de #app", pg.evaluate("!document.getElementById('app').contains(document.getElementById('palette-root'))"))
    check("input focado + role=combobox", pg.evaluate("document.activeElement.getAttribute('role')") == "combobox")
    check("#app inert", pg.evaluate("document.getElementById('app').inert") is True)
    n = pg.locator("#palette-root [role=option]").count()
    check("opções role=option", n >= 7, str(n))
    check("sem dicas fantasma (#1 / Ctrl+T)", "Ctrl+T" not in pg.inner_text("#palette-root") and "#1" not in pg.inner_text("#palette-root"))
    pg.screenshot(path=f"{OUT}/01_palette_open.png")
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowDown")
    ad = pg.evaluate("document.activeElement.getAttribute('aria-activedescendant')")
    check("ArrowDown move aria-activedescendant", ad == "palette-opt-2", ad)
    pg.keyboard.press("End"); check("End -> última", pg.evaluate("document.activeElement.getAttribute('aria-activedescendant')") == f"palette-opt-{n-1}")
    pg.keyboard.press("Home"); check("Home -> primeira", pg.evaluate("document.activeElement.getAttribute('aria-activedescendant')") == "palette-opt-0")
    live = pg.inner_text("[data-bind=palette-live]")
    check("aria-live conta resultados", "resultados" in live, live)
    # focus trap: Tab fica dentro
    for _ in range(4): pg.keyboard.press("Tab")
    check("focus trap (Tab)", pg.evaluate("document.getElementById('palette-root').contains(document.activeElement)"))
    pg.keyboard.type("custos")
    check("filtro", pg.locator("#palette-root [role=option]").count() == 1)
    pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    check("Enter navega para #/costs", pg.evaluate("location.hash") == "#/costs", pg.evaluate("location.hash"))
    check("palette fechou", pg.locator("#palette-root [role=dialog]").count() == 0)
    check("title costs", pg.title().startswith("Custos"), pg.title())
    check("foco no conteúdo após navegação", pg.evaluate("document.activeElement.id") == "main-content", pg.evaluate("document.activeElement.id"))
    # Esc + retorno de foco
    pg.goto(BASE + "#/config"); pg.wait_for_selector(".config-tabs-nav")
    pg.focus("[data-action=toggle-theme]") if pg.locator("[data-action=toggle-theme]").count() else None
    trig = pg.evaluate("document.activeElement.outerHTML.slice(0,60)")
    pg.keyboard.press("Control+k"); pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("Esc fecha e devolve foco ao gatilho", pg.evaluate("document.activeElement.outerHTML.slice(0,60)") == trig, trig)
    # Atalho global Alt+Shift+4
    pg.keyboard.press("Alt+Shift+4"); pg.wait_for_timeout(400)
    check("atalho Alt+Shift+4 -> #/costs", pg.evaluate("location.hash") == "#/costs")
    # guarda de contexto: Alt+Shift+1 dentro de input não dispara
    pg.keyboard.press("Control+k"); pg.keyboard.press("Alt+Shift+1"); pg.wait_for_timeout(300)
    check("atalho não-Ctrl ignorado em campo editável", pg.evaluate("location.hash") == "#/costs")
    pg.keyboard.press("Escape")
    # Theme toggle via palette
    pg.keyboard.press("Control+k"); pg.keyboard.type("tema"); pg.keyboard.press("Enter"); pg.wait_for_timeout(300)
    check("tema alterna via paleta", pg.evaluate("document.documentElement.dataset.theme") == "dark")
    pg.screenshot(path=f"{OUT}/02_dark_costs.png")
    pg.keyboard.press("Control+k"); pg.keyboard.type("tema"); pg.keyboard.press("Enter"); pg.wait_for_timeout(300)

    # --- Config tabs (APG)
    pg.goto(BASE + "#/config"); pg.wait_for_selector(".config-tabs-nav"); pg.wait_for_timeout(600)
    check("title config", pg.title().startswith("Configuração"), pg.title())
    tabs = pg.locator("[role=tab]")
    check("tabs com aria-controls + tabpanel", tabs.count() == 7 and pg.locator("[role=tabpanel]").count() == 1 and pg.evaluate("document.querySelector('[role=tab]').getAttribute('aria-controls')") == "config-panel")
    pg.focus("[role=tab][aria-selected=true]")
    pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
    sel = pg.evaluate("document.activeElement.dataset.tab")
    check("ArrowRight ativa próxima aba e mantém foco", sel == "general" and pg.evaluate("document.activeElement.getAttribute('aria-selected')") == "true", sel)
    check("roving tabindex", pg.locator("[role=tab][tabindex='0']").count() == 1 and pg.locator("[role=tab][tabindex='-1']").count() == 6)
    check("tabpanel labelledby", pg.evaluate("document.querySelector('[role=tabpanel]').getAttribute('aria-labelledby')") == "config-tab-general")
    pg.keyboard.press("End"); pg.wait_for_timeout(200)
    check("End -> última aba", pg.evaluate("document.activeElement.dataset.tab") == "active")
    pg.keyboard.press("Home"); pg.wait_for_timeout(200)
    check("Home -> primeira aba", pg.evaluate("document.activeElement.dataset.tab") == "subagents")
    pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(200)
    check("ArrowLeft cicla", pg.evaluate("document.activeElement.dataset.tab") == "active")
    pg.keyboard.press("Home"); pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
    pg.screenshot(path=f"{OUT}/03_config_tabs.png")
    for tid in ("gateway",):
        pg.click(f"[data-tab={tid}]"); pg.wait_for_timeout(300)
        unl = pg.evaluate("[...document.querySelectorAll('.input-label')].filter(l=>!l.htmlFor && !l.querySelector('input,select,textarea') && l.closest('.input-group') && l.closest('.input-group').querySelector('input,select,textarea')).length")
        check("labels da aba gateway com for=", unl == 0, str(unl))

    # --- Workspace
    pg.goto(BASE + "#/workspace"); pg.wait_for_timeout(1500)
    check("projetos são <button> (ou lista vazia)", pg.locator("div.project-item").count() == 0)
    if pg.locator("button.project-item").count():
        pg.focus("button.project-item >> nth=0"); pg.keyboard.press("Enter"); pg.wait_for_timeout(300)
        check("Enter ativa projeto, foco preservado", pg.evaluate("document.activeElement.classList.contains('project-item')"))
    pg.screenshot(path=f"{OUT}/04_workspace.png")
    # modal de projeto
    if pg.locator("[data-action=open-add-project]").count():
        pg.focus("[data-action=open-add-project] >> nth=0"); pg.keyboard.press("Enter"); pg.wait_for_selector(".modal-dialog")
        check("modal: foco no input nome", pg.evaluate("document.activeElement.id") == "new-project-name", pg.evaluate("document.activeElement.id"))
        check("modal: labels for=", pg.evaluate("document.querySelector('label[for=new-project-name]') && document.querySelector('label[for=new-project-path]') && true"))
        for _ in range(8): pg.keyboard.press("Tab")
        check("modal: focus trap", pg.evaluate("!!document.activeElement.closest('.modal-dialog')"))
        pg.screenshot(path=f"{OUT}/05_modal.png")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        check("modal: Esc fecha", pg.locator(".modal-dialog").count() == 0)
        check("modal: foco retorna ao gatilho", pg.evaluate("document.activeElement.getAttribute('data-action')") == "open-add-project", pg.evaluate("document.activeElement.outerHTML.slice(0,80)"))
    # terminal tabs (precisa de sessão): verificar estrutura se existir
    check("sem div role=tab", pg.locator("div[role=tab]").count() == 0)
    # --- Lab charts
    pg.goto(BASE + "#/compare/overview"); pg.wait_for_timeout(2500)
    check("title lab", pg.title().startswith("Laborat") or pg.title().startswith("Comparison"), pg.title())
    pg.screenshot(path=f"{OUT}/06_lab.png")
    pg.goto(BASE + "#/costs"); pg.wait_for_timeout(2500)
    det = pg.locator(".chart-data-details")
    print("chart details on costs:", det.count(), "marks:", pg.locator(".chart-point, .chart-bar").count())
    pg.screenshot(path=f"{OUT}/07_costs.png")
    check("sem erros JS", not errs, "; ".join(errs[:3]))
    b.close()
json.dump(res, open(OUT + "/result.json", "w"), ensure_ascii=False)
print(sum(1 for r in res if r[1]), "/", len(res))
sys.exit(0 if all(r[1] for r in res) else 1)
