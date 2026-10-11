/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: ANÁLISE DE TOKENS (#/compare/tokens)
 * Contexto entregue vs tokens efetivamente necessários / gastos.
 * Gráfico SVG StackedBarChart com eixos, escala real e cálculos dinâmicos do mock.
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';
import { createStackedBarChart } from '../../charts/chart-kit.js';

let chartInstance = null;

export function render() {
  const pipelines = mockBenchmark.pipelines;

  // Cálculos dinâmicos a partir do mockBenchmark (zero valores hardcoded)
  const baseline = pipelines.find(p => p.id === 'baseline') || pipelines[0];
  const baselineUseful = baseline.context_tokens_avg - baseline.tokens_wasted_avg;
  const eff = (u, t) => (t > 0 ? ((u / t) * 100).toFixed(1) : '—');
  const baselineEffPct = eff(baselineUseful, baseline.context_tokens_avg);

  const opt = pipelines.find(p => p.id === 'graphify_jev_opt') || pipelines[pipelines.length - 1];
  const optUseful = opt.context_tokens_avg - opt.tokens_wasted_avg;
  const optEffPct = eff(optUseful, opt.context_tokens_avg);

  const wasteDiffPct = baseline.tokens_wasted_avg > 0 ? (((opt.tokens_wasted_avg - baseline.tokens_wasted_avg) / baseline.tokens_wasted_avg) * 100).toFixed(1) : '—';

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Contexto Entregue vs Desperdício de Tokens</h2>
          <p class="lab-section-desc">Comparação da densidade de tokens úteis nos prompts de inferência.</p>
        </div>
      </div>

      <!-- Gráfico de Barras Empilhadas SVG com Eixos Reais (ChartKit) -->
      <div class="card" style="padding: var(--space-5);">
        <div class="card-header" style="margin-bottom: var(--space-4);">
          <div>
            <h3 class="card-title">Distribuição de Tokens por Execução Média</h3>
            <p class="card-subtitle">Azul: tokens entregues ao modelo · Vermelho: candidatos descartados antes do contexto</p>
          </div>
        </div>

        <div id="tokens-stacked-chart-mount" style="min-height: 250px; width: 100%;"></div>
      </div>

      <!-- Métricas comparativas calculadas em tempo de execução -->
      <div class="cards-grid" style="margin-top: var(--space-4);">
        <div class="card">
          <div class="card-title" style="font-size: 13px;">Aproveitamento no Pipeline Baseline</div>
          <div style="font-size: 26px; font-weight: 700; color: var(--danger); margin-top: 6px;">${baselineEffPct}%</div>
          <p style="font-size: 11px; color: var(--text-tertiary); margin-top: 4px;">
            ${baselineUseful.toLocaleString()} de ${baseline.context_tokens_avg.toLocaleString()} tokens candidatos chegaram ao contexto do modelo.
          </p>
        </div>

        <div class="card">
          <div class="card-title" style="font-size: 13px;">Aproveitamento no Graphify + JEV Otimizado</div>
          <div style="font-size: 26px; font-weight: 700; color: var(--success); margin-top: 6px;">${optEffPct}%</div>
          <p style="font-size: 11px; color: var(--text-tertiary); margin-top: 4px;">
            ${optUseful.toLocaleString()} de ${opt.context_tokens_avg.toLocaleString()} tokens candidatos chegaram ao contexto do modelo.
          </p>
        </div>

        <div class="card">
          <div class="card-title" style="font-size: 13px;">Variação de candidatos descartados</div>
          <div style="font-size: 26px; font-weight: 700; color: var(--primary); margin-top: 6px;">${wasteDiffPct}%</div>
          <p style="font-size: 11px; color: var(--text-tertiary); margin-top: 4px;">
            De ${baseline.tokens_wasted_avg.toLocaleString()} tokens descartados, variando para ${opt.tokens_wasted_avg.toLocaleString()} tokens neste pipeline.
          </p>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  cleanupChart();

  const mountElem = root.querySelector('#tokens-stacked-chart-mount');
  if (mountElem) {
    const pipelines = mockBenchmark.pipelines;
    const categories = pipelines.map(p => p.name);

    const usefulValues = pipelines.map(p => p.context_tokens_avg - p.tokens_wasted_avg);
    const wastedValues = pipelines.map(p => p.tokens_wasted_avg);

    chartInstance = createStackedBarChart(mountElem, {
      categories,
      series: [
        { label: 'Entregues ao modelo', color: 'var(--chart-1)', values: usefulValues },
        { label: 'Descartados', color: 'var(--chart-6)', values: wastedValues }
      ],
      yFormatter: (v) => `${v.toLocaleString()} tok`,
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
