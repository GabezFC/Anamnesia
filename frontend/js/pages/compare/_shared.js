/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: helpers compartilhados das abas (estado honesto, formatação, selo de procedência).
 * Regra (ANA-200): toda métrica ausente é `null` e vira o texto "indisponível" — nunca 0, nunca mock.
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtMs, fmtPct, fmtCost, num } from '../../format.js';
import { lab, ensureLab } from '../../lab-data.js';
import { emptyState } from '../../components/empty-state.js';
import { skeletonKpis, skeletonCard, loadingBlock } from '../../components/skeleton.js';

/** "indisponível" estilizado (texto + aria), usado no lugar de qualquer valor nulo. */
export const na = () => `<span class="lab-na" title="${esc(I18N.lab.naHint)}">${esc(I18N.app.unavailable)}</span>`;

/** Valor formatado ou "indisponível". `f` recebe o número. */
export function val(v, f = fmtNum) {
  return num(v) === null ? na() : esc(f(v));
}
export const vTok = (v) => val(v, (x) => `${fmtNum(x, 0)} tok`);
export const vMs = (v) => val(v, fmtMs);
export const vPct = (v) => val(v, (x) => fmtPct(x, 1));
export const vCost = (v) => val(v, fmtCost);

/** Selo de procedência por KPI: real (medido no benchmark.db) | n/d. */
export function originBadge(v) {
  const real = num(v) !== null;
  return `<span class="badge-origin ${real ? 'badge-origin-measured' : 'badge-origin-unavailable'}">${esc(real ? I18N.lab.badgeReal : I18N.lab.badgeNa)}</span>`;
}

/** Bloco de estado quando os dados do laboratório não estão prontos; null se estiver tudo ok. */
export function stateBlock() {
  const t = I18N.lab;
  switch (lab.status) {
    case 'idle':
    case 'loading':
      return loadingBlock(skeletonKpis(4) + skeletonCard({ lines: 4 }), I18N.app.loading);
    case 'unavailable':
      return emptyState({ title: t.unavailableTitle, description: t.unavailableDesc, variant: 'error', action: { label: I18N.app.errorRetry, action: 'lab-reload', kind: 'secondary' } });
    case 'error':
      return emptyState({ title: t.errorTitle, description: lab.error, variant: 'error', action: { label: I18N.app.errorRetry, action: 'lab-reload', kind: 'secondary' } });
    case 'empty':
      return emptyState({ title: t.emptyTitle, description: t.emptyDesc, variant: 'data' });
    default:
      return null;
  }
}

export function header(title, desc) {
  return `<div class="lab-section-header"><div><h2 class="lab-section-title">${esc(title)}</h2><p class="lab-section-desc">${esc(desc)}</p></div></div>`;
}

/**
 * Padrão de aba: render() síncrono por estado; mount() dispara ensureLab() e repinta.
 * `body()` só é chamado com lab.status === 'ready'. `after(root)` monta gráficos/handlers.
 */
export function makeTab({ title, desc, body, after, cleanup }) {
  const view = () => `<div class="lab-view-container">${header(I18N.lab[title], I18N.lab[desc])}${stateBlock() ?? body()}</div>`;
  const state = { root: null };
  const paint = (root) => {
    cleanup?.(root);
    root.innerHTML = view();
    if (lab.status === 'ready') after?.(root);
  };
  return {
    render: () => view(),
    mount(root) {
      state.root = root;
      const onClick = (e) => {
        if (e.target.closest('[data-action="lab-reload"]')) ensureLab(true).then(() => root.isConnected && paint(root));
      };
      root.addEventListener('click', onClick);
      root._tabCleanup = () => { root.removeEventListener('click', onClick); cleanup?.(root); };
      if (lab.status === 'ready' || lab.status === 'empty') { if (lab.status === 'ready') after?.(root); return; }
      ensureLab().then(() => root.isConnected && paint(root));
    },
    unmount(root) { if (root?._tabCleanup) { root._tabCleanup(); delete root._tabCleanup; } },
  };
}

export const pipeName = (id) => (I18N.lab.pipelines && I18N.lab.pipelines[id]) || id;

/** Tabela acessível: <caption> visível só a leitores de tela, th com scope. */
export function table({ caption, cols, rows, empty = '' }) {
  if (!rows.length) return empty;
  return `<div class="table-container" tabindex="0" role="region" aria-label="${esc(caption)}"><table class="table">
    <caption class="sr-only">${esc(caption)}</caption>
    <thead><tr>${cols.map((c) => `<th scope="col"${c.num ? ' class="num-col"' : ''}>${esc(c.label)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td${c.num ? ' class="num-col tabular font-mono"' : ''}>${c.html(r)}</td>`).join('')}</tr>`).join('')}</tbody>
  </table></div>`;
}
