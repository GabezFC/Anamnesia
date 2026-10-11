/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: FLUXO DE PIPELINE (#/compare/pipeline)
 * Fluxo visual interativo: Query → Retrieval → Graphify → Pré-filtro → JEV → Filtro → Contexto → Modelo.
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';

let selectedStageId = 'stage-jev';

export function render() {
  const stages = mockBenchmark.pipeline_flow_stages;
  const currentStage = stages.find(s => s.id === selectedStageId) || stages[4];

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Diagrama de Fluxo do Pipeline de Memória</h2>
          <p class="lab-section-desc">Decomposição das 8 etapas de processamento do prompt antes da inferência.</p>
        </div>
      </div>

      <!-- Fluxo horizontal com nós conectores -->
      <div class="pipeline-flow-board">
        ${stages.map((stage, idx) => {
          const isSelected = stage.id === selectedStageId;
          const isLast = idx === stages.length - 1;
          return `
            <div 
              class="pipeline-node ${isSelected ? 'is-active-stage' : ''}" 
              data-action="inspect-stage" 
              data-stage-id="${stage.id}"
              tabindex="0"
              role="button"
              aria-label="Inspecionar etapa ${stage.name}"
            >
              <span class="node-step-num">${stage.step}</span>
              <span class="node-title">${stage.name}</span>
              <span style="font-size: 10px; color: var(--text-tertiary);">${stage.type}</span>
              <span class="node-metric">${stage.avg_latency_ms} ms</span>
            </div>
            ${!isLast ? `
              <div class="pipeline-arrow" aria-hidden="true">
                ${icon('chevronRight', '', 14)}
              </div>
            ` : ''}
          `;
        }).join('')}
      </div>

      <!-- Inspetor da Etapa Selecionada -->
      <div class="stage-inspector-card">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <div>
            <span class="badge-origin badge-origin-measured" style="margin-bottom: 6px;">Etapa ${currentStage.step} · ${currentStage.type}</span>
            <h3 style="font-size: var(--text-lg); font-weight: var(--font-semibold); color: var(--text-primary);">${currentStage.name}</h3>
          </div>
          <span class="kpi-value tabular" style="color: var(--lab-accent); font-size: 20px;">${currentStage.avg_latency_ms} ms médio</span>
        </div>

        <p style="font-size: var(--text-sm); color: var(--text-secondary); line-height: 1.6;">
          ${currentStage.desc}. Esta fase assegura a consistência referencial e a eliminação de ruídos no contexto do agente.
        </p>

        <div class="readonly-kv-grid" style="margin-top: var(--space-2);">
          <div class="readonly-kv-item">
            <span class="readonly-kv-label">Tipo de processamento</span>
            <span class="readonly-kv-value">${currentStage.type}</span>
          </div>
          <div class="readonly-kv-item">
            <span class="readonly-kv-label">Desvio padrão de latência</span>
            <span class="readonly-kv-value tabular">± 12.4 ms</span>
          </div>
          <div class="readonly-kv-item">
            <span class="readonly-kv-label">Taxa de filtragem média</span>
            <span class="readonly-kv-value tabular">${currentStage.id === 'stage-jev' ? '46.2% descartados' : 'Nominal'}</span>
          </div>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  const handleClick = (e) => {
    const target = e.target.closest('[data-action="inspect-stage"]');
    if (target) {
      selectedStageId = target.getAttribute('data-stage-id');
      root.innerHTML = render();
    }
  };

  root.addEventListener('click', handleClick);
  root._pipelineCleanup = () => {
    root.removeEventListener('click', handleClick);
  };
}

export function unmount(root) {
  if (root && root._pipelineCleanup) {
    root._pipelineCleanup();
    delete root._pipelineCleanup;
  }
}
