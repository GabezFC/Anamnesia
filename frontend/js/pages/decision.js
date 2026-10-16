/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * DECISION ENGINE (#/decision) — página com abas APG: Visão geral, Avaliação, Histórico, Calibração, Diagnóstico Laya.
 * Somente leitura (não há rota de escrita de config). JEV continua o padrão; Laya/híbridos são experimentais.
 * Rotas: GET /api/decision/{status,config,metrics,evaluation,history}.
 */
import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc, fmtNum, fmtNumber, fmtPct, fmtMs } from '../format.js';
import { handleTablistKey, tabId, panelId } from '../components/tabs.js';
import { registerCommand, unregisterCommand } from '../commands.js';
import { T, store, loadAll, gate, labelBadge, valueWithLabel, honestBanner } from './decision-ui.js';
import { evalTab, historyTab } from './decision-eval.js';
import { PROVIDERS, PRESET_IDS, PRESET_ENV, PRESET_PROVIDER, thresholdRows, diagnoseLaya, lab, isNum } from './decision-data.js';

const ADV_PREF = 'anamnesia.decision.advanced';
const ui = { advanced: false, tab: 'overview', copied: '' };
try { ui.advanced = localStorage.getItem(ADV_PREF) === '1'; } catch { /* storage indisponível: iniciante */ }

const cfg = () => store.config.data || null;
const stat = () => store.status.data || null;

/* ============================== Visão geral ============================== */
function activeProvider() {
  const s = stat(); const c = cfg();
  return (s && s.active_provider) || (c && c.provider) || null;
}

function activeCard() {
  const t = T().ov; const s = stat(); const c = cfg();
  const prov = activeProvider();
  if (!prov) return `<p class="dec-muted">${esc(T().ov.none)}</p>`;
  const isDefault = s ? s.default_is_jev_only === true : prov === 'jev';
  const strat = (s && s.active_strategy) || (prov === 'hybrid' && c ? c.strategy : null);
  const preset = c && c.preset;
  return `<dl class="dec-dl">
    <div><dt>${esc(t.activeProvider)}</dt><dd><strong>${esc(t.provider[prov] || prov)}</strong>
      ${isDefault ? `<span class="badge-seal badge-seal-verified">${icon('check', '', 12)} ${esc(t.standard)}</span>` : `<span class="badge-seal badge-seal-experimental">${icon('alertTriangle', '', 12)} ${esc(T().experimental)}</span>`}</dd></div>
    ${strat ? `<div><dt>${esc(t.activeStrategy)}</dt><dd><code>${esc(strat)}</code></dd></div>` : ''}
    <div><dt>${esc(t.presetActive)}</dt><dd>${preset ? `<strong>${esc(t.preset[preset] || preset)}</strong> <span class="badge-seal badge-seal-experimental">${esc(T().experimental)}</span>` : esc(t.noPreset)}</dd></div>
  </dl>
  <p class="dec-muted">${esc(isDefault ? t.defaultJev : t.notDefault)}</p>`;
}

function copyBtn(text) {
  const t = T();
  const done = ui.copied === text;
  return `<button type="button" class="btn btn-ghost btn-sm" data-action="dec-copy" data-text="${esc(text)}">${icon(done ? 'check' : 'copy', '', 13)} ${esc(done ? t.copied : t.copy)}</button>`;
}

function presetsHtml() {
  const t = T().ov; const c = cfg();
  const cards = PRESET_IDS.map((id) => {
    const on = c && c.preset === id;
    return `<article class="dec-card${on ? ' is-active' : ''}" aria-labelledby="dec-preset-${id}">
      <h3 class="dec-card-title" id="dec-preset-${id}">${esc(t.preset[id])} <span class="badge-seal badge-seal-experimental">${esc(T().experimental)}</span>${on ? ` <span class="badge-origin badge-origin-measured">${icon('check', '', 11)} ${esc(t.active)}</span>` : ''}</h3>
      <p class="dec-muted">${esc(t.presetNote[id])}</p>
      <p class="dec-muted">→ ${esc(t.provider[PRESET_PROVIDER[id]])}</p>
      <p class="dec-howto"><span class="dec-muted">${esc(t.howTo)}:</span> <code>${esc(PRESET_ENV[id])}</code> ${copyBtn(PRESET_ENV[id])}</p></article>`;
  }).join('');
  return `<section class="card dec-section" aria-labelledby="dec-presets-h"><div class="card-header"><div><h2 class="card-title" id="dec-presets-h">${esc(t.presetsTitle)}</h2><p class="card-subtitle">${esc(t.presetsDesc)}</p></div></div><div class="dec-grid">${cards}</div></section>`;
}

function strategiesHtml() {
  const t = T().ov; const prov = activeProvider();
  const cards = PROVIDERS.map((id) => `<article class="dec-card${prov === id ? ' is-active' : ''}" aria-labelledby="dec-prov-${id}">
    <h3 class="dec-card-title" id="dec-prov-${id}">${esc(t.provider[id])} ${id === 'jev' ? `<span class="badge-seal badge-seal-verified">${esc(t.standard)}</span>` : `<span class="badge-seal badge-seal-experimental">${esc(T().experimental)}</span>`}${prov === id ? ` <span class="badge-origin badge-origin-measured">${icon('check', '', 11)} ${esc(t.active)}</span>` : ''}</h3>
    <p class="dec-muted">${esc(t.providerDesc[id])}</p></article>`).join('');
  return `<section class="card dec-section" aria-labelledby="dec-strat-h"><div class="card-header"><h2 class="card-title" id="dec-strat-h">${esc(t.strategiesTitle)}</h2></div><div class="dec-grid dec-grid-4">${cards}</div></section>`;
}

function healthHtml() {
  const t = T().ov; const s = stat();
  if (!s) return `<p class="dec-muted">${esc(T().src.status)}: ${esc(T().label.UNKNOWN)}</p>`;
  const prov = s.providers || {};
  const jev = prov.jev || {};
  let jevState;
  if (jev.available === true) jevState = `<strong>${esc(t.layaUp)}</strong> ${labelBadge(lab({ value: 1, label: jev.label }).label)}`;
  else if (jev.available === false) jevState = `<strong>${esc(t.layaDown)}</strong> ${labelBadge(lab({ value: 1, label: jev.label }).label)}`;
  else jevState = `<strong>${esc(t.jevUnknown)}</strong> ${labelBadge('UNKNOWN')}`;
  const jevDesc = jev.available === null || jev.available === undefined ? t.jevUnknownDesc : (jev.reason || '');
  const laya = prov.laya;
  let layaState;
  if (!laya) layaState = `<strong>${esc(t.jevUnknown)}</strong> ${labelBadge('UNKNOWN')}`;
  else layaState = `<span class="dec-health-${laya.available ? 'up' : 'down'}">${icon(laya.available ? 'check' : 'x', '', 13)} <strong>${esc(laya.available ? t.layaUp : t.layaDown)}</strong></span> ${labelBadge(laya.label || 'UNKNOWN')}`;
  const layaDesc = laya ? `${laya.mode ? `${t.layaMode}: ${laya.mode}. ` : ''}${laya.reason ? `${t.layaReason}: ${laya.reason}` : ''}` : '';
  return `<div class="dec-grid">
    <article class="dec-card"><h3 class="dec-card-title">${esc(t.healthJev)}</h3><p>${jevState}</p><p class="dec-muted">${esc(jevDesc)}</p>
      <p class="dec-muted">${esc(jev.configured ? t.jevConfigured : t.jevNotConfigured)}${jev.backend ? ` · ${esc(jev.backend)}` : ''}</p></article>
    <article class="dec-card"><h3 class="dec-card-title">${esc(t.healthLaya)}</h3><p>${layaState}</p><p class="dec-muted">${esc(layaDesc)}</p></article></div>`;
}

function metricsHtml() {
  const t = T().ov; const m = store.metrics.data; const s = stat();
  if (!m) return `<p class="dec-muted">${esc(t.metricsNone)}</p>`;
  const req = lab(m.requests);
  const tile = (label, x, fmt) => `<div class="dec-tile"><span class="dec-tile-label">${esc(label)}</span><span class="dec-tile-value">${valueWithLabel(x, fmt)}</span></div>`;
  const cache = s && s.cache ? `<p class="dec-muted">${esc(t.cacheEntries)}: ${esc(fmtNumber(s.cache.size))}/${esc(fmtNumber(s.cache.max_size))} · ${esc(t.historyRecords)}: ${esc(fmtNumber(s.history && s.history.records))}</p>` : '';
  if (!req.value) return `<p class="dec-muted">${esc(t.metricsNone)}</p>${cache}`;
  return `<div class="dec-tiles">${tile(t.requests, m.requests, (v) => fmtNumber(v))}${tile(t.latP50, m.latency_ms_p50, (v) => fmtMs(v))}${tile(t.latP95, m.latency_ms_p95, (v) => fmtMs(v))}
    ${tile(t.cacheRate, m.cache_hit_rate, (v) => fmtPct(v))}${tile(t.fallbackRate, m.fallback_rate, (v) => fmtPct(v))}${tile(t.jevAvoided, m.jev_calls_avoided, (v) => fmtNumber(v))}
    ${tile(t.jevTokens, m.jev_tokens, (v) => fmtNumber(v))}${tile(t.jevCost, m.jev_cost_usd, (v) => String(v))}</div>${cache}`;
}

function advancedHtml() {
  const t = T().ov; const c = cfg(); const s = stat();
  const policy = s && s.fallback_policy ? `<h3 class="dec-h3">${esc(t.fallbackPolicy)}</h3><pre class="dec-pre">${esc(JSON.stringify(s.fallback_policy, null, 2))}</pre>` : '';
  const proj = c && c.projects && Object.keys(c.projects).length ? `<h3 class="dec-h3">${esc(t.projectOverrides)}</h3><pre class="dec-pre">${esc(JSON.stringify(c.projects, null, 2))}</pre>` : '';
  const dl = c ? `<dl class="dec-dl"><div><dt>${esc(t.reviewAction)}</dt><dd><code>${esc(c.review_action)}</code></dd></div><div><dt>${esc(t.cacheSize)}</dt><dd>${esc(fmtNumber(c.cache_size))}</dd></div>
    <div><dt>${esc(t.historySize)}</dt><dd>${esc(fmtNumber(c.history_size))}</dd></div><div><dt>${esc(t.persist)}</dt><dd>${esc(c.history_persist ? t.yes : t.no)}</dd></div></dl>` : '';
  return `<section class="card dec-section" aria-labelledby="dec-adv-h"><div class="card-header"><h2 class="card-title" id="dec-adv-h">${esc(t.advTitle)}</h2></div>${dl}${policy}${proj}</section>`;
}

function overviewBody() {
  const t = T().ov;
  const adv = ui.advanced;
  return `${honestBanner()}
    <section class="card dec-section" aria-labelledby="dec-active-h"><div class="card-header"><h2 class="card-title" id="dec-active-h">${esc(t.activeTitle)}</h2></div>${activeCard()}<p class="dec-muted dec-readonly">${icon('info', '', 13)} ${esc(t.readOnly)}</p></section>
    ${presetsHtml()}${adv ? strategiesHtml() : ''}
    <section class="card dec-section" aria-labelledby="dec-health-h"><div class="card-header"><h2 class="card-title" id="dec-health-h">${esc(t.health)}</h2></div>${healthHtml()}</section>
    <section class="card dec-section" aria-labelledby="dec-metrics-h"><div class="card-header"><h2 class="card-title" id="dec-metrics-h">${esc(t.metricsTitle)}</h2></div>${metricsHtml()}</section>
    ${adv ? advancedHtml() : ''}`;
}

const overviewTab = { html: () => gate(['status', 'config', 'metrics'], overviewBody), mount: () => ({}) };

/* ============================== Calibração ============================== */
function calibrationBody() {
  const t = T().ca; const c = cfg();
  const rows = thresholdRows(c);
  const tbl = rows.length ? `<div class="table-container"><table class="table dec-table" aria-label="${esc(t.rowsAria)}"><thead><tr><th scope="col">${esc(t.provider)}</th><th scope="col" class="num-col">${esc(t.keep)}</th><th scope="col" class="num-col">${esc(t.review)}</th><th scope="col" class="num-col">${esc(t.minConf)}</th></tr></thead><tbody>${rows.map((r) => `<tr><th scope="row">${esc(r.id)}</th>
    <td class="num-col tabular"><output>${esc(isNum(r.keep) ? fmtNum(r.keep, 3) : '—')}</output></td><td class="num-col tabular"><output>${esc(isNum(r.review) ? fmtNum(r.review, 3) : '—')}</output></td>
    <td class="num-col tabular"><output>${esc(isNum(r.minConfidence) ? fmtNum(r.minConfidence, 3) : '—')}</output></td></tr>`).join('')}</tbody></table></div>` : `<p class="dec-muted">${esc(t.noThresholds)}</p>`;
  const origin = c && c.threshold_label ? `<p class="dec-muted">${esc(t.thresholdsLabel)}: ${labelBadge('ESTIMATED')} ${esc(c.threshold_label)}</p>` : '';
  const w = c && c.ensemble_weights ? `<dl class="dec-dl"><div><dt>${esc(t.weightLaya)}</dt><dd>${esc(fmtNum(c.ensemble_weights.laya, 2))}</dd></div><div><dt>${esc(t.weightJev)}</dt><dd>${esc(fmtNum(c.ensemble_weights.jev, 2))}</dd></div></dl>` : '';
  const projs = c && c.projects && Object.keys(c.projects).length ? `<pre class="dec-pre">${esc(JSON.stringify(c.projects, null, 2))}</pre>` : `<p class="dec-muted">${esc(t.projectsNone)}</p>`;
  const ex = '{"thresholds": {"laya": {"keep": 0.25, "review": 0.10}},\n "ensemble_weights": {"laya": 0.5, "jev": 0.5}}';
  return `${honestBanner()}
    <section class="card dec-section" aria-labelledby="dec-ca-h"><div class="card-header"><div><h2 class="card-title" id="dec-ca-h">${esc(t.title)}</h2><p class="card-subtitle">${esc(t.desc)}</p></div></div>
      <div class="callout-notice dec-nowrite" role="note"><span class="callout-notice-icon">${icon('info', '', 16)}</span><div class="callout-notice-body">${esc(t.noWrite)}</div></div>
      ${tbl}${origin}
      <details class="dec-adv"><summary>${esc(t.advTitle)}</summary><h3 class="dec-h3">${esc(t.weights)}</h3>${w}<h3 class="dec-h3">${esc(t.projects)}</h3>${projs}
        <h3 class="dec-h3">${esc(t.example)}</h3><pre class="dec-pre">${esc(ex)}</pre></details></section>`;
}
const calibrationTab = { html: () => gate(['config'], calibrationBody, 'table'), mount: () => ({}) };

/* ============================== Diagnóstico Laya ============================== */
const CHECK_ICON = { ok: 'check', fail: 'x', unknown: 'info' };
function layaBody() {
  const t = T().la;
  const s = stat();
  const d = diagnoseLaya(s && s.providers ? s.providers.laya : null);
  if (!d.reachable) return `<p class="dec-muted">${esc(t.unreachable)}</p>`;
  const note = { device: t.deviceNote, inference: t.inferNote };
  const rows = d.checks.map((c) => `<tr><th scope="row">${esc(t.checks[c.id])}</th>
    <td><span class="dec-check dec-check-${c.state}">${icon(CHECK_ICON[c.state], '', 13)} <span>${esc(t.st[c.state])}</span></span></td>
    <td>${esc(c.detail)}${c.state === 'unknown' && note[c.id] ? `<span class="dec-muted">${esc(note[c.id])}</span>` : ''}</td></tr>`).join('');
  const probs = d.problems.length ? `<div class="table-container"><table class="table dec-table"><caption class="sr-only">${esc(t.problemsTitle)}</caption><thead><tr><th scope="col">${esc(t.problem)}</th><th scope="col">${esc(t.cause)}</th><th scope="col">${esc(t.action)}</th></tr></thead><tbody>${d.problems.map((p) => `<tr><td>${esc(t.p[p].problem)}</td><td>${esc(t.p[p].cause)}</td><td>${esc(t.p[p].action)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="dec-muted">${icon('info', '', 13)} ${esc(t.noProblems)}</p>`;
  return `${honestBanner()}
    <section class="card dec-section" aria-labelledby="dec-la-h"><div class="card-header"><div><h2 class="card-title" id="dec-la-h">${esc(t.title)}</h2><p class="card-subtitle">${esc(t.desc)}</p></div>${labelBadge('MEASURED')}</div>
      <div class="table-container"><table class="table dec-table"><thead><tr><th scope="col">${esc(t.check)}</th><th scope="col">${esc(t.result)}</th><th scope="col">${esc(t.detail)}</th></tr></thead><tbody>${rows}</tbody></table></div>
      ${d.promptVersion ? `<p class="dec-muted">${esc(t.promptVersion)}: <code>${esc(d.promptVersion)}</code></p>` : ''}</section>
    <section class="card dec-section" aria-labelledby="dec-la-p"><div class="card-header"><h2 class="card-title" id="dec-la-p">${esc(t.problemsTitle)}</h2></div>${probs}</section>`;
}
const layaTab = { html: () => gate(['status'], layaBody, 'table'), mount: () => ({}) };

/* ============================== Página ============================== */
const TABS = [
  { id: 'overview', label: () => T().tabs.overview, tab: overviewTab },
  { id: 'evaluation', label: () => T().tabs.evaluation, tab: evalTab },
  { id: 'history', label: () => T().tabs.history, tab: historyTab },
  { id: 'calibration', label: () => T().tabs.calibration, tab: calibrationTab },
  { id: 'laya', label: () => T().tabs.laya, tab: layaTab },
];

export function render() {
  const t = T();
  return `
    <div class="decision-page page-fade-slide">
      <header class="decision-header">
        <div><h1 class="page-title">${esc(t.title)}</h1><p class="page-subtitle">${esc(t.subtitle)}</p></div>
        <div class="dec-actions">
          <button type="button" class="btn btn-secondary btn-sm" data-action="dec-advanced" aria-pressed="${ui.advanced}">${esc(ui.advanced ? t.mode.advanced : t.mode.beginner)}</button>
          <button type="button" class="btn btn-secondary btn-sm" data-action="dec-reload">${icon('refresh', '', 13)} ${esc(t.reload)}</button>
        </div>
      </header>
      <div class="tab-list dec-tablist" role="tablist" aria-label="${esc(t.tabsAria)}" data-bind="dec-tablist">
        ${TABS.map((x) => `<button type="button" class="tab-btn" role="tab" id="${tabId('decision', x.id)}" aria-selected="${ui.tab === x.id}" aria-controls="${panelId('decision')}-${x.id}" tabindex="${ui.tab === x.id ? '0' : '-1'}" data-action="dec-tab" data-tab="${x.id}">${esc(x.label())}</button>`).join('')}
      </div>
      ${TABS.map((x) => `<div class="decision-tabpanel" role="tabpanel" id="${panelId('decision')}-${x.id}" aria-labelledby="${tabId('decision', x.id)}" tabindex="0" data-tabpanel="${x.id}" ${ui.tab === x.id ? '' : 'hidden'}>${x.tab.html()}</div>`).join('')}
    </div>`;
}

export function mount(root) {
  const api = {};
  const paint = (id) => {
    const x = TABS.find((y) => y.id === id); const p = root.querySelector(`[data-tabpanel="${id}"]`);
    if (x && p) p.innerHTML = x.tab.html();
  };
  const paintAll = () => {
    TABS.forEach((x) => paint(x.id));
    const b = root.querySelector('[data-action="dec-advanced"]');
    if (b) { b.setAttribute('aria-pressed', String(ui.advanced)); b.textContent = ui.advanced ? T().mode.advanced : T().mode.beginner; }
  };
  const reload = async () => { paintAll(); await loadAll(); if (root.isConnected) paintAll(); };
  const ctx = { repaint: paint, reload };
  const selectTab = (id, focus = false) => {
    if (!TABS.some((x) => x.id === id)) return;
    ui.tab = id;
    root.querySelectorAll('[data-action="dec-tab"]').forEach((b) => {
      const on = b.getAttribute('data-tab') === id;
      b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
    });
    root.querySelectorAll('[data-tabpanel]').forEach((p) => { p.hidden = p.getAttribute('data-tabpanel') !== id; });
  };
  const onKey = (e) => {
    const list = root.querySelector('[data-bind="dec-tablist"]');
    if (list) handleTablistKey(e, list, '[role="tab"]', (b) => selectTab(b.getAttribute('data-tab'), true));
  };
  const onClick = (e) => {
    const el = e.target.closest('[data-action]'); if (!el) return;
    const a = el.getAttribute('data-action');
    if (a === 'dec-tab') selectTab(el.getAttribute('data-tab'));
    else if (a === 'dec-reload') reload();
    else if (a === 'dec-advanced') {
      ui.advanced = !ui.advanced;
      try { localStorage.setItem(ADV_PREF, ui.advanced ? '1' : '0'); } catch { /* ignora */ }
      paintAll(); root.querySelector('[data-action="dec-advanced"]')?.focus();
    } else if (a === 'dec-copy') {
      const txt = el.getAttribute('data-text') || '';
      navigator.clipboard?.writeText(txt).catch(() => {});
      ui.copied = txt; paint('overview');
      root.querySelector(`[data-action="dec-copy"][data-text="${CSS.escape(txt)}"]`)?.focus();
      setTimeout(() => { ui.copied = ''; if (root.isConnected) paint('overview'); }, 1500);
    }
  };
  root.addEventListener('keydown', onKey);
  root.addEventListener('click', onClick);
  TABS.forEach((x) => { api[x.id] = x.tab.mount(root, ctx); });
  registerCommand({ id: 'decision-reload', label: () => T().reload + ' — ' + T().title, category: 'nav', categoryLabel: () => I18N.palette.catNav, icon: 'refresh', keywords: 'decision engine atualizar reload', run: () => reload() });
  root._decisionCleanup = () => {
    root.removeEventListener('keydown', onKey); root.removeEventListener('click', onClick);
    Object.values(api).forEach((x) => x && x.cleanup && x.cleanup());
    unregisterCommand('decision-reload');
  };
  loadAll().then(() => { if (root.isConnected) paintAll(); });
}

export function unmount(root) {
  if (root && root._decisionCleanup) { root._decisionCleanup(); delete root._decisionCleanup; }
}
