// app.js — hash router + shell. ES module; no framework, no build step.
import * as API from './api.js';
import { esc, fmtDate, get, realRuns, metricsOf, num, fmtCompact, mean, totalTokens } from './format.js';
import {
  errorState, skeletonCards, skeletonChart, skeletonTable, panel,
} from './components.js';
import {
  loadCore, loadRecentDetails, getSystemInfo, getQuestions, getProjects, RUN_LIMIT,
} from './store.js';
import { destroyCharts } from './charts.js';
import {
  renderDashboard, mountDashboard, renderBenchmarks, renderPipeline, mountPipeline,
  renderTokens, mountTokens, renderLatency, mountLatency, renderCosts, mountCosts,
} from './pages-core.js';
import {
  renderHistory, mountHistory, unmountHistory, renderProjects, renderMemory, renderAgents, renderModels,
} from './pages-data.js';
import { renderConfig, renderResults } from './pages-config.js';
import { mountSetup, renderSetup } from './pages-setup.js';
import { renderWorkspace, mountWorkspace, unmountWorkspace, workspaceActions } from './pages-workspace.js';
import { renderConnections, mountConnections, unmountConnections } from './pages-connections.js';
import { renderOrchestration, mountOrchestration, unmountOrchestration } from './pages-orchestration.js';
import { renderAnaCosts, mountAnaCosts, unmountAnaCosts } from './pages-anacosts.js';
import { renderHealthBanner, installPalette } from './shell-extras.js';
import { installLangToggle, t } from './i18n.js';

// Anamnesia shell: Workspace is the home page. The four top entries are the product; every
// pre-existing benchmark/observability page is kept and re-routed under Custos > "Benchmark avançado".
const NAV_MAIN = [
  ['workspace', 'Workspace', '▦'], ['connections', 'Conexões', '⇌'], ['config', 'Config', '⚙'], ['costs', 'Custos', '$'],
];
// Config-adjacent gateway pages (formerly "Configuração" and "Setup").
const NAV_CONFIG_SUB = [['setup', 'Setup do gateway', '⚒'], ['config-active', 'Configuração ativa', '☰']];
const NAV = [
  ['dashboard', 'Dashboard', '◎'], ['benchmarks', 'Benchmarks', '⇄'], ['pipeline', 'Pipeline', '⇉'],
  ['tokens', 'Tokens', '▤'], ['latency', 'Latência', '◷'], ['costs-model', 'Custo por modelo', '$'],
  ['results', 'Resultados', '✓'],
  ['projects', 'Projetos', '▣'], ['memory', 'Memória', '❖'], ['agents', 'Agentes', '◈'],
  ['models', 'Modelos', '◐'],
  ['history', 'Histórico', '↻'],
];
const NAV_GROUPS = [
  ['Observabilidade', 0, 6],
  ['Evidência', 6, 7],
  ['Entidades', 7, 11],
  ['Sistema', 11, 12],
];
// Old hash ids that moved: keep bookmarks working where the meaning is unchanged.
const ALIASES = { 'bench-costs': 'costs-model' };

const PAGES = {
  workspace: {
    title: 'Workspace', wide: true,
    sub: 'Projetos, terminais e arquivos no mesmo lugar. Os terminais continuam rodando no servidor ao trocar de página.',
    render: renderWorkspace, mount: mountWorkspace, unmount: unmountWorkspace, needs: [],
  },
  connections: {
    title: 'Conexões',
    sub: 'Agentes, modelos e servidores MCP. As chaves são enviadas uma vez ao servidor e nunca são exibidas de volta.',
    render: renderConnections, mount: mountConnections, unmount: unmountConnections, needs: [],
  },
  config: {
    title: 'Config',
    sub: 'Predefinições de subagentes: quais classes de modelo cada papel usa.',
    render: renderOrchestration, mount: mountOrchestration, unmount: unmountOrchestration, needs: [],
  },
  costs: {
    title: 'Custos',
    sub: 'Livro de custos por chamada do Memory Gateway: medido, estimado ou indisponível — nunca inventado.',
    render: renderAnaCosts, mount: mountAnaCosts, unmount: unmountAnaCosts, needs: [],
  },
  dashboard: {
    title: 'Dashboard',
    sub: 'Visão geral dos pipelines de retrieval, com gasto real de tokens e comparação Baseline vs Otimizado.',
    render: renderDashboard, mount: mountDashboard, needs: ['core', 'details'],
  },
  benchmarks: {
    title: 'Comparação de benchmarks',
    sub: 'Baseline vs Graphify vs pipelines com juiz. Destaque apenas em diferenças significativas.',
    render: renderBenchmarks, needs: ['core', 'details'],
  },
  pipeline: {
    title: 'Visualização do pipeline',
    sub: 'Fluxo query → retrieval → graphify → pré-filtro → JEV → filter → context → model.',
    render: renderPipeline, mount: mountPipeline, needs: ['core'],
  },
  tokens: {
    title: 'Eficiência de tokens',
    sub: 'Contexto entregue ao consumidor vs tokens realmente gastos, incluindo os pagos ao juiz.',
    render: renderTokens, mount: mountTokens, needs: ['core'],
  },
  latency: {
    title: 'Latência', sub: 'Decomposição por estágio do pipeline.',
    render: renderLatency, mount: mountLatency, needs: ['core'],
  },
  'costs-model': {
    title: 'Custo por modelo', sub: 'Benchmark avançado — custo do modelo consumidor, do juiz, por query e por 1K tokens.',
    render: renderCosts, mount: mountCosts, needs: ['core'],
  },
  results: {
    title: 'Resultados e procedência',
    sub: 'O que é Verificado, o que é apenas Experimental e o que foi Invalidado.',
    render: renderResults, needs: ['core'],
  },
  projects: {
    title: 'Projetos',
    sub: 'Projetos e áreas descobertos no vault, cruzados com a atividade de retrieval.',
    render: renderProjects, needs: ['core', 'details', 'projects'],
  },
  memory: {
    title: 'Memória', sub: 'Vault, grafo, áreas e notas mais recuperadas.',
    render: renderMemory, needs: ['core', 'details', 'system', 'projects'],
  },
  agents: {
    title: 'Agentes', sub: 'Adapters detectados e desempenho por consumidor.',
    render: renderAgents, needs: ['core', 'system'],
  },
  models: {
    title: 'Modelos', sub: 'Provedores, modelos disponíveis e modelos medidos.',
    render: renderModels, needs: ['core', 'system'],
  },
  history: {
    title: 'Histórico', sub: 'Séries temporais por sessão e run, ordenadas por created_at.',
    render: renderHistory, mount: mountHistory, unmount: unmountHistory, needs: ['core'],
  },
  'config-active': {
    title: 'Configuração ativa',
    sub: 'Configuração ativa, pipeline selecionado, flags de otimização, dataset e estado das runs.',
    render: renderConfig, needs: ['core', 'system', 'questions', 'latestRun'],
  },
  setup: {
    title: 'Configuração (setup)',
    sub: 'Conectar chave de modelo, apontar o vault, ligar o veredito e os estágios opcionais — tudo aplicado em runtime (§3, §5.4).',
    render: renderSetup, mount: mountSetup, needs: [],
  },
};

/** UI state persisted across navigation (toggles). */
const state = {
  pipeline: 'graphify_jev_opt', tokenView: 'total', costView: 'total',
  histSeries: 'tokens', histAgg: 'day', histScale: 'linear', histPeriod: 'all',
};
const ctx = {
  runs: [], sessions: [], stats: null, details: [], systemInfo: null, questions: [],
  projects: null, health: null, latestRunDetail: null, state, api: API,
};

/** Manual refresh: drop every memoised GET and reload the 5000-run preload + header totals. */
ctx.refreshCore = async () => {
  API.invalidate();
  corePromise = null;
  await ensure(['core']);
};

const $ = (s) => document.querySelector(s);
const route = () => {
  const id = (location.hash.replace(/^#\/?/, '') || 'workspace').split('?')[0];
  return ALIASES[id] || id;
};
const BENCH_IDS = NAV.map((n) => n[0]);

/* ---------------------------------------------------------------- shell */
function renderShell() {
  document.body.innerHTML = `
    <a class="skip" href="#main">Pular para o conteúdo</a>
    <div id="app-shell">
      <header id="header">
        <button id="hamburger" aria-label="Alternar menu" aria-expanded="false">☰</button>
        <div class="brand">
          <span class="brand-mark" aria-hidden="true"></span>
          <span class="brand-text">Memory Gateway<small>otimização de contexto com JEV</small></span>
        </div>
        <div class="header-meta">
          <span class="meta-item hide-md">Runs: <b id="hdr-runs">—</b></span>
          <span class="meta-item hide-md">Último benchmark: <b id="hdr-last">—</b></span>
          <span class="meta-item hide-sm">Versão: <b id="hdr-ver">—</b></span>
          <span id="hdr-health" class="pill"><span class="dot"></span>verificando…</span>
        </div>
      </header>
      <nav id="sidebar" aria-label="Navegação principal">
        <div class="nav-group">Anamnesia</div>
        ${NAV_MAIN.map(navLink).join('')}
        ${NAV_GROUPS.map(([label, a, b]) =>
    `<div class="nav-group nav-sub">Benchmark avançado · ${esc(label)}</div>${NAV.slice(a, b).map(navLink).join('')}`).join('')}
        <div class="nav-group nav-sub">Benchmark avançado · Gateway</div>${NAV_CONFIG_SUB.map(navLink).join('')}
        <div class="nav-foot">Atalhos: Ctrl+K (fora do terminal)</div>
      </nav>
      <div id="scrim"></div>
      <main id="main" tabindex="-1">
        <div id="health-banner" class="health-banner" role="region" aria-label="Avisos do servidor" aria-live="polite" hidden></div>
        <div class="page-head" id="page-head"><h1 id="page-title">…</h1><p id="page-sub"></p></div>
        <div id="page-body"></div>
      </main>
    </div>`;
  installLangToggle($('.header-meta'));
  const ham = $('#hamburger');
  ham.addEventListener('click', () => {
    const open = document.body.classList.toggle('nav-open');
    ham.setAttribute('aria-expanded', String(open));
  });
  $('#scrim').addEventListener('click', () => {
    document.body.classList.remove('nav-open');
    ham.setAttribute('aria-expanded', 'false');
  });
}
const navLink = ([id, label, icon]) =>
  `<a href="#/${id}" data-nav="${id}"><span class="nav-icon" aria-hidden="true">${icon}</span>${esc(label)}</a>`;

/* ---------------------------------------------------------------- header */
async function refreshHeader() {
  const pill = $('#hdr-health');
  if (!pill) return;
  try {
    const h = await API.getHealth();
    ctx.health = h;
    renderHealthBanner(h.warnings);
    const ok = h.status === 'ok' && h.vault_exists !== false;
    pill.className = `pill ${ok ? 'ok' : 'warn'}`;
    pill.innerHTML = `<span class="dot"></span>${esc(h.status)}${h.vault_exists === false ? ' · vault ausente' : ''}`;
  } catch {
    ctx.health = null;
    pill.className = 'pill err';
    pill.innerHTML = '<span class="dot"></span>offline';
  }
  // /system/info has no version field; the FastAPI app version lives in /openapi.json.
  try {
    const info = await getSystemInfo();
    ctx.systemInfo = info;
    const ver = $('#hdr-ver');
    if (ver) ver.textContent = info.profile ? `perfil ${info.profile}` : '—';
  } catch { /* header degrades gracefully */ }
  try {
    const spec = await API.getOpenApi();
    const v = get(spec, 'info.version');
    const ver = $('#hdr-ver');
    if (v && ver) ver.textContent = `v${v}`;
  } catch { /* optional */ }
}

/** Header totals come from the history summary (the whole database), not from the 5000-run preload. */
async function refreshHistoryTotals() {
  try {
    const s = await API.getHistorySummary();
    const runsEl = $('#hdr-runs');
    if (runsEl) runsEl.textContent = s.total_runs ? fmtInt(s.total_runs) : 'nenhuma';
    const lastEl = $('#hdr-last');
    if (lastEl) lastEl.textContent = s.newest_run_at ? fmtDate(s.newest_run_at) : 'nenhum';
  } catch { /* keep the preload-derived values */ }
}
const fmtInt = (n) => Number(n).toLocaleString('pt-BR');

function updateHeaderCounts() {
  const rs = realRuns(ctx.runs);
  const runsEl = $('#hdr-runs');
  if (runsEl) runsEl.textContent = rs.length ? `${rs.length}${ctx.runs.length >= RUN_LIMIT ? '+' : ''}` : 'nenhuma';
  const latest = rs.map((r) => num(r.created_at)).filter((x) => x !== null).sort((a, b) => b - a)[0];
  const lastEl = $('#hdr-last');
  if (lastEl) lastEl.textContent = latest ? fmtDate(latest) : 'nenhum';
}

/* ---------------------------------------------------------------- data */
let corePromise = null;
async function ensure(needs) {
  if (needs.includes('core')) {
    if (!corePromise) {
      corePromise = loadCore().then((d) => {
        ctx.runs = d.runs; ctx.sessions = d.sessions; ctx.stats = d.stats;
        updateHeaderCounts();
        refreshHistoryTotals();
      }).catch((e) => { corePromise = null; throw e; });
    }
    await corePromise;
  }
  if (needs.includes('system') && !ctx.systemInfo) ctx.systemInfo = await getSystemInfo();
  if (needs.includes('questions') && !ctx.questions.length) ctx.questions = await getQuestions().catch(() => []);
  if (needs.includes('projects') && !ctx.projects) ctx.projects = await getProjects().catch(() => null);
  if (needs.includes('details') && !ctx.details.length) {
    ctx.details = await loadRecentDetails(ctx.runs, 36).catch(() => []);
  }
  // The configuration view needs config_json, which only the run-detail route returns.
  if (needs.includes('latestRun') && !ctx.latestRunDetail) {
    const newest = realRuns(ctx.runs)[0];
    if (newest?.run_id) ctx.latestRunDetail = await API.getRunDetail(newest.run_id).catch(() => null);
  }
}

/* ---------------------------------------------------------------- render */
let rendering = 0;
let activePage = null;
let lastPageId = null;
// The browser would restore a stale scroll offset on reload; the app always opens at the top.
if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
async function navigate() {
  const id = route();
  const known = Boolean(PAGES[id]);
  const page = PAGES[id] || PAGES.workspace;
  const token = ++rendering;

  document.querySelectorAll('[data-nav]').forEach((a) => {
    const on = a.dataset.nav === (known ? id : 'workspace');
    a.classList.toggle('active', on);
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  document.body.classList.toggle('page-wide', Boolean(page.wide));
  const pageId = known ? id : 'workspace';
  const pageTitle = t(`page.title.${pageId}`) === `page.title.${pageId}` ? page.title : t(`page.title.${pageId}`);
  $('#page-title').textContent = pageTitle;
  document.title = `${pageTitle} · ${t('app.title.suffix')}`;
  // A new route starts at the top; toggles re-render the same route and keep the scroll position.
  if (pageId !== lastPageId) { lastPageId = pageId; window.scrollTo(0, 0); }
  $('#page-sub').textContent = page.sub;
  document.body.classList.remove('nav-open');
  $('#hamburger')?.setAttribute('aria-expanded', 'false');

  // A page that owns a timer (e.g. History's auto-refresh) must stop it before its DOM is
  // replaced, or the interval keeps firing against a detached node.
  if (activePage !== page) activePage?.unmount?.();
  activePage = page;

  const body = $('#page-body');
  destroyCharts(body);
  body.innerHTML = skeletonCards(4)
    + panel('Carregando', skeletonChart(), { sub: 'consultando a API' })
    + panel('Carregando', skeletonTable(6));

  try {
    await ensure(page.needs || []);
    if (token !== rendering) return;               // a newer navigation won
    body.innerHTML = page.render(ctx);
    page.mount?.(body, ctx);
    bindToggles(body);
    bindSessionLinks(body);
  } catch (e) {
    if (token !== rendering) return;
    body.innerHTML = errorState(e && e.message ? e.message : String(e),
      'Verifique se o servidor está no ar (<code>python -m app.main</code>) e se o gateway inicializou '
      + '(<code>GET /health</code> deve responder <code>status: ok</code>). '
      + 'Recarregue a página para tentar novamente.');
  }
}

/** Segmented toggles re-render the current page with new state. */
function bindToggles(root) {
  root.querySelectorAll('[data-seg]').forEach((seg) => {
    seg.querySelectorAll('button[data-val]').forEach((b) => {
      b.addEventListener('click', () => {
        state[seg.dataset.seg] = b.dataset.val;
        navigate();
      });
    });
  });
}

/** Session drill-down. Rendered into a dedicated slot; failures are shown, never swallowed. */
function bindSessionLinks(root) {
  // Delegated, and bound once per root: the sessions table is painted asynchronously and re-painted
  // on every page change/refresh, so per-button listeners would be lost or duplicated.
  if (root._sessionDelegated) return;
  root._sessionDelegated = true;
  root.addEventListener('click', async (ev) => {
    const a = ev.target.closest('[data-session]');
    if (!a) return;
    {
      const box = root.querySelector('#session-detail');
      if (!box) return;
      const sid = a.dataset.session;
      box.innerHTML = panel(`Sessão ${esc(String(sid).slice(0, 24))}`, skeletonTable(3));
      try {
        const runs = await API.getRunsForSession(sid);
        const rs = realRuns(runs);
        const avgTotal = mean(rs.map((r) => totalTokens(metricsOf(r))));
        const avgCtx = mean(rs.map((r) => num(get(metricsOf(r), 'context_tokens'))));
        box.innerHTML = panel(`Sessão ${esc(String(sid).slice(0, 24))}`,
          `<div class="kv-inline">
             <span><b>${rs.length}</b> runs não-warmup</span>
             <span>Tokens gastos (média): <b>${avgTotal === null ? 'Não medido' : fmtCompact(avgTotal)}</b></span>
             <span>Contexto (média): <b>${avgCtx === null ? 'Não medido' : fmtCompact(avgCtx)}</b></span>
           </div>`, { sub: 'GET /benchmark/runs?session_id=…', prov: 'experimental' });
      } catch (e) {
        box.innerHTML = panel(`Sessão ${esc(String(sid).slice(0, 24))}`,
          `<div class="state error"><div class="state-title">Não foi possível carregar a sessão</div>
            <code>${esc(e && e.message ? e.message : String(e))}</code></div>`);
      }
      box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

/* ---------------------------------------------------------------- boot */
// An unexpected rejection must be visible, not silent in the console only.
window.addEventListener('unhandledrejection', (ev) => {
  const body = $('#page-body');
  if (body && !body.querySelector('.state.error')) {
    body.insertAdjacentHTML('afterbegin',
      errorState(`Promessa rejeitada sem tratamento: ${ev.reason?.message || ev.reason}`));
  }
});

renderShell();
installPalette(() => [
  ...NAV_MAIN.map(([id, label]) => ({ id: `go-${id}`, label: `Ir para ${label}`, run: () => { location.hash = `#/${id}`; } })),
  ...NAV.map(([id, label]) => ({ id: `go-${id}`, label: `Benchmark avançado: ${label}`, run: () => { location.hash = `#/${id}`; } })),
  ...(activePage === PAGES.workspace ? workspaceActions() : []),
]);
window.addEventListener('hashchange', navigate);
refreshHeader();
navigate();
setInterval(refreshHeader, 30000);
setInterval(refreshHistoryTotals, 30000);
