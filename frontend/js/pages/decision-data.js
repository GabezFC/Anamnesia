/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * DECISION ENGINE (#/decision) — funções PURAS (sem DOM/I18N): normalização dos contratos REST
 * /api/decision/*, vocabulário de estados, colunas da avaliação, filtro/paginação/exportação do histórico
 * e diagnóstico do Laya. Testáveis em node. Nada aqui inventa número: ausente => UNKNOWN.
 */

export const LABELS = ['MEASURED', 'ESTIMATED', 'UNKNOWN'];

/** Estados exibidos na UI; o backend usa QUARANTINE/UNJUDGED (mapeados) e `fallback` como marca. */
export const STATES = ['KEEP', 'REVIEW', 'DROP', 'BLOCKED', 'FALLBACK', 'UNCERTAIN'];
export const STATE_ICON = { KEEP: 'check', REVIEW: 'eye', DROP: 'x', BLOCKED: 'eyeOff', FALLBACK: 'refresh', UNCERTAIN: 'info' };
const BACKEND_TO_STATE = { KEEP: 'KEEP', REVIEW: 'REVIEW', DROP: 'DROP', QUARANTINE: 'BLOCKED', BLOCKED: 'BLOCKED', UNJUDGED: 'UNCERTAIN', UNCERTAIN: 'UNCERTAIN', FALLBACK: 'FALLBACK' };

/** Decisão do backend (+ flag de fallback) -> estado da UI. Desconhecido => UNCERTAIN (nunca KEEP por omissão). */
export function stateOf(decision, { fallback = false } = {}) {
  if (fallback) return 'FALLBACK';
  return BACKEND_TO_STATE[String(decision || '').toUpperCase()] || 'UNCERTAIN';
}

/** Aceita `{value,label,source}` (labeled do backend) ou valor cru; rótulo ausente/valor nulo => UNKNOWN. */
export function lab(x) {
  if (x && typeof x === 'object' && !Array.isArray(x) && 'value' in x) {
    const label = LABELS.includes(x.label) ? x.label : 'UNKNOWN';
    const value = x.value === undefined ? null : x.value;
    return { value, label: value === null ? 'UNKNOWN' : label, source: x.source || '' };
  }
  if (x === null || x === undefined) return { value: null, label: 'UNKNOWN', source: '' };
  return { value: x, label: 'UNKNOWN', source: '' };   // cru, sem proveniência declarada: nunca finge MEASURED
}

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

/** Estado da carga de um recurso a partir de erro: offline (sem servidor/rota) vs erro. */
export function errKind(e) {
  const s = e && typeof e.status === 'number' ? e.status : -1;
  return [0, 404, 405, 501, 502, 503].includes(s) ? 'offline' : 'error';
}

/** Estado global: loading | offline | error | partial | ok, dado { status, config, metrics, evaluation } -> {status,...}. */
export function pageState(res) {
  const list = Object.values(res || {});
  if (!list.length || list.some((r) => r.status === 'loading')) return 'loading';
  const bad = list.filter((r) => r.status !== 'ok');
  if (!bad.length) return 'ok';
  if (bad.length === list.length) return bad.every((r) => r.status === 'offline') ? 'offline' : 'error';
  return 'partial';
}

/** Cartões de estratégia (JEV padrão; demais experimentais). */
export const PROVIDERS = ['jev', 'laya', 'hybrid', 'adaptive'];
export const PRESET_IDS = ['fast', 'balanced', 'quality'];
export const PRESET_ENV = { fast: 'MG_DECISION_PRESET=fast', balanced: 'MG_DECISION_PRESET=balanced', quality: 'MG_DECISION_PRESET=quality' };
export const PRESET_PROVIDER = { fast: 'laya', balanced: 'adaptive', quality: 'hybrid' };

// ---- Avaliação -----------------------------------------------------------------------------------------
const HYBRID_BY_STRATEGY = { laya_then_jev: 'Laya→JEV', jev_then_laya: 'JEV→Laya', ensemble: 'ensemble' };
export const HYBRID_STRATEGIES = Object.keys(HYBRID_BY_STRATEGY);

function rowFor(results, name) {
  return (results || []).find((r) => r && r.name === name) || null;
}
const pick = (r) => (r ? {
  precision: r.precision, recall: r.recall, f1: r.f1, avoidedPct: r.jev_avoided_pct, jevTokens: r.jev_tokens_est,
  layaP50: r.laya_ms_p50_est, layaP95: r.laya_ms_p95_est, fallbacks: r.fallbacks, items: r.items, name: r.name,
} : null);

/**
 * Colunas lado a lado JEV × Laya × Hybrid × Adaptive. `hybrid` = estratégia do híbrido mostrada
 * (laya_then_jev | jev_then_laya | ensemble). Coluna sem dado => `null` (a UI mostra "não medido").
 */
export function evalColumns(evaluation, hybrid = 'laya_then_jev') {
  const res = evaluation && evaluation.bench && Array.isArray(evaluation.bench.results) ? evaluation.bench.results : [];
  const hn = HYBRID_BY_STRATEGY[hybrid] || HYBRID_BY_STRATEGY.laya_then_jev;
  const jev = rowFor(res, 'JEV-only (padrão)') || res.find((r) => /^JEV-only/.test(r.name || '')) || null;
  return [
    { id: 'jev', data: pick(jev) },
    { id: 'laya', data: pick(rowFor(res, 'Laya-only')) },
    { id: 'hybrid', data: pick(rowFor(res, hn)), strategy: hybrid },
    { id: 'adaptive', data: pick(rowFor(res, 'adaptive')) },
  ];
}

/** Veredito derivado dos DADOS (não de texto fixo): quem superou o baseline JEV-only em F1. */
export function verdict(columns) {
  const base = columns.find((c) => c.id === 'jev')?.data;
  if (!base || !isNum(base.f1)) return { kind: 'unknown', better: [] };
  const better = columns.filter((c) => c.id !== 'jev' && c.data && isNum(c.data.f1) && c.data.f1 > base.f1).map((c) => c.id);
  return { kind: better.length ? 'better' : 'none', better, baselineF1: base.f1 };
}

export function benchMeta(evaluation) {
  const b = evaluation && evaluation.bench && !evaluation.bench.error ? evaluation.bench : null;
  if (!b) return null;
  return { dataset: b.dataset || null, labels: b.labels || {}, sweep: Array.isArray(b.adaptive_sweep) ? b.adaptive_sweep : [], fault: b.fault_injection || null,
    divergence: b.divergence_laya_vs_fakejev || null };
}

// ---- Histórico -----------------------------------------------------------------------------------------
export const PAGE_SIZES = [10, 25, 50];

/** f = { q, provider, op, state } — q casa request_id/query_hash/projeto; state: marca de resultado. */
export function filterHistory(records, f = {}) {
  const q = String(f.q || '').trim().toLowerCase();
  return (records || []).filter((r) => {
    if (f.provider && r.provider !== f.provider) return false;
    if (f.op && r.op !== f.op) return false;
    if (q && !`${r.request_id || ''} ${r.query_hash || ''} ${r.project || ''}`.toLowerCase().includes(q)) return false;
    if (f.state) {
      if (f.state === 'FALLBACK') return (r.fallbacks || 0) > 0;
      return Object.entries(r.decisions || {}).some(([k, n]) => n > 0 && stateOf(k) === f.state);
    }
    return true;
  });
}

export function paginate(rows, page = 1, size = 10) {
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / size));
  const p = Math.min(Math.max(1, page | 0 || 1), pages);
  return { page: p, pages, total, size, rows: rows.slice((p - 1) * size, p * size), from: total ? (p - 1) * size + 1 : 0, to: Math.min(total, p * size) };
}

/** Contagens por estado da UI de um registro do histórico (QUARANTINE->BLOCKED etc.) + FALLBACK. */
export function stateCounts(r) {
  const out = {};
  for (const [k, n] of Object.entries((r && r.decisions) || {})) {
    if (n > 0) { const s = stateOf(k); out[s] = (out[s] || 0) + n; }
  }
  if (r && r.fallbacks > 0) out.FALLBACK = r.fallbacks;
  return out;
}

const CSV_COLS = ['ts', 'request_id', 'op', 'project', 'provider', 'strategy', 'query_hash', 'n_items', 'latency_ms', 'cache_hits', 'fallbacks',
  'jev_requests', 'jev_calls_avoided', 'KEEP', 'REVIEW', 'DROP', 'QUARANTINE', 'UNJUDGED'];
const csvCell = (v) => {
  let s = v === null || v === undefined ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;          // neutraliza injeção de fórmula ao abrir no Excel
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};
/** Exporta SÓ campos de ID/hash/contagem (o backend já não guarda texto). */
export function historyToCsv(records) {
  const lines = [CSV_COLS.join(',')];
  for (const r of records || []) {
    lines.push(CSV_COLS.map((c) => csvCell(['KEEP', 'REVIEW', 'DROP', 'QUARANTINE', 'UNJUDGED'].includes(c) ? ((r.decisions || {})[c] || 0) : r[c])).join(','));
  }
  return lines.join('\r\n') + '\r\n';
}
export function historyToJson(records) {
  const keep = ['ts', 'request_id', 'op', 'project', 'provider', 'strategy', 'query_hash', 'n_items', 'decisions', 'latency_ms', 'calls', 'jev_requests', 'jev_calls_avoided', 'cache_hits', 'fallbacks', 'errors'];
  return JSON.stringify((records || []).map((r) => Object.fromEntries(keep.filter((k) => k in r).map((k) => [k, r[k]]))), null, 2);
}

// ---- Calibração ----------------------------------------------------------------------------------------
/** thresholds {provider:{keep,review,min_confidence}} -> linhas ordenadas (só leitura). */
export function thresholdRows(cfg) {
  const t = (cfg && cfg.thresholds) || {};
  return ['jev', 'laya', 'ensemble', 'adaptive'].filter((k) => t[k]).map((k) => ({ id: k, keep: t[k].keep, review: t[k].review, minConfidence: t[k].min_confidence }));
}

// ---- Diagnóstico Laya ----------------------------------------------------------------------------------
/**
 * health = status.providers.laya. Só afirma o que a API prova; o resto é UNKNOWN. `reason` do backend é
 * lido apenas como pista (inferido) para instalado/checkpoint.
 * Cada check: { id, state: ok|fail|unknown, detail, problem? } — problem = chave i18n do trio Problema/Causa/Ação.
 */
export function diagnoseLaya(health) {
  if (!health || typeof health !== 'object') {
    return { checks: ['installed', 'checkpoint', 'runtime', 'device', 'inference'].map((id) => ({ id, state: 'unknown', detail: '' })), problems: [], reachable: false };
  }
  const reason = String(health.reason || '');
  const mode = health.mode || null;
  const avail = health.available === true;
  const notInstalled = /pacote 'laya' não importável/.test(reason);
  const noWeights = /pesos multilingual ausentes/.test(reason);
  const serveBad = /MG_LAYA_SERVE_URL|porta 8000/.test(reason) && !avail;
  const off = /MG_LAYA_MODE=off/.test(reason);
  const checks = [];
  checks.push({ id: 'installed', state: avail && mode === 'inproc' ? 'ok' : (notInstalled ? 'fail' : (avail ? 'unknown' : 'unknown')), detail: notInstalled ? reason : '', problem: notInstalled ? 'notInstalled' : null });
  checks.push({ id: 'checkpoint', state: avail && mode === 'inproc' ? 'ok' : (noWeights ? 'fail' : 'unknown'), detail: noWeights ? reason : '', problem: noWeights ? 'noWeights' : null });
  checks.push({ id: 'runtime', state: avail ? 'ok' : (off ? 'fail' : (serveBad ? 'fail' : 'unknown')), detail: mode ? `${mode}${reason ? ` — ${reason}` : ''}` : reason,
    problem: !avail ? (off ? 'modeOff' : (serveBad ? 'serveBad' : (reason ? 'unavailable' : null))) : null });
  checks.push({ id: 'device', state: 'unknown', detail: '' });                       // a API não expõe o dispositivo
  const errs = isNum(health.errors) ? health.errors : null;
  checks.push({ id: 'inference', state: errs && errs > 0 ? 'fail' : 'unknown', detail: errs === null ? '' : String(errs), problem: errs && errs > 0 ? 'inferenceErrors' : null });
  const problems = checks.filter((c) => c.problem).map((c) => c.problem);
  return { checks, problems: [...new Set(problems)], reachable: true, available: avail, mode, reason, promptVersion: health.prompt_version || null };
}
