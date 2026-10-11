/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: RESULTADOS & SELOS DE PROCEDÊNCIA (#/compare/results)
 * Selos: Verificado / Experimental / Invalidado e critérios de certificação.
 */

import { icon } from '../../icons.js';
import { mockBenchmark } from '../../mock-data.js';

export function render() {
  const pipelines = mockBenchmark.pipelines;

  return `
    <div class="lab-view-container">
      <div class="lab-section-header">
        <div>
          <h2 class="lab-section-title">Resultados e Selos de Certificação</h2>
          <p class="lab-section-desc">Auditoria formal de reprodutibilidade e critérios de validação estatística.</p>
        </div>
      </div>

      <!-- Grid de Cartões de Selo -->
      <div class="cards-grid">
        ${pipelines.map(p => `
          <div class="card" style="border-top: 3px solid ${p.seal === 'verified' ? 'var(--success)' : p.seal === 'experimental' ? 'var(--lab-accent)' : 'var(--danger)'};">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
              <span class="badge-seal badge-seal-${p.seal}">${p.seal_label}</span>
              <span class="font-mono tabular" style="font-size: 11px; color: var(--text-tertiary);">N = 50 tasks</span>
            </div>

            <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary);">${p.name}</h3>
            <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px; line-height: 1.5;">${p.description}</p>

            <div style="display: flex; flex-direction: column; gap: 6px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-subtle); font-size: 11px;">
              <div style="display: flex; justify-content: space-between;">
                <span style="color: var(--text-tertiary);">Taxa de Acerto</span>
                <span class="font-mono tabular" style="font-weight: 600; color: var(--text-primary);">${p.quality_score.toFixed(1)}%</span>
              </div>
              <div style="display: flex; justify-content: space-between;">
                <span style="color: var(--text-tertiary);">Significância (p < 0.05)</span>
                <span class="font-mono tabular">${p.p_value !== null ? `Sim (p = ${p.p_value})` : 'Referência'}</span>
              </div>
              <div style="display: flex; justify-content: space-between;">
                <span style="color: var(--text-tertiary);">Latência p95</span>
                <span class="font-mono tabular">${p.total_latency_ms} ms</span>
              </div>
            </div>
          </div>
        `).join('')}

        <!-- Exemplo de Selo Invalidado para demonstrar completude da taxonomia -->
        <div class="card" style="border-top: 3px solid var(--danger); opacity: 0.85;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
            <span class="badge-seal badge-seal-invalidated">Invalidado</span>
            <span class="font-mono tabular" style="font-size: 11px; color: var(--text-tertiary);">Run #18 descartado</span>
          </div>
          <h3 style="font-size: 15px; font-weight: 600; color: var(--text-primary);">BM25 Puro sem Grafo</h3>
          <p style="font-size: 12px; color: var(--text-secondary); margin-top: 4px; line-height: 1.5;">
            Falha no critério de integridade: taxa de alucinação de imports superou 38% em benchmarks com monorepos TypeScript.
          </p>
          <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border-subtle); font-size: 11px; color: var(--danger);">
            Status: Desqualificado para produção local.
          </div>
        </div>
      </div>
    </div>
  `;
}

export function mount(root) {}
export function unmount(root) {}
