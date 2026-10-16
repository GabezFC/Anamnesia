/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-027 (AUD-035/036): comandos do app registrados no registro central.
 * Só existe <kbd> para atalho que tem handler (o dispatcher global lê este mesmo registro).
 */
import { I18N } from './i18n.js';
import { registerCommand } from './commands.js';

const NAV = [
  ['nav-workspace', '#/workspace', 'goWorkspace', 'terminal', 'Alt+Shift+1', 'workspace ide terminal'],
  ['nav-connections', '#/connections', 'goConnections', 'connections', 'Alt+Shift+2', 'conexoes connections'],
  ['nav-config', '#/config', 'goConfig', 'config', 'Alt+Shift+3', 'configuracao settings config'],
  ['nav-costs', '#/costs', 'goCosts', 'costs', 'Alt+Shift+4', 'custos costs ledger'],
  ['nav-memory', '#/memory', 'goMemory', 'database', 'Alt+Shift+5', 'memoria memory'],
  ['nav-decision', '#/decision', 'goDecision', 'cpu', 'Alt+Shift+6', 'decision engine decisao jev laya hybrid adaptive avaliacao'],
];

/** `api`: { navigate(hash), toggleTheme(), toggleLang(), openPalette(), newTerminal() } fornecido pelo app.js. */
export function registerAppCommands(api) {
  const cat = () => I18N.palette.catNav;
  NAV.forEach(([id, hash, key, ico, shortcut, keywords]) => registerCommand({
    id, label: () => I18N.palette[key], category: 'nav', categoryLabel: cat, icon: ico, shortcut, keywords,
    run: () => api.navigate(hash),
  }));
  registerCommand({
    id: 'nav-lab', label: () => I18N.palette.goLab, category: 'nav', categoryLabel: cat, icon: 'scale', badge: 'Lab',
    keywords: 'laboratorio compare comparar benchmark', run: () => api.navigate('#/compare/overview'),
  });
  const sys = () => I18N.palette.catSystem;
  registerCommand({
    id: 'palette-toggle', label: () => I18N.palette.openPalette, category: 'system', categoryLabel: sys, icon: 'search',
    shortcut: 'Mod+K', keywords: 'ctrl k busca search', run: () => api.openPalette(),
    hidden: true,
  });
  registerCommand({
    id: 'new-terminal', label: () => I18N.palette.newTerminal, category: 'system', categoryLabel: sys, icon: 'plus',
    keywords: 'terminal novo new perfil profile', run: () => api.newTerminal(),
  });
  registerCommand({
    id: 'toggle-theme', label: () => I18N.app.paletteToggleTheme, category: 'system', categoryLabel: sys, icon: 'sun',
    keywords: 'tema theme dark light escuro claro', run: () => api.toggleTheme(),
  });
  registerCommand({
    id: 'toggle-lang', label: () => I18N.app.paletteToggleLang, category: 'system', categoryLabel: sys, icon: 'info',
    keywords: 'idioma language pt en', run: () => api.toggleLang(),
  });
}
