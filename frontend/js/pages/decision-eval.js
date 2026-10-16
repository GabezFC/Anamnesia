/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * DECISION ENGINE — abas "Avaliação" (JEV × Laya × Hybrid × Adaptive) e "Histórico" (paginado, filtrável, exportável).
 * Dados: GET /api/decision/evaluation e /api/decision/history. Backend/benchmark -> sempre via esc().
 */
import { icon } from '../icons.js';
import { esc, fmtNum, fmtNumber, fmtPct, fmtMs, fmtDate } from '../format.js';
import { emptyState } from '../components/empty-state.js';
import { T, store, gate, stateBadge, labelBadge, valueWithLabel, cell } from './decision-ui.js';
import {
  evalColumns, verdict, benchMeta, HYBRID_STRATEGIES, STATES, PAGE_SIZES, filterHistory, paginate, stateCounts, historyToCsv, historyToJson, lab, isNum,
} from './decision-data.js';

/* ============================== Avaliação ============================== */
const es = { hybrid: 'laya_then_jev' };

const pctPoints = (v) => `${fmtNum(v, 1)}%`;
const ROWS = [
  { id: 'precision', key: 'precision', fmt: (v) => fmtPct(v), label: 'MEASURED' },
  { id: 'recall', key: 'recall', fmt: (v) => fmtPct(v), label: 'MEASURED' },
  { id: 'f1', key: 'f1', fmt: (v) => fmtNum(v, 3), label: 'MEASURED' },
  { id: 'avoided', key: 'avoidedPct', fmt: pctPoints, label: 'MEASURED' },
  { id: 'tokens', key: 'jevTokens', fmt: (v) => fmtNumber(v), label: 'ESTIMATED' },
  { id: 'layaP50', key: 'layaP50', fmt: (v) => fmtMs(v), label: 'ESTIMATED' },
  { id: 'layaP95', key: 'layaP95', fmt: (v) => fmtMs(v), label: 'ESTIMATED' },
  { id: 'fallbacks', key: 'fallbacks', fmt: (v) => fmtNumber(v), label: 'MEASURED' },
];

function colHead(c) {
  const t = T();
  const name = t.ov.provider[c.id];
  const sub = c.id === 'hybrid' ? t.ev.hybrid[c.strategy] : (c.id === 'jev' ? 'proxy' : '');
  return `<th scope="col" class="num-col">${esc(name)}${sub ? ` <span class="dec-colsub">${esc(sub)}</span>` : ''}</th>`;
}

function divergenceHtml(ev) {
  const t = T().ev;
  const d = ev && ev.history;
  if (!d || !d.agreement_rate || lab(d.agreement_rate).value === null) return `<p class="dec-muted">${esc(t.divNone)}</p>`;
  const tile = (label, x, fmt) => `<div class="dec-tile"><span class="dec-tile-label">${esc(label)}</span><span class="dec-tile-value">${valueWithLabel(x, fmt)}</span></div>`;
  return `<div class="dec-tiles">${tile(t.n, d.n, (v) => fmtNumber(v))}${tile(t.agreement, d.agreement_rate, (v) => fmtPct(v))}${tile(t.survival, d.survival_agreement_rate, (v) => fmtPct(v))}${tile(t.kappa, d.cohen_kappa, (v) => fmtNum(v, 3))}</div>`;
}

function evalBody() {
  const t = T();
  const ev = store.evaluation.data || {};
  const meta = benchMeta(ev);
  const benchProblem = ev.bench && ev.bench.error ? t.ev.benchError : null;
  const jevReal = `<div class="callout-notice dec-jevreal" role="note"><span class="callout-notice-icon">${icon('alertTriangle', '', 16)}</span><div class="callout-notice-body"><strong>${esc(t.ev.jevReal)}</strong> ${labelBadge('UNKNOWN')} ${esc(t.ev.jevRealDesc)}</div></div>`;
  const div = `<section class="card dec-section" aria-labelledby="dec-ev-div"><div class="card-header"><h2 class="card-title" id="dec-ev-div">${esc(t.ev.divTitle)}</h2></div>${divergenceHtml(ev)}</section>`;
  if (!meta) {
    return `${jevReal}${emptyState({ title: t.ev.noBenchTitle, description: benchProblem || t.ev.noBenchDesc, variant: 'data', compact: true })}${div}`;
  }
  const cols = evalColumns(ev, es.hybrid);
  const v = verdict(cols);
  const names = (ids) => ids.map((i) => t.ov.provider[i]).join(', ');
  const vText = v.kind === 'better' ? t.ev.verdictBetter.replace('{list}', names(v.better)) : (v.kind === 'none' ? t.ev.verdictNone : t.ev.verdictUnknown);
  const vIcon = v.kind === 'better' ? 'check' : (v.kind === 'none' ? 'info' : 'alertTriangle');
  const head = `<tr><th scope="col">${esc(t.ev.metric)}</th>${cols.map(colHead).join('')}</tr>`;
  const body = ROWS.map((r) => `<tr><th scope="row">${esc(t.ev[r.id])} ${labelBadge(r.label)}</th>${cols.map((c) => `<td class="num-col tabular">${cell(c.data ? c.data[r.key] : null, r.fmt)}</td>`).join('')}</tr>`).join('');
  const usd = `<tr><th scope="row">${esc(t.ev.usd)} ${labelBadge('UNKNOWN')}</th>${cols.map(() => `<td class="num-col"><span class="dec-na">${esc(t.ev.notRun)}</span></td>`).join('')}</tr>`;
  const opts = HYBRID_STRATEGIES.map((s) => `<option value="${s}" ${es.hybrid === s ? 'selected' : ''}>${esc(t.ev.hybrid[s])}</option>`).join('');
  const ds = meta.dataset ? `<p class="dec-muted">${esc(t.ev.dataset)}: ${esc(t.ev.datasetItems.replace('{items}', fmtNumber(meta.dataset.items)).replace('{q}', fmtNumber(meta.dataset.queries)))} · ${esc(meta.dataset.source || '')}</p>` : '';
  const labels = Object.entries(meta.labels || {}).map(([k, x]) => `<li><code>${esc(k)}</code>: ${esc(x)}</li>`).join('');
  const sweep = meta.sweep.length ? `<h3 class="dec-h3">${esc(t.ev.sweepTitle)}</h3><div class="table-container"><table class="table dec-table"><thead><tr><th scope="col">${esc(t.ev.sweepName)}</th><th scope="col" class="num-col">${esc(t.ev.precision)}</th><th scope="col" class="num-col">${esc(t.ev.recall)}</th><th scope="col" class="num-col">${esc(t.ev.f1)}</th><th scope="col" class="num-col">${esc(t.ev.avoided)}</th></tr></thead><tbody>${meta.sweep.map((s) => `<tr><th scope="row">${esc(s.name)}</th><td class="num-col tabular">${cell(s.precision, fmtPct)}</td><td class="num-col tabular">${cell(s.recall, fmtPct)}</td><td class="num-col tabular">${cell(s.f1, (x) => fmtNum(x, 3))}</td><td class="num-col tabular">${cell(s.jev_avoided_pct, pctPoints)}</td></tr>`).join('')}</tbody></table></div>` : '';
  const fault = meta.fault ? `<h3 class="dec-h3">${esc(t.ev.faultTitle)}</h3><p class="dec-muted">${esc(t.ev.faultDesc)}</p><div class="table-container"><table class="table dec-table"><thead><tr><th scope="col">${esc(t.ev.op)}</th><th scope="col">${esc(t.ev.result)}</th><th scope="col">${esc(t.ev.action)}</th></tr></thead><tbody>${Object.entries(meta.fault).map(([op, r]) => `<tr><th scope="row">${esc(op)}</th><td>${(r.decisions || []).map((d) => stateBadge(d === 'UNJUDGED' ? 'UNCERTAIN' : (d === 'QUARANTINE' ? 'BLOCKED' : d))).join(' ')} ${stateBadge('FALLBACK')}</td><td><code>${esc(r.fallback_action)}</code></td></tr>`).join('')}</tbody></table></div>` : '';
  return `${jevReal}
    <section class="card dec-section" aria-labelledby="dec-ev-title">
      <div class="card-header"><div><h2 class="card-title" id="dec-ev-title">${esc(t.ev.title)}</h2><p class="card-subtitle">${esc(t.ev.desc)}</p></div>
        <label class="dec-field">${esc(t.ev.hybridPick)}<span class="select-control-wrap"><select class="select-control" data-bind="dec-hybrid">${opts}</select></span></label></div>
      <p class="dec-verdict dec-verdict-${v.kind}" role="status">${icon(vIcon, '', 14)} <span>${esc(vText)}</span></p>
      <div class="table-container"><table class="table dec-table dec-eval-table"><caption class="sr-only">${esc(t.ev.title)}</caption><thead>${head}</thead><tbody>${body}${usd}</tbody></table></div>
      ${ds}
      <details class="dec-adv"><summary>${esc(t.ov.advTitle)}</summary>${labels ? `<ul class="dec-list">${labels}</ul>` : ''}${sweep}${fault}</details>
    </section>${div}`;
}

export const evalTab = {
  html: () => gate(['evaluation'], evalBody, 'table'),
  mount(root, ctx) {
    const onChange = (e) => {
      const s = e.target.closest('[data-bind="dec-hybrid"]');
      if (!s) return;
      es.hybrid = HYBRID_STRATEGIES.includes(s.value) ? s.value : 'laya_then_jev';
      ctx.repaint('evaluation');
      root.querySelector('[data-bind="dec-hybrid"]')?.focus();
    };
    root.addEventListener('change', onChange);
    return { cleanup: () => root.removeEventListener('change', onChange) };
  },
};

/* ============================== Histórico ============================== */
const hs = { q: '', provider: '', op: '', state: '', page: 1, size: 10 };
const OPS = ['retrieval', 'memory', 'security'];

const records = () => (store.history.data && Array.isArray(store.history.data.records) ? store.history.data.records : []);
const filtered = () => filterHistory(records(), hs);

function rowHtml(r) {
  const t = T().hi;
  const sc = stateCounts(r);
  const badges = STATES.filter((s) => sc[s]).map((s) => stateBadge(s, sc[s])).join(' ') || '—';
  const strat = r.strategy ? `${r.provider} / ${r.strategy}` : (r.provider || '—');
  return `<tr>
    <td class="dec-nowrap">${esc(fmtDate(r.ts))}</td>
    <td><code class="dec-id" title="${esc(r.request_id)}">${esc(String(r.request_id || '').slice(0, 12))}</code><br><span class="dec-muted" title="${esc(r.query_hash)}">#${esc(String(r.query_hash || '').slice(0, 12))}</span>
      <span class="dec-muted">${esc(r.op || '')}${r.project ? ` · ${esc(r.project)}` : ` · ${esc(t.unknownProject)}`}</span></td>
    <td>${esc(strat)}</td>
    <td class="num-col tabular">${esc(fmtNumber(r.n_items))}</td>
    <td><div class="dec-states">${badges}</div></td>
    <td class="num-col tabular">${esc(fmtMs(r.latency_ms))}</td>
    <td class="num-col tabular">${esc(fmtNumber(r.cache_hits))}</td>
    <td class="num-col tabular">${esc(fmtNumber(r.fallbacks))}</td></tr>`;
}

function resultsHtml() {
  const t = T().hi;
  const all = records();
  if (!all.length) return emptyState({ title: T().emptyTitle, description: T().emptyDesc, variant: 'data', compact: true });
  const f = filtered();
  if (!f.length) return emptyState({ title: t.noMatchTitle, description: t.noMatchDesc, variant: 'search', compact: true, action: { label: t.clear, action: 'dec-hi-clear', kind: 'secondary' } });
  const p = paginate(f, hs.page, hs.size);
  hs.page = p.page;
  const total = store.history.data && isNum(store.history.data.total) ? store.history.data.total : all.length;
  const sizes = PAGE_SIZES.map((n) => `<option value="${n}" ${hs.size === n ? 'selected' : ''}>${n}</option>`).join('');
  return `<div class="table-container"><table class="table dec-table" aria-label="${esc(t.tableAria)}"><thead><tr>
      <th scope="col">${esc(t.time)}</th><th scope="col">${esc(t.request)}</th><th scope="col">${esc(t.strategy)}</th><th scope="col" class="num-col">${esc(t.items)}</th>
      <th scope="col">${esc(t.states)}</th><th scope="col" class="num-col">${esc(t.latency)}</th><th scope="col" class="num-col">${esc(t.cache)}</th><th scope="col" class="num-col">${esc(t.fallbacks)}</th></tr></thead>
      <tbody>${p.rows.map(rowHtml).join('')}</tbody></table></div>
    <div class="dec-pager">
      <p class="dec-muted" role="status" aria-live="polite">${esc(t.showing.replace('{from}', p.from).replace('{to}', p.to).replace('{n}', f.length).replace('{loaded}', all.length).replace('{total}', total))}</p>
      <div class="dec-pager-ctl">
        <label class="dec-field-inline">${esc(t.rowsPerPage)} <span class="select-control-wrap"><select class="select-control" data-bind="dec-hi-size">${sizes}</select></span></label>
        <button type="button" class="btn btn-secondary btn-sm" data-action="dec-hi-prev" ${p.page <= 1 ? 'disabled' : ''}>${esc(t.prev)}</button>
        <span class="dec-muted">${esc(t.page.replace('{p}', p.page).replace('{n}', p.pages))}</span>
        <button type="button" class="btn btn-secondary btn-sm" data-action="dec-hi-next" ${p.page >= p.pages ? 'disabled' : ''}>${esc(t.next)}</button>
      </div></div>`;
}

function historyBody() {
  const t = T().hi;
  const provs = [...new Set(['jev', 'laya', 'hybrid', 'adaptive', ...records().map((r) => r.provider).filter(Boolean)])];
  const opt = (arr, cur, lblFn = (x) => x) => `<option value="">${esc(t.all)}</option>${arr.map((x) => `<option value="${esc(x)}" ${cur === x ? 'selected' : ''}>${esc(lblFn(x))}</option>`).join('')}`;
  const dis = records().length ? '' : 'disabled';
  return `<section class="card dec-section" aria-labelledby="dec-hi-title">
    <div class="card-header"><div><h2 class="card-title" id="dec-hi-title">${esc(t.title)}</h2><p class="card-subtitle">${esc(t.desc)}</p></div>
      <div class="dec-actions"><button type="button" class="btn btn-secondary btn-sm" data-action="dec-hi-export-csv" ${dis}>${icon('download', '', 13)} ${esc(t.exportCsv)}</button>
        <button type="button" class="btn btn-secondary btn-sm" data-action="dec-hi-export-json" ${dis}>${icon('download', '', 13)} ${esc(t.exportJson)}</button></div></div>
    <form class="dec-filters" role="search" aria-label="${esc(t.filters)}" data-bind="dec-hi-form">
      <label class="dec-field dec-field-grow">${esc(t.q)}<span class="input-control"><input type="search" name="q" value="${esc(hs.q)}" placeholder="${esc(t.qPh)}" autocomplete="off" data-bind="dec-hi-q" /></span></label>
      <label class="dec-field">${esc(t.provider)}<span class="select-control-wrap"><select class="select-control" name="provider">${opt(provs, hs.provider)}</select></span></label>
      <label class="dec-field">${esc(t.op)}<span class="select-control-wrap"><select class="select-control" name="op">${opt(OPS, hs.op, (x) => t[`op_${x}`])}</select></span></label>
      <label class="dec-field">${esc(t.state)}<span class="select-control-wrap"><select class="select-control" name="state">${opt(STATES, hs.state, (x) => T().state[x])}</select></span></label>
      <button type="button" class="btn btn-ghost btn-sm" data-action="dec-hi-clear">${esc(t.clear)}</button>
    </form>
    <p class="dec-muted">${esc(t.exportNote)}</p>
    <div data-bind="dec-hi-results">${resultsHtml()}</div>
  </section>`;
}

function download(name, mime, text) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const historyTab = {
  html: () => gate(['history'], historyBody, 'table'),
  mount(root, ctx) {
    let timer = null;
    const results = () => root.querySelector('[data-bind="dec-hi-results"]');
    const paintResults = () => { const r = results(); if (r) r.innerHTML = resultsHtml(); };
    const readForm = () => {
      const f = root.querySelector('[data-bind="dec-hi-form"]'); if (!f) return;
      const d = new FormData(f);
      ['q', 'provider', 'op', 'state'].forEach((k) => { hs[k] = String(d.get(k) || ''); });
      hs.page = 1;
    };
    const onInput = (e) => {
      if (!e.target.closest('[data-bind="dec-hi-q"]')) return;
      clearTimeout(timer); timer = setTimeout(() => { readForm(); paintResults(); }, 150);
    };
    const onChange = (e) => {
      if (e.target.closest('[data-bind="dec-hi-form"] select')) { readForm(); paintResults(); }
      const sz = e.target.closest('[data-bind="dec-hi-size"]');
      if (sz) { hs.size = PAGE_SIZES.includes(+sz.value) ? +sz.value : 10; hs.page = 1; paintResults(); root.querySelector('[data-bind="dec-hi-size"]')?.focus(); }
    };
    const onSubmit = (e) => { if (e.target.closest('[data-bind="dec-hi-form"]')) e.preventDefault(); };
    const focusAction = (a) => root.querySelector(`[data-action="${a}"]:not([disabled])`)?.focus();
    const onClick = (e) => {
      const el = e.target.closest('[data-action]'); if (!el) return;
      const a = el.getAttribute('data-action');
      if (a === 'dec-hi-prev') { hs.page -= 1; paintResults(); focusAction(a); }
      else if (a === 'dec-hi-next') { hs.page += 1; paintResults(); focusAction(a); }
      else if (a === 'dec-hi-clear') { Object.assign(hs, { q: '', provider: '', op: '', state: '', page: 1 }); ctx.repaint('history'); root.querySelector('[data-bind="dec-hi-q"]')?.focus(); }
      else if (a === 'dec-hi-export-csv') download('decision-history.csv', 'text/csv;charset=utf-8', historyToCsv(filtered()));
      else if (a === 'dec-hi-export-json') download('decision-history.json', 'application/json', historyToJson(filtered()));
    };
    root.addEventListener('input', onInput); root.addEventListener('change', onChange);
    root.addEventListener('submit', onSubmit); root.addEventListener('click', onClick);
    return { cleanup: () => { clearTimeout(timer); root.removeEventListener('input', onInput); root.removeEventListener('change', onChange); root.removeEventListener('submit', onSubmit); root.removeEventListener('click', onClick); } };
  },
};
