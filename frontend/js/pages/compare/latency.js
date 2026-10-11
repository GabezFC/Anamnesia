/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: DECOMPOSIÇÃO DE LATÊNCIA (#/compare/latency)
 * Decomposição em milissegundos por estágio de pipeline com ChartKit SVG StackedBarChart.
 * Escala real e eixos com nice ticks, zero barras fixas em div.
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';
import { createStackedBarChart } from '../../charts/chart-kit.js';

let chartInstance = null;

export function render() {
  const pipelines = mockBenchmark.pipelines;

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Decomposição de Latência por Estágio</h2>
          <p class="lab-section-desc">Mapeamento em milissegundos (ms) com escala real para cada fase do ciclo de atendimento.</p>
        </div>
      </div>

      <!-- Gráfico de Decomposição StackedBarChart (ChartKit) -->
      <div class="card" style="padding: var(--space-5);">
        <div class="card-header" style="margin-bottom: var(--space-4);">
          <div>
            <h3 class="card-title">Tempo Total de Resposta por Pipeline</h3>
            <p class="card-subtitle">Azul: Query · Céu: Retrieval · Violeta: Graphify · Âmbar: JEV · Cinza: Inferência</p>
          </div>
        </div>

        <div id="latency-stacked-chart-mount" style="min-height: 250px; width: 100%;"></div>
      </div>

      <!-- Tabela analítica de latência por estágio -->
      <div class="card" style="margin-top: var(--space-4);">
        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Pipeline</th>
                <th class="num-col">Query</th>
                <th class="num-col">Retrieval</th>
                <th class="num-col">Graphify</th>
                <th class="num-col">JEV Veredito</th>
                <th class="num-col">Inferência Agente</th>
                <th class="num-col">Total</th>
              </tr>
            </thead>
            <tbody>
              ${pipelines.map(p => `
                <tr>
                  <td style="font-weight: 600;">${p.name}</td>
                  <td class="num-col tabular font-mono">${p.stages_latency.query} ms</td>
                  <td class="num-col tabular font-mono">${p.stages_latency.retrieval} ms</td>
                  <td class="num-col tabular font-mono">${p.stages_latency.graphify} ms</td>
                  <td class="num-col tabular font-mono">${p.stages_latency.jev} ms</td>
                  <td class="num-col tabular font-mono">${p.stages_latency.model} ms</td>
                  <td class="num-col tabular font-mono" style="font-weight: 700; color: var(--text-primary);">${p.total_latency_ms} ms</td>
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

  const mountElem = root.querySelector('#latency-stacked-chart-mount');
  if (mountElem) {
    const pipelines = mockBenchmark.pipelines;
    const categories = pipelines.map(p => p.name);

    chartInstance = createStackedBarChart(mountElem, {
      categories,
      series: [
        { label: 'Query', color: 'var(--chart-1)', values: pipelines.map(p => p.stages_latency.query) },
        { label: 'Retrieval', color: 'var(--chart-5)', values: pipelines.map(p => p.stages_latency.retrieval) },
        { label: 'Graphify', color: 'var(--chart-2)', values: pipelines.map(p => p.stages_latency.graphify) },
        { label: 'JEV', color: 'var(--chart-4)', values: pipelines.map(p => p.stages_latency.jev) },
        { label: 'Modelo', color: 'var(--chart-8)', values: pipelines.map(p => p.stages_latency.model) }
      ],
      yFormatter: (v) => `${Math.round(v)} ms`,
      horizontal: true,
      height: 250,
      marginLeft: 170
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
