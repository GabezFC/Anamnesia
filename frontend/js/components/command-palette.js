/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-027 (AUD-001/033/034): paleta de comandos acessível (padrão combobox + listbox, APG).
 *
 * - Renderiza num container PRÓPRIO (#palette-root, irmão de #app): abrir/fechar não re-renderiza o app.
 * - Foco permanece no input; a opção ativa é exposta via aria-activedescendant.
 * - ↑/↓/Home/End movem a opção ativa, Enter executa, Esc fecha; Tab fica preso no diálogo.
 * - Região aria-live anuncia a contagem de resultados.
 * - Ao fechar, o foco volta ao gatilho. #app recebe `inert` enquanto a paleta está aberta.
 */
import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc } from '../format.js';
import { listCommands, filterCommands, shortcutLabel } from '../commands.js';
import { trapFocus } from './focus-trap.js';

let root = null;
let release = null;
let state = { open: false, query: '', items: [], active: 0, ctx: {} };

function ensureRoot() {
  if (root && root.isConnected) return root;
  root = document.getElementById('palette-root');
  if (!root) {
    root = document.createElement('div');
    root.id = 'palette-root';
    document.body.appendChild(root);
  }
  return root;
}

export function isPaletteOpen() { return state.open; }

const groupOf = (c) => c.categoryText || c.category;

function renderOptions() {
  const groups = new Map();
  state.items.forEach((c, i) => {
    const g = groupOf(c);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push({ c, i });
  });
  if (!state.items.length) return `<div class="command-palette-empty" role="presentation">${esc(I18N.palette.empty)}</div>`;
  let gi = 0;
  return [...groups].map(([name, rows]) => {
    const gid = `palette-group-${gi++}`;
    const opts = rows.map(({ c, i }) => {
      const sel = i === state.active;
      const kbd = c.shortcut ? `<kbd>${esc(shortcutLabel(c.shortcut))}</kbd>` : '';
      const badge = c.badge ? `<span class="badge-seal badge-seal-experimental">${esc(c.badge)}</span>` : '';
      return `<div class="command-palette-item ${sel ? 'is-selected' : ''}" id="palette-opt-${i}" role="option" aria-selected="${sel}" data-index="${i}" data-cmd="${esc(c.id)}">
        <div class="command-palette-item-left">${icon(c.icon || 'info', '', 14)}<span>${esc(c.labelText)}</span></div>${badge}${kbd}</div>`;
    }).join('');
    return `<div role="group" aria-labelledby="${gid}"><div class="command-palette-group-title" id="${gid}" role="presentation">${esc(name)}</div>${opts}</div>`;
  }).join('');
}

function announce() {
  const live = root.querySelector('[data-bind="palette-live"]');
  if (live) live.textContent = state.items.length ? I18N.palette.results.replace('{n}', String(state.items.length)) : I18N.palette.empty;
}

function paintList() {
  const list = root.querySelector('[data-bind="palette-list"]');
  const input = root.querySelector('.command-palette-input');
  if (!list || !input) return;
  list.innerHTML = renderOptions();
  input.setAttribute('aria-activedescendant', state.items.length ? `palette-opt-${state.active}` : '');
  announce();
}

function setActive(i) {
  if (!state.items.length) return;
  const n = state.items.length;
  state.active = (i + n) % n;
  root.querySelectorAll('[role="option"]').forEach((el) => {
    const on = Number(el.dataset.index) === state.active;
    el.classList.toggle('is-selected', on);
    el.setAttribute('aria-selected', String(on));
    if (on) el.scrollIntoView?.({ block: 'nearest' });
  });
  root.querySelector('.command-palette-input').setAttribute('aria-activedescendant', `palette-opt-${state.active}`);
}

function runActive(index = state.active) {
  const cmd = state.items[index];
  if (!cmd) return;
  closePalette({ restoreFocus: !cmd.keepsFocusAway });
  cmd.run({ source: 'palette' });
}

function onKeydown(e) {
  if (e.isComposing) return;
  const k = e.key;
  if (k === 'ArrowDown') { e.preventDefault(); setActive(state.active + 1); }
  else if (k === 'ArrowUp') { e.preventDefault(); setActive(state.active - 1); }
  else if (k === 'Home' && e.target.matches('.command-palette-input')) { e.preventDefault(); setActive(0); }
  else if (k === 'End' && e.target.matches('.command-palette-input')) { e.preventDefault(); setActive(state.items.length - 1); }
  else if (k === 'Enter') { e.preventDefault(); runActive(); }
  else if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); closePalette(); }
}

function onInput(e) {
  state.query = e.target.value;
  state.items = filterCommands(listCommands({ ...state.ctx, forPalette: true }), state.query);
  state.active = 0;
  paintList();
}

function onClick(e) {
  if (e.target.classList.contains('command-palette-backdrop')) { closePalette(); return; }
  const opt = e.target.closest('[role="option"]');
  if (opt) runActive(Number(opt.dataset.index));
}

function onHover(e) {
  const opt = e.target.closest('[role="option"]');
  if (opt && Number(opt.dataset.index) !== state.active) setActive(Number(opt.dataset.index));
}

/** Abre a paleta (idempotente). `ctx` é repassado a when()/permission dos comandos. */
export function openPalette(ctx = {}) {
  if (state.open) return;
  const host = ensureRoot();
  const trigger = document.activeElement;
  state = { open: true, query: '', items: filterCommands(listCommands({ ...ctx, forPalette: true }), ''), active: 0, ctx };
  host.innerHTML = `
    <div class="command-palette-backdrop is-active">
      <div class="command-palette-dialog" role="dialog" aria-modal="true" aria-label="${esc(I18N.palette.title)}" tabindex="-1">
        <div class="command-palette-input-wrap">
          ${icon('search', '', 16)}
          <input type="text" class="command-palette-input" role="combobox" aria-expanded="true" aria-controls="palette-listbox"
            aria-autocomplete="list" aria-activedescendant="" autocomplete="off" spellcheck="false"
            placeholder="${esc(I18N.palette.placeholder)}" aria-label="${esc(I18N.palette.inputLabel)}" />
          <kbd>Esc</kbd>
        </div>
        <div class="command-palette-list" id="palette-listbox" role="listbox" aria-label="${esc(I18N.palette.listLabel)}" data-bind="palette-list"></div>
        <div class="sr-only" role="status" aria-live="polite" data-bind="palette-live"></div>
      </div>
    </div>`;
  const dialog = host.querySelector('.command-palette-dialog');
  const input = host.querySelector('.command-palette-input');
  const appEl = document.getElementById('app');
  dialog.addEventListener('keydown', onKeydown);
  input.addEventListener('input', onInput);
  host.querySelector('.command-palette-backdrop').addEventListener('click', onClick);
  host.querySelector('[data-bind="palette-list"]').addEventListener('mousemove', onHover);
  paintList();
  release = trapFocus(dialog, { returnTo: trigger, initial: input, inertRoot: appEl });
}

export function closePalette({ restoreFocus = true } = {}) {
  if (!state.open) return;
  state.open = false;
  const rel = release; release = null;
  if (root) root.innerHTML = '';
  if (rel) rel({ restore: restoreFocus });
}

export function togglePalette(ctx) { if (state.open) closePalette(); else openPalette(ctx); }
