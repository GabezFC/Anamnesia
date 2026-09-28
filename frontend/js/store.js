// store.js — shared data loading + derived aggregates used across pages.
// Every aggregate keeps nulls as nulls: a missing metric is never coerced to 0.
import {
  getRuns, getSessions, getStats, getRunDetails, getSystemInfo, getQuestions, getIntegrations, getProjects,
} from './api.js';
import {
  realRuns, byPipeline, metricsOf, meanMetric, sumMetric, get, num, totalTokens, judgeTokens,
  tokenAmplification, recallOf, precisionOf, costOf, PIPELINES, mean, median, sum, ratio,
  savedTokens, judgeQuestions, judgeRequests, cacheCounts, waveCount, armOf,
} from './format.js';

const state = { detailIds: null, details: null, aggCache: new WeakMap() };

/** Hard cap on how many runs the dashboard loads. Surfaced in the UI so the sample is honest. */
export const RUN_LIMIT = 5000;

export async function loadCore() {
  const [runs, sessions, stats] = await Promise.all([
    getRuns(RUN_LIMIT),
    getSessions().catch(() => []),
    getStats().catch(() => null),
  ]);
  return { runs: Array.isArray(runs) ? runs : [], sessions: Array.isArray(sessions) ? sessions : [], stats };
}

export { getSystemInfo, getQuestions, getIntegrations, getRunDetails, getProjects };

/** Load details for the N most recent non-warmup runs (sources/candidates live only in the detail route). */
export async function loadRecentDetails(runs, n = 36) {
  const ids = realRuns(runs).slice(0, n).map((r) => r.run_id).filter(Boolean);
  const key = ids.join(',');
  if (state.detailIds === key && state.details) return state.details;
  state.details = await getRunDetails(ids);
  state.detailIds = key;
  return state.details;
}

/** Per-pipeline aggregate of every metric the dashboard/charts need. Nulls stay null. */
export function aggregate(runs) {
  if (runs && state.aggCache.has(runs)) return state.aggCache.get(runs);
  const g = byPipeline(realRuns(runs));
  const agg = {};
  for (const p of PIPELINES) {
    const rs = g[p] || [];
    const ms = rs.map(metricsOf);
    const cacheRows = ms.map(cacheCounts).filter((c) => c.lookups !== null);
    const waves = ms.map(waveCount).filter((w) => w !== null && w > 0);
    agg[p] = {
      pipeline: p,
      runs: rs.length,
      // tokens (means per run)
      total_tokens: mean(ms.map(totalTokens)),
      total_tokens_median: median(ms.map(totalTokens)),
      total_tokens_sum: sum(ms.map(totalTokens)),
      judge_tokens: mean(ms.map(judgeTokens)),
      judge_tokens_sum: sum(ms.map(judgeTokens)),
      token_amplification: mean(ms.map(tokenAmplification)),
      token_amplification_median: median(ms.map(tokenAmplification)),
      context_tokens: meanMetric(rs, 'context_tokens'),
      context_tokens_median: median(ms.map((m) => get(m, 'context_tokens'))),
      context_tokens_sum: sumMetric(rs, 'context_tokens'),
      saved_tokens: mean(ms.map(savedTokens)),
      saved_tokens_sum: sum(ms.map(savedTokens)),
      // free (zero-token) stages
      prefilter_in: meanMetric(rs, 'prefilter_in'),
      prefilter_sent: meanMetric(rs, 'prefilter_sent'),
      prefilter_withheld: meanMetric(rs, 'prefilter_withheld'),
      prefilter_tokens_saved_estimate: meanMetric(rs, 'prefilter_tokens_saved_estimate'),
      prefilter_top_k: meanMetric(rs, 'prefilter_top_k'),
      dedup_near_collapsed: meanMetric(rs, 'dedup_near_collapsed'),
      dedup_near_tokens_saved_estimate: meanMetric(rs, 'dedup_near_tokens_saved_estimate'),
      snippet_tokens_saved: meanMetric(rs, 'snippet_tokens_saved'),
      candidate_tokens_before_filter: meanMetric(rs, 'candidate_tokens_before_filter'),
      jev_input_tokens: meanMetric(rs, 'jev_input_tokens'),
      jev_output_tokens: meanMetric(rs, 'jev_output_tokens'),
      jev_tokens: meanMetric(rs, 'jev_tokens'),
      model_input_tokens: meanMetric(rs, 'model_input_tokens'),
      model_output_tokens: meanMetric(rs, 'model_output_tokens'),
      survivor_tokens_snippets: meanMetric(rs, 'survivor_tokens_snippets'),
      // judge workload
      requests: mean(ms.map(judgeRequests)),
      requests_sum: sum(ms.map(judgeRequests)),
      questions: mean(ms.map(judgeQuestions)),
      questions_sum: sum(ms.map(judgeQuestions)),
      relevance_questions_sum: sumMetric(rs, 'jev_relevance_questions'),
      injection_questions_sum: sumMetric(rs, 'jev_injection_questions'),
      injection_skipped_sum: sumMetric(rs, 'jev_injection_skipped'),
      // cache — rate computed over the SUMS, not as a mean of rates
      cache_hits_sum: cacheRows.length ? sum(cacheRows.map((c) => c.hits)) : null,
      cache_lookups_sum: cacheRows.length ? sum(cacheRows.map((c) => c.lookups)) : null,
      cache_hit_rate: cacheRows.length
        ? ratio(sum(cacheRows.map((c) => c.hits)), sum(cacheRows.map((c) => c.lookups))) : null,
      // early stopping: fraction of judged runs that executed a SINGLE wave
      wave_runs: waves.length || null,
      waves_mean: waves.length ? mean(waves) : null,
      early_stop_rate: waves.length ? waves.filter((w) => w <= 1).length / waves.length : null,
      // latency by stage
      retrieval_latency_ms: meanMetric(rs, 'retrieval_latency_ms'),
      graphify_latency_ms: meanMetric(rs, 'graphify_latency_ms'),
      jev_latency_ms: meanMetric(rs, 'jev_latency_ms'),
      full_note_latency_ms: meanMetric(rs, 'full_note_latency_ms'),
      filter_latency_ms: meanMetric(rs, 'filter_latency_ms'),
      context_build_latency_ms: meanMetric(rs, 'context_build_latency_ms'),
      generation_latency_ms: meanMetric(rs, 'generation_latency_ms'),
      total_latency_ms: meanMetric(rs, 'total_latency_ms'),
      total_latency_ms_median: median(ms.map((m) => get(m, 'total_latency_ms'))),
      // cost
      total_cost: mean(ms.map(costOf)),
      total_cost_sum: sum(ms.map(costOf)),
      jev_cost: meanMetric(rs, 'jev_cost'),
      model_cost: meanMetric(rs, 'model_cost'),
      // documents
      documents_found: meanMetric(rs, 'documents_found'),
      documents_deduplicated: meanMetric(rs, 'documents_deduplicated'),
      documents_sent_to_jev: meanMetric(rs, 'documents_sent_to_jev'),
      documents_kept: meanMetric(rs, 'documents_kept'),
      documents_review: meanMetric(rs, 'documents_review'),
      documents_dropped: meanMetric(rs, 'documents_dropped'),
      documents_quarantined: meanMetric(rs, 'documents_quarantined'),
      documents_unjudged: meanMetric(rs, 'documents_unjudged'),
      documents_unselected: meanMetric(rs, 'documents_unselected'),
      documents_sent_to_model: meanMetric(rs, 'documents_sent_to_model'),
      candidates: meanMetric(rs, 'candidates'),
      survivors: meanMetric(rs, 'survivors'),
      // quality
      context_reduction: meanMetric(rs, 'context_reduction'),
      recall: mean(ms.map(recallOf)),
      recall_n: ms.filter((m) => recallOf(m) !== null).length,
      precision: mean(ms.map(precisionOf)),
      precision_n: ms.filter((m) => precisionOf(m) !== null).length,
      average_graphify_score: meanMetric(rs, 'average_graphify_score'),
      jev_candidates_received: meanMetric(rs, 'jev.candidates_received'),
      jev_candidates_dropped: meanMetric(rs, 'jev.candidates_dropped'),
      jev_average_relevance: meanMetric(rs, 'jev.average_relevance'),
      jev_cache_hits: meanMetric(rs, 'jev_cache_hits'),
      jev_request_count: meanMetric(rs, 'jev.request_count'),
      jev_fallback_used: meanMetric(rs, 'jev_fallback_used'),
      // optimization flags actually seen on these runs
      opt_flags: optFlagsOf(ms),
    };
    // derived
    const a = agg[p];
    a.cost_per_1k = a.total_cost !== null && a.total_tokens ? (a.total_cost / a.total_tokens) * 1000 : null;
    a.efficiency = a.documents_sent_to_model !== null && a.total_tokens
      ? (a.documents_sent_to_model / a.total_tokens) * 1000 : null;
    a.tokens_per_question = ratio(a.judge_tokens, a.questions);
    a.tokens_per_request = ratio(a.judge_tokens, a.requests);
  }
  if (runs) state.aggCache.set(runs, agg);
  return agg;
}

/** Union of opt_flags seen across a set of metric dicts (sorted, deduped). */
export function optFlagsOf(metricDicts) {
  const set = new Set();
  let seen = false;
  for (const m of metricDicts || []) {
    const f = get(m, 'opt_flags');
    if (Array.isArray(f)) { seen = true; for (const k of f) set.add(String(k)); }
  }
  return seen ? [...set].sort() : null;
}

/** Latency stages, in pipeline order. Keys are metric names; STAGE is the flow-node id. */
export const LATENCY_STAGES = [
  ['retrieval_latency_ms', 'Retrieval', 'RETRIEVAL'],
  ['graphify_latency_ms', 'Graphify', 'GRAPHIFY'],
  ['jev_latency_ms', 'JEV', 'JEV'],
  ['full_note_latency_ms', 'Full note', 'FILTER'],
  ['filter_latency_ms', 'Filter', 'FILTER'],
  ['context_build_latency_ms', 'Context build', 'CONTEXT'],
  ['total_latency_ms', 'Total', 'TOTAL'],
];

/** Which pipelines actually produce which stage (for dimming the flow diagram). */
export const STAGE_APPLIES = {
  baseline: new Set(['QUERY', 'RETRIEVAL', 'FILTER', 'CONTEXT', 'MODEL', 'TOTAL']),
  graphify: new Set(['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'FILTER', 'CONTEXT', 'MODEL', 'TOTAL']),
  graphify_jev: new Set(['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'JEV', 'FILTER', 'CONTEXT', 'MODEL', 'TOTAL']),
  graphify_jev_opt: new Set(['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'PREFILTER', 'JEV', 'FILTER', 'CONTEXT', 'MODEL', 'TOTAL']),
};
/** Never throws for an unknown pipeline. */
export const stagesOf = (p) => STAGE_APPLIES[p] || new Set(['QUERY', 'RETRIEVAL', 'CONTEXT', 'MODEL', 'TOTAL']);

/** Benchmark arms present in the loaded runs, with their token totals. Derived from runs.mode. */
export function armSummary(runs) {
  const map = new Map();
  for (const r of realRuns(runs)) {
    const arm = armOf(r);
    const m = metricsOf(r);
    const e = map.get(arm) || {
      arm, runs: 0, pipelines: new Set(), judge: [], ctx: [], total: [], amp: [], requests: [], questions: [],
      recall: [], flags: [],
    };
    e.runs += 1;
    e.pipelines.add(r.pipeline);
    e.judge.push(judgeTokens(m));
    e.ctx.push(get(m, 'context_tokens'));
    e.total.push(totalTokens(m));
    e.amp.push(tokenAmplification(m));
    e.requests.push(judgeRequests(m));
    e.questions.push(judgeQuestions(m));
    e.recall.push(recallOf(m));
    e.flags.push(m);
    map.set(arm, e);
  }
  return [...map.values()].map((e) => ({
    arm: e.arm,
    runs: e.runs,
    pipelines: [...e.pipelines],
    judge_sum: sum(e.judge),
    context_sum: sum(e.ctx),
    total_sum: sum(e.total),
    amp_mean: mean(e.amp),
    requests_sum: sum(e.requests),
    questions_sum: sum(e.questions),
    recall_mean: mean(e.recall),
    opt_flags: optFlagsOf(e.flags),
  })).sort((a, b) => b.runs - a.runs);
}

/** Project entities derived from source_file prefixes in run details. */
export function deriveProjects(details) {
  const map = new Map();
  for (const d of details) {
    for (const s of d?.sources || []) {
      const parts = String(s.file || '').split('/').filter(Boolean);
      const area = /^\d{2}-/.test(parts[0] || '') ? parts[0] : '(raiz do vault)';
      const project = parts.length >= 2 && /^\d{2}-/.test(parts[0]) ? parts[1].replace(/\.md$/, '') : (parts[0] || '?');
      const key = `${area}/${project}`;
      if (!map.has(key)) {
        map.set(key, { key, area, project, files: new Set(), hits: 0, tokens: 0, runs: new Set(), relevance: [], kept: 0, dropped: 0 });
      }
      const e = map.get(key);
      e.files.add(s.file);
      e.hits += 1;
      e.tokens += num(s.tokens) || 0;
      e.runs.add(d.run_id);
      const rel = num(s.relevance);
      if (rel !== null) e.relevance.push(rel);
      if (s.decision === 'KEEP') e.kept += 1;
      if (s.decision === 'DROP' || s.decision === 'QUARANTINE') e.dropped += 1;
    }
  }
  return [...map.values()].map((e) => ({
    ...e, fileCount: e.files.size, runCount: e.runs.size, avgRelevance: mean(e.relevance),
  })).sort((a, b) => b.hits - a.hits);
}

/** Agent/model consumer rows straight from stats.groups (real aggregation done server-side). */
export function consumerRows(stats) {
  return (stats?.groups || []).map((g) => ({
    agent: g.agent, provider: g.provider, model: g.model, pipeline: g.pipeline, runs: g.runs,
    latency: get(g, 'total_latency_ms.median'),
    latencyP95: get(g, 'total_latency_ms.p95'),
    context: get(g, 'context_tokens.median'),
    jevTokens: get(g, 'jev_input_tokens.mean'),
    inTokens: get(g, 'model_input_tokens.mean'),
    outTokens: get(g, 'model_output_tokens.mean'),
    agentTokens: get(g, 'agent_tokens.mean'),
    cost: get(g, 'total_cost.mean'),
    docs: get(g, 'documents_sent_to_model.median'),
  }));
}
