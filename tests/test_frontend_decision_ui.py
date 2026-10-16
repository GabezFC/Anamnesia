"""UI do Decision Engine (#/decision): guardas estáticas + helpers puros e render em node + i18n PT/EN."""
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
PAGES = ["decision.js", "decision-ui.js", "decision-eval.js", "decision-data.js"]


def read(rel: str) -> str:
    return (FRONT / rel).read_text(encoding="utf-8")


def _run(code: str) -> str:
    stub = ("globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };"
            "globalThis.window = globalThis; globalThis.addEventListener = () => {}; globalThis.dispatchEvent = () => true; globalThis.CustomEvent = class {};"
            "globalThis.document = { documentElement: { setAttribute() {} }, addEventListener() {} };")
    r = subprocess.run([NODE, "--input-type=module", "-e", stub + code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1]


def _url(rel: str) -> str:
    return "file:///" + (FRONT / rel).as_posix()


def test_route_nav_palette_css_are_wired_without_polluting_sidebar():
    app = read("js/app.js")
    assert "'#/decision'" in app and "decisionPage" in app
    # a navegação principal continua com 5 itens; Decision Engine fica no grupo recolhível "Avançado"
    assert re.findall(r'href="#/(\w+)" class="nav-item', app) == ["workspace", "connections", "config", "costs", "memory"]
    assert 'href="#/decision"' in app and "toggle-nav-advanced" in app and "aria-expanded" in app
    cmds = read("js/app-commands.js")
    assert "'#/decision'" in cmds and "goDecision" in cmds
    shortcuts = re.findall(r"'(Alt\+Shift\+\d)'", cmds)
    assert len(shortcuts) == len(set(shortcuts)), "atalho duplicado"
    assert "/static/css/pages/decision.css" in read("index.html")
    assert (FRONT / "css/pages/decision.css").is_file()


def test_page_has_apg_tabs_and_reuses_shared_pieces():
    d = read("js/pages/decision.js")
    assert 'role="tablist"' in d and 'role="tab"' in d and 'role="tabpanel"' in d
    assert "handleTablistKey" in d and "aria-selected" in d and "aria-controls" in d
    assert all(t in d for t in ("overview", "evaluation", "history", "calibration", "laya"))
    assert "registerCommand" in d and "unregisterCommand" in d
    ui = read("js/pages/decision-ui.js")
    assert "emptyState" in ui and "skeletonKpis" in ui and "skeletonTable" in ui


def test_csp_safe_and_escaped():
    for f in PAGES:
        s = read(f"js/pages/{f}")
        assert not re.search(r"\son[a-z]+=\"", s), f"handler inline em {f}"
        assert 'style="' not in s, f"style inline em {f}"
        assert "eval(" not in s and "new Function" not in s
    for f in ("decision-eval.js", "decision.js"):
        assert read(f"js/pages/{f}").count("esc(") > 40


def test_read_only_no_write_routes_and_no_fake_numbers():
    api = read("js/anamnesia-api.js")
    block = api[api.index("decision engine"):]
    assert all(r in block for r in ("/api/decision/status", "/api/decision/config", "/api/decision/metrics",
                                    "/api/decision/evaluation", "/api/decision/history"))
    assert "'POST'" not in block and "'PUT'" not in block and "'PATCH'" not in block
    allsrc = "".join(read(f"js/pages/{f}") for f in PAGES)
    texts = re.sub(r"/\*.*?\*/", "", read("js/i18n-decision.js"), flags=re.S)
    assert not re.search(r"(?i)operational|operacional", texts), "'Operational' sem health real"
    assert "Math.random" not in allsrc
    assert "dec-advanced" in allsrc and "localStorage" in allsrc


def test_css_uses_tokens_only():
    css = read("css/pages/decision.css")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "cor literal no CSS (use tokens)"
    assert "@media (max-width: 640px)" in css and "@media (max-width: 900px)" in css
    assert re.search(r"var\(--", css)


@NEEDS_NODE
@pytest.mark.parametrize("rel", [f"js/pages/{f}" for f in PAGES] + ["js/i18n-decision.js", "js/app.js", "js/app-commands.js"])
def test_node_check(rel):
    r = subprocess.run([NODE, "--check", str(FRONT / rel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _flat(x, p=""):
    out = set()
    for k, v in x.items():
        out |= _flat(v, f"{p}{k}.") if isinstance(v, dict) else {f"{p}{k}"}
    return out


@NEEDS_NODE
def test_i18n_pt_en_same_keys_merged_and_all_used_keys_exist():
    out = subprocess.run([NODE, "--input-type=module", "-e",
                          f"import {{ DECISION_I18N as M }} from '{_url('js/i18n-decision.js')}'; console.log(JSON.stringify(M))"],
                         capture_output=True, text=True, check=True)
    d = json.loads(out.stdout)
    assert _flat(d["pt"]) == _flat(d["en"]) and len(_flat(d["pt"])) > 150
    for lang in ("pt", "en"):
        st = d[lang]["decision"]["state"]
        assert set(st) == {"KEEP", "REVIEW", "DROP", "BLOCKED", "FALLBACK", "UNCERTAIN"}
        assert set(d[lang]["decision"]["stateTip"]) == set(st), "todo estado precisa de tooltip"
        assert set(d[lang]["decision"]["label"]) == {"MEASURED", "ESTIMATED", "UNKNOWN"}
    # chaves usadas como t.ov.xxx / t.ev.xxx / t.hi.xxx / t.ca.xxx / t.la.xxx existem
    keys = _flat(d["pt"])
    src = "".join(read(f"js/pages/{f}") for f in PAGES)
    used = set(re.findall(r"\bt\.(ov|ev|hi|ca|la)\.([A-Za-z]+)\b", src))
    missing = [f"{a}.{b}" for a, b in used if not any(k.startswith(f"decision.{a}.{b}") for k in keys)]
    assert not missing, missing
    r = _run("const { I18N, setLang } = await import('" + _url("js/i18n.js") + "');"
             "const pt = I18N.decision.tabs.history; setLang('en'); console.log(JSON.stringify([pt, I18N.decision.tabs.history, I18N.nav.decision]));")
    pt, en, nav = json.loads(r)
    assert (pt, en) == ("Histórico", "History") and nav == "Decision Engine"


@NEEDS_NODE
def test_pure_helpers():
    r = _run(f"""
    const m = await import('{_url("js/pages/decision-data.js")}');
    const bench = {{ bench: {{ results: [
      {{name:'JEV-only (padrão)', precision:.8, recall:.9, f1:.86, jev_avoided_pct:0}},
      {{name:'Laya-only', f1:.48}}, {{name:'Laya→JEV', f1:.67}}, {{name:'JEV→Laya', f1:.86}}, {{name:'ensemble', f1:.49}}, {{name:'adaptive', f1:.62}}]}} }};
    const cols = m.evalColumns(bench, 'ensemble');
    const better = m.evalColumns({{bench:{{results:[{{name:'JEV-only (padrão)', f1:.5}},{{name:'Laya-only', f1:.9}}]}}}});
    const recs = Array.from({{length: 25}}, (_, i) => ({{ request_id:'r'+i, query_hash:'h'+i, project: i%2?'p':'', provider: i%2?'laya':'jev', op:'retrieval',
      decisions: i%5===0 ? {{QUARANTINE:1}} : {{KEEP:1, UNJUDGED: 1}}, fallbacks: i%3===0 ? 1 : 0, ts: i, latency_ms: 1, n_items: 2, calls:{{}} }}));
    const d = m.diagnoseLaya({{available:false, mode:'off', reason:"pacote 'laya' não importável neste Python", errors:0}});
    console.log(JSON.stringify({{
      s: [m.stateOf('QUARANTINE'), m.stateOf('UNJUDGED'), m.stateOf('KEEP', {{fallback:true}}), m.stateOf('???'), m.stateOf(null)],
      lab: [m.lab({{value:null,label:'MEASURED'}}).label, m.lab({{value:3,label:'ESTIMATED'}}).label, m.lab(5).label, m.lab(undefined).label],
      cols: cols.map(c => c.id + ':' + (c.data && c.data.name)),
      verdictNone: m.verdict(cols).kind, verdictBetter: m.verdict(better).better, verdictUnknown: m.verdict(m.evalColumns({{}})).kind,
      emptyCols: m.evalColumns({{}}).map(c => c.data),
      pg: [m.paginate(recs, 3, 10).rows.length, m.paginate(recs, 99, 10).page, m.paginate([], 1, 10).pages, m.paginate(recs,1,10).from],
      fq: m.filterHistory(recs, {{q:'H3'}}).length, fp: m.filterHistory(recs, {{provider:'laya'}}).length,
      fs: m.filterHistory(recs, {{state:'BLOCKED'}}).length, ff: m.filterHistory(recs, {{state:'FALLBACK'}}).length,
      sc: m.stateCounts(recs[0]),
      csv: m.historyToCsv([{{request_id:'=cmd', decisions:{{KEEP:2}}, project:'a,"b"'}}]).split('\\r\\n').slice(0,2),
      json: JSON.parse(m.historyToJson([{{request_id:'x', secret_text:'NAO', decisions:{{}}}}])),
      th: m.thresholdRows({{thresholds:{{laya:{{keep:.25,review:.1,min_confidence:.05}}, jev:{{keep:.7,review:.5,min_confidence:0}}}}}}).map(r=>r.id),
      diag: d.checks.map(c => c.id+':'+c.state), probs: d.problems, diagNull: m.diagnoseLaya(null).reachable,
      okLaya: m.diagnoseLaya({{available:true, mode:'inproc', reason:'pacote laya + pesos', errors:0}}).checks.map(c=>c.state),
      errKind: [m.errKind({{status:0}}), m.errKind({{status:503}}), m.errKind({{status:500}}), m.errKind(new Error('x'))],
      pageState: [m.pageState({{a:{{status:'ok'}}, b:{{status:'ok'}}}}), m.pageState({{a:{{status:'ok'}}, b:{{status:'error'}}}}),
        m.pageState({{a:{{status:'offline'}}, b:{{status:'offline'}}}}), m.pageState({{a:{{status:'offline'}}, b:{{status:'error'}}}}), m.pageState({{a:{{status:'loading'}}}})],
    }}));
    """)
    o = json.loads(r)
    assert o["s"] == ["BLOCKED", "UNCERTAIN", "FALLBACK", "UNCERTAIN", "UNCERTAIN"]   # desconhecido nunca vira KEEP
    assert o["lab"] == ["UNKNOWN", "ESTIMATED", "UNKNOWN", "UNKNOWN"]                 # nulo/cru nunca finge MEASURED
    assert o["cols"] == ["jev:JEV-only (padrão)", "laya:Laya-only", "hybrid:ensemble", "adaptive:adaptive"]
    assert o["verdictNone"] == "none" and o["verdictBetter"] == ["laya"] and o["verdictUnknown"] == "unknown"
    assert o["emptyCols"] == [None, None, None, None]
    assert o["pg"] == [5, 3, 1, 1]
    assert o["fq"] == 1 and o["fp"] == 12 and o["fs"] == 5 and o["ff"] == 9
    assert o["sc"] == {"BLOCKED": 1, "FALLBACK": 1}
    assert o["csv"][1].startswith("'=cmd") or o["csv"][1].split(",")[1] == "'=cmd"      # sem injeção de fórmula
    assert o["json"] == [{"request_id": "x", "decisions": {}}]                          # só campos permitidos
    assert o["th"] == ["jev", "laya"]
    assert o["diag"] == ["installed:fail", "checkpoint:unknown", "runtime:unknown", "device:unknown", "inference:unknown"]
    assert o["probs"] == ["notInstalled", "unavailable"] and o["diagNull"] is False
    assert o["okLaya"][:3] == ["ok", "ok", "ok"] and "unknown" in o["okLaya"]
    assert o["errKind"] == ["offline", "offline", "error", "error"]
    assert o["pageState"] == ["ok", "partial", "offline", "error", "loading"]


@NEEDS_NODE
def test_render_states_and_honesty():
    """Renderiza as abas com a loja em cada estado: nada de 'Operational', JEV real = não medido, escape de HTML."""
    r = _run(f"""
    const ui = await import('{_url("js/pages/decision-ui.js")}');
    const page = await import('{_url("js/pages/decision.js")}');
    const ev = await import('{_url("js/pages/decision-eval.js")}');
    const out = {{}};
    const html = () => ({{ ov: page.render(), eval: ev.evalTab.html(), hist: ev.historyTab.html() }});
    out.loading = html();
    const ok = (data) => ({{ status:'ok', data, error:'' }});
    ui.store.status = ok({{ active_provider:'jev', default_is_jev_only:true, providers:{{ jev:{{available:null, label:'UNKNOWN', configured:true}}, laya:{{available:false, label:'MEASURED', mode:'off', reason:'MG_LAYA_MODE=off'}} }}, cache:{{size:0,max_size:10}}, history:{{records:0}} }});
    ui.store.config = ok({{ provider:'jev', preset:null, thresholds:{{ laya:{{keep:.25,review:.1,min_confidence:.05}} }}, ensemble_weights:{{laya:.5,jev:.5}}, projects:{{}} }});
    ui.store.metrics = ok({{ requests:{{value:0,label:'MEASURED'}} }});
    ui.store.evaluation = ok({{ history:{{note:'vazio'}}, bench:null }});
    ui.store.history = ok({{ records:[{{request_id:'<img src=x onerror=alert(1)>', query_hash:'abc', provider:'laya', op:'memory', decisions:{{KEEP:1}}, fallbacks:0, n_items:1, latency_ms:1, cache_hits:0, ts:1}}], total:1 }});
    out.ok = html();
    ui.store.history = ok({{ records:[], total:0 }});
    out.empty = ev.historyTab.html();
    ui.store.status = {{ status:'offline', data:null, error:'' }}; ui.store.config = {{ status:'offline', data:null, error:'' }}; ui.store.metrics = {{ status:'offline', data:null, error:'' }};
    out.offline = page.render();
    ui.store.status = ok({{ active_provider:'jev', providers:{{}} }}); ui.store.config = {{ status:'error', data:null, error:'boom' }};
    out.partial = page.render();
    console.log(JSON.stringify(out));
    """)
    o = json.loads(r)
    assert "role=\"status\"" in o["loading"]["ov"] and "aria-busy" in o["loading"]["ov"]
    ov = o["ok"]["ov"]
    assert "PADRÃO" in ov and "Não sondado" in ov and "MG_LAYA_MODE=off" in ov and "nada medido" in ov.lower()
    assert not re.search(r"(?i)operational|operacional", json.dumps(o))
    assert "JEV real: não medido" in o["ok"]["eval"] or "Benchmark indisponível" in o["ok"]["eval"]
    assert "<img" not in o["ok"]["hist"], "texto do backend precisa passar por esc()"
    assert "&lt;img" in o["ok"]["hist"]
    assert "Nada medido ainda" in o["empty"]
    assert "Serviço local indisponível" in o["offline"]
    assert "Dados parciais" in o["partial"] and "boom" not in o["partial"].split("Dados parciais")[0]
    for name in ("Fast", "Balanced", "Quality"):
        assert name in ov
