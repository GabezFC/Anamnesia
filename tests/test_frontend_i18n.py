"""Static checks for the PT-BR/EN i18n helper (frontend/js/i18n.js). Needs node to evaluate the module."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "frontend" / "js"
I18N_USERS = ["pages-workspace.js", "pages-connections.js", "pages-orchestration.js", "pages-anacosts.js",
              "terminals.js", "shell-extras.js"]
node = shutil.which("node")
needs_node = pytest.mark.skipif(not node, reason="node not installed")


def _dicts() -> dict:
    code = f"import('{(JS / 'i18n.js').as_uri()}').then(m => console.log(JSON.stringify(m.DICT)))"
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _node_eval(body: str) -> str:
    code = ("const store = {}; globalThis.localStorage = { getItem: k => (k in store ? store[k] : null), "
            "setItem: (k, v) => { store[k] = String(v); } };\n"
            f"import('{(JS / 'i18n.js').as_uri()}').then(m => {{ {body} }})")
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@needs_node
def test_pt_and_en_have_identical_keys():
    d = _dicts()
    assert set(d["pt"]) == set(d["en"]), sorted(set(d["pt"]) ^ set(d["en"]))
    assert len(d["pt"]) > 100


@needs_node
def test_placeholders_match_and_values_nonempty():
    d = _dicts()
    for k, pt in d["pt"].items():
        en = d["en"][k]
        assert pt.strip() and en.strip(), k
        assert sorted(re.findall(r"\{(\w+)\}", pt)) == sorted(re.findall(r"\{(\w+)\}", en)), k


@needs_node
def test_every_key_used_in_code_exists():
    d = _dicts()["pt"]
    used: set[str] = set()
    for name in I18N_USERS:
        src = (JS / name).read_text(encoding="utf-8")
        assert "./i18n.js" in src, f"{name} does not use the i18n helper"
        used |= set(re.findall(r"\b(?:tx|t)\(\s*'([a-z]{2,4}\.[\w.]+)'", src))
    used |= set(re.findall(r"\b(?:tx|t)\(\s*'([a-z]{2,4}\.[\w.]+)'", (JS / "i18n.js").read_text(encoding="utf-8")))
    missing = sorted(k for k in used if k not in d)
    assert not missing, missing
    assert len(used) > 80


@needs_node
def test_default_is_pt_toggle_persists_and_falls_back():
    assert _node_eval("console.log(m.getLang(), m.t('ws.newTerm'))") == "pt + Terminal"
    out = _node_eval("m.setLang('en'); console.log(m.getLang(), localStorage.getItem(m.LS_LANG), m.t('ws.newTerm'))")
    assert out == "en en + Terminal"
    assert _node_eval("m.setLang('en'); console.log(m.t('ws.msg.added', {n: 'X'}))") == "Project \u201cX\u201d added."
    assert _node_eval("m.setLang('xx'); console.log(m.getLang())") == "pt"
    assert _node_eval("console.log(m.t('no.such.key'))") == "no.such.key"


def test_no_leftover_portuguese_literals_in_translated_ui_strings():
    """Spot-check strings that used to be hard-coded PT in the translated modules."""
    leftovers = {
        "pages-workspace.js": ["Backend do Workspace ainda", "Nenhum projeto ainda", "Escolha um projeto", "Painel vazio"],
        "pages-connections.js": ["Nenhuma conexão cadastrada", "Digite a chave antes", "Testando…"],
        "pages-orchestration.js": ["Backend de orquestração ainda", "Execuções recentes", "Sem detalhe de papéis"],
        "pages-anacosts.js": ["Tarefas por dificuldade", "Estratégias (origem", "matriz indisponível"],
        "terminals.js": ["não foi possível carregar"],
        "shell-extras.js": ["Avisos do servidor", "Nenhum comando", "Paleta de comandos"],
    }
    for name, needles in leftovers.items():
        src = (JS / name).read_text(encoding="utf-8")
        for n in needles:
            assert n not in src, f"{name} still hard-codes {n!r}"


def test_language_toggle_is_installed_in_the_shell():
    app = (JS / "app.js").read_text(encoding="utf-8")
    assert "installLangToggle" in app
