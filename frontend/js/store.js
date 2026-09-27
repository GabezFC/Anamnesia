// store.js — shared data loading + derived aggregates used across pages.
import {
  getRuns, getSessions, getStats, getRunDetails, getSystemInfo, getQuestions, getIntegrations, getProjects,
} from './api.js';
import {
  realRuns, byPipeline, metricsOf, meanMetric, get, num, totalTokens, judgeTokens, tokenAmplification,
  recallOf, costOf, PIPELINES, mean, median,
} from './format.js';

const state = { detailIds: null, details: null };

export async function loadCore() {
  const [runs, sessions, stats] = await Promise.all([getRuns(1000), getSessions(), getStats()]);
  return { runs, sessions, stats };
}

export { getSystemInfo, getQuestions, getIntegrations, getRunDetails, getProjects };

/** Load details for the N most recent non-warmup runs (sources/candidates live only in the detail route). */
export async function loadRecentDetails(runs, n = 36) {
  const ids = realRuns(runs).slice(0, n).map((r) => r.run_id);
  const key = ids.join(',');
  if (state.detailIds === key && state.details) return state.details;
  state.details = await getRunDetails(ids);
  state.detailIds = key;
  return state.details;
}

/** Per-pipeline aggregate of every metric the dashboard/charts need. Nulls stay null. */
export function aggregate(runs) {
  const g = byPipeline(realRuns(runs));
  const agg = {};
  for (const p of PIPELINES) {
    const rs = g[p];
    const ms = rs.map(metricsOf);
    agg[p] = {
      pipeline: p,
      runs: rs.length,
      // tokens
      total_tokens: mean(ms.map(totalTokens)),
      total_tokens_median: median(ms.map(totalTokens)),
      judge_tokens: mean(ms.map(judgeTokens)),
      token_amplification: mean(ms.map(tokenAmplification)),
      token_amplification_median: median(ms.map(tokenAmplification)),
      context_tokens: meanMetric(rs, 'context_tokens'),
      context_tokens_median: median(ms.map((m) => get(m, 'context_tokens'))),
      // prefilter (present only on runs recorded after the prefilter stage was added)
      prefilter_in: meanMetric(rs, 'prefilter_in'),
      prefilter_sent: meanMetric(rs, 'prefilter_sent'),
      prefilter_withheld: meanMetric(rs, 'prefilter_withheld'),
      prefilter_tokens_saved_estimate: meanMetric(rs, 'prefilter_tokens_saved_estimate'),
      prefilter_top_k: meanMetric(rs, 'prefilter_top_k'),
      candidate_tokens_before_filter: meanMetric(rs, 'candidate_tokens_before_filter'),
      jev_input_tokens: meanMetric(rs, 'jev_input_tokens'),
      jev_output_tokens: meanMetric(rs, 'jev_output_tokens'),
      jev_tokens: meanMetric(rs, 'jev_tokens'),
      model_input_tokens: meanMetric(rs, 'model_input_tokens'),
      model_output_tokens: meanMetric(rs, 'model_output_tokens'),
      survivor_tokens_snippets: meanMetric(rs, 'survivor_tokens_snippets'),
      // latency by stage
      retrieval_latency_ms: meanMetric(rs, 'retrieval_latency_ms'),
      graphify_latency_ms: meanMetric(rs, 'graphify_latency_ms'),
      jev_latency_ms: meanMetric(rs, 'jev_latency_ms'),
      full_note_latency_ms: meanMetric(rs, 'full_note_latency_ms'),
      filter_latency_ms: meanMetric(rs, 'filter_latency_ms'),
      context_build_latency_ms: meanMetric(rs, 'context_build_latency_ms'),
      generation_latency_ms: meanMetric(rs, 'generation_latency_ms'),
      total_latency_ms: meanMetric(rs, 'total_latency_ms'),
      // cost
      total_cost: mean(ms.map(costOf)),
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
      documents_sent_to_model: meanMetric(rs, 'documents_sent_to_model'),
      candidates: meanMetric(rs, 'candidates'),
      survivors: meanMetric(rs, 'survivors'),
      // quality / jev
      context_reduction: meanMetric(rs, 'context_reduction'),
      recall: mean(ms.map(recallOf)),
      average_graphify_score: meanMetric(rs, 'average_graphify_score'),
      jev_candidates_received: meanMetric(rs, 'jev.candidates_received'),
      jev_candidates_dropped: meanMetric(rs, 'jev.candidates_dropped'),
      jev_average_relevance: meanMetric(rs, 'jev.average_relevance'),
      jev_cache_hits: meanMetric(rs, 'jev.cache_hits'),
      jev_request_count: meanMetric(rs, 'jev.request_count'),
    };
    // derived
    const a = agg[p];
    a.cost_per_1k = a.total_cost !== null && a.total_tokens ? (a.total_cost / a.total_tokens) * 1000 : null;
    a.efficiency = a.documents_sent_to_model !== null && a.total_tokens
      ? (a.documents_sent_to_model / a.total_tokens) * 1000 : null;
  }
  return agg;
}

/** Latency stages, in pipeline order. */
export const LATENCY_STAGES = [
  ['retrieval_latency_ms', 'Retrieval'],
  ['graphify_latency_ms', 'Graphify'],
  ['jev_latency_ms', 'JEV'],
  ['full_note_latency_ms', 'Full note'],
  ['filter_latency_ms', 'Filter'],
  ['context_build_latency_ms', 'Context build'],
  ['total_latency_ms', 'Total'],
];

/** Which pipelines actually produce which stage (for dimming the flow diagram). */
export const STAGE_APPLIES = {
  baseline: new Set(['QUERY', 'RETRIEVAL', 'FILTER', 'CONTEXT', 'MODEL']),
  graphify: new Set(['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'FILTER', 'CONTEXT', 'MODEL']),
  graphify_jev: new Set(['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'JEV', 'FILTER', 'CONTEXT', 'MODEL']),
};

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
