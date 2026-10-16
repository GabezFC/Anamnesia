/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-028 (AUD-044): acessibilidade dos gráficos SVG.
 * - <details> "Ver dados" com <table> equivalente (alternativa tabular, sem depender de mouse nem cor);
 * - marcas (pontos/barras/fatias) focáveis com roving tabindex (←/→/↑/↓/Home/End) que reutilizam o
 *   tooltip do hover (disparam o mesmo onmouseenter/onmouseleave) e têm nome acessível.
 */
import { I18N } from '../i18n.js';

const escHtml = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/** HTML da tabela alternativa. `head`: string[]; `rows`: (string|number)[][] */
export function dataTableHtml(caption, head, rows) {
  const th = head.map((h, i) => `<th scope="col"${i === 0 ? '' : ' class="chart-data-num"'}>${escHtml(h)}</th>`).join('');
  const tr = rows.map((r) => `<tr><th scope="row">${escHtml(r[0])}</th>${r.slice(1).map((c) => `<td class="chart-data-num tabular">${escHtml(c)}</td>`).join('')}</tr>`).join('');
  return `<table class="chart-data-table"><caption class="sr-only">${escHtml(caption)}</caption><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
}

function fire(el, type) {
  const r = el.getBoundingClientRect();
  el.dispatchEvent(new MouseEvent(type, { clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: false }));
}

/**
 * @param {HTMLElement} container wrapper do gráfico (já com o SVG renderizado)
 * @param {{caption:string, head:string[], rows:any[][], marks:string, nameOf:(el:Element,i:number)=>string}} spec
 */
export function enhanceChart(container, spec) {
  const a = I18N.a11y;
  const svg = container.querySelector('svg.chart-svg');
  const wasOpen = !!container._chartDetailsOpen;
  if (svg) {
    svg.removeAttribute('aria-hidden');
    svg.setAttribute('role', 'group');
    if (!svg.getAttribute('aria-label')) svg.setAttribute('aria-label', spec.caption);
    const marks = [...svg.querySelectorAll(spec.marks)];
    marks.forEach((m, i) => {
      m.setAttribute('role', 'img');
      m.setAttribute('tabindex', i === 0 ? '0' : '-1');
      m.setAttribute('aria-label', spec.nameOf(m, i));
      m.addEventListener('focus', () => fire(m, 'mouseenter'));
      m.addEventListener('blur', () => fire(m, 'mouseleave'));
    });
    svg.addEventListener('keydown', (e) => {
      const i = marks.indexOf(e.target);
      if (i < 0) return;
      const k = e.key;
      let n = -1;
      if (k === 'ArrowRight' || k === 'ArrowDown') n = (i + 1) % marks.length;
      else if (k === 'ArrowLeft' || k === 'ArrowUp') n = (i - 1 + marks.length) % marks.length;
      else if (k === 'Home') n = 0;
      else if (k === 'End') n = marks.length - 1;
      else if (k === 'Escape') { e.target.blur(); return; }
      if (n < 0) return;
      e.preventDefault();
      marks.forEach((m, j) => m.setAttribute('tabindex', j === n ? '0' : '-1'));
      marks[n].focus();
    });
  }
  const det = document.createElement('details');
  det.className = 'chart-data-details';
  det.open = wasOpen;
  det.innerHTML = `<summary>${escHtml(a.viewData)}</summary>${dataTableHtml(a.chartTable + ': ' + spec.caption, spec.head, spec.rows)}`;
  det.addEventListener('toggle', () => { container._chartDetailsOpen = det.open; });
  container.appendChild(det);
}
