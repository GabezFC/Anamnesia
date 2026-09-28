// pages-core.js — Dashboard, Benchmarks, Pipeline, Tokens, Latency, Costs.
// Data comes only from the API. A metric with no data renders "Não medido"; nothing is fabricated.
import { hBarChart, groupedBarChart, stackedBarChart } from './charts.js';
import {
  PIPELINES, PIPELINE_LABEL, PIPELINE_SHORT, PIPELINE_COLOR, esc, fmtNum, fmtCompact, fmtMs, fmtCost,
  fmtPct, fmtAmp, num, delta, realRuns,
} from './format.js';
import {
  metricCard, panel, emptyState, notMeasuredState, table, segmented, help, callout, provenanceBadge,
  flagChip,
} from './components.js';
import { aggregate, LATENCY_STAGES, stagesOf, armSummary, RUN_LIMIT } from './store.js';
import { detectAnomalies, RULES } from './anomalies.js';
import { LIVE_PROVENANCE, invalidResults } from './provenance.js';

const BASE = 'baseline';
/** Pipelines that actually have runs, in canonical order. */
const activeOf = (agg) => PIPELINES.filter((p) => agg[p] && agg[p].runs > 0);
/** The most "optimized" pipeline present — used as the default "Optimized" arm of the comparison. */
const optimizedOf = (agg) => ['graphify_jev_opt', 'graphify_jev', 'graphify'].find((p) => agg[p]?.runs > 0) || null;

const ampColor = (v) => (num(v) === null ? 'var(--text-1)'
  : num(v) > 3 ? 'var(--error)' : num(v) > 1.5 ? 'var(--warn)' : 'var(--success)');

/* ============================================ BASELINE vs OPTIMIZED ====== */
/**
 * The headline comparison. Rendered ONLY from values that exist; each row that has no data on
 * either side says "Não medido" instead of showing a fabricated delta.
 */
function comparisonPanel(agg, truncated) {
  const b = agg[BASE];
  const optKey = optimizedOf(agg);
  if (!b?.runs || !optKey) {
    const why = truncated
      ? `A janela carregada está saturada em <b>${RUN_LIMIT}</b> runs (as mais recentes por <code>created_at</code>), `
        + 'então runs mais antigas de <code>baseline</code> podem existir no banco e estar fora desta janela. '
        + 'Isto é uma limitação da consulta, não a ausência da medição.'
      : 'A comparação exige runs do pipeline <code>baseline</code> E de pelo menos um pipeline com juiz. '
        + 'Rode <code>POST /benchmark/run-all</code> para gerar os dois lados.';
    return panel('Baseline vs Otimizado',
      notMeasuredState('runs de baseline e de um pipeline otimizado', why),
    { sub: 'sem os dois lados medidos', prov: 'experimental' });
  }
  const o = agg[optKey];
  const ROWS = [
    ['Tokens totais gastos', 'total_tokens', fmtCompact, true, 'total_tokens'],
    ['Tokens pagos ao juiz', 'judge_tokens', fmtCompact, true, 'judge_tokens'],
    ['Contexto entregue ao consumidor', 'context_tokens', fmtCompact, true, 'consumer_context'],
    ['Amplificação', 'token_amplification', fmtAmp, true, 'token_amplification'],
    ['Requisições ao juiz', 'requests', (v) => fmtNum(v, 1), true, 'requests'],
    ['Perguntas pagas', 'questions', (v) => fmtNum(v, 1), true, 'questions'],
    ['Taxa de acerto do cache', 'cache_hit_rate', (v) => fmtPct(v, 1), false, 'cache_hit_rate'],
    ['Parada antecipada (1 onda)', 'early_stop_rate', (v) => fmtPct(v, 1), false, 'early_stop_rate'],
    ['Recall', 'recall', (v) => fmtPct(v, 1), false, 'recall'],
    ['Precisão do contexto', 'precision', (v) => fmtPct(v, 1), false, 'precision'],
    ['Latência total', 'total_latency_ms', fmtMs, true, 'total_latency_ms'],
    ['Custo', 'total_cost', fmtCost, true, 'total_cost'],
  ];
  const rows = ROWS.map(([label, key, fmt, lowerBetter, tipKey]) => {
    const bv = num(b[key]); const ov = num(o[key]);
    if (bv === null && ov === null) {
      return `<tr class="row-empty"><th class="rowhead">${esc(label)}${help(tipKey)}</th>
        <td class="num muted">—</td><td class="num muted">—</td>
        <td class="num"><span class="delta flat">não medido</span></td></tr>`;
    }
    const d = delta(ov, bv, lowerBetter);
    return `<tr>
      <th class="rowhead">${esc(label)}${help(tipKey)}</th>
      <td class="num">${bv === null ? '<span class="muted">—</span>' : esc(fmt(bv))}</td>
      <td class="num strong">${ov === null ? '<span class="muted">—</span>' : esc(fmt(ov))}</td>
      <td class="num">${bv === null || ov === null
    ? '<span class="delta flat">n/a</span>'
    : `<span class="delta ${d.cls}">${d.text}</span>`}</td>
    </tr>`;
  });
  return panel('Baseline vs Otimizado',
    `${callout('warn', 'Como ler esta tabela',
      'Cada lado é a MÉDIA por run das runs gravadas daquele pipeline, não um experimento pareado. '
      + 'As runs vêm de sessões e configurações diferentes, então as diferenças aqui indicam onde olhar — '
      + 'não constituem um resultado medido. Linhas sem dado dizem "não medido" em vez de mostrar zero.')}
     ${table([
    { label: 'Métrica' },
    { label: `${PIPELINE_LABEL[BASE]} (${b.runs} runs)`, num: true },
    { label: `${PIPELINE_LABEL[optKey]} (${o.runs} runs)`, num: true },
    { label: 'Δ', num: true },
  ], rows)}`,
    { sub: `${b.runs} + ${o.runs} runs · média por run`, prov: 'experimental', provNote: LIVE_PROVENANCE.why });
}

/* ====================================================== DASHBOARD ======= */
export function renderDashboard(ctx) {
  const { runs } = ctx;
  const rs = realRuns(runs);
  if (!rs.length) {
    return emptyState('Nenhuma run registrada',
      '<p class="state-body">Execute um benchmark (<code>POST /benchmark/run-all</code>) para popular o dashboard. '
      + 'Enquanto não houver runs, nenhum número é exibido — nem zero, nem estimativa.</p>');
  }
  const agg = aggregate(runs);
  const active = activeOf(agg);
  const optKey = optimizedOf(agg);
  const o = optKey ? agg[optKey] : null;
  const b = agg[BASE];
  const ref = (key) => num(b?.[key]);

  /** Card over the pipeline chosen as "optimized", falling back to baseline when it is the only one. */
  const show = (key) => {
    const v = o && num(o[key]) !== null ? num(o[key]) : num(b?.[key]);
    return v;
  };

  const kpis = [
    metricCard({
      title: 'Tokens economizados (estimativa)', tipKey: 'saved_tokens',
      value: num(show('saved_tokens')) === null ? undefined : fmtCompact(show('saved_tokens')),
      unit: 'tokens / run', rawValue: show('saved_tokens'), ref: ref('saved_tokens'), lowerIsBetter: false,
      context: 'estágios determinísticos (custo zero)',
      missingHint: 'prefilter/near-dedup/snippet não registrados nestas runs',
    }),
    metricCard({
      title: 'Tokens consumidos', tipKey: 'total_tokens',
      value: num(show('total_tokens')) === null ? undefined : fmtCompact(show('total_tokens')),
      unit: 'tokens / run', rawValue: show('total_tokens'), ref: ref('total_tokens'), lowerIsBetter: true,
      context: `contexto final ${fmtCompact(show('context_tokens'))} tokens`,
    }),
    metricCard({
      title: 'Requisições ao juiz', tipKey: 'requests',
      value: num(show('requests')) === null ? undefined : fmtNum(show('requests'), 2),
      unit: 'por run', rawValue: show('requests'), ref: ref('requests'), lowerIsBetter: true,
      context: 'cada requisição tem overhead fixo',
      missingHint: 'jev.request_count ausente nas runs',
    }),
    metricCard({
      title: 'Perguntas pagas', tipKey: 'questions',
      value: num(show('questions')) === null ? undefined : fmtNum(show('questions'), 1),
      unit: 'por run', rawValue: show('questions'), ref: ref('questions'), lowerIsBetter: true,
      context: 'relevância + injeção',
      missingHint: 'jev_relevance_questions/jev_injection_questions ausentes',
    }),
    metricCard({
      title: 'Recall', tipKey: 'recall',
      value: num(show('recall')) === null ? undefined : fmtPct(show('recall'), 1),
      unit: 'fontes esperadas', rawValue: show('recall'), ref: ref('recall'), lowerIsBetter: false,
      context: `${(o || b)?.recall_n || 0} runs com expected_sources`,
      missingHint: 'nenhuma run com expected_sources declaradas',
    }),
    metricCard({
      title: 'Precisão do contexto', tipKey: 'precision',
      value: num(show('precision')) === null ? undefined : fmtPct(show('precision'), 1),
      unit: 'do contexto entregue', rawValue: show('precision'), ref: ref('precision'), lowerIsBetter: false,
      context: `${(o || b)?.precision_n || 0} runs com base de cálculo`,
      missingHint: 'exige expected_sources_found.found e documents_sent_to_model',
    }),
    metricCard({
      title: 'Acerto de cache', tipKey: 'cache_hit_rate',
      value: num(show('cache_hit_rate')) === null ? undefined : fmtPct(show('cache_hit_rate'), 1),
      unit: 'das consultas', rawValue: show('cache_hit_rate'), ref: ref('cache_hit_rate'), lowerIsBetter: false,
      context: `${fmtCompact(show('cache_hits_sum'))} acertos / ${fmtCompact(show('cache_lookups_sum'))} consultas`,
      missingHint: 'cache_layers/jev_cache_hits ausentes nas runs',
    }),
    metricCard({
      title: 'Parada antecipada', tipKey: 'early_stop_rate',
      value: num(show('early_stop_rate')) === null ? undefined : fmtPct(show('early_stop_rate'), 1),
      unit: 'runs com 1 onda', rawValue: show('early_stop_rate'), ref: ref('early_stop_rate'), lowerIsBetter: false,
      context: `${(o || b)?.wave_runs || 0} runs registram ondas`,
      missingHint: 'jev_wave_sizes/jev_waves ausentes nas runs',
    }),
    metricCard({
      title: 'Contexto do consumidor', tipKey: 'consumer_context',
      value: num(show('context_tokens')) === null ? undefined : fmtCompact(show('context_tokens')),
      unit: 'tokens / run', rawValue: show('context_tokens'), ref: ref('context_tokens'), lowerIsBetter: true,
      context: 'o que o modelo realmente recebe',
    }),
    metricCard({
      title: 'Amplificação', tipKey: 'token_amplification',
      value: num(show('token_amplification')) === null ? undefined : fmtAmp(show('token_amplification')),
      unit: '× gasto / entregue', rawValue: show('token_amplification'), ref: ref('token_amplification'),
      lowerIsBetter: true, context: '>1 gasta mais do que entrega',
    }),
    metricCard({
      title: 'Latência total', tipKey: 'total_latency_ms',
      value: num(show('total_latency_ms')) === null ? undefined : fmtMs(show('total_latency_ms')),
      unit: 'por run', rawValue: show('total_latency_ms'), ref: ref('total_latency_ms'), lowerIsBetter: true,
      context: 'média · mediana ' + fmtMs(show('total_latency_ms_median')),
    }),
    metricCard({
      title: 'Custo', tipKey: 'total_cost',
      value: num(show('total_cost')) === null ? undefined : fmtCost(show('total_cost')),
      unit: 'USD / run', rawValue: show('total_cost'), ref: ref('total_cost'), lowerIsBetter: true,
      context: 'juiz + modelo, quando registrados',
      missingHint: 'runs de retrieval não registram custo de geração',
    }),
  ].join('');

  const anomalies = detectAnomalies(runs, ctx.details || []);
  const sev = { error: 0, warn: 0, info: 0 };
  for (const a of anomalies) sev[a.severity] = (sev[a.severity] || 0) + 1;

  return `
    ${provenanceNotice(ctx)}
    <div class="grid grid-kpi">${kpis}</div>
    ${comparisonPanel(agg, (ctx.runs || []).length >= RUN_LIMIT)}
    <div class="grid grid-2">
      ${panel('Composição de tokens por pipeline', '<div class="chart-wrap" data-chart="dash-tokens"></div>',
    { sub: `${rs.length} runs · warm-up excluído`, prov: 'experimental' })}
      ${panel('Latência por estágio', '<div class="chart-wrap" data-chart="dash-latency"></div>',
    { sub: 'média em ms', prov: 'experimental' })}
    </div>
    ${panel('Resumo por pipeline', pipelineSummaryTable(agg),
    { sub: `${active.length} pipelines com dados`, prov: 'experimental' })}
    ${panel('Anomalias detectadas',
    anomalies.length
      ? `<div class="page-toolbar">
           ${sev.error ? `<span class="pill err"><span class="dot"></span>${sev.error} erro</span>` : ''}
           ${sev.warn ? `<span class="pill warn"><span class="dot"></span>${sev.warn} atenção</span>` : ''}
           ${sev.info ? `<span class="pill info"><span class="dot"></span>${sev.info} informativo</span>` : ''}
         </div>${anomalies.slice(0, 8).map(anomalyCard).join('')}
         ${anomalies.length > 8 ? `<p class="muted">+${anomalies.length - 8} outras — ver a aba Benchmarks.</p>` : ''}`
      : emptyState('Nenhuma anomalia', `<p class="state-body">${RULES.length} regras avaliadas, nenhuma disparou.</p>`),
    { sub: `${anomalies.length} ocorrência(s)` })}
  `;
}

/** Banner that states, once per page, what the live numbers are and are not. */
function provenanceNotice(ctx) {
  const invalid = invalidResults();
  const truncated = (ctx?.runs || []).length >= RUN_LIMIT;
  return `<div class="notice">
    <div class="notice-row">
      ${provenanceBadge('experimental')}
      <p>${esc(LIVE_PROVENANCE.why)}</p>
    </div>
    ${truncated ? `<div class="notice-row">
      <span class="pill warn"><span class="dot"></span>amostra truncada</span>
      <p>O dashboard carrega no máximo <b>${RUN_LIMIT}</b> runs, as mais recentes por
        <code>created_at</code>. Pipelines executados antes desse corte podem não aparecer aqui,
        ainda que existam no banco — por isso um lado da comparação pode ficar vazio.</p>
    </div>` : ''}
    ${invalid.length ? `<div class="notice-row">
      ${provenanceBadge('invalid')}
      <p>${invalid.map((r) => esc(r.title)).join(' · ')} — retirado de circulação; ver a aba
        <a href="#/results">Resultados</a>.</p>
    </div>` : ''}
  </div>`;
}

export function mountDashboard(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const t = root.querySelector('[data-chart="dash-tokens"]');
  if (t) {
    stackedBarChart(t, {
      rows: active.map((p) => ({
        label: PIPELINE_SHORT[p] || p,
        parts: [
          { label: 'Contexto entregue', value: num(agg[p].context_tokens), color: PIPELINE_COLOR[p] },
          { label: 'Tokens do juiz', value: num(agg[p].judge_tokens), color: 'var(--warn)' },
        ],
      })),
      unit: 'tokens (média/run)', fmt: fmtCompact,
      emptyMsg: 'nenhuma run carregada registra context_tokens ou judge_tokens',
    });
  }
  const l = root.querySelector('[data-chart="dash-latency"]');
  if (l) mountLatencyChart(l, agg, active);
}

function mountLatencyChart(wrap, agg, active) {
  const stages = LATENCY_STAGES.filter(([k]) => active.some((p) => num(agg[p][k]) !== null));
  groupedBarChart(wrap, {
    groups: stages.map(([, label]) => ({ label })),
    series: active.map((p) => ({
      label: PIPELINE_SHORT[p] || p, color: PIPELINE_COLOR[p],
      values: stages.map(([k]) => num(agg[p][k]) || 0),
    })),
    unit: 'ms', fmt: fmtMs, emptyMsg: 'nenhuma run registra latência por estágio',
  });
}

function pipelineSummaryTable(agg) {
  const active = activeOf(agg);
  const rows = active.map((p) => {
    const a = agg[p];
    const d = (v, ref, low = true) => {
      if (p === BASE) return '<td class="num muted">ref</td>';
      const x = delta(v, ref, low);
      return `<td class="num"><span class="delta ${x.cls}">${x.text}</span></td>`;
    };
    return `<tr>
      <th class="rowhead">${esc(PIPELINE_LABEL[p] || p)}</th>
      <td class="num">${a.runs}</td>
      <td class="num">${fmtCompact(a.total_tokens)}</td>${d(a.total_tokens, agg[BASE].total_tokens)}
      <td class="num">${fmtCompact(a.context_tokens)}</td>
      <td class="num">${fmtCompact(a.judge_tokens)}</td>
      <td class="num" style="color:${ampColor(a.token_amplification)}">${fmtAmp(a.token_amplification)}</td>
      <td class="num">${fmtMs(a.total_latency_ms)}</td>${d(a.total_latency_ms, agg[BASE].total_latency_ms)}
      <td class="num">${fmtCost(a.total_cost)}</td>
      <td class="num">${a.recall === null ? '<span class="muted">n/m</span>' : fmtPct(a.recall)}</td>
      <td class="num">${a.precision === null ? '<span class="muted">n/m</span>' : fmtPct(a.precision)}</td>
    </tr>`;
  });
  return table([
    { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Tokens totais', num: true, tipKey: 'total_tokens' }, { label: 'Δ vs base', num: true },
    { label: 'Contexto', num: true, tipKey: 'context_tokens' },
    { label: 'Juiz', num: true, tipKey: 'judge_tokens' },
    { label: 'Amplif.', num: true, tipKey: 'token_amplification' },
    { label: 'Latência', num: true, tipKey: 'total_latency_ms' }, { label: 'Δ vs base', num: true },
    { label: 'Custo', num: true, tipKey: 'total_cost' },
    { label: 'Recall', num: true, tipKey: 'recall' },
    { label: 'Precisão', num: true, tipKey: 'precision' },
  ], rows, { emptyDetail: 'nenhum pipeline tem runs não-warmup carregadas' });
}

export function anomalyCard(a) {
  return `<div class="anom sev-${esc(a.severity)}">
    <div class="bar"></div>
    <div class="anom-body">
      <div class="anom-title">${esc(a.title)}</div>
      <div class="anom-detail">
        <span class="muted">${esc(a.where || '')}</span>
        <dl>
          <dt>Métrica</dt><dd class="mono">${esc(a.metric)}</dd>
          <dt>Observado</dt><dd>${esc(a.observed)}</dd>
          <dt>Esperado</dt><dd>${esc(a.expected)}</dd>
        </dl>
      </div>
    </div>
  </div>`;
}

/* ====================================================== BENCHMARKS ====== */
const CMP_ROWS = [
  ['Tokens totais GASTOS', (a) => a.total_tokens, fmtCompact, true, 'total_tokens'],
  ['Tokens do juiz', (a) => a.judge_tokens, fmtCompact, true, 'judge_tokens'],
  ['Amplificação (gasto/entregue)', (a) => a.token_amplification, fmtAmp, true, 'token_amplification'],
  ['Contexto entregue', (a) => a.context_tokens, fmtCompact, true, 'context_tokens'],
  ['Economia estimada (estágios grátis)', (a) => a.saved_tokens, fmtCompact, false, 'saved_tokens'],
  ['Requisições ao juiz', (a) => a.requests, (v) => fmtNum(v, 2), true, 'requests'],
  ['Perguntas pagas', (a) => a.questions, (v) => fmtNum(v, 1), true, 'questions'],
  ['Acerto de cache', (a) => a.cache_hit_rate, (v) => fmtPct(v, 1), false, 'cache_hit_rate'],
  ['Parada antecipada', (a) => a.early_stop_rate, (v) => fmtPct(v, 1), false, 'early_stop_rate'],
  ['Input tokens (modelo)', (a) => a.model_input_tokens, fmtCompact, true, null],
  ['Output tokens (modelo)', (a) => a.model_output_tokens, fmtCompact, true, null],
  ['JEV input tokens', (a) => a.jev_input_tokens, fmtCompact, true, 'jev_input_tokens'],
  ['JEV output tokens', (a) => a.jev_output_tokens, fmtCompact, true, 'jev_output_tokens'],
  ['Latência', (a) => a.total_latency_ms, fmtMs, true, 'total_latency_ms'],
  ['Custo', (a) => a.total_cost, fmtCost, true, 'total_cost'],
  ['Candidatos', (a) => a.candidates, fmtNum, false, null],
  ['Removidos no dedup', (a) => a.documents_deduplicated, fmtNum, true, 'documents_deduplicated'],
  ['Enviados ao juiz', (a) => a.documents_sent_to_jev, fmtNum, true, 'documents_sent_to_jev'],
  ['No contexto final (docs)', (a) => a.documents_sent_to_model, fmtNum, false, 'documents_sent_to_model'],
  ['Recall', (a) => a.recall, (v) => fmtPct(v, 1), false, 'recall'],
  ['Precisão do contexto', (a) => a.precision, (v) => fmtPct(v, 1), false, 'precision'],
];

export function renderBenchmarks(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', '<p class="state-body">Nada para comparar ainda.</p>');
  const agg = aggregate(ctx.runs);
  const cols = activeOf(agg);

  const rows = CMP_ROWS.map(([label, val, fmt, lowerBetter, tipKey]) => {
    const vals = cols.map((p) => num(val(agg[p])));
    const ref = num(val(agg[BASE]));
    if (vals.every((v) => v === null)) {
      return `<tr class="row-empty"><th class="rowhead">${esc(label)}${help(tipKey)}</th>
        ${cols.map(() => '<td class="num muted">—</td>').join('')}
        <td class="num"><span class="delta flat">não medido</span></td></tr>`;
    }
    const cells = cols.map((p, i) => {
      const v = vals[i];
      if (v === null) return '<td class="num muted">—</td>';
      // Highlight only SIGNIFICANT differences (>=15% vs baseline).
      let cls = '';
      if (p !== BASE && ref) {
        const pct = (v - ref) / Math.abs(ref);
        if (Math.abs(pct) >= 0.15) cls = (pct < 0) === lowerBetter ? 'sig-down' : 'sig-up';
      }
      return `<td class="num ${cls}">${esc(fmt(v))}</td>`;
    });
    return `<tr><th class="rowhead">${esc(label)}${help(tipKey)}</th>${cells.join('')}<td></td></tr>`;
  });

  const anomalies = detectAnomalies(ctx.runs, ctx.details || []);
  const arms = armSummary(ctx.runs);
  // Rendering one card per anomaly is unbounded: thousands of runs produce thousands of cards and
  // a multi-megabyte page. Cap the rendered list and summarise the rest by rule.
  const ANOM_CAP = 60;
  const shown = anomalies.slice(0, ANOM_CAP);
  const byTitle = new Map();
  for (const a of anomalies) byTitle.set(a.title, (byTitle.get(a.title) || 0) + 1);
  const sevCount = { error: 0, warn: 0, info: 0 };
  for (const a of anomalies) sevCount[a.severity] = (sevCount[a.severity] || 0) + 1;

  return `
    ${panel('Comparação de pipelines',
    `${callout('info', 'Leitura',
      'Colunas são os pipelines reais do backend. Valores = média das runs (warm-up excluído). '
      + 'Destaque de cor apenas quando a diferença vs <b>Baseline</b> ≥ 15%: '
      + '<span style="color:var(--success)">verde = melhora</span>, '
      + '<span style="color:var(--error)">vermelho = piora</span>. '
      + 'Linhas sem dado em nenhum pipeline aparecem como "não medido".')}
     ${table([{ label: 'Métrica' }, ...cols.map((p) => ({ label: PIPELINE_SHORT[p] || p, num: true })), { label: '' }], rows)}`,
    { sub: `${rs.length} runs`, prov: 'experimental', provNote: LIVE_PROVENANCE.why })}
    ${panel('Braços de benchmark presentes nas runs', armTable(arms),
    { sub: 'derivado de runs.mode ("<braço>|pass<N>")', prov: 'experimental' })}
    ${panel('Anomalias',
    anomalies.length
      ? `<div class="page-toolbar">
           ${sevCount.error ? `<span class="pill err"><span class="dot"></span>${sevCount.error} erro</span>` : ''}
           ${sevCount.warn ? `<span class="pill warn"><span class="dot"></span>${sevCount.warn} atenção</span>` : ''}
           ${sevCount.info ? `<span class="pill info"><span class="dot"></span>${sevCount.info} informativo</span>` : ''}
         </div>
         ${table([{ label: 'Ocorrência' }, { label: 'Runs afetadas', num: true }],
    [...byTitle.entries()].sort((x, y) => y[1] - x[1]).map(([t, n]) =>
      `<tr><th class="rowhead">${esc(t)}</th><td class="num">${fmtNum(n)}</td></tr>`))}
         <h3 class="sub-head">Ocorrências individuais (${shown.length} de ${anomalies.length})</h3>
         ${shown.map(anomalyCard).join('')}
         ${anomalies.length > ANOM_CAP
    ? `<p class="muted">Lista truncada em ${ANOM_CAP} cartões para manter a página utilizável; a tabela acima resume todas as ${anomalies.length} ocorrências.</p>`
    : ''}`
      : emptyState('Nenhuma anomalia detectada',
        `<p class="state-body">Regras avaliadas:<br><span class="mono">${RULES.map(esc).join('<br>')}</span></p>`),
    { sub: `${anomalies.length} ocorrência(s) · ${RULES.length} regras` })}
    ${panel('Regras de anomalia aplicadas',
    `<ul class="rule-list">${RULES.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`)}
  `;
}

function armTable(arms) {
  if (!arms.length) return notMeasuredState('runs.mode');
  const rows = arms.map((a) => `<tr>
    <th class="rowhead mono">${esc(a.arm)}</th>
    <td class="num">${fmtNum(a.runs)}</td>
    <td class="mono muted">${esc(a.pipelines.map((p) => PIPELINE_SHORT[p] || p).join(', '))}</td>
    <td class="num">${fmtCompact(a.judge_sum)}</td>
    <td class="num">${fmtCompact(a.context_sum)}</td>
    <td class="num">${fmtCompact(a.total_sum)}</td>
    <td class="num">${fmtNum(a.requests_sum)}</td>
    <td class="num">${fmtNum(a.questions_sum)}</td>
    <td class="num">${a.recall_mean === null ? '<span class="muted">n/m</span>' : fmtPct(a.recall_mean)}</td>
    <td>${a.opt_flags === null ? '<span class="muted">n/m</span>'
    : (a.opt_flags.length ? a.opt_flags.map((f) => flagChip(f, true)).join(' ') : '<span class="muted">nenhum (referência)</span>')}</td>
  </tr>`);
  return `${callout('warn', 'Somas, não experimentos pareados',
    'Cada linha soma as runs que o harness gravou com aquele <code>mode</code>. Braços diferentes rodaram '
    + 'com números de perguntas e passes diferentes, então as somas NÃO são comparáveis entre si. '
    + 'Use-as para ver o que foi executado, não para concluir qual braço é melhor.')}
    ${table([
    { label: 'Braço' }, { label: 'Runs', num: true }, { label: 'Pipelines' },
    { label: 'Tokens juiz (soma)', num: true, tipKey: 'judge_tokens' },
    { label: 'Contexto (soma)', num: true, tipKey: 'context_tokens' },
    { label: 'Total (soma)', num: true, tipKey: 'total_tokens' },
    { label: 'Requisições', num: true, tipKey: 'requests' },
    { label: 'Perguntas', num: true, tipKey: 'questions' },
    { label: 'Recall médio', num: true, tipKey: 'recall' },
    { label: 'opt_flags', tipKey: 'opt_flags' },
  ], rows)}`;
}

/* ====================================================== PIPELINE ======== */
const FLOW = [
  { id: 'QUERY', label: 'Query' },
  { id: 'RETRIEVAL', label: 'Retrieval' },
  { id: 'GRAPHIFY', label: 'Graphify' },
  { id: 'PREFILTER', label: 'Pré-filtro' },
  { id: 'JEV', label: 'JEV' },
  { id: 'FILTER', label: 'Filter' },
  { id: 'CONTEXT', label: 'Context' },
  { id: 'MODEL', label: 'Model' },
];

export function renderPipeline(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', '<p class="state-body">Sem dados de pipeline.</p>');
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const sel = active.includes(ctx.state.pipeline) ? ctx.state.pipeline : active[active.length - 1];
  const a = agg[sel];
  const applies = stagesOf(sel);
  const durations = FLOW.map((n) => num(stageDur(a, n.id))).filter((v) => v !== null);
  const maxDur = durations.length ? Math.max(...durations, 1) : 1;

  const nodes = FLOW.map((n, i) => {
    const ok = applies.has(n.id);
    const dur = ok ? num(stageDur(a, n.id)) : null;
    const st = stageStats(a, n.id);
    const barPct = ok && dur !== null ? Math.max(2, (dur / maxDur) * 100) : 0;
    const color = !ok ? 'var(--text-2)'
      : dur !== null && dur > maxDur * 0.5 ? 'var(--warn)' : 'var(--success)';
    return `${i ? '<div class="flow-arrow">→</div>' : ''}
      <div class="flow-node ${ok ? '' : 'dim'}">
        <div class="fn-name">${esc(n.label)}</div>
        <div class="fn-dur">${ok ? (dur === null ? '<span class="fn-none">n/m</span>' : fmtMs(dur)) : 'n/a'}</div>
        <div class="fn-kv"><span>tokens</span><b>${ok ? fmtCompact(st.tokens) : 'n/a'}</b></div>
        <div class="fn-kv"><span>itens</span><b>${ok ? fmtNum(st.items) : 'n/a'}</b></div>
        <div class="fn-bar"><div style="height:100%;width:${barPct}%;background:${color};border-radius:2px"></div></div>
      </div>`;
  }).join('');

  return `
    <div class="page-toolbar">
      <span class="muted">Pipeline:</span>
      ${segmented('pipeline', active.map((p) => [p, PIPELINE_SHORT[p] || p]), sel)}
      <span class="pill info"><span class="dot"></span>${a.runs} runs (média)</span>
    </div>
    ${panel(`Fluxo — ${PIPELINE_LABEL[sel] || sel}`,
    `<div class="flow">${nodes}</div>
      <p class="muted flow-help">Nós que não existem neste pipeline aparecem esmaecidos com <b>n/a</b>;
      nós que existem mas cuja métrica não foi gravada mostram <b>n/m</b> (não medido). Barra: duração
      relativa ao estágio mais lento — verde = rápido, amarelo = &gt;50% do mais lento.</p>`,
    { sub: 'duração · tokens · itens', prov: 'experimental' })}
    <div class="grid grid-2">
      ${panel('Latência por estágio deste pipeline', '<div class="chart-wrap" data-chart="pipe-latency"></div>',
    { sub: 'ms', prov: 'experimental' })}
      ${panel('Funil de documentos', docFunnel(a), { sub: 'média por run', prov: 'experimental' })}
    </div>
    ${panel('Roteamento do juiz', judgeRouting(a), { sub: 'decisões por run (média)', prov: 'experimental' })}
  `;
}

function stageDur(a, id) {
  return ({
    QUERY: 0,
    RETRIEVAL: a.retrieval_latency_ms,
    GRAPHIFY: a.graphify_latency_ms,
    PREFILTER: 0,
    JEV: a.jev_latency_ms,
    FILTER: a.filter_latency_ms,
    CONTEXT: a.context_build_latency_ms,
    MODEL: a.generation_latency_ms,
  })[id] ?? null;
}
function stageStats(a, id) {
  return ({
    QUERY: { tokens: null, items: 1 },
    RETRIEVAL: { tokens: a.candidate_tokens_before_filter, items: a.documents_found },
    GRAPHIFY: { tokens: a.candidate_tokens_before_filter, items: a.documents_found },
    PREFILTER: { tokens: a.prefilter_tokens_saved_estimate, items: a.prefilter_sent },
    JEV: { tokens: a.jev_input_tokens, items: a.documents_sent_to_jev },
    FILTER: { tokens: a.survivor_tokens_snippets, items: a.survivors },
    CONTEXT: { tokens: a.context_tokens, items: a.documents_sent_to_model },
    MODEL: { tokens: a.model_input_tokens, items: a.documents_sent_to_model },
  })[id] || { tokens: null, items: null };
}

function docFunnel(a) {
  const steps = [
    ['Encontrados', a.documents_found, 'var(--info)'],
    ['Enviados ao juiz', a.documents_sent_to_jev, 'var(--warn)'],
    ['Sobreviventes', a.survivors, 'var(--success)'],
    ['No contexto final', a.documents_sent_to_model, 'var(--success)'],
  ].filter(([, v]) => num(v) !== null);
  if (!steps.length) return notMeasuredState('documents_found / documents_sent_to_jev / survivors');
  const top = Math.max(...steps.map(([, v]) => v), 1);
  return `<div class="funnel">${steps.map(([label, v, c]) => `
    <div class="funnel-row">
      <span class="funnel-label">${esc(label)}</span>
      <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(1, (v / top) * 100)}%;background:${c}"></div></div>
      <span class="funnel-val">${fmtNum(v)} <small>docs</small></span>
    </div>`).join('')}</div>`;
}

function judgeRouting(a) {
  const keys = [
    ['documents_kept', 'KEEP', 'var(--success)'],
    ['documents_review', 'REVIEW', 'var(--warn)'],
    ['documents_dropped', 'DROP', 'var(--text-2)'],
    ['documents_quarantined', 'QUARANTINE', 'var(--error)'],
    ['documents_unjudged', 'UNJUDGED', 'var(--info)'],
    ['documents_unselected', 'UNSELECTED', 'var(--purple)'],
  ].filter(([k]) => num(a[k]) !== null);
  if (!keys.length) return notMeasuredState('documents_kept / documents_dropped / …',
    'Este pipeline não chama o juiz, ou as runs carregadas não gravaram as decisões.');
  const top = Math.max(...keys.map(([k]) => num(a[k])), 1);
  return `<div class="funnel">${keys.map(([k, label, c]) => `
    <div class="funnel-row">
      <span class="funnel-label">${esc(label)}${help(k)}</span>
      <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(1, (num(a[k]) / top) * 100)}%;background:${c}"></div></div>
      <span class="funnel-val">${fmtNum(a[k], 2)} <small>docs</small></span>
    </div>`).join('')}
    <p class="muted flow-help">UNSELECTED = candidatos que o otimizador decidiu não pagar para julgar.
    Eles NUNCA sobrevivem; se aparecerem no contexto, é o vazamento que invalidou a medição antiga.</p>
    </div>`;
}

export function mountPipeline(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const sel = active.includes(ctx.state.pipeline) ? ctx.state.pipeline : active[active.length - 1];
  const w = root.querySelector('[data-chart="pipe-latency"]');
  if (w && sel) mountLatencyChart(w, agg, [sel]);
}

/* ====================================================== TOKENS ========== */
const TOKEN_VIEWS = {
  total: ['Total gasto', (a) => a.total_tokens, 'total_tokens'],
  context: ['Contexto entregue', (a) => a.context_tokens, 'context_tokens'],
  judge: ['Tokens do juiz', (a) => a.judge_tokens, 'judge_tokens'],
  saved: ['Economia estimada', (a) => a.saved_tokens, 'saved_tokens'],
};

export function renderTokens(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', '<p class="state-body">Sem dados de tokens.</p>');
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const view = TOKEN_VIEWS[ctx.state.tokenView] ? ctx.state.tokenView : 'total';
  const selP = active.includes(ctx.state.pipeline) ? ctx.state.pipeline : active[active.length - 1];
  const a = agg[selP];
  const b = agg[BASE];

  const recovered = num(a.candidate_tokens_before_filter);
  const survivors = num(a.survivor_tokens_snippets);
  const finalCtx = num(a.context_tokens);
  const discarded = recovered !== null && survivors !== null ? Math.max(0, recovered - survivors) : null;
  const spentTotal = num(a.total_tokens);
  const reduction = num(a.context_reduction);

  const funnelSteps = [
    ['Recuperados', recovered, 'var(--info)', 'candidate_tokens_before_filter'],
    ['Sobreviventes (snippets)', survivors, 'var(--warn)', 'survivor_tokens_snippets'],
    ['Descartados', discarded, 'var(--text-2)', 'recuperados − sobreviventes'],
    ['Entregues ao modelo', finalCtx, 'var(--success)', 'context_tokens'],
  ].filter(([, v]) => v !== null);
  const top = funnelSteps.length ? Math.max(...funnelSteps.map(([, v]) => v), 1) : 1;

  return `
    <div class="page-toolbar">
      <span class="muted">Pipeline:</span>${segmented('pipeline', active.map((p) => [p, PIPELINE_SHORT[p] || p]), selP)}
      <span class="muted toolbar-gap">Série do gráfico:</span>
      ${segmented('tokenView', Object.entries(TOKEN_VIEWS).map(([k, v]) => [k, v[0]]), view)}
    </div>

    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Contexto entregue', tipKey: 'consumer_context',
    value: finalCtx === null ? undefined : fmtCompact(finalCtx), unit: 'tokens',
    rawValue: finalCtx, ref: b.context_tokens, lowerIsBetter: true, context: 'vs baseline',
  })}
      ${metricCard({
    title: 'Tokens totais gastos', tipKey: 'total_tokens',
    value: spentTotal === null ? undefined : fmtCompact(spentTotal), unit: 'tokens',
    rawValue: spentTotal, ref: b.total_tokens, lowerIsBetter: true,
    context: 'vs baseline — inclui tokens do juiz',
  })}
      ${metricCard({
    title: 'Amplificação', tipKey: 'token_amplification',
    value: num(a.token_amplification) === null ? undefined : fmtAmp(a.token_amplification),
    unit: '× gasto / entregue', rawValue: a.token_amplification, ref: b.token_amplification,
    lowerIsBetter: true, context: '>1 gasta mais do que entrega',
  })}
      ${metricCard({
    title: 'Tokens do juiz', tipKey: 'judge_tokens',
    value: num(a.judge_tokens) === null ? undefined : fmtCompact(a.judge_tokens), unit: 'tokens',
    rawValue: a.judge_tokens, ref: b.judge_tokens, lowerIsBetter: true, context: 'custo extra do filtro',
  })}
      ${metricCard({
    title: 'Economia estimada', tipKey: 'saved_tokens',
    value: num(a.saved_tokens) === null ? undefined : fmtCompact(a.saved_tokens), unit: 'tokens',
    rawValue: a.saved_tokens, ref: b.saved_tokens, lowerIsBetter: false,
    context: 'estágios determinísticos (custo zero)',
    missingHint: 'nenhuma métrica prefilter/near-dedup/snippet nestas runs',
  })}
      ${metricCard({
    title: 'Tokens por pergunta paga', tipKey: 'questions',
    value: num(a.tokens_per_question) === null ? undefined : fmtNum(a.tokens_per_question, 0),
    unit: 'tokens/pergunta', rawValue: a.tokens_per_question, ref: b.tokens_per_question, lowerIsBetter: true,
    context: 'judge_tokens ÷ perguntas pagas',
    missingHint: 'exige jev_relevance_questions/jev_injection_questions',
  })}
    </div>

    ${panel('Eficiência de tokens — contexto entregue vs gasto total',
    `<div class="grid grid-duo">
       <div class="stat-box">
         <div class="metric-title">Redução do contexto final ${help('context_reduction')}</div>
         <div class="bignum" style="color:${reduction !== null && reduction > 0 ? 'var(--success)' : 'var(--text-1)'}">
           ${reduction === null ? 'Não medido' : fmtPct(reduction)}</div>
         <div class="muted stat-note">
           ${fmtCompact(recovered)} recuperados → ${fmtCompact(finalCtx)} entregues
         </div>
       </div>
       <div class="stat-box">
         <div class="metric-title">Amplificação total de tokens ${help('token_amplification')}</div>
         <div class="bignum" style="color:${ampColor(a.token_amplification)}">${num(a.token_amplification) === null ? 'Não medido' : fmtAmp(a.token_amplification)}</div>
         <div class="muted stat-note">
           gasta <b style="color:${totalTokenColor(spentTotal, b.total_tokens)}">${fmtCompact(spentTotal)}</b>
           para entregar ${fmtCompact(finalCtx)} · juiz ${fmtCompact(a.judge_tokens)}
           · baseline gasta ${fmtCompact(b.total_tokens)}
         </div>
       </div>
     </div>
     ${callout('warn', 'As duas métricas são intencionalmente distintas',
    'A redução do <b>contexto final</b> pode esconder um aumento do <b>gasto total</b>, porque os tokens '
    + 'enviados ao juiz também são pagos. E o inverso também ocorre: uma economia no juiz pode reaparecer '
    + 'como tokens de contexto no consumidor.')}
     ${funnelSteps.length ? `<div class="funnel">${funnelSteps.map(([label, v, c, srcKey]) => `
       <div class="funnel-row">
         <span class="funnel-label">${esc(label)} ${help(null, `fonte: ${srcKey}`)}</span>
         <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(1, (v / top) * 100)}%;background:${c}"></div></div>
         <span class="funnel-val">${fmtCompact(v)} <small>tokens</small></span>
       </div>`).join('')}</div>`
    : notMeasuredState('candidate_tokens_before_filter / context_tokens')}`,
    { sub: PIPELINE_LABEL[selP] || selP, prov: 'experimental' })}

    ${panel(`Tokens por pipeline — ${TOKEN_VIEWS[view][0]}`,
    '<div class="chart-wrap" data-chart="tok-bars"></div>', { sub: 'média por run', prov: 'experimental' })}
    ${panel('Detalhe de tokens por pipeline', tokenTable(agg, active), { sub: 'média por run', prov: 'experimental' })}
    ${panel('Estágios determinísticos (custo zero em tokens)', freeStagePanel(agg, active),
    { sub: 'estimativas do backend', prov: 'experimental' })}
  `;
}

/** The prefilter / near-dedup / snippet keys exist only on runs recorded after those stages were added. */
function freeStagePanel(agg, active) {
  const keys = [
    ['prefilter_top_k', 'top-K do pré-filtro'],
    ['prefilter_in', 'Candidatos na entrada'],
    ['prefilter_sent', 'Enviados ao juiz'],
    ['prefilter_withheld', 'Retidos (não julgados)'],
    ['prefilter_tokens_saved_estimate', 'Tokens poupados pelo pré-filtro (est.)'],
    ['dedup_near_collapsed', 'Duplicatas próximas colapsadas'],
    ['dedup_near_tokens_saved_estimate', 'Tokens poupados pelo near-dedup (est.)'],
    ['snippet_tokens_saved', 'Tokens poupados pelo smart snippet (est.)'],
  ];
  const withData = active.filter((p) => keys.some(([k]) => num(agg[p][k]) !== null));
  if (!withData.length) {
    return notMeasuredState('prefilter_* / dedup_near_* / snippet_tokens_saved',
      'As chaves existem no backend, mas nenhuma das runs carregadas as contém. '
      + 'Execute um novo benchmark para populá-las.');
  }
  const rows = keys
    .filter(([k]) => withData.some((p) => num(agg[p][k]) !== null))
    .map(([k, label]) => `<tr>
      <th class="rowhead">${esc(label)}${help(k === 'prefilter_top_k' ? 'prefilter' : 'saved_tokens')}</th>
      ${withData.map((p) => `<td class="num">${num(agg[p][k]) === null ? '<span class="muted">—</span>' : fmtCompact(agg[p][k])}</td>`).join('')}
    </tr>`);
  return `${callout('info', 'São estimativas do backend',
    'Estes valores vêm de <code>*_tokens_saved_estimate</code>: o backend calcula quantos tokens os '
    + 'candidatos retidos teriam custado. Não são tokens medidos em uma chamada real e não devem ser '
    + 'somados ao gasto observado como se fossem.')}
    ${table([{ label: 'Métrica' }, ...withData.map((p) => ({ label: PIPELINE_SHORT[p] || p, num: true }))], rows)}`;
}

function totalTokenColor(v, ref) {
  if (num(v) === null || !num(ref)) return 'var(--text-0)';
  if (v > ref * 1.15) return 'var(--error)';
  if (v < ref * 0.85) return 'var(--success)';
  return 'var(--text-0)';
}

function tokenTable(agg, active) {
  const keys = [
    ['candidate_tokens_before_filter', 'Recuperados'], ['survivor_tokens_snippets', 'Sobreviventes'],
    ['context_tokens', 'Contexto entregue'], ['jev_input_tokens', 'JEV input'], ['jev_output_tokens', 'JEV output'],
    ['model_input_tokens', 'Modelo input'], ['model_output_tokens', 'Modelo output'],
    ['judge_tokens', 'Tokens do juiz'], ['total_tokens', 'TOTAL gasto'], ['saved_tokens', 'Economia estimada'],
  ];
  const rows = keys.map(([k, label]) => {
    const anyVal = active.some((p) => num(agg[p][k]) !== null);
    return `<tr class="${anyVal ? '' : 'row-empty'}">
      <th class="rowhead">${esc(label)}${help(k)}</th>
      ${active.map((p) => `<td class="num">${num(agg[p][k]) === null ? '<span class="muted">—</span>' : fmtCompact(agg[p][k])}</td>`).join('')}
    </tr>`;
  });
  rows.push(`<tr>
    <th class="rowhead">Amplificação${help('token_amplification')}</th>
    ${active.map((p) => `<td class="num" style="color:${ampColor(agg[p].token_amplification)}">${fmtAmp(agg[p].token_amplification)}</td>`).join('')}
  </tr>`);
  return table([{ label: 'Métrica' }, ...active.map((p) => ({ label: PIPELINE_SHORT[p] || p, num: true }))], rows);
}

export function mountTokens(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const view = TOKEN_VIEWS[ctx.state.tokenView] ? ctx.state.tokenView : 'total';
  const [label, valFn] = TOKEN_VIEWS[view];
  const w = root.querySelector('[data-chart="tok-bars"]');
  if (!w) return;
  hBarChart(w, {
    rows: active.map((p) => ({
      label: PIPELINE_SHORT[p] || p, value: num(valFn(agg[p])) || 0, color: PIPELINE_COLOR[p],
      tip: `total ${fmtCompact(agg[p].total_tokens)} · ctx ${fmtCompact(agg[p].context_tokens)}`,
    })),
    unit: 'tokens', fmt: fmtCompact, emptyMsg: `nenhuma run carregada registra "${label}"`,
  });
}

/* ====================================================== LATENCY ========= */
export function renderLatency(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', '<p class="state-body">Sem dados de latência.</p>');
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const b = agg[BASE];
  const cards = active.map((p) => metricCard({
    title: PIPELINE_LABEL[p] || p, tipKey: 'total_latency_ms',
    value: num(agg[p].total_latency_ms) === null ? undefined : fmtMs(agg[p].total_latency_ms),
    unit: 'total / run', rawValue: agg[p].total_latency_ms, ref: b.total_latency_ms, lowerIsBetter: true,
    context: p === BASE ? 'referência (baseline)' : `vs baseline · mediana ${fmtMs(agg[p].total_latency_ms_median)}`,
  })).join('');

  const rows = LATENCY_STAGES.map(([k, label, stage]) => `<tr>
    <th class="rowhead">${esc(label)}${help(k)}</th>
    ${active.map((p) => {
    const v = num(agg[p][k]);
    const applies = stagesOf(p).has(stage);
    return `<td class="num ${v === null ? 'muted' : ''}">${v === null ? (applies ? 'n/m' : 'n/a') : fmtMs(v)}</td>`;
  }).join('')}
  </tr>`);

  return `
    <div class="grid grid-kpi">${cards}</div>
    ${panel('Latência por estágio (agrupada por pipeline)',
    '<div class="chart-wrap" data-chart="lat-grouped"></div>',
    { sub: 'retrieval · graphify · jev · full-note · filter · context build · total', prov: 'experimental' })}
    ${panel('Tabela de estágios', table(
    [{ label: 'Estágio' }, ...active.map((p) => ({ label: PIPELINE_SHORT[p] || p, num: true }))], rows),
  { sub: 'média em ms · "n/a" = estágio não existe · "n/m" = não medido', prov: 'experimental' })}
  `;
}
export function mountLatency(root, ctx) {
  const agg = aggregate(ctx.runs);
  const w = root.querySelector('[data-chart="lat-grouped"]');
  if (w) mountLatencyChart(w, agg, activeOf(agg));
}

/* ====================================================== COSTS =========== */
const COST_VIEWS = {
  total: ['Custo total', (a) => a.total_cost, fmtCost, 'USD'],
  agent: ['Custo do modelo', (a) => a.model_cost, fmtCost, 'USD'],
  jev: ['Custo do juiz', (a) => a.jev_cost, fmtCost, 'USD'],
  per_1k: ['Custo por 1K tokens', (a) => a.cost_per_1k, fmtCost, 'USD/1K tokens'],
};

export function renderCosts(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', '<p class="state-body">Sem dados de custo.</p>');
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const view = COST_VIEWS[ctx.state.costView] ? ctx.state.costView : 'total';
  const b = agg[BASE];
  const optKey = optimizedOf(agg);
  const jv = optKey ? agg[optKey] : b;
  const anyCost = active.some((p) => num(agg[p].total_cost) !== null || num(agg[p].jev_cost) !== null);

  const rows = active.map((p) => {
    const a = agg[p];
    return `<tr>
      <th class="rowhead">${esc(PIPELINE_LABEL[p] || p)}</th>
      <td class="num">${a.runs}</td>
      <td class="num">${fmtCost(a.model_cost)}</td>
      <td class="num">${fmtCost(a.jev_cost)}</td>
      <td class="num">${fmtCost(a.total_cost)}</td>
      <td class="num">${fmtCost(a.cost_per_1k)}</td>
      <td class="num">${fmtCompact(a.total_tokens)}</td>
    </tr>`;
  });

  return `
    <div class="page-toolbar">
      <span class="muted">Série:</span>${segmented('costView', Object.entries(COST_VIEWS).map(([k, v]) => [k, v[0]]), view)}
    </div>
    ${anyCost ? '' : callout('warn', 'As runs carregadas não registram custo',
    'Elas são <code>mode=retrieval</code> sem geração paga, então <code>total_cost</code> e '
    + '<code>jev_cost</code> são nulos ou zero. Os cartões abaixo mostram "Não medido" em vez de $0 '
    + 'inventado. Rode um benchmark com <code>consumers</code> para medir custo real.')}
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Custo total / run', tipKey: 'total_cost',
    value: num(jv.total_cost) === null ? undefined : fmtCost(jv.total_cost),
    unit: 'USD', rawValue: jv.total_cost, ref: b.total_cost, lowerIsBetter: true, context: 'vs baseline',
    missingHint: 'total_cost/model_cost/jev_cost ausentes',
  })}
      ${metricCard({
    title: 'Custo do juiz', tipKey: 'jev_cost',
    value: num(jv.jev_cost) === null ? undefined : fmtCost(jv.jev_cost), unit: 'USD / run',
    rawValue: jv.jev_cost, ref: b.jev_cost, lowerIsBetter: true, context: 'só pipelines com juiz',
  })}
      ${metricCard({
    title: 'Custo por 1K tokens', tipKey: 'cost_per_1k',
    value: num(jv.cost_per_1k) === null ? undefined : fmtCost(jv.cost_per_1k),
    unit: 'USD / 1K', rawValue: jv.cost_per_1k, ref: b.cost_per_1k, lowerIsBetter: true, context: 'vs baseline',
  })}
      ${metricCard({
    title: 'Custo acumulado', tipKey: 'total_cost',
    value: num(jv.total_cost_sum) === null ? undefined : fmtCost(jv.total_cost_sum),
    unit: `USD em ${jv.runs} runs`, deltaText: 'soma', deltaCls: 'flat', context: 'soma das runs carregadas',
  })}
    </div>
    ${panel(`Gráfico — ${COST_VIEWS[view][0]}`, '<div class="chart-wrap" data-chart="cost-bars"></div>',
    { sub: COST_VIEWS[view][3], prov: 'experimental' })}
    ${panel('Detalhe de custos', table([
    { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Modelo', num: true, tip: 'metrics.model_cost' },
    { label: 'Juiz', num: true, tipKey: 'jev_cost' },
    { label: 'Total', num: true, tipKey: 'total_cost' },
    { label: 'Por 1K tokens', num: true, tipKey: 'cost_per_1k' },
    { label: 'Tokens totais', num: true, tipKey: 'total_tokens' },
  ], rows), { sub: 'média por run', prov: 'experimental' })}
  `;
}
export function mountCosts(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = activeOf(agg);
  const view = COST_VIEWS[ctx.state.costView] ? ctx.state.costView : 'total';
  const [label, valFn, fmt, unit] = COST_VIEWS[view];
  const w = root.querySelector('[data-chart="cost-bars"]');
  if (!w) return;
  hBarChart(w, {
    rows: active.map((p) => ({ label: PIPELINE_SHORT[p] || p, value: num(valFn(agg[p])) || 0, color: PIPELINE_COLOR[p] })),
    unit, fmt, emptyMsg: `nenhuma run registrou "${label}" (métrica ausente ou igual a zero)`,
  });
}
