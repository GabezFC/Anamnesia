// app.js — hash router + shell. ES module; no framework, no build step.
import * as API from './api.js';
import { esc, fmtDate, get, realRuns, metricsOf, num } from './format.js';
import { errorState, skeletonCards, skeletonChart, panel } from './components.js';
import { loadCore, loadRecentDetails, getSystemInfo, getQuestions, getProjects } from './store.js';
import {
  renderDashboard, mountDashboard, renderBenchmarks, renderPipeline, mountPipeline,
  renderTokens, mountTokens, renderLatency, mountLatency, renderCosts, mountCosts,
} from './pages-core.js';
import {
  renderHistory, mountHistory, renderProjects, renderMemory, renderAgents, renderModels, renderSettings,
} from './pages-data.js';

const NAV = [
  ['dashboard', 'Dashboard', '◎'], ['benchmarks', 'Benchmarks', '⇄'], ['pipeline', 'Pipeline', '⇉'],
  ['tokens', 'Tokens', '▤'], ['latency', 'Latency', '◷'], ['costs', 'Costs', '$'],
  ['projects', 'Projects', '▣'], ['memory', 'Memory', '❖'], ['agents', 'Agents', '◈'],
  ['models', 'Models', '◐'], ['history', 'History', '↻'], ['settings', 'Settings', '⚙'],
];

const PAGES = {
  dashboard: { title: 'Dashboard', sub: 'Visão geral dos três pipelines de retrieval, com gasto real de tokens.', render: renderDashboard, mount: mountDashboard, needs: ['core', 'details'] },
  benchmarks: { title: 'Comparação de benchmarks', sub: 'Baseline vs Graphify vs Graphify+JEV. Destaque apenas em diferenças significativas.', render: renderBenchmarks, needs: ['core', 'details'] },
  pipeline: { title: 'Visualização do pipeline', sub: 'Fluxo query → retrieval → graphify → JEV → filter → context → model.', render: renderPipeline, mount: mountPipeline, needs: ['core'] },
  tokens: { title: 'Eficiência de tokens', sub: 'Contexto final entregue vs tokens realmente gastos.', render: renderTokens, mount: mountTokens, needs: ['core'] },
  latency: { title: 'Latência', sub: 'Decomposição por estágio do pipeline.', render: renderLatency, mount: mountLatency, needs: ['core'] },
  costs: { title: 'Custos', sub: 'Custo do agente, do juiz JEV, por query e por 1K tokens.', render: renderCosts, mount: mountCosts, needs: ['core'] },
  projects: { title: 'Projetos', sub: 'Projetos e áreas descobertos no vault, cruzados com a atividade de retrieval.', render: renderProjects, needs: ['core', 'details', 'projects'] },
  memory: { title: 'Memória', sub: 'Vault, grafo, áreas e notas mais recuperadas.', render: renderMemory, needs: ['core', 'details', 'system', 'projects'] },
  agents: { title: 'Agentes', sub: 'Adapters detectados e desempenho por consumidor.', render: renderAgents, needs: ['core', 'system'] },
  models: { title: 'Modelos', sub: 'Provedores, modelos disponíveis e modelos medidos.', render: renderModels, needs: ['core', 'system'] },
  history: { title: 'Histórico', sub: 'Séries temporais por sessão e run, ordenadas por created_at.', render: renderHistory, mount: mountHistory, needs: ['core'] },
  settings: { title: 'Configuração', sub: 'Estado do sistema e dataset de perguntas (somente leitura).', render: renderSettings, needs: ['core', 'system', 'questions'] },
};

/** UI state persisted across navigation (toggles). */
const state = { pipeline: 'graphify_jev', tokenView: 'total', costView: 'total', histSeries: 'tokens' };
const ctx = {
  runs: [], sessions: [], stats: null, details: [], systemInfo: null, questions: [],
  projects: null, state, api: API,
};

const $ = (s) => document.querySelector(s);
const route = () => (location.hash.replace(/^#\/?/, '') || 'dashboard').split('?')[0];

/* ---------------------------------------------------------------- shell */
function renderShell() {
  document.body.innerHTML = `
    <div id="app-shell">
      <header id="header">
        <button id="hamburger" aria-label="Alternar menu">☰</button>
        <div class="brand"><span class="brand-dot"></span>Memory Gateway</div>
        <div class="header-meta">
          <span class="meta-item hide-sm">Último benchmark: <b id="hdr-last">—</b></span>
          <span class="meta-item hide-sm">Versão: <b id="hdr-ver">—</b></span>
          <span id="hdr-health" class="pill"><span class="dot"></span>verificando…</span>
        </div>
      </header>
      <nav id="sidebar" aria-label="Navegação principal">
        <div class="nav-group">Observabilidade</div>
        ${NAV.slice(0, 6).map(navLink).join('')}
        <div class="nav-group">Entidades</div>
        ${NAV.slice(6, 10).map(navLink).join('')}
        <div class="nav-group">Sistema</div>
        ${NAV.slice(10).map(navLink).join('')}
      </nav>
      <div id="scrim"></div>
      <main id="main">
        <div class="page-head"><h1 id="page-title">…</h1><p id="page-sub"></p></div>
        <div id="page-body"></div>
      </main>
    </div>`;
  $('#hamburger').addEventListener('click', () => document.body.classList.toggle('nav-open'));
  $('#scrim').addEventListener('click', () => document.body.classList.remove('nav-open'));
}
const navLink = ([id, label, icon]) =>
  `<a href="#/${id}" data-nav="${id}"><span class="nav-icon">${icon}</span>${esc(label)}</a>`;

/* ---------------------------------------------------------------- header */
async function refreshHeader() {
  const pill = $('#hdr-health');
  try {
    const h = await API.getHealth();
    const ok = h.status === 'ok' && h.vault_exists !== false;
    pill.className = `pill ${ok ? 'ok' : 'warn'}`;
    pill.innerHTML = `<span class="dot"></span>${esc(h.status)}${h.vault_exists === false ? ' · vault ausente' : ''}`;
  } catch (e) {
    pill.className = 'pill err';
    pill.innerHTML = '<span class="dot"></span>offline';
  }
  try {
    const info = await getSystemInfo();
    ctx.systemInfo = info;
    // /system/info has no version field; FastAPI app version is exposed at /openapi.json.
    $('#hdr-ver').textContent = info.profile ? `perfil ${info.profile}` : '—';
    try {
      const spec = await API.api('/openapi.json');
      const v = get(spec, 'info.version');
      if (v) $('#hdr-ver').textContent = `v${v}`;
    } catch { /* optional */ }
  } catch { /* header degrades gracefully */ }
}
function updateLastBenchmark() {
  const rs = realRuns(ctx.runs);
  const latest = rs.map((r) => num(r.created_at)).filter((x) => x !== null).sort((a, b) => b - a)[0];
  $('#hdr-last').textContent = latest ? fmtDate(latest) : 'nenhum';
}

/* ---------------------------------------------------------------- data */
let corePromise = null;
async function ensure(needs) {
  if (needs.includes('core')) {
    if (!corePromise) {
      corePromise = loadCore().then((d) => {
        ctx.runs = d.runs; ctx.sessions = d.sessions; ctx.stats = d.stats;
        updateLastBenchmark();
      });
    }
    await corePromise;
  }
  if (needs.includes('system') && !ctx.systemInfo) ctx.systemInfo = await getSystemInfo();
  if (needs.includes('questions') && !ctx.questions.length) ctx.questions = await getQuestions().catch(() => []);
  if (needs.includes('projects') && !ctx.projects) ctx.projects = await getProjects().catch(() => null);
  if (needs.includes('details') && !ctx.details.length) {
    ctx.details = await loadRecentDetails(ctx.runs, 36).catch(() => []);
  }
}

/* ---------------------------------------------------------------- render */
let rendering = 0;
async function navigate() {
  const id = route();
  const page = PAGES[id] || PAGES.dashboard;
  const token = ++rendering;

  document.querySelectorAll('[data-nav]').forEach((a) =>
    a.classList.toggle('active', a.dataset.nav === (PAGES[id] ? id : 'dashboard')));
  $('#page-title').textContent = page.title;
  $('#page-sub').textContent = page.sub;
  document.body.classList.remove('nav-open');

  const body = $('#page-body');
  body.innerHTML = skeletonCards(4) + panel('Carregando', skeletonChart());

  try {
    await ensure(page.needs || []);
    if (token !== rendering) return;               // a newer navigation won
    body.innerHTML = page.render(ctx);
    page.mount?.(body, ctx);
    bindToggles(body);
    bindSessionLinks(body);
  } catch (e) {
    if (token !== rendering) return;
    body.innerHTML = errorState(e.message);
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
function bindSessionLinks(root) {
  root.querySelectorAll('[data-session]').forEach((a) => {
    a.addEventListener('click', async () => {
      try {
        const runs = await API.getRunsForSession(a.dataset.session);
        const box = document.createElement('div');
        box.innerHTML = panel(`Sessão ${esc(String(a.dataset.session).slice(0, 12))}`,
          `<p class="muted" style="margin:0">${runs.length} runs nesta sessão. `
          + `Média de tokens gastos: ${runs.length ? Math.round(runs.reduce((s, r) =>
            s + ((get(metricsOf(r), 'total_tokens_spent')
              ?? ((get(metricsOf(r), 'jev_input_tokens') || 0) + (get(metricsOf(r), 'jev_output_tokens') || 0)
                + (get(metricsOf(r), 'context_tokens') || 0)))), 0) / runs.length).toLocaleString('en-US') : '—'}.</p>`);
        a.closest('.panel').after(box.firstElementChild);
      } catch (e) { /* ignore */ }
    });
  });
}

/* ---------------------------------------------------------------- boot */
renderShell();
window.addEventListener('hashchange', navigate);
refreshHeader();
navigate();
setInterval(refreshHeader, 30000);
