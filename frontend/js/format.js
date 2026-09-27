// format.js — formatting, safe metric access, aggregation. All metric keys are optional.

export const PIPELINES = ['baseline', 'graphify', 'graphify_jev'];
export const PIPELINE_LABEL = {
  baseline: 'Baseline',
  graphify: 'Graphify',
  graphify_jev: 'Graphify + JEV',
};
/** Chart colours per pipeline. Neutral/info hues — NOT good/bad signals. */
export const PIPELINE_COLOR = { baseline: '#6F7A87', graphify: '#3B82F6', graphify_jev: '#8B5CF6' };

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Safe nested get. Returns null (never undefined/NaN) when absent. */
export function get(obj, path) {
  let cur = obj;
  for (const k of String(path).split('.')) {
    if (cur == null || typeof cur !== 'object') return null;
    cur = cur[k];
  }
  return cur === undefined || Number.isNaN(cur) ? null : cur;
}
export const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/* ---- number formatting ------------------------------------------------- */
export function fmtNum(v, digits) {
  const n = num(v);
  if (n === null) return '—';
  if (digits !== undefined) return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (Number.isInteger(n)) return n.toLocaleString('en-US');
  if (Math.abs(n) >= 100) return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 1) return n.toLocaleString('en-US', { maximumFractionDigits: 1 });
  return n.toPrecision(3);
}
export function fmtCompact(v) {
  const n = num(v);
  if (n === null) return '—';
  const a = Math.abs(n);
  if (a >= 1e6) return `${(n / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${(n / 1e3).toFixed(0)}k`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return fmtNum(n);
}
export function fmtMs(v) {
  const n = num(v);
  if (n === null) return '—';
  if (n >= 60000) return `${(n / 60000).toFixed(1)}m`;
  if (n >= 1000) return `${(n / 1000).toFixed(2)}s`;
  return `${fmtNum(Math.round(n * 10) / 10)}ms`;
}
export function fmtCost(v) {
  const n = num(v);
  if (n === null) return '—';
  if (n === 0) return '$0';
  if (Math.abs(n) < 0.01) return `$${n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
  return `$${n.toFixed(4)}`;
}
export function fmtPct(v, digits = 1) {
  const n = num(v);
  return n === null ? '—' : `${(n * 100).toFixed(digits)}%`;
}
export function fmtDate(epochSeconds) {
  const n = num(epochSeconds);
  if (n === null) return '—';
  return new Date(n * 1000).toLocaleString();
}
export function fmtDateShort(epochSeconds) {
  const n = num(epochSeconds);
  if (n === null) return '—';
  return new Date(n * 1000).toLocaleDateString(undefined, { month: 'short', day: '2-digit' });
}

/* ---- statistics -------------------------------------------------------- */
export function mean(values) {
  const v = values.map(num).filter((x) => x !== null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
export function sum(values) {
  const v = values.map(num).filter((x) => x !== null);
  return v.length ? v.reduce((a, b) => a + b, 0) : null;
}
export function median(values) {
  const v = values.map(num).filter((x) => x !== null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/* ---- run helpers ------------------------------------------------------- */
/** Warm-up runs are excluded from every chart/aggregate (mode==='warmup' or warmup flag). */
export const isWarmup = (r) => Boolean(r?.warmup) || r?.mode === 'warmup';
export const realRuns = (runs) => (runs || []).filter((r) => !isWarmup(r));
export const metricsOf = (r) => (r && r.metrics) || {};

/** Group runs by pipeline. */
export function byPipeline(runs) {
  const g = { baseline: [], graphify: [], graphify_jev: [] };
  for (const r of runs || []) if (g[r.pipeline]) g[r.pipeline].push(r);
  return g;
}

/** Mean of metrics[path] across runs. */
export const meanMetric = (runs, path) => mean((runs || []).map((r) => get(metricsOf(r), path)));
export const sumMetric = (runs, path) => sum((runs || []).map((r) => get(metricsOf(r), path)));

/**
 * Tokens spent by the paid judge (JEV). Prefers the backend key `judge_tokens`;
 * falls back to jev_input + jev_output for runs recorded before that key existed.
 */
export function judgeTokens(m) {
  const direct = num(get(m, 'judge_tokens'));
  if (direct !== null) return direct;
  const parts = [get(m, 'jev_input_tokens'), get(m, 'jev_output_tokens')].map(num).filter((x) => x !== null);
  return parts.length ? parts.reduce((a, b) => a + b, 0) : null;
}

/**
 * TOTAL tokens actually spent on a run — the honest per-query cost, deliberately
 * distinct from the final context. Prefers backend `total_tokens_spent`; falls back to
 * judge_tokens + context_tokens (i.e. jev_input + jev_output + context_tokens) so the
 * 170 historical runs that predate the key still chart correctly.
 * Final-context reduction can hide a total-token blow-up.
 */
export function totalTokens(m) {
  const direct = num(get(m, 'total_tokens_spent'));
  if (direct !== null) return direct;
  const parts = [judgeTokens(m), get(m, 'context_tokens')].map(num).filter((x) => x !== null);
  return parts.length ? parts.reduce((a, b) => a + b, 0) : null;
}

/**
 * token_amplification = total_tokens_spent / context_tokens.
 * > 1 means the pipeline spends more tokens than it delivers as context.
 * Prefers the backend key; otherwise derived from the fallbacks above.
 */
export function tokenAmplification(m) {
  const direct = num(get(m, 'token_amplification'));
  if (direct !== null) return direct;
  const spent = totalTokens(m);
  const ctx = num(get(m, 'context_tokens'));
  return spent !== null && ctx ? spent / ctx : null;
}
/** Recall from expected_sources_found {expected, found, recall}. */
export const recallOf = (m) => num(get(m, 'expected_sources_found.recall'));
/** Total cost: prefer total_cost, else model_cost+jev_cost, else jev_cost. */
export function costOf(m) {
  const t = num(get(m, 'total_cost'));
  if (t !== null) return t;
  const mc = num(get(m, 'model_cost'));
  const jc = num(get(m, 'jev_cost'));
  if (mc === null && jc === null) return null;
  return (mc || 0) + (jc || 0);
}

/* ---- deltas ------------------------------------------------------------ */
/**
 * Delta vs a reference value.
 * lowerIsBetter=true -> a decrease is an improvement (green).
 * Returns {pct, text, cls} where cls ∈ good|bad|flat.
 */
export function delta(value, reference, lowerIsBetter = true) {
  const v = num(value); const r = num(reference);
  if (v === null || r === null || r === 0) return { pct: null, text: 'n/a', cls: 'flat' };
  const pct = (v - r) / Math.abs(r);
  const sign = pct > 0 ? '+' : '';
  const text = `${sign}${(pct * 100).toFixed(Math.abs(pct) < 0.1 ? 1 : 0)}%`;
  let cls = 'flat';
  if (Math.abs(pct) >= 0.02) cls = (pct < 0) === lowerIsBetter ? 'good' : 'bad';
  return { pct, text, cls };
}

/** Derive project entities from vault source paths. Fully data-driven — no hardcoded names. */
export function projectFromPath(file) {
  const parts = String(file || '').split('/').filter(Boolean);
  if (parts.length >= 2 && /^\d{2}-/.test(parts[0])) {
    return { area: parts[0], project: parts[1].replace(/\.md$/, '') };
  }
  if (parts.length >= 1 && /^\d{2}-/.test(parts[0])) return { area: parts[0], project: '(raiz da área)' };
  return { area: '(raiz do vault)', project: parts[0] || '(desconhecido)' };
}
