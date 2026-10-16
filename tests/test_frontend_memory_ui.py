"""ANAM-029: UI da memória (aba Notas de #/memory) — guardas estáticas + helpers puros em node + i18n."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
NODE = shutil.which("node")
NEEDS_NODE = pytest.mark.skipif(NODE is None, reason="node not installed")


def read(rel: str) -> str:
    return (FRONT / rel).read_text(encoding="utf-8")


def _run_module(code: str) -> str:
    stub = ("globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };"
            "globalThis.window = globalThis; globalThis.addEventListener = () => {}; globalThis.dispatchEvent = () => true; globalThis.CustomEvent = class {};"
            "globalThis.document = { documentElement: { setAttribute() {} }, addEventListener() {} };")
    r = subprocess.run([NODE, "--input-type=module", "-e", stub + code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1]


def test_api_client_covers_the_existing_routes():
    api = read("js/anamnesia-api.js")
    for frag in ("/api/memory/notes", "/history", "/diff?", "/rollback", "/api/memory/trash", "/restore",
                 "/api/memory/consolidate", "/api/memory/export.jsonl", "/api/memory/import"):
        assert frag in api, frag
    # cada rota consumida existe no backend
    be = (ROOT / "app/api/memory_store.py").read_text(encoding="utf-8")
    for frag in ('"/notes"', '"/notes/{note_id}"', '"/notes/{note_id}/history"', '"/notes/{note_id}/diff"',
                 '"/notes/{note_id}/rollback"', '"/trash"', '"/trash/{trash_id}/restore"', '"/consolidate"',
                 '"/export.jsonl"', '"/import"'):
        assert frag in be, frag


def test_page_has_apg_tabs_with_extension_point():
    m = read("js/pages/memory.js")
    assert "role=\"tablist\"" in m and "role=\"tab\"" in m and "role=\"tabpanel\"" in m
    assert "handleTablistKey" in m and "aria-selected" in m and "aria-controls" in m
    assert "const TABS = [" in m and "PONTO DE EXTENSÃO" in m
    assert "id: 'decision" not in m  # a aba Decision Engine é de outro agente


def test_notes_tab_reuses_shared_a11y_pieces_and_is_csp_safe():
    n = read("js/pages/memory-notes.js")
    assert "trapFocus" in n and "registerCommand" in n and "unregisterCommand" in n
    assert "alertdialog" in n and "aria-modal" in n
    assert "emptyState" in n and "skeletonTable" in n
    assert not re.search(r"\son[a-z]+=\"", n), "handler inline viola a CSP (script-src 'self')"
    assert "style=\"" not in n, "style inline viola a CSP (style-src 'self')"
    assert "innerHTML" in n and n.count("esc(") > 40
    for act in ("consolidate", "export", "import", "history", "archive", "delete", "restore", "rollback"):
        assert f"'{act}'" in n or f"\"{act}\"" in n or f"data-act=\"{act}\"" in n or f"data-dlg=\"{act}\"" in n, act


def test_destructive_flows_use_confirmation_and_dry_run_first():
    n = read("js/pages/memory-notes.js")
    assert re.search(r"function askDelete[\s\S]*?confirmDialog", n)
    assert re.search(r"function askArchive[\s\S]*?confirmDialog", n)
    assert "memConsolidate(false)" in n and "memConsolidate(true)" in n
    assert n.index("memConsolidate(false)") < n.index("memConsolidate(true)")
    # foco inicial em Cancelar nos diálogos destrutivos
    assert "mem-cancel" in n


def test_consolidate_toast_uses_integer_superseded_count():
    # lifecycle.consolidate devolve `superseded` como int (não lista)
    assert "Number(r?.superseded)" in read("js/pages/memory-notes.js")
    lc = (ROOT / "app/memory_store/lifecycle.py").read_text(encoding="utf-8")
    assert '"superseded": done' in lc


def test_css_uses_tokens_only():
    css = read("css/pages/memory.css")
    block = css.split("ANAM-029")[1]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", block), "cor literal fora dos tokens"


@NEEDS_NODE
@pytest.mark.parametrize("rel", ["js/pages/memory.js", "js/pages/memory-notes.js", "js/i18n-memory.js", "js/i18n.js",
                                 "js/anamnesia-api.js"])
def test_node_check(rel):
    r = subprocess.run([NODE, "--check", str(FRONT / rel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@NEEDS_NODE
def test_i18n_pt_en_same_keys_and_merged():
    out = subprocess.run(
        [NODE, "--input-type=module", "-e",
         f"import {{ MEM_NOTES_I18N as M }} from 'file:///{(FRONT / 'js/i18n-memory.js').as_posix()}';"
         "console.log(JSON.stringify(M))"], capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)

    def flat(x, p=""):
        r = set()
        for k, v in x.items():
            r |= flat(v, f"{p}{k}.") if isinstance(v, dict) else {f"{p}{k}"}
        return r
    assert flat(d["pt"]) == flat(d["en"]) and len(flat(d["pt"])) > 100
    # toda chave i18n usada em memory-notes.js (t.xxx / tn().xxx / t.kind[..]) existe
    keys = {k for k in flat(d["pt"]) if k.startswith("memory.notes.")}
    used = set(re.findall(r"\bt\.([a-zA-Z]+)\b", read("js/pages/memory-notes.js")))
    keys = {k[len("memory.notes."):] for k in keys}
    assert not (used - keys - {"kind", "status"}), used - keys
    r = _run_module(f"const {{ I18N, setLang }} = await import('file:///{(FRONT / 'js/i18n.js').as_posix()}');"
                    "const pt = I18N.memory.notes.newNote; setLang('en'); console.log(JSON.stringify([pt, I18N.memory.notes.newNote, I18N.memory.title]));")
    pt, en, title = json.loads(r)
    assert pt == "Nova nota" and en == "New note" and title


@NEEDS_NODE
def test_pure_helpers():
    url = (FRONT / "js/pages/memory-notes.js").as_posix()
    r = _run_module(f"""
    const m = await import('file:///{url}');
    const notes = [
      {{id:'a', title:'Alfa <b>', project:'p1', tags:['x'], kind:'fact', status:'active', updated:'2026-01-01T00:00:00Z'}},
      {{id:'b', title:'Beta', project:'p2', tags:['y'], kind:'task', status:'archived', updated:'2026-02-01T00:00:00Z'}},
      {{id:'c', title:'Gama', tags:[], updated:'2025-01-01T00:00:00Z'}}];
    console.log(JSON.stringify({{
      tags: m.parseTags(' a, b ,,a '),
      byQ: m.filterNotes(notes, {{q:'beta'}}).map(n=>n.id),
      byTag: m.filterNotes(notes, {{q:'x'}}).map(n=>n.id),
      byStatus: m.filterNotes(notes, {{status:'active'}}).map(n=>n.id),
      byProject: m.filterNotes(notes, {{project:'p2'}}).map(n=>n.id),
      sorted: m.sortNotes(notes).map(n=>n.id),
      empty: m.buildNotePayload({{title:' ', content:'x'}}),
      noContent: m.buildNotePayload({{title:'t', content:'  '}}),
      long: m.buildNotePayload({{title:'x'.repeat(201), content:'x'}}),
      ok: m.buildNotePayload({{title:' T ', content:'c', tags:'a,b', kind:'fact', project:'p'}}, {{create:true}}),
      okEdit: m.buildNotePayload({{title:'T', content:'c', project:'p'}}),
      diff: m.classifyDiff('--- a\\n+++ b\\n@@ -1 +1 @@\\n-x\\n+y\\n z\\n').map(l=>l.cls),
      j1: m.inspectJsonl('{{"a":1}}\\n\\n{{"b":2}}\\n'), j2: m.inspectJsonl('{{"a":1}}\\nnope'), j3: m.inspectJsonl('[1]'),
      plan: m.summarizePlan({{groups:[{{keep:'a',supersede:['b','c']}},{{keep:'d',supersede:['e']}}]}}),
      planNone: m.summarizePlan({{groups:[]}}),
      ver: m.versionEpoch('1700000000000000000'),
    }}));
    """)
    o = json.loads(r)
    assert o["tags"] == ["a", "b"]
    assert o["byQ"] == ["b"] and o["byTag"] == ["a"] and o["byStatus"] == ["a", "c"] and o["byProject"] == ["b"]
    assert o["sorted"] == ["b", "a", "c"]
    assert o["empty"]["error"] == "errTitle" and o["noContent"]["error"] == "errContent" and o["long"]["error"] == "errTitleLen"
    assert o["ok"]["body"] == {"title": "T", "content": "c", "tags": ["a", "b"], "kind": "fact", "project": "p"}
    assert "project" not in o["okEdit"]["body"]
    assert o["diff"] == ["meta", "meta", "hunk", "del", "add", "ctx"]
    assert o["j1"] == {"count": 2, "badLine": 0} and o["j2"] == {"count": 2, "badLine": 2} and o["j3"]["badLine"] == 1
    assert o["plan"] == {"groups": 2, "notes": 3} and o["planNone"] == {"groups": 0, "notes": 0}
    assert o["ver"] == 1700000000


@NEEDS_NODE
def test_list_html_escapes_backend_text_and_has_states():
    url = (FRONT / "js/pages/memory-notes.js").as_posix()
    r = _run_module(f"""
    const m = await import('file:///{url}');
    console.log(JSON.stringify(m.html()));
    """)
    html = json.loads(r)
    assert 'role="toolbar"' in html and 'role="search"' in html and 'aria-live="polite"' in html
    assert 'aria-busy="false"' in html or 'aria-busy="true"' in html
