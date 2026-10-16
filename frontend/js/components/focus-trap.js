/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-027 (AUD-034): focus trap + retorno de foco para diálogos modais.
 */

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function focusableIn(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => !el.hidden && el.getClientRects().length > 0 && el.getAttribute('aria-hidden') !== 'true');
}

/**
 * Prende o Tab/Shift+Tab dentro de `dialog` e devolve `release()`.
 * Opcional: `inertRoot` (ex.: #app) recebe `inert` enquanto aberto; `returnTo` (elemento ou função)
 * recebe o foco ao liberar; `initial` recebe o foco ao prender (explícito, sem depender de `autofocus`).
 */
export function trapFocus(dialog, { returnTo = null, initial = null, inertRoot = null } = {}) {
  const prev = returnTo || document.activeElement;
  if (inertRoot) inertRoot.inert = true;
  const onKey = (e) => {
    if (e.key !== 'Tab') return;
    const items = focusableIn(dialog);
    if (!items.length) { e.preventDefault(); dialog.focus?.(); return; }
    const first = items[0]; const last = items[items.length - 1];
    const active = document.activeElement;
    if (!dialog.contains(active)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
  };
  dialog.addEventListener('keydown', onKey);
  const start = typeof initial === 'function' ? initial() : initial;
  (start || focusableIn(dialog)[0] || dialog).focus?.();
  let released = false;
  return function release({ restore = true } = {}) {
    if (released) return;
    released = true;
    dialog.removeEventListener('keydown', onKey);
    if (inertRoot) inertRoot.inert = false;
    if (!restore) return;
    const target = typeof prev === 'function' ? prev() : prev;
    if (target && target.isConnected && target.focus) target.focus();
  };
}

/** Seletor estável de um elemento (para recuperar o gatilho depois de um re-render). */
export function selectorFor(el) {
  if (!el || !el.getAttribute) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  const a = el.getAttribute('data-action');
  if (a) return `[data-action="${a}"]`;
  return null;
}
