// anomalies.js — rule-based detection computed client-side from real run data only.
// Each anomaly reports: metric, observed value, expected range, severity.
import {
  get, num, metricsOf, realRuns, byPipeline, meanMetric, totalTokens, tokenAmplification, recallOf,
} from './format.js';

const mk = (o) => ({ severity: 'warn', ...o });

/**
 * @param {Array} runs  list_runs rows (metrics decoded)
 * @param {Array} details optional run detail objects (for source_file duplicate check)
 */
export function detectAnomalies(runs, details = []) {
  const rs = realRuns(runs);
  const out = [];
  if (!rs.length) return out;

  const groups = byPipeline(rs);
  const baseTokens = groups.baseline.length
    ? (() => {
      const v = groups.baseline.map((r) => totalTokens(metricsOf(r))).filter((x) => x !== null);
      return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
    })() : null;
  const baseLatency = groups.baseline.length ? meanMetric(groups.baseline, 'total_latency_ms') : null;

  for (const r of rs) {
    const m = metricsOf(r);
    const id = r.run_id;
    const where = `${r.pipeline} · run ${String(id).slice(0, 8)}`;

    // 1. total tokens > 3x baseline
    const tt = totalTokens(m);
    if (tt !== null && baseTokens && tt > 3 * baseTokens) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'Tokens totais acima de 3× o baseline',
        where, metric: 'jev_input + jev_output + context_tokens',
        observed: `${Math.round(tt).toLocaleString('en-US')} tokens`,
        expected: `≤ ${Math.round(3 * baseTokens).toLocaleString('en-US')} tokens (3× média baseline ${Math.round(baseTokens).toLocaleString('en-US')})`,
      }));
    }

    // 9. token_amplification > 3 — pipeline spends far more than it delivers
    const amp = tokenAmplification(m);
    if (amp !== null && amp > 3) {
      out.push(mk({
        severity: 'error', run_id: id,
        title: `Pipeline gasta ${amp.toFixed(1)}× mais tokens do que entrega como contexto`,
        where, metric: 'token_amplification (total_tokens_spent / context_tokens)',
        observed: `${amp.toFixed(2)}× (gastos ${Math.round(tt ?? 0).toLocaleString('en-US')} vs contexto ${Math.round(num(get(m, 'context_tokens')) ?? 0).toLocaleString('en-US')})`,
        expected: '≤ 3.0×',
      }));
    }

    // 2. recall below 0.8
    const rec = recallOf(m);
    if (rec !== null && rec < 0.8) {
      out.push(mk({
        severity: rec < 0.5 ? 'error' : 'warn', run_id: id,
        title: 'Recall abaixo do mínimo aceitável', where,
        metric: 'expected_sources_found.recall',
        observed: rec.toFixed(2),
        expected: '≥ 0.80',
      }));
    }

    // 3. jev cache_hits == 0 while cache_enabled
    const cacheEnabled = get(m, 'jev.cache_enabled') ?? get(m, 'jev_cache_enabled') ?? get(m, 'cache_enabled');
    const hits = num(get(m, 'jev.cache_hits') ?? get(m, 'jev_cache_hits'));
    const reqs = num(get(m, 'jev.request_count'));
    if (cacheEnabled === true && hits === 0 && reqs > 0) {
      out.push(mk({
        severity: 'warn', run_id: id, title: 'Cache do JEV habilitado mas sem nenhum acerto', where,
        metric: 'jev.cache_hits (cache_enabled=true)',
        observed: `0 acertos em ${reqs} requisições`,
        expected: '> 0 acertos quando o cache está habilitado',
      }));
    }

    // 4. latency > 2x baseline
    const lat = num(get(m, 'total_latency_ms'));
    if (lat !== null && baseLatency && lat > 2 * baseLatency) {
      out.push(mk({
        severity: lat > 4 * baseLatency ? 'error' : 'warn', run_id: id,
        title: 'Latência acima de 2× o baseline', where, metric: 'total_latency_ms',
        observed: `${Math.round(lat).toLocaleString('en-US')} ms`,
        expected: `≤ ${Math.round(2 * baseLatency).toLocaleString('en-US')} ms (2× média baseline ${Math.round(baseLatency)} ms)`,
      }));
    }

    // 5. candidates_dropped ratio > 0.9
    const recv = num(get(m, 'jev.candidates_received'));
    const drop = num(get(m, 'jev.candidates_dropped'));
    if (recv > 0 && drop !== null && drop / recv > 0.9) {
      out.push(mk({
        severity: 'warn', run_id: id, title: 'JEV descartou mais de 90% dos candidatos', where,
        metric: 'jev.candidates_dropped / jev.candidates_received',
        observed: `${(drop / recv).toFixed(3)} (${drop} de ${recv})`,
        expected: '≤ 0.90',
      }));
    }

    // 6. jev errors[] non-empty
    const errs = get(m, 'jev.errors');
    if (Array.isArray(errs) && errs.length) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'JEV retornou erros', where, metric: 'jev.errors[]',
        observed: `${errs.length} erro(s): ${errs.slice(0, 2).map((e) => (typeof e === 'string' ? e : JSON.stringify(e))).join('; ').slice(0, 160)}`,
        expected: 'lista vazia',
      }));
    }

    // 7. run-level error column
    if (r.error) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'Run registrou erro', where, metric: 'runs.error',
        observed: String(r.error).slice(0, 180), expected: 'null',
      }));
    }
  }

  // 8. duplicate source_file within one run (needs detail payload)
  for (const d of details) {
    const files = (d?.sources || []).map((s) => s.file).filter(Boolean);
    const seen = new Map();
    for (const f of files) seen.set(f, (seen.get(f) || 0) + 1);
    const dupes = [...seen.entries()].filter(([, n]) => n > 1);
    if (dupes.length) {
      out.push(mk({
        severity: 'warn', run_id: d.run_id,
        title: 'source_file duplicado no mesmo contexto',
        where: `${d.pipeline} · run ${String(d.run_id).slice(0, 8)}`,
        metric: 'sources[].file (dedup deveria garantir 1 por nota)',
        observed: dupes.map(([f, n]) => `${f.split('/').pop()} ×${n}`).join(', ').slice(0, 180),
        expected: 'cada arquivo aparece no máximo 1×',
      }));
    }
  }

  const rank = { error: 0, warn: 1, info: 2 };
  return out.sort((a, b) => rank[a.severity] - rank[b.severity]);
}

/** Rules documented for the UI so users know what is (and isn't) checked. */
export const RULES = [
  'Tokens totais > 3× a média do baseline',
  'token_amplification > 3 (gasta mais de 3× o que entrega como contexto)',
  'Recall (expected_sources_found.recall) < 0.80',
  'jev.cache_hits == 0 com cache_enabled == true',
  'total_latency_ms > 2× a média do baseline',
  'jev.candidates_dropped / candidates_received > 0.90',
  'jev.errors[] não vazio, ou coluna runs.error preenchida',
  'source_file duplicado dentro da mesma run',
];
