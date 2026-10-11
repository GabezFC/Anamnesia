/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA WORKSPACE PAGE (#/workspace)
 * 3-column desktop IDE layout: Projects | Terminals Canvas | Files & Context
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { mockProjects, mockProfiles, mockSessions, mockFiles, mockRecentContext } from '../mock-data.js';
import { renderTerminalFrame } from '../components/terminal-view.js';
import { launchSession, closeSession, loadFiles } from '../live.js';

let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'
let activeProjectId = 'proj-1';
let activeSessionId = 'sess-1';
let isSplitMode = false;
let splitDirection = 'vertical'; // 'vertical' | 'horizontal'
let isFilesOpen = true;
let isContextDrawerOpen = false;
let isProfileMenuOpen = false;
let searchFilter = '';

export function render() {
  const t = I18N.workspace;
  if (!mockProjects.some(p => p.id === activeProjectId) && mockProjects[0]) activeProjectId = mockProjects[0].id;
  if (!mockSessions.some(s => s.id === activeSessionId) && mockSessions[0]) activeSessionId = mockSessions[0].id;

  // Render Skeleton state
  if (currentState === 'loading') {
    return `
      <div class="workspace-layout">
        <div class="workspace-left-col" style="padding: 16px;">
          <div class="skeleton" style="height: 28px; margin-bottom: 16px;"></div>
          <div class="skeleton" style="height: 60px; margin-bottom: 8px;"></div>
          <div class="skeleton" style="height: 60px; margin-bottom: 8px;"></div>
          <div class="skeleton" style="height: 60px;"></div>
        </div>
        <div class="workspace-center-col" style="padding: 24px;">
          <div class="skeleton" style="height: 38px; margin-bottom: 16px;"></div>
          <div class="skeleton" style="height: calc(100% - 60px);"></div>
        </div>
      </div>
    `;
  }

  // Render Error state
  if (currentState === 'error') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap" style="color: var(--danger);">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Falha ao inicializar sessões do subsistema local de terminais.</p>
        <button class="btn btn-secondary" data-action="retry-state">${I18N.app.errorRetry}</button>
      </div>
    `;
  }

  // Render Empty state
  if (currentState === 'empty') {
    return `
      <div class="workspace-layout">
        <div class="workspace-left-col">
          <div class="pane-header">
            <span class="pane-title">${t.projectsTitle}</span>
            <button class="btn btn-secondary btn-sm" data-action="open-add-project">${icon('plus', '', 12)} ${t.addProject}</button>
          </div>
          <div class="state-container" style="padding: 32px 16px;">
            <p class="state-description">Nenhum projeto cadastrado.</p>
          </div>
        </div>
        <div class="workspace-center-col">
          <div class="state-container" style="height: 100%;">
            <div class="state-icon-wrap">${icon('terminal', '', 28)}</div>
            <h2 class="state-title">${t.emptyTerminalTitle}</h2>
            <p class="state-description">${t.emptyTerminalDesc}</p>
            <div style="display: flex; gap: 8px; margin-top: 12px;">
              <button class="btn btn-primary" data-action="new-terminal">${icon('plus', '', 14)} Novo Terminal</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // Render Backend Unavailable callout overlay
  const backendNotice = currentState === 'backend-unavailable' ? `
    <div style="position: absolute; top: 12px; left: 50%; transform: translateX(-50%); z-index: 600; width: 90%; max-width: 680px;">
      <div class="callout-notice">
        <div class="callout-notice-icon">${icon('info', '', 18)}</div>
        <div class="callout-notice-body">
          <strong>${I18N.app.backendUnavailableTitle}</strong>
          ${I18N.app.backendUnavailableDesc}
        </div>
      </div>
    </div>
  ` : '';

  // Filter files
  const filteredFiles = searchFilter
    ? mockFiles.filter(f => f.name.toLowerCase().includes(searchFilter.toLowerCase()))
    : mockFiles;

  // Active Project & Sessions
  const activeProject = mockProjects.find(p => p.id === activeProjectId) || mockProjects[0];
  const activeSession = mockSessions.find(s => s.id === activeSessionId) || mockSessions[0];

  return `
    <div class="workspace-layout" data-bind="workspace-root">
      ${backendNotice}

      <!-- COLUNA ESQUERDA: Projetos & Sessões Ativas (~260px) -->
      <aside class="workspace-left-col" aria-label="Projetos registrados">
        <div class="pane-header">
          <span class="pane-title">${t.projectsTitle}</span>
          <button class="btn btn-ghost btn-sm" data-action="open-add-project" title="${t.addProject}" aria-label="${t.addProject}">
            ${icon('plus', '', 14)}
          </button>
        </div>

        <div class="projects-list-container" data-bind="projects-list" role="list">
          ${mockProjects.map(proj => {
            const isActive = proj.id === activeProjectId;
            const hasActiveSessions = proj.active_sessions > 0;
            return `
              <div class="project-item ${isActive ? 'is-active' : ''}" data-action="select-project" data-project-id="${proj.id}" role="listitem" tabindex="0">
                <div class="project-info">
                  <div class="project-name-row">
                    <span class="dot ${hasActiveSessions ? 'dot-success' : 'dot-neutral'}" title="${hasActiveSessions ? 'Sessão ativa' : 'Inativo'}"></span>
                    <span class="project-name">${proj.name}</span>
                  </div>
                  <span class="project-path">${proj.path}</span>
                </div>
                ${hasActiveSessions ? `<span class="badge-origin badge-origin-measured" title="${proj.active_sessions} terminais ativos">${proj.active_sessions}</span>` : ''}
              </div>
            `;
          }).join('')}
        </div>

        <!-- Sessões ativas agrupadas -->
        <div class="active-sessions-section">
          <div style="display: flex; align-items: center; justify-content: space-between;">
            <span class="pane-title">${t.activeSessions}</span>
            <span class="section-count tabular">${mockSessions.length}</span>
          </div>
          ${mockSessions.map(sess => `
            <div class="session-mini-item" data-action="focus-session" data-session-id="${sess.id}" style="cursor: pointer;">
              <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                <span class="dot dot-success"></span>
                <span style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-primary);">${sess.title}</span>
              </div>
              <span class="time-stamp tabular" style="font-size: 10px;">${sess.startTime}</span>
            </div>
          `).join('')}
        </div>
      </aside>

      <!-- COLUNA CENTRAL: Canvas de Terminais -->
      <main class="workspace-center-col" aria-label="Terminal interativo">
        <!-- Barra de Abas de Terminal com moldura elegante e 3 pontinhos neutros -->
        <div class="terminal-tab-bar" role="tablist">
          <div class="terminal-dots" aria-hidden="true">
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
          </div>

          ${mockSessions.map(sess => {
            const isActive = sess.id === activeSessionId;
            return `
              <div class="terminal-tab ${isActive ? 'is-active' : ''}" role="tab" aria-selected="${isActive}" data-action="switch-tab" data-session-id="${sess.id}">
                ${icon(sess.profileId.includes('claude') || sess.profileId.includes('hermes') ? 'bot' : 'terminal', '', 13)}
                <span>${sess.title}</span>
                <span class="dot dot-success" title="Ativo"></span>
                <button class="terminal-tab-close" data-action="close-session" data-session-id="${sess.id}" title="Fechar terminal" aria-label="Fechar terminal">
                  ${icon('x', '', 12)}
                </button>
              </div>
            `;
          }).join('')}

          <!-- Botão + para novo terminal -->
          <button class="btn btn-ghost btn-sm" data-action="toggle-profile-menu" title="${t.newTerminal}" aria-label="${t.newTerminal}" style="padding: 4px 6px;">
            ${icon('plus', '', 14)}
          </button>

          <!-- Controles de split e gavetas no lado direito da barra -->
          <div class="terminal-actions-bar">
            <button class="btn btn-ghost btn-icon" data-action="split-panel-vertical" title="${t.splitVertical}" aria-label="${t.splitVertical}">
              ${icon('splitV', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="split-panel-horizontal" title="${t.splitHorizontal}" aria-label="${t.splitHorizontal}">
              ${icon('splitH', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="toggle-context-drawer" title="Contexto do agente" aria-label="Contexto do agente">
              ${icon('database', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="toggle-files-panel" title="Painel de arquivos" aria-label="Painel de arquivos">
              ${icon('sidebar', '', 14)}
            </button>
          </div>
        </div>

        <!-- Menu dropdown de perfis (Shell, PowerShell, Hermes, Claude Code, Codex, OpenCode) -->
        <div class="profile-menu ${isProfileMenuOpen ? 'is-open' : ''}" data-bind="profile-menu">
          <div style="padding: 4px 8px; font-size: 11px; font-weight: 600; color: var(--text-tertiary); text-transform: uppercase;">
            Perfis de Execução
          </div>
          ${mockProfiles.map(prof => `
            <div class="profile-menu-item ${!prof.available ? 'is-disabled' : ''}" data-action="launch-profile" data-profile-id="${prof.id}">
              <div class="profile-info">
                ${icon(prof.icon, '', 14)}
                <div>
                  <div style="font-size: 12px; font-weight: 500; color: var(--text-primary);">${prof.name}</div>
                  <div style="font-size: 10px; color: var(--text-tertiary);">${prof.description}</div>
                </div>
              </div>
              ${!prof.available ? `<span class="profile-badge-unavailable">${t.profileUnavailable}</span>` : ''}
            </div>
          `).join('')}
        </div>

        <!-- Contêiner de painéis divididos / fluido -->
        <div class="terminal-panes-wrapper ${isSplitMode ? (splitDirection === 'vertical' ? 'split-vertical' : 'split-horizontal') : ''}">
          ${activeSession ? renderTerminalFrame(activeSession) : `
            <div class="state-container" data-bind="terminal-empty">
              <div class="state-icon-wrap">${icon('terminal', '', 28)}</div>
              <h2 class="state-title">${t.emptyTerminalTitle}</h2>
              <p class="state-description">${mockProjects.length ? 'Use o botão + e escolha um perfil (Shell, PowerShell, Hermes, Claude Code…). O terminal roda localmente dentro do Anamnésia.' : 'Adicione um projeto na coluna da esquerda e depois abra um terminal.'}</p>
            </div>`}
          ${isSplitMode && activeSession ? `
            <div class="terminal-split-divider" data-action="drag-divider"></div>
            ${renderTerminalFrame(mockSessions[1] || activeSession, { isSplit: true })}
          ` : ''}
        </div>
      </main>

      <!-- COLUNA DIREITA: Arquivos do Projeto Ativo (~280px, recolhível) -->
      <aside class="workspace-right-col ${!isFilesOpen ? 'is-collapsed' : ''}" aria-label="Arquivos do projeto">
        <div class="pane-header">
          <span class="pane-title">${t.filesTitle}</span>
          <span class="section-count">${filteredFiles.length}</span>
        </div>

        <div class="files-search-wrap">
          <div class="input-control" style="padding: 3px 8px; font-size: 11px;">
            ${icon('search', '', 12)}
            <input type="text" placeholder="${t.searchFiles}" data-action="filter-files" value="${searchFilter}" style="margin-left: 6px;" />
          </div>
        </div>

        <div class="file-tree-container" data-bind="files-tree">
          ${filteredFiles.map(file => {
            const isDir = file.type === 'dir';
            const indentClass = file.indent === 1 ? 'file-indent-1' : file.indent === 2 ? 'file-indent-2' : '';
            return `
              <div class="file-tree-item ${indentClass}" title="${file.name}">
                ${icon(isDir ? 'folder' : 'file', '', 13)}
                <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${file.name}</span>
                ${file.size ? `<span style="font-size: 10px; color: var(--text-tertiary); font-family: var(--font-mono);">${file.size}</span>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </aside>

      <!-- GAVETA LATERAL: Contexto do Agente (Recolhível) -->
      <div class="drawer-backdrop ${isContextDrawerOpen ? 'is-active' : ''}" data-action="close-context-drawer"></div>
      <div class="drawer ${isContextDrawerOpen ? 'is-active' : ''}">
        <div class="drawer-header">
          <div>
            <div class="card-title">${t.agentContextTitle}</div>
            <div class="card-subtitle">${t.agentContextSubtitle}</div>
          </div>
          <button class="btn btn-ghost btn-icon" data-action="close-context-drawer">
            ${icon('x', '', 16)}
          </button>
        </div>
        <div class="drawer-content">
          ${mockRecentContext.map(ctx => `
            <div class="memory-context-card">
              <div style="font-size: 12px; font-weight: 600; color: var(--text-primary); line-height: 1.4;">${ctx.title}</div>
              <div style="font-size: 10px; font-family: var(--font-mono); color: var(--text-tertiary);">${ctx.source}</div>
              <div class="memory-context-meta">
                <span class="badge-origin badge-origin-measured">${ctx.tokens} tok</span>
                <span>Score: ${(ctx.score * 100).toFixed(0)}% · ${ctx.timestamp}</span>
              </div>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  // Click actions handler
  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) {
      if (isProfileMenuOpen && !e.target.closest('.profile-menu')) {
        isProfileMenuOpen = false;
        refresh(root);
      }
      return;
    }

    const action = target.getAttribute('data-action');

    switch (action) {
      case 'select-project': {
        const id = target.getAttribute('data-project-id');
        if (id) {
          activeProjectId = id;
          loadFiles(id).catch(() => {}).finally(() => refresh(root));
        }
        break;
      }
      case 'switch-tab': {
        const id = target.getAttribute('data-session-id');
        if (id) {
          activeSessionId = id;
          refresh(root);
        }
        break;
      }
      case 'close-session': {
        e.stopPropagation();
        const id = target.getAttribute('data-session-id');
        closeSession(id).then(() => {
          if (activeSessionId === id && mockSessions[0]) activeSessionId = mockSessions[0].id;
          refresh(root);
        });
        break;
      }
      case 'toggle-profile-menu': {
        isProfileMenuOpen = !isProfileMenuOpen;
        refresh(root);
        break;
      }
      case 'launch-profile': {
        const profId = target.getAttribute('data-profile-id');
        const prof = mockProfiles.find(p => p.id === profId);
        if (prof && prof.available && mockProjects.length) {
          isProfileMenuOpen = false;
          launchSession(activeProjectId, prof.id).then((sid) => {
            if (sid) activeSessionId = sid;
            refresh(root);
          }).catch((err) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type: 'error', message: `Não foi possível iniciar: ${err.message || err}` } })));
        }
        break;
      }
      case 'split-panel-vertical': {
        isSplitMode = !isSplitMode;
        splitDirection = 'vertical';
        refresh(root);
        break;
      }
      case 'split-panel-horizontal': {
        isSplitMode = !isSplitMode;
        splitDirection = 'horizontal';
        refresh(root);
        break;
      }
      case 'toggle-files-panel': {
        isFilesOpen = !isFilesOpen;
        refresh(root);
        break;
      }
      case 'toggle-context-drawer':
      case 'close-context-drawer': {
        isContextDrawerOpen = !isContextDrawerOpen;
        refresh(root);
        break;
      }
      case 'open-add-project': {
        window.dispatchEvent(new CustomEvent('anamnesia:modal:add-project'));
        break;
      }
      case 'retry-state': {
        currentState = 'loaded';
        refresh(root);
        break;
      }
      case 'new-terminal': {
        isProfileMenuOpen = true;
        refresh(root);
        break;
      }
    }
  };

  const handleInput = (e) => {
    if (e.target.matches('[data-action="filter-files"]')) {
      searchFilter = e.target.value;
      const tree = root.querySelector('[data-bind="files-tree"]');
      if (tree) {
        const filtered = searchFilter
          ? mockFiles.filter(f => f.name.toLowerCase().includes(searchFilter.toLowerCase()))
          : mockFiles;
        tree.innerHTML = filtered.map(file => {
          const isDir = file.type === 'dir';
          const indentClass = file.indent === 1 ? 'file-indent-1' : file.indent === 2 ? 'file-indent-2' : '';
          return `
            <div class="file-tree-item ${indentClass}" title="${file.name}">
              ${icon(isDir ? 'folder' : 'file', '', 13)}
              <span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${file.name}</span>
              ${file.size ? `<span style="font-size: 10px; color: var(--text-tertiary); font-family: var(--font-mono);">${file.size}</span>` : ''}
            </div>
          `;
        }).join('');
      }
    }
  };

  root.addEventListener('click', handleClick);
  root.addEventListener('input', handleInput);

  root._workspaceCleanup = () => {
    root.removeEventListener('click', handleClick);
    root.removeEventListener('input', handleInput);
  };
}

function refresh(root) {
  root.innerHTML = render();
}

export function unmount(root) {
  if (root && root._workspaceCleanup) {
    root._workspaceCleanup();
    delete root._workspaceCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) refresh(root);
}
