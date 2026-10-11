/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * EMPTY STATE — estado vazio ilustrado (SVG inline, cores via tokens CSS, sem assets externos).
 *
 * emptyState({ title, description, variant, action, compact }) → HTML string
 *   variant: 'data' | 'search' | 'terminal' | 'error' | 'cost'  (padrão 'data')
 *   action:  { label, action: 'data-action', href?, attrs?: {k:v}, kind?: 'primary'|'secondary' }
 * Os cliques usam delegação por data-action (sem handlers inline).
 */
import { esc } from '../format.js';
import { I18N } from '../i18n.js';

const STROKE = 'stroke="var(--border-strong)" stroke-width="1.5"';
const ACC = 'stroke="var(--primary)" stroke-width="1.5"';

const ART = {
  data: `<rect x="22" y="18" width="76" height="54" rx="6" ${STROKE} fill="var(--bg-surface-subtle)"/><line x1="34" y1="34" x2="86" y2="34" ${STROKE} stroke-linecap="round"/><line x1="34" y1="46" x2="72" y2="46" ${STROKE} stroke-linecap="round"/><line x1="34" y1="58" x2="60" y2="58" ${STROKE} stroke-linecap="round"/><circle cx="92" cy="66" r="12" fill="var(--primary-muted)" ${ACC}/><line x1="92" y1="60" x2="92" y2="72" ${ACC} stroke-linecap="round"/><line x1="86" y1="66" x2="98" y2="66" ${ACC} stroke-linecap="round"/>`,
  search: `<rect x="20" y="16" width="64" height="48" rx="6" ${STROKE} fill="var(--bg-surface-subtle)"/><line x1="32" y1="32" x2="72" y2="32" ${STROKE} stroke-linecap="round"/><line x1="32" y1="44" x2="58" y2="44" ${STROKE} stroke-linecap="round"/><circle cx="84" cy="54" r="16" fill="var(--bg-surface)" ${ACC}/><line x1="96" y1="66" x2="106" y2="76" ${ACC} stroke-linecap="round" stroke-width="2.5"/>`,
  terminal: `<rect x="16" y="14" width="88" height="62" rx="8" ${STROKE} fill="var(--term-bg, var(--bg-surface-subtle))"/><line x1="16" y1="28" x2="104" y2="28" ${STROKE}/><circle cx="26" cy="21" r="2" fill="var(--danger, var(--border-strong))"/><circle cx="34" cy="21" r="2" fill="var(--warning, var(--border-strong))"/><circle cx="42" cy="21" r="2" fill="var(--success, var(--border-strong))"/><polyline points="30 42 40 50 30 58" ${ACC} stroke-linecap="round" stroke-linejoin="round"/><line x1="46" y1="58" x2="66" y2="58" ${ACC} stroke-linecap="round"/>`,
  error: `<path d="M60 14 L100 74 H20 Z" fill="var(--bg-surface-subtle)" ${STROKE} stroke-linejoin="round"/><line x1="60" y1="36" x2="60" y2="54" stroke="var(--danger, var(--primary))" stroke-width="2" stroke-linecap="round"/><circle cx="60" cy="63" r="1.8" fill="var(--danger, var(--primary))"/>`,
  cost: `<ellipse cx="48" cy="60" rx="26" ry="9" fill="var(--bg-surface-subtle)" ${STROKE}/><path d="M22 48 v12 a26 9 0 0 0 52 0 v-12" ${STROKE}/><ellipse cx="48" cy="48" rx="26" ry="9" fill="var(--bg-surface-subtle)" ${STROKE}/><path d="M22 36 v12 a26 9 0 0 0 52 0 v-12" ${STROKE}/><ellipse cx="48" cy="36" rx="26" ry="9" fill="var(--primary-muted)" ${ACC}/><circle cx="92" cy="30" r="12" fill="var(--bg-surface)" ${ACC}/><text x="92" y="35" text-anchor="middle" font-size="14" fill="var(--primary)" font-family="inherit">$</text>`,
};

export function emptyIllustration(variant = 'data') {
  return `<svg class="empty-illustration" viewBox="0 0 120 90" width="120" height="90" fill="none" aria-hidden="true" focusable="false">${ART[variant] || ART.data}</svg>`;
}

export function emptyState({ title, description = '', variant = 'data', action = null, compact = false } = {}) {
  const t = esc(title ?? I18N.app.emptyTitle);
  let btn = '';
  if (action && action.label) {
    const cls = `btn btn-${action.kind === 'secondary' ? 'secondary' : 'primary'}`;
    const attrs = Object.entries(action.attrs || {}).map(([k, v]) => ` ${esc(k)}="${esc(v)}"`).join('');
    btn = action.href
      ? `<a class="${cls}" href="${esc(action.href)}"${action.action ? ` data-action="${esc(action.action)}"` : ''}${attrs}>${esc(action.label)}</a>`
      : `<button type="button" class="${cls}" data-action="${esc(action.action || '')}"${attrs}>${esc(action.label)}</button>`;
  }
  return `<div class="state-container empty-state${compact ? ' empty-state-compact' : ''}" role="status">${emptyIllustration(variant)}<h3 class="state-title">${t}</h3>${description ? `<p class="state-desc">${esc(description)}</p>` : ''}${btn}</div>`;
}
