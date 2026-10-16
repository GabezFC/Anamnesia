/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA MAIN APP & HASH ROUTER
 * Gerencia a navegação entre o App Principal (Workspace, Conexões, Config, Custos)
 * e o Laboratório Isolado de Comparação (#/compare/*).
 * Controla modais, paleta de comandos Ctrl+K, toasts e troca de temas.
 */

import './dynamic-style.js';
import { icon } from './icons.js';
import { I18N, getLang, setLang } from './i18n.js';
import { mockProjects, mockCostSummary, mockSessions } from './mock-data.js';

import * as workspacePage from './pages/workspace.js';
import * as connectionsPage from './pages/connections.js';
import * as configPage from './pages/config.js';
import * as costsPage from './pages/costs.js';
import * as memoryPage from './pages/memory.js';
import * as decisionPage from './pages/decision.js';
import * as compareLab from './pages/compare/index.js';
import { esc, fmtNumber } from './format.js';
import { installShortcutDispatcher } from './commands.js';
import { registerAppCommands } from './app-commands.js';
import { openPalette, isPaletteOpen } from './components/command-palette.js';
import { trapFocus } from './components/focus-trap.js';
import { loadLive, installTerminalObserver, registerProject, live, demoBlocks, isDemo, checkHealth, refreshAlerts } from './live.js';

// `title` é getter: lê I18N no momento do render para acompanhar a troca de idioma.
const ROUTES = {
  '#/workspace': { id: 'workspace', get title() { return I18N.nav.workspace; }, icon: 'terminal', module: workspacePage },
  '#/connections': { id: 'connections', get title() { return I18N.nav.connections; }, icon: 'connections', module: connectionsPage },
  '#/config': { id: 'config', get title() { return I18N.nav.config; }, icon: 'config', module: configPage },
  '#/costs': { id: 'costs', get title() { return I18N.nav.costs; }, icon: 'costs', module: costsPage },
  '#/memory': { id: 'memory', get title() { return I18N.nav.memory; }, icon: 'database', module: memoryPage },
  '#/decision': { id: 'decision', get title() { return I18N.nav.decision; }, icon: 'cpu', module: decisionPage },
};

let navAdvancedOpen = false;
/** Grupo recolhível "Avançado" da sidebar: abriga páginas experimentais sem poluir a navegação principal. */
function navAdvancedHtml(activeDecision) {
  const open = navAdvancedOpen || activeDecision;
  return `<div class="nav-advanced">
              <button type="button" class="nav-item nav-advanced-toggle" data-action="toggle-nav-advanced" aria-expanded="${open}" aria-controls="nav-advanced-list">
                <span class="nav-item-icon">${icon('chevronDown', '', 16)}</span>
                <span>${esc(I18N.nav.advanced)}</span>
              </button>
              <div id="nav-advanced-list" class="nav-advanced-list" data-bind="nav-advanced-list" ${open ? '' : 'hidden'}>
                <a class="nav-item ${activeDecision ? 'is-active' : ''}" href="#/decision" aria-current="${activeDecision ? 'page' : 'false'}">
                  <span class="nav-item-icon">${icon('cpu', '', 18)}</span>
                  <span>${esc(I18N.nav.decision)}</span>
                </a>
              </div>
            </div>`;
}

/** Seletor PT | EN (botões segmentados; delegação via data-action="set-lang"). */
function renderLangSwitch() {
  const cur = getLang();
  const btn = (code, label) => `<button type="button" class="lang-switch-btn ${cur === code ? 'is-active' : ''}" data-action="set-lang" data-lang="${code}" aria-pressed="${cur === code}" lang="${code === 'en' ? 'en' : 'pt-BR'}">${label}</button>`;
  return `<div class="lang-switch" role="group" aria-label="${I18N.app.language}">${btn('pt', 'PT')}${btn('en', 'EN')}</div>`;
}

function changeLang(lang) {
  if (lang === getLang()) return;
  setLang(lang); // persiste em localStorage e emite 'anamnesia:lang'
}

function getInitialTheme() {
  const saved = localStorage.getItem('anamnesia_theme');
  if (saved) return saved;
  // Respeita preferência do sistema na primeira visita, padrão light
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

let currentRoute = '#/workspace';
let currentTheme = getInitialTheme();
let activePageModule = null;
let modalRelease = null; // libera o focus trap do modal (ANAM-027)
let modalTrigger = null; // elemento que abriu o modal (retorno de foco)
let firstRoute = true;
let activeModal = null; // null | { type: 'add-project' } | { type: 'snippet', title, snippet }
let currentDebugState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'

// Elements cache
let appRoot = null;

export async function init() {
  appRoot = document.getElementById('app');
  if (!appRoot) return;

  // Apply saved theme
  document.documentElement.setAttribute('data-theme', currentTheme);

  // Setup global event listeners
  window.addEventListener('hashchange', handleRoute);
  // Re-renderiza a página atual quando o idioma muda (as páginas leem I18N a cada render)
  window.addEventListener('anamnesia:lang', () => {
    if (!appRoot) return;
    if (activePageModule && activePageModule.unmount) {
      const slot = appRoot.querySelector('[data-bind="content-slot"]');
      if (slot) activePageModule.unmount(slot);
    }
    renderShell();
  });
  registerAppCommands({
    navigate: (hash) => { window.location.hash = hash; },
    openPalette: () => openPalette(),
    toggleTheme,
    toggleLang: () => changeLang(getLang() === 'en' ? 'pt' : 'en'),
    newTerminal: () => {
      window.location.hash = '#/workspace';
      setTimeout(() => document.querySelector('[data-action="toggle-profile-menu"]')?.click(), 60);
    },
  });
  installShortcutDispatcher(window);
  window.addEventListener('keydown', handleModalEscape);
  // ANA-201/202: cabeçalho do Lab (nº de runs/alertas) depende de dados reais carregados sob demanda
  window.addEventListener('anamnesia:lab-ready', () => { if (currentRoute.startsWith('#/compare')) renderShell(); });
  // Saúde real e alertas: atualizados em segundo plano; só os indicadores são repintados (sem re-render de página)
  setInterval(() => { Promise.all([checkHealth(), refreshAlerts()]).then(paintLiveIndicators); }, 30000);
  window.addEventListener('anamnesia:toast', (e) => showToast(e.detail));
  window.addEventListener('anamnesia:modal:add-project', () => openModal({ type: 'add-project' }));
  window.addEventListener('anamnesia:modal:snippet', (e) => openModal({ type: 'snippet', ...e.detail }));

  // Dados reais do backend (fallback ao mock se indisponível)
  await loadLive();
  installTerminalObserver();

  // Initial routing
  handleRoute();
}

/** Repinta só os indicadores de saúde/alertas do shell (não toca no conteúdo da página). */
function paintLiveIndicators() {
  if (!appRoot) return;
  const h = healthView();
  appRoot.querySelectorAll('[data-bind="health"]').forEach((el) => {
    const dot = el.querySelector('.dot'); const txt = el.querySelector('[data-bind="health-text"]');
    if (dot) dot.className = `dot ${h.dot}`;
    if (txt) txt.textContent = h.text;
    const ws = live.health.warnings || [];            // E1: avisos do /health (estágios opcionais ausentes)
    el.title = ws.map((w) => `${w.component}: ${w.message}`).join('\n');
    if (ws.length && txt && live.health.state === 'ok') { txt.textContent = `${h.text} · ${ws.length} aviso(s)`; if (dot) dot.className = 'dot dot-warning'; }
  });
  const slot = appRoot.querySelector('[data-bind="alerts-slot"]');
  if (slot) slot.innerHTML = alertsBadge();
}

function healthView() {
  const st = live.health.state;
  if (st === 'ok') return { dot: 'dot-success', text: I18N.app.localHealthOk };
  if (st === 'warn') return { dot: 'dot-warning', text: I18N.app.localHealthWarn };
  if (st === 'error') return { dot: 'dot-danger', text: I18N.app.localHealthError };
  return { dot: 'dot-neutral', text: I18N.app.unavailable };
}

function alertsBadge() {
  const n = live.alerts.length;
  if (!n) return '';
  return `<a href="#/compare/overview" class="badge-origin badge-alert" aria-label="${esc(I18N.lab.alertsAria.replace('{n}', String(n)))}">${esc(I18N.lab.alertsBadge.replace('{n}', String(n)))}</a>`;
}

/** Banner ÚNICO de modo demonstração (ANA-201): lista os blocos que ainda mostram mock por falha da API. */
function demoBanner() {
  const blocks = demoBlocks();
  if (!blocks.length) return '';
  const names = blocks.map((b) => (I18N.app.demoBlocks && I18N.app.demoBlocks[b]) || b).join(', ');
  return `<div class="demo-banner" role="status" data-bind="demo-banner">${icon('alertTriangle', '', 14)}<span><strong>${esc(I18N.app.demoBanner)}:</strong> ${esc(names)}</span></div>`;
}

function handleRoute() {
  let hash = window.location.hash || '#/workspace';

  // Normalize root
  if (hash === '' || hash === '#/') {
    window.location.hash = '#/workspace';
    return;
  }

  currentRoute = hash;

  // Cleanup active page module
  if (activePageModule && activePageModule.unmount) {
    const contentArea = appRoot.querySelector('[data-bind="content-slot"]');
    if (contentArea) activePageModule.unmount(contentArea);
  }

  renderShell();
  // AUD-038: a cada navegação (não na carga inicial) o foco vai para o conteúdo da nova página.
  if (!firstRoute) focusPageHeading();
  firstRoute = false;
}

function renderShell() {
  renderShellBody();
  updateDocumentTitle();
  syncModalFocus();
}

function renderShellBody() {
  const isLab = currentRoute.startsWith('#/compare');

  // REGRA DE OURO: Se estiver na rota #/compare, a casca do app some completamente
  // e entra o Laboratório de Comparação com header próprio
  if (isLab) {
    const subRoute = currentRoute.split('?')[0].replace('#/compare/', '').replace('#/compare', '') || 'overview';
    appRoot.innerHTML = `
      ${compareLab.render(subRoute, { langSwitch: renderLangSwitch() })}
      ${renderGlobalToasts()}
    `;
    compareLab.mount(appRoot);
    activePageModule = compareLab;
    attachShellHandlers();
    return;
  }

  // APP PRINCIPAL ANAMNÉSIA: Sidebar com APENAS 4 itens + Topbar + Statusbar
  const routeObj = ROUTES[currentRoute] || ROUTES['#/workspace'];
  activePageModule = routeObj.module;

  // ANA-201: valores do shell só vêm do backend; com a API do bloco indisponível o mock NÃO é exibido ("—").
  const wsDemo = isDemo('workspace');
  const activeProject = (!wsDemo && mockProjects[0]) || { name: '—' };
  const activeSession = (!wsDemo && mockSessions[0]) || { profileId: '—' };
  const activeSessions = wsDemo ? null : mockSessions.filter((s) => s.status === 'active').length;
  const costVal = isDemo('costs') ? null : mockCostSummary.total_usd.value;
  const hv = healthView();
  const debugOn = /[?&]debug=1/.test(window.location.hash) || localStorage.getItem('anamnesia_debug') === '1';

  appRoot.innerHTML = `
    <div class="shell-container" data-bind="app-shell">
      <!-- SIDEBAR ESQUERDA (Exatamente 4 itens de navegação + Rodapé) -->
      <a class="skip-link" href="#main-content" data-action="skip-to-content">${esc(I18N.app.skipToContent)}</a>
      <aside class="app-sidebar" aria-label="${esc(I18N.app.mainNav)}">
        <div>
          <!-- Header da Sidebar -->
          <div class="sidebar-header">
            <a href="#/workspace" class="brand-logo" aria-label="${I18N.app.title}">
              <div class="brand-icon">${icon('cpu', '', 22)}</div>
              <span>${I18N.app.title}</span>
            </a>
          </div>

          <!-- Navegação: Apenas Workspace, Conexões, Config, Custos -->
          <nav class="sidebar-nav" aria-label="${esc(I18N.app.mainNav)}">
            <a href="#/workspace" class="nav-item ${routeObj.id === 'workspace' ? 'is-active' : ''}" aria-current="${routeObj.id === 'workspace' ? 'page' : 'false'}">
              <span class="nav-item-icon">${icon('terminal', '', 18)}</span>
              <span>${I18N.nav.workspace}</span>
            </a>
            <a href="#/connections" class="nav-item ${routeObj.id === 'connections' ? 'is-active' : ''}" aria-current="${routeObj.id === 'connections' ? 'page' : 'false'}">
              <span class="nav-item-icon">${icon('connections', '', 18)}</span>
              <span>${I18N.nav.connections}</span>
            </a>
            <a href="#/config" class="nav-item ${routeObj.id === 'config' ? 'is-active' : ''}" aria-current="${routeObj.id === 'config' ? 'page' : 'false'}">
              <span class="nav-item-icon">${icon('config', '', 18)}</span>
              <span>${I18N.nav.config}</span>
            </a>
            <a href="#/costs" class="nav-item ${routeObj.id === 'costs' ? 'is-active' : ''}" aria-current="${routeObj.id === 'costs' ? 'page' : 'false'}">
              <span class="nav-item-icon">${icon('costs', '', 18)}</span>
              <span>${I18N.nav.costs}</span>
            </a>
            <a href="#/memory" class="nav-item ${routeObj.id === 'memory' ? 'is-active' : ''}" aria-current="${routeObj.id === 'memory' ? 'page' : 'false'}">
              <span class="nav-item-icon">${icon('database', '', 18)}</span>
              <span>${I18N.nav.memory}</span>
            </a>
            ${navAdvancedHtml(routeObj.id === 'decision')}
          </nav>
        </div>

        <!-- Rodapé da Sidebar: Saúde local, tema e versão -->
        <div class="sidebar-footer">
          <!-- Mini seletor de depuração de estados (Section 6) -->
          ${debugOn ? `<div class="debug-state-bar" title="Simulador de estados para teste e avaliação">
            <span class="u-93d1d3">Estado:</span>
            <select class="select-control u-92c95c" data-action="switch-debug-state">
              <option value="loaded" ${currentDebugState === 'loaded' ? 'selected' : ''}>Normal (Carregado)</option>
              <option value="loading" ${currentDebugState === 'loading' ? 'selected' : ''}>Carregando (Skeleton)</option>
              <option value="empty" ${currentDebugState === 'empty' ? 'selected' : ''}>Vazio (Empty State)</option>
              <option value="error" ${currentDebugState === 'error' ? 'selected' : ''}>Erro (Falha)</option>
              <option value="backend-unavailable" ${currentDebugState === 'backend-unavailable' ? 'selected' : ''}>Backend Indisponível</option>
            </select>
          </div>` : ''}

          <div class="sidebar-health-row">
            <span class="status-indicator" data-bind="health" role="status">
              <span class="dot ${hv.dot}" aria-hidden="true"></span>
              <span data-bind="health-text">${esc(hv.text)}</span>
            </span>
            <span class="sidebar-version tabular">${I18N.app.version}</span>
          </div>

          <div class="sidebar-actions-row">
            <!-- Alternador de Tema Escuro / Claro -->
            <button class="btn btn-ghost btn-sm" data-action="toggle-theme" title="${I18N.app.toggleTheme}" aria-label="${I18N.app.toggleTheme}">
              ${icon(currentTheme === 'dark' ? 'sun' : 'moon', '', 14)}
              <span>${currentTheme === 'dark' ? I18N.app.switchToLight : I18N.app.switchToDark}</span>
            </button>

            ${renderLangSwitch()}

            <!-- Atalho da paleta -->
            <button class="btn btn-ghost btn-sm" data-action="open-command-palette" title="Paleta de Comandos (Ctrl+K)">
              <kbd>Ctrl+K</kbd>
            </button>
          </div>
        </div>
      </aside>

      <!-- VIEWPORT PRINCIPAL: TOPBAR + CONTEÚDO + STATUS BAR -->
      <div class="main-viewport">
        <!-- TOPBAR: Breadcrumb, Busca/Ctrl+K e Botão Destacado "Comparar Modelos" -->
        <header class="app-topbar">
          <div class="topbar-left">
            <div class="breadcrumb-trail">
              <span>${I18N.app.title}</span>
              <span aria-hidden="true">/</span>
              <span class="breadcrumb-active">${esc(routeObj.title)}</span>
              <span aria-hidden="true">·</span>
              <span class="u-ebaf11">${activeProject.name}</span>
            </div>
          </div>

          <div class="topbar-center">
            <button class="command-trigger-btn" data-action="open-command-palette" aria-haspopup="dialog" aria-label="${esc(I18N.app.openPalette)}">
              <div class="u-598951">
                ${icon('search', '', 13)}
                <span>${I18N.app.searchPlaceholder}</span>
              </div>
              <kbd>Ctrl+K</kbd>
            </button>
          </div>

          <!-- Botão "Comparar Modelos" (destacado no canto direito) -->
          <div class="topbar-right">
            <span data-bind="alerts-slot">${alertsBadge()}</span>
            <a href="#/compare/overview" class="btn btn-secondary-highlight" data-action="nav-compare" aria-label="${I18N.app.compareModelsBtn}">
              ${icon('scale', '', 14)}
              <span>${I18N.app.compareModelsBtn}</span>
            </a>
          </div>
        </header>

        <!-- ÁREA DE CONTEÚDO DA PÁGINA ATIVA -->
        ${demoBanner()}
        <main class="app-content" id="main-content" tabindex="-1" data-bind="content-slot">
          ${activePageModule ? activePageModule.render() : ''}
        </main>

        <!-- STATUS BAR INFERIOR (Alta densidade, nativa do app) -->
        <footer class="app-statusbar" aria-label="${esc(I18N.app.statusBar)}">
          <div class="statusbar-section">
            <div class="statusbar-item" data-bind="health">
              <span class="dot ${hv.dot}" aria-hidden="true"></span>
              <span data-bind="health-text">${esc(hv.text)}</span>
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item">
              <span>${esc(I18N.app.statusProject)}:</span>
              <span class="u-3171f9">${activeProject.name}</span>
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item">
              <span>${esc(I18N.app.statusProfile)}:</span>
              <span class="u-3171f9">${activeSession.profileId}</span>
            </div>
          </div>

          <div class="statusbar-section">
            <div class="statusbar-item tabular">
              <span>Memory Gateway:</span>
              <span class="u-2bbabc">${costVal == null ? esc(I18N.app.statusCostUnavailable) : esc('US$ ' + fmtNumber(costVal, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ' + I18N.app.statusToday)}</span>
              ${costVal == null ? '' : `<span class="badge-origin badge-origin-measured u-eb7604">${esc(I18N.app.measured)}</span>`}
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item tabular">
              <span>${activeSessions == null ? esc(I18N.app.unavailable) : esc(fmtNumber(activeSessions))} ${esc(I18N.app.statusSessions)}</span>
            </div>
          </div>
        </footer>
      </div>

      <!-- Modais Globais & Paleta de Comandos -->
      ${renderModal()}
      ${renderGlobalToasts()}
    </div>
  `;

  // Mount active page module
  const contentArea = appRoot.querySelector('[data-bind="content-slot"]');
  if (contentArea && activePageModule && activePageModule.mount) {
    activePageModule.mount(contentArea);
    if (activePageModule.setDebugState) {
      activePageModule.setDebugState(currentDebugState, contentArea);
    }
  }

  attachShellHandlers();
}

function renderModal() {
  if (!activeModal) return '';

  if (activeModal.type === 'add-project') {
    return `
      <div class="modal-backdrop is-active" data-action="close-modal">
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modal-add-title" tabindex="-1">
          <div class="modal-header">
            <h3 id="modal-add-title" class="card-title">${I18N.workspace.addProjectModalTitle}</h3>
            <button class="btn btn-ghost btn-icon" data-action="close-modal" aria-label="${I18N.app.close}">${icon('x', '', 16)}</button>
          </div>
          <div class="modal-body">
            <div class="input-group">
              <label class="input-label" for="new-project-name">${I18N.workspace.projectNameLabel}</label>
              <div class="input-control">
                <input type="text" id="new-project-name" placeholder="meu-novo-projeto" autocomplete="off" />
              </div>
            </div>
            <div class="input-group">
              <label class="input-label" for="new-project-path">${I18N.workspace.projectPathLabel}</label>
              <div class="input-control">
                <input type="text" id="new-project-path" placeholder="/home/dev/meu-novo-projeto" autocomplete="off" />
              </div>
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" data-action="close-modal">${I18N.app.cancel}</button>
            <button class="btn btn-primary" data-action="submit-add-project">${I18N.app.save}</button>
          </div>
        </div>
      </div>
    `;
  }

  if (activeModal.type === 'snippet') {
    return `
      <div class="modal-backdrop is-active" data-action="close-modal">
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modal-snip-title" tabindex="-1">
          <div class="modal-header">
            <div>
              <h3 id="modal-snip-title" class="card-title">${I18N.connections.snippetModalTitle}</h3>
              <div class="card-subtitle">${esc(activeModal.title)}</div>
            </div>
            <button class="btn btn-ghost btn-icon" data-action="close-modal" aria-label="${I18N.app.close}">${icon('x', '', 16)}</button>
          </div>
          <div class="modal-body">
            <pre class="code-snippet-box"><code>${esc(activeModal.snippet)}</code></pre>
          </div>
          <div class="modal-footer">
            <button class="btn btn-secondary" data-action="copy-snippet" data-snippet-text="${encodeURIComponent(activeModal.snippet)}">
              ${icon('copy', '', 13)} ${I18N.app.copy}
            </button>
            <button class="btn btn-primary" data-action="close-modal">${I18N.app.close}</button>
          </div>
        </div>
      </div>
    `;
  }

  return '';
}

function renderGlobalToasts() {
  return `<div class="toast-container" id="toast-container" role="status" aria-live="polite" aria-atomic="false"></div>`;
}

function showToast({ type = 'info', message = '' }) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <span class="toast-icon toast-icon-${['success', 'warning', 'error'].includes(type) ? type : 'info'}">
      ${icon(type === 'success' ? 'check' : type === 'warning' ? 'alertTriangle' : 'info', '', 16)}
    </span>
    <span class="u-d2dc0a">${esc(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.2s';
    setTimeout(() => toast.remove(), 200);
  }, 3200);
}

function openModal(modalData) {
  modalTrigger = document.activeElement;
  activeModal = modalData;
  renderShell();
}

function closeModal() {
  activeModal = null;
  renderShell();
  const trigger = modalTrigger; modalTrigger = null;
  const target = trigger && trigger.isConnected ? trigger : (trigger?.getAttribute?.('data-action') && document.querySelector(`[data-action="${trigger.getAttribute('data-action')}"]`));
  (target || document.getElementById('main-content'))?.focus?.();
}

/** Focus trap do modal: refeito a cada render do shell (o DOM do diálogo é recriado). */
function syncModalFocus() {
  if (modalRelease) { modalRelease({ restore: false }); modalRelease = null; }
  if (!activeModal || !appRoot) return;
  const dialog = appRoot.querySelector('.modal-dialog');
  if (!dialog) return;
  modalRelease = trapFocus(dialog, { initial: dialog.querySelector('input, textarea') || dialog.querySelector('.modal-footer .btn-primary') });
}

function toggleTheme() {
  currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
  localStorage.setItem('anamnesia_theme', currentTheme);
  document.documentElement.setAttribute('data-theme', currentTheme);
  renderShell();
}

function focusPageHeading() {
  const el = appRoot.querySelector('#main-content') || appRoot.querySelector('h1');
  if (!el) return;
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  el.focus({ preventScroll: true });
}

/** Título do documento por rota (WCAG 2.4.2). */
function routeTitle() {
  if (currentRoute.startsWith('#/compare')) return I18N.a11y.labTitle;
  return (ROUTES[currentRoute] || ROUTES['#/workspace']).title;
}
function updateDocumentTitle() {
  document.title = `${routeTitle()} · ${I18N.a11y.pageTitleSuffix}`;
}

/** Esc fecha o modal (a paleta trata o próprio Esc). */
function handleModalEscape(e) {
  if (e.key === 'Escape' && activeModal && !isPaletteOpen() && !e.defaultPrevented) closeModal();
}

function attachShellHandlers() {
  appRoot.onclick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

    switch (action) {
      case 'open-command-palette': {
        openPalette();
        break;
      }
      case 'skip-to-content': {
        e.preventDefault();
        appRoot.querySelector('#main-content')?.focus();
        break;
      }
      case 'toggle-nav-advanced': {   // grupo "Avançado" da sidebar (Decision Engine): só alterna a visibilidade
        const list = appRoot.querySelector('[data-bind="nav-advanced-list"]');
        if (!list) break;
        const open = list.hidden;
        list.hidden = !open;
        target.setAttribute('aria-expanded', String(open));
        navAdvancedOpen = open;
        break;
      }
      case 'set-lang': {
        changeLang(target.getAttribute('data-lang'));
        break;
      }
      case 'toggle-theme': {
        toggleTheme();
        break;
      }
      case 'close-modal': {
        if (e.target.classList.contains('modal-backdrop') || target.tagName === 'BUTTON') {
          closeModal();
        }
        break;
      }
      case 'submit-add-project': {
        const nameInput = document.getElementById('new-project-name');
        const pathInput = document.getElementById('new-project-path');
        const name = nameInput ? nameInput.value.trim() : '';
        const path = pathInput ? pathInput.value.trim() : '';
        if (name && path) {
          registerProject(name, path).then(() => {
            closeModal();
            showToast({ type: 'success', message: `Projeto ${name} registrado com sucesso!` });
            handleRoute();
          }).catch((err) => showToast({ type: 'error', message: `Não foi possível registrar: ${err.message || err}` }));
        }
        break;
      }
      case 'copy-snippet': {
        const text = decodeURIComponent(target.getAttribute('data-snippet-text') || '');
        if (navigator.clipboard) {
          navigator.clipboard.writeText(text);
        }
        showToast({ type: 'success', message: I18N.app.copied });
        break;
      }
    }
  };

  // State switcher onchange handler
  const debugSelect = appRoot.querySelector('[data-action="switch-debug-state"]');
  if (debugSelect) {
    debugSelect.onchange = (e) => {
      currentDebugState = e.target.value;
      const contentArea = appRoot.querySelector('[data-bind="content-slot"]');
      if (activePageModule && activePageModule.setDebugState && contentArea) {
        activePageModule.setDebugState(currentDebugState, contentArea);
      }
    };
  }
}

// Start application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
