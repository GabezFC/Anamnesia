/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA MEMORY PAGE (#/memory)
 * Prévia de busca (GET /api/memory/search-preview, sem gravar execução) + última busca real
 * (GET /api/memory/last-search) com fontes, score, tokens e o contexto entregue ao agente.
 * Tudo que vem do backend passa por esc().
 */
import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc, fmtDate, fmtNumber } from '../format.js';
import { searchPreview, lastSearch, isUnavailable } from '../anamnesia-api.js';
import { skeletonTable, skeletonKpis, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';
import { extrasHtml, mountExtras } from './memory-extras.js';

const st = {
  q: '', scope: '', max: 8,
  preview: { status: 'idle', data: null, error: '' }, // idle | loading | ok | error
  last: { status: 'loading', data: null, error: '' }, // loading | ok | empty | error
  showContext: false,
};

const nf = (v) => fmtNumber(v);
const sc = (v) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(3) : '—');

export function renderSourcesTable(sources) {
  const t = I18N.memory;
  return `
    <div class="table-container"><table class="table memory-table">
      <thead><tr>
        <th>${esc(t.colFile)}</th><th>${esc(t.colSection)}</th>
        <th class="num-col">${esc(t.colScore)}</th><th class="num-col">${esc(t.colTokens)}</th><th>${esc(t.colDecision)}</th>
      </tr></thead>
      <tbody>${sources.map((s) => `
        <tr>
          <td class="memory-file" title="${esc(s.file)}">${esc(s.file)}</td>
          <td>${esc(s.section || '—')}</td>
          <td class="num-col tabular">${esc(sc(s.score ?? s.relevance))}</td>
          <td class="num-col tabular">${esc(nf(s.tokens))}</td>
          <td>${s.decision ? `<span class="badge-origin badge-origin-measured">${esc(s.decision)}</span>` : '—'}</td>
        </tr>`).join('')}
      </tbody></table></div>`;
}

export function renderTotals(tokens) {
  const t = I18N.memory;
  const tk = tokens || {};
  const items = [
    [t.totalContext, tk.context], [t.totalCandidates, tk.candidates],
    [t.totalSources, tk.sources_sum], ...(tk.total_spent != null ? [[t.totalSpent, tk.total_spent]] : []),
  ];
  return `<div class="memory-totals" aria-label="${esc(t.totalsTitle)}">${items.map(([l, v]) => `
    <div class="memory-total"><span class="memory-total-label">${esc(l)}</span><span class="memory-total-value tabular">${esc(nf(v))}</span></div>`).join('')}</div>`;
}

function previewBody() {
  const t = I18N.memory;
  const p = st.preview;
  if (p.status === 'loading') return loadingBlock(skeletonKpis(3) + skeletonTable({ rows: 5, cols: 5 }), t.searching);
  if (p.status === 'error') return emptyState({ title: t.errorTitle, description: p.error, variant: 'error', compact: true });
  if (p.status !== 'ok') return emptyState({ title: t.previewEmptyTitle, description: t.previewEmptyDesc, variant: 'search', compact: true });
  const srcs = p.data.sources || [];
  if (!srcs.length) return emptyState({ title: t.previewNoneTitle, description: t.previewNoneDesc, variant: 'search', compact: true });
  return `${renderTotals(p.data.tokens)}
    <div class="memory-meta">${esc(t.pipeline)}: <strong>${esc(p.data.pipeline || '—')}</strong></div>
    ${renderSourcesTable(srcs)}`;
}

function lastBody() {
  const t = I18N.memory;
  const l = st.last;
  if (l.status === 'loading') return loadingBlock(skeletonTable({ rows: 3, cols: 5 }), t.lastTitle);
  if (l.status === 'error') return emptyState({ title: t.lastErrorTitle, description: l.error, variant: 'error', compact: true });
  if (l.status === 'empty') return emptyState({ title: t.lastEmptyTitle, description: t.lastEmptyDesc, variant: 'data', compact: true });
  const d = l.data;
  const ctx = typeof d.context === 'string' ? d.context : '';
  return `
    <div class="memory-meta">
      <span>${esc(t.queryLabel)}: <strong>${esc(d.query || '—')}</strong></span>
      <span>${esc(t.pipeline)}: ${esc(d.pipeline || '—')}</span>
      <span>${esc(t.when)}: ${esc(d.created_at ? fmtDate(d.created_at) : '—')}</span>
      ${d.latency_ms != null ? `<span>${esc(t.latency)}: ${esc(nf(Math.round(d.latency_ms)))} ms</span>` : ''}
      ${d.cache_hit != null ? `<span>${esc(d.cache_hit ? t.cacheHit : t.cacheMiss)}</span>` : ''}
    </div>
    ${renderTotals(d.tokens)}
    ${(d.sources || []).length ? renderSourcesTable(d.sources) : ''}
    <div class="memory-actions">
      <button type="button" class="btn btn-secondary btn-sm" data-action="memory-toggle-context" aria-expanded="${st.showContext}">
        ${icon('eye', '', 13)} ${esc(st.showContext ? t.hideContext : t.viewContext)}</button>
      ${st.showContext && ctx ? `<button type="button" class="btn btn-ghost btn-sm" data-action="memory-copy-context">${icon('copy', '', 13)} ${esc(t.copyContext)}</button>` : ''}
    </div>
    ${st.showContext ? `<div class="memory-context"><div class="card-title">${esc(t.contextTitle)}</div>
      ${ctx ? `<pre class="memory-context-pre">${esc(ctx)}</pre>` : `<p class="state-desc">${esc(t.contextEmpty)}</p>`}</div>` : ''}`;
}

export function render() {
  const t = I18N.memory;
  return `
    <div class="memory-page page-fade-slide">
      <header class="memory-header">
        <h1 class="page-title">${esc(t.title)}</h1>
        <p class="page-subtitle">${esc(t.subtitle)}</p>
      </header>
      <form class="memory-search card" data-action="memory-search-form" role="search">
        <label class="memory-field memory-field-grow"><span>${esc(t.queryLabel)}</span>
          <div class="input-control">${icon('search', '', 14)}
            <input type="text" name="q" data-bind="mem-q" value="${esc(st.q)}" placeholder="${esc(t.queryPlaceholder)}" autocomplete="off" /></div></label>
        <label class="memory-field"><span>${esc(t.scopeLabel)}</span>
          <div class="input-control"><input type="text" name="scope" value="${esc(st.scope)}" placeholder="${esc(t.scopePlaceholder)}" autocomplete="off" /></div></label>
        <label class="memory-field memory-field-sm"><span>${esc(t.maxLabel)}</span>
          <div class="input-control"><input type="number" name="max" min="1" max="50" value="${esc(st.max)}" /></div></label>
        <button type="submit" class="btn btn-primary" ${st.preview.status === 'loading' ? 'disabled' : ''}>${icon('search', '', 14)} ${esc(st.preview.status === 'loading' ? t.searching : t.searchBtn)}</button>
      </form>
      <section class="card memory-section" aria-labelledby="mem-src-title">
        <div class="card-header"><div class="card-title" id="mem-src-title">${esc(t.sourcesTitle)}</div></div>
        <div data-bind="mem-preview" aria-live="polite">${previewBody()}</div>
      </section>
      <section class="card memory-section" aria-labelledby="mem-last-title">
        <div class="card-header"><div class="card-title" id="mem-last-title">${esc(t.lastTitle)}</div>
          <button type="button" class="btn btn-ghost btn-sm" data-action="memory-refresh-last">${icon('refresh', '', 13)} ${esc(t.refresh)}</button></div>
        <div data-bind="mem-last">${lastBody()}</div>
      </section>
      ${extrasHtml()}
    </div>`;
}

function paint(root) {
  const a = root.querySelector('[data-bind="mem-preview"]');
  const b = root.querySelector('[data-bind="mem-last"]');
  if (a) a.innerHTML = previewBody();
  if (b) b.innerHTML = lastBody();
  const btn = root.querySelector('.memory-search button[type="submit"]');
  if (btn) btn.disabled = st.preview.status === 'loading';
}

const errText = (e) => (isUnavailable(e) ? I18N.app.backendUnavailableDesc : (e && e.message) || String(e));

async function loadLast(root) {
  st.last = { status: 'loading', data: null, error: '' };
  paint(root);
  try {
    const d = await lastSearch();
    st.last = d && d.found ? { status: 'ok', data: d, error: '' } : { status: 'empty', data: null, error: '' };
  } catch (e) {
    st.last = { status: 'error', data: null, error: errText(e) };
  }
  if (root.isConnected) paint(root);
}

async function runSearch(root) {
  const q = st.q.trim();
  if (!q) return;
  st.preview = { status: 'loading', data: null, error: '' };
  paint(root);
  try {
    const d = await searchPreview({ q, maxResults: st.max, scope: st.scope.trim() });
    st.preview = { status: 'ok', data: d || { sources: [] }, error: '' };
  } catch (e) {
    st.preview = { status: 'error', data: null, error: errText(e) };
  }
  if (root.isConnected) paint(root);
}

export function mount(root) {
  const onClick = (e) => {
    const el = e.target.closest('[data-action]');
    if (!el) return;
    const a = el.getAttribute('data-action');
    if (a === 'memory-refresh-last') loadLast(root);
    else if (a === 'memory-toggle-context') { st.showContext = !st.showContext; paint(root); }
    else if (a === 'memory-copy-context') navigator.clipboard?.writeText(st.last.data?.context || '').catch(() => {});
  };
  const onSubmit = (e) => {
    if (!e.target.closest('[data-action="memory-search-form"]')) return;
    e.preventDefault();
    const f = new FormData(e.target);
    st.q = String(f.get('q') || '');
    st.scope = String(f.get('scope') || '');
    st.max = Math.min(50, Math.max(1, parseInt(f.get('max'), 10) || 8));
    runSearch(root);
  };
  root.addEventListener('click', onClick);
  root.addEventListener('submit', onSubmit);
  const stopExtras = mountExtras(root);
  root._memoryCleanup = () => { root.removeEventListener('click', onClick); root.removeEventListener('submit', onSubmit); stopExtras(); };
  loadLast(root);
}

export function unmount(root) {
  if (root && root._memoryCleanup) { root._memoryCleanup(); delete root._memoryCleanup; }
}
