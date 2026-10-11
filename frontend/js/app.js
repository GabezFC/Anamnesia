/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA MAIN APP & HASH ROUTER
 * Gerencia a navegação entre o App Principal (Workspace, Conexões, Config, Custos)
 * e o Laboratório Isolado de Comparação (#/compare/*).
 * Controla modais, paleta de comandos Ctrl+K, toasts e troca de temas.
 */

import { icon } from './icons.js';
import { I18N, getLang, setLang } from './i18n.js';
import { mockProjects, mockCostSummary, mockSessions } from './mock-data.js';

import * as workspacePage from './pages/workspace.js';
import * as connectionsPage from './pages/connections.js';
import * as configPage from './pages/config.js';
import * as costsPage from './pages/costs.js';
import * as compareLab from './pages/compare/index.js';
import { esc } from './format.js';
import { loadLive, installTerminalObserver, registerProject } from './live.js';

// `title` é getter: lê I18N no momento do render para acompanhar a troca de idioma.
const ROUTES = {
  '#/workspace': { id: 'workspace', get title() { return I18N.nav.workspace; }, icon: 'terminal', module: workspacePage },
  '#/connections': { id: 'connections', get title() { return I18N.nav.connections; }, icon: 'connections', module: connectionsPage },
  '#/config': { id: 'config', get title() { return I18N.nav.config; }, icon: 'config', module: configPage },
  '#/costs': { id: 'costs', get title() { return I18N.nav.costs; }, icon: 'costs', module: costsPage },
};

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
let isCommandPaletteOpen = false;
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
  window.addEventListener('keydown', handleKeyboardShortcuts);
  window.addEventListener('anamnesia:toast', (e) => showToast(e.detail));
  window.addEventListener('anamnesia:modal:add-project', () => openModal({ type: 'add-project' }));
  window.addEventListener('anamnesia:modal:snippet', (e) => openModal({ type: 'snippet', ...e.detail }));

  // Dados reais do backend (fallback ao mock se indisponível)
  await loadLive();
  installTerminalObserver();

  // Initial routing
  handleRoute();
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
}

function renderShell() {
  const isLab = currentRoute.startsWith('#/compare');

  // REGRA DE OURO: Se estiver na rota #/compare, a casca do app some completamente
  // e entra o Laboratório de Comparação com header próprio
  if (isLab) {
    const subRoute = currentRoute.replace('#/compare/', '').replace('#/compare', '') || 'overview';
    appRoot.innerHTML = `
      ${compareLab.render(subRoute, { langSwitch: renderLangSwitch() })}
      ${renderGlobalToasts()}
      ${renderCommandPalette()}
    `;
    compareLab.mount(appRoot);
    activePageModule = compareLab;
    attachShellHandlers();
    return;
  }

  // APP PRINCIPAL ANAMNÉSIA: Sidebar com APENAS 4 itens + Topbar + Statusbar
  const routeObj = ROUTES[currentRoute] || ROUTES['#/workspace'];
  activePageModule = routeObj.module;

  const activeProject = mockProjects[0] || { name: 'sem projeto' };
  const activeSession = mockSessions[0] || { profileId: '—' };

  appRoot.innerHTML = `
    <div class="shell-container" data-bind="app-shell">
      <!-- SIDEBAR ESQUERDA (Exatamente 4 itens de navegação + Rodapé) -->
      <aside class="app-sidebar" aria-label="Navegação principal">
        <div>
          <!-- Header da Sidebar -->
          <div class="sidebar-header">
            <a href="#/workspace" class="brand-logo" aria-label="${I18N.app.title}">
              <div class="brand-icon">${icon('cpu', '', 22)}</div>
              <span>${I18N.app.title}</span>
            </a>
          </div>

          <!-- Navegação: Apenas Workspace, Conexões, Config, Custos -->
          <nav class="sidebar-nav" role="navigation">
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
          </nav>
        </div>

        <!-- Rodapé da Sidebar: Saúde local, tema e versão -->
        <div class="sidebar-footer">
          <!-- Mini seletor de depuração de estados (Section 6) -->
          <div class="debug-state-bar" title="Simulador de estados para teste e avaliação">
            <span style="font-weight: 600;">Estado:</span>
            <select class="select-control" data-action="switch-debug-state" style="padding: 2px 18px 2px 6px; font-size: 10px;">
              <option value="loaded" ${currentDebugState === 'loaded' ? 'selected' : ''}>Normal (Carregado)</option>
              <option value="loading" ${currentDebugState === 'loading' ? 'selected' : ''}>Carregando (Skeleton)</option>
              <option value="empty" ${currentDebugState === 'empty' ? 'selected' : ''}>Vazio (Empty State)</option>
              <option value="error" ${currentDebugState === 'error' ? 'selected' : ''}>Erro (Falha)</option>
              <option value="backend-unavailable" ${currentDebugState === 'backend-unavailable' ? 'selected' : ''}>Backend Indisponível</option>
            </select>
          </div>

          <div class="sidebar-health-row">
            <span class="status-indicator">
              <span class="dot dot-success"></span>
              <span>${I18N.app.localHealthOk}</span>
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
              <span style="color: var(--text-tertiary); font-family: var(--font-mono);">${activeProject.name}</span>
            </div>
          </div>

          <div class="topbar-center">
            <button class="command-trigger-btn" data-action="open-command-palette" aria-label="Abrir busca e paleta de comandos">
              <div style="display: flex; align-items: center; gap: 8px;">
                ${icon('search', '', 13)}
                <span>${I18N.app.searchPlaceholder}</span>
              </div>
              <kbd>Ctrl+K</kbd>
            </button>
          </div>

          <!-- Botão "Comparar Modelos" (destacado no canto direito) -->
          <div class="topbar-right">
            <a href="#/compare/overview" class="btn btn-secondary-highlight" data-action="nav-compare" aria-label="${I18N.app.compareModelsBtn}">
              ${icon('scale', '', 14)}
              <span>${I18N.app.compareModelsBtn}</span>
            </a>
          </div>
        </header>

        <!-- ÁREA DE CONTEÚDO DA PÁGINA ATIVA -->
        <div class="app-content" data-bind="content-slot">
          ${activePageModule ? activePageModule.render() : ''}
        </div>

        <!-- STATUS BAR INFERIOR (Alta densidade, nativa do app) -->
        <footer class="app-statusbar" aria-label="Barra de status">
          <div class="statusbar-section">
            <div class="statusbar-item">
              <span class="dot dot-success"></span>
              <span>${I18N.app.localHealthOk}</span>
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item">
              <span>Projeto:</span>
              <span style="color: var(--text-primary); font-weight: 500;">${activeProject.name}</span>
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item">
              <span>Perfil ativo:</span>
              <span style="color: var(--text-primary); font-weight: 500;">${activeSession.profileId}</span>
            </div>
          </div>

          <div class="statusbar-section">
            <div class="statusbar-item tabular">
              <span>Memory Gateway:</span>
              <span style="color: var(--text-primary); font-weight: 600;">${mockCostSummary.total_usd.value == null ? 'custo indisponível' : 'US$ ' + mockCostSummary.total_usd.value.toFixed(2) + ' hoje'}</span>
              <span class="badge-origin badge-origin-measured" style="margin-left: 4px;">medido</span>
            </div>
            <span aria-hidden="true">|</span>
            <div class="statusbar-item tabular">
              <span>${mockSessions.length} sessões ativas</span>
            </div>
          </div>
        </footer>
      </div>

      <!-- Modais Globais & Paleta de Comandos -->
      ${renderModal()}
      ${renderCommandPalette()}
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
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modal-add-title">
          <div class="modal-header">
            <h3 id="modal-add-title" class="card-title">${I18N.workspace.addProjectModalTitle}</h3>
            <button class="btn btn-ghost btn-icon" data-action="close-modal" aria-label="${I18N.app.close}">${icon('x', '', 16)}</button>
          </div>
          <div class="modal-body">
            <div class="input-group">
              <label class="input-label">${I18N.workspace.projectNameLabel}</label>
              <div class="input-control">
                <input type="text" id="new-project-name" placeholder="meu-novo-projeto" autofocus />
              </div>
            </div>
            <div class="input-group">
              <label class="input-label">${I18N.workspace.projectPathLabel}</label>
              <div class="input-control">
                <input type="text" id="new-project-path" placeholder="/home/dev/meu-novo-projeto" />
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
        <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="modal-snip-title">
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

function renderCommandPalette() {
  if (!isCommandPaletteOpen) return '';

  return `
    <div class="command-palette-backdrop is-active" data-action="close-command-palette">
      <div class="command-palette-dialog" role="dialog" aria-modal="true">
        <div class="command-palette-input-wrap">
          ${icon('search', '', 16)}
          <input 
            type="text" 
            class="command-palette-input" 
            placeholder="Digite para buscar páginas, projetos ou ações..." 
            data-action="filter-palette" 
            autofocus 
          />
          <kbd>Esc</kbd>
        </div>
        <div class="command-palette-list" data-bind="palette-list">
          <div class="command-palette-group-title">Navegação Rápida</div>
          <div class="command-palette-item" data-action="palette-navigate" data-target="#/workspace">
            <div class="command-palette-item-left">
              ${icon('terminal', '', 14)}
              <span>Ir para Workspace (IDE)</span>
            </div>
            <kbd>#1</kbd>
          </div>
          <div class="command-palette-item" data-action="palette-navigate" data-target="#/connections">
            <div class="command-palette-item-left">
              ${icon('connections', '', 14)}
              <span>Ir para Conexões</span>
            </div>
            <kbd>#2</kbd>
          </div>
          <div class="command-palette-item" data-action="palette-navigate" data-target="#/config">
            <div class="command-palette-item-left">
              ${icon('config', '', 14)}
              <span>Ir para Configuração</span>
            </div>
            <kbd>#3</kbd>
          </div>
          <div class="command-palette-item" data-action="palette-navigate" data-target="#/costs">
            <div class="command-palette-item-left">
              ${icon('costs', '', 14)}
              <span>Ir para Livro de Custos</span>
            </div>
            <kbd>#4</kbd>
          </div>
          <div class="command-palette-item" data-action="palette-navigate" data-target="#/compare/overview">
            <div class="command-palette-item-left" style="color: var(--lab-accent);">
              ${icon('scale', '', 14)}
              <span>Abrir Laboratório de Comparação de Modelos</span>
            </div>
            <span class="badge-seal badge-seal-experimental">Lab</span>
          </div>

          <div class="command-palette-group-title">Ações do Sistema</div>
          <div class="command-palette-item" data-action="palette-action" data-subaction="new-terminal">
            <div class="command-palette-item-left">
              ${icon('plus', '', 14)}
              <span>${I18N.app.paletteNewTerminal}</span>
            </div>
            <kbd>Ctrl+T</kbd>
          </div>
          <div class="command-palette-item" data-action="palette-action" data-subaction="toggle-theme">
            <div class="command-palette-item-left">
              ${icon('sun', '', 14)}
              <span>${I18N.app.paletteToggleTheme}</span>
            </div>
          </div>
          <div class="command-palette-item" data-action="palette-action" data-subaction="toggle-lang">
            <div class="command-palette-item-left">
              ${icon('info', '', 14)}
              <span>${I18N.app.paletteToggleLang}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderGlobalToasts() {
  return `<div class="toast-container" id="toast-container"></div>`;
}

function showToast({ type = 'info', message = '' }) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <span style="color: ${type === 'success' ? 'var(--success)' : type === 'warning' ? 'var(--warning)' : type === 'error' ? 'var(--danger)' : 'var(--primary)'};">
      ${icon(type === 'success' ? 'check' : type === 'warning' ? 'alertTriangle' : 'info', '', 16)}
    </span>
    <span style="flex: 1;">${esc(message)}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.2s';
    setTimeout(() => toast.remove(), 200);
  }, 3200);
}

function openModal(modalData) {
  activeModal = modalData;
  renderShell();
}

function closeModal() {
  activeModal = null;
  renderShell();
}

function handleKeyboardShortcuts(e) {
  // Ctrl+K / Cmd+K opens Command Palette
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    isCommandPaletteOpen = !isCommandPaletteOpen;
    renderShell();
    return;
  }

  // Escape closes Command Palette or Modal
  if (e.key === 'Escape') {
    if (isCommandPaletteOpen) {
      isCommandPaletteOpen = false;
      renderShell();
    } else if (activeModal) {
      closeModal();
    }
  }
}

function attachShellHandlers() {
  appRoot.onclick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

    switch (action) {
      case 'open-command-palette': {
        isCommandPaletteOpen = true;
        renderShell();
        break;
      }
      case 'close-command-palette': {
        if (e.target.classList.contains('command-palette-backdrop')) {
          isCommandPaletteOpen = false;
          renderShell();
        }
        break;
      }
      case 'set-lang': {
        changeLang(target.getAttribute('data-lang'));
        break;
      }
      case 'toggle-theme': {
        currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
        localStorage.setItem('anamnesia_theme', currentTheme);
        document.documentElement.setAttribute('data-theme', currentTheme);
        renderShell();
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
      case 'palette-navigate': {
        const dest = target.getAttribute('data-target');
        isCommandPaletteOpen = false;
        window.location.hash = dest;
        break;
      }
      case 'palette-action': {
        const subaction = target.getAttribute('data-subaction');
        isCommandPaletteOpen = false;
        if (subaction === 'toggle-theme') {
          currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
          localStorage.setItem('anamnesia_theme', currentTheme);
          document.documentElement.setAttribute('data-theme', currentTheme);
          renderShell();
        } else if (subaction === 'toggle-lang') {
          changeLang(getLang() === 'en' ? 'pt' : 'en');
        } else if (subaction === 'new-terminal') {
          window.location.hash = '#/workspace';
        }
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

  // Palette input filter
  const paletteInput = appRoot.querySelector('[data-action="filter-palette"]');
  if (paletteInput) {
    paletteInput.oninput = (e) => {
      const q = e.target.value.toLowerCase().trim();
      const items = appRoot.querySelectorAll('.command-palette-item');
      items.forEach(it => {
        const text = it.textContent.toLowerCase();
        it.style.display = text.includes(q) ? 'flex' : 'none';
      });
    };
  }
}

// Start application when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
