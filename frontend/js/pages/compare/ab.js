/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: COMPARAÇÃO A×B (#/compare/ab?a=…&b=…) — ANA-204.
 * Duas runs reais (/benchmark/runs/{id}): diferença de métricas, fontes e contexto; exporta Markdown local.
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtPct } from '../../format.js';
import { call, isUnavailable } from '../../anamnesia-api.js';
import { hashQuery, setHashQuery, diffRuns, diffToMarkdown } from '../../lab-data.js';
import { emptyState } from '../../components/empty-state.js';
import { loadingBlock, skeletonTable } from '../../components/skeleton.js';
import { na, header, table } from './_shared.js';

const S = { a: '', b: '', ra: null, rb: null, status: 'idle', error: '' };
let token = 0;

async function fetchRun(id) { return call('GET', `/benchmark/runs/${encodeURIComponent(id)}`); }
async function load() {
  const my = ++token;
  if (!S.a || !S.b) { S.status = 'idle'; return; }
  S.status = 'loading';
  try {
    const [ra, rb] = await Promise.all([fetchRun(S.a), fetchRun(S.b)]);
    if (my !== token) return;
    S.ra = ra; S.rb = rb; S.status = 'ready';
  } catch (e) {
    if (my !== token) return;
    S.status = isUnavailable(e) && e.status !== 404 ? 'unavailable' : 'error'; S.error = e?.message || String(e);
  }
}

const nv = (v, f = fmtNum) => (v === null || v === undefined ? na() : esc(f(v)));

function result() {
  const t = I18N.lab;
  const d = diffRuns(S.ra, S.rb);
  const verdict = (m) => {
    if (m.delta === null || m.delta === 0) return '';
    if (m.lowerBetter === null) return '';
    return (m.delta < 0) === m.lowerBetter ? `<span class="ab-better">${esc(t.better)}</span>` : `<span class="ab-worse">${esc(t.worse)}</span>`;
  };
  const files = (arr) => (arr.length ? `<ul class="ab-files">${arr.map((f) => `<li><code>${esc(f)}</code></li>`).join('')}</ul>` : `<p class="lab-note">—</p>`);
  return `
    <p class="lab-note">A: <code>${esc(S.ra.run_id)}</code> (${esc(d.meta.pipelineA ?? '—')}) · B: <code>${esc(S.rb.run_id)}</code> (${esc(d.meta.pipelineB ?? '—')})</p>
    <div class="card">${table({ caption: t.abTableCaption, cols: [
      { label: t.metric, html: (m) => esc(t.abMetrics[m.key] || m.key) },
      { label: 'A', num: true, html: (m) => nv(m.a) },
      { label: 'B', num: true, html: (m) => nv(m.b) },
      { label: 'Δ', num: true, html: (m) => nv(m.delta, (v) => `${v > 0 ? '+' : ''}${fmtNum(v)}`) },
      { label: 'Δ %', num: true, html: (m) => nv(m.pct === null ? null : m.pct / 100, (v) => fmtPct(v, 1)) },
      { label: '', html: verdict }], rows: d.metrics })}</div>
    <div class="card u-1644b7">
      <h3 class="card-title">${esc(t.abSources)} <span class="lab-n">Jaccard ${d.sources.jaccard === null ? na() : esc(d.sources.jaccard.toFixed(2))}</span></h3>
      <div class="ab-cols"><div><h4 class="lab-subtitle">${esc(t.abOnlyA)} (${d.sources.onlyA.length})</h4>${files(d.sources.onlyA)}</div>
      <div><h4 class="lab-subtitle">${esc(t.abBoth)} (${d.sources.both.length})</h4>${files(d.sources.both)}</div>
      <div><h4 class="lab-subtitle">${esc(t.abOnlyB)} (${d.sources.onlyB.length})</h4>${files(d.sources.onlyB)}</div></div>
      <p class="lab-note">${d.context.hasA && d.context.hasB ? esc(t.abCtxSizes.replace('{a}', fmtNum(d.context.lenA)).replace('{b}', fmtNum(d.context.lenB)).replace('{same}', d.context.same ? t.yes : t.no)) : esc(t.abNoContext)}</p>
    </div>
    <p class="u-dd9991"><button type="button" class="btn btn-secondary btn-sm" data-action="ab-export">${esc(t.abExport)}</button>
      <a class="btn btn-ghost btn-sm" href="/api/benchmark/report.md" download="benchmark-report.md">${esc(I18N.lab.exportMd)}</a></p>`;
}

function view() {
  const t = I18N.lab;
  let body;
  if (S.status === 'idle') body = `<p class="lab-note">${esc(t.abHint)}</p>`;
  else if (S.status === 'loading') body = loadingBlock(skeletonTable({ rows: 5, cols: 4 }), I18N.app.loading);
  else if (S.status === 'ready') body = result();
  else body = emptyState({ title: S.status === 'unavailable' ? t.unavailableTitle : t.abNotFound, description: S.error, variant: 'error', compact: true });
  return `<div class="lab-view-container">${header(t.abTitle, t.abDesc)}
    <form class="lab-filters" data-action="ab-form" aria-label="${esc(t.abTitle)}">
      <label class="lab-field"><span>${esc(t.abRunA)}</span><input class="input-control font-mono" name="a" value="${esc(S.a)}" autocomplete="off" required /></label>
      <label class="lab-field"><span>${esc(t.abRunB)}</span><input class="input-control font-mono" name="b" value="${esc(S.b)}" autocomplete="off" required /></label>
      <button class="btn btn-secondary btn-sm" type="submit">${esc(t.compareAB)}</button></form>
    <div aria-live="polite">${body}</div></div>`;
}

export function render() { return view(); }
export function mount(root) {
  const q = hashQuery(); S.a = q.get('a') || S.a; S.b = q.get('b') || S.b;
  const paint = () => { if (root.isConnected) root.innerHTML = view(); };
  const onSubmit = async (e) => {
    const f = e.target.closest('form[data-action="ab-form"]'); if (!f) return;
    e.preventDefault(); const d = new FormData(f);
    S.a = String(d.get('a') || '').trim(); S.b = String(d.get('b') || '').trim();
    setHashQuery({ a: S.a, b: S.b });
    S.status = 'loading'; paint(); await load(); paint();
  };
  const onClick = (e) => {
    if (!e.target.closest('[data-action="ab-export"]') || S.status !== 'ready') return;
    const md = diffToMarkdown(S.ra, S.rb, diffRuns(S.ra, S.rb));
    const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = `ab-${S.a}-${S.b}.md`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  root.addEventListener('submit', onSubmit); root.addEventListener('click', onClick);
  root._abCleanup = () => { root.removeEventListener('submit', onSubmit); root.removeEventListener('click', onClick); token += 1; };
  if (S.a && S.b) { S.status = 'loading'; paint(); load().then(paint); }
}
export function unmount(root) { if (root?._abCleanup) { root._abCleanup(); delete root._abCleanup; } }
