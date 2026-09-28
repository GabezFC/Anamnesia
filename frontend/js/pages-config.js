// pages-config.js — Configuration and Results (provenance) views.
//
// CONFIGURATION reads the active configuration from two real sources:
//   * GET /system/info          — vault, graph, judge model/mode, cache, profile, db
//   * the newest run's config_json (GET /benchmark/runs/{id}) — jev + retrieval config as actually used
// Optimization flags come from the runs' `opt_flags` metric, which is OptimizationConfig.active_flags().
// Nothing here is hardcoded and no absolute developer path is ever printed (see safePath).
import {
  esc, fmtNum, fmtPct, fmtDate, get, num, safePath, realRuns, metricsOf, armOf,
  PIPELINE_LABEL, PIPELINE_SHORT, PIPELINES,
} from './format.js';
import {
  panel, emptyState, notWiredState, notMeasuredState, table, kvTable, callout, flagChip, help,
  provenanceBadge, metricCard,
} from './components.js';
import { aggregate, optFlagsOf } from './store.js';
import { RESULTS, statusOf, LIVE_PROVENANCE } from './provenance.js';

/**
 * Every optimization mechanism OptimizationConfig.active_flags() can report, with what it does.
 * The list mirrors config/optimization.py; a flag the backend reports but we do not know about
 * is still displayed (see unknownFlags below) instead of being silently dropped.
 */
const MECHANISMS = [
  ['near_dedup', 'Colapsa quase-duplicatas antes do juiz (limiar calibrado em 0,88).'],
  ['adaptive_k', 'Julga em ondas crescentes de K. Exige early_stopping para compensar.'],
  ['early_stopping', 'Para de escalar quando já há KEEP confirmado no topo do ranking.'],
  ['zero_evidence_drop', 'VETADO: descartaria candidatos sem vocabulário em comum com a query.'],
  ['layered_cache', 'Cache de julgamentos em camadas (L1..L5).'],
  ['cache_promote_l3', 'Serve estimativas da camada L3 (só após medir em shadow).'],
  ['cache_ranking', 'Cache do ranking determinístico.'],
  ['cache_snippets', 'Cache dos snippets recortados.'],
  ['smart_snippet', 'Recorta o snippet ao redor da evidência (mínimo de economia exigido).'],
  ['progressive_context', 'Re-pergunta com mais contexto apenas na banda de ambiguidade.'],
  ['strict_gating', 'Só paga a pergunta de injeção quando ela pode mudar a decisão.'],
  ['query_profiling', 'Classifica a complexidade da query (instrumentação).'],
];
const KNOWN_FLAGS = new Set(MECHANISMS.map(([k]) => k));

/* ====================================================== CONFIG ========== */
export function renderConfig(ctx) {
  const info = ctx.systemInfo;
  if (!info || typeof info !== 'object') {
    return notWiredState('GET /system/info não retornou um objeto de configuração');
  }
  const rs = realRuns(ctx.runs);
  const latest = ctx.latestRunDetail;          // full run row incl. config_json (may be null)
  const cfg = get(latest, 'config') || null;   // { jev: {...}, retrieval: {...} }
  const jev = get(cfg, 'jev');
  const retr = get(cfg, 'retrieval');

  // ---- validity checks. An invalid configuration must be legible, never silent. -------------
  const problems = [];
  if (get(info, 'vault_exists') === false) {
    problems.push(['Vault inacessível',
      'GET /system/info devolveu <code>vault_exists: false</code>. Nenhum retrieval funciona sem o vault. '
      + 'Defina <code>MEMORY_GATEWAY_VAULT</code> no <code>.env</code> ou passe <code>--vault &lt;caminho&gt;</code>.']);
  }
  if (!num(get(info, 'markdown_files'))) {
    problems.push(['Nenhuma nota indexada',
      'O campo <code>markdown_files</code> é 0 ou ausente: o vault existe mas está vazio (ou totalmente excluído '
      + 'por <code>excluded_dirs</code>).']);
  }
  if (!get(info, 'graphify')) {
    problems.push(['graphify indisponível',
      'GET /system/info não devolveu versão do <code>graphify</code>. Os pipelines com grafo caem para o modo de '
      + 'fallback e a recuperação estrutural é perdida.']);
  }
  if (jev) {
    const rel = num(jev.relevance_threshold); const rev = num(jev.review_threshold);
    if (rel !== null && rev !== null && rev > rel) {
      problems.push(['Limiares do juiz invertidos',
        `<code>review_threshold (${rev})</code> é maior que <code>relevance_threshold (${rel})</code>. `
        + 'A banda REVIEW fica vazia e o roteamento nunca produz REVIEW.']);
    }
    if (jev.failure_mode && !['fail_open', 'fail_closed'].includes(jev.failure_mode)) {
      problems.push(['failure_mode desconhecido', `Valor <code>${esc(jev.failure_mode)}</code> não é `
        + '<code>fail_open</code> nem <code>fail_closed</code>.']);
    }
  }
  // adaptive_k without early_stopping is a measured net loss and OptimizationConfig.validate() rejects it.
  const flagsSeen = optFlagsOf(rs.map(metricsOf));
  if (flagsSeen && flagsSeen.includes('adaptive_k') && !flagsSeen.includes('early_stopping')) {
    problems.push(['adaptive_k sem early_stopping',
      'Combinação rejeitada por <code>OptimizationConfig.validate()</code>: medido em 2026-09-27, ondas sem regra '
      + 'de parada escalaram em 120/120 queries e custaram +20,0% de tokens de juiz.']);
  }

  const health = ctx.health;
  const statusRow = health
    ? (health.status === 'ok' && health.vault_exists !== false
      ? '<span class="pill ok"><span class="dot"></span>ok</span>'
      : `<span class="pill warn"><span class="dot"></span>${esc(health.status || 'degradado')}</span>`)
    : '<span class="pill err"><span class="dot"></span>offline</span>';

  // ---- pipeline selected by the most recent run ---------------------------------------------
  const newest = rs[0] || null;
  const selectedPipeline = newest?.pipeline || null;

  // ---- dataset ------------------------------------------------------------------------------
  const qs = ctx.questions || [];
  const withExpected = qs.filter((q) => (q.expected_sources || []).length).length;

  return `
    ${problems.length ? panel('Problemas de configuração',
    problems.map(([t, d]) => `<div class="anom sev-error"><div class="bar"></div>
        <div class="anom-body"><div class="anom-title">${esc(t)}</div>
        <div class="anom-detail">${d}</div></div></div>`).join(''),
    { sub: `${problems.length} problema(s) detectado(s)` })
    : callout('ok', 'Configuração coerente',
      'As verificações de sanidade (vault acessível, notas indexadas, graphify presente, limiares do juiz '
      + 'ordenados, combinações de flags válidas) passaram.')}

    ${panel('Estado do serviço', kvTable([
    ['Status (GET /health)', statusRow, ''],
    ['Vault acessível', get(info, 'vault_exists') ? '<span class="pill ok"><span class="dot"></span>sim</span>' : '<span class="pill err"><span class="dot"></span>não</span>', ''],
    ['Vault (caminho abreviado)', `<span class="mono">${esc(safePath(get(info, 'vault')))}</span>`],
    ['Notas .md indexadas', fmtNum(get(info, 'markdown_files'))],
    ['Grafo (graphify)', `<span class="mono">${esc(safePath(get(info, 'graph_path')))}</span>`],
    ['Versão graphify', `<span class="mono">${esc(get(info, 'graphify') || '—')}</span>`],
    ['Banco de benchmark', `<span class="mono">${esc(safePath(get(info, 'db')))}</span>`],
    ['Perfil', `<span class="mono">${esc(get(info, 'profile') || '—')}</span>`],
    ['Cache habilitado', String(get(info, 'cache_enabled') ?? '—')],
    ['Modelo do juiz', `<span class="mono">${esc(get(info, 'jev_model') || '—')}</span>`],
    ['Modo do juiz', `<span class="mono">${esc(get(info, 'jev_mode') || '—')}</span>`],
    ['SDK do juiz', `<span class="mono">${esc(get(info, 'jev_sdk') || '—')}</span>`],
  ]), { sub: 'GET /health + GET /system/info', prov: 'verified' })}

    ${panel('Pipeline e execução selecionados', newest ? kvTable([
    ['Pipeline da run mais recente', esc(PIPELINE_LABEL[selectedPipeline] || selectedPipeline || '—'), ''],
    ['Braço (runs.mode)', `<span class="mono">${esc(armOf(newest))}</span>`],
    ['Sessão', `<span class="mono">${esc(newest.session_id || '—')}</span>`],
    ['Run', `<span class="mono">${esc(newest.run_id || '—')}</span>`],
    ['Gravada em', esc(fmtDate(newest.created_at)), ''],
    ['Pipelines com runs', PIPELINES.filter((p) => rs.some((r) => r.pipeline === p))
      .map((p) => `<span class="chip chip-on"><span class="dot"></span>${esc(PIPELINE_SHORT[p] || p)}</span>`).join(' ') || '<span class="muted">nenhum</span>', ''],
  ]) : notMeasuredState('runs', 'Nenhuma run gravada: não há estado de execução para mostrar.'),
  { sub: 'derivado de GET /benchmark/runs', prov: 'experimental' })}

    ${panel('Flags de otimização em vigor', optFlagPanel(flagsSeen, rs),
    { sub: 'metrics.opt_flags = OptimizationConfig.active_flags()', prov: 'experimental' })}

    ${panel('Configuração do juiz (JEV) usada na última run', jev
    ? kvTable(Object.entries(jev).map(([k, v]) => [k, `<span class="mono">${esc(String(v))}</span>`]))
    : notMeasuredState('config_json.jev',
      'A run mais recente não trouxe <code>config_json.jev</code>, ou nenhuma run foi carregada.'),
  { sub: 'config_json da run mais recente', prov: 'verified' })}

    ${panel('Configuração de retrieval usada na última run', retr
    ? kvTable(Object.entries(retr).map(([k, v]) => [k,
      // Any config value that looks like a path is abbreviated before display.
      `<span class="mono">${esc(/path|dir/i.test(k) ? safePath(v) : String(v))}</span>`]))
    : notMeasuredState('config_json.retrieval'),
  { sub: 'caminhos abreviados · config_json da run mais recente', prov: 'verified' })}

    ${panel('Dataset de perguntas', qs.length ? `
      <div class="grid grid-kpi dataset-kpis">
        ${metricCard({ title: 'Perguntas', value: fmtNum(qs.length), unit: 'no dataset', deltaText: 'GET /benchmark/questions', deltaCls: 'flat', context: 'carregadas do arquivo configurado' })}
        ${metricCard({ title: 'Com fontes esperadas', value: fmtNum(withExpected), unit: `de ${qs.length}`, deltaText: withExpected ? 'medível' : 'nenhuma', deltaCls: withExpected ? 'good' : 'attn', context: 'única base para recall/precisão' })}
        ${metricCard({ title: 'Categorias', value: fmtNum(new Set(qs.map((q) => q.category).filter(Boolean)).size), unit: 'distintas', deltaText: 'derivado', deltaCls: 'flat', context: 'campo category' })}
      </div>
      ${table([
    { label: 'ID' }, { label: 'Pergunta' }, { label: 'Categoria' },
    { label: 'Fontes esperadas', num: true }, { label: 'Respondível' },
  ], qs.slice(0, 60).map((q) => `<tr>
        <td class="mono">${esc(q.id)}</td>
        <td>${esc(String(q.question || '').slice(0, 90))}</td>
        <td>${esc(q.category || '—')}</td>
        <td class="num">${fmtNum((q.expected_sources || []).length)}</td>
        <td>${q.answerable === false ? '<span class="pill warn"><span class="dot"></span>não</span>' : 'sim'}</td>
      </tr>`))}`
    : notWiredState('/benchmark/questions retornou lista vazia'),
  { sub: `${qs.length} perguntas · mostrando até 60 · GET /benchmark/questions`, prov: 'verified' })}

    ${panel('Escrita e ações', emptyState('Somente leitura',
    '<p class="state-body">Este dashboard só faz GET. Disparar benchmarks (<code>POST /benchmark/run-all</code>), '
    + 'sweeps (<code>POST /benchmark/threshold-sweep</code>) e feedback (<code>POST /feedback/*</code>) '
    + 'existem na API mas não são acionados por esta UI de observabilidade.</p>'))}
  `;
}

function optFlagPanel(flagsSeen, rs) {
  if (flagsSeen === null) {
    return notMeasuredState('metrics.opt_flags',
      'Nenhuma das runs carregadas registra <code>opt_flags</code>. Runs sem essa chave foram gravadas '
      + 'antes da instrumentação de otimização, ou pelo pipeline de referência.');
  }
  const unknown = flagsSeen.filter((f) => !KNOWN_FLAGS.has(f));
  // How many runs carried each flag — so "em vigor" does not mean "em todas as runs".
  const counts = new Map();
  let withFlags = 0;
  for (const r of rs) {
    const f = get(metricsOf(r), 'opt_flags');
    if (!Array.isArray(f)) continue;
    withFlags += 1;
    for (const k of f) counts.set(k, (counts.get(k) || 0) + 1);
  }
  const rows = MECHANISMS.map(([k, desc]) => {
    const n = counts.get(k) || 0;
    return `<tr class="${n ? '' : 'row-empty'}">
      <th class="rowhead">${flagChip(k, n > 0)}</th>
      <td class="num">${fmtNum(n)}</td>
      <td class="num">${withFlags ? fmtPct(n / withFlags, 0) : '—'}</td>
      <td class="muted">${desc}</td>
    </tr>`;
  });
  for (const k of unknown) {
    rows.push(`<tr><th class="rowhead">${flagChip(k, true)}</th>
      <td class="num">${fmtNum(counts.get(k) || 0)}</td>
      <td class="num">${withFlags ? fmtPct((counts.get(k) || 0) / withFlags, 0) : '—'}</td>
      <td class="muted">Flag reportada pelo backend e desconhecida por esta UI — exibida sem descrição em vez de ser omitida.</td></tr>`);
  }
  return `${flagsSeen.length
    ? ''
    : callout('info', 'Nenhum mecanismo ativo nas runs carregadas',
      'Todas as runs com <code>opt_flags</code> reportaram a lista vazia, que é exatamente a configuração '
      + 'de referência congelada (master switch desligado).')}
    ${table([
    { label: 'Mecanismo', tipKey: 'opt_flags' }, { label: 'Runs com a flag', num: true },
    { label: 'Share', num: true }, { label: 'O que faz' },
  ], rows)}
    <p class="muted flow-help">${withFlags} de ${rs.length} runs carregadas registram <code>opt_flags</code>.</p>`;
}

/* ====================================================== RESULTS ========= */
/** Provenance ledger: what is Verified, what is merely Experimental, what is Invalid. */
export function renderResults(ctx) {
  const agg = aggregate(ctx.runs);
  const live = PIPELINES.filter((p) => agg[p]?.runs > 0).length;
  const cards = RESULTS.map(resultCard).join('');
  return `
    ${callout('warn', 'Por que esta página existe',
    'Um número publicado sem procedimento é indistinguível de um palpite. Aqui cada resultado carrega um '
    + 'selo: <b>Verificado</b> (medição isolada e registrada), <b>Experimental</b> (agregado ao vivo, serve '
    + 'para observar, não para publicar) e <b>Inválido — substituído</b> (retirado de circulação, mantido '
    + 'visível para que o erro não se repita).')}

    ${panel('Números ao vivo deste dashboard',
    `<div class="notice-row">${provenanceBadge('experimental')}<p>${esc(LIVE_PROVENANCE.why)}</p></div>
     ${kvTable([
    ['Runs carregadas', fmtNum(realRuns(ctx.runs).length), 'num'],
    ['Pipelines com dados', fmtNum(live), 'num'],
    ['Runs com fontes esperadas (base de recall)', fmtNum(realRuns(ctx.runs).filter((r) => get(metricsOf(r), 'expected_sources_found')).length), 'num'],
  ])}`,
    { sub: 'agregados calculados no navegador', prov: 'experimental' })}

    ${panel('Registro de resultados', cards || notMeasuredState('registro de resultados'),
    { sub: `${RESULTS.length} entradas` })}
  `;
}

function resultCard(r) {
  const s = statusOf(r.status);
  return `<article class="result result-${esc(s.id)}">
    <header class="result-head">
      ${provenanceBadge(r.status)}
      <h3>${esc(r.title)}</h3>
      <span class="result-date">${esc(r.date)}</span>
    </header>
    <div class="result-meta">
      <span>${esc(r.scope)}</span>
      <span class="mono">${esc(r.source)}</span>
    </div>
    ${r.figures?.length ? `<div class="result-figs">${r.figures.map(([k, v, note]) => `
      <div class="result-fig">
        <div class="rf-k">${esc(k)}</div>
        <div class="rf-v ${r.status === 'invalid' ? 'rf-void' : ''}">${esc(v)}</div>
        ${note ? `<div class="rf-n">${esc(note)}</div>` : ''}
      </div>`).join('')}</div>` : ''}
    <p class="result-note">${esc(r.note)}</p>
  </article>`;
}
