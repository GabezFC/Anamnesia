/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA CONFIGURATION PAGE (#/config)
 * Configurações de Subagentes, Gateway de Memória e Visão de Configuração Ativa.
 * Produto puro, zero benchmarks.
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc } from '../format.js';
import { mockPresets } from '../mock-data.js';
import { gatewayState, saveGatewayConfig, getSavedPreset, savePreset } from '../live.js';

let activeTab = 'subagents'; // 'subagents' | 'gateway' | 'active'
let selectedPresetId = 'equilibrado';
let isAdvancedOpen = false;
let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'

// Config state
const gatewayConfig = gatewayState;
const savedPreset = getSavedPreset();
if (savedPreset) selectedPresetId = savedPreset;

export function render() {
  const t = I18N.config;

  if (currentState === 'loading') {
    return `
      <div class="config-page">
        <div class="skeleton" style="height: 38px; width: 320px; margin-bottom: 24px;"></div>
        <div class="skeleton" style="height: 280px;"></div>
      </div>
    `;
  }

  if (currentState === 'error') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap" style="color: var(--danger);">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Falha ao ler o arquivo anamnesia.config.json.</p>
        <button class="btn btn-secondary" data-action="retry-config">${I18N.app.errorRetry}</button>
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

  return `
    <div class="config-page" data-bind="config-page">
      ${backendNotice}

      <div class="connections-header-bar">
        <div>
          <h1 style="font-size: var(--text-2xl); font-weight: var(--font-semibold);">${I18N.nav.config}</h1>
          <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
            Ajuste políticas de orquestração de subagentes e parâmetros de injeção de memória.
          </p>
        </div>
      </div>

      <!-- Abas internas: Subagentes | Gateway | Configuração Ativa -->
      <nav class="config-tabs-nav" role="tablist">
        <button class="config-tab-item ${activeTab === 'subagents' ? 'is-active' : ''}" role="tab" aria-selected="${activeTab === 'subagents'}" data-action="switch-config-tab" data-tab="subagents">
          ${t.tabSubagents}
        </button>
        <button class="config-tab-item ${activeTab === 'gateway' ? 'is-active' : ''}" role="tab" aria-selected="${activeTab === 'gateway'}" data-action="switch-config-tab" data-tab="gateway">
          ${t.tabGateway}
        </button>
        <button class="config-tab-item ${activeTab === 'active' ? 'is-active' : ''}" role="tab" aria-selected="${activeTab === 'active'}" data-action="switch-config-tab" data-tab="active">
          ${t.tabActive}
        </button>
      </nav>

      <!-- CONTEÚDO DA ABA SELECIONADA -->
      ${activeTab === 'subagents' ? renderSubagentsTab(t) : ''}
      ${activeTab === 'gateway' ? renderGatewayTab(t) : ''}
      ${activeTab === 'active' ? renderActiveConfigTab(t) : ''}
    </div>
  `;
}

function renderSubagentsTab(t) {
  return `
    <div style="display: flex; flex-direction: column; gap: var(--space-6);">
      <div>
        <h2 style="font-size: var(--text-md); font-weight: var(--font-semibold);">${t.presetsTitle}</h2>
        <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
          Selecione a política de alocação de modelos por papel no pipeline do agente.
        </p>
      </div>

      <!-- Cards Grandes de Seleção de Predefinição (Radio) -->
      <div class="presets-grid" role="radiogroup">
        ${mockPresets.map(preset => {
          const isSelected = preset.id === selectedPresetId;
          return `
            <div 
              class="preset-card ${isSelected ? 'is-selected' : ''}" 
              role="radio" 
              aria-checked="${isSelected}" 
              tabindex="0"
              data-action="select-preset" 
              data-preset-id="${preset.id}"
            >
              <div class="preset-card-header">
                <div>
                  <div class="preset-name">${preset.name}</div>
                  <div style="font-size: 11px; color: var(--text-tertiary); margin-top: 2px;">${preset.description}</div>
                </div>
                <span class="preset-tag">${preset.tag}</span>
              </div>

              <!-- Matriz Visual de Papéis e Classes -->
              <div class="preset-roles-matrix">
                ${Object.entries(preset.roles).map(([roleKey, role]) => `
                  <div class="preset-role-row">
                    <span class="role-title">${role.title}</span>
                    <span class="role-class-badge ${role.className}">${role.label}</span>
                  </div>
                `).join('')}
              </div>

              <!-- Linha de Custo Estimado (nunca afirmar mais barato sem dado) -->
              <div class="preset-cost-line">
                <span class="dot dot-neutral"></span>
                <span>${t.estimatedCostNoData}</span>
              </div>
            </div>
          `;
        }).join('')}
      </div>

      <!-- Seção Avançado (Recolhível) -->
      <div class="card" style="margin-top: var(--space-2);">
        <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" data-action="toggle-advanced">
          <div>
            <div style="font-size: var(--text-sm); font-weight: var(--font-medium);">${t.advancedToggle}</div>
            <div style="font-size: var(--text-xs); color: var(--text-tertiary);">Substituições manuais de temperatura, fallback e timeouts</div>
          </div>
          <button class="btn btn-ghost btn-icon">${icon(isAdvancedOpen ? 'chevronDown' : 'chevronRight', '', 16)}</button>
        </div>

        ${isAdvancedOpen ? `
          <div style="margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--border-subtle); display: flex; flex-direction: column; gap: var(--space-3);">
            <div class="gateway-toggle-row">
              <div class="gateway-toggle-info">
                <span class="gateway-toggle-title">Fallback dinâmico de modelo</span>
                <span class="gateway-toggle-desc">Chama automaticamente modelo secundário caso ocorra rate limit (429)</span>
              </div>
              <button class="toggle-switch" role="switch" aria-checked="true" data-action="toggle-switch-dummy">
                <span class="toggle-switch-thumb"></span>
              </button>
            </div>
            <div class="gateway-toggle-row">
              <div class="gateway-toggle-info">
                <span class="gateway-toggle-title">Temperatura determinística em tarefas de refatoração</span>
                <span class="gateway-toggle-desc">Força temperatura 0.0 em implementadores para previsibilidade de AST</span>
              </div>
              <button class="toggle-switch" role="switch" aria-checked="true" data-action="toggle-switch-dummy">
                <span class="toggle-switch-thumb"></span>
              </button>
            </div>
          </div>
        ` : ''}
      </div>
    </div>
  `;
}

function renderGatewayTab(t) {
  return `
    <div class="gateway-form-card">
      <div>
        <h2 style="font-size: var(--text-md); font-weight: var(--font-semibold);">Setup do Memory Gateway</h2>
        <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
          Configure a ponte local entre os agentes e o vault de persistência de memória.
        </p>
      </div>

      <div class="input-group">
        <label class="input-label">${t.gatewayVaultLabel}</label>
        <div class="input-control">
          <input type="text" value="${esc(gatewayConfig.vaultPath)}" data-bind="vault-path-input" />
        </div>
      </div>

      <div class="input-group">
        <label class="input-label">${t.gatewayModelKeyLabel}</label>
        <div class="input-control">
          <input type="password" value="${esc(gatewayConfig.modelKey)}" readonly placeholder="nenhuma chave salva" />
        </div>
      </div>

      <!-- Toggles dos Estágios -->
      <div class="gateway-toggle-row">
        <div class="gateway-toggle-info">
          <span class="gateway-toggle-title">${t.gatewayVerdictJev}</span>
          <span class="gateway-toggle-desc">${t.gatewayVerdictDesc}</span>
        </div>
        <button class="toggle-switch" role="switch" aria-checked="${gatewayConfig.enableJev}" data-action="toggle-jev">
          <span class="toggle-switch-thumb"></span>
        </button>
      </div>

      <div class="gateway-toggle-row">
        <div class="gateway-toggle-info">
          <span class="gateway-toggle-title">${t.gatewayPreFilter}</span>
          <span class="gateway-toggle-desc">${t.gatewayPreFilterDesc}</span>
        </div>
        <button class="toggle-switch" role="switch" aria-checked="${gatewayConfig.enablePrefilter}" data-action="toggle-prefilter">
          <span class="toggle-switch-thumb"></span>
        </button>
      </div>

      <div class="gateway-toggle-row">
        <div class="gateway-toggle-info">
          <span class="gateway-toggle-title">Cache semântico de embeddings</span>
          <span class="gateway-toggle-desc">Evita recalcular representações de trechos já indexados no banco local</span>
        </div>
        <button class="toggle-switch" role="switch" aria-checked="${gatewayConfig.enableSemanticCache}" data-action="toggle-cache">
          <span class="toggle-switch-thumb"></span>
        </button>
      </div>

      <div style="display: flex; justify-content: flex-end; margin-top: var(--space-2);">
        <button class="btn btn-primary" data-action="save-gateway-config">${I18N.app.save}</button>
      </div>
    </div>
  `;
}

function renderActiveConfigTab(t) {
  const currentPreset = mockPresets.find(p => p.id === selectedPresetId) || mockPresets[1];

  return `
    <div style="display: flex; flex-direction: column; gap: var(--space-4);">
      <div>
        <h2 style="font-size: var(--text-md); font-weight: var(--font-semibold);">Visão de Configuração Ativa</h2>
        <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
          Valores em execução carregados no runtime do daemon local (somente leitura).
        </p>
      </div>

      <div class="readonly-kv-grid">
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Predefinição ativa</span>
          <span class="readonly-kv-value">${currentPreset.name}</span>
        </div>
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Veredito JEV</span>
          <span class="readonly-kv-value" style="color: ${gatewayConfig.enableJev ? 'var(--success)' : 'var(--text-tertiary)'};">
            ${gatewayConfig.enableJev ? 'Habilitado' : 'Desabilitado'}
          </span>
        </div>
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Pré-filtro semântico</span>
          <span class="readonly-kv-value" style="color: ${gatewayConfig.enablePrefilter ? 'var(--success)' : 'var(--text-tertiary)'};">
            ${gatewayConfig.enablePrefilter ? 'Habilitado' : 'Desabilitado'}
          </span>
        </div>
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Limiar de poda</span>
          <span class="readonly-kv-value tabular">${gatewayConfig.pruneThreshold}</span>
        </div>
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Vault Ativo</span>
          <span class="readonly-kv-value" style="font-family: var(--font-mono); font-size: 12px;">${esc(gatewayConfig.vaultPath)}</span>
        </div>
        <div class="readonly-kv-item">
          <span class="readonly-kv-label">Status do Daemon</span>
          <span class="readonly-kv-value" style="color: var(--success); display: flex; align-items: center; gap: 6px;">
            <span class="dot dot-success"></span> Ativo (PID 14209)
          </span>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

    if (action === 'switch-config-tab') {
      activeTab = target.getAttribute('data-tab');
      root.innerHTML = render();
    } else if (action === 'select-preset') {
      selectedPresetId = target.getAttribute('data-preset-id');
      savePreset(selectedPresetId);
      root.innerHTML = render();
      window.dispatchEvent(new CustomEvent('anamnesia:toast', {
        detail: { type: 'info', message: `Predefinição alterada para ${selectedPresetId}` }
      }));
    } else if (action === 'toggle-advanced') {
      isAdvancedOpen = !isAdvancedOpen;
      root.innerHTML = render();
    } else if (action === 'toggle-jev') {
      gatewayConfig.enableJev = !gatewayConfig.enableJev;
      root.innerHTML = render();
    } else if (action === 'toggle-prefilter') {
      gatewayConfig.enablePrefilter = !gatewayConfig.enablePrefilter;
      root.innerHTML = render();
    } else if (action === 'toggle-cache') {
      gatewayConfig.enableSemanticCache = !gatewayConfig.enableSemanticCache;
      root.innerHTML = render();
    } else if (action === 'save-gateway-config') {
      const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
      const vp = root.querySelector('[data-bind="vault-path-input"]')?.value?.trim() || gatewayConfig.vaultPath;
      saveGatewayConfig({ vaultPath: vp, enableJev: gatewayConfig.enableJev, enablePrefilter: gatewayConfig.enablePrefilter, enableSemanticCache: gatewayConfig.enableSemanticCache })
        .then(() => toast('success', 'Veredito (JEV) e caminho do vault salvos no gateway; pré-filtro e cache ficam apenas neste navegador.'))
        .catch((err) => toast('error', `Não foi possível salvar: ${err.message || err}`));
    } else if (action === 'retry-config') {
      currentState = 'loaded';
      root.innerHTML = render();
    }
  };

  root.addEventListener('click', handleClick);
  root._configCleanup = () => {
    root.removeEventListener('click', handleClick);
  };
}

export function unmount(root) {
  if (root && root._configCleanup) {
    root._configCleanup();
    delete root._configCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) root.innerHTML = render();
}
