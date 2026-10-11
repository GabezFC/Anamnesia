"""Static + node guards for the Costs page wired to the backend (#/costs)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
COSTS = (FRONT / "js" / "pages" / "costs.js").read_text(encoding="utf-8")
API = (FRONT / "js" / "anamnesia-api.js").read_text(encoding="utf-8")
I18N_COSTS = (FRONT / "js" / "i18n-costs.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_all_endpoints_wired_with_range():
    for fn in ("costSummary", "costHourly", "costByRole", "costCallsRange", "costBudget", "putCostBudget"):
        assert re.search(rf"A\.{fn}\(", COSTS), fn
    assert "/api/costs/hourly" in API and "/api/costs/by-role" in API and "/api/costs/budget" in API
    assert "A.costSummary(range)" in COSTS and "A.costHourly(range)" in COSTS and "A.costByRole(range)" in COSTS
    assert "range, limit: PAGE_SIZE" in COSTS


def test_no_mock_data_left():
    assert "mock-data" not in COSTS and "mockCalls" not in COSTS and "mockBudget" not in COSTS


def test_period_filter_refetches():
    m = re.search(r"action === 'filter-period'.*?load\(\)", COSTS, re.S)
    assert m and "S.range = p" in m.group(0)


def test_budget_form_put_with_feedback():
    assert 'data-action="budget-form"' in COSTS
    assert "A.putCostBudget(body)" in COSTS and "daily_usd" in COSTS and "monthly_usd" in COSTS and "alert_pct" in COSTS
    assert "budgetSaved" in COSTS and "budgetSaveFail" in COSTS and 'role="progressbar"' in COSTS
    assert 'role="alert"' in COSTS and "r.d.alert || r.d.exceeded" in COSTS


def test_live_stream_with_polling_fallback_and_cleanup():
    assert "A.openCostStream(" in COSTS and "setInterval" in COSTS and "30000" in COSTS
    assert "setTimeout(() => { load({ silent: true }); }, DEBOUNCE_MS)" in COSTS
    unmount = COSTS[COSTS.index("export function unmount"):]
    assert "stopLive()" in unmount and "destroyWidgets()" in unmount
    stop = COSTS[COSTS.index("function stopLive"):COSTS.index("/* ---------------------------------------------------------------- views")]
    assert "stopStream()" in stop and "clearInterval" in stop and "clearTimeout" in stop


def test_virtual_table_cursor_skeleton_empty_state():
    assert "createVirtualTable(" in COSTS and "next_cursor" in COSTS and "cursor: S.nextCursor" in COSTS
    assert "skeletonKpis" in COSTS and "emptyState(" in COSTS
    assert "rolesTitle" in COSTS and "A.costByRole" in COSTS


def test_no_hardcoded_portuguese_in_costs_js():
    # texto de UI vem de I18N; só comentários podem ter PT
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", COSTS, flags=re.S)
    for word in ("Carregar", "Orçamento", "Nenhum", "Detalhes", "Exibindo", "Salvar", "Papel"):
        assert word not in code, word


def test_i18n_costs_pt_en_same_keys_and_used_keys_exist():
    if not NODE:
        pytest.skip("node ausente")
    script = f"""
import {{ COSTS_I18N as C }} from 'file:///{(FRONT / "js" / "i18n-costs.js").as_posix()}';
import {{ I18N }} from 'file:///{(FRONT / "js" / "i18n.js").as_posix()}';
console.log(JSON.stringify({{pt: Object.keys(C.pt).sort(), en: Object.keys(C.en).sort(), costs: Object.keys(I18N.costs)}}));
"""
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["pt"] == out["en"], "PT/EN com chaves diferentes"
    used = set(re.findall(r"t\.([A-Za-z0-9_]+)", COSTS))
    assert sorted(used - set(out["costs"])) == []


def test_node_syntax_and_pure_helpers():
    if not NODE:
        pytest.skip("node ausente")
    for f in ("js/pages/costs.js", "js/anamnesia-api.js", "js/i18n-costs.js", "js/i18n.js"):
        r = subprocess.run([NODE, "--check", str(FRONT / f)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{f}: {r.stderr}"
    script = f"""
import * as m from 'file:///{(FRONT / "js" / "pages" / "costs.js").as_posix()}';
const d = m.hourlyChartData([{{hour:'a',cost_usd:0.1}},{{hour:'b',cost_usd:0.25}},{{hour:'c',cost_usd:null}}]);
const c = m.normalizeCall({{run_id:'r1',created_at:10,cost_usd:{{value:0.5,origin:'estimated'}},context_tokens:{{value:7,origin:'measured'}}}});
console.log(JSON.stringify({{d, c}}));
"""
    r = subprocess.run([NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    import json
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert [p["cost"] for p in out["d"]] == [0.1, 0.35, 0.35]
    assert out["c"]["origin"] == "estimated" and out["c"]["cost"] == 0.5 and out["c"]["context_tokens"] == 7
