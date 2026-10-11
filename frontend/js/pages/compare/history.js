/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: HISTÓRICO DE RUNS (#/compare/history)
 * Séries temporais ao longo de 30 runs com gráficos SVG LineChart do ChartKit.
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';
import { createLineChart } from '../../charts/chart-kit.js';

let visibleHistoryCount = 10;
let chartInstance = null;

export function render() {
  const history = mockBenchmark.history_runs;
  const visibleRuns = [...history].reverse().slice(0, visibleHistoryCount);

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Histórico Longitudinal de Execuções</h2>
          <p class="lab-section-desc">Série temporal de 30 benchmarks comparativos em ambientes controlados.</p>
        </div>
      </div>

      <!-- Gráfico de Linhas ChartKit: Baseline vs Graphify vs JEV ao longo dos 30 runs -->
      <div class="card" style="padding: var(--space-5);">
        <div class="card-header" style="margin-bottom: var(--space-4);">
          <div>
            <h3 class="card-title">Evolução do Score de Qualidade (%)</h3>
            <p class="card-subtitle">
              Série longitudinal dos 30 testes com hover interativo e grade pontilhada.
            </p>
          </div>
          <span class="badge-origin badge-origin-measured">30 runs consolidados</span>
        </div>

        <div id="history-line-chart-mount" style="min-height: 250px; width: 100%;"></div>
      </div>

      <!-- Tabela com listagem dos runs -->
      <div class="card" style="margin-top: var(--space-4);">
        <div class="card-header">
          <h3 class="card-title">Registros Recentes de Execução</h3>
          <span class="section-count tabular">Exibindo ${visibleRuns.length} de ${history.length} runs</span>
        </div>

        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Run #</th>
                <th>Data</th>
                <th class="num-col">Baseline</th>
                <th class="num-col">Graphify</th>
                <th class="num-col">Graphify + JEV</th>
                <th class="num-col">Tokens Poupados</th>
                <th class="num-col">Latência p95</th>
              </tr>
            </thead>
            <tbody>
              ${visibleRuns.map(r => `
                <tr>
                  <td class="font-mono tabular" style="font-weight: 600;">#${String(r.run).padStart(2, '0')}</td>
                  <td class="font-mono tabular" style="font-size: 11px; color: var(--text-tertiary);">${r.timestamp}</td>
                  <td class="num-col font-mono" style="color: var(--text-tertiary);">${r.baseline_score.toFixed(1)}%</td>
                  <td class="num-col font-mono" style="color: var(--primary);">${r.graphify_score.toFixed(1)}%</td>
                  <td class="num-col font-mono" style="color: var(--lab-accent); font-weight: 600;">${r.jev_score.toFixed(1)}%</td>
                  <td class="num-col font-mono" style="color: var(--success);">${r.tokens_saved_pct}%</td>
                  <td class="num-col font-mono">${r.latency_p95_ms} ms</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>

        ${visibleHistoryCount < history.length ? `
          <div style="display: flex; justify-content: center; margin-top: var(--space-4);">
            <button class="btn btn-secondary btn-sm" data-action="load-more-history">Carregar mais runs</button>
          </div>
        ` : ''}
      </div>
    </div>
  `;
}

export function mount(root) {
  cleanupChart();

  const mountElem = root.querySelector('#history-line-chart-mount');
  if (mountElem) {
    const runs = mockBenchmark.history_runs;
    const chartData = runs.map(r => ({
      run: `R${r.run}`,
      baseline: r.baseline_score,
      graphify: r.graphify_score,
      jev: r.jev_score
    }));

    chartInstance = createLineChart(mountElem, {
      data: chartData,
      xKey: 'run',
      series: [
        { key: 'baseline', label: 'Baseline', color: 'var(--chart-8)', fill: false },
        { key: 'graphify', label: 'Graphify', color: 'var(--chart-1)', fill: false },
        { key: 'jev', label: 'Graphify + JEV', color: 'var(--chart-2)', fill: true }
      ],
      yFormatter: (v) => `${v.toFixed(0)}%`,
      xFormatter: (v) => v,
      height: 250,
      marginLeft: 50
    });
  }

  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    if (target.getAttribute('data-action') === 'load-more-history') {
      visibleHistoryCount = Math.min(visibleHistoryCount + 10, mockBenchmark.history_runs.length);
      root.innerHTML = render();
      mount(root);
    }
  };

  root.addEventListener('click', handleClick);
  root._historyCleanup = () => {
    root.removeEventListener('click', handleClick);
    cleanupChart();
  };
}

function cleanupChart() {
  if (chartInstance && chartInstance.destroy) {
    chartInstance.destroy();
    chartInstance = null;
  }
}

export function unmount(root) {
  cleanupChart();
  if (root && root._historyCleanup) {
    root._historyCleanup();
    delete root._historyCleanup;
  }
}
