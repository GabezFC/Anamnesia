/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * MEMÓRIA — extras da Onda 7 (somente leitura, nada de mock):
 *   ANA-208 explorador de recuperação (2 pipelines gratuitos lado a lado, sem gravar run)
 *   ANA-205 inspetor de contexto + atribuição de tokens (por run gravada)
 *   ANA-213 linhagem das notas salvas (origem + runs que as citaram)
 * Tudo que vem do backend passa por esc(); métrica ausente = "indisponível".
 */
import { I18N } from '../i18n.js';
import { esc, fmtNum, fmtDate, fmtPct, num } from '../format.js';
import { searchPreview, recentRuns, runDetail, memoryLineage, isUnavailable } from '../anamnesia-api.js';
import { emptyState } from '../components/empty-state.js';
import { loadingBlock, skeletonTable } from '../components/skeleton.js';

/* ------------------------------------------------------------------ helpers puros (testados em node) */
/** recall@k: fração dos arquivos esperados presentes nos k primeiros resultados. null se nada esperado. */
export function recallAtK(files, expected, k) {
  const exp = [...new Set((expected || []).map((s) => String(s).trim().replace(/\\/g, '/')).filter(Boolean))];
  if (!exp.length) return null;
  const top = (files || []).slice(0, k).map((f) => String(f).replace(/\\/g, '/'));
  const hit = exp.filter((e) => top.some((f) => f === e || f.endsWith(`/${e}`) || e.endsWith(`/${f}`)));
  return hit.length / exp.length;
}
/** Sobreposição entre duas listas ordenadas (NÃO é recall: não há rótulo de relevância). */
export function overlapOf(a, b) {
  const A = new Set(a || []); const B = new Set(b || []);
  const both = [...A].filter((x) => B.has(x));
  const union = new Set([...A, ...B]);
  return { both, onlyA: [...A].filter((x) => !B.has(x)), onlyB: [...B].filter((x) => !A.has(x)), jaccard: union.size ? both.length / union.size : null };
}
const NOTE_RE = /<note((?:\s+[\w-]+=(?:"[^"]*"|[^\s>"]+))*)\s*>\n?([\s\S]*?)\n?<\/note>/g;
const ATTR_RE = /([\w-]+)=(?:"([^"]*)"|([^\s>"]+))/g;
/** Quebra o contexto entregue em blocos <note> (fonte/seção/relevância/texto); `rest` = texto fora de blocos. */
export function splitContext(ctx) {
  const text = String(ctx ?? '');
  const blocks = []; let last = 0; let rest = '';
  for (const m of text.matchAll(NOTE_RE)) {
    rest += text.slice(last, m.index); last = m.index + m[0].length;
    const attrs = {};
    for (const a of m[1].matchAll(ATTR_RE)) attrs[a[1]] = a[2] ?? a[3];
    blocks.push({ source: attrs.source || '—', section: attrs.section || '', relevance: attrs.relevance != null ? Number(attrs.relevance) : null, text: m[2], chars: m[2].length });
  }
  rest += text.slice(last);
  return { blocks, rest: rest.trim() };
}
/** Funil de tokens de uma run (cada estágio só aparece se a run o gravou). */
export function tokenFunnel(run) {
  const m = run?.metrics || {};
  const steps = [
    ['candidates', m.candidate_tokens_before_filter],
    ['afterPrefilter', num(m.candidate_tokens_before_filter) !== null && num(m.prefilter_tokens_saved_estimate) !== null ? m.candidate_tokens_before_filter - m.prefilter_tokens_saved_estimate : null],
    ['survivors', m.survivor_tokens_snippets],
    ['context', m.context_tokens],
    ['judge', m.judge_tokens],
  ];
  return steps.map(([id, v]) => ({ id, tokens: num(v) }));
}
/** Tokens por fonte: usa `sources[].tokens` da run; share relativo à soma real. */
export function sourceShares(run) {
  const srcs = (run?.sources || []).map((s) => ({ file: s.file, section: s.section, tokens: num(s.tokens), decision: s.decision ?? null }));
  const sum = srcs.reduce((a, s) => a + (s.tokens || 0), 0);
  return { rows: srcs.map((s) => ({ ...s, share: sum && s.tokens !== null ? s.tokens / sum : null })), sum: sum || null };
}

const na = () => `<span class="lab-na">${esc(I18N.app.unavailable)}</span>`;
const errText = (e) => (isUnavailable(e) ? I18N.app.backendUnavailableDesc : (e && e.message) || String(e));
const state = {
  exp: { q: '', scope: '', max: 8, a: 'baseline', b: 'graphify', expected: '', ra: { s: 'idle' }, rb: { s: 'idle' } },
  insp: { runs: { s: 'idle', data: [] }, sel: '', run: { s: 'idle', data: null, error: '' }, ctx: false },
  lin: { s: 'idle', data: null, error: '', q: '' },
};

/* ------------------------------------------------------------------ ANA-208 explorador */
const PIPES = ['baseline', 'graphify'];
function expColumn(label, r, k, expected) {
  const t = I18N.memory;
  let body;
  if (r.s === 'loading') body = loadingBlock(skeletonTable({ rows: 4, cols: 3 }), t.searching);
  else if (r.s === 'error') body = emptyState({ title: t.errorTitle, description: r.error, variant: 'error', compact: true });
  else if (r.s !== 'ok') body = `<p class="lab-note">${esc(t.previewEmptyDesc)}</p>`;
  else {
    const srcs = r.data.sources || [];
    const rc = recallAtK(srcs.map((s) => s.file), expected, k);
    body = `<p class="lab-note">${esc(t.expTokens)}: <strong>${esc(fmtNum(r.data.tokens?.context ?? null))}</strong> · recall@${k}: ${rc === null ? na() : `<strong>${esc(fmtPct(rc, 0))}</strong>`}</p>
      <ol class="exp-list">${srcs.map((s) => `<li><code title="${esc(s.file)}">${esc(s.file)}</code> <span class="lab-n">${esc(s.section || '')}</span> <span class="tabular">${esc(num(s.score) === null ? '—' : s.score.toFixed(3))}</span></li>`).join('')}</ol>`;
  }
  return `<div class="exp-col" role="group" aria-label="${esc(label)}"><h4 class="lab-subtitle">${esc(label)}</h4>${body}</div>`;
}
function explorerHtml() {
  const t = I18N.memory; const e = state.exp;
  const opts = (cur) => PIPES.map((p) => `<option value="${p}"${p === cur ? ' selected' : ''}>${esc(p)}</option>`).join('');
  const both = e.ra.s === 'ok' && e.rb.s === 'ok';
  const ov = both ? overlapOf((e.ra.data.sources || []).map((s) => s.file), (e.rb.data.sources || []).map((s) => s.file)) : null;
  const expected = e.expected.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
  return `<form class="memory-search" data-action="exp-form" role="search" aria-label="${esc(t.expTitle)}">
      <label class="memory-field memory-field-grow"><span>${esc(t.queryLabel)}</span><div class="input-control"><input type="text" name="q" value="${esc(e.q)}" placeholder="${esc(t.queryPlaceholder)}" autocomplete="off" /></div></label>
      <label class="memory-field"><span>${esc(t.scopeLabel)}</span><div class="input-control"><input type="text" name="scope" value="${esc(e.scope)}" autocomplete="off" /></div></label>
      <label class="memory-field memory-field-sm"><span>${esc(t.maxLabel)}</span><div class="input-control"><input type="number" name="max" min="1" max="50" value="${esc(e.max)}" /></div></label>
      <label class="memory-field"><span>${esc(t.expPipelineA)}</span><select class="select-control" name="a">${opts(e.a)}</select></label>
      <label class="memory-field"><span>${esc(t.expPipelineB)}</span><select class="select-control" name="b">${opts(e.b)}</select></label>
      <label class="memory-field memory-field-grow"><span>${esc(t.expExpected)}</span><textarea class="input-control" name="expected" rows="2" placeholder="${esc(t.expExpectedPh)}">${esc(e.expected)}</textarea></label>
      <button type="submit" class="btn btn-primary">${esc(t.searchBtn)}</button></form>
    <p class="lab-note" role="note">${esc(t.expJevNote)}</p>
    <div class="exp-grid">${expColumn(`A · ${e.a}`, e.ra, e.max, expected)}${expColumn(`B · ${e.b}`, e.rb, e.max, expected)}</div>
    ${ov ? `<p class="lab-note">${esc(t.expOverlap)}: ${esc(fmtNum(ov.both.length))} · Jaccard ${ov.jaccard === null ? na() : esc(ov.jaccard.toFixed(2))} · ${esc(t.expNoRecall)}</p>` : ''}
    <p class="lab-note">${esc(t.expRecorded)}</p>`;
}
async function runExplorer(root) {
  const e = state.exp; const q = e.q.trim(); if (!q) return;
  e.ra = { s: 'loading' }; e.rb = { s: 'loading' }; paintExp(root);
  const one = async (pipeline) => {
    try { return { s: 'ok', data: await searchPreview({ q, maxResults: e.max, scope: e.scope.trim(), pipeline }) }; }
    catch (err) { return { s: 'error', error: errText(err) }; }
  };
  [e.ra, e.rb] = await Promise.all([one(e.a), one(e.b)]);
  if (root.isConnected) paintExp(root);
}

/* ------------------------------------------------------------------ ANA-205 inspetor */
function inspectorHtml() {
  const t = I18N.memory; const i = state.insp;
  if (i.runs.s === 'loading') return loadingBlock(skeletonTable({ rows: 3, cols: 3 }), t.searching);
  if (i.runs.s === 'error') return emptyState({ title: t.inspUnavailable, description: i.runs.error, variant: 'error', compact: true });
  if (!i.runs.data.length) return emptyState({ title: t.lastEmptyTitle, description: t.lastEmptyDesc, variant: 'data', compact: true });
  const sel = `<label class="memory-field"><span>${esc(t.inspPick)}</span><select class="select-control" data-action="insp-select">
    <option value="">—</option>${i.runs.data.map((r) => `<option value="${esc(r.run_id)}"${r.run_id === i.sel ? ' selected' : ''}>${esc(fmtDate(r.created_at))} · ${esc(r.pipeline)} · ${esc((r.query || r.run_id).slice(0, 60))}</option>`).join('')}</select></label>`;
  let body = `<p class="lab-note">${esc(t.inspHint)}</p>`;
  if (i.run.s === 'loading') body = loadingBlock(skeletonTable({ rows: 4, cols: 4 }), t.searching);
  else if (i.run.s === 'error') body = emptyState({ title: t.inspUnavailable, description: i.run.error, variant: 'error', compact: true });
  else if (i.run.s === 'ok') body = runInspection(i.run.data);
  return `${sel}<div aria-live="polite" data-bind="insp-body">${body}</div>`;
}
function runInspection(run) {
  const t = I18N.memory; const m = run.metrics || {};
  const funnel = tokenFunnel(run); const sh = sourceShares(run);
  const cands = run.candidates || [];
  const split = splitContext(run.context);
  const maxTok = Math.max(1, ...funnel.map((f) => f.tokens || 0));
  const kept = cands.filter((c) => c.decision === 'KEEP').length;
  return `
    <h4 class="lab-subtitle">${esc(t.inspFunnel)}</h4>
    <table class="table"><caption class="sr-only">${esc(t.inspFunnel)}</caption><thead><tr><th scope="col">${esc(t.inspStage)}</th><th scope="col" class="num-col">${esc(t.colTokens)}</th><th scope="col"><span class="sr-only">${esc(t.inspBar)}</span></th></tr></thead>
    <tbody>${funnel.map((f) => `<tr><td>${esc(t.funnel[f.id])}</td><td class="num-col tabular">${f.tokens === null ? na() : esc(fmtNum(f.tokens))}</td>
      <td aria-hidden="true">${f.tokens === null ? '' : `<span class="tok-bar" data-w="${Math.round((f.tokens / maxTok) * 100)}" data-css="--w:${Math.round((f.tokens / maxTok) * 100)}%"></span>`}</td></tr>`).join('')}</tbody></table>
    <h4 class="lab-subtitle">${esc(t.inspBySource)}</h4>
    ${sh.rows.length ? `<table class="table"><caption class="sr-only">${esc(t.inspBySource)}</caption><thead><tr><th scope="col">${esc(t.colFile)}</th><th scope="col">${esc(t.colDecision)}</th><th scope="col" class="num-col">${esc(t.colTokens)}</th><th scope="col" class="num-col">%</th></tr></thead>
      <tbody>${sh.rows.map((s, idx) => `<tr><td><span class="src-chip src-c${idx % 8}" aria-hidden="true"></span><code>${esc(s.file)}</code> <span class="lab-n">${esc(s.section || '')}</span></td><td>${esc(s.decision || '—')}</td>
      <td class="num-col tabular">${s.tokens === null ? na() : esc(fmtNum(s.tokens))}</td><td class="num-col tabular">${s.share === null ? na() : esc(fmtPct(s.share, 0))}</td></tr>`).join('')}</tbody></table>` : `<p class="lab-note">${na()}</p>`}
    <h4 class="lab-subtitle">${esc(t.inspCandidates)} <span class="lab-n">${esc(fmtNum(cands.length))} · KEEP ${esc(fmtNum(kept))}</span></h4>
    ${cands.length ? `<div class="table-container u-585391" tabindex="0" role="region" aria-label="${esc(t.inspCandidates)}"><table class="table"><thead><tr><th scope="col">${esc(t.colFile)}</th><th scope="col" class="num-col">${esc(t.colScore)}</th><th scope="col">${esc(t.colDecision)}</th><th scope="col" class="num-col">${esc(t.colTokens)}</th></tr></thead>
      <tbody>${cands.slice(0, 200).map((c) => `<tr><td><code>${esc(c.source_file)}</code></td><td class="num-col tabular">${num(c.score) === null ? na() : esc(c.score.toFixed(3))}</td><td>${esc(c.decision || '—')}</td><td class="num-col tabular">${num(c.tokens) === null ? na() : esc(fmtNum(c.tokens))}</td></tr>`).join('')}</tbody></table></div>` : `<p class="lab-note">${esc(t.inspNoCandidates)}</p>`}
    <div class="memory-actions"><button type="button" class="btn btn-secondary btn-sm" data-action="insp-toggle-ctx" aria-expanded="${state.insp.ctx}">${esc(state.insp.ctx ? t.hideContext : t.viewContext)}</button>
      ${run.context ? `<button type="button" class="btn btn-ghost btn-sm" data-action="insp-copy">${esc(t.copyContext)}</button><button type="button" class="btn btn-ghost btn-sm" data-action="insp-export">${esc(t.inspExport)}</button>` : ''}</div>
    ${state.insp.ctx ? (run.context ? `<div class="memory-context">${split.blocks.map((b, idx) => `<article class="ctx-block src-c${idx % 8}"><header><code>${esc(b.source)}</code> <span class="lab-n">${esc(b.section)}${b.relevance === null ? '' : ` · rel ${esc(b.relevance.toFixed(2))}`} · ${esc(fmtNum(b.chars))} ${esc(t.chars)}</span></header><pre class="memory-context-pre">${esc(b.text)}</pre></article>`).join('')}${split.rest ? `<pre class="memory-context-pre">${esc(split.rest)}</pre>` : ''}</div>` : `<p class="lab-note">${esc(t.contextEmpty)}</p>`) : ''}
    <p class="lab-note">${esc(t.inspTotal)}: ${num(m.context_tokens) === null ? na() : esc(fmtNum(m.context_tokens))} ${esc(t.colTokens.toLowerCase())}</p>`;
}
async function loadRuns(root) {
  const i = state.insp; i.runs = { s: 'loading', data: [] }; paintInsp(root);
  try { i.runs = { s: 'ok', data: await recentRuns(30) }; } catch (e) { i.runs = { s: 'error', data: [], error: errText(e) }; }
  if (root.isConnected) paintInsp(root);
}
async function loadRun(root, id) {
  const i = state.insp; i.sel = id;
  if (!id) { i.run = { s: 'idle', data: null }; paintInsp(root); return; }
  i.run = { s: 'loading', data: null }; paintInsp(root);
  try { i.run = { s: 'ok', data: await runDetail(id) }; } catch (e) { i.run = { s: 'error', data: null, error: errText(e) }; }
  if (root.isConnected) paintInsp(root);
}

/* ------------------------------------------------------------------ ANA-213 linhagem */
function lineageHtml() {
  const t = I18N.memory; const l = state.lin;
  if (l.s === 'loading' || l.s === 'idle') return loadingBlock(skeletonTable({ rows: 4, cols: 5 }), t.searching);
  if (l.s === 'error') return emptyState({ title: t.linUnavailable, description: l.error, variant: 'error', compact: true, action: { label: I18N.app.errorRetry, action: 'lin-reload', kind: 'secondary' } });
  const d = l.data; if (!d.count) return emptyState({ title: t.linEmpty, description: t.linEmptyDesc, variant: 'data', compact: true });
  const q = l.q.toLowerCase();
  const rows = d.notes.filter((n) => !q || `${n.title} ${n.project} ${n.source_agent}`.toLowerCase().includes(q));
  return `<p class="lab-note">${esc(t.linCoverage)}: <strong>${d.origin_coverage === null ? na() : esc(fmtPct(d.origin_coverage, 0))}</strong> (${esc(fmtNum(d.with_origin))}/${esc(fmtNum(d.count))})</p>
    <label class="memory-field"><span>${esc(t.linFilter)}</span><input class="input-control" type="search" data-action="lin-filter" value="${esc(l.q)}" /></label>
    <div class="table-container" tabindex="0" role="region" aria-label="${esc(t.linTitle)}"><table class="table"><caption class="sr-only">${esc(t.linTitle)}</caption>
    <thead><tr><th scope="col">${esc(t.linNote)}</th><th scope="col">${esc(t.linAgent)}</th><th scope="col">${esc(t.linProject)}</th><th scope="col">${esc(t.linCreated)}</th><th scope="col" class="num-col">${esc(t.linCited)}</th><th scope="col">${esc(t.linRuns)}</th></tr></thead>
    <tbody>${rows.map((n) => `<tr><td>${esc(n.title)}${n.superseded_by ? ` <span class="lab-n">→ ${esc(n.superseded_by)}</span>` : ''}</td><td>${n.source_agent ? esc(n.source_agent) : na()}</td><td>${esc(n.project || '—')}</td>
      <td class="tabular">${esc(n.created || '—')}</td><td class="num-col tabular">${esc(fmtNum(n.cited_by_count))}</td>
      <td>${n.cited_by.length ? n.cited_by.map((r) => `<a href="#/compare/history?a=${encodeURIComponent(r.run_id)}" class="lin-run"><code>${esc(r.run_id)}</code></a>`).join(' ') : '—'}</td></tr>`).join('')}</tbody></table></div>`;
}
async function loadLineage(root) {
  const l = state.lin; l.s = 'loading'; paintLin(root);
  try { l.data = await memoryLineage(); l.s = 'ok'; } catch (e) { l.s = isUnavailable(e) ? 'error' : 'error'; l.error = errText(e); }
  if (root.isConnected) paintLin(root);
}

/* ------------------------------------------------------------------ montagem */
export function extrasHtml() {
  const t = I18N.memory;
  const sec = (id, title, desc, inner) => `<section class="card memory-section" aria-labelledby="mem-${id}-title"><div class="card-header"><div><div class="card-title" id="mem-${id}-title">${esc(title)}</div><p class="card-subtitle">${esc(desc)}</p></div></div><div data-bind="mem-${id}">${inner}</div></section>`;
  return sec('exp', t.expTitle, t.expDesc, explorerHtml()) + sec('insp', t.inspTitle, t.inspDesc, inspectorHtml()) + sec('lin', t.linTitle, t.linDesc, lineageHtml());
}
const setHtml = (root, bind, html) => { const el = root.querySelector(`[data-bind="${bind}"]`); if (el) el.innerHTML = html; };
const paintExp = (root) => setHtml(root, 'mem-exp', explorerHtml());
const paintInsp = (root) => setHtml(root, 'mem-insp', inspectorHtml());
const paintLin = (root) => setHtml(root, 'mem-lin', lineageHtml());

export function mountExtras(root) {
  const onClick = (e) => {
    const el = e.target.closest('[data-action]'); if (!el) return;
    const a = el.getAttribute('data-action'); const run = state.insp.run.data;
    if (a === 'insp-toggle-ctx') { state.insp.ctx = !state.insp.ctx; paintInsp(root); }
    else if (a === 'insp-copy') navigator.clipboard?.writeText(run?.context || '').catch(() => {});
    else if (a === 'insp-export' && run?.context) {
      const url = URL.createObjectURL(new Blob([run.context], { type: 'text/plain;charset=utf-8' }));
      const link = document.createElement('a'); link.href = url; link.download = `context-${run.run_id}.txt`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } else if (a === 'lin-reload') loadLineage(root);
  };
  const onSubmit = (e) => {
    const f = e.target.closest('[data-action="exp-form"]'); if (!f) return;
    e.preventDefault(); const d = new FormData(f); const x = state.exp;
    x.q = String(d.get('q') || ''); x.scope = String(d.get('scope') || '');
    x.max = Math.min(50, Math.max(1, parseInt(d.get('max'), 10) || 8));
    x.a = PIPES.includes(d.get('a')) ? d.get('a') : 'baseline'; x.b = PIPES.includes(d.get('b')) ? d.get('b') : 'graphify';
    x.expected = String(d.get('expected') || '');
    runExplorer(root);
  };
  const onChange = (e) => { const s = e.target.closest('[data-action="insp-select"]'); if (s) loadRun(root, s.value); };
  const onInput = (e) => { const f = e.target.closest('[data-action="lin-filter"]'); if (f) { state.lin.q = f.value; const pos = f.selectionStart; paintLin(root); const n = root.querySelector('[data-action="lin-filter"]'); n?.focus(); n?.setSelectionRange(pos, pos); } };
  root.addEventListener('click', onClick); root.addEventListener('submit', onSubmit); root.addEventListener('change', onChange); root.addEventListener('input', onInput);
  loadRuns(root); loadLineage(root);
  return () => { root.removeEventListener('click', onClick); root.removeEventListener('submit', onSubmit); root.removeEventListener('change', onChange); root.removeEventListener('input', onInput); };
}
