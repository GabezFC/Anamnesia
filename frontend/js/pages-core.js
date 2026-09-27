// pages-core.js — Dashboard, Benchmarks, Pipeline, Tokens, Latency, Costs.
import { hBarChart, groupedBarChart } from './charts.js';
import {
  PIPELINES, PIPELINE_LABEL, PIPELINE_COLOR, esc, fmtNum, fmtCompact, fmtMs, fmtCost, fmtPct,
  get, num, delta, realRuns, byPipeline, metricsOf, totalTokens, tokenAmplification, recallOf, mean,
} from './format.js';
import {
  metricCard, panel, emptyState, table, segmented, help, skeletonChart,
} from './components.js';
import { aggregate, LATENCY_STAGES, STAGE_APPLIES } from './store.js';
import { detectAnomalies, RULES } from './anomalies.js';

const BASE = 'baseline';

/** Amplification formatted as "43.2×". */
const ampText = (v) => (num(v) === null ? '—' : `${num(v).toFixed(num(v) >= 10 ? 1 : 2)}×`);
const ampColor = (v) => (num(v) === null ? 'var(--text-0)'
  : num(v) > 3 ? 'var(--error)' : num(v) > 1.5 ? 'var(--warn)' : 'var(--success)');

/**
 * The headline trade-off banner: final-context reduction looks great while total spend explodes.
 * Rendered only when the data actually shows the divergence — never asserted blindly.
 */
function tradeoffBanner(agg) {
  const j = agg.graphify_jev; const b = agg[BASE];
  if (!j || !j.runs || num(j.token_amplification) === null) return '';
  const amp = num(j.token_amplification);
  const red = num(j.context_reduction);
  if (!(amp > 1.5)) return '';
  const spendX = b.total_tokens ? j.total_tokens / b.total_tokens : null;
  return `<section class="panel" style="border-color:rgba(245,158,11,.4)">
    <div class="panel-head"><h2>Leitura obrigatória — redução de contexto ≠ economia de tokens</h2>
      <span class="panel-sub">Graphify + JEV vs Baseline</span></div>
    <div class="panel-body">
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px">
        <div>
          <div class="metric-title">Contexto final entregue ${help('context_reduction')}</div>
          <div class="bignum" style="color:var(--success)">${red === null ? '—' : `−${(red * 100).toFixed(0)}%`}</div>
          <div class="muted" style="font-size:12px;margin-top:6px">parece uma grande melhora</div>
        </div>
        <div>
          <div class="metric-title">Tokens totais gastos ${help('total_tokens')}</div>
          <div class="bignum" style="color:var(--error)">${spendX === null ? '—' : `${spendX.toFixed(1)}×`}</div>
          <div class="muted" style="font-size:12px;margin-top:6px">
            ${fmtCompact(j.total_tokens)} vs ${fmtCompact(b.total_tokens)} no baseline
          </div>
        </div>
        <div>
          <div class="metric-title">Amplificação ${help('token_amplification')}</div>
          <div class="bignum" style="color:${ampColor(amp)}">${ampText(amp)}</div>
          <div class="muted" style="font-size:12px;margin-top:6px">gasto ÷ contexto entregue</div>
        </div>
      </div>
      <p class="muted" style="font-size:12px;margin:16px 0 0;border-left:2px solid var(--warn);padding-left:10px">
        O pipeline <b>graphify_jev</b> reduz o contexto final em ${red === null ? 'n/a' : `${(red * 100).toFixed(0)}%`},
        mas paga ${fmtCompact(j.judge_tokens)} tokens ao juiz para conseguir isso — gastando
        ${spendX === null ? 'n/a' : `${spendX.toFixed(1)}×`} mais tokens no total que o baseline.
        Um dashboard que mostrasse apenas o contexto final esconderia exatamente esse custo.
      </p>
    </div>
  </section>`;
}

/* ====================================================== DASHBOARD ======= */
export function renderDashboard(ctx) {
  const { runs } = ctx;
  const rs = realRuns(runs);
  if (!rs.length) {
    return emptyState('Nenhuma run registrada',
      'Execute um benchmark (<code>POST /benchmark/run-all</code>) para popular o dashboard.');
  }
  const agg = aggregate(runs);
  const b = agg[BASE];
  const jev = agg.graphify_jev;
  const pipeCount = PIPELINES.filter((p) => agg[p].runs > 0).length;

  const kpis = [
    metricCard({
      title: 'Total Tokens Spent', tipKey: 'total_tokens',
      value: fmtCompact(jev.total_tokens ?? b.total_tokens), unit: 'tokens / run (gasto real)',
      rawValue: jev.total_tokens, ref: b.total_tokens, lowerIsBetter: true,
      context: `vs baseline · contexto final ${fmtCompact(jev.context_tokens ?? b.context_tokens)} tokens`,
    }),
    metricCard({
      title: 'Token Amplification', tipKey: 'token_amplification',
      value: ampText(jev.token_amplification ?? b.token_amplification), unit: '× gasto / entregue',
      rawValue: jev.token_amplification, ref: b.token_amplification, lowerIsBetter: true,
      context: 'vs baseline · >1 gasta mais do que entrega',
    }),
    metricCard({
      title: 'Total Latency', tipKey: 'total_latency_ms',
      value: fmtMs(jev.total_latency_ms ?? b.total_latency_ms), unit: 'por run',
      rawValue: jev.total_latency_ms, ref: b.total_latency_ms, lowerIsBetter: true,
      context: 'vs baseline (média)',
    }),
    metricCard({
      title: 'Total Cost', tipKey: 'total_cost',
      value: fmtCost(jev.total_cost ?? b.total_cost), unit: 'USD / run',
      rawValue: jev.total_cost, ref: b.total_cost, lowerIsBetter: true,
      context: 'vs baseline (média)',
    }),
    metricCard({
      title: 'Documents Retrieved', tipKey: 'documents_found',
      value: fmtNum(jev.documents_found ?? b.documents_found), unit: 'docs / run',
      rawValue: jev.documents_found, ref: b.documents_found, lowerIsBetter: false,
      context: 'vs baseline (média)',
    }),
    metricCard({
      title: 'Final Context', tipKey: 'context_tokens',
      value: fmtCompact(jev.context_tokens ?? b.context_tokens), unit: 'tokens',
      rawValue: jev.context_tokens, ref: b.context_tokens, lowerIsBetter: true,
      context: 'vs baseline (média)',
    }),
    metricCard({
      title: 'Efficiency', tipKey: 'efficiency',
      value: fmtNum(jev.efficiency ?? b.efficiency, 2), unit: 'docs / 1K tokens',
      rawValue: jev.efficiency, ref: b.efficiency, lowerIsBetter: false,
      context: 'vs baseline (média)',
    }),
  ].join('');

  const anomalies = detectAnomalies(runs, ctx.details || []);
  const sev = { error: 0, warn: 0, info: 0 };
  for (const a of anomalies) sev[a.severity] += 1;

  return `
    <div class="grid grid-kpi">${kpis}</div>
    ${tradeoffBanner(agg)}
    <div class="grid grid-2">
      ${panel('Tokens por pipeline', '<div class="chart-wrap" data-chart="dash-tokens"></div>',
    `${rs.length} runs · warm-up excluído`)}
      ${panel('Latência por estágio', '<div class="chart-wrap" data-chart="dash-latency"></div>',
    'média em ms')}
    </div>
    ${panel('Resumo por pipeline', pipelineSummaryTable(agg), `${pipeCount} pipelines com dados`)}
    ${panel('Anomalias detectadas',
    anomalies.length
      ? `<div class="page-toolbar">
           <span class="pill err"><span class="dot"></span>${sev.error} erro</span>
           <span class="pill warn"><span class="dot"></span>${sev.warn} atenção</span>
         </div>${anomalies.slice(0, 8).map(anomalyCard).join('')}
         ${anomalies.length > 8 ? `<p class="muted">+${anomalies.length - 8} outras — ver aba Benchmarks.</p>` : ''}`
      : emptyState('Nenhuma anomalia', `Regras avaliadas: ${RULES.length}.`),
    `${anomalies.length} ocorrência(s)`)}
  `;
}

export function mountDashboard(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const t = root.querySelector('[data-chart="dash-tokens"]');
  if (t) {
    hBarChart(t, {
      rows: active.map((p) => ({
        label: PIPELINE_LABEL[p], value: agg[p].total_tokens || 0, color: PIPELINE_COLOR[p],
        tip: `contexto ${fmtCompact(agg[p].context_tokens)} · JEV in ${fmtCompact(agg[p].jev_input_tokens)}`,
      })),
      unit: 'tokens (média/run)', fmt: fmtCompact, emptyMsg: 'nenhuma métrica de tokens nas runs',
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
      label: PIPELINE_LABEL[p], color: PIPELINE_COLOR[p],
      values: stages.map(([k]) => num(agg[p][k]) || 0),
    })),
    unit: 'ms', fmt: fmtMs, emptyMsg: 'nenhuma métrica de latência por estágio',
  });
}

function pipelineSummaryTable(agg) {
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const rows = active.map((p) => {
    const a = agg[p];
    const d = (v, ref, low = true) => {
      if (p === BASE) return '<td class="num muted">ref</td>';
      const x = delta(v, ref, low);
      return `<td class="num"><span class="delta ${x.cls}">${x.text}</span></td>`;
    };
    return `<tr>
      <th class="rowhead">${esc(PIPELINE_LABEL[p])}</th>
      <td class="num">${a.runs}</td>
      <td class="num">${fmtCompact(a.total_tokens)}</td>${d(a.total_tokens, agg[BASE].total_tokens)}
      <td class="num">${fmtCompact(a.context_tokens)}</td>
      <td class="num">${fmtMs(a.total_latency_ms)}</td>${d(a.total_latency_ms, agg[BASE].total_latency_ms)}
      <td class="num">${fmtCost(a.total_cost)}</td>
      <td class="num">${fmtPct(a.context_reduction)}</td>
      <td class="num">${a.recall === null ? '—' : fmtPct(a.recall)}</td>
    </tr>`;
  });
  return table([
    { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Tokens totais', num: true, tipKey: 'total_tokens' }, { label: 'Δ vs base', num: true },
    { label: 'Contexto final', num: true, tipKey: 'context_tokens' },
    { label: 'Latência', num: true, tipKey: 'total_latency_ms' }, { label: 'Δ vs base', num: true },
    { label: 'Custo', num: true, tipKey: 'total_cost' },
    { label: 'Redução ctx', num: true, tipKey: 'context_reduction' },
    { label: 'Recall', num: true, tipKey: 'recall' },
  ], rows);
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
  ['Tokens totais GASTOS', (a) => fmtCompact(a.total_tokens), (a) => a.total_tokens, true, 'total_tokens'],
  ['Tokens do juiz (JEV)', (a) => fmtCompact(a.judge_tokens), (a) => a.judge_tokens, true, 'judge_tokens'],
  ['Amplificação (gasto/entregue)', (a) => ampText(a.token_amplification), (a) => a.token_amplification, true, 'token_amplification'],
  ['Context tokens', (a) => fmtCompact(a.context_tokens), (a) => a.context_tokens, true, 'context_tokens'],
  ['Input tokens (modelo)', (a) => fmtCompact(a.model_input_tokens), (a) => a.model_input_tokens, true, 'jev_input_tokens'],
  ['Output tokens (modelo)', (a) => fmtCompact(a.model_output_tokens), (a) => a.model_output_tokens, true, null],
  ['JEV input tokens', (a) => fmtCompact(a.jev_input_tokens), (a) => a.jev_input_tokens, true, 'jev_input_tokens'],
  ['JEV output tokens', (a) => fmtCompact(a.jev_output_tokens), (a) => a.jev_output_tokens, true, 'jev_output_tokens'],
  ['Latency', (a) => fmtMs(a.total_latency_ms), (a) => a.total_latency_ms, true, 'total_latency_ms'],
  ['Cost', (a) => fmtCost(a.total_cost), (a) => a.total_cost, true, 'total_cost'],
  ['Candidates', (a) => fmtNum(a.candidates), (a) => a.candidates, false, null],
  ['Documents (dedup)', (a) => fmtNum(a.documents_deduplicated), (a) => a.documents_deduplicated, false, 'documents_deduplicated'],
  ['Final context (docs)', (a) => fmtNum(a.documents_sent_to_model), (a) => a.documents_sent_to_model, false, 'documents_sent_to_model'],
  ['Recall', (a) => (a.recall === null ? '—' : fmtPct(a.recall)), (a) => a.recall, false, 'recall'],
];

export function renderBenchmarks(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'Nada para comparar ainda.');
  const agg = aggregate(ctx.runs);
  const cols = PIPELINES.filter((p) => agg[p].runs > 0);

  const rows = CMP_ROWS.map(([label, fmt, val, lowerBetter, tipKey]) => {
    const vals = cols.map((p) => num(val(agg[p])));
    const ref = num(val(agg[BASE]));
    const cells = cols.map((p, i) => {
      const v = vals[i];
      if (v === null) return '<td class="num muted">—</td>';
      // Highlight only SIGNIFICANT differences (>=15% vs baseline).
      let cls = '';
      if (p !== BASE && ref) {
        const pct = (v - ref) / Math.abs(ref);
        if (Math.abs(pct) >= 0.15) cls = (pct < 0) === lowerBetter ? 'sig-down' : 'sig-up';
      }
      return `<td class="num ${cls}">${fmt(agg[p])}</td>`;
    });
    return `<tr><th class="rowhead">${esc(label)}${help(tipKey)}</th>${cells.join('')}</tr>`;
  });

  const anomalies = detectAnomalies(ctx.runs, ctx.details || []);

  return `
    ${panel('Comparação de pipelines',
    `<p class="muted" style="margin:0 0 12px">Colunas são os três pipelines reais do backend. Valores = média das runs
     (warm-up excluído). Destaque de cor apenas quando a diferença vs <b>Baseline</b> ≥ 15%:
     <span style="color:var(--success)">verde = melhora</span>, <span style="color:var(--error)">vermelho = piora</span>.</p>`
    + table([{ label: 'Métrica' }, ...cols.map((p) => ({ label: PIPELINE_LABEL[p], num: true }))], rows),
    `${rs.length} runs`)}
    ${panel('Anomalias (todas)',
    anomalies.length ? anomalies.map(anomalyCard).join('')
      : emptyState('Nenhuma anomalia detectada', `Regras avaliadas:<br><span class="mono">${RULES.map(esc).join('<br>')}</span>`),
    `${anomalies.length} ocorrência(s) · ${RULES.length} regras`)}
    ${panel('Regras de anomalia aplicadas',
    `<ul class="muted" style="margin:0;padding-left:18px">${RULES.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`)}
  `;
}

/* ====================================================== PIPELINE ======== */
const FLOW = [
  { id: 'QUERY', label: 'Query' },
  { id: 'RETRIEVAL', label: 'Retrieval' },
  { id: 'GRAPHIFY', label: 'Graphify' },
  { id: 'JEV', label: 'JEV' },
  { id: 'FILTER', label: 'Filter' },
  { id: 'CONTEXT', label: 'Context' },
  { id: 'MODEL', label: 'Model' },
];

export function renderPipeline(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'Sem dados de pipeline.');
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const sel = active.includes(ctx.state.pipeline) ? ctx.state.pipeline : active[active.length - 1];
  const a = agg[sel];
  const applies = STAGE_APPLIES[sel] || new Set();
  const maxDur = Math.max(...FLOW.map((n) => num(stageDur(a, n.id)) || 0), 1);

  const nodes = FLOW.map((n, i) => {
    const ok = applies.has(n.id);
    const dur = ok ? stageDur(a, n.id) : null;
    const st = stageStats(a, n.id);
    const barPct = ok && dur !== null ? Math.max(2, (dur / maxDur) * 100) : 0;
    const color = !ok ? 'var(--text-2)'
      : dur !== null && dur > maxDur * 0.5 ? 'var(--warn)'
        : 'var(--success)';
    return `${i ? '<div class="flow-arrow">→</div>' : ''}
      <div class="flow-node ${ok ? '' : 'dim'}">
        <div class="fn-name">${esc(n.label)}</div>
        <div class="fn-dur">${ok ? (dur === null ? '—' : fmtMs(dur)) : 'n/a'}</div>
        <div class="fn-kv"><span>tokens</span><b>${ok ? fmtCompact(st.tokens) : 'n/a'}</b></div>
        <div class="fn-kv"><span>itens</span><b>${ok ? fmtNum(st.items) : 'n/a'}</b></div>
        <div class="fn-bar"><div style="height:100%;width:${barPct}%;background:${color};border-radius:2px"></div></div>
      </div>`;
  }).join('');

  return `
    <div class="page-toolbar">
      <span class="muted">Pipeline:</span>
      ${segmented('pipeline', active.map((p) => [p, PIPELINE_LABEL[p]]), sel)}
      <span class="pill info"><span class="dot"></span>${a.runs} runs (média)</span>
    </div>
    ${panel(`Fluxo — ${PIPELINE_LABEL[sel]}`, `<div class="flow">${nodes}</div>
      <p class="muted" style="margin:12px 0 0;font-size:12px">Nós não aplicáveis a este pipeline aparecem esmaecidos
      com <b>n/a</b>. Barra: duração relativa ao estágio mais lento. Verde = rápido, amarelo = &gt;50% do mais lento.</p>`,
    'duração · tokens · itens')}
    <div class="grid grid-2">
      ${panel('Latência por estágio deste pipeline', '<div class="chart-wrap" data-chart="pipe-latency"></div>', 'ms')}
      ${panel('Funil de documentos', docFunnel(a), 'média por run')}
    </div>
  `;
}

function stageDur(a, id) {
  return ({
    QUERY: 0,
    RETRIEVAL: a.retrieval_latency_ms,
    GRAPHIFY: a.graphify_latency_ms,
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
    GRAPHIFY: { tokens: a.candidate_tokens_before_filter, items: a.documents_deduplicated },
    JEV: { tokens: a.jev_input_tokens, items: a.documents_sent_to_jev },
    FILTER: { tokens: a.survivor_tokens_snippets, items: a.survivors },
    CONTEXT: { tokens: a.context_tokens, items: a.documents_sent_to_model },
    MODEL: { tokens: a.model_input_tokens, items: a.documents_sent_to_model },
  })[id] || { tokens: null, items: null };
}

function docFunnel(a) {
  const steps = [
    ['Encontrados', a.documents_found, 'var(--info)'],
    ['Após dedup', a.documents_deduplicated, 'var(--info)'],
    ['Enviados ao JEV', a.documents_sent_to_jev, 'var(--warn)'],
    ['Sobreviventes', a.survivors, 'var(--success)'],
    ['No contexto final', a.documents_sent_to_model, 'var(--success)'],
  ].filter(([, v]) => num(v) !== null);
  if (!steps.length) return emptyState('Sem métricas de documentos', 'nenhuma das chaves documents_* está presente');
  const top = Math.max(...steps.map(([, v]) => v));
  return `<div class="funnel">${steps.map(([label, v, c]) => `
    <div class="funnel-row">
      <span class="funnel-label">${esc(label)}</span>
      <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(1, (v / top) * 100)}%;background:${c}"></div></div>
      <span class="funnel-val">${fmtNum(v)} <small>docs</small></span>
    </div>`).join('')}</div>`;
}

export function mountPipeline(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const sel = active.includes(ctx.state.pipeline) ? ctx.state.pipeline : active[active.length - 1];
  const w = root.querySelector('[data-chart="pipe-latency"]');
  if (w) mountLatencyChart(w, agg, [sel]);
}

/* ====================================================== TOKENS ========== */
const TOKEN_VIEWS = {
  total: ['Total', (a) => a.total_tokens, 'total_tokens'],
  context: ['Contexto', (a) => a.context_tokens, 'context_tokens'],
  input: ['Input (JEV+modelo)', (a) => ((num(a.jev_input_tokens) || 0) + (num(a.model_input_tokens) || 0)) || null, 'jev_input_tokens'],
  output: ['Output (JEV+modelo)', (a) => ((num(a.jev_output_tokens) || 0) + (num(a.model_output_tokens) || 0)) || null, 'jev_output_tokens'],
};

export function renderTokens(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'Sem dados de tokens.');
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
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
    ['Filtrados (sobreviventes)', survivors, 'var(--warn)', 'survivor_tokens_snippets'],
    ['Descartados', discarded, 'var(--error)', 'recuperados − sobreviventes'],
    ['Enviados ao modelo', finalCtx, 'var(--success)', 'context_tokens'],
  ].filter(([, v]) => v !== null);
  const top = funnelSteps.length ? Math.max(...funnelSteps.map(([, v]) => v)) : 1;

  return `
    <div class="page-toolbar">
      <span class="muted">Pipeline:</span>${segmented('pipeline', active.map((p) => [p, PIPELINE_LABEL[p]]), selP)}
      <span class="muted" style="margin-left:12px">Série do gráfico:</span>
      ${segmented('tokenView', Object.entries(TOKEN_VIEWS).map(([k, v]) => [k, v[0]]), view)}
    </div>

    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Contexto final', tipKey: 'context_tokens', value: fmtCompact(finalCtx), unit: 'tokens',
    rawValue: finalCtx, ref: b.context_tokens, lowerIsBetter: true, context: 'vs baseline',
  })}
      ${metricCard({
    title: 'TOKENS TOTAIS GASTOS', tipKey: 'total_tokens', value: fmtCompact(spentTotal), unit: 'tokens',
    rawValue: spentTotal, ref: b.total_tokens, lowerIsBetter: true,
    context: 'vs baseline — inclui tokens do juiz',
  })}
      ${metricCard({
    title: 'Amplificação', tipKey: 'token_amplification', value: ampText(a.token_amplification),
    unit: '× gasto / entregue', rawValue: a.token_amplification, ref: b.token_amplification,
    lowerIsBetter: true, context: 'vs baseline · >1 gasta mais do que entrega',
  })}
      ${metricCard({
    title: 'Tokens do juiz', tipKey: 'judge_tokens', value: fmtCompact(a.judge_tokens), unit: 'tokens',
    rawValue: a.judge_tokens, ref: b.judge_tokens, lowerIsBetter: true, context: 'custo extra do filtro JEV',
  })}
    </div>

    ${panel('Eficiência de tokens — contexto final vs gasto total',
    `<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px">
       <div style="border:1px solid var(--line-0);border-radius:6px;padding:16px;background:var(--surface-1)">
         <div class="metric-title">Redução do contexto final ${help('context_reduction')}</div>
         <div class="bignum" style="color:${reduction !== null && reduction > 0 ? 'var(--success)' : 'var(--text-1)'}">
           ${reduction === null ? '—' : fmtPct(reduction)}</div>
         <div class="muted" style="font-size:12px;margin-top:6px">
           ${fmtCompact(recovered)} recuperados → ${fmtCompact(finalCtx)} enviados
         </div>
       </div>
       <div style="border:1px solid var(--line-0);border-radius:6px;padding:16px;background:var(--surface-1)">
         <div class="metric-title">Amplificação total de tokens ${help('token_amplification')}</div>
         <div class="bignum" style="color:${ampColor(a.token_amplification)}">${ampText(a.token_amplification)}</div>
         <div class="muted" style="font-size:12px;margin-top:6px">
           gasta <b style="color:${totalTokenColor(spentTotal, b.total_tokens)}">${fmtCompact(spentTotal)}</b>
           para entregar ${fmtCompact(finalCtx)} · juiz ${fmtCompact(a.judge_tokens)}
           · baseline gasta ${fmtCompact(b.total_tokens)}
         </div>
       </div>
     </div>
     <p class="muted" style="font-size:12px;margin:0 0 14px;border-left:2px solid var(--warn);padding-left:10px">
       As duas métricas são intencionalmente distintas: a redução do <b>contexto final</b> pode esconder um aumento
       do <b>gasto total</b>, porque os tokens enviados ao JEV para julgamento também são pagos.
     </p>
     <div class="funnel">${funnelSteps.map(([label, v, c, srcKey]) => `
       <div class="funnel-row">
         <span class="funnel-label">${esc(label)} ${help(null, `fonte: ${srcKey}`)}</span>
         <div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(1, (v / top) * 100)}%;background:${c}"></div></div>
         <span class="funnel-val">${fmtCompact(v)} <small>tokens</small></span>
       </div>`).join('')}</div>`,
    PIPELINE_LABEL[selP])}

    ${panel(`Tokens por pipeline — ${TOKEN_VIEWS[view][0]}`,
    '<div class="chart-wrap" data-chart="tok-bars"></div>', 'média por run')}
    ${panel('Detalhe de tokens por pipeline', tokenTable(agg, active), 'média por run')}
    ${panel('Pré-filtro determinístico (top-K antes do juiz pago)', prefilterPanel(agg, active), 'custa zero tokens')}
  `;
}

/** prefilter_* keys exist only on runs recorded after the prefilter stage was added. */
function prefilterPanel(agg, active) {
  const withData = active.filter((p) => num(agg[p].prefilter_in) !== null);
  if (!withData.length) {
    return emptyState('Nenhuma run tem métricas de pré-filtro',
      'As chaves <code>prefilter_in / prefilter_sent / prefilter_withheld / prefilter_tokens_saved_estimate / '
      + 'prefilter_top_k</code> existem no backend, mas nenhuma das runs já gravadas as contém. '
      + 'Execute um novo benchmark para populá-las.');
  }
  const keys = [
    ['prefilter_top_k', 'top-K configurado'], ['prefilter_in', 'Candidatos na entrada'],
    ['prefilter_sent', 'Enviados ao juiz'], ['prefilter_withheld', 'Retidos (não julgados)'],
    ['prefilter_tokens_saved_estimate', 'Tokens economizados (estimativa)'],
  ];
  const rows = keys.map(([k, label]) => `<tr>
    <th class="rowhead">${esc(label)}${help('prefilter')}</th>
    ${withData.map((p) => `<td class="num">${fmtCompact(agg[p][k])}</td>`).join('')}
  </tr>`);
  return table([{ label: 'Métrica' }, ...withData.map((p) => ({ label: PIPELINE_LABEL[p], num: true }))], rows);
}

function totalTokenColor(v, ref) {
  if (v === null || !ref) return 'var(--text-0)';
  if (v > ref * 1.15) return 'var(--error)';
  if (v < ref * 0.85) return 'var(--success)';
  return 'var(--text-0)';
}

function tokenTable(agg, active) {
  const keys = [
    ['candidate_tokens_before_filter', 'Recuperados'], ['survivor_tokens_snippets', 'Sobreviventes'],
    ['context_tokens', 'Contexto final'], ['jev_input_tokens', 'JEV input'], ['jev_output_tokens', 'JEV output'],
    ['model_input_tokens', 'Modelo input'], ['model_output_tokens', 'Modelo output'],
    ['judge_tokens', 'Tokens do juiz'], ['total_tokens', 'TOTAL gasto'],
  ];
  const rows = keys.map(([k, label]) => `<tr>
    <th class="rowhead">${esc(label)}${help(k)}</th>
    ${active.map((p) => `<td class="num">${fmtCompact(agg[p][k])}</td>`).join('')}
  </tr>`);
  rows.push(`<tr>
    <th class="rowhead">Amplificação${help('token_amplification')}</th>
    ${active.map((p) => `<td class="num" style="color:${ampColor(agg[p].token_amplification)}">${ampText(agg[p].token_amplification)}</td>`).join('')}
  </tr>`);
  return table([{ label: 'Métrica' }, ...active.map((p) => ({ label: PIPELINE_LABEL[p], num: true }))], rows);
}

export function mountTokens(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const view = TOKEN_VIEWS[ctx.state.tokenView] ? ctx.state.tokenView : 'total';
  const [, valFn] = TOKEN_VIEWS[view];
  const w = root.querySelector('[data-chart="tok-bars"]');
  if (!w) return;
  hBarChart(w, {
    rows: active.map((p) => ({
      label: PIPELINE_LABEL[p], value: num(valFn(agg[p])) || 0, color: PIPELINE_COLOR[p],
      tip: `total ${fmtCompact(agg[p].total_tokens)} · ctx ${fmtCompact(agg[p].context_tokens)}`,
    })),
    unit: 'tokens', fmt: fmtCompact, emptyMsg: `nenhuma run tem a métrica "${view}"`,
  });
}

/* ====================================================== LATENCY ========= */
export function renderLatency(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'Sem dados de latência.');
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const b = agg[BASE];
  const cards = active.map((p) => metricCard({
    title: PIPELINE_LABEL[p], tipKey: 'total_latency_ms', value: fmtMs(agg[p].total_latency_ms),
    unit: 'total / run', rawValue: agg[p].total_latency_ms, ref: b.total_latency_ms, lowerIsBetter: true,
    context: p === BASE ? 'referência (baseline)' : 'vs baseline',
  })).join('');

  const rows = LATENCY_STAGES.map(([k, label]) => `<tr>
    <th class="rowhead">${esc(label)}${help(k)}</th>
    ${active.map((p) => {
    const v = num(agg[p][k]);
    const applies = STAGE_APPLIES[p].has(label.toUpperCase().split(' ')[0]) || k === 'total_latency_ms';
    return `<td class="num ${v === null ? 'muted' : ''}">${v === null ? (applies ? '—' : 'n/a') : fmtMs(v)}</td>`;
  }).join('')}
  </tr>`);

  return `
    <div class="grid grid-kpi">${cards}</div>
    ${panel('Latência por estágio (agrupada por pipeline)',
    '<div class="chart-wrap" data-chart="lat-grouped"></div>',
    'retrieval · graphify · jev · full-note · context build · total')}
    ${panel('Tabela de estágios', table(
    [{ label: 'Estágio' }, ...active.map((p) => ({ label: PIPELINE_LABEL[p], num: true }))], rows),
  'média em ms; "n/a" = estágio não existe no pipeline')}
  `;
}
export function mountLatency(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const w = root.querySelector('[data-chart="lat-grouped"]');
  if (w) mountLatencyChart(w, agg, active);
}

/* ====================================================== COSTS =========== */
const COST_VIEWS = {
  total: ['Custo total', (a) => a.total_cost, fmtCost, 'USD'],
  agent: ['Custo do agente/modelo', (a) => a.model_cost, fmtCost, 'USD'],
  jev: ['Custo do JEV', (a) => a.jev_cost, fmtCost, 'USD'],
  per_query: ['Custo por query', (a) => a.total_cost, fmtCost, 'USD/query'],
  per_1k: ['Custo por 1K tokens', (a) => a.cost_per_1k, fmtCost, 'USD/1K tokens'],
};

export function renderCosts(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'Sem dados de custo.');
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const view = COST_VIEWS[ctx.state.costView] ? ctx.state.costView : 'total';
  const b = agg[BASE];
  const jv = agg.graphify_jev;
  const anyCost = active.some((p) => num(agg[p].total_cost) !== null || num(agg[p].jev_cost) !== null);

  const rows = active.map((p) => {
    const a = agg[p];
    return `<tr>
      <th class="rowhead">${esc(PIPELINE_LABEL[p])}</th>
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
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Custo total / run', tipKey: 'total_cost', value: fmtCost(jv.total_cost ?? b.total_cost),
    unit: 'USD', rawValue: jv.total_cost, ref: b.total_cost, lowerIsBetter: true, context: 'vs baseline',
  })}
      ${metricCard({
    title: 'Custo do JEV', tipKey: 'jev_cost', value: fmtCost(jv.jev_cost), unit: 'USD / run',
    rawValue: jv.jev_cost, ref: b.jev_cost, lowerIsBetter: true, context: 'só pipeline graphify_jev',
  })}
      ${metricCard({
    title: 'Custo por 1K tokens', tipKey: 'cost_per_1k', value: fmtCost(jv.cost_per_1k ?? b.cost_per_1k),
    unit: 'USD / 1K', rawValue: jv.cost_per_1k, ref: b.cost_per_1k, lowerIsBetter: true, context: 'vs baseline',
  })}
      ${metricCard({
    title: 'Custo por query', tipKey: 'cost_per_query', value: fmtCost(jv.total_cost ?? b.total_cost),
    unit: 'USD / query', rawValue: jv.total_cost, ref: b.total_cost, lowerIsBetter: true,
    context: 'média por run executada',
  })}
    </div>
    ${anyCost ? '' : `<div class="panel"><div class="panel-body">${emptyState('Custos zerados nas runs existentes',
    'As runs atuais são <code>mode=retrieval</code> sem geração paga, então <code>total_cost</code> e <code>jev_cost</code> são 0 ou nulos. Não há números inventados aqui.')}</div></div>`}
    ${panel(`Gráfico — ${COST_VIEWS[view][0]}`, '<div class="chart-wrap" data-chart="cost-bars"></div>', COST_VIEWS[view][3])}
    ${panel('Detalhe de custos', table([
    { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Agente/modelo', num: true, tip: 'metrics.model_cost' },
    { label: 'JEV', num: true, tipKey: 'jev_cost' },
    { label: 'Total', num: true, tipKey: 'total_cost' },
    { label: 'Por 1K tokens', num: true, tipKey: 'cost_per_1k' },
    { label: 'Tokens totais', num: true, tipKey: 'total_tokens' },
  ], rows), 'média por run')}
  `;
}
export function mountCosts(root, ctx) {
  const agg = aggregate(ctx.runs);
  const active = PIPELINES.filter((p) => agg[p].runs > 0);
  const view = COST_VIEWS[ctx.state.costView] ? ctx.state.costView : 'total';
  const [label, valFn, fmt, unit] = COST_VIEWS[view];
  const w = root.querySelector('[data-chart="cost-bars"]');
  if (!w) return;
  hBarChart(w, {
    rows: active.map((p) => ({ label: PIPELINE_LABEL[p], value: num(valFn(agg[p])) || 0, color: PIPELINE_COLOR[p] })),
    unit, fmt, emptyMsg: `nenhuma run registrou "${label}" (métrica ausente ou igual a zero)`,
  });
}
