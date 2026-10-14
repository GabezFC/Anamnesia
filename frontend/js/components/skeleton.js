/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * SKELETON / SPINNER — placeholders de carregamento reutilizáveis (retornam HTML string).
 *
 * skeleton({ width, height, radius, className })       → bloco único com shimmer
 * skeletonLines(n, { widths })                          → n linhas de texto
 * skeletonCard({ lines })                               → cartão com título + linhas
 * skeletonKpis(n)                                       → faixa de n KPIs
 * skeletonTable({ rows, cols })                         → tabela fantasma
 * spinner({ size, label })                              → indicador circular acessível
 */
import { esc } from '../format.js';

const dim = (v, fallback) => {
  if (v == null) return fallback;
  return typeof v === 'number' ? `${v}px` : String(v).replace(/[^0-9a-z%.\s()+*/-]/gi, '');
};

export function skeleton({ width = '100%', height = 14, radius, className = '' } = {}) {
  const r = radius != null ? `;border-radius:${dim(radius, '4px')}` : '';
  return `<div class="skeleton ${esc(className)}" aria-hidden="true" data-css="${esc(`width:${dim(width, '100%')};height:${dim(height, '14px')}${r}`)}"></div>`;
}

export function skeletonLines(n = 3, { widths = ['100%', '92%', '64%'], height = 12 } = {}) {
  return Array.from({ length: n }, (_, i) => skeleton({ width: widths[i % widths.length], height })).join('');
}

export function skeletonCard({ lines = 3 } = {}) {
  return `<div class="card skeleton-card" aria-hidden="true">${skeleton({ width: '40%', height: 16 })}${skeletonLines(lines)}</div>`;
}

export function skeletonKpis(n = 4) {
  return `<div class="skeleton-kpis" aria-hidden="true">${Array.from({ length: n }, () => skeletonCard({ lines: 1 })).join('')}</div>`;
}

export function skeletonTable({ rows = 6, cols = 5 } = {}) {
  const row = `<div class="skeleton-row" data-css="grid-template-columns:repeat(${Number(cols) || 1},1fr)">${Array.from({ length: cols }, () => skeleton({ height: 12 })).join('')}</div>`;
  return `<div class="skeleton-table" aria-hidden="true">${row.repeat(rows)}</div>`;
}

export function spinner({ size = 18, label = '' } = {}) {
  const s = Number(size) || 18;
  return `<span class="spinner-wrap" role="status" aria-live="polite"><span class="spinner" data-css="width:${s}px;height:${s}px" aria-hidden="true"></span>${label ? `<span class="spinner-label">${esc(label)}</span>` : '<span class="sr-only">…</span>'}</span>`;
}

/** Wrapper acessível: envolve skeletons e anuncia o carregamento a leitores de tela. */
export function loadingBlock(inner, label = '') {
  return `<div class="loading-block" role="status" aria-busy="true" aria-live="polite">${label ? `<span class="sr-only">${esc(label)}</span>` : ''}${inner}</div>`;
}
