/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA COSTS PAGE (#/costs)
 * Livro de custos por chamada do Memory Gateway, orçamentos e gráficos SVG interativos.
 * Zero benchmarks ou comparações de modelos nesta página (foco em produto e auditoria financeira).
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { mockCostSummary, mockBudget, mockCalls } from '../mock-data.js';
import { createLineChart, createDonutChart } from '../charts/chart-kit.js';

let selectedPeriod = 'today'; // 'today' | '7d' | '30d' | 'all'
let visibleCallsCount = 12;
let selectedCardCall = null;
let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'

// Chart instances for proper cleanup on unmount
let lineChartInstance = null;
let donutChartInstance = null;
const ORIGIN_PT = { measured: 'medido', estimated: 'estimado', unavailable: 'indisponível' };

export function render() {
  const t = I18N.costs;

  if (currentState === 'loading') {
    return `
      <div class="costs-page">
        <div class="skeleton" style="height: 36px; width: 340px;"></div>
        <div class="costs-kpi-grid">
          <div class="skeleton" style="height: 110px;"></div>
          <div class="skeleton" style="height: 110px;"></div>
          <div class="skeleton" style="height: 110px;"></div>
          <div class="skeleton" style="height: 110px;"></div>
        </div>
        <div class="skeleton" style="height: 240px; margin-top: 16px;"></div>
      </div>
    `;
  }

  if (currentState === 'error') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap" style="color: var(--danger);">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Falha ao consolidar o ledger de chamadas do Memory Gateway.</p>
        <button class="btn btn-secondary" data-action="retry-costs">${I18N.app.errorRetry}</button>
      </div>
    `;
  }

  if (currentState === 'empty') {
    return `
      <div class="state-container" style="height: 100%;">
        <div class="state-icon-wrap">${icon('costs', '', 28)}</div>
        <h2 class="state-title">Nenhum custo registrado</h2>
        <p class="state-description">Execute comandos em um terminal para registrar consumo no Memory Gateway.</p>
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

  const visibleCalls = mockCalls.slice(0, visibleCallsCount);

  // Dynamic calculations based on mockCalls
  const totalCallsCount = mockCalls.length;
  const measuredCalls = mockCalls.filter(c => c.cost_usd.value !== null);
  const totalSpentUsd = measuredCalls.reduce((acc, c) => acc + c.cost_usd.value, 0);
  const totalContextTokens = mockCalls.reduce((acc, c) => acc + c.context_tokens, 0);

  return `
    <div class="costs-page" data-bind="costs-page">
      ${backendNotice}

      <!-- BARRA DE CABEÇALHO & FILTROS -->
      <div class="costs-filter-bar">
        <div>
          <h1 style="font-size: var(--text-2xl); font-weight: var(--font-semibold); color: var(--text-primary);">${t.ledgerTitle}</h1>
          <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">
            Auditoria de consumo financeiro e volumetria de tokens entregues pelo gateway local.
          </p>
        </div>

        <div style="display: flex; align-items: center; gap: var(--space-3);">
          <div class="tab-list" role="tablist">
            <button class="tab-btn ${selectedPeriod === 'today' ? 'is-active' : ''}" role="tab" aria-selected="${selectedPeriod === 'today'}" data-action="filter-period" data-period="today">${t.periodToday}</button>
            <button class="tab-btn ${selectedPeriod === '7d' ? 'is-active' : ''}" role="tab" aria-selected="${selectedPeriod === '7d'}" data-action="filter-period" data-period="7d">${t.period7d}</button>
            <button class="tab-btn ${selectedPeriod === '30d' ? 'is-active' : ''}" role="tab" aria-selected="${selectedPeriod === '30d'}" data-action="filter-period" data-period="30d">${t.period30d}</button>
            <button class="tab-btn ${selectedPeriod === 'all' ? 'is-active' : ''}" role="tab" aria-selected="${selectedPeriod === 'all'}" data-action="filter-period" data-period="all">${t.periodAll}</button>
          </div>

          <button class="btn btn-secondary btn-sm" data-action="export-csv">
            ${icon('download', '', 13)} ${t.exportCsv}
          </button>
        </div>
      </div>

      <!-- CARDS KPI COM SELOS DE ORIGEM (medido, estimado, indisponível) -->
      <div class="costs-kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">
            <span>${t.kpiTotal}</span>
            <span class="badge-origin badge-origin-${mockCostSummary.total_usd.origin}">${ORIGIN_PT[mockCostSummary.total_usd.origin]}</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value">${mockCostSummary.total_usd.value == null ? 'indisponível' : 'US$ ' + mockCostSummary.total_usd.value.toFixed(2)}</span>
          </div>
          <span class="kpi-subtext">Acumulado no período selecionado</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>${t.kpiCalls}</span>
            <span class="badge-origin badge-origin-measured">medido</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value">${totalCallsCount}</span>
          </div>
          <span class="kpi-subtext">Registros no gateway local</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>${t.kpiTokens}</span>
            <span class="badge-origin badge-origin-${mockCostSummary.context_tokens.origin}">${ORIGIN_PT[mockCostSummary.context_tokens.origin]}</span>
          </div>
          <div class="kpi-value-row">
            <span class="kpi-value">${(totalContextTokens / 1000).toFixed(1)}k</span>
          </div>
          <span class="kpi-subtext">Injetados no contexto dos prompts</span>
        </div>

        <div class="kpi-card">
          <div class="kpi-label">
            <span>${t.kpiSavedTokens}</span>
            <span class="badge-origin badge-origin-${mockCostSummary.saved_tokens_est.origin}">${ORIGIN_PT[mockCostSummary.saved_tokens_est.origin]}</span>
          </div>
          <div class="kpi-value-row" style="color: var(--success);">
            <span class="kpi-value" style="color: var(--success);">${mockCostSummary.saved_tokens_est.label}</span>
          </div>
          <span class="kpi-subtext">Evitados via deduplicação & JEV</span>
        </div>
      </div>

      <!-- PAINEL DE ORÇAMENTO (Gauges diário e mensal) -->
      <div class="budget-panel">
        <div style="display: flex; align-items: center; justify-content: space-between;">
          <h2 style="font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary);">Limites de Orçamento do Usuário</h2>
          <span class="status-indicator">
            <span class="dot dot-success"></span>
            <span style="font-size: var(--text-xs); color: var(--text-secondary);">Dentro das metas configuradas</span>
          </span>
        </div>

        <div class="budget-bars-grid">
          <div class="budget-item">
            <div class="budget-header">
              <span style="font-weight: 500;">${t.budgetDaily}</span>
              <span class="tabular">US$ ${mockBudget.daily.spent.toFixed(2)} ${t.budgetOf} US$ ${mockBudget.daily.limit.toFixed(2)} (${((mockBudget.daily.spent / mockBudget.daily.limit) * 100).toFixed(0)}%)</span>
            </div>
            <div class="budget-track">
              <div class="budget-fill budget-fill-ok" style="width: ${Math.min((mockBudget.daily.spent / mockBudget.daily.limit) * 100, 100)}%;"></div>
            </div>
          </div>

          <div class="budget-item">
            <div class="budget-header">
              <span style="font-weight: 500;">${t.budgetMonthly}</span>
              <span class="tabular">US$ ${mockBudget.monthly.spent.toFixed(2)} ${t.budgetOf} US$ ${mockBudget.monthly.limit.toFixed(2)} (${mockBudget.monthly.pct}%)</span>
            </div>
            <div class="budget-track">
              <div class="budget-fill budget-fill-ok" style="width: ${mockBudget.monthly.pct}%;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- SEÇÃO DE GRÁFICOS REATIVOS COM CHART-KIT (LINHA TEMPORAL + DISTRIBUIÇÃO POR AGENTE) -->
      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: var(--space-4); margin-bottom: var(--space-5);">
        <!-- Gráfico de Linha de Gastos Acumulados -->
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <h2 style="font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary);">Consumo Financeiro Acumulado (Hoje)</h2>
              <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">Variação horária em dólares norte-americanos (US$)</p>
            </div>
            <span class="badge-origin badge-origin-measured">medido</span>
          </div>

          <!-- Container do ChartKit SVG -->
          <div id="cost-line-chart-mount" style="min-height: 220px; width: 100%; margin-top: var(--space-3);"></div>
        </div>

        <!-- Donut de Distribuição de Chamadas por Agente -->
        <div class="chart-card">
          <div class="chart-header">
            <div>
              <h2 style="font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary);">Chamadas por Agente</h2>
              <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 2px;">Distribuição de volume</p>
            </div>
          </div>

          <div id="cost-donut-chart-mount" style="min-height: 220px; width: 100%; margin-top: var(--space-3); display: flex; align-items: center; justify-content: center;"></div>
        </div>
      </div>

      <!-- TABELA DE CHAMADAS (Quando, Projeto, Agente, Pipeline, Contexto, Custo, Origem, Detalhes) -->
      <div class="calls-section">
        <div class="calls-table-toolbar">
          <h2 style="font-size: var(--text-md); font-weight: var(--font-semibold); color: var(--text-primary);">${t.callsTableTitle}</h2>
          <span class="section-count tabular">Exibindo ${visibleCalls.length} de ${mockCalls.length} chamadas</span>
        </div>

        <div class="table-container">
          <table class="table" data-bind="calls-table">
            <thead>
              <tr>
                <th>${t.colWhen}</th>
                <th>${t.colProject}</th>
                <th>${t.colAgent}</th>
                <th>${t.colPipeline}</th>
                <th class="num-col">${t.colContext}</th>
                <th class="num-col">${t.colCost}</th>
                <th>${t.colOrigin}</th>
                <th style="text-align: right;">${t.colActions}</th>
              </tr>
            </thead>
            <tbody>
              ${visibleCalls.map(c => {
                const hasValue = c.cost_usd.value !== null;
                const costDisplay = hasValue ? `US$ ${c.cost_usd.value.toFixed(4)}` : 'indisponível';
                const originClass = c.cost_usd.origin === 'measured' ? 'badge-origin-measured' : c.cost_usd.origin === 'estimated' ? 'badge-origin-estimated' : 'badge-origin-unavailable';
                return `
                  <tr>
                    <td class="tabular font-mono" style="color: var(--text-secondary); font-size: 11px;">${c.when}</td>
                    <td style="font-weight: 500;">${c.project}</td>
                    <td>
                      <span class="badge" style="font-family: var(--font-mono); font-size: 11px;">${c.agent}</span>
                    </td>
                    <td><span class="font-mono text-tertiary" style="font-size: 11px;">${c.pipeline}</span></td>
                    <td class="num-col tabular font-mono">${c.context_tokens.toLocaleString()} tok</td>
                    <td class="num-col tabular font-mono" style="font-weight: 600;">${costDisplay}</td>
                    <td>
                      <span class="badge-origin ${originClass}">${c.cost_usd.origin}</span>
                    </td>
                    <td style="text-align: right;">
                      <button class="btn btn-ghost btn-sm" data-action="view-call-detail" data-call-id="${c.id}">
                        ${icon('fileText', '', 12)} Detalhes
                      </button>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>

        ${visibleCallsCount < mockCalls.length ? `
          <div style="text-align: center; margin-top: var(--space-4);">
            <button class="btn btn-secondary btn-sm" data-action="load-more-calls">
              Carregar mais chamadas (${mockCalls.length - visibleCallsCount} restantes)
            </button>
          </div>
        ` : ''}
      </div>

      <!-- GAVETA LATERAL: Detalhamento da Chamada -->
      <div class="drawer-backdrop ${selectedCardCall ? 'is-active' : ''}" data-action="close-call-detail"></div>
      <div class="drawer ${selectedCardCall ? 'is-active' : ''}">
        <div class="drawer-header">
          <div>
            <div class="card-title">${t.callDetailTitle}</div>
            <div class="card-subtitle">${selectedCardCall ? selectedCardCall.id : ''}</div>
          </div>
          <button class="btn btn-ghost btn-icon" data-action="close-call-detail">${icon('x', '', 16)}</button>
        </div>
        <div class="drawer-content">
          ${selectedCardCall ? `
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Timestamp</span>
              <span class="readonly-kv-value tabular">${selectedCardCall.when}</span>
            </div>
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Projeto Vinculado</span>
              <span class="readonly-kv-value">${selectedCardCall.project}</span>
            </div>
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Agente Consumidor</span>
              <span class="readonly-kv-value">${selectedCardCall.agent}</span>
            </div>
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Pipeline de Execução</span>
              <span class="readonly-kv-value font-mono">${selectedCardCall.pipeline}</span>
            </div>
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Tokens de Contexto Injetados</span>
              <span class="readonly-kv-value tabular">${selectedCardCall.context_tokens.toLocaleString()} tokens</span>
            </div>
            <div class="readonly-kv-item">
              <span class="readonly-kv-label">Custo Total e Origem</span>
              <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 4px;">
                <span class="readonly-kv-value tabular" style="font-size: 16px;">
                  ${selectedCardCall.cost_usd.value !== null ? `US$ ${selectedCardCall.cost_usd.value.toFixed(4)}` : 'indisponível'}
                </span>
                <span class="badge-origin badge-origin-${selectedCardCall.cost_usd.origin}">${selectedCardCall.cost_usd.origin}</span>
              </div>
            </div>
          ` : ''}
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {
  // Mount interactive SVG charts using ChartKit
  mountCharts(root);

  const handleClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.getAttribute('data-action');

    if (action === 'filter-period') {
      selectedPeriod = target.getAttribute('data-period');
      root.innerHTML = render();
      mountCharts(root);
    } else if (action === 'export-csv') {
      window.dispatchEvent(new CustomEvent('anamnesia:toast', {
        detail: { type: 'success', message: 'Relatório anamnesia-costs.csv gerado com sucesso.' }
      }));
    } else if (action === 'load-more-calls') {
      visibleCallsCount = Math.min(visibleCallsCount + 10, mockCalls.length);
      root.innerHTML = render();
      mountCharts(root);
    } else if (action === 'view-call-detail') {
      const callId = target.getAttribute('data-call-id');
      selectedCardCall = mockCalls.find(c => c.id === callId) || null;
      root.innerHTML = render();
      mountCharts(root);
    } else if (action === 'close-call-detail') {
      selectedCardCall = null;
      root.innerHTML = render();
      mountCharts(root);
    } else if (action === 'retry-costs') {
      currentState = 'loaded';
      root.innerHTML = render();
      mountCharts(root);
    }
  };

  root.addEventListener('click', handleClick);
  root._costsCleanup = () => {
    root.removeEventListener('click', handleClick);
    cleanupCharts();
  };
}

function mountCharts(root) {
  cleanupCharts();

  const lineMount = root.querySelector('#cost-line-chart-mount');
  if (lineMount) {
    // Cumulative hourly spending from 06h to 12h
    const byHour = new Map();
    [...mockCalls].filter(c => c.ts).sort((a, b) => a.ts - b.ts).forEach(c => {
      const d = new Date(c.ts * 1000);
      const key = `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}h`;
      byHour.set(key, (byHour.get(key) || 0) + (c.cost_usd.value || 0));
    });
    let acc = 0;
    const hourlyPoints = [...byHour.entries()].map(([hour, v]) => { acc += v; return { hour, cost: Number(acc.toFixed(4)) }; });
    if (!hourlyPoints.length) hourlyPoints.push({ hour: '—', cost: 0 });

    lineChartInstance = createLineChart(lineMount, {
      data: hourlyPoints,
      xKey: 'hour',
      series: [
        { key: 'cost', label: 'Custo Acumulado', color: 'var(--chart-1)', fill: true }
      ],
      yFormatter: (v) => `US$ ${v.toFixed(2)}`,
      xFormatter: (v) => v,
      height: 220
    });
  }

  const donutMount = root.querySelector('#cost-donut-chart-mount');
  if (donutMount) {
    // Count calls per agent
    const counts = {};
    mockCalls.forEach(c => {
      counts[c.agent] = (counts[c.agent] || 0) + 1;
    });

    const PAL = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)'];
    const donutData = Object.entries(counts).map(([label, value], i) => ({ label, value, color: PAL[i % PAL.length] }));
    if (!donutData.length) donutData.push({ label: 'sem chamadas', value: 1, color: 'var(--border-subtle)' });

    donutChartInstance = createDonutChart(donutMount, {
      data: donutData,
      formatter: (v) => `${v} chamadas`,
      centerLabel: 'Total',
      size: 190,
      thickness: 24
    });
  }
}

function cleanupCharts() {
  if (lineChartInstance && lineChartInstance.destroy) {
    lineChartInstance.destroy();
    lineChartInstance = null;
  }
  if (donutChartInstance && donutChartInstance.destroy) {
    donutChartInstance.destroy();
    donutChartInstance = null;
  }
}

export function unmount(root) {
  cleanupCharts();
  if (root && root._costsCleanup) {
    root._costsCleanup();
    delete root._costsCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) {
    root.innerHTML = render();
    mountCharts(root);
  }
}
