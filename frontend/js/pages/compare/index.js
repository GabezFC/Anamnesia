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

import * as overviewTab from './overview.js';
import * as modelsTab from './models.js';
import * as pipelineTab from './pipeline.js';
import * as tokensTab from './tokens.js';
import * as latencyTab from './latency.js';
import * as modelCostTab from './model-cost.js';
import * as resultsTab from './results.js';
import * as historyTab from './history.js';

const TABS = {
  overview: { id: 'overview', label: I18N.lab.overview, module: overviewTab },
  models: { id: 'models', label: I18N.lab.models, module: modelsTab },
  pipeline: { id: 'pipeline', label: I18N.lab.pipeline, module: pipelineTab },
  tokens: { id: 'tokens', label: I18N.lab.tokens, module: tokensTab },
  latency: { id: 'latency', label: I18N.lab.latency, module: latencyTab },
  'model-cost': { id: 'model-cost', label: I18N.lab.modelCost, module: modelCostTab },
  results: { id: 'results', label: I18N.lab.results, module: resultsTab },
  history: { id: 'history', label: I18N.lab.history, module: historyTab }
};

let currentSubTab = 'overview';
let activeSubModule = null;

export function render(subRoute = 'overview') {
  currentSubTab = TABS[subRoute] ? subRoute : 'overview';
  const currentTabObj = TABS[currentSubTab];
  activeSubModule = currentTabObj.module;
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
          <span class="tabular">Ambiente de Teste Isolado</span>
          <span aria-hidden="true">·</span>
          <span>Sessão de Auditoria Local</span>
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
        <nav class="lab-nav-bar" role="tablist" aria-label="Abas do Laboratório de Comparação">
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
          ${activeSubModule ? activeSubModule.render() : ''}
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  // Mount the sub-tab module inside the container
  const container = root.querySelector('[data-bind="lab-tab-content"]');
  if (container && activeSubModule && activeSubModule.mount) {
    activeSubModule.mount(container);
  }

  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

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
