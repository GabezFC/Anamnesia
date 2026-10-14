/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA COSTS PAGE (#/costs)
 * Livro de custos ligado ao backend: /api/costs/{summary,calls,hourly,budget,by-role,stream}.
 * Zero benchmarks ou comparações de modelos nesta página (foco em produto e auditoria financeira).
 */

import { icon } from '../icons.js';
import { I18N, getLang } from '../i18n.js';
import { esc, fmtNumber, fmtDate } from '../format.js';
import * as A from '../anamnesia-api.js';
import { createLineChart } from '../charts/chart-kit.js';
import { createVirtualTable } from '../components/virtual-table.js';
import { skeleton, skeletonKpis, skeletonTable } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';

const RANGES = ['today', '7d', '30d', 'all'];
const PAGE_SIZE = 50;
const POLL_MS = 30000;
const DEBOUNCE_MS = 600;
// fallback de rótulo de origem caso a chave I18N esteja ausente (nunca exibe 0 no lugar de 'indisponível')
const ORIGIN_PT = { measured: 'medido', estimated: 'estimado', unavailable: 'indisponível' };

const S = {
  range: 'today',
  status: 'loading', // 'loading' | 'ready' | 'error' | 'backend-unavailable'
  summary: null,
  hourly: [],
  budget: null,
  roles: [],
  calls: [],
  nextCursor: null,
  loadingMore: false,
  selected: null,
  live: 'polling', // 'live' | 'polling'
  draft: { daily: null, monthly: null, alert: null },
  budgetMsg: null, // { ok, text }
  budgetSaving: false,
};

let reqSeq = 0;
let stopStream = null;
let pollTimer = null;
let debounceTimer = null;
let lineChart = null;
let callsTable = null;
let currentRoot = null;

/* ---------------------------------------------------------------- helpers */
const originKey = (o) => (o === 'measured' || o === 'estimated' ? o : 'unavailable');
const originText = (o) => I18N.app[originKey(o)] || ORIGIN_PT[originKey(o)];
const fmtMoney = (v) => (typeof v === 'number' && Number.isFinite(v) ? `US$ ${v.toFixed(v !== 0 && Math.abs(v) < 0.01 ? 4 : 2)}` : '—');
const fmtTok = (v) => (typeof v === 'number' && Number.isFinite(v) ? (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)) : null);
const fmtWhen = (ts) => fmtDate(ts);
const fill = (tpl, vars) => String(tpl).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''));
const asNum = (x) => (typeof x === 'number' && Number.isFinite(x) ? x : null);

export function normalizeCall(c) {
  return {
    id: String(c.run_id ?? c.id ?? ''),
    ts: asNum(c.created_at),
    project: c.project || '—',
    agent: c.client || c.agent || '—',
    pipeline: c.pipeline || '—',
    context_tokens: A.lvValue(c.context_tokens),
    cost: A.lvValue(c.cost_usd),
    origin: originKey(A.lvOrigin(c.cost_usd)),
  };
}

function budgetRows() {
  const b = S.budget;
  if (!b) return [];
  const t = I18N.costs;
  return [
    { key: 'daily', label: t.budgetDaily, short: t.budgetDailyShort, d: b.daily || {} },
    { key: 'monthly', label: t.budgetMonthly, short: t.budgetMonthlyShort, d: b.monthly || {} },
  ];
}

/* ---------------------------------------------------------------- data */
async function fetchAll(seq) {
  const range = S.range;
  const r = await Promise.allSettled([
    A.costSummary(range),
    A.costHourly(range),
    A.costBudget(),
    A.costByRole(range),
    A.costCallsRange({ range, limit: PAGE_SIZE }),
  ]);
  if (seq !== reqSeq) return null;
  return r;
}

async function load({ silent = false } = {}) {
  const seq = ++reqSeq;
  if (!silent) { S.status = 'loading'; paint(); }
  const r = await fetchAll(seq);
  if (!r) return;
  const [sum, hourly, budget, roles, calls] = r;
  if (sum.status === 'rejected' && calls.status === 'rejected') {
    S.status = A.isUnavailable(sum.reason) ? 'backend-unavailable' : 'error';
    if (!silent || !S.summary) paint();
    return;
  }
  if (sum.status === 'fulfilled') S.summary = sum.value;
  S.hourly = hourly.status === 'fulfilled' ? (hourly.value?.points || []) : [];
  S.budget = budget.status === 'fulfilled' ? budget.value : null;
  S.roles = roles.status === 'fulfilled' ? A.asList(roles.value) : [];
  if (calls.status === 'fulfilled') {
    const fresh = A.asList(calls.value).map(normalizeCall);
    if (silent && S.calls.length > fresh.length) {
      // refresh em segundo plano preserva páginas já carregadas (mescla por id)
      const seen = new Set(fresh.map((c) => c.id));
      S.calls = [...fresh, ...S.calls.filter((c) => !seen.has(c.id))];
    } else {
      S.calls = fresh;
      S.nextCursor = calls.value?.next_cursor || null;
    }
  }
  S.status = 'ready';
  paint();
}

async function loadMore() {
  if (!S.nextCursor || S.loadingMore) return;
  const seq = reqSeq;
  S.loadingMore = true;
  paint();
  try {
    const page = await A.costCallsRange({ range: S.range, limit: PAGE_SIZE, cursor: S.nextCursor });
    if (seq !== reqSeq) return;
    const seen = new Set(S.calls.map((c) => c.id));
    S.calls = [...S.calls, ...A.asList(page).map(normalizeCall).filter((c) => !seen.has(c.id))];
    S.nextCursor = page?.next_cursor || null;
  } catch { /* mantém a lista atual; o botão continua disponível */ }
  S.loadingMore = false;
  paint();
}

function scheduleRefresh() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => { load({ silent: true }); }, DEBOUNCE_MS);
}

function startLive() {
  stopLive();
  const startPoll = () => {
    if (pollTimer) return;
    pollTimer = setInterval(() => { load({ silent: true }); }, POLL_MS);
  };
  const stopPoll = () => { clearInterval(pollTimer); pollTimer = null; };
  startPoll(); // fallback: cobre o intervalo até o SSE conectar (ou se EventSource faltar)
  if (typeof EventSource === 'undefined') return;
  stopStream = A.openCostStream(
    () => scheduleRefresh(),
    (state) => {
      if (state === 'live') { stopPoll(); S.live = 'live'; } else { startPoll(); S.live = 'polling'; }
      const el = currentRoot?.querySelector('[data-bind="costs-live"]');
      if (el) el.innerHTML = liveBadge();
    },
  );
}

function stopLive() {
  if (stopStream) { stopStream(); stopStream = null; }
  clearInterval(pollTimer); pollTimer = null;
  clearTimeout(debounceTimer); debounceTimer = null;
}

/* ---------------------------------------------------------------- views */
function liveBadge() {
  const t = I18N.costs;
  return `<span class="dot ${S.live === 'live' ? 'dot-success' : 'dot-warning'}"></span><span class="u-4d6d16">${esc(S.live === 'live' ? t.liveOn : t.livePolling)}</span>`;
}

function skeletonView() {
  return `
    <div class="costs-page" data-bind="costs-page" aria-busy="true">
      ${skeleton({ width: 340, height: 36 })}
      ${skeletonKpis(4)}
      ${skeleton({ height: 120 })}
      <div class="charts-dual-row">${skeleton({ height: 260 })}${skeleton({ height: 260 })}</div>
      ${skeletonTable({ rows: 6, cols: 6 })}
    </div>`;
}

function kpiCard(label, origin, value, sub, accent = false) {
  const style = accent ? ' data-css="color:var(--success)"' : '';
  return `
    <div class="kpi-card">
      <div class="kpi-label"><span>${esc(label)}</span><span class="badge-origin badge-origin-${origin}">${esc(originText(origin))}</span></div>
      <div class="kpi-value-row"><span class="kpi-value"${style}>${esc(value)}</span></div>
      <span class="kpi-subtext">${esc(sub)}</span>
    </div>`;
}

function kpisView() {
  const t = I18N.costs;
  const s = S.summary || {};
  const na = t.unavailable;
  const money = A.lvValue(s.cost_usd);
  const ctx = A.lvValue(s.context_tokens);
  const cand = A.lvValue(s.candidate_tokens);
  const saved = cand != null && ctx != null ? cand - ctx : null;
  const calls = asNum(s.calls);
  return `
    <div class="costs-kpi-grid">
      ${kpiCard(t.kpiTotal, originKey(A.lvOrigin(s.cost_usd)), money == null ? na : fmtMoney(money), t.kpiTotalSub)}
      ${kpiCard(t.kpiCalls, 'measured', calls == null ? na : String(calls), t.kpiCallsSub)}
      ${kpiCard(t.kpiTokens, originKey(A.lvOrigin(s.context_tokens)), ctx == null ? na : `${fmtTok(ctx)} ${t.tokensUnit}`, t.kpiTokensSub)}
      ${kpiCard(t.kpiSavedTokens, saved == null ? 'unavailable' : 'estimated', saved == null ? na : `${fmtTok(saved)} ${t.tokensUnit}`, t.kpiSavedSub, saved != null)}
    </div>`;
}

function budgetView() {
  const t = I18N.costs;
  const b = S.budget;
  let banner = '';
  let bars = '';
  let status = `<span class="dot dot-success"></span><span class="u-4d6d16">${esc(t.budgetOk)}</span>`;
  if (!b) {
    bars = `<p class="kpi-subtext">${esc(t.budgetUnavailable)}</p>`;
    status = '';
  } else {
    const rows = budgetRows();
    const hot = rows.filter((r) => r.d.alert || r.d.exceeded);
    if (hot.length) {
      const exceeded = hot.some((r) => r.d.exceeded);
      const which = hot.map((r) => r.short).join(', ');
      const pct = Math.round(Math.max(...hot.map((r) => asNum(r.d.percent) ?? 0)));
      const msg = esc(fill(exceeded ? t.budgetExceededBanner : t.budgetAlertBanner, { pct, which }));
      banner = `
        <div class="callout-notice budget-banner ${exceeded ? 'is-exceeded' : 'is-alert'}" role="alert" data-bind="budget-banner">
          <div class="callout-notice-icon">${icon('alertTriangle', '', 18)}</div>
          <div class="callout-notice-body">${msg}</div>
        </div>`;
      status = `<span class="dot ${exceeded ? 'dot-danger' : 'dot-warning'}"></span><span class="u-4d6d16">${esc(exceeded ? t.budgetStatusExceeded : t.budgetStatusAlert)}</span>`;
    }
    bars = rows.map((r) => {
      const pct = asNum(r.d.percent);
      const noLimit = asNum(r.d.limit_usd) == null;
      const cls = r.d.exceeded ? 'exceeded' : r.d.alert ? 'warning' : 'ok';
      const text = noLimit
        ? `${fmtMoney(asNum(r.d.spent_usd))} · ${t.budgetNoLimit}`
        : `${fmtMoney(asNum(r.d.spent_usd))} ${t.budgetOf} ${fmtMoney(r.d.limit_usd)}${pct != null ? ` (${pct.toFixed(0)}%)` : ''}`;
      return `
        <div class="budget-item" data-budget="${r.key}">
          <div class="budget-header"><span class="u-cf5948">${esc(r.label)}</span><span class="tabular">${esc(text)}</span></div>
          <div class="budget-track" role="progressbar" aria-label="${esc(r.label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(pct ?? 0, 100).toFixed(0)}">
            <div class="budget-fill budget-fill-${cls}" data-css="width:${Math.min(pct ?? 0, 100)}%"></div>
          </div>
        </div>`;
    }).join('');
  }

  const val = (k, fallback) => (S.draft[k] != null ? S.draft[k] : (fallback == null ? '' : String(fallback)));
  const form = b ? `
    <form class="budget-form" data-action="budget-form" novalidate>
      <label class="input-group"><span class="input-label">${esc(t.budgetDailyInput)}</span>
        <input class="input-field" name="daily" type="number" min="0" step="0.01" inputmode="decimal" value="${esc(val('daily', b.daily?.limit_usd))}"></label>
      <label class="input-group"><span class="input-label">${esc(t.budgetMonthlyInput)}</span>
        <input class="input-field" name="monthly" type="number" min="0" step="0.01" inputmode="decimal" value="${esc(val('monthly', b.monthly?.limit_usd))}"></label>
      <label class="input-group"><span class="input-label">${esc(t.budgetAlertInput)}</span>
        <input class="input-field" name="alert" type="number" min="1" max="100" step="1" inputmode="numeric" value="${esc(val('alert', b.alert_pct))}"></label>
      <button class="btn btn-primary btn-sm" type="submit" ${S.budgetSaving ? 'disabled' : ''}>${esc(S.budgetSaving ? t.budgetSaving : t.budgetSave)}</button>
      <span class="budget-msg ${S.budgetMsg ? (S.budgetMsg.ok ? 'is-ok' : 'is-error') : ''}" role="status" aria-live="polite">${S.budgetMsg ? esc(S.budgetMsg.text) : ''}</span>
    </form>` : '';

  return `
    ${banner}
    <div class="budget-panel">
      <div class="u-dd70a6">
        <h2 class="u-ae978d">${esc(t.budgetTitle)}</h2>
        <span class="status-indicator">${status}</span>
      </div>
      <div class="budget-bars-grid">${bars}</div>
      ${form}
    </div>`;
}

function rolesView() {
  const t = I18N.costs;
  const body = S.roles.length
    ? `<table class="table" data-bind="roles-table"><thead><tr>
        <th>${esc(t.colRole)}</th><th class="num-col">${esc(t.colCalls)}</th><th class="num-col">${esc(t.colRuns)}</th>
        <th class="num-col">${esc(t.colTokens)}</th><th class="num-col">${esc(t.colCost)}</th><th>${esc(t.colCostStatus)}</th>
      </tr></thead><tbody>${S.roles.map((r) => {
        const cost = asNum(r.cost_usd);
        const st = originKey(r.cost_status);
        return `<tr>
          <td><span class="badge u-d28f36">${esc(r.role || '—')}</span></td>
          <td class="num-col tabular font-mono">${esc(r.calls ?? '—')}</td>
          <td class="num-col tabular font-mono">${esc(r.runs ?? '—')}</td>
          <td class="num-col tabular font-mono">${esc(fmtNumber(asNum(r.total_tokens_spent)))}</td>
          <td class="num-col tabular font-mono u-93d1d3">${esc(cost == null ? t.unavailable : fmtMoney(cost))}</td>
          <td><span class="badge-origin badge-origin-${st}">${esc(originText(st))}</span></td>
        </tr>`;
      }).join('')}</tbody></table>`
    : emptyState({ title: t.rolesEmptyTitle, description: t.rolesEmptyDesc, variant: 'data', compact: true });
  return `
    <div class="chart-card" data-bind="roles-card">
      <div class="chart-header"><div>
        <h2 class="u-ae978d">${esc(t.rolesTitle)}</h2>
        <p class="u-47c8df">${esc(t.rolesSubtitle)}</p>
      </div></div>
      <div class="table-container u-dd9991">${body}</div>
    </div>`;
}

function callsView() {
  const t = I18N.costs;
  const more = S.nextCursor
    ? `<div class="u-aa69d1"><button class="btn btn-secondary btn-sm" data-action="load-more-calls" ${S.loadingMore ? 'disabled' : ''}>${esc(S.loadingMore ? t.callsLoadingMore : t.callsMore)}</button></div>`
    : '';
  return `
    <div class="calls-section">
      <div class="calls-table-toolbar">
        <h2 class="u-b41b77">${esc(t.callsTableTitle)}</h2>
        <span class="section-count tabular">${esc(fill(t.callsShowing, { n: S.calls.length }))}</span>
      </div>
      <div id="costs-calls-mount" data-bind="calls-table"></div>
      ${more}
    </div>`;
}

function drawerView() {
  const t = I18N.costs;
  const c = S.selected;
  const kv = (label, value, extra = '') => `<div class="readonly-kv-item"><span class="readonly-kv-label">${esc(label)}</span><span class="readonly-kv-value ${extra}">${esc(value)}</span></div>`;
  return `
    <div class="drawer-backdrop ${c ? 'is-active' : ''}" data-action="close-call-detail"></div>
    <div class="drawer ${c ? 'is-active' : ''}">
      <div class="drawer-header">
        <div><div class="card-title">${esc(t.callDetailTitle)}</div><div class="card-subtitle">${esc(c ? c.id : '')}</div></div>
        <button class="btn btn-ghost btn-icon" data-action="close-call-detail" aria-label="${esc(I18N.app.close)}">${icon('x', '', 16)}</button>
      </div>
      <div class="drawer-content">${c ? `
        ${kv(t.detailTimestamp, fmtWhen(c.ts), 'tabular')}
        ${kv(t.detailProject, c.project)}
        ${kv(t.detailAgent, c.agent)}
        ${kv(t.detailPipeline, c.pipeline, 'font-mono')}
        ${kv(t.detailContext, c.context_tokens == null ? t.unavailable : `${fmtNumber(c.context_tokens)} ${t.tokensUnit}`, 'tabular')}
        <div class="readonly-kv-item"><span class="readonly-kv-label">${esc(t.detailCost)}</span>
          <div class="u-a631c9">
            <span class="readonly-kv-value tabular u-4e0dc0">${esc(c.cost == null ? t.unavailable : fmtMoney(c.cost))}</span>
            <span class="badge-origin badge-origin-${c.origin}">${esc(originText(c.origin))}</span>
          </div>
        </div>` : ''}
      </div>
    </div>`;
}

export function render() {
  const t = I18N.costs;
  if (S.status === 'loading') return skeletonView();

  if (S.status === 'error') {
    return `<div class="costs-page" data-bind="costs-page">${emptyState({
      title: I18N.app.errorTitle, description: t.errorDesc, variant: 'error',
      action: { label: I18N.app.errorRetry, action: 'retry-costs', kind: 'secondary' },
    })}</div>`;
  }

  const unavailable = S.status === 'backend-unavailable';
  const noData = !unavailable && S.calls.length === 0 && !(asNum(S.summary?.calls) > 0);
  const notice = unavailable ? `
    <div class="callout-notice">
      <div class="callout-notice-icon">${icon('info', '', 18)}</div>
      <div class="callout-notice-body"><strong>${esc(I18N.app.backendUnavailableTitle)}</strong> ${esc(I18N.app.backendUnavailableDesc)}</div>
    </div>` : '';

  const tabs = RANGES.map((r) => {
    const label = { today: t.periodToday, '7d': t.period7d, '30d': t.period30d, all: t.periodAll }[r];
    return `<button class="tab-btn ${S.range === r ? 'is-active' : ''}" role="tab" aria-selected="${S.range === r}" data-action="filter-period" data-period="${r}">${esc(label)}</button>`;
  }).join('');

  const header = `
    <div class="costs-filter-bar">
      <div>
        <h1 class="u-5a2a94">${esc(t.ledgerTitle)}</h1>
        <p class="u-47c8df">${esc(t.ledgerSubtitle)}</p>
      </div>
      <div class="u-966338">
        <span class="status-indicator" data-bind="costs-live">${liveBadge()}</span>
        <div class="tab-list" role="tablist" aria-label="${esc(t.rangeAria)}">${tabs}</div>
        <button class="btn btn-secondary btn-sm" data-action="export-csv">${icon('download', '', 13)} ${esc(t.exportCsv)}</button>
      </div>
    </div>`;

  if (noData) {
    return `<div class="costs-page" data-bind="costs-page">${notice}${header}${budgetView()}${emptyState({
      title: t.emptyTitle, description: t.emptyDesc, variant: 'cost',
    })}</div>`;
  }

  return `
    <div class="costs-page" data-bind="costs-page">
      ${notice}
      ${header}
      ${kpisView()}
      ${budgetView()}
      <div class="charts-dual-row">
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <h2 class="u-ae978d">${esc(t.chartTitle)}</h2>
              <p class="u-47c8df">${esc(t.chartSubtitle)}</p>
            </div>
            <span class="badge-origin badge-origin-measured">${esc(originText('measured'))}</span>
          </div>
          <div id="cost-line-chart-mount" class="u-02afda"></div>
        </div>
        ${rolesView()}
      </div>
      ${callsView()}
      ${drawerView()}
    </div>`;
}

/* ---------------------------------------------------------------- mounting */
export function hourlyChartData(points) {
  let acc = 0;
  return (points || []).map((p) => {
    acc += asNum(p.cost_usd) || 0;
    return { hour: String(p.hour ?? ''), cost: Number(acc.toFixed(4)) };
  });
}

function destroyWidgets() {
  if (lineChart && lineChart.destroy) lineChart.destroy();
  lineChart = null;
  if (callsTable) callsTable.destroy();
  callsTable = null;
}

function mountWidgets(root) {
  destroyWidgets();
  const t = I18N.costs;
  const lineMount = root.querySelector('#cost-line-chart-mount');
  if (lineMount) {
    const data = hourlyChartData(S.hourly);
    if (!data.length) {
      lineMount.innerHTML = emptyState({ title: t.chartEmpty, variant: 'data', compact: true });
    } else {
      lineChart = createLineChart(lineMount, {
        data,
        xKey: 'hour',
        series: [{ key: 'cost', label: t.chartSeries, color: 'var(--chart-1)', fill: true }],
        yFormatter: (v) => `US$ ${v.toFixed(2)}`,
        xFormatter: (v) => v,
        height: 220,
      });
    }
  }
  const tableMount = root.querySelector('#costs-calls-mount');
  if (tableMount) {
    callsTable = createVirtualTable({
      container: tableMount,
      ariaLabel: t.callsAria,
      rowHeight: 40,
      height: 400,
      rows: S.calls,
      rowKey: (r) => r.id,
      emptyHtml: emptyState({ title: I18N.app.noCallsTitle, description: I18N.app.noCallsDesc, variant: 'data', compact: true }),
      columns: [
        { key: 'ts', label: t.colWhen, width: '150px', render: (r) => `<span class="tabular font-mono u-bdff7b">${esc(fmtWhen(r.ts))}</span>` },
        { key: 'project', label: t.colProject, width: '1fr', render: (r) => `<span class="u-cf5948">${esc(r.project)}</span>` },
        { key: 'agent', label: t.colAgent, width: '1fr', render: (r) => `<span class="badge u-d28f36">${esc(r.agent)}</span>` },
        { key: 'pipeline', label: t.colPipeline, width: '1fr', render: (r) => `<span class="font-mono text-tertiary u-15b680">${esc(r.pipeline)}</span>` },
        { key: 'context_tokens', label: t.colContext, width: '110px', align: 'right', render: (r) => `<span class="tabular font-mono">${esc(r.context_tokens == null ? '—' : `${fmtNumber(r.context_tokens)} ${t.tokensUnit}`)}</span>` },
        { key: 'cost', label: t.colCost, width: '120px', align: 'right', render: (r) => `<span class="tabular font-mono u-93d1d3">${esc(r.cost == null ? t.unavailable : fmtMoney(r.cost))}</span>` },
        { key: 'origin', label: t.colOrigin, width: '110px', render: (r) => `<span class="badge-origin badge-origin-${r.origin}">${esc(originText(r.origin))}</span>` },
        { key: 'id', label: t.colActions, width: '110px', align: 'right', render: (r) => `<button class="btn btn-ghost btn-sm" data-action="view-call-detail" data-call-id="${esc(r.id)}">${icon('fileText', '', 12)} ${esc(t.detailsBtn)}</button>` },
      ],
    });
  }
}

function paint() {
  if (!currentRoot) return;
  // preserva o foco do formulário de orçamento durante refresh em segundo plano
  const name = currentRoot.querySelector('form[data-action="budget-form"] :focus')?.name;
  destroyWidgets();
  currentRoot.innerHTML = render();
  mountWidgets(currentRoot);
  if (name) {
    const el = currentRoot.querySelector(`form[data-action="budget-form"] [name="${name}"]`);
    if (el) el.focus();
  }
}

async function saveBudget(form) {
  const t = I18N.costs;
  const fd = new FormData(form);
  const parse = (v) => {
    const s = String(v ?? '').trim();
    if (s === '') return undefined;
    const n = Number(s);
    return Number.isFinite(n) ? n : NaN;
  };
  const daily = parse(fd.get('daily'));
  const monthly = parse(fd.get('monthly'));
  const alert = parse(fd.get('alert'));
  const bad = [daily, monthly].some((n) => n !== undefined && (Number.isNaN(n) || n < 0))
    || (alert !== undefined && (Number.isNaN(alert) || alert < 1 || alert > 100));
  if (bad) { S.budgetMsg = { ok: false, text: t.budgetInvalid }; paint(); return; }
  const body = {};
  if (daily !== undefined) body.daily_usd = daily;
  if (monthly !== undefined) body.monthly_usd = monthly;
  if (alert !== undefined) body.alert_pct = alert;
  S.budgetSaving = true; S.budgetMsg = null; paint();
  try {
    await A.putCostBudget(body);
    S.budgetMsg = { ok: true, text: t.budgetSaved };
    S.draft = { daily: null, monthly: null, alert: null };
    try { S.budget = await A.costBudget(); } catch { /* mantém valores anteriores */ }
    window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type: 'success', message: t.budgetSaved } }));
  } catch (e) {
    const detail = e && e.message ? `: ${e.message}` : '';
    S.budgetMsg = { ok: false, text: `${t.budgetSaveFail}${detail}` };
  }
  S.budgetSaving = false;
  paint();
}

export function mount(root) {
  currentRoot = root;
  S.selected = null;
  S.budgetMsg = null;

  const onClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target || target.getAttribute('data-action') === 'budget-form') return;
    const action = target.getAttribute('data-action');
    if (action === 'filter-period') {
      const p = target.getAttribute('data-period');
      if (!RANGES.includes(p) || p === S.range) return;
      S.range = p; S.calls = []; S.nextCursor = null;
      load();
    } else if (action === 'export-csv') {
      const a = document.createElement('a');
      a.href = A.costCsvUrl(S.range);
      a.download = 'anamnesia-costs.csv';
      document.body.appendChild(a); a.click(); a.remove();
      window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type: 'success', message: I18N.costs.csvStarted } }));
    } else if (action === 'load-more-calls') {
      loadMore();
    } else if (action === 'view-call-detail') {
      const id = target.getAttribute('data-call-id');
      S.selected = S.calls.find((c) => c.id === id) || null;
      paint();
    } else if (action === 'close-call-detail') {
      S.selected = null; paint();
    } else if (action === 'retry-costs') {
      load();
    }
  };
  const onSubmit = (e) => {
    const form = e.target.closest('form[data-action="budget-form"]');
    if (!form) return;
    e.preventDefault();
    saveBudget(form);
  };
  const onInput = (e) => {
    const el = e.target;
    if (el && el.closest && el.closest('form[data-action="budget-form"]') && el.name in S.draft) S.draft[el.name] = el.value;
  };

  root.addEventListener('click', onClick);
  root.addEventListener('submit', onSubmit);
  root.addEventListener('input', onInput);
  root._costsCleanup = () => {
    root.removeEventListener('click', onClick);
    root.removeEventListener('submit', onSubmit);
    root.removeEventListener('input', onInput);
  };

  // stale-while-revalidate: com dados anteriores, atualiza sem voltar ao skeleton
  const hasData = S.status === 'ready' && S.summary;
  if (!hasData) S.status = 'loading';
  paint();
  load({ silent: !!hasData });
  startLive();
}

export function unmount(root) {
  stopLive();
  reqSeq += 1; // descarta respostas em voo
  destroyWidgets();
  const r = root || currentRoot;
  if (r && r._costsCleanup) { r._costsCleanup(); delete r._costsCleanup; }
  currentRoot = null;
}

export function setDebugState(state, root) {
  S.status = state === 'loaded' ? 'ready' : state;
  if (root) currentRoot = root;
  paint();
}
