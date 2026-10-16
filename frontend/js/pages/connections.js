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
import { testConn, snippetOf } from '../live.js';
import { listConnections, setSecret, removeSecret } from '../anamnesia-api.js';
import { healthSection, mountHealth } from './provider-health.js';

/* ------------------------------------------------------------------ chaves por provedor */
// Estado por variável vindo de GET /api/connections ({cid: {ENV: {has_key, masked}}}); só máscara, nunca o segredo.
const keyStatus = {};

const tKeys = () => I18N.config || {};
const fmtMsg = (m, vars) => String(m).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');

/** Id de DOM seguro (a11y: associa <label for> ao campo). */
const domId = (v) => String(v).replace(/[^A-Za-z0-9_-]/g, '-');

/** Linhas de chave (uma por variável de ambiente) de uma conexão. Input password sempre vazio. */
export function renderKeyRows(item) {
  const t = I18N.connections;
  const c = tKeys();
  const envKeys = item.env_keys || [];
  if (!envKeys.length) {
    return `
      <div class="connection-key-section">
        <label class="input-label" for="key-${domId(item.id)}">${t.apiKeyLabel}</label>
        <div class="input-control">
          <input id="key-${domId(item.id)}" type="password" autocomplete="new-password" value="" placeholder="${t.apiKeyPlaceholder}" readonly disabled data-bind="masked-key-input" />
        </div>
      </div>`;
  }
  return envKeys.map((env) => {
    const st = (keyStatus[item.id] || {})[env];
    const has = st ? !!st.has_key : !!item.has_key;
    const masked = st ? st.masked : item.masked_key;
    return `
      <div class="connection-key-section" data-env-key="${esc(env)}">
        <label class="input-label" for="key-${domId(item.id)}-${domId(env)}">${t.apiKeyLabel} · <span class="tabular">${esc(env)}</span>
          <span class="chip ${has ? 'chip-configured' : 'chip-unconfigured'}">${has ? c.keyConfigured : c.keyMissing}</span>
        </label>
        <div class="input-control config-key-row">
          <input
            id="key-${domId(item.id)}-${domId(env)}"
            type="password"
            autocomplete="new-password"
            value=""
            placeholder="${masked ? esc(masked) : (c.keyPlaceholder || t.apiKeyPlaceholder)}"
            data-bind="masked-key-input"
            data-env-key="${esc(env)}"
          />
          <button class="btn btn-primary btn-sm" data-action="save-key" data-item-id="${esc(item.id)}" data-env-key="${esc(env)}">${c.keySave}</button>
          <button class="btn btn-ghost btn-sm" data-action="remove-key" data-item-id="${esc(item.id)}" data-env-key="${esc(env)}" ${has ? '' : 'disabled'}>${c.keyRemove}</button>
        </div>
      </div>`;
  }).join('');
}

const allConnections = () => [...mockConnections.agents, ...mockConnections.models, ...mockConnections.mcp];

/** Relê máscaras/estado das chaves do servidor e atualiza os cartões em memória. */
export async function refreshKeyStatus() {
  try {
    const list = await listConnections();
    for (const c of list) {
      keyStatus[c.id] = c.keys || {};
      const item = allConnections().find((x) => x.id === c.id);
      if (item) { item.has_key = !!c.has_key; item.masked_key = c.masked ? esc(c.masked) : null; }
    }
  } catch { /* backend indisponível: mantém o que há */ }
}

const safeErr = (e) => (e && e.message ? e.message : String(e));

/**
 * Ações de chave compartilhadas (#/connections e #/config → Chaves). `target` é o botão clicado.
 * Nunca registra nem exibe o valor digitado; o input é limpo assim que a requisição é montada.
 */
export async function handleKeyAction(action, target, { toast, rerender } = {}) {
  const c = tKeys();
  const itemId = target.getAttribute('data-item-id');
  const found = allConnections().find((x) => x.id === itemId);
  const name = found?.name || itemId;
  const card = target.closest('.connection-card') || document;

  if (action === 'test-connection') {
    try {
      const r = await testConn(itemId);
      const ok = r && (r.ok === true || r.status === 'ok');
      toast(ok ? 'success' : 'error', `${name}: ${r?.message || r?.status || (ok ? 'ok' : 'falhou')}`);
    } catch (err) { toast('error', `${name}: ${safeErr(err)}`); }
    return;
  }

  if (action === 'remove-key') {
    const env = target.getAttribute('data-env-key');
    try {
      await removeSecret(itemId, env);
      toast('success', c.keyRemoved);
    } catch (err) { toast('error', fmtMsg(c.keyFailed, { err: safeErr(err) })); }
    await refreshKeyStatus();
    if (rerender) rerender();
    return;
  }

  // save-key (uma variável) ou save-connection (todas as preenchidas do cartão)
  const inputs = [...card.querySelectorAll('input[type="password"][data-env-key]')]
    .filter((i) => action === 'save-connection' || i.getAttribute('data-env-key') === target.getAttribute('data-env-key'));
  const pending = [];
  for (const input of inputs) {
    if (input.value) {
      const v = input.value; input.value = '';
      pending.push([input.getAttribute('data-env-key'), v]);
    }
  }
  if (!pending.length) { toast('info', c.keyEmptyInput || 'Informe a chave para salvar.'); return; }
  let failed = null;
  for (const [env, v] of pending) {
    try { await setSecret(itemId, env, v); } catch (err) { failed = err; break; }
  }
  if (failed) toast('error', fmtMsg(c.keyFailed, { err: safeErr(failed) }));
  else toast('success', c.keySaved);
  await refreshKeyStatus();
  if (rerender) rerender();
}

let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'

export function render() {
  const t = I18N.connections;

  // Loading Skeleton State
  if (currentState === 'loading') {
    return `
      <div class="connections-page">
        <div class="skeleton u-da8145"></div>
        <div class="cards-grid">
          <div class="skeleton u-35e8b6"></div>
          <div class="skeleton u-35e8b6"></div>
          <div class="skeleton u-35e8b6"></div>
        </div>
      </div>
    `;
  }

  // Error State
  if (currentState === 'error') {
    return `
      <div class="state-container u-2d3094">
        <div class="state-icon-wrap u-52b1c0">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Não foi possível carregar os descritores de sockets e tokens locais.</p>
        <button class="btn btn-secondary" data-action="retry-connections">${I18N.app.errorRetry}</button>
      </div>
    `;
  }

  // Empty State
  if (currentState === 'empty') {
    return `
      <div class="state-container u-2d3094">
        <div class="state-icon-wrap">${icon('connections', '', 28)}</div>
        <h2 class="state-title">Nenhuma conexão registrada</h2>
        <p class="state-description">Adicione agentes locais ou configure chaves de provedores de modelos.</p>
      </div>
    `;
  }

  const backendNotice = currentState === 'backend-unavailable' ? `
    <div class="callout-notice u-36fc7e">
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

        <!-- Chaves por variável de ambiente (NUNCA reexibir a chave real no client-side) -->
        ${renderKeyRows(item)}

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
          <h1 class="u-23e58e">${I18N.nav.connections}</h1>
          <p class="u-47c8df">
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

      ${healthSection()}
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
    const all = allConnections();
    const found = all.find(x => x.id === itemId);
    if (action === 'test-connection' || action === 'save-connection' || action === 'save-key' || action === 'remove-key') {
      handleKeyAction(action, target, { toast, rerender: () => { root.innerHTML = render(); } });
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
  const stopHealth = mountHealth(root);
  refreshKeyStatus().then(() => { if (root.isConnected) root.innerHTML = render(); });
  root._connectionsCleanup = () => {
    root.removeEventListener('click', handleClick);
    stopHealth();
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
