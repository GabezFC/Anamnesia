/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-028 (AUD-039/040): navegação por teclado do padrão APG "Tabs" (roving tabindex, ←/→/Home/End).
 */

/** Tecla -> índice da próxima aba (ou -1 se a tecla não navega). Ativação automática: o chamador troca a aba. */
export function nextTabIndex(key, index, count, { vertical = false } = {}) {
  if (!count) return -1;
  const prev = vertical ? 'ArrowUp' : 'ArrowLeft';
  const next = vertical ? 'ArrowDown' : 'ArrowRight';
  if (key === next) return (index + 1) % count;
  if (key === prev) return (index - 1 + count) % count;
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  return -1;
}

/**
 * Trata keydown numa tablist. `tabSelector` seleciona as abas (role=tab) dentro de `tablist`.
 * Devolve o elemento da aba alvo (já com foco) ou null. `activate(tabEl)` é chamado em seguida.
 */
export function handleTablistKey(e, tablist, tabSelector, activate) {
  const tab = e.target.closest && e.target.closest(tabSelector);
  if (!tab || !tablist.contains(tab) || e.altKey || e.ctrlKey || e.metaKey) return null;
  const tabs = [...tablist.querySelectorAll(tabSelector)];
  const i = nextTabIndex(e.key, tabs.indexOf(tab), tabs.length);
  if (i < 0) return null;
  e.preventDefault();
  const target = tabs[i];
  activate(target);
  return target;
}

/** Id estável de aba/painel. */
export const tabId = (prefix, id) => `${prefix}-tab-${id}`;
export const panelId = (prefix) => `${prefix}-panel`;
