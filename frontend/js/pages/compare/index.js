/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB SHELL & ROUTER (#/compare)
 * Casca isolada do laboratório com navegação própria, cabeçalho de runs e botão de retorno.
 */

import { icon } from '../../icons.js';
import { estimateBenchmark } from '../../live.js';
import { I18N } from '../../i18n.js';
import { mockBenchmark } from '../../mock-data.js';

import { skeletonKpis, skeletonCard, loadingBlock } from '../../components/skeleton.js';
import { emptyState } from '../../components/empty-state.js';

// Abas carregadas sob demanda (dynamic import + cache): nada de aba é baixado/avaliado até ser aberta.
// `label` é getter para acompanhar a troca de idioma.
const TABS = {
  overview: { id: 'overview', get label() { return I18N.lab.overview; }, load: () => import('./overview.js') },
  models: { id: 'models', get label() { return I18N.lab.models; }, load: () => import('./models.js') },
  pipeline: { id: 'pipeline', get label() { return I18N.lab.pipeline; }, load: () => import('./pipeline.js') },
  tokens: { id: 'tokens', get label() { return I18N.lab.tokens; }, load: () => import('./tokens.js') },
  latency: { id: 'latency', get label() { return I18N.lab.latency; }, load: () => import('./latency.js') },
  'model-cost': { id: 'model-cost', get label() { return I18N.lab.modelCost; }, load: () => import('./model-cost.js') },
  results: { id: 'results', get label() { return I18N.lab.results; }, load: () => import('./results.js') },
  history: { id: 'history', get label() { return I18N.lab.history; }, load: () => import('./history.js') },
};

const tabCache = new Map(); // id -> módulo já importado
let loadToken = 0;

/** Importa a aba uma única vez (cache). */
export function loadTab(id) {
  const tab = TABS[id] || TABS.overview;
  if (tabCache.has(tab.id)) return Promise.resolve(tabCache.get(tab.id));
  return tab.load().then((m) => { tabCache.set(tab.id, m); return m; });
}

/** Ids de aba já carregados (diagnóstico/testes). */
export function loadedTabs() { return [...tabCache.keys()]; }

let currentSubTab = 'overview';
let activeSubModule = null;

export function render(subRoute = 'overview', opts = {}) {
  currentSubTab = TABS[subRoute] ? subRoute : 'overview';
  const currentTabObj = TABS[currentSubTab];
  activeSubModule = tabCache.get(currentTabObj.id) || null;
  const meta = mockBenchmark.meta;

  return `
    <div class="lab-shell" data-bind="lab-shell">
      <!-- Faixa Superior Violeta com Retorno ao Anamnésia -->
      <div class="lab-banner">
        <div class="lab-banner-left">
          <a href="#/workspace" class="lab-back-btn" data-action="back-to-app" aria-label="${I18N.app.backToApp}">
            ${icon('arrowLeft', '', 14)}
            <span>${I18N.app.backToApp}</span>
          </a>
          <span style="color: var(--border-strong);" aria-hidden="true">|</span>
          <div class="lab-title-badge">
            ${icon('scale', '', 15)}
            <span>${I18N.app.labBadge}</span>
          </div>
        </div>

        <div class="lab-banner-right">
          <span class="tabular">${I18N.app.labIsolated}</span>
          <span aria-hidden="true">·</span>
          <span>${I18N.app.labAudit}</span>
          ${opts.langSwitch || ''}
        </div>
      </div>

      <!-- Cabeçalho do Laboratório: Total de runs, dataset e Nova Comparação -->
      <div class="lab-header">
        <div class="lab-header-left">
          <div class="lab-dataset-picker">
            <span style="font-weight: 500;">Dataset:</span>
            <select class="select-control" data-action="change-dataset">
              <option selected>${meta.dataset_name}</option>
              <option>HumanEval-X / 164 prompts</option>
              <option>RepoQA-Python / 30 monorepos</option>
            </select>
          </div>

          <div class="status-indicator">
            <span class="dot dot-success"></span>
            <span class="tabular">${meta.total_runs} runs</span>
            <span aria-hidden="true">·</span>
            <span>Último: ${meta.last_benchmark}</span>
          </div>
        </div>

        <div class="lab-header-right">
          <button class="btn btn-lab btn-sm" data-action="run-new-benchmark">
            ${icon('play', '', 12)}
            <span>${I18N.app.runNewComparison}</span>
          </button>
        </div>
      </div>

      <!-- Barra de Abas Internas do Laboratório -->
      <div class="lab-main">
        <nav class="lab-nav-bar" role="tablist" aria-label="${I18N.app.labTabsAria}">
          ${Object.values(TABS).map(tab => {
            const isActive = tab.id === currentSubTab;
            return `
              <a 
                href="#/compare/${tab.id}" 
                class="lab-nav-tab ${isActive ? 'is-active' : ''}" 
                role="tab" 
                aria-selected="${isActive}"
                data-action="switch-lab-tab"
                data-subtab="${tab.id}"
              >
                ${tab.label}
              </a>
            `;
          }).join('')}
        </nav>

        <!-- Conteúdo da Sub-Aba -->
        <div class="lab-tab-content" data-bind="lab-tab-content">
          ${activeSubModule ? activeSubModule.render() : loadingBlock(skeletonKpis(4) + skeletonCard({ lines: 5 }), I18N.app.loading)}
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  // Mount the sub-tab module inside the container
  const container = root.querySelector('[data-bind="lab-tab-content"]');
  const tabId = currentSubTab;
  const token = ++loadToken;
  // Aba já em cache: render() já devolveu o conteúdo, só montar. Senão: importar sob demanda.
  if (container && activeSubModule) {
    if (activeSubModule.mount) activeSubModule.mount(container);
  } else if (container) {
    loadTab(tabId).then((mod) => {
      if (token !== loadToken || !container.isConnected) return; // usuário trocou de aba/saiu
      activeSubModule = mod;
      container.innerHTML = mod.render();
      if (mod.mount) mod.mount(container);
    }).catch((err) => {
      if (token !== loadToken || !container.isConnected) return;
      container.innerHTML = emptyState({ title: I18N.app.labTabLoadFail, description: err?.message || String(err), variant: 'error', action: { label: I18N.app.errorRetry, action: 'retry-lab-tab' } });
    });
  }

  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

    if (action === 'retry-lab-tab') {
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      return;
    }

    if (action === 'run-new-benchmark') {
      const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
      estimateBenchmark().then((r) => {
        const n = r?.questions ?? r?.n_questions ?? r?.total_runs ?? '';
        toast('info', `Estimativa calculada (nenhum token gasto)${n !== '' ? `: ${n} consultas` : ''}. Para executar de verdade use: python -m memory_gateway benchmark.`);
      }).catch((err) => toast('error', `Não foi possível estimar: ${err.message || err}`));
    }
  };

  root.addEventListener('click', handleClick);
  root._labCleanup = () => {
    root.removeEventListener('click', handleClick);
    loadToken += 1; // invalida import em andamento
    if (activeSubModule && activeSubModule.unmount && container) {
      activeSubModule.unmount(container);
    }
  };
}

export function unmount(root) {
  if (root && root._labCleanup) {
    root._labCleanup();
    delete root._labCleanup;
  }
}
