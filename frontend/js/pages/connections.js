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
  if (!envKeys.length && (item.uses_providers || []).length) {
    const names = item.uses_providers.map((id) => { const m = (mockConnections.models || []).find((x) => x.id === id); return m ? m.name : id; }).join(', ');
    return `
      <div class="connection-key-section" data-bind="uses-providers">
        <p class="input-hint">${esc(fmtMsg(c.keyUsesProviders || 'Usa a credencial dos provedores {names}.', { names }))}</p>
      </div>`;
  }
  if (!envKeys.length) {
    return `
      <div class="connection-key-section">
        <p class="input-hint">${esc(c.keyNone || 'Este item não usa chave de API: a autenticação é feita pelo próprio programa.')}</p>
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
      if (item) { item.has_key = !!c.has_key; item.masked_key = c.masked ? esc(c.masked) : null; item.state = c.state; item.state_detail = c.detail || ''; item.uses_providers = c.uses_providers || []; item.detected = !!c.detected; item.status = c.state === 'connected' ? 'online' : 'offline'; }
    }
    return true;
  } catch { return false; /* backend indisponível: mantém o que há */ }
}

/* ------------------------------------------------------------------ estado da conexão (vem do backend) */
export const STATE_LABEL = {
  not_installed: 'Não instalado', detected: 'Detectado · não autenticado', not_configured: 'Não configurado',
  configured: 'Configurado · não testado', testing: 'Testando…', connected: 'Autenticado · verificado',
  auth_error: 'Erro de autenticação', unavailable: 'Erro · indisponível', expired: 'Verificação expirada',
};
const STATE_CHIP = {
  connected: 'chip-online', configured: 'chip-configured', detected: 'chip-configured', testing: 'chip-configured',
  not_configured: 'chip-offline', not_installed: 'chip-offline', unavailable: 'chip-unconfigured',
  auth_error: 'chip-unconfigured', expired: 'chip-unconfigured',
};
export const stateOf = (item) => item.state || (item.has_key ? 'configured' : 'not_configured');

/**
 * Troca o innerHTML preservando o que o usuário está digitando nos campos de chave (e o foco).
 * Sem isso, qualquer re-render assíncrono (refresh de status) apagava a digitação no meio.
 */
export function paintKeepingKeys(root, html) {
  const drafts = new Map();
  root.querySelectorAll('input[data-env-key]').forEach((i) => { if (i.value) drafts.set(i.id, i.value); });
  const active = document.activeElement;
  const activeId = active && root.contains(active) ? active.id : null;
  const caret = activeId && active.selectionStart != null ? active.selectionStart : null;
  root.innerHTML = html;
  drafts.forEach((v, id) => { const el = root.querySelector(`#${CSS.escape(id)}`); if (el) el.value = v; });
  if (activeId) {
    const el = root.querySelector(`#${CSS.escape(activeId)}`);
    if (el) { el.focus(); if (caret != null && el.setSelectionRange) { try { el.setSelectionRange(caret, caret); } catch { /* tipo sem seleção */ } } }
  }
}

const safeErr = (e) => (e && e.message ? e.message : String(e));

/**
 * Ações de chave compartilhadas (#/connections; a antiga aba Configuração › Chaves foi removida). `target` é o botão clicado.
 * Nunca registra nem exibe o valor digitado; o input é limpo assim que a requisição é montada.
 */
export async function handleKeyAction(action, target, { toast, rerender } = {}) {
  const c = tKeys();
  const itemId = target.getAttribute('data-item-id');
  const found = allConnections().find((x) => x.id === itemId);
  const name = found?.name || itemId;
  const card = target.closest('.connection-card') || document;

  if (action === 'test-connection') {
    if (found) { found.state = 'testing'; found.state_detail = ''; if (rerender) rerender(); }
    try {
      const r = await testConn(itemId);
      const st = r && r.state;
      const kind = st === 'connected' ? 'success' : (['configured', 'detected', 'not_configured', 'not_installed'].includes(st) ? 'info' : 'error');
      toast(kind, `${name}: ${STATE_LABEL[st] || st || 'sem resposta'} — ${r?.detail || r?.note || ''}`);
    } catch (err) { toast('error', `${name}: ${safeErr(err)}`); }
    await refreshKeyStatus();
    if (rerender) rerender();
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
    const st = stateOf(item);
    const isDetected = item.detected;

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
            <span class="chip ${STATE_CHIP[st] || 'chip-offline'}" data-bind="connection-state" data-state="${st}" title="${esc(item.state_detail || '')}">
              <span class="dot ${st === 'connected' ? 'dot-success' : 'dot-neutral'}"></span>
              ${STATE_LABEL[st] || st}
            </span>
          </div>
        </div>

        <div class="connection-chips-row">
          <span class="chip ${isDetected ? 'chip-configured' : 'chip-offline'}">${isDetected ? t.detected : t.notDetected}</span>
        </div>
        ${item.state_detail ? `<p class="input-hint" data-bind="connection-detail">${esc(item.state_detail)}</p>` : ''}

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
      handleKeyAction(action, target, { toast, rerender: () => { paintKeepingKeys(root, render()); } });
    } else if (action === 'view-snippet') {
      snippetOf(itemId).then((r) => {
        window.dispatchEvent(new CustomEvent('anamnesia:modal:snippet', { detail: { title: found?.name || itemId, snippet: r.content || r.note || '' } }));
      }).catch(() => {
        if (found) window.dispatchEvent(new CustomEvent('anamnesia:modal:snippet', { detail: { title: found.name, snippet: found.snippet || 'Sem snippet disponível para esta conexão.' } }));
      });
    } else if (action === 'retry-connections') {
      currentState = 'loaded';
      paintKeepingKeys(root, render());
    }
  };

  root.addEventListener('click', handleClick);
  const stopHealth = mountHealth(root);
  refreshKeyStatus().then(() => { if (root.isConnected) paintKeepingKeys(root, render()); });
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
  if (root) paintKeepingKeys(root, render());
}
