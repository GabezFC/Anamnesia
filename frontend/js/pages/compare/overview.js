/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: VISÃO GERAL (#/compare/overview)
 * Resumo sintético das execuções de benchmark e ganhos globais do pipeline.
 * Todas as porcentagens e métricas calculadas estritamente em tempo de execução via mock-data.
 */

import { icon } from '../../icons.js';
import { I18N } from '../../i18n.js';
import { mockBenchmark } from '../../mock-data.js';
import { createBarChart } from '../../charts/chart-kit.js';

let chartInstance = null;

export function render() {
  const meta = mockBenchmark.meta;
  const pipelines = mockBenchmark.pipelines;
  const baseline = pipelines.find(p => p.id === 'baseline') || pipelines[0];
  const bestPipeline = pipelines.find(p => p.id === 'graphify_jev_opt') || pipelines[pipelines.length - 1];

  // Cálculos dinâmicos
  const pct = (a, b) => (b > 0 && Number.isFinite(a) ? (((a - b) / b) * 100).toFixed(1) : null);
  const qualityDiffPct = pct(bestPipeline.quality_score, baseline.quality_score);
  const wasteReductionPct = pct(bestPipeline.tokens_wasted_avg, baseline.tokens_wasted_avg);
  const latencyDiffPct = pct(bestPipeline.total_latency_ms, baseline.total_latency_ms);

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Visão Geral dos Benchmarks</h2>
          <p class="lab-section-desc">Desempenho consolidado nos testes automatizados em ${meta.dataset_name}.</p>
        </div>
      </div>

      <!-- KPI Grid do Laboratório (Todos os valores calculados) -->
      <div class="costs-kpi-grid">
        <div class="kpi-card" style="border-color: var(--lab-accent-border);">
          <div class="kpi-label">
            <span>Runs Executados</span>
            <span class="badge-origin badge-origin-measured">Dataset Lite</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value" style="color: var(--lab-accent);">${meta.total_runs}</span>
          </div>
          <span class="kpi-subtext">Última execução: ${meta.last_benchmark}</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>Melhoria de Qualidade</span>
            <span class="badge-origin badge-origin-measured">vs Baseline</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value" style="color: var(--success);">${qualityDiffPct == null ? '—' : '+' + qualityDiffPct + '%'}</span>
          </div>
          <span class="kpi-subtext">${bestPipeline.name} (${bestPipeline.quality_score} pts)</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>Redução de Desperdício</span>
            <span class="badge-origin badge-origin-measured">Tokens Espúrios</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value" style="color: var(--primary);">${wasteReductionPct == null ? '—' : wasteReductionPct + '%'}</span>
          </div>
          <span class="kpi-subtext">De ${baseline.tokens_wasted_avg} para ${bestPipeline.tokens_wasted_avg} tokens</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>Impacto em Latência</span>
            <span class="badge-origin badge-origin-measured">Tempo Total</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value" style="color: ${parseFloat(latencyDiffPct) <= 0 ? 'var(--success)' : 'var(--warning)'};">${latencyDiffPct == null ? '—' : (latencyDiffPct > 0 ? '+' : '') + latencyDiffPct + '%'}</span>
          </div>
          <span class="kpi-subtext">${bestPipeline.total_latency_ms} ms vs ${baseline.total_latency_ms} ms</span>
        </div>
      </div>

      <!-- Gráfico Comparativo de Quality Score dos Pipelines -->
      <div class="card" style="padding: var(--space-5); margin-top: var(--space-4);">
        <div class="card-header" style="margin-bottom: var(--space-4);">
          <div>
            <h3 class="card-title">Score de Qualidade por Pipeline (0 a 100)</h3>
            <p class="card-subtitle">Avaliação cega baseada em taxa de resolução de patches corretos no dataset.</p>
          </div>
        </div>

        <div id="overview-score-chart-mount" style="min-height: 230px; width: 100%;"></div>
      </div>

      <!-- Tabela sintética de pipelines -->
      <div class="card" style="margin-top: var(--space-4);">
        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Pipeline</th>
                <th class="num-col">Score (Qualidade)</th>
                <th class="num-col">Δ Baseline</th>
                <th class="num-col">Tokens / Execução</th>
                <th class="num-col">Latência Média</th>
                <th>Selo de Procedência</th>
              </tr>
            </thead>
            <tbody>
              ${pipelines.map(p => {
                const diff = pct(p.quality_score, baseline.quality_score);
                const diffLabel = p.id === 'baseline' ? 'Ref.' : (diff == null ? '—' : `+${diff}%`);
                const sealClass = p.seal === 'verified' ? 'badge-verified' : 'badge-experimental';
                return `
                  <tr>
                    <td>
                      <div style="font-weight: 600; color: var(--text-primary);">${p.name}</div>
                      <div style="font-size: 11px; color: var(--text-tertiary);">${p.description}</div>
                    </td>
                    <td class="num-col tabular font-mono" style="font-size: 14px; font-weight: 700;">${p.quality_score > 0 ? p.quality_score.toFixed(1) : '—'}</td>
                    <td class="num-col tabular font-mono" style="color: ${p.id === 'baseline' ? 'var(--text-tertiary)' : 'var(--success)'}; font-weight: 600;">
                      ${diffLabel}
                    </td>
                    <td class="num-col tabular font-mono">${p.context_tokens_avg.toLocaleString()} tok</td>
                    <td class="num-col tabular font-mono">${p.total_latency_ms} ms</td>
                    <td>
                      <span class="${sealClass}">${p.seal_label}</span>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  cleanupChart();

  const mountElem = root.querySelector('#overview-score-chart-mount');
  if (mountElem) {
    const pipelines = mockBenchmark.pipelines;
    const categories = pipelines.map(p => p.name);

    chartInstance = createBarChart(mountElem, {
      categories,
      series: [
        { label: 'Score de Qualidade', color: 'var(--chart-2)', values: pipelines.map(p => p.quality_score) }
      ],
      yFormatter: (v) => `${v.toFixed(0)} pts`,
      height: 230
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
