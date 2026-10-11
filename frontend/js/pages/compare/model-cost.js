/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: CUSTO POR MODELO (#/compare/model-cost)
 * Custo do consumidor, do juiz, por query e normalizado por 1K tokens.
 * Gráfico SVG BarChart agrupado com escala e eixos reais (ChartKit).
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';
import { createBarChart } from '../../charts/chart-kit.js';

let chartInstance = null;

export function render() {
  const pipelines = mockBenchmark.pipelines;

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Análise Financeira por Pipeline & Modelo</h2>
          <p class="lab-section-desc">Detalhamento dos custos unitários por inferência do agente e do juiz avaliador.</p>
        </div>
      </div>

      <!-- Gráfico de Custos Agrupados (ChartKit BarChart) -->
      <div class="card" style="padding: var(--space-5);">
        <div class="card-header" style="margin-bottom: var(--space-4);">
          <div>
            <h3 class="card-title">Custo Médio por Query (US$)</h3>
            <p class="card-subtitle">Comparativo direto de custos por chamada entre o modelo do agente e o juiz JEV.</p>
          </div>
        </div>

        <div id="model-cost-barchart-mount" style="min-height: 250px; width: 100%;"></div>
      </div>

      <!-- Tabela de Custos Unitários -->
      <div class="card" style="margin-top: var(--space-4);">
        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Pipeline</th>
                <th class="num-col">Custo Consumidor / Query</th>
                <th class="num-col">Custo Juiz / Query</th>
                <th class="num-col">Custo Total / Query</th>
                <th class="num-col">Tarifa / 1K Tokens</th>
                <th>Veredito Econômico</th>
              </tr>
            </thead>
            <tbody>
              ${pipelines.map(p => `
                <tr>
                  <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${p.name}</div>
                    <div style="font-size: 11px; color: var(--text-tertiary);">${p.description}</div>
                  </td>
                  <td class="num-col tabular font-mono">US$ ${p.consumer_cost_per_query.toFixed(4)}</td>
                  <td class="num-col tabular font-mono" style="color: ${p.judge_cost_per_query > 0 ? 'var(--warning)' : 'var(--text-tertiary)'};">
                    ${p.judge_cost_per_query > 0 ? `US$ ${p.judge_cost_per_query.toFixed(4)}` : 'US$ 0,0000'}
                  </td>
                  <td class="num-col tabular font-mono" style="font-size: 14px; font-weight: 700; color: var(--text-primary);">
                    US$ ${p.total_cost_per_query.toFixed(4)}
                  </td>
                  <td class="num-col tabular font-mono">US$ ${p.cost_per_1k_tokens.toFixed(4)}</td>
                  <td>
                    ${p.total_cost_per_query < 0.025 ? `
                      <span class="badge-origin badge-origin-measured" style="color: var(--success); border-color: var(--success-border);">
                        ${icon('check', '', 10)} Alta Economia
                      </span>
                    ` : `
                      <span class="badge-origin badge-origin-unavailable">Custo Padrão</span>
                    `}
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  cleanupChart();

  const mountElem = root.querySelector('#model-cost-barchart-mount');
  if (mountElem) {
    const pipelines = mockBenchmark.pipelines;
    const categories = pipelines.map(p => p.name);

    chartInstance = createBarChart(mountElem, {
      categories,
      series: [
        { label: 'Consumidor', color: 'var(--chart-1)', values: pipelines.map(p => p.consumer_cost_per_query) },
        { label: 'Juiz JEV', color: 'var(--chart-4)', values: pipelines.map(p => p.judge_cost_per_query) },
        { label: 'Custo Total', color: 'var(--chart-7)', values: pipelines.map(p => p.total_cost_per_query) }
      ],
      yFormatter: (v) => `US$ ${v.toFixed(3)}`,
      height: 250
    });
  }
}

function cleanupChart() {
  if (chartInstance && chartInstance.destroy) {
    chartInstance.destroy();
    chartInstance = null;
  }
}

export function unmount(root) {
  cleanupChart();
}
