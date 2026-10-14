/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: EXPLORADOR DE RUNS (#/compare/history) — ANA-203 + ANA-209.
 * Runs reais de /benchmark/runs (filtros agent/q/since no servidor; pipeline no cliente), série de
 * /benchmark/timeseries, tabela virtualizada, estado na URL (#/compare/history?pipeline=…) e detalhe da run
 * com trace waterfall (SVG + tabela). Nada de mock: falha de API = "indisponível".
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtDate, fmtDateShort, fmtMs } from '../../format.js';
import { call, isUnavailable } from '../../anamnesia-api.js';
import { createLineChart } from '../../charts/chart-kit.js';
import { createVirtualTable } from '../../components/virtual-table.js';
import { emptyState } from '../../components/empty-state.js';
import { loadingBlock, skeletonTable } from '../../components/skeleton.js';
import { STAGES, hashQuery, setHashQuery, runSpans, ensureLab, lab } from '../../lab-data.js';
import { na, vMs, vTok, pipeName, header, table } from './_shared.js';

const PAGE = 200;
const METRICS = ['tokens', 'context', 'latency', 'cost', 'documents', 'recall'];
const S = {
  f: { pipeline: '', agent: '', q: '', days: '', metric: 'context' },
  runs: [], status: 'idle', error: '', limit: PAGE, series: null, seriesStatus: 'idle',
  detail: null, detailStatus: 'idle', detailError: '', pickA: '', pickB: '',
};
let table$ = null; let chart = null; let token = 0;

function readUrl() {
  const q = hashQuery();
  for (const k of Object.keys(S.f)) if (q.has(k)) S.f[k] = q.get(k);
  if (!METRICS.includes(S.f.metric)) S.f.metric = 'context';
  S.pickA = q.get('a') || S.pickA; S.pickB = q.get('b') || S.pickB;
}
const writeUrl = () => setHashQuery({ ...S.f, metric: S.f.metric === 'context' ? '' : S.f.metric, a: S.pickA, b: S.pickB });

const since = () => (S.f.days ? Math.floor(Date.now() / 1000) - Number(S.f.days) * 86400 : '');

async function loadRuns() {
  S.status = 'loading';
  const p = new URLSearchParams({ limit: String(S.limit) });
  if (S.f.agent) p.set('agent', S.f.agent);
  if (S.f.q) p.set('q', S.f.q);
  if (since()) p.set('since', String(since()));
  try {
    const r = await call('GET', `/benchmark/runs?${p}`);
    S.runs = Array.isArray(r) ? r : [];
    S.status = S.runs.length ? 'ready' : 'empty';
  } catch (e) { S.runs = []; S.status = isUnavailable(e) ? 'unavailable' : 'error'; S.error = e?.message || String(e); }
}
async function loadSeries() {
  S.seriesStatus = 'loading';
  const p = new URLSearchParams({ metric: S.f.metric, agg: 'day' });
  if (S.f.pipeline) p.set('pipeline', S.f.pipeline);
  try { S.series = await call('GET', `/benchmark/timeseries?${p}`); S.seriesStatus = 'ready'; }
  catch (e) { S.series = null; S.seriesStatus = isUnavailable(e) ? 'unavailable' : 'error'; }
}
async function loadDetail(id) {
  S.detailStatus = 'loading'; S.detail = null;
  try { S.detail = await call('GET', `/benchmark/runs/${encodeURIComponent(id)}`); S.detailStatus = 'ready'; }
  catch (e) { S.detailStatus = isUnavailable(e) ? 'unavailable' : 'error'; S.detailError = e?.message || String(e); }
}

const visible = () => S.runs.filter((r) => !S.f.pipeline || r.pipeline === S.f.pipeline);
const pipelines = () => [...new Set([...S.runs.map((r) => r.pipeline), ...(lab.stats?.groups || []).map((g) => g.pipeline)])].filter(Boolean).sort();
const agents = () => [...new Set(S.runs.map((r) => r.agent).filter(Boolean))].sort();

/* ---- waterfall (ANA-209) -------------------------------------------------- */
export function waterfall(run) {
  const t = I18N.lab;
  const w = runSpans(run);
  if (!w.spans.length) return `<p class="lab-note">${esc(t.wfNone)}</p>`;
  const total = Math.max(w.total ?? 0, w.sum) || 1;
  const W = 640; const RH = 22; const L = 130; const H = w.spans.length * RH + 18;
  const x = (v) => L + (v / total) * (W - L - 8);
  const bars = w.spans.map((s, i) => `<g><text x="${L - 6}" y="${i * RH + 15}" text-anchor="end" class="chart-axis-text">${esc(t.stage[s.id])}</text>
    <rect x="${x(s.start).toFixed(1)}" y="${i * RH + 4}" width="${Math.max(2, x(s.end) - x(s.start)).toFixed(1)}" height="${RH - 8}" rx="3" fill="var(--chart-${(i % 8) + 1})"><title>${esc(t.stage[s.id])}: ${esc(fmtMs(s.ms))}</title></rect></g>`).join('');
  const tolerance = w.withinTolerance === null ? na() : esc(w.withinTolerance ? t.wfWithin : t.wfOutside);
  return `<svg class="wf-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t.wfAria)}">${bars}</svg>
    ${table({ caption: t.wfTableCaption, cols: [
      { label: t.colStage, html: (s) => esc(t.stage[s.id]) },
      { label: t.wfStart, num: true, html: (s) => vMs(s.start) },
      { label: t.wfEnd, num: true, html: (s) => vMs(s.end) },
      { label: t.colMeanMs, num: true, html: (s) => vMs(s.ms) }], rows: w.spans })}
    <p class="lab-note">${esc(t.wfSum)}: ${vMs(w.sum)} · ${esc(t.colTotal)}: ${vMs(w.total)} · ${esc(t.wfUnattributed)}: ${vMs(w.unattributed)} · ${tolerance}</p>
    <p class="lab-note">${esc(t.wfReconstructed)}</p>`;
}

function detailHtml() {
  const t = I18N.lab;
  if (S.detailStatus === 'idle') return `<p class="lab-note">${esc(t.pickRunHint)}</p>`;
  if (S.detailStatus === 'loading') return loadingBlock(skeletonTable({ rows: 3, cols: 3 }), I18N.app.loading);
  if (S.detailStatus !== 'ready') return emptyState({ title: t.unavailableTitle, description: S.detailError, variant: 'error', compact: true });
  const r = S.detail; const m = r.metrics || {};
  const kv = (k, v) => `<div class="readonly-kv"><span class="readonly-kv-label">${esc(k)}</span><span class="readonly-kv-value tabular">${v}</span></div>`;
  return `<h3 class="card-title">${esc(t.detailTitle)} <code>${esc(r.run_id)}</code></h3>
    <div class="readonly-kv-grid">${kv(t.colPipeline, esc(pipeName(r.pipeline)))}${kv(t.detailWhen, esc(fmtDate(r.created_at)))}
      ${kv(t.colCtx, vTok(m.context_tokens))}${kv(t.colCand, vTok(m.candidate_tokens_before_filter))}${kv(t.colTotal, vMs(m.total_latency_ms))}</div>
    <h4 class="lab-subtitle">${esc(t.wfTitle)}</h4>${waterfall(r)}`;
}

function rowsCols() {
  const t = I18N.lab;
  const sel = (id) => (id === S.pickA ? ' is-picked' : id === S.pickB ? ' is-picked' : '');
  return [
    { key: 'created_at', label: t.colWhen, width: '1.1fr', render: (r) => esc(fmtDateShort(r.created_at)) },
    { key: 'pipeline', label: t.colPipeline, width: '1.2fr', render: (r) => esc(pipeName(r.pipeline)) },
    { key: 'agent', label: t.colAgent, width: '0.8fr', render: (r) => esc(r.agent || '—') },
    { key: 'ctx', label: t.colCtx, width: '0.9fr', align: 'right', render: (r) => vTok(r.metrics?.context_tokens) },
    { key: 'lat', label: t.colTotal, width: '0.9fr', align: 'right', render: (r) => vMs(r.metrics?.total_latency_ms) },
    { key: 'ab', label: 'A/B', width: '1.1fr', render: (r) => `<span class="ab-pick${sel(r.run_id)}">
      <button type="button" class="btn btn-ghost btn-sm" data-action="pick-a" data-run="${esc(r.run_id)}" aria-pressed="${r.run_id === S.pickA}" aria-label="${esc(t.setA)} ${esc(r.run_id)}">A</button>
      <button type="button" class="btn btn-ghost btn-sm" data-action="pick-b" data-run="${esc(r.run_id)}" aria-pressed="${r.run_id === S.pickB}" aria-label="${esc(t.setB)} ${esc(r.run_id)}">B</button></span>` },
  ];
}

function filtersHtml() {
  const t = I18N.lab;
  const opt = (v, cur, label) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label ?? v)}</option>`;
  return `<form class="lab-filters" data-action="explorer-filters" role="search" aria-label="${esc(t.filtersAria)}">
    <label class="lab-field"><span>${esc(t.colPipeline)}</span><select class="select-control" name="pipeline">${opt('', S.f.pipeline, t.all)}${pipelines().map((p) => opt(p, S.f.pipeline, pipeName(p))).join('')}</select></label>
    <label class="lab-field"><span>${esc(t.colAgent)}</span><select class="select-control" name="agent">${opt('', S.f.agent, t.all)}${agents().map((a) => opt(a, S.f.agent)).join('')}${S.f.agent && !agents().includes(S.f.agent) ? opt(S.f.agent, S.f.agent) : ''}</select></label>
    <label class="lab-field"><span>${esc(t.period)}</span><select class="select-control" name="days">${opt('', S.f.days, t.all)}${['1', '7', '30'].map((d) => opt(d, S.f.days, `${d} ${t.days}`)).join('')}</select></label>
    <label class="lab-field"><span>${esc(t.search)}</span><input class="input-control" type="search" name="q" value="${esc(S.f.q)}" placeholder="${esc(t.searchPh)}" /></label>
    <label class="lab-field"><span>${esc(t.metric)}</span><select class="select-control" name="metric">${METRICS.map((m) => opt(m, S.f.metric, t.metrics[m])).join('')}</select></label>
    <button type="submit" class="btn btn-secondary btn-sm">${esc(t.apply)}</button>
  </form>`;
}

function seriesHtml() {
  const t = I18N.lab;
  if (S.seriesStatus === 'loading') return loadingBlock(skeletonTable({ rows: 2, cols: 3 }), I18N.app.loading);
  if (S.seriesStatus !== 'ready') return `<p class="lab-note">${na()} — ${esc(t.seriesUnavailable)}</p>`;
  const names = Object.keys(S.series?.series || {});
  if (!names.length || !names.some((n) => S.series.series[n].points_returned > 0)) return `<p class="lab-note">${esc(t.seriesEmpty)}</p>`;
  return `<div class="field-row"><label class="lab-field"><span>${esc(t.colPipeline)}</span>
    <select class="select-control" data-action="series-pipeline">${names.map((n) => `<option value="${esc(n)}">${esc(pipeName(n))}</option>`).join('')}</select></label>
    <span class="lab-n">${esc(fmtNum(S.series.total_runs_in_range))} runs · ${esc(S.series.sampled ? t.sampled : t.notSampled)}</span></div>
    <div id="history-line-chart-mount" class="u-ef46fd"></div>`;
}

function paintChart(root, name) {
  const el = root.querySelector('#history-line-chart-mount');
  chart?.destroy?.(); chart = null;
  if (!el || !S.series) return;
  const sel = name || root.querySelector('[data-action="series-pipeline"]')?.value;
  const pts = S.series.series?.[sel]?.points || [];
  if (!pts.length) { el.textContent = I18N.lab.seriesEmpty; return; }
  chart = createLineChart(el, {
    data: pts.map((p) => ({ x: p.bucket ?? p.day ?? p.x, y: p.y })), xKey: 'x',
    series: [{ key: 'y', label: I18N.lab.metrics[S.f.metric], color: 'var(--chart-2)', fill: true }],
    yFormatter: (v) => fmtNum(v), xFormatter: (v) => String(v).slice(-5), height: 230, ariaLabel: `${I18N.lab.metrics[S.f.metric]} — ${pipeName(sel)}`,
  });
}

function view() {
  const t = I18N.lab;
  let list;
  if (S.status === 'loading' || S.status === 'idle') list = loadingBlock(skeletonTable({ rows: 6, cols: 5 }), I18N.app.loading);
  else if (S.status === 'unavailable' || S.status === 'error') list = emptyState({ title: S.status === 'unavailable' ? t.unavailableTitle : t.errorTitle, description: S.error, variant: 'error', action: { label: I18N.app.errorRetry, action: 'explorer-reload', kind: 'secondary' } });
  else if (!visible().length) list = emptyState({ title: t.noRunsFilter, description: t.noRunsFilterDesc, variant: 'data' });
  else list = '<div id="history-vtable" class="u-be70d9"></div>';
  const abLink = S.pickA && S.pickB ? `<a class="btn btn-lab btn-sm" href="#/compare/ab?a=${encodeURIComponent(S.pickA)}&b=${encodeURIComponent(S.pickB)}">${esc(t.compareAB)}</a>` : `<span class="lab-n">${esc(t.pickTwo)}</span>`;
  return `<div class="lab-view-container">${header(t.historyTitle, t.historyDesc)}
    ${filtersHtml()}
    <div class="card u-e68317"><div class="card-header"><h3 class="card-title">${esc(t.seriesTitle)}</h3></div>${seriesHtml()}</div>
    <div class="card u-b38a50"><div class="card-header"><h3 class="card-title">${esc(t.runsTitle)}</h3>
      <span class="section-count tabular">${esc(fmtNum(visible().length))} / ${esc(fmtNum(lab.stats?.total_runs ?? null))} runs</span> ${abLink}</div>
      ${list}
      ${S.status === 'ready' && S.runs.length >= S.limit ? `<div class="u-420527"><button type="button" class="btn btn-secondary btn-sm" data-action="load-more-history">${esc(t.loadMore)}</button></div>` : ''}
    </div>
    <div class="card u-1644b7" data-bind="run-detail" aria-live="polite">${detailHtml()}</div>
  </div>`;
}

function mountTable(root) {
  table$?.destroy?.(); table$ = null;
  const el = root.querySelector('#history-vtable');
  if (!el) return;
  table$ = createVirtualTable({
    container: el, columns: rowsCols(), rows: visible(), rowHeight: 38, height: 340, rowKey: (r) => r.run_id,
    ariaLabel: I18N.lab.runsTitle,
    onRowClick: async (r, _i, ev) => {
      const b = ev.target.closest('[data-action]');
      if (b && (b.dataset.action === 'pick-a' || b.dataset.action === 'pick-b')) {
        if (b.dataset.action === 'pick-a') S.pickA = b.dataset.run; else S.pickB = b.dataset.run;
        writeUrl(); repaint(root); return;
      }
      await loadDetail(r.run_id);
      const box = root.querySelector('[data-bind="run-detail"]');
      if (box) box.innerHTML = detailHtml();
    },
  });
}
function repaint(root) {
  chart?.destroy?.(); chart = null;
  root.innerHTML = view();
  mountTable(root);
  if (S.seriesStatus === 'ready') paintChart(root);
}
async function refresh(root, { runs = true, series = true } = {}) {
  const my = ++token;
  const jobs = [];
  if (runs) { S.status = 'loading'; jobs.push(loadRuns()); }
  if (series) { S.seriesStatus = 'loading'; jobs.push(loadSeries()); }
  repaint(root);
  await Promise.all(jobs);
  if (my !== token || !root.isConnected) return;
  repaint(root);
}

export function render() { return view(); }

export function mount(root) {
  readUrl();
  const onClick = (e) => {
    const a = e.target.closest('[data-action]');
    if (!a) return;
    const act = a.dataset.action;
    if (act === 'load-more-history') { S.limit += PAGE; refresh(root, { series: false }); }
    else if (act === 'explorer-reload') refresh(root);
  };
  const onSubmit = (e) => {
    const f = e.target.closest('form[data-action="explorer-filters"]');
    if (!f) return;
    e.preventDefault();
    const d = new FormData(f);
    const prevMetric = S.f.metric;
    for (const k of Object.keys(S.f)) S.f[k] = String(d.get(k) ?? '');
    S.limit = PAGE; writeUrl();
    refresh(root, { series: true, runs: true });
    void prevMetric;
  };
  const onChange = (e) => {
    const sp = e.target.closest('[data-action="series-pipeline"]');
    if (sp) paintChart(root, sp.value);
  };
  root.addEventListener('click', onClick); root.addEventListener('submit', onSubmit); root.addEventListener('change', onChange);
  root._historyCleanup = () => {
    root.removeEventListener('click', onClick); root.removeEventListener('submit', onSubmit); root.removeEventListener('change', onChange);
    token += 1; chart?.destroy?.(); chart = null; table$?.destroy?.(); table$ = null;
  };
  ensureLab().then(() => { if (root.isConnected) refresh(root); });
}
export function unmount(root) { if (root?._historyCleanup) { root._historyCleanup(); delete root._historyCleanup; } }
void STAGES;
void fmtDateShort;
