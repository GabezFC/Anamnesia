// pages-data.js — History, Projects, Memory, Agents, Models.
// Strictly data-driven: entities derive from API payloads. No hardcoded project names, no fake numbers,
// and NEVER an absolute developer path (see safePath in format.js).
import { lineChart } from './charts.js';
import {
  PIPELINES, PIPELINE_LABEL, PIPELINE_SHORT, PIPELINE_COLOR, esc, fmtNum, fmtCompact, fmtMs, fmtCost,
  fmtPct, fmtAmp, fmtDate, get, num, realRuns, metricsOf, totalTokens, tokenAmplification,
  recallOf, precisionOf, costOf, mean, safePath, armOf, judgeTokens, savedTokens,
} from './format.js';
import {
  AGG_MODES, AGG_LABEL, AGG_HINT, serverPoints, timeAxis, zoomRange, periodRange, fmtFullDate, HIST_FORMAT,
} from './series.js';
import {
  metricCard, panel, emptyState, notWiredState, notMeasuredState, table, segmented, kvTable,
  callout, skeletonLines, skeletonTable,
} from './components.js';
import { consumerRows } from './store.js';

/* ====================================================== HISTORY ========= */
const HIST_SERIES = {
  tokens: ['Tokens totais gastos', (m) => totalTokens(m), fmtCompact, 'tokens', 'total_tokens'],
  judge: ['Tokens do juiz', (m) => judgeTokens(m), fmtCompact, 'tokens', 'judge_tokens'],
  context: ['Contexto entregue', (m) => num(get(m, 'context_tokens')), fmtCompact, 'tokens', 'context_tokens'],
  saved: ['Economia estimada', (m) => savedTokens(m), fmtCompact, 'tokens', 'saved_tokens'],
  amplification: ['Amplificação', (m) => tokenAmplification(m), fmtAmp, '×', 'token_amplification'],
  latency: ['Latência total', (m) => num(get(m, 'total_latency_ms')), fmtMs, 'ms', 'total_latency_ms'],
  cost: ['Custo', (m) => costOf(m), fmtCost, 'USD', 'total_cost'],
  documents: ['Documentos no contexto', (m) => num(get(m, 'documents_sent_to_model')), fmtNum, 'docs', 'documents_sent_to_model'],
  recall: ['Recall', (m) => recallOf(m), (v) => fmtPct(v, 0), 'fração', 'recall'],
  precision: ['Precisão do contexto', (m) => precisionOf(m), (v) => fmtPct(v, 0), 'fração', 'precision'],
};

export function renderHistory(ctx) {
  const key = HIST_SERIES[ctx.state.histSeries] ? ctx.state.histSeries : 'tokens';
  const [label, , , unit] = HIST_SERIES[key];
  const agg = AGG_MODES.includes(ctx.state.histAgg) ? ctx.state.histAgg : 'day';
  const scale = ctx.state.histScale === 'log' ? 'log' : 'linear';
  const period = PERIODS.some(([k]) => k === ctx.state.histPeriod) ? ctx.state.histPeriod : 'all';
  const custom = period === 'custom';

  return `
    <div class="page-toolbar">
      <span class="muted">Série temporal:</span>
      ${segmented('histSeries', Object.entries(HIST_SERIES).map(([k, v]) => [k, v[0]]), key)}
    </div>
    <div class="page-toolbar">
      <span class="muted">Agregação:</span>
      ${segmented('histAgg', AGG_MODES.map((m) => [m, AGG_LABEL[m]]), agg)}
      <span class="muted">Escala:</span>
      ${segmented('histScale', [['linear', 'Linear'], ['log', 'Log']], scale)}
      <span class="muted">Período:</span>
      ${segmented('histPeriod', PERIODS, period)}
    </div>
    ${panel(`${label} ao longo do tempo`, `
      <div class="hist-controls">
        ${custom ? `<label>de <input type="date" data-hist-since value="${esc(histView.since)}"></label>
        <label>até <input type="date" data-hist-until value="${esc(histView.until)}"></label>
        <button type="button" data-hist-apply>aplicar</button>` : ''}
        <button type="button" data-hist-zoom="0.5" title="aproximar">+</button>
        <button type="button" data-hist-zoom="2" title="afastar">−</button>
        <button type="button" data-hist-zoom-reset ${histView.zoom ? '' : 'disabled'}>resetar zoom</button>
        <label><input type="checkbox" data-hist-band ${histView.band ? 'checked' : ''}> faixa p25–p75</label>
        <span class="muted">arraste sobre o gráfico para dar zoom no período</span>
      </div>
      <p class="hist-summary" id="hist-summary" aria-live="polite">carregando o histórico completo…</p>
      <div class="chart-wrap" data-chart="hist-line"></div>`,
    { sub: `calculado no servidor sobre todas as runs do período · ${AGG_HINT[agg]} · unidade: ${unit}`, prov: 'experimental' })}
    ${panel('Sessões', `<div id="sessions-slot">${skeletonTable(6)}</div>`,
    { sub: 'GET /benchmark/sessions — ordenadas por última atividade · clique para detalhar', prov: 'experimental' })}
    <div id="session-detail"></div>
    ${panel('Runs recentes', `
      <div class="page-toolbar runs-toolbar">
        <div class="seg" role="tablist" data-hist-tab>
          <button type="button" data-val="all" role="tab"
            class="${histRunsState.tab === 'all' ? 'active' : ''}"
            aria-selected="${histRunsState.tab === 'all'}">Todas</button>
          <button type="button" data-val="adhoc" role="tab"
            class="${histRunsState.tab === 'adhoc' ? 'active' : ''}"
            aria-selected="${histRunsState.tab === 'adhoc'}">Chamadas reais (adhoc)</button>
        </div>
        <input type="search" data-hist-filter="agent" placeholder="agente (mcp/rest/cli)"
          value="${esc(histRunsState.agent)}">
        <input type="search" data-hist-filter="session" placeholder="session_id"
          value="${esc(histRunsState.session)}">
        <input type="search" data-hist-filter="q" placeholder="buscar na pergunta…"
          value="${esc(histRunsState.q)}">
        <span class="runs-filter-dates">de <input type="date" data-hist-filter="since" aria-label="runs desde"
          value="${esc(histRunsState.since)}"> até <input type="date" data-hist-filter="until" aria-label="runs até"
          value="${esc(histRunsState.until)}"></span>
        <button type="button" data-hist-refresh>Atualizar</button>
        <label class="muted"><input type="checkbox" data-hist-autorefresh
          ${histRunsState.autoRefresh ? 'checked' : ''}> auto-atualizar (10s)</label>
      </div>
      <div id="runs-recent-slot">${skeletonTable(8)}</div>
    `, { sub: 'GET /benchmark/runs — paginado no servidor', prov: 'experimental' })}
    <div id="run-detail"></div>
  `;
}

const PERIODS = [['7d', '7 dias'], ['30d', '30 dias'], ['all', 'Tudo'], ['custom', 'Personalizado']];
/** Chart-only UI state (not in ctx.state: zoom/dates are not toggles that re-render the whole page). */
const histView = { since: '', until: '', zoom: null, band: false, sessOffset: 0, sessLimit: 25, last: null };
let histSeq = 0;
let histSessSeq = 0;

/** Local calendar date (YYYY-MM-DD from <input type=date>) → epoch seconds; `end` = end of that day. */
const dateToEpoch = (s, end = false) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ''));
  if (!m) return null;
  const d = end ? new Date(+m[1], +m[2] - 1, +m[3], 23, 59, 59) : new Date(+m[1], +m[2] - 1, +m[3]);
  return d.getTime() / 1000;
};

/** since/until currently requested: the zoom wins over the period buttons. */
function currentRange(ctx) {
  if (histView.zoom) return { since: histView.zoom[0], until: histView.zoom[1] };
  const period = ctx.state.histPeriod;
  const custom = { since: dateToEpoch(histView.since), until: dateToEpoch(histView.until, true) };
  return periodRange(period, Date.now() / 1000, custom);
}

/** Table-only UI state for the "Runs recentes" widget. Not part of ctx.state: it drives its own
 * server fetch (getRunsPage), independent of the RUN_LIMIT=5000 preload used by every other page. */
const histRunsState = {
  tab: 'all', agent: '', session: '', q: '', since: '', until: '', offset: 0, limit: 50, autoRefresh: false,
};
let histRunsSeq = 0;
let histRunsTimer = null;

function runRowHtml(r) {
  const m = metricsOf(r);
  const rec = recallOf(m);
  const client = get(m, 'client') || r.agent || '—';
  return `<tr>
      <td><button type="button" class="linkish mono" data-run="${esc(r.run_id)}">${esc(String(r.run_id).slice(0, 10))}</button></td>
      <td class="muted">${fmtDate(r.created_at)}</td>
      <td>${esc(PIPELINE_SHORT[r.pipeline] || r.pipeline || '—')}</td>
      <td class="mono muted">${esc(armOf(r))}</td>
      <td class="mono muted">${esc(client)}</td>
      <td style="white-space:pre-wrap;word-break:break-word;max-width:360px">${esc(r.query || '—')}</td>
      <td class="num">${fmtCompact(totalTokens(m))}</td>
      <td class="num">${fmtCompact(num(get(m, 'context_tokens')))}</td>
      <td class="num">${fmtMs(num(get(m, 'total_latency_ms')))}</td>
      <td class="num">${rec === null ? '<span class="muted">n/m</span>' : fmtPct(rec, 0)}</td>
      <td>${r.error
    ? '<span class="pill err"><span class="dot"></span>erro</span>'
    : '<span class="pill ok"><span class="dot"></span>ok</span>'}</td>
    </tr>`;
}

function runsTableHtml(rows, total) {
  const body = table([
    { label: 'Run' }, { label: 'Data' }, { label: 'Pipeline' }, { label: 'Braço' }, { label: 'Cliente' },
    { label: 'Pergunta completa' },
    { label: 'Tokens gastos', num: true, tipKey: 'total_tokens' },
    { label: 'Contexto', num: true, tipKey: 'context_tokens' },
    { label: 'Latência', num: true, tipKey: 'total_latency_ms' },
    { label: 'Recall', num: true, tipKey: 'recall' }, { label: 'Status' },
  ], rows.map(runRowHtml), { emptyDetail: 'nenhuma run corresponde ao filtro atual' });
  const { offset, limit } = histRunsState;
  const from = total ? offset + 1 : 0;
  const to = offset + rows.length;
  return `${body}
    <div class="runs-pager">
      <span class="muted">mostrando ${from}–${to} de ${total}</span>
      <button type="button" data-hist-page="-1" ${offset <= 0 ? 'disabled' : ''}>◀ anterior</button>
      <button type="button" data-hist-page="1" ${to >= total ? 'disabled' : ''}>próxima ▶</button>
    </div>`;
}

/** Fetches the current filter/tab/offset from the server and repaints only #runs-recent-slot
 * (chart and sessions panel are untouched). Stale responses (an older request resolving after a
 * newer one) are dropped via a monotonically increasing sequence number. */
async function refreshRunsTable(root, ctx) {
  const slot = root.querySelector('#runs-recent-slot');
  if (!slot) return;
  const seq = ++histRunsSeq;
  try {
    const { runs, total } = await ctx.api.getRunsPage({
      limit: histRunsState.limit, offset: histRunsState.offset,
      sessionId: histRunsState.session || undefined,
      agent: histRunsState.agent || undefined,
      q: histRunsState.q || undefined,
      since: dateToEpoch(histRunsState.since) || undefined,
      until: dateToEpoch(histRunsState.until, true) || undefined,
      adhocOnly: histRunsState.tab === 'adhoc',
    });
    if (seq !== histRunsSeq) return;
    slot.innerHTML = runsTableHtml(realRuns(runs), total);
    bindRunsTableRowClicks(slot, root, ctx);
    slot.querySelectorAll('[data-hist-page]').forEach((b) => {
      b.addEventListener('click', () => {
        histRunsState.offset = Math.max(0, histRunsState.offset + Number(b.dataset.histPage) * histRunsState.limit);
        refreshRunsTable(root, ctx);
      });
    });
  } catch (e) {
    if (seq !== histRunsSeq) return;
    slot.innerHTML = `<div class="state error"><div class="state-title">Não foi possível carregar as runs</div>
      <code>${esc(e && e.message ? e.message : String(e))}</code></div>`;
  }
}

function bindRunsTableRowClicks(slot, root, ctx) {
  slot.querySelectorAll('[data-run]').forEach((a) => {
    a.addEventListener('click', async () => {
      const box = root.querySelector('#run-detail');
      if (!box) return;
      box.innerHTML = panel('Detalhe da run', skeletonLines(5));
      try {
        const d = await ctx.api.getRunDetail(a.dataset.run);
        box.innerHTML = renderRunDetail(d);
      } catch (e) {
        box.innerHTML = panel('Detalhe da run',
          `<div class="state error"><div class="state-title">Não foi possível carregar a run</div>
            <code>${esc(e.message)}</code></div>`);
      }
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function bindRunsToolbar(root, ctx) {
  root.querySelectorAll('[data-hist-tab] [data-val]').forEach((b) => {
    b.addEventListener('click', () => {
      if (histRunsState.tab === b.dataset.val) return;
      histRunsState.tab = b.dataset.val;
      histRunsState.offset = 0;
      root.querySelectorAll('[data-hist-tab] [data-val]').forEach((x) => {
        x.classList.toggle('active', x === b);
        x.setAttribute('aria-selected', String(x === b));
      });
      refreshRunsTable(root, ctx);
    });
  });
  let debounceTimer = null;
  root.querySelectorAll('[data-hist-filter]').forEach((input) => {
    input.addEventListener('input', () => {
      histRunsState[input.dataset.histFilter] = input.value.trim();
      histRunsState.offset = 0;
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => refreshRunsTable(root, ctx), 300);
    });
  });
  root.querySelector('[data-hist-refresh]')?.addEventListener('click', () => refreshHistory(root, ctx, { core: true }));
  const auto = root.querySelector('[data-hist-autorefresh]');
  auto?.addEventListener('change', () => {
    histRunsState.autoRefresh = auto.checked;
    setupAutoRefresh(root, ctx);
  });
}

function setupAutoRefresh(root, ctx) {
  clearInterval(histRunsTimer);
  histRunsTimer = histRunsState.autoRefresh ? setInterval(() => refreshHistory(root, ctx), 10000) : null;
}

/** Called by the router before leaving the History page, so the auto-refresh timer never keeps
 * firing against a detached DOM node (see app.js navigate()). */
export function unmountHistory() {
  clearInterval(histRunsTimer);
  histRunsTimer = null;
}

/** Chart: GET /benchmark/timeseries over every run in the range. The server sorts, dedups, aggregates
 * and downsamples (only after sorting); the browser only cuts the line at gaps and formats. */
async function loadHistChart(root, ctx) {
  const w = root.querySelector('[data-chart="hist-line"]');
  const sum = root.querySelector('#hist-summary');
  if (!w) return;
  const key = HIST_SERIES[ctx.state.histSeries] ? ctx.state.histSeries : 'tokens';
  const [label, , , unit] = HIST_SERIES[key];
  const agg = AGG_MODES.includes(ctx.state.histAgg) ? ctx.state.histAgg : 'day';
  const { since, until } = currentRange(ctx);
  const seq = ++histSeq;
  let res;
  try {
    res = await ctx.api.getTimeseries({ metric: key, agg, since, until });
  } catch (e) {
    if (seq !== histSeq) return;
    if (sum) sum.textContent = '';
    w.innerHTML = `<div class="state error"><div class="state-title">Não foi possível carregar a série</div>
      <code>${esc(e && e.message ? e.message : String(e))}</code></div>`;
    return;
  }
  if (seq !== histSeq) return;
  histView.last = res;
  const fmt = HIST_FORMAT[key] || String;
  const series = PIPELINES.map((p) => {
    const sr = res.series && res.series[p];
    const pts = sr ? serverPoints(sr.points, agg) : [];
    return pts.length ? { label: PIPELINE_SHORT[p] || p, color: PIPELINE_COLOR[p], points: pts } : null;
  }).filter(Boolean);
  const first = res.range && res.range.first;
  const last = res.range && res.range.last;
  const x0 = since ?? first;
  const x1 = until ?? last;
  const dom = x0 !== null && x0 !== undefined && x1 !== null && x1 !== undefined && x1 > x0 ? [x0, x1] : null;
  const axis = dom ? timeAxis(dom[0], dom[1]) : null;
  if (sum) {
    const span = first !== null && first !== undefined
      ? ` · de ${fmtFullDate(first)} a ${fmtFullDate(last)}` : '';
    sum.innerHTML = `histórico completo: <b>${fmtNum(res.total_runs_in_range)}</b> runs · `
      + `pontos desenhados: <b>${fmtNum(res.points_returned)}</b> · `
      + `amostrado: <b>${res.sampled ? 'sim' : 'não'}</b>${res.sampled ? ' (só a visualização; nenhum dado foi removido)' : ''}${span}`
      + (res.invalid_dropped ? ` · <span class="warn">${fmtNum(res.invalid_dropped)} runs com timestamp inválido descartadas</span>` : '');
  }
  const rzoom = root.querySelector('[data-hist-zoom-reset]');
  if (rzoom) rzoom.disabled = !histView.zoom;
  lineChart(w, {
    series, unit, fmt,
    xFmt: axis ? axis.fmt : fmtFullDate, tipXFmt: fmtFullDate,
    logScale: ctx.state.histScale === 'log',
    xTicks: axis ? axis.ticks : null, xDomain: dom, band: histView.band,
    onBrush: (a, b) => { histView.zoom = [a, b]; loadHistChart(root, ctx); },
    tableLabel: `${label} — ${AGG_HINT[agg]}`,
    ariaTitle: `${label} ao longo do tempo (${AGG_HINT[agg]})`,
    notes: res.sampled ? [`amostrado para ${res.max_points} pontos por pipeline (LTTB, depois de ordenar por tempo); o total de runs acima é o real`] : [],
    emptyMsg: `nenhuma run no período tem a métrica "${label}"`,
  });
}

/** Sessions by last activity, paginated on the server. */
async function loadSessions(root, ctx) {
  const slot = root.querySelector('#sessions-slot');
  if (!slot) return;
  const seq = ++histSessSeq;
  try {
    const { rows, total } = await ctx.api.getSessionsPage({ limit: histView.sessLimit, offset: histView.sessOffset });
    if (seq !== histSessSeq) return;
    const body = rows.map((s) => `<tr>
      <td><button type="button" class="linkish" data-session="${esc(s.session_id)}">${esc(String(s.session_id).slice(0, 22))}</button></td>
      <td>${esc(s.kind || '—')}</td>
      <td class="num">${fmtNum(s.runs)}</td>
      <td class="muted">${s.first_run_at ? fmtFullDate(s.first_run_at) : '—'}</td>
      <td class="muted">${s.last_run_at ? fmtFullDate(s.last_run_at) : '—'}</td>
      <td class="muted">${s.created_at ? fmtFullDate(s.created_at) : '—'}</td>
    </tr>`);
    const off = histView.sessOffset;
    slot.innerHTML = `${table([
      { label: 'Sessão' }, { label: 'Tipo' }, { label: 'Runs', num: true },
      { label: 'Primeira run' }, { label: 'Última run' }, { label: 'Registrada em' },
    ], body, { emptyDetail: 'GET /benchmark/sessions não retornou sessões' })}
      <div class="runs-pager">
        <span class="muted">${total ? off + 1 : 0}–${off + rows.length} de ${fmtNum(total)} sessões</span>
        <button type="button" data-sess-page="-1" ${off <= 0 ? 'disabled' : ''}>◀ anterior</button>
        <button type="button" data-sess-page="1" ${off + rows.length >= total ? 'disabled' : ''}>próxima ▶</button>
      </div>`;
    slot.querySelectorAll('[data-sess-page]').forEach((b) => b.addEventListener('click', () => {
      histView.sessOffset = Math.max(0, off + Number(b.dataset.sessPage) * histView.sessLimit);
      loadSessions(root, ctx);
    }));
  } catch (e) {
    if (seq !== histSessSeq) return;
    slot.innerHTML = `<div class="state error"><div class="state-title">Não foi possível carregar as sessões</div>
      <code>${esc(e && e.message ? e.message : String(e))}</code></div>`;
  }
}

/** Manual "Atualizar" and the auto-refresh timer: every history route is re-fetched (none of them
 * is memoised) and the memoised GETs are dropped. Only the manual button also reloads the 5000-run
 * preload used by the other pages. */
function refreshHistory(root, ctx, { core = false } = {}) {
  ctx.api.invalidate();
  if (core) ctx.refreshCore?.().catch(() => {});
  loadHistChart(root, ctx);
  loadSessions(root, ctx);
  refreshRunsTable(root, ctx);
}

export function mountHistory(root, ctx) {
  unmountHistory();
  const rerender = () => loadHistChart(root, ctx);
  root.querySelector('[data-hist-apply]')?.addEventListener('click', () => {
    histView.since = root.querySelector('[data-hist-since]')?.value || '';
    histView.until = root.querySelector('[data-hist-until]')?.value || '';
    histView.zoom = null;
    rerender();
  });
  root.querySelectorAll('[data-hist-zoom]').forEach((b) => b.addEventListener('click', () => {
    const r = histView.last && histView.last.range;
    const cur = histView.zoom || (r && r.first !== null && r.first !== undefined ? [r.first, r.last] : null);
    if (!cur || !(cur[1] > cur[0])) return;
    histView.zoom = zoomRange(cur, Number(b.dataset.histZoom));
    rerender();
  }));
  root.querySelector('[data-hist-zoom-reset]')?.addEventListener('click', () => { histView.zoom = null; rerender(); });
  root.querySelector('[data-hist-band]')?.addEventListener('change', (e) => { histView.band = e.target.checked; rerender(); });

  bindRunsToolbar(root, ctx);
  loadHistChart(root, ctx);
  loadSessions(root, ctx);
  refreshRunsTable(root, ctx);
  setupAutoRefresh(root, ctx);
}

function renderRunDetail(d) {
  const m = metricsOf(d);
  const srcRows = (d.sources || []).map((s) => `<tr>
    <td class="mono">${esc(s.file)}</td>
    <td>${esc(String(s.section || '').slice(0, 60))}</td>
    <td class="num">${fmtNum(s.score, 3)}</td>
    <td class="num">${num(s.relevance) === null ? '<span class="muted">—</span>' : fmtNum(s.relevance, 2)}</td>
    <td>${esc(s.decision || '—')}</td>
    <td class="num">${fmtNum(s.tokens)}</td>
  </tr>`);
  const flags = get(m, 'opt_flags');
  return panel(`Run ${esc(String(d.run_id).slice(0, 10))} — ${esc(PIPELINE_LABEL[d.pipeline] || d.pipeline)}`,
    `<p class="muted run-query">${esc(d.query || '')}</p>
     <div class="grid grid-kpi run-kpis">
       ${metricCard({ title: 'Tokens gastos', tipKey: 'total_tokens', value: totalTokens(m) === null ? undefined : fmtCompact(totalTokens(m)), unit: 'tokens', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Contexto entregue', tipKey: 'context_tokens', value: num(get(m, 'context_tokens')) === null ? undefined : fmtCompact(get(m, 'context_tokens')), unit: 'tokens', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Latência', tipKey: 'total_latency_ms', value: num(get(m, 'total_latency_ms')) === null ? undefined : fmtMs(get(m, 'total_latency_ms')), unit: 'total', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Amplificação', tipKey: 'token_amplification', value: tokenAmplification(m) === null ? undefined : fmtAmp(tokenAmplification(m)), unit: '× gasto/entregue', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
     </div>
     ${kvTable([
    ['Braço (mode)', `<span class="mono">${esc(armOf(d))}</span>`],
    ['Sessão', `<span class="mono">${esc(d.session_id || '—')}</span>`],
    ['Pipeline', esc(PIPELINE_LABEL[d.pipeline] || d.pipeline || '—')],
    ['opt_flags', Array.isArray(flags)
      ? (flags.length ? `<span class="mono">${esc(flags.join(', '))}</span>` : '<span class="muted">nenhum (referência)</span>')
      : '<span class="muted">não registrado</span>'],
    ['Erro', d.error ? `<span style="color:var(--error)">${esc(d.error)}</span>` : '<span class="muted">nenhum</span>'],
  ])}
     <h3 class="sub-head">Fontes entregues ao modelo</h3>
     ${table([{ label: 'Arquivo' }, { label: 'Seção' }, { label: 'Score', num: true },
    { label: 'Relevância', num: true }, { label: 'Decisão' }, { label: 'Tokens', num: true }], srcRows,
  { emptyTitle: 'Contexto vazio', emptyDetail: 'esta run não entregou nenhuma fonte' })}
     <details class="raw"><summary class="muted">metrics_json completo</summary>
       <pre class="block">${esc(JSON.stringify(m, null, 2))}</pre></details>`,
    { sub: fmtDate(d.created_at), prov: 'experimental' });
}

/* ====================================================== PROJECTS ======== */
/** Data source: GET /system/projects (vault-derived) joined with retrieval activity from run sources[]. */
export function renderProjects(ctx) {
  const reg = ctx.projects;
  const details = ctx.details || [];
  if (!reg || !Array.isArray(reg.projects)) {
    return notWiredState('GET /system/projects não retornou { total_notes, areas, projects[] }');
  }
  // Retrieval activity per project, keyed by the area/display_name prefix of source paths.
  const activity = new Map();
  for (const d of details) {
    for (const s of d?.sources || []) {
      const parts = String(s.file || '').split('/').filter(Boolean);
      if (parts.length < 2) continue;
      const key = `${parts[0]}/${parts[1]}`;
      const e = activity.get(key) || { hits: 0, tokens: 0, rel: [], runs: new Set() };
      e.hits += 1;
      e.tokens += num(s.tokens) || 0;
      if (num(s.relevance) !== null) e.rel.push(num(s.relevance));
      e.runs.add(d.run_id);
      activity.set(key, e);
    }
  }
  const totalNotes = num(reg.total_notes);
  const areas = reg.areas && typeof reg.areas === 'object' ? reg.areas : {};

  const rows = reg.projects.map((p) => {
    const act = activity.get(`${p.area}/${p.display_name}`);
    return `<tr>
      <th class="rowhead">${esc(p.display_name)}</th>
      <td class="mono muted">${esc(p.slug)}</td>
      <td class="mono muted">${esc(p.area)}</td>
      <td class="num">${fmtNum(p.note_count)}</td>
      <td class="num">${totalNotes ? fmtPct(num(p.note_count) / totalNotes, 1) : '—'}</td>
      <td class="num">${act ? fmtNum(act.hits) : '<span class="muted">0</span>'}</td>
      <td class="num">${act ? fmtCompact(act.tokens) : '<span class="muted">—</span>'}</td>
      <td class="num">${act && act.rel.length ? fmtNum(mean(act.rel), 2) : '<span class="muted">—</span>'}</td>
      <td class="num">${act ? fmtNum(act.runs.size) : '<span class="muted">—</span>'}</td>
    </tr>`;
  });

  const areaRows = Object.entries(areas)
    .sort((a, b) => b[1] - a[1])
    .map(([area, count]) => `<tr>
      <th class="rowhead mono">${esc(area)}</th>
      <td class="num">${fmtNum(count)}</td>
      <td class="num">${totalNotes ? fmtPct(num(count) / totalNotes, 1) : '—'}</td>
      <td class="num">${fmtNum(reg.projects.filter((p) => p.area === area).length)}</td>
    </tr>`);

  const touched = reg.projects.filter((p) => activity.has(`${p.area}/${p.display_name}`)).length;
  return `
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Projetos no vault', value: fmtNum(reg.projects.length), unit: 'projetos',
    deltaText: 'fonte: /system/projects', deltaCls: 'flat', context: 'descobertos dos caminhos do vault',
    tip: 'Entidades retornadas por GET /system/projects, derivadas da estrutura de pastas do vault. Nenhum nome está no código.',
  })}
      ${metricCard({
    title: 'Notas totais', value: totalNotes === null ? undefined : fmtNum(totalNotes), unit: 'notas .md',
    deltaText: 'fonte: /system/projects', deltaCls: 'flat', context: 'campo total_notes',
  })}
      ${metricCard({
    title: 'Áreas', value: fmtNum(Object.keys(areas).length), unit: 'áreas do vault',
    deltaText: 'fonte: /system/projects', deltaCls: 'flat', context: 'campo areas',
  })}
      ${metricCard({
    title: 'Projetos já recuperados', value: fmtNum(touched), unit: `de ${reg.projects.length}`,
    deltaText: touched ? 'derivado' : 'nenhum', deltaCls: touched ? 'good' : 'attn',
    context: `citados em ${details.length} runs detalhadas`,
    tip: 'Projetos que apareceram em sources[] das runs carregadas — cruzamento entre o registro do vault e a atividade real de retrieval.',
  })}
    </div>
    ${panel('Projetos', table([
    { label: 'Projeto' }, { label: 'Slug' }, { label: 'Área' },
    { label: 'Notas', num: true }, { label: 'Share do vault', num: true },
    { label: 'Citações', num: true, tip: 'Vezes que uma nota do projeto entrou em um contexto (sources[]).' },
    { label: 'Tokens citados', num: true }, { label: 'Relevância média', num: true },
    { label: 'Runs', num: true },
  ], rows, { emptyDetail: 'GET /system/projects devolveu projects[] vazio' }),
  { sub: `${reg.projects.length} projetos · GET /system/projects`, prov: 'verified', provNote: 'Contagens lidas do sistema de arquivos.' })}
    ${panel('Distribuição por área', table([
    { label: 'Área' }, { label: 'Notas', num: true }, { label: 'Share', num: true },
    { label: 'Projetos', num: true },
  ], areaRows, { emptyDetail: 'campo areas vazio' }), { sub: 'campo areas de GET /system/projects', prov: 'verified' })}
  `;
}

/* ====================================================== MEMORY ========== */
/** Area note distribution from GET /system/projects. Generic: iterates whatever areas the API returns. */
function areaBreakdown(reg) {
  const areas = get(reg, 'areas');
  if (!areas || typeof areas !== 'object' || !Object.keys(areas).length) {
    return notWiredState('GET /system/projects não retornou o campo areas');
  }
  const tot = num(get(reg, 'total_notes'));
  const rows = Object.entries(areas).sort((a, b) => b[1] - a[1]).map(([area, count]) => `<tr>
    <th class="rowhead mono">${esc(area)}</th>
    <td class="num">${fmtNum(count)}</td>
    <td class="num">${tot ? fmtPct(num(count) / tot, 1) : '—'}</td>
  </tr>`);
  return table([{ label: 'Área' }, { label: 'Notas', num: true }, { label: 'Share', num: true }], rows);
}

export function renderMemory(ctx) {
  const info = ctx.systemInfo;
  const reg = ctx.projects;
  const details = ctx.details || [];
  const files = new Map();
  for (const d of details) {
    for (const s of d?.sources || []) {
      if (!s.file) continue;
      const e = files.get(s.file) || { file: s.file, hits: 0, tokens: [], rel: [], sections: new Set() };
      e.hits += 1;
      if (num(s.tokens) !== null) e.tokens.push(num(s.tokens));
      if (num(s.relevance) !== null) e.rel.push(num(s.relevance));
      if (s.section) e.sections.add(s.section);
      files.set(s.file, e);
    }
  }
  const top = [...files.values()].sort((a, b) => b.hits - a.hits).slice(0, 40);
  const rows = top.map((f) => `<tr>
    <td class="mono">${esc(f.file)}</td>
    <td class="num">${fmtNum(f.hits)}</td>
    <td class="num">${fmtNum(f.sections.size)}</td>
    <td class="num">${fmtCompact(mean(f.tokens))}</td>
    <td class="num">${f.rel.length ? fmtNum(mean(f.rel), 2) : '<span class="muted">—</span>'}</td>
  </tr>`);
  const totalNotes = num(get(reg, 'total_notes')) ?? num(get(info, 'markdown_files'));
  const vaultOk = get(info, 'vault_exists');

  return `
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Notas no vault', value: totalNotes === null ? undefined : fmtNum(totalNotes),
    unit: 'notas .md', deltaText: 'fonte: /system/projects', deltaCls: 'flat', context: 'vault somente leitura',
    tip: 'Campo total_notes de GET /system/projects (fallback: markdown_files de GET /system/info).',
  })}
      ${metricCard({
    title: 'Arquivos já recuperados', value: fmtNum(files.size), unit: 'arquivos distintos',
    deltaText: 'derivado', deltaCls: 'flat', context: `em ${details.length} runs detalhadas`,
  })}
      ${metricCard({
    title: 'Cobertura do vault',
    value: totalNotes ? fmtPct(files.size / totalNotes, 1) : undefined,
    unit: 'do vault citado', deltaText: 'derivado', deltaCls: 'flat', context: 'arquivos citados ÷ total de notas',
    tip: 'Fração das notas do vault que já apareceu em algum contexto nas runs carregadas.',
    missingHint: 'total de notas desconhecido',
  })}
      ${metricCard({
    title: 'Vault acessível', value: vaultOk === null ? undefined : (vaultOk ? 'sim' : 'não'), unit: '',
    deltaText: vaultOk ? 'ok' : 'falha', deltaCls: vaultOk ? 'good' : 'bad',
    context: 'campo vault_exists',
  })}
    </div>
    ${panel('Localização do vault e do grafo', kvTable([
    // safePath: the dashboard never prints an absolute developer path.
    ['Vault', `<span class="mono">${esc(safePath(get(info, 'vault')))}</span>`],
    ['Grafo (graphify)', `<span class="mono">${esc(safePath(get(info, 'graph_path')))}</span>`],
    ['Versão graphify', `<span class="mono">${esc(get(info, 'graphify') || '—')}</span>`],
    ['Banco de benchmark', `<span class="mono">${esc(safePath(get(info, 'db')))}</span>`],
  ]) + callout('info', 'Caminhos abreviados de propósito',
    'A UI exibe apenas os últimos segmentos de qualquer caminho absoluto devolvido pela API, '
    + 'para nunca revelar o diretório pessoal de quem roda o servidor.'),
  { sub: 'GET /system/info', prov: 'verified' })}
    ${panel('Distribuição de notas por área', areaBreakdown(reg),
    { sub: 'GET /system/projects → areas', prov: 'verified' })}
    ${panel('Notas mais recuperadas', rows.length ? table([
    { label: 'Arquivo' }, { label: 'Citações', num: true }, { label: 'Seções distintas', num: true },
    { label: 'Tokens médios', num: true }, { label: 'Relevância média', num: true },
  ], rows) : notMeasuredState('sources[]', 'As runs carregadas não têm fontes registradas.'),
  { sub: `top ${top.length} de ${files.size} arquivos`, prov: 'experimental' })}
  `;
}

/* ====================================================== AGENTS ========== */
export function renderAgents(ctx) {
  const info = ctx.systemInfo;
  const agents = get(info, 'integrations.agents') || [];
  const rows = agents.map((a) => `<tr>
    <th class="rowhead">${esc(a.agent)}</th>
    <td>${a.available
    ? '<span class="pill ok"><span class="dot"></span>disponível</span>'
    : '<span class="pill err"><span class="dot"></span>indisponível</span>'}</td>
    <td class="mono">${esc(a.version || '—')}</td>
    <td>${a.mcp ? 'sim' : 'não'}</td>
    <td>${a.cli ? 'sim' : 'não'}</td>
    <td class="mono">${esc(a.metrics || '—')}</td>
    <td class="muted">${esc(a.reason || '')}</td>
  </tr>`);

  const consumers = consumerRows(ctx.stats).filter((c) => c.agent && c.agent !== '-');
  const cRows = consumers.map((c) => `<tr>
    <th class="rowhead">${esc(c.agent)}</th>
    <td class="mono">${esc(c.model || '—')}</td>
    <td>${esc(PIPELINE_SHORT[c.pipeline] || c.pipeline)}</td>
    <td class="num">${fmtNum(c.runs)}</td>
    <td class="num">${fmtMs(c.latency)}</td>
    <td class="num">${fmtMs(c.latencyP95)}</td>
    <td class="num">${fmtCompact(c.context)}</td>
    <td class="num">${fmtCompact(c.agentTokens)}</td>
    <td class="num">${fmtCost(c.cost)}</td>
  </tr>`);

  const avail = agents.filter((a) => a.available).length;
  return `
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Agentes detectados', value: fmtNum(agents.length), unit: 'adapters',
    deltaText: 'fonte: /system/info', deltaCls: 'flat', context: 'integrations.agents',
  })}
      ${metricCard({
    title: 'Agentes disponíveis', value: fmtNum(avail), unit: `de ${agents.length}`,
    deltaText: avail ? 'ok' : 'nenhum', deltaCls: avail ? 'good' : 'attn', context: 'campo available',
  })}
      ${metricCard({
    title: 'Consumidores com runs', value: fmtNum(consumers.length), unit: 'grupos agente×modelo×pipeline',
    deltaText: 'fonte: /benchmark/stats', deltaCls: 'flat', context: 'stats.groups',
  })}
      ${metricCard({
    title: 'Runs end-to-end', value: fmtNum(realRuns(ctx.runs).filter((r) => r.mode === 'end_to_end').length),
    unit: 'runs com geração', deltaText: 'derivado', deltaCls: 'flat', context: 'mode = end_to_end',
  })}
    </div>
    ${panel('Adapters de agente', rows.length ? table([
    { label: 'Agente' }, { label: 'Status' }, { label: 'Versão' }, { label: 'MCP' },
    { label: 'CLI' }, { label: 'Métricas' }, { label: 'Motivo' },
  ], rows) : notWiredState('/system/info não retornou integrations.agents[]'),
  { sub: 'GET /system/info → integrations', prov: 'verified' })}
    ${panel('Desempenho por consumidor', cRows.length ? table([
    { label: 'Agente' }, { label: 'Modelo' }, { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Latência mediana', num: true, tipKey: 'total_latency_ms' }, { label: 'p95', num: true },
    { label: 'Contexto', num: true, tipKey: 'context_tokens' },
    { label: 'Tokens do agente', num: true }, { label: 'Custo médio', num: true, tipKey: 'total_cost' },
  ], cRows) : emptyState('Nenhuma run com agente',
    '<p class="state-body">Todas as runs gravadas são <code>retrieval-only</code> (sem consumidor). '
    + 'Rode um benchmark com <code>consumers</code> para popular esta tabela.</p>'),
  { sub: 'GET /benchmark/stats → groups', prov: 'experimental' })}
  `;
}

/* ====================================================== MODELS ========== */
export function renderModels(ctx) {
  const info = ctx.systemInfo;
  const models = get(info, 'integrations.models') || {};
  const provRows = Object.entries(models).map(([prov, v]) => `<tr>
    <th class="rowhead">${esc(prov)}</th>
    <td>${v.available
    ? '<span class="pill ok"><span class="dot"></span>disponível</span>'
    : '<span class="pill warn"><span class="dot"></span>indisponível</span>'}</td>
    <td class="num">${fmtNum((v.models || []).length)}</td>
    <td class="mono">${esc((v.models || []).slice(0, 4).join(', ') || '—')}</td>
    <td class="muted">${esc(v.reason || v.base_url || '')}</td>
  </tr>`);

  const consumers = consumerRows(ctx.stats).filter((c) => c.model && c.model !== '-');
  const mRows = consumers.map((c) => `<tr>
    <th class="rowhead mono">${esc(c.model)}</th>
    <td>${esc(c.agent)}</td>
    <td>${esc(PIPELINE_SHORT[c.pipeline] || c.pipeline)}</td>
    <td class="num">${fmtNum(c.runs)}</td>
    <td class="num">${fmtCompact(c.inTokens)}</td>
    <td class="num">${fmtCompact(c.outTokens)}</td>
    <td class="num">${fmtCost(c.cost)}</td>
  </tr>`);

  const availProv = Object.values(models).filter((v) => v.available).length;
  return `
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Provedores', value: fmtNum(Object.keys(models).length), unit: 'configurados',
    deltaText: 'fonte: /system/info', deltaCls: 'flat', context: 'integrations.models',
  })}
      ${metricCard({
    title: 'Provedores disponíveis', value: fmtNum(availProv), unit: `de ${Object.keys(models).length}`,
    deltaText: availProv ? 'ok' : 'nenhum', deltaCls: availProv ? 'good' : 'attn', context: 'campo available',
  })}
      ${metricCard({
    title: 'Modelo do juiz (JEV)', value: get(info, 'jev_model') || undefined, unit: '',
    deltaText: `SDK ${get(info, 'jev_sdk') || '?'}`, deltaCls: 'flat', context: `modo ${get(info, 'jev_mode') || '—'}`,
    tip: 'Modelo do juiz usado para avaliar relevância nos pipelines com JEV.',
  })}
      ${metricCard({
    title: 'Modelos com runs', value: fmtNum(new Set(consumers.map((c) => c.model)).size), unit: 'modelos medidos',
    deltaText: 'fonte: /benchmark/stats', deltaCls: 'flat', context: 'stats.groups',
  })}
    </div>
    ${panel('Provedores e modelos', provRows.length ? table([
    { label: 'Provedor' }, { label: 'Status' }, { label: 'Modelos', num: true },
    { label: 'Exemplos' }, { label: 'Observação' },
  ], provRows) : notWiredState('/system/info não retornou integrations.models'),
  { sub: 'GET /system/info', prov: 'verified' })}
    ${panel('Modelos medidos em runs', mRows.length ? table([
    { label: 'Modelo' }, { label: 'Agente' }, { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Input tokens', num: true }, { label: 'Output tokens', num: true },
    { label: 'Custo médio', num: true, tipKey: 'total_cost' },
  ], mRows) : emptyState('Nenhum modelo medido',
    '<p class="state-body">As runs gravadas não têm <code>model</code> definido (retrieval-only). '
    + 'Nenhum número é inventado aqui.</p>'),
  { sub: 'GET /benchmark/stats → groups', prov: 'experimental' })}
  `;
}
