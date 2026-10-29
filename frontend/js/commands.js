/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-027 (AUD-036/037/035): registro central de comandos + dispatcher único de atalhos.
 *
 * - `registerCommand({id,label,description,shortcut,category,permission,when,run,keywords})`:
 *   fonte única para a paleta (Ctrl+K), dicas <kbd> e documentação. Dicas de atalho são
 *   geradas do registro: não existe mais dica sem handler.
 * - O dispatcher (`installShortcutDispatcher`) ignora composição IME e campos editáveis,
 *   exceto atalhos com Ctrl/Cmd (que continuam valendo em qualquer lugar).
 *
 * Módulo puro (sem dependências de DOM na importação) para poder ser testado em Node.
 */

const registry = new Map();
const listeners = new Set();

const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '');

/** Registra (ou substitui) um comando. `label`/`description` podem ser string ou função (i18n lazy). */
export function registerCommand(cmd) {
  if (!cmd || !cmd.id || typeof cmd.run !== 'function') throw new Error('command needs id and run()');
  registry.set(cmd.id, { category: 'general', permission: null, when: null, keywords: '', ...cmd });
  listeners.forEach((fn) => fn());
  return cmd.id;
}

export function unregisterCommand(id) {
  const had = registry.delete(id);
  if (had) listeners.forEach((fn) => fn());
  return had;
}

export function onRegistryChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }

const text = (v) => (typeof v === 'function' ? v() : v) || '';

/** Comandos visíveis: `when()` verdadeiro e permissão concedida (`ctx.permissions` opcional). */
export function listCommands(ctx = {}) {
  const perms = ctx.permissions;
  return [...registry.values()]
    .filter((c) => !(ctx.forPalette && c.hidden))
    .filter((c) => (!c.when || c.when(ctx)) && (!c.permission || !perms || perms.has(c.permission)))
    .map((c) => ({ ...c, labelText: text(c.label), descriptionText: text(c.description), categoryText: text(c.categoryLabel) || c.category }));
}

export function getCommand(id) { return registry.get(id) || null; }

/** Normaliza "Ctrl+K", "Alt+Shift+1" → {ctrl,alt,shift,meta,key}. */
export function parseShortcut(spec) {
  const parts = String(spec || '').split('+').map((p) => p.trim()).filter(Boolean);
  const out = { ctrl: false, alt: false, shift: false, mod: false, key: '' };
  for (const p of parts) {
    const l = p.toLowerCase();
    if (l === 'ctrl' || l === 'control') out.ctrl = true;
    else if (l === 'mod' || l === 'cmd' || l === 'meta') out.mod = true;
    else if (l === 'alt' || l === 'option') out.alt = true;
    else if (l === 'shift') out.shift = true;
    else out.key = p.length === 1 ? p.toLowerCase() : l;
  }
  return out;
}

/** Texto para <kbd>: "Ctrl+K" (⌘ no macOS para Mod). */
export function shortcutLabel(spec) {
  if (!spec) return '';
  return String(spec).split('+').map((p) => {
    const l = p.trim().toLowerCase();
    if (l === 'mod') return isMac() ? '⌘' : 'Ctrl';
    return p.trim().length === 1 ? p.trim().toUpperCase() : p.trim();
  }).join('+');
}

function keyOf(ev) {
  // Dígitos por `code`: com Shift, `key` vira "!" etc.
  if (/^Digit\d$/.test(ev.code || '')) return ev.code.slice(5);
  return (ev.key || '').length === 1 ? ev.key.toLowerCase() : (ev.key || '').toLowerCase();
}

export function matchesShortcut(ev, spec) {
  const s = parseShortcut(spec);
  if (!s.key) return false;
  const wantCtrl = s.ctrl || (s.mod && !isMac());
  const wantMeta = s.mod && isMac();
  return !!ev.ctrlKey === wantCtrl && !!ev.metaKey === wantMeta && !!ev.altKey === s.alt && !!ev.shiftKey === s.shift && keyOf(ev) === s.key;
}

/** Atalho com Ctrl/Cmd: continua valendo mesmo em campos editáveis e no terminal. */
export function usesCtrlOrMeta(spec) {
  const s = parseShortcut(spec);
  return s.ctrl || s.mod;
}

/** Alvo onde digitar não deve disparar atalhos "soltos" (campos, contenteditable). */
export function isEditableTarget(t) {
  if (!t || !t.closest) return false;
  if (t.isContentEditable) return true;
  const tag = t.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') return !/^(button|checkbox|radio|submit|reset|range|file|image)$/i.test(t.type || 'text');
  return !!t.closest('[contenteditable=""],[contenteditable="true"],[role="textbox"],[role="combobox"]');
}

/** Primeiro comando cujo atalho casa com o evento e que pode rodar no contexto (guardas incluídas). */
export function findCommandForEvent(ev, ctx = {}) {
  if (!ev || ev.isComposing || ev.keyCode === 229) return null;
  const editable = isEditableTarget(ev.target);
  for (const c of listCommands(ctx)) {
    if (!c.shortcut || !matchesShortcut(ev, c.shortcut)) continue;
    if (editable && !usesCtrlOrMeta(c.shortcut)) continue;
    return c;
  }
  return null;
}

export function isAppShortcut(ev, phase = 'down') {
  if (phase === 'peek') return false;
  const c = findCommandForEvent(ev, {});
  return !!c && usesCtrlOrMeta(c.shortcut);
}

/** Instala o ÚNICO handler global de atalhos. Devolve função de remoção. */
export function installShortcutDispatcher(target = window, getCtx = () => ({})) {
  const handler = (ev) => {
    const c = findCommandForEvent(ev, getCtx());
    if (!c) return;
    ev.preventDefault();
    c.run({ event: ev, source: 'shortcut' });
  };
  target.addEventListener('keydown', handler);
  return () => target.removeEventListener('keydown', handler);
}

/** Texto de busca de um comando para o filtro da paleta. */
export function commandHaystack(c) {
  return `${c.labelText} ${c.descriptionText} ${c.keywords || ''}`.toLowerCase();
}

export function filterCommands(cmds, query) {
  const q = String(query || '').toLowerCase().trim();
  if (!q) return cmds;
  const words = q.split(/\s+/);
  return cmds.filter((c) => { const h = commandHaystack(c); return words.every((w) => h.includes(w)); });
}
