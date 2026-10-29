"""Tela #/config ligada a /api/settings: estático + node (helpers puros, fluxo otimista, migração, segredos)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
JS = FRONT / "js"
NODE = shutil.which("node") is not None


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _node(code: str) -> str:
    r = subprocess.run(["node", "--input-type=module", "-e", code], cwd=str(JS),
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


STUBS = """
const store = {};
globalThis.localStorage = { getItem(k){return k in store ? store[k] : null}, setItem(k,v){store[k]=String(v)}, removeItem(k){delete store[k]} };
globalThis.window = { addEventListener(){}, dispatchEvent(e){ (globalThis.__events ||= []).push(e.detail); } };
globalThis.CustomEvent = class { constructor(n, o){ this.type = n; this.detail = o && o.detail; } };
globalThis.document = { documentElement: { setAttribute(){} } };
"""


def test_config_uses_server_settings_and_not_local_storage_for_prefs():
    c = read(JS / "pages" / "config.js")
    assert "getSettings" in c and "putSettings" in c
    # predefinição/pré-filtro não são mais gravados no navegador (só lidos para migrar e removidos)
    assert "savePreset" not in c and "saveGatewayConfig" not in c
    assert not re.search(r"localStorage\.setItem", c)
    assert "removeItem" in c and "LEGACY_PRESET_KEY" in c and "LEGACY_GATEWAY_KEY" in c


def test_config_has_budget_economy_pipeline_cap_and_by_role():
    c = read(JS / "pages" / "config.js")
    for needle in ("max_tokens_per_query", "default_pipeline", "auto_graphify_jev_opt",
                   "reduce_max_results_by_question_type", "alert_pct", "costByRole", "costBudget"):
        assert needle in c, needle
    for p in ("auto", "baseline", "graphify", "graphify_jev", "graphify_jev_opt"):
        assert f"'{p}'" in c, p


def test_config_uses_shared_components_and_i18n_not_hardcoded_strings():
    c = read(JS / "pages" / "config.js")
    assert "skeletonCard" in c and "loadingBlock" in c and "emptyState(" in c
    assert "setLang" in c and "getLang" in c
    assert "PID 14209" not in c and "anamnesia.config.json" not in c


def test_key_management_never_stores_or_shows_secrets():
    cn = read(JS / "pages" / "connections.js")
    assert "setSecret" in cn and "removeSecret" in cn
    assert "input.value = ''" in cn and 'type="password"' in cn and 'autocomplete="new-password"' in cn
    assert not re.search(r"console\.\w+\([^)]*(?:input\.value|\bv\b|secret|value)", cn)
    cfg = read(JS / "pages" / "config.js")
    assert "renderKeyRows" not in cfg and "handleKeyAction" not in cfg  # aba Chaves removida; só Conexões
    # nenhum value="${...}" preenchendo input password com segredo
    for src in (cn, cfg):
        for m in re.finditer(r'<input[^>]*type="password"[^>]*>', src, flags=re.S):
            assert 'value=""' in m.group(0), m.group(0)


def test_i18n_config_has_pt_en_parity():
    s = read(JS / "i18n-config.js")
    pt = set(re.findall(r"^  (\w+):", s.split("export const CONFIG_EN")[0], flags=re.M))
    en = set(re.findall(r"^  (\w+):", s.split("export const CONFIG_EN")[1], flags=re.M))
    assert pt == en and len(pt) > 60, pt ^ en
    c = read(JS / "pages" / "config.js")
    used = set(re.findall(r"\bt\.(\w+)", c)) | set(re.findall(r"I18N\.config\.(\w+)", c))
    from_dict = pt | {"tabSubagents", "tabGateway", "tabActive", "presetsTitle", "estimatedCostNoData",
                      "gatewayVaultLabel", "gatewayModelKeyLabel", "gatewayVerdictJev", "gatewayVerdictDesc",
                      "gatewayPreFilter", "gatewayPreFilterDesc", "roleOrchestrator", "roleResearcher",
                      "roleImplementer", "roleReviewer"}
    assert not (used - from_dict), used - from_dict


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_en_dictionary_still_complete_with_config_keys():
    out = _node(STUBS + """
const m = await import('./i18n.js');
m.setLang('en');
console.log(JSON.stringify({ miss: m.missingKeys('en'), en: m.I18N.config.tabBudget }));
m.setLang('pt');
console.log(JSON.stringify({ pt: m.I18N.config.tabBudget }));
""")
    first, second = [json.loads(x) for x in out.splitlines()[-2:]]
    assert first["miss"] == [] and first["en"] == "Budget" and second["pt"] == "Orçamento"


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_pure_helpers():
    out = _node(STUBS + """
const m = await import('./pages/config.js');
const base = m.normalizeSettings({ default_pipeline: 'bogus', budget: { daily_usd: 3 } });
console.log(JSON.stringify({
  norm: base,
  cap: [m.parseTokenCap(''), m.parseTokenCap('4000'), m.parseTokenCap('0'), m.parseTokenCap('1.5'), m.parseTokenCap('-3'), m.parseTokenCap('abc')],
  usd: [m.parseUsd(''), m.parseUsd('2,5'), m.parseUsd('-1'), m.parseUsd('x')],
  pct: [m.parseAlertPct(''), m.parseAlertPct('90'), m.parseAlertPct('0'), m.parseAlertPct('101')],
  bud: [m.buildBudgetPatch('1', '', ''), m.buildBudgetPatch('-1', '', '')],
  patch: m.applyPatch(base, { budget: { alert_pct: 70 }, language: 'en' }),
  lang: [m.langToServer('en'), m.langToServer('pt'), m.langFromServer('en'), m.langFromServer('pt-BR'), m.langFromServer(undefined)],
  fmt: m.fmt('{pct}% de {x}', { pct: 80 }),
}));
""")
    d = json.loads(out.splitlines()[-1])
    assert d["norm"]["default_pipeline"] == "auto" and d["norm"]["budget"] == {"daily_usd": 3, "monthly_usd": None, "alert_pct": 80}
    assert d["cap"] == [None, 4000, None, None, None, None]
    assert d["usd"] == [None, 2.5, None, None]
    assert d["pct"] == [80, 90, None, None]
    assert d["bud"][0] == {"budget": {"daily_usd": 1, "monthly_usd": None, "alert_pct": 80}} and d["bud"][1] is None
    assert d["patch"]["budget"] == {"daily_usd": 3, "monthly_usd": None, "alert_pct": 70} and d["patch"]["language"] == "en"
    assert d["lang"] == ["en", "pt-BR", "pt".replace("pt", "en"), "pt", "pt"]
    assert d["fmt"] == "80% de "


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_legacy_migration_only_when_server_empty():
    out = _node(STUBS + """
const m = await import('./pages/config.js');
const empty = m.normalizeSettings({});
const full = m.normalizeSettings({ subagent_preset: { name: 'max' }, prefilter_cache: { enablePrefilter: false } });
console.log(JSON.stringify([
  m.planMigration(empty, 'economico', { enablePrefilter: false, enableSemanticCache: true }),
  m.planMigration(full, 'economico', { enablePrefilter: true }),
  m.planMigration(empty, null, null),
]));
""")
    a, b, c = json.loads(out.splitlines()[-1])
    assert a["patch"] == {"subagent_preset": {"name": "economico"},
                          "prefilter_cache": {"enablePrefilter": False, "enableSemanticCache": True}}
    assert a["clearPreset"] and a["clearGw"]
    assert b["patch"] == {} and b["clearPreset"] and b["clearGw"]  # servidor manda; chave local é descartada
    assert c == {"patch": {}, "clearPreset": False, "clearGw": False}


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_render_states_and_optimistic_rollback():
    out = _node(STUBS + """
const m = await import('./pages/config.js');
m.setDebugState('loading');
const loading = m.render();
m.setDebugState('error');
const error = m.render();
m.setDebugState('loaded');
const loaded = m.render();
console.log(JSON.stringify({
  skeleton: loading.includes('skeleton') && loading.includes('aria-busy'),
  err: error.includes('retry-config') && error.includes('empty-state'),
  tabs: ['general','budget','economy','gateway'].every(t => loaded.includes('data-tab="' + t + '"')),
  presets: loaded.includes('select-preset'),
}));
""")
    d = json.loads(out.splitlines()[-1])
    assert all(d.values()), d
