// pages-data.js — History, Projects, Memory, Agents, Models, Settings.
// Strictly data-driven: entities derive from API payloads. No hardcoded project names, no fake numbers.
import { lineChart } from './charts.js';
import {
  PIPELINES, PIPELINE_LABEL, PIPELINE_COLOR, esc, fmtNum, fmtCompact, fmtMs, fmtCost, fmtPct,
  fmtDate, fmtDateShort, get, num, realRuns, metricsOf, totalTokens, tokenAmplification, recallOf, costOf, mean,
} from './format.js';
import {
  metricCard, panel, emptyState, notWiredState, table, segmented, help,
} from './components.js';
import { consumerRows } from './store.js';

/* ====================================================== HISTORY ========= */
const HIST_SERIES = {
  tokens: ['Tokens totais gastos', (m) => totalTokens(m), fmtCompact, 'tokens', 'total_tokens'],
  amplification: ['Amplificação', (m) => tokenAmplification(m), (v) => `${num(v)?.toFixed(1) ?? '—'}×`, '×', 'token_amplification'],
  latency: ['Latência total', (m) => num(get(m, 'total_latency_ms')), fmtMs, 'ms', 'total_latency_ms'],
  cost: ['Custo', (m) => costOf(m), fmtCost, 'USD', 'total_cost'],
  documents: ['Documentos no contexto', (m) => num(get(m, 'documents_sent_to_model')), fmtNum, 'docs', 'documents_sent_to_model'],
  recall: ['Recall', (m) => recallOf(m), (v) => fmtPct(v, 0), 'fração', 'recall'],
  efficiency: ['Eficiência', (m) => {
    const d = num(get(m, 'documents_sent_to_model')); const t = totalTokens(m);
    return d !== null && t ? (d / t) * 1000 : null;
  }, (v) => fmtNum(v, 2), 'docs/1K tokens', 'efficiency'],
};

export function renderHistory(ctx) {
  const rs = realRuns(ctx.runs);
  if (!rs.length) return emptyState('Nenhuma run registrada', 'O histórico aparece após o primeiro benchmark.');
  const key = HIST_SERIES[ctx.state.histSeries] ? ctx.state.histSeries : 'tokens';
  const [label, , , unit, tipKey] = HIST_SERIES[key];
  const sessions = ctx.sessions || [];

  const sessionRows = sessions.map((s) => {
    const sr = rs.filter((r) => r.session_id === s.session_id);
    const tt = mean(sr.map((r) => totalTokens(metricsOf(r))));
    return `<tr>
      <td class="mono clickable" data-session="${esc(s.session_id)}">${esc(String(s.session_id).slice(0, 12))}</td>
      <td>${esc(s.kind || '—')}</td>
      <td class="num">${fmtNum(s.runs)}</td>
      <td class="num">${fmtCompact(tt)}</td>
      <td class="num">${fmtMs(mean(sr.map((r) => num(get(metricsOf(r), 'total_latency_ms')))))}</td>
      <td class="num">${fmtCost(mean(sr.map((r) => costOf(metricsOf(r)))))}</td>
      <td class="muted">${fmtDate(s.created_at)}</td>
    </tr>`;
  });

  const runRows = rs.slice(0, 60).map((r) => {
    const m = metricsOf(r);
    return `<tr>
      <td class="mono clickable" data-run="${esc(r.run_id)}">${esc(String(r.run_id).slice(0, 10))}</td>
      <td class="muted">${fmtDate(r.created_at)}</td>
      <td>${esc(PIPELINE_LABEL[r.pipeline] || r.pipeline)}</td>
      <td>${esc(r.question_id || String(r.query || '').slice(0, 40))}</td>
      <td class="num">${fmtCompact(totalTokens(m))}</td>
      <td class="num">${fmtCompact(num(get(m, 'context_tokens')))}</td>
      <td class="num">${fmtMs(num(get(m, 'total_latency_ms')))}</td>
      <td class="num">${recallOf(m) === null ? '—' : fmtPct(recallOf(m), 0)}</td>
      <td>${r.error ? `<span class="pill err"><span class="dot"></span>erro</span>` : `<span class="pill ok"><span class="dot"></span>ok</span>`}</td>
    </tr>`;
  });

  return `
    <div class="page-toolbar">
      <span class="muted">Série temporal:</span>
      ${segmented('histSeries', Object.entries(HIST_SERIES).map(([k, v]) => [k, v[0]]), key)}
    </div>
    ${panel(`${label} ao longo do tempo`, '<div class="chart-wrap" data-chart="hist-line"></div>',
    `${rs.length} runs ordenadas por created_at · unidade: ${unit}`)}
    ${panel('Sessões', table([
    { label: 'Sessão' }, { label: 'Tipo' }, { label: 'Runs', num: true },
    { label: 'Tokens gastos', num: true, tipKey: 'total_tokens' },
    { label: 'Latência', num: true, tipKey: 'total_latency_ms' },
    { label: 'Custo', num: true, tipKey: 'total_cost' }, { label: 'Criada em' },
  ], sessionRows), `${sessions.length} sessões`)}
    ${panel('Runs recentes', table([
    { label: 'Run' }, { label: 'Data' }, { label: 'Pipeline' }, { label: 'Pergunta' },
    { label: 'Tokens gastos', num: true, tipKey: 'total_tokens' },
    { label: 'Contexto', num: true, tipKey: 'context_tokens' },
    { label: 'Latência', num: true, tipKey: 'total_latency_ms' },
    { label: 'Recall', num: true, tipKey: 'recall' }, { label: 'Status' },
  ], runRows), `mostrando ${Math.min(60, rs.length)} de ${rs.length}`)}
    <div id="run-detail"></div>
  `;
}

export function mountHistory(root, ctx) {
  const rs = realRuns(ctx.runs);
  const key = HIST_SERIES[ctx.state.histSeries] ? ctx.state.histSeries : 'tokens';
  const [label, valFn, fmt, unit] = HIST_SERIES[key];
  const w = root.querySelector('[data-chart="hist-line"]');
  if (w) {
    lineChart(w, {
      series: PIPELINES.map((p) => ({
        label: PIPELINE_LABEL[p], color: PIPELINE_COLOR[p],
        points: rs.filter((r) => r.pipeline === p)
          .map((r) => ({ x: num(r.created_at), y: num(valFn(metricsOf(r))) }))
          .filter((q) => q.x !== null && q.y !== null),
      })).filter((s) => s.points.length),
      unit, fmt, xFmt: fmtDateShort,
      emptyMsg: `nenhuma run tem a métrica "${label}"`,
    });
  }
  // run drill-down
  root.querySelectorAll('[data-run]').forEach((a) => {
    a.addEventListener('click', async () => {
      const box = root.querySelector('#run-detail');
      box.innerHTML = panel('Detalhe da run', '<div class="skel skel-line"></div>'.repeat(4));
      try {
        const d = await ctx.api.getRunDetail(a.dataset.run);
        box.innerHTML = renderRunDetail(d);
      } catch (e) {
        box.innerHTML = panel('Detalhe da run', `<div class="state error">${esc(e.message)}</div>`);
      }
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function renderRunDetail(d) {
  const m = metricsOf(d);
  const srcRows = (d.sources || []).map((s) => `<tr>
    <td class="mono">${esc(s.file)}</td>
    <td>${esc(String(s.section || '').slice(0, 60))}</td>
    <td class="num">${fmtNum(s.score)}</td>
    <td class="num">${s.relevance === null || s.relevance === undefined ? '—' : fmtNum(s.relevance)}</td>
    <td>${esc(s.decision || '—')}</td>
    <td class="num">${fmtNum(s.tokens)}</td>
  </tr>`);
  return panel(`Run ${esc(String(d.run_id).slice(0, 10))} — ${esc(PIPELINE_LABEL[d.pipeline] || d.pipeline)}`,
    `<p class="muted" style="margin:0 0 12px">${esc(d.query || '')}</p>
     <div class="grid grid-kpi" style="margin-bottom:16px">
       ${metricCard({ title: 'Tokens gastos', tipKey: 'total_tokens', value: fmtCompact(totalTokens(m)), unit: 'tokens', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Contexto final', tipKey: 'context_tokens', value: fmtCompact(num(get(m, 'context_tokens'))), unit: 'tokens', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Latência', tipKey: 'total_latency_ms', value: fmtMs(num(get(m, 'total_latency_ms'))), unit: 'total', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
       ${metricCard({ title: 'Amplificação', tipKey: 'token_amplification', value: `${num(tokenAmplification(m))?.toFixed(2) ?? '—'}×`, unit: '× gasto/entregue', deltaText: 'run única', deltaCls: 'flat', context: 'sem comparação' })}
     </div>
     ${table([{ label: 'Arquivo' }, { label: 'Seção' }, { label: 'Score', num: true },
    { label: 'Relevância', num: true }, { label: 'Decisão' }, { label: 'Tokens', num: true }], srcRows)}
     <details style="margin-top:12px"><summary class="muted">metrics_json completo</summary>
       <pre class="block">${esc(JSON.stringify(m, null, 2))}</pre></details>`,
    fmtDate(d.created_at));
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
      <td class="num">${act ? fmtCompact(act.tokens) : '—'}</td>
      <td class="num">${act && act.rel.length ? fmtNum(mean(act.rel), 2) : '—'}</td>
      <td class="num">${act ? fmtNum(act.runs.size) : '—'}</td>
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
    title: 'Notas totais', value: fmtNum(totalNotes), unit: 'notas .md',
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
  ], rows), `${reg.projects.length} projetos · GET /system/projects`)}
    ${panel('Distribuição por área', table([
    { label: 'Área' }, { label: 'Notas', num: true }, { label: 'Share', num: true },
    { label: 'Projetos', num: true },
  ], areaRows), 'campo areas de GET /system/projects')}
    <section class="panel"><div class="panel-body">
      <p class="muted" style="margin:0;font-size:12px">Tabelas geradas iterando os arrays devolvidos pela API.
      Colunas de notas/área vêm de <code>GET /system/projects</code>; colunas de citações/tokens/relevância são
      calculadas a partir de <code>sources[]</code> das runs. Nenhum nome de projeto está embutido no código.</p>
    </div></section>
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
    <td class="num">${f.rel.length ? fmtNum(mean(f.rel), 2) : '—'}</td>
  </tr>`);

  return `
    <div class="grid grid-kpi">
      ${metricCard({
    title: 'Notas no vault', value: fmtNum(num(get(reg, 'total_notes')) ?? get(info, 'markdown_files')),
    unit: 'notas .md', deltaText: 'fonte: /system/projects', deltaCls: 'flat', context: 'vault somente leitura',
    tip: 'Campo total_notes de GET /system/projects (fallback: markdown_files de GET /system/info).',
  })}
      ${metricCard({
    title: 'Arquivos já recuperados', value: fmtNum(files.size), unit: 'arquivos distintos',
    deltaText: 'derivado', deltaCls: 'flat', context: `em ${details.length} runs detalhadas`,
  })}
      ${metricCard({
    title: 'Cobertura do vault',
    value: (() => {
      const tot = num(get(reg, 'total_notes')) ?? num(get(info, 'markdown_files'));
      return tot ? fmtPct(files.size / tot, 1) : '—';
    })(),
    unit: 'do vault citado', deltaText: 'derivado', deltaCls: 'flat', context: 'arquivos citados ÷ total de notas',
    tip: 'Fração das notas do vault que já apareceu em algum contexto nas runs carregadas.',
  })}
      ${metricCard({
    title: 'Vault acessível', value: get(info, 'vault_exists') ? 'sim' : 'não', unit: '',
    deltaText: get(info, 'vault_exists') ? 'ok' : 'falha', deltaCls: get(info, 'vault_exists') ? 'good' : 'bad',
    context: 'campo vault_exists',
  })}
    </div>
    ${panel('Caminho e grafo', `<table class="data"><tbody>
      <tr><th class="rowhead">Vault</th><td class="mono">${esc(get(info, 'vault') || '—')}</td></tr>
      <tr><th class="rowhead">Grafo (graphify)</th><td class="mono">${esc(get(info, 'graph_path') || '—')}</td></tr>
      <tr><th class="rowhead">Versão graphify</th><td class="mono">${esc(get(info, 'graphify') || '—')}</td></tr>
      <tr><th class="rowhead">Banco</th><td class="mono">${esc(get(info, 'db') || '—')}</td></tr>
    </tbody></table>`, 'GET /system/info')}
    ${panel('Distribuição de notas por área', areaBreakdown(reg), 'GET /system/projects → areas')}
    ${panel('Notas mais recuperadas', rows.length ? table([
    { label: 'Arquivo' }, { label: 'Citações', num: true }, { label: 'Seções distintas', num: true },
    { label: 'Tokens médios', num: true }, { label: 'Relevância média', num: true },
  ], rows) : notWiredState('sources[] vazio nas runs carregadas'),
  `top ${top.length} de ${files.size} arquivos`)}
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
    <td>${esc(PIPELINE_LABEL[c.pipeline] || c.pipeline)}</td>
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
    deltaText: 'fonte: /system/integrations', deltaCls: 'flat', context: 'registry de adapters',
  })}
      ${metricCard({
    title: 'Agentes disponíveis', value: fmtNum(avail), unit: `de ${agents.length}`,
    deltaText: avail ? 'ok' : 'nenhum', deltaCls: avail ? 'good' : 'attn', context: 'campo available',
  })}
      ${metricCard({
    title: 'Consumidores com runs', value: fmtNum(consumers.length), unit: 'grupos agent×model×pipeline',
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
  ], rows) : notWiredState('/system/integrations não retornou agents[]'), 'GET /system/integrations')}
    ${panel('Desempenho por consumidor', cRows.length ? table([
    { label: 'Agente' }, { label: 'Modelo' }, { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Latência mediana', num: true, tipKey: 'total_latency_ms' }, { label: 'p95', num: true },
    { label: 'Contexto', num: true, tipKey: 'context_tokens' },
    { label: 'Tokens do agente', num: true }, { label: 'Custo médio', num: true, tipKey: 'total_cost' },
  ], cRows) : emptyState('Nenhuma run com agente',
    'Todas as runs gravadas são <code>retrieval-only</code> (sem consumidor). Rode um benchmark com <code>consumers</code> para popular esta tabela.'),
  'GET /benchmark/stats → groups')}
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
    <td>${esc(PIPELINE_LABEL[c.pipeline] || c.pipeline)}</td>
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
    title: 'Modelo do juiz (JEV)', value: esc(get(info, 'jev_model') || '—'), unit: '',
    deltaText: `SDK ${get(info, 'jev_sdk') || '?'}`, deltaCls: 'flat', context: `modo ${get(info, 'jev_mode') || '—'}`,
    tip: 'Modelo TypeSafe/JEV usado para julgar relevância no pipeline graphify_jev.',
  })}
      ${metricCard({
    title: 'Modelos com runs', value: fmtNum(new Set(consumers.map((c) => c.model)).size), unit: 'modelos medidos',
    deltaText: 'fonte: /benchmark/stats', deltaCls: 'flat', context: 'stats.groups',
  })}
    </div>
    ${panel('Provedores e modelos', provRows.length ? table([
    { label: 'Provedor' }, { label: 'Status' }, { label: 'Modelos', num: true },
    { label: 'Exemplos' }, { label: 'Observação' },
  ], provRows) : notWiredState('/system/info não retornou integrations.models'), 'GET /system/info')}
    ${panel('Modelos medidos em runs', mRows.length ? table([
    { label: 'Modelo' }, { label: 'Agente' }, { label: 'Pipeline' }, { label: 'Runs', num: true },
    { label: 'Input tokens', num: true }, { label: 'Output tokens', num: true },
    { label: 'Custo médio', num: true, tipKey: 'total_cost' },
  ], mRows) : emptyState('Nenhum modelo medido',
    'As runs gravadas não têm <code>model</code> definido (retrieval-only). Nenhum número é inventado aqui.'),
  'GET /benchmark/stats → groups')}
  `;
}

/* ====================================================== SETTINGS ======== */
export function renderSettings(ctx) {
  const info = ctx.systemInfo;
  const rows = [
    ['Vault', get(info, 'vault')], ['Vault existe', String(get(info, 'vault_exists'))],
    ['Arquivos .md', get(info, 'markdown_files')], ['Graphify', get(info, 'graphify')],
    ['Caminho do grafo', get(info, 'graph_path')], ['JEV SDK', get(info, 'jev_sdk')],
    ['Modelo JEV', get(info, 'jev_model')], ['Modo JEV', get(info, 'jev_mode')],
    ['Cache habilitado', String(get(info, 'cache_enabled'))], ['Profile', get(info, 'profile')],
    ['Banco de dados', get(info, 'db')],
  ].map(([k, v]) => `<tr><th class="rowhead">${esc(k)}</th><td class="mono">${esc(v ?? '—')}</td></tr>`);

  const qs = ctx.questions || [];
  const qRows = qs.slice(0, 40).map((q) => `<tr>
    <td class="mono">${esc(q.id)}</td>
    <td>${esc(String(q.question || '').slice(0, 80))}</td>
    <td>${esc(q.category || '—')}</td>
    <td class="num">${fmtNum((q.expected_sources || []).length)}</td>
    <td>${q.answerable === false ? '<span class="pill warn"><span class="dot"></span>não</span>' : 'sim'}</td>
  </tr>`);

  return `
    ${panel('Configuração do sistema', `<table class="data"><tbody>${rows.join('')}</tbody></table>`,
    'somente leitura · GET /system/info')}
    ${panel('Dataset de perguntas', qRows.length ? table([
    { label: 'ID' }, { label: 'Pergunta' }, { label: 'Categoria' },
    { label: 'Fontes esperadas', num: true }, { label: 'Respondível' },
  ], qRows) : notWiredState('/benchmark/questions retornou lista vazia'),
  `${qs.length} perguntas · GET /benchmark/questions`)}
    ${panel('Escrita e ações', emptyState('Somente leitura',
    'Este dashboard só faz GET. Disparar benchmarks (<code>POST /benchmark/run-all</code>), '
    + 'sweeps (<code>POST /benchmark/threshold-sweep</code>) e feedback (<code>POST /feedback/*</code>) '
    + 'existem na API mas não são acionados por esta UI de observabilidade.'))}
  `;
}
