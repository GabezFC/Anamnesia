/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: COMPARAÇÃO DE MODELOS & PIPELINES (#/compare/models)
 * Baseline vs Graphify vs JEV pipelines com significância estatística (p-valor, IC 95%).
 */

import { icon } from '../../icons.js';
import { I18N } from '../../i18n.js';
import { mockBenchmark } from '../../mock-data.js';

export function render() {
  const pipelines = mockBenchmark.pipelines;

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Comparação Estatística de Pipelines</h2>
          <p class="lab-section-desc">Análise de hipótese nula com pareamento de tarefas em SWE-bench (N=50).</p>
        </div>
      </div>

      <!-- Tabela estatística detalhada com p-valor e IC -->
      <div class="card">
        <div class="table-container">
          <table class="table">
            <thead>
              <tr>
                <th>Pipeline</th>
                <th class="num-col">Score de Qualidade</th>
                <th class="num-col">Δ vs Baseline</th>
                <th class="num-col">p-valor</th>
                <th class="num-col">IC 95%</th>
                <th>Significância</th>
                <th>Selo</th>
              </tr>
            </thead>
            <tbody>
              ${pipelines.map(p => {
                const isSignificant = p.p_value !== null && p.p_value < 0.05;
                return `
                  <tr>
                    <td>
                      <div style="font-weight: 600; color: var(--text-primary);">${p.name}</div>
                      <div style="font-size: 11px; color: var(--text-tertiary);">${p.description}</div>
                    </td>
                    <td class="num-col" style="font-size: 14px; font-weight: 600;">${p.quality_score.toFixed(1)}%</td>
                    <td class="num-col" style="font-weight: 600; color: ${p.diff_baseline.startsWith('+0') ? 'var(--text-tertiary)' : 'var(--success)'};">${p.diff_baseline}</td>
                    <td class="num-col">
                      ${p.p_value !== null ? `<span class="sig-p-value">p = ${p.p_value.toFixed(3)}</span>` : '<span style="color: var(--text-tertiary);">-</span>'}
                    </td>
                    <td class="num-col font-mono" style="font-size: 11px; color: var(--text-secondary);">${p.ci_95}</td>
                    <td>
                      ${isSignificant ? `
                        <span class="badge-origin badge-origin-measured" style="color: var(--success); border-color: var(--success-border);">
                          ${icon('check', '', 10)} ${I18N.lab.statSignificant}
                        </span>
                      ` : `
                        <span class="badge-origin badge-origin-unavailable">Referência</span>
                      `}
                    </td>
                    <td>
                      <span class="badge-seal badge-seal-${p.seal}">${p.seal_label}</span>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <!-- Explicação Metodológica -->
      <div class="card" style="background-color: var(--bg-surface-elevated);">
        <div style="display: flex; gap: var(--space-4); align-items: flex-start;">
          <div style="color: var(--lab-accent);">${icon('info', '', 20)}</div>
          <div>
            <h4 style="font-size: var(--text-sm); font-weight: var(--font-semibold); color: var(--text-primary);">Metodologia de Veredito com Avaliação Conjunta (JEV)</h4>
            <p style="font-size: var(--text-xs); color: var(--text-secondary); margin-top: 4px; line-height: 1.6;">
              O pipeline JEV submete os trechos de memória recuperados a uma etapa preliminar de juiz cego que cruza os artefatos de código com a query original do programador.
              Observou-se uma redução de 74.2% em tokens poluídos e um aumento estatisticamente significante de +28.4% no índice de resolução correta de bugs (p = 0.004).
            </p>
          </div>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {}
export function unmount(root) {}
