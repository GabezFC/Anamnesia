// format.js — formatting, safe metric access, aggregation. All metric keys are optional.
// NOTHING here invents a value: every function returns null when the source metric is absent,
// and the UI layer turns null into an explicit "Não medido" state.

/** Pipelines as defined by app/schemas/models.py PIPELINES (all four, including the cascade). */
export const PIPELINES = ['baseline', 'graphify', 'graphify_jev', 'graphify_jev_opt'];
export const PIPELINE_LABEL = {
  baseline: 'Baseline',
  graphify: 'Graphify',
  graphify_jev: 'Graphify + JEV',
  graphify_jev_opt: 'Graphify + JEV (otimizado)',
};
export const PIPELINE_SHORT = {
  baseline: 'Baseline',
  graphify: 'Graphify',
  graphify_jev: 'JEV',
  graphify_jev_opt: 'JEV opt',
};
/** Chart colours per pipeline. Neutral/info hues — NOT good/bad signals. */
export const PIPELINE_COLOR = {
  baseline: '#7C8794',
  graphify: '#3B82F6',
  graphify_jev: '#8B5CF6',
  graphify_jev_opt: '#14B8A6',
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Safe nested get. Returns null (never undefined/NaN) when absent. */
export function get(obj, path) {
  let cur = obj;
  for (const k of String(path).split('.')) {
    if (cur == null || typeof cur !== 'object') return null;
    cur = cur[k];
  }
  return cur === undefined || (typeof cur === 'number' && Number.isNaN(cur)) ? null : cur;
}
export const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/**
 * Display form of a filesystem path coming from the API.
 * The dashboard must NEVER print a developer's home directory, so this:
 *   1. drops everything up to and including the user name that follows a home marker
 *      (Users/, home/, Documents/), which is where a personal path always leaks; and
 *   2. abbreviates whatever is left of an absolute path to its last segments.
 * Relative paths (the default bundled corpus, `data/synthetic_vault`) pass through unchanged.
 */
export function safePath(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  let parts = raw.split(/[\\/]+/).filter(Boolean);
  const absolute = /^[a-zA-Z]:$/.test(parts[0] || '') || /^[\\/]/.test(raw);
  if (!absolute) return parts.join('/');
  const HOME_MARKERS = new Set(['users', 'home', 'documents', 'usr']);
  // Cut past "<marker>/<username>" wherever it appears.
  for (let i = parts.length - 2; i >= 0; i--) {
    if (HOME_MARKERS.has(parts[i].toLowerCase())) { parts = parts.slice(i + 2); break; }
  }
  // Drop a bare drive letter such as "C:".
  if (/^[a-zA-Z]:$/.test(parts[0] || '')) parts = parts.slice(1);
  if (!parts.length) return '—';
  return `…/${parts.slice(-3).join('/')}`;
}

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
/** Amplification formatted as "43.2×". */
export const fmtAmp = (v) => (num(v) === null ? '—' : `${num(v).toFixed(num(v) >= 10 ? 1 : 2)}×`);

/* ---- statistics -------------------------------------------------------- */
export function mean(values) {
  const v = (values || []).map(num).filter((x) => x !== null);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
export function sum(values) {
  const v = (values || []).map(num).filter((x) => x !== null);
  return v.length ? v.reduce((a, b) => a + b, 0) : null;
}
export function median(values) {
  const v = (values || []).map(num).filter((x) => x !== null).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}
/** Safe ratio: null unless both sides are real numbers and the denominator is non-zero. */
export const ratio = (a, b) => (num(a) !== null && num(b) ? num(a) / num(b) : null);

/* ---- run helpers ------------------------------------------------------- */
/** Warm-up runs are excluded from every chart/aggregate (mode==='warmup' or warmup flag). */
export const isWarmup = (r) => Boolean(r?.warmup) || r?.mode === 'warmup';
export const realRuns = (runs) => (runs || []).filter((r) => !isWarmup(r));
export const metricsOf = (r) => (r && r.metrics) || {};
/** Benchmark arm: runs written by the optimization harness use mode="<arm>|pass<N>". */
export const armOf = (r) => String(r?.mode || '').split('|')[0] || '—';

/** Group runs by pipeline. Unknown pipelines are kept under their own key. */
export function byPipeline(runs) {
  const g = {};
  for (const p of PIPELINES) g[p] = [];
  for (const r of runs || []) {
    if (!r || !r.pipeline) continue;
    (g[r.pipeline] = g[r.pipeline] || []).push(r);
  }
  return g;
}

/** Mean/sum of metrics[path] across runs. */
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
 * judge_tokens + context_tokens so runs recorded before that key still chart correctly.
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
 */
export function tokenAmplification(m) {
  const direct = num(get(m, 'token_amplification'));
  if (direct !== null) return direct;
  return ratio(totalTokens(m), get(m, 'context_tokens'));
}

/** Recall from expected_sources_found {expected, found, recall}. Null when the dataset had none. */
export const recallOf = (m) => num(get(m, 'expected_sources_found.recall'));

/**
 * Precision of the delivered context, derived ONLY when the dataset declared expected sources:
 *   found / documents_sent_to_model
 * Never estimated: null whenever either side is missing.
 */
export function precisionOf(m) {
  const found = num(get(m, 'expected_sources_found.found'));
  const sent = num(get(m, 'documents_sent_to_model'));
  if (found === null || sent === null || sent <= 0) return null;
  return Math.min(1, found / sent);
}

/** Paid judge questions actually asked (relevance + injection). */
export function judgeQuestions(m) {
  const parts = [get(m, 'jev_relevance_questions'), get(m, 'jev_injection_questions')]
    .map(num).filter((x) => x !== null);
  return parts.length ? parts.reduce((a, b) => a + b, 0) : null;
}

/** Judge requests (HTTP calls to the judge). */
export const judgeRequests = (m) => num(get(m, 'jev.request_count'));

/**
 * Tokens avoided by the FREE (deterministic, zero-token) stages, as reported by the backend:
 * prefilter_tokens_saved_estimate + dedup_near_tokens_saved_estimate + snippet_tokens_saved.
 * These are backend estimates and are labelled as such in the UI — never presented as measured spend.
 */
export function savedTokens(m) {
  const parts = ['prefilter_tokens_saved_estimate', 'dedup_near_tokens_saved_estimate', 'snippet_tokens_saved']
    .map((k) => num(get(m, k))).filter((x) => x !== null);
  return parts.length ? parts.reduce((a, b) => a + b, 0) : null;
}

/** Judge cache hits / lookups for one run. Returns {hits, lookups} with nulls when absent. */
export function cacheCounts(m) {
  const lookups = num(get(m, 'cache_layers.lookups'));
  const hits = num(get(m, 'cache_layers.hits'));
  if (lookups !== null && hits !== null) return { hits, lookups };
  const jevHits = num(get(m, 'jev_cache_hits')) ?? num(get(m, 'jev.cache_hits'));
  const received = num(get(m, 'jev.candidates_received')) ?? num(get(m, 'documents_sent_to_jev'));
  if (jevHits === null || received === null) return { hits: null, lookups: null };
  return { hits: jevHits, lookups: received };
}

/** Wave count actually executed by adaptive-K. 1 == no escalation (early stop / single wave). */
export function waveCount(m) {
  const sizes = get(m, 'jev_wave_sizes');
  if (Array.isArray(sizes) && sizes.length) return sizes.length;
  const w = num(get(m, 'jev_waves'));
  return w;
}

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
