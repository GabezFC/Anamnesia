// anomalies.js — rule-based detection computed client-side from real run data only.
// Each anomaly reports: metric, observed value, expected range, severity.
// No rule ever invents a threshold from thin air: each one is tied to a documented invariant
// of the backend (see config/optimization.py and app/services/jev.py).
import {
  get, num, metricsOf, realRuns, byPipeline, meanMetric, totalTokens, tokenAmplification, recallOf,
  cacheCounts, judgeRequests, waveCount, mean,
} from './format.js';

const mk = (o) => ({ severity: 'warn', ...o });
const int = (v) => Math.round(num(v) ?? 0).toLocaleString('en-US');

/**
 * @param {Array} runs  list_runs rows (metrics decoded)
 * @param {Array} details optional run detail objects (for source_file duplicate check)
 */
export function detectAnomalies(runs, details = []) {
  const rs = realRuns(runs);
  const out = [];
  if (!rs.length) return out;

  const groups = byPipeline(rs);
  const baseRuns = groups.baseline || [];
  const baseTokens = baseRuns.length ? mean(baseRuns.map((r) => totalTokens(metricsOf(r)))) : null;
  const baseLatency = baseRuns.length ? meanMetric(baseRuns, 'total_latency_ms') : null;

  for (const r of rs) {
    const m = metricsOf(r);
    const id = r.run_id;
    const where = `${r.pipeline} · run ${String(id).slice(0, 8)}`;

    // 1. total tokens > 3x baseline
    const tt = totalTokens(m);
    if (tt !== null && baseTokens && tt > 3 * baseTokens) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'Tokens totais acima de 3× o baseline',
        where, metric: 'total_tokens_spent',
        observed: `${int(tt)} tokens`,
        expected: `≤ ${int(3 * baseTokens)} tokens (3× média baseline ${int(baseTokens)})`,
      }));
    }

    // 2. token_amplification > 3 — pipeline spends far more than it delivers
    const amp = tokenAmplification(m);
    if (amp !== null && amp > 3) {
      out.push(mk({
        severity: 'error', run_id: id,
        title: `Pipeline gasta ${amp.toFixed(1)}× mais tokens do que entrega como contexto`,
        where, metric: 'token_amplification (total_tokens_spent / context_tokens)',
        observed: `${amp.toFixed(2)}× (gastos ${int(tt)} vs contexto ${int(get(m, 'context_tokens'))})`,
        expected: '≤ 3,0×',
      }));
    }

    // 3. recall below 0.8 (only for runs whose question declared expected_sources)
    const rec = recallOf(m);
    if (rec !== null && rec < 0.8) {
      out.push(mk({
        severity: rec < 0.5 ? 'error' : 'warn', run_id: id,
        title: 'Recall abaixo do mínimo aceitável', where,
        metric: 'expected_sources_found.recall',
        observed: rec.toFixed(2),
        expected: '≥ 0,80',
      }));
    }

    // 4. judge cache enabled but not a single hit
    const cacheEnabled = get(m, 'jev.cache_enabled') ?? get(m, 'jev_cache_enabled') ?? get(m, 'cache_enabled');
    const { hits, lookups } = cacheCounts(m);
    if (cacheEnabled === true && hits === 0 && lookups !== null && lookups > 0) {
      out.push(mk({
        severity: 'warn', run_id: id, title: 'Cache do juiz habilitado mas sem nenhum acerto', where,
        metric: 'cache_layers.hits (cache_enabled=true)',
        observed: `0 acertos em ${lookups} consultas`,
        expected: '> 0 acertos quando o cache está habilitado',
      }));
    }

    // 5. latency > 2x baseline
    const lat = num(get(m, 'total_latency_ms'));
    if (lat !== null && baseLatency && lat > 2 * baseLatency) {
      out.push(mk({
        severity: lat > 4 * baseLatency ? 'error' : 'warn', run_id: id,
        title: 'Latência acima de 2× o baseline', where, metric: 'total_latency_ms',
        observed: `${int(lat)} ms`,
        expected: `≤ ${int(2 * baseLatency)} ms (2× média baseline ${int(baseLatency)} ms)`,
      }));
    }

    // 6. candidates_dropped ratio > 0.9
    const recv = num(get(m, 'jev.candidates_received'));
    const drop = num(get(m, 'jev.candidates_dropped'));
    if (recv !== null && recv > 0 && drop !== null && drop / recv > 0.9) {
      out.push(mk({
        severity: 'warn', run_id: id, title: 'O juiz descartou mais de 90% dos candidatos', where,
        metric: 'jev.candidates_dropped / jev.candidates_received',
        observed: `${(drop / recv).toFixed(3)} (${drop} de ${recv})`,
        expected: '≤ 0,90',
      }));
    }

    // 7. jev errors[] non-empty
    const errs = get(m, 'jev.errors');
    if (Array.isArray(errs) && errs.length) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'O juiz retornou erros', where, metric: 'jev.errors[]',
        observed: `${errs.length} erro(s): ${errs.slice(0, 2).map((e) => (typeof e === 'string' ? e : JSON.stringify(e))).join('; ').slice(0, 160)}`,
        expected: 'lista vazia',
      }));
    }

    // 8. run-level error column
    if (r.error) {
      out.push(mk({
        severity: 'error', run_id: id, title: 'Run registrou erro', where, metric: 'runs.error',
        observed: String(r.error).slice(0, 180), expected: 'null',
      }));
    }

    // 9. safety net fired — the judge eliminated everything and unjudged candidates were served
    const fb = num(get(m, 'jev_fallback_used'));
    if (fb !== null && fb > 0) {
      out.push(mk({
        severity: 'warn', run_id: id,
        title: 'Rede de segurança acionada: o juiz eliminou todos os candidatos', where,
        metric: 'jev_fallback_used',
        observed: `${fb} candidato(s) devolvido(s) sem julgamento favorável`,
        expected: '0 (o juiz deveria manter ao menos um candidato)',
      }));
    }

    // 10. CONTEXT LEAK: candidates we deliberately refused to pay for must never be served.
    // This is exactly the bug that invalidated the old "-3.0%" headline; the rule keeps it visible.
    const unselected = num(get(m, 'documents_unselected'));
    const survivors = num(get(m, 'survivors'));
    const kept = num(get(m, 'documents_kept'));
    const review = num(get(m, 'documents_review'));
    if (unselected !== null && unselected > 0 && survivors !== null
        && kept !== null && review !== null && survivors > kept + review) {
      out.push(mk({
        severity: 'error', run_id: id,
        title: 'Possível vazamento de contexto: sobreviventes além de KEEP+REVIEW com candidatos UNSELECTED',
        where, metric: 'survivors vs documents_kept + documents_review (documents_unselected > 0)',
        observed: `${survivors} sobreviventes, ${kept} KEEP + ${review} REVIEW, ${unselected} UNSELECTED`,
        expected: 'survivors ≤ documents_kept + documents_review — UNSELECTED nunca sobrevive (app/services/jev.py survives())',
      }));
    }

    // 11. waves without savings: escalation on a run that asked more requests than waves warrant
    const waves = waveCount(m);
    const reqs = judgeRequests(m);
    if (waves !== null && waves > 1 && reqs !== null && reqs > waves) {
      out.push(mk({
        severity: 'info', run_id: id,
        title: 'Mais requisições ao juiz do que ondas de escalonamento', where,
        metric: 'jev.request_count vs jev_wave_sizes.length',
        observed: `${reqs} requisições para ${waves} onda(s)`,
        expected: 'requisições ≈ ondas; cada requisição extra custa ~340 tokens fixos',
      }));
    }
  }

  // 12. duplicate source_file within one run (needs detail payload)
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
  'Recall (expected_sources_found.recall) < 0,80',
  'Cache do juiz habilitado com 0 acertos em > 0 consultas',
  'total_latency_ms > 2× a média do baseline',
  'jev.candidates_dropped / candidates_received > 0,90',
  'jev.errors[] não vazio, ou coluna runs.error preenchida',
  'jev_fallback_used > 0 (rede de segurança acionada)',
  'survivors > documents_kept + documents_review com documents_unselected > 0 (vazamento de contexto)',
  'jev.request_count > número de ondas (requisições extras a ~340 tokens cada)',
  'source_file duplicado dentro da mesma run',
];
