/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA CONNECTIONS PAGE (#/connections)
 * Grade de conexões para Agentes, Modelos e Servidores MCP.
 * Chaves mascaradas, teste de conexão e snippets de integração.
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc } from '../format.js';
import { mockConnections } from '../mock-data.js';
import { testConn, snippetOf, saveKey } from '../live.js';

let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'

export function render() {
  const t = I18N.connections;

  // Loading Skeleton State
  if (currentState === 'loading') {
    return `
      <div class="connections-page">
        <div class="skeleton" style="height: 32px; width: 280px;"></div>
        <div class="cards-grid">
          <div class="skeleton" style="height: 190px;"></div>
          <div class="skeleton" style="height: 190px;"></div>
          <div class="skeleton" style="height: 190px;"></div>
        </div>
      </div>
    `;
  }

  // Error State
  if (currentState === 'error') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap" style="color: var(--danger);">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Não foi possível carregar os descritores de sockets e tokens locais.</p>
        <button class="btn btn-secondary" data-action="retry-connections">${I18N.app.errorRetry}</button>
      </div>
    `;
  }

  // Empty State
  if (currentState === 'empty') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap">${icon('connections', '', 28)}</div>
        <h2 class="state-title">Nenhuma conexão registrada</h2>
        <p class="state-description">Adicione agentes locais ou configure chaves de provedores de modelos.</p>
      </div>
    `;
  }

  const backendNotice = currentState === 'backend-unavailable' ? `
    <div class="callout-notice" style="margin-bottom: var(--space-4);">
      <div class="callout-notice-icon">${icon('info', '', 18)}</div>
      <div class="callout-notice-body">
        <strong>${I18N.app.backendUnavailableTitle}</strong>
        ${I18N.app.backendUnavailableDesc}
      </div>
    </div>
  ` : '';

  const renderCard = (item) => {
    const isOnline = item.status === 'online';
    const isDetected = item.detected;
    const hasKey = item.has_key;

    return `
      <div class="connection-card" data-connection-id="${item.id}" data-bind="connection-card">
        <div class="connection-card-top">
          <div class="connection-brand">
            <div class="connection-avatar">${item.name.charAt(0)}</div>
            <div>
              <div class="connection-name">${item.name}</div>
              <div class="connection-type">${item.type}</div>
            </div>
          </div>
          <div class="connection-chips-row">
            <span class="chip ${isOnline ? 'chip-online' : 'chip-offline'}">
              <span class="dot ${isOnline ? 'dot-success' : 'dot-neutral'}"></span>
              ${isOnline ? t.online : t.offline}
            </span>
          </div>
        </div>

        <div class="connection-chips-row">
          <span class="chip ${isDetected ? 'chip-online' : 'chip-offline'}">${isDetected ? t.detected : t.notDetected}</span>
          <span class="chip ${hasKey ? 'chip-configured' : 'chip-unconfigured'}">${hasKey ? t.configured : t.notConfigured}</span>
        </div>

        <!-- Chave mascarada (NUNCA reexibir a chave real no client-side) -->
        <div class="connection-key-section">
          <label class="input-label">${t.apiKeyLabel}</label>
          <div class="input-control">
            <input 
              type="password" 
              autocomplete="new-password"
              value="" 
              placeholder="${item.masked_key ? esc(item.masked_key) : t.apiKeyPlaceholder}" 
              ${item.env_keys && item.env_keys.length ? '' : 'readonly disabled'}
              data-bind="masked-key-input"
            />
          </div>
        </div>

        <div class="connection-card-actions">
          <button class="btn btn-ghost btn-sm" data-action="view-snippet" data-item-id="${item.id}">
            ${icon('copy', '', 12)} ${t.viewSnippet}
          </button>
          <div class="connection-card-actions-right">
            <button class="btn btn-secondary btn-sm" data-action="test-connection" data-item-id="${item.id}">${I18N.app.test}</button>
            <button class="btn btn-primary btn-sm" data-action="save-connection" data-item-id="${item.id}">${I18N.app.save}</button>
          </div>
        </div>
      </div>
    `;
  };

  return `
    <div class="connections-page" data-bind="connections-page">
      ${backendNotice}

      <div class="connections-header-bar">
        <div>
          <h1 style="font-size: var(--text-2xl); font-weight: var(--font-semibold);">${I18N.nav.connections}</h1>
          <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
            Gerencie instâncias de agentes CLI, roteadores de modelos e conexões MCP locais.
          </p>
        </div>
      </div>

      <!-- SEÇÃO 1: Agentes de Programação -->
      <section class="connections-section">
        <div class="section-title-wrap">
          <h2 class="section-title">${t.agentsTitle}</h2>
          <span class="section-count">${mockConnections.agents.length}</span>
        </div>
        <div class="cards-grid">
          ${mockConnections.agents.map(renderCard).join('')}
        </div>
      </section>

      <!-- SEÇÃO 2: Modelos e Provedores -->
      <section class="connections-section">
        <div class="section-title-wrap">
          <h2 class="section-title">${t.modelsTitle}</h2>
          <span class="section-count">${mockConnections.models.length}</span>
        </div>
        <div class="cards-grid">
          ${mockConnections.models.map(renderCard).join('')}
        </div>
      </section>

      <!-- SEÇÃO 3: Servidores MCP -->
      <section class="connections-section">
        <div class="section-title-wrap">
          <h2 class="section-title">${t.mcpTitle}</h2>
          <span class="section-count">${mockConnections.mcp.length}</span>
        </div>
        <div class="cards-grid">
          ${mockConnections.mcp.map(renderCard).join('')}
        </div>
      </section>
    </div>
  `;
}

export function mount(root) {
  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');
    const itemId = target.getAttribute('data-item-id');

    const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
    const all = [...mockConnections.agents, ...mockConnections.models, ...mockConnections.mcp];
    const found = all.find(x => x.id === itemId);
    if (action === 'test-connection') {
      testConn(itemId).then((r) => {
        const ok = r && (r.ok === true || r.status === 'ok');
        toast(ok ? 'success' : 'error', `${found?.name || itemId}: ${r?.message || r?.status || (ok ? 'ok' : 'falhou')}`);
      }).catch((err) => toast('error', `${found?.name || itemId}: ${err.message || err}`));
    } else if (action === 'save-connection') {
      const card = target.closest('.connection-card, [data-item-card], .card') || root;
      const input = card.querySelector('input[type="password"]');
      const envKey = found?.env_keys?.[0];
      if (input && input.value && envKey) {
        const v = input.value; input.value = '';
        saveKey(itemId, envKey, v).then(() => toast('success', I18N.connections.saveSuccess))
          .catch((err) => toast('error', `Não foi possível salvar: ${err.message || err}`));
      } else {
        toast('info', 'Informe a chave para salvar.');
      }
    } else if (action === 'view-snippet') {
      snippetOf(itemId).then((r) => {
        window.dispatchEvent(new CustomEvent('anamnesia:modal:snippet', { detail: { title: found?.name || itemId, snippet: r.content || r.note || '' } }));
      }).catch(() => {
        if (found) window.dispatchEvent(new CustomEvent('anamnesia:modal:snippet', { detail: { title: found.name, snippet: found.snippet || 'Sem snippet disponível para esta conexão.' } }));
      });
    } else if (action === 'retry-connections') {
      currentState = 'loaded';
      root.innerHTML = render();
    }
  };

  root.addEventListener('click', handleClick);
  root._connectionsCleanup = () => {
    root.removeEventListener('click', handleClick);
  };
}

export function unmount(root) {
  if (root && root._connectionsCleanup) {
    root._connectionsCleanup();
    delete root._connectionsCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) root.innerHTML = render();
}
