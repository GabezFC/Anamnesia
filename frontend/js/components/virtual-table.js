/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * VIRTUAL TABLE — tabela com virtualização por janela (altura de linha fixa).
 * Só as linhas visíveis (+ overscan) existem no DOM; o scroll é do próprio contêiner.
 *
 *   const vt = createVirtualTable({
 *     container,                      // HTMLElement onde a tabela é montada
 *     columns: [{ key, label, width?: '1fr'|'120px', align?: 'right', render?: (row, i) => htmlString }],
 *     rows,                           // array de objetos
 *     rowHeight: 40,                  // px, fixo (padrão 40)
 *     height: 420,                    // px da viewport de rolagem (padrão 420)
 *     overscan: 6,                    // linhas extras acima/abaixo
 *     rowKey: (row, i) => i,          // opcional
 *     onRowClick: (row, i, ev) => {}, // opcional
 *     emptyHtml: '',                  // HTML mostrado sem linhas (ex.: emptyState(...))
 *     ariaLabel: 'Chamadas',
 *   });
 *   vt.update(newRows);  vt.scrollToTop();  vt.destroy();  vt.getVisibleRange() → {start,end}
 *
 * `render` DEVE devolver HTML já escapado (use esc()); sem `render`, o valor é escapado aqui.
 * Células com [data-action] funcionam com delegação no ancestral (as linhas são re-criadas ao rolar).
 */
import { esc } from '../format.js';

export function computeRange(scrollTop, viewportH, rowHeight, total, overscan = 6) {
  if (total <= 0 || rowHeight <= 0) return { start: 0, end: 0 };
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const visible = Math.ceil(viewportH / rowHeight);
  return {
    start: Math.max(0, first - overscan),
    end: Math.min(total, first + visible + overscan),
  };
}

export function createVirtualTable({
  container, columns = [], rows = [], rowHeight = 40, height = 420, overscan = 6,
  rowKey = null, onRowClick = null, emptyHtml = '', ariaLabel = '',
} = {}) {
  if (!container) throw new Error('createVirtualTable: container é obrigatório');
  const RH = Math.max(1, Number(rowHeight) || 40);
  let data = Array.isArray(rows) ? rows : [];
  let raf = 0;
  let lastKey = '';

  const tpl = columns.map((c) => c.width || '1fr').join(' ');
  container.innerHTML = `
    <div class="vtable" role="table" aria-label="${esc(ariaLabel)}" aria-rowcount="${data.length}">
      <div class="vtable-head" role="row" style="grid-template-columns:${tpl}">
        ${columns.map((c) => `<div class="vtable-cell vtable-th${c.align === 'right' ? ' is-right' : ''}" role="columnheader">${esc(c.label ?? c.key ?? '')}</div>`).join('')}
      </div>
      <div class="vtable-viewport" style="height:${Number(height) || 420}px" tabindex="0">
        <div class="vtable-spacer"></div>
        <div class="vtable-empty" hidden></div>
      </div>
    </div>`;
  const root = container.querySelector('.vtable');
  const viewport = container.querySelector('.vtable-viewport');
  const spacer = container.querySelector('.vtable-spacer');
  const emptyEl = container.querySelector('.vtable-empty');

  function cell(c, row, i) {
    const html = c.render ? c.render(row, i) : esc(row?.[c.key]);
    return `<div class="vtable-cell${c.align === 'right' ? ' is-right' : ''}" role="cell">${html}</div>`;
  }

  function paint(force = false) {
    raf = 0;
    const { start, end } = computeRange(viewport.scrollTop, viewport.clientHeight || Number(height) || 420, RH, data.length, overscan);
    const key = `${start}:${end}:${data.length}`;
    if (!force && key === lastKey) return;
    lastKey = key;
    let html = '';
    for (let i = start; i < end; i += 1) {
      const row = data[i];
      html += `<div class="vtable-row" role="row" aria-rowindex="${i + 2}" data-row-index="${i}"${rowKey ? ` data-row-key="${esc(rowKey(row, i))}"` : ''} style="grid-template-columns:${tpl};height:${RH}px;transform:translateY(${i * RH}px)">${columns.map((c) => cell(c, row, i)).join('')}</div>`;
    }
    // reaproveita o spacer (altura total) e substitui apenas as linhas
    spacer.innerHTML = html;
  }

  function schedule() { if (!raf) raf = requestAnimationFrame(() => paint()); }
  function onClick(ev) {
    if (!onRowClick) return;
    const el = ev.target.closest('.vtable-row');
    if (!el || !spacer.contains(el)) return;
    const i = Number(el.dataset.rowIndex);
    onRowClick(data[i], i, ev);
  }

  function layout() {
    spacer.style.height = `${data.length * RH}px`;
    root.setAttribute('aria-rowcount', String(data.length + 1));
    if (data.length === 0 && emptyHtml) { emptyEl.innerHTML = emptyHtml; emptyEl.hidden = false; } else { emptyEl.hidden = true; emptyEl.innerHTML = ''; }
  }

  viewport.addEventListener('scroll', schedule, { passive: true });
  viewport.addEventListener('click', onClick);
  const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(schedule) : null;
  ro?.observe(viewport);

  layout();
  paint(true);

  return {
    el: root,
    update(newRows) { data = Array.isArray(newRows) ? newRows : []; layout(); paint(true); },
    scrollToTop() { viewport.scrollTop = 0; paint(true); },
    getVisibleRange() { return computeRange(viewport.scrollTop, viewport.clientHeight || Number(height) || 420, RH, data.length, 0); },
    getRowCount() { return data.length; },
    destroy() {
      if (raf) cancelAnimationFrame(raf);
      viewport.removeEventListener('scroll', schedule);
      viewport.removeEventListener('click', onClick);
      ro?.disconnect();
      container.innerHTML = '';
    },
  };
}
