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

const NAV = [
  ['dashboard', 'Dashboard', '◎'], ['benchmarks', 'Benchmarks', '⇄'], ['pipeline', 'Pipeline', '⇉'],
  ['tokens', 'Tokens', '▤'], ['latency', 'Latência', '◷'], ['costs', 'Custos', '$'],
  ['results', 'Resultados', '✓'],
  ['projects', 'Projetos', '▣'], ['memory', 'Memória', '❖'], ['agents', 'Agentes', '◈'],
  ['models', 'Modelos', '◐'],
  ['history', 'Histórico', '↻'], ['config', 'Configuração', '⚙'],
];
const NAV_GROUPS = [
  ['Observabilidade', 0, 6],
  ['Evidência', 6, 7],
  ['Entidades', 7, 11],
  ['Sistema', 11, 13],
];

const PAGES = {
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
  costs: {
    title: 'Custos', sub: 'Custo do modelo consumidor, do juiz, por query e por 1K tokens.',
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
  config: {
    title: 'Configuração',
    sub: 'Configuração ativa, pipeline selecionado, flags de otimização, dataset e estado das runs.',
    render: renderConfig, needs: ['core', 'system', 'questions', 'latestRun'],
  },
};

/** UI state persisted across navigation (toggles). */
const state = { pipeline: 'graphify_jev_opt', tokenView: 'total', costView: 'total', histSeries: 'tokens' };
const ctx = {
  runs: [], sessions: [], stats: null, details: [], systemInfo: null, questions: [],
  projects: null, health: null, latestRunDetail: null, state, api: API,
};

const $ = (s) => document.querySelector(s);
const route = () => (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?')[0];

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
        ${NAV_GROUPS.map(([label, a, b]) =>
    `<div class="nav-group">${esc(label)}</div>${NAV.slice(a, b).map(navLink).join('')}`).join('')}
        <div class="nav-foot">Somente leitura · nenhum dado é inventado</div>
      </nav>
      <div id="scrim"></div>
      <main id="main" tabindex="-1">
        <div class="page-head"><h1 id="page-title">…</h1><p id="page-sub"></p></div>
        <div id="page-body"></div>
      </main>
    </div>`;
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
async function navigate() {
  const id = route();
  const known = Boolean(PAGES[id]);
  const page = PAGES[id] || PAGES.dashboard;
  const token = ++rendering;

  document.querySelectorAll('[data-nav]').forEach((a) =>
    a.classList.toggle('active', a.dataset.nav === (known ? id : 'dashboard')));
  $('#page-title').textContent = page.title;
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
  root.querySelectorAll('[data-session]').forEach((a) => {
    a.addEventListener('click', async () => {
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
    });
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
window.addEventListener('hashchange', navigate);
refreshHeader();
navigate();
setInterval(refreshHeader, 30000);
