/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * LAB DATA — dados REAIS do Laboratório (ANA-200/203). Nada aqui inventa valores:
 * uma métrica ausente é `null` e a UI a mostra como "indisponível". Sem mock quando a API falha.
 *   /benchmark/stats  /benchmark/runs  /benchmark/runs/{id}  /benchmark/timeseries  /api/alerts
 */
import { call, isUnavailable } from './anamnesia-api.js';
import { num } from './format.js';

export const RUN_SAMPLE = 500;
/** Estágios com latência gravada por run (chave em metrics_json). Ordem = ordem do pipeline. */
export const STAGES = [
  { id: 'retrieval', key: 'retrieval_latency_ms' },
  { id: 'graphify', key: 'graphify_latency_ms' },
  { id: 'free', key: 'free_stage_latency_ms' },
  { id: 'filter', key: 'filter_latency_ms' },
  { id: 'jev', key: 'jev_latency_ms' },
  { id: 'full_note', key: 'full_note_latency_ms' },
  { id: 'context', key: 'context_build_latency_ms' },
  { id: 'generation', key: 'generation_latency_ms' },
];

export const lab = {
  status: 'idle', // idle | loading | ready | empty | unavailable | error
  error: '',
  stats: null,
  runs: [],
  alerts: null,
  loadedAt: 0,
};
let inflight = null;

const isWarm = (r) => Boolean(r?.warmup) || r?.mode === 'warmup';

/** Carrega (uma vez; `force` recarrega). Nunca lança: o estado fica em `lab.status`. */
export function ensureLab(force = false) {
  if (inflight) return inflight;
  if (!force && (lab.status === 'ready' || lab.status === 'empty')) return Promise.resolve(lab);
  lab.status = 'loading';
  inflight = (async () => {
    try {
      const [stats, runs] = await Promise.all([
        call('GET', '/benchmark/stats'),
        call('GET', `/benchmark/runs?limit=${RUN_SAMPLE}`),
      ]);
      lab.stats = stats || { groups: [], total_runs: 0 };
      lab.runs = Array.isArray(runs) ? runs : [];
      lab.status = (lab.stats.total_runs || 0) > 0 ? 'ready' : 'empty';
      lab.error = '';
    } catch (e) {
      lab.stats = null; lab.runs = [];
      lab.status = isUnavailable(e) ? 'unavailable' : 'error';
      lab.error = (e && e.message) || String(e);
    }
    try { lab.alerts = await call('GET', '/api/alerts'); } catch { lab.alerts = null; }
    lab.loadedAt = Date.now();
    inflight = null;
    return lab;
  })();
  return inflight;
}

/* ---- aggregation (puro: testável em node) ------------------------------- */
/** Média ponderada por `n` das descrições {n, mean, p95} de um mesmo pipeline. null se n total = 0. */
export function weightedMean(groups, key) {
  let n = 0; let s = 0;
  for (const g of groups) {
    const d = g?.[key];
    if (d && num(d.mean) !== null && num(d.n) > 0) { n += d.n; s += d.mean * d.n; }
  }
  return n ? { mean: s / n, n } : null;
}
export function maxP95(groups, key) {
  const v = groups.map((g) => num(g?.[key]?.p95)).filter((x) => x !== null);
  return v.length ? Math.max(...v) : null;
}

/** Linhas por pipeline a partir de /benchmark/stats (todas as execuções, sem warm-up). */
export function pipelineRows(stats) {
  const byPipe = new Map();
  for (const g of stats?.groups || []) {
    if (!byPipe.has(g.pipeline)) byPipe.set(g.pipeline, []);
    byPipe.get(g.pipeline).push(g);
  }
  return [...byPipe.entries()].map(([pipeline, gs]) => {
    const ctx = weightedMean(gs, 'context_tokens');
    const cand = weightedMean(gs, 'candidate_tokens_before_filter');
    const cost = weightedMean(gs, 'total_cost') || weightedMean(gs, 'jev_cost');
    return {
      pipeline,
      runs: gs.reduce((a, g) => a + (g.runs || 0), 0),
      ctx: ctx?.mean ?? null,
      cand: cand?.mean ?? null,
      wasted: ctx && cand ? Math.max(0, cand.mean - ctx.mean) : null,
      reduction: weightedMean(gs, 'context_reduction')?.mean ?? null,
      latMean: weightedMean(gs, 'total_latency_ms')?.mean ?? null,
      latP95: maxP95(gs, 'total_latency_ms'),
      cost: cost?.mean ?? null,
      costKind: weightedMean(gs, 'total_cost') ? 'total_cost' : weightedMean(gs, 'jev_cost') ? 'jev_cost' : null,
      judge: weightedMean(gs, 'jev_input_tokens')?.mean ?? null,
      groups: gs,
    };
  });
}

/** Média por estágio por pipeline, calculada sobre a AMOSTRA de runs carregada (n explícito). */
export function stageMeans(runs) {
  const acc = new Map();
  for (const r of runs || []) {
    if (isWarm(r) || r.error) continue;
    const p = r.pipeline || '—';
    if (!acc.has(p)) acc.set(p, { runs: 0, total: [], stages: Object.fromEntries(STAGES.map((s) => [s.id, []])) });
    const a = acc.get(p); a.runs += 1;
    const m = r.metrics || {};
    if (num(m.total_latency_ms) !== null) a.total.push(m.total_latency_ms);
    for (const s of STAGES) if (num(m[s.key]) !== null) a.stages[s.id].push(m[s.key]);
  }
  const avg = (v) => (v.length ? v.reduce((x, y) => x + y, 0) / v.length : null);
  return [...acc.entries()].map(([pipeline, a]) => ({
    pipeline, sample: a.runs, total: avg(a.total),
    stages: Object.fromEntries(STAGES.map((s) => [s.id, { mean: avg(a.stages[s.id]), n: a.stages[s.id].length }])),
  }));
}

/** Recall esperado (quando a run tem rótulo) por pipeline sobre a amostra. */
export function recallByPipeline(runs) {
  const acc = new Map();
  for (const r of runs || []) {
    const v = num(r?.metrics?.expected_sources_found?.recall);
    if (v === null || isWarm(r)) continue;
    const a = acc.get(r.pipeline) || { s: 0, n: 0 };
    a.s += v; a.n += 1; acc.set(r.pipeline, a);
  }
  return new Map([...acc].map(([k, a]) => [k, { mean: a.s / a.n, n: a.n }]));
}

/* ---- URL de estado: #/compare/history?pipeline=… (ANA-203) ------------- */
export function hashQuery(hash) {
  const h = String(hash ?? (typeof location !== 'undefined' ? location.hash : ''));
  const i = h.indexOf('?');
  return new URLSearchParams(i >= 0 ? h.slice(i + 1) : '');
}
/** Atualiza a query do hash SEM disparar hashchange (não re-renderiza o shell). */
export function setHashQuery(params) {
  if (typeof location === 'undefined') return;
  const base = location.hash.split('?')[0] || '#/compare/history';
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== '' && v != null) q.set(k, String(v));
  const s = q.toString();
  history.replaceState(null, '', `${location.pathname}${location.search}${base}${s ? `?${s}` : ''}`);
}

/* ---- diff A×B (ANA-204), puro ------------------------------------------ */
const pick = (r, k) => num(r?.metrics?.[k]);
export const DIFF_METRICS = [
  { key: 'context_tokens', lowerBetter: true },
  { key: 'candidate_tokens_before_filter', lowerBetter: null },
  { key: 'total_tokens_spent', lowerBetter: true },
  { key: 'total_latency_ms', lowerBetter: true },
  { key: 'documents_kept', lowerBetter: null },
  { key: 'documents_dropped', lowerBetter: null },
  { key: 'jev_cost', lowerBetter: true },
  { key: 'total_cost', lowerBetter: true },
];
export function diffRuns(a, b) {
  const metrics = DIFF_METRICS.map(({ key, lowerBetter }) => {
    const x = pick(a, key); const y = pick(b, key);
    const d = x !== null && y !== null ? y - x : null;
    return { key, a: x, b: y, delta: d, pct: d !== null && x ? (d / x) * 100 : null, lowerBetter };
  });
  const files = (r) => (r?.sources || []).map((s) => s.file).filter(Boolean);
  const fa = new Set(files(a)); const fb = new Set(files(b));
  const both = [...fa].filter((f) => fb.has(f));
  const union = new Set([...fa, ...fb]);
  const ca = String(a?.context ?? ''); const cb = String(b?.context ?? '');
  return {
    metrics,
    sources: { onlyA: [...fa].filter((f) => !fb.has(f)), onlyB: [...fb].filter((f) => !fa.has(f)), both,
      jaccard: union.size ? both.length / union.size : null },
    context: { hasA: ca !== '', hasB: cb !== '', lenA: ca.length, lenB: cb.length, same: ca !== '' && ca === cb },
    meta: { pipelineA: a?.pipeline ?? null, pipelineB: b?.pipeline ?? null, queryA: a?.query ?? null, queryB: b?.query ?? null },
  };
}
export function diffToMarkdown(a, b, d) {
  const f = (v) => (v === null || v === undefined ? 'indisponível' : String(Math.round(v * 1e6) / 1e6));
  const L = [`# Comparação de runs A × B`, '', `- A: \`${a.run_id}\` (${d.meta.pipelineA ?? '—'})`, `- B: \`${b.run_id}\` (${d.meta.pipelineB ?? '—'})`, '',
    '| Métrica | A | B | Δ | Δ % |', '| --- | ---: | ---: | ---: | ---: |'];
  for (const m of d.metrics) L.push(`| ${m.key} | ${f(m.a)} | ${f(m.b)} | ${f(m.delta)} | ${m.pct === null ? 'indisponível' : `${m.pct.toFixed(1)}%`} |`);
  L.push('', `Fontes em comum: ${d.sources.both.length}; só em A: ${d.sources.onlyA.length}; só em B: ${d.sources.onlyB.length}; Jaccard: ${d.sources.jaccard === null ? 'indisponível' : d.sources.jaccard.toFixed(3)}`);
  return L.join('\n');
}

/* ---- waterfall (ANA-209) ------------------------------------------------- */
/**
 * Spans de UMA run. O gateway grava só DURAÇÕES por estágio (não t_start/t_end); os spans são
 * reconstruídos em sequência na ordem do pipeline e marcados `reconstructed: true`.
 * `unattributed` = total − soma (negativo ⇒ estágios sobrepostos ou medidos em paralelo).
 */
export function runSpans(run) {
  const m = run?.metrics || {};
  const total = num(m.total_latency_ms);
  let t = 0; const spans = [];
  for (const s of STAGES) {
    const d = num(m[s.key]);
    if (d === null || d <= 0) continue;
    spans.push({ id: s.id, key: s.key, start: t, end: t + d, ms: d });
    t += d;
  }
  const sum = t;
  return {
    spans, total, sum, reconstructed: true,
    unattributed: total === null ? null : total - sum,
    withinTolerance: total === null || total === 0 ? null : Math.abs(total - sum) / total <= 0.05,
  };
}
