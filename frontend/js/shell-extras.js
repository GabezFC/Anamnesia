// shell-extras.js — app-wide chrome that belongs to no single page:
//   * /health `warnings` banner (dismissible; closes pending item E1)
//   * Ctrl+K command palette (only when focus is OUTSIDE a terminal — xterm owns every key)
// Every value coming from the server goes through esc() before reaching innerHTML.
import { esc } from './format.js';

/* ------------------------------------------------------------- health banner */
const DISMISS_KEY = 'anamnesia.health.dismissed.v1';

function readDismissed() {
  try {
    const v = JSON.parse(sessionStorage.getItem(DISMISS_KEY) || '[]');
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : [];
  } catch { return []; }
}
const keyOf = (w) => `${w.component || ''}:${w.code || ''}`;

/** warnings: [{component, code, message, hint}]. Renders into #health-banner (role=region, polite). */
export function renderHealthBanner(warnings) {
  const box = document.querySelector('#health-banner');
  if (!box) return;
  const dismissed = new Set(readDismissed());
  const list = (Array.isArray(warnings) ? warnings : [])
    .filter((w) => w && typeof w === 'object' && !dismissed.has(keyOf(w)));
  if (!list.length) { box.innerHTML = ''; box.hidden = true; return; }
  box.hidden = false;
  const itemsHtml = list.map((w) => `
    <li class="hb-item">
      <span class="hb-comp">${esc(w.component || 'sistema')}</span>
      <span class="hb-msg">${esc(w.message || w.code || 'aviso')}</span>
      ${w.hint ? `<span class="hb-hint">${esc(w.hint)}</span>` : ''}
      <button type="button" class="hb-close" data-hb-key="${esc(keyOf(w))}"
        aria-label="Dispensar aviso: ${esc(w.component || '')} ${esc(w.code || '')}">×</button>
    </li>`).join('');
  box.innerHTML = `<div class="hb-title">Avisos do servidor (${list.length})</div><ul class="hb-list">${itemsHtml}</ul>`;
  box.querySelectorAll('[data-hb-key]').forEach((b) => b.addEventListener('click', () => {
    const d = readDismissed();
    d.push(b.dataset.hbKey);
    try { sessionStorage.setItem(DISMISS_KEY, JSON.stringify(d)); } catch { /* private mode */ }
    renderHealthBanner(list.filter((w) => keyOf(w) !== b.dataset.hbKey));
    document.querySelector('#main')?.focus();
  }));
}

/* ------------------------------------------------------------- command palette */
let paletteEl = null;
let lastFocus = null;

/** True when the key event originates inside a terminal (xterm's hidden textarea). */
export const inTerminal = (t) => Boolean(t && t.closest && t.closest('.xterm, .ws-term'));

export function closePalette() {
  if (!paletteEl) return;
  paletteEl.remove();
  paletteEl = null;
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

/** actions: [{id, label, hint?, run()}] */
export function openPalette(actions) {
  if (paletteEl) { closePalette(); return; }
  lastFocus = document.activeElement;
  paletteEl = document.createElement('div');
  paletteEl.className = 'palette-scrim';
  paletteEl.innerHTML = `
    <div class="palette" role="dialog" aria-modal="true" aria-label="Paleta de comandos">
      <input id="palette-q" type="text" autocomplete="off" spellcheck="false"
        placeholder="Digite um comando… (Esc fecha)" aria-label="Filtrar comandos"
        role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list">
      <ul id="palette-list" role="listbox"></ul>
    </div>`;
  document.body.appendChild(paletteEl);
  const q = paletteEl.querySelector('#palette-q');
  const ul = paletteEl.querySelector('#palette-list');
  let sel = 0;
  let shown = actions;
  const paint = () => {
    ul.innerHTML = shown.map((a, i) =>
      `<li role="option" id="pal-${i}" aria-selected="${i === sel}" data-i="${i}">${esc(a.label)}`
      + `${a.hint ? `<span class="pal-hint">${esc(a.hint)}</span>` : ''}</li>`).join('')
      || '<li class="pal-empty" role="presentation">Nenhum comando</li>';
    q.setAttribute('aria-activedescendant', shown.length ? `pal-${sel}` : '');
  };
  const run = (i) => { const a = shown[i]; closePalette(); if (a) a.run(); };
  q.addEventListener('input', () => {
    const s = q.value.trim().toLowerCase();
    shown = actions.filter((a) => a.label.toLowerCase().includes(s));
    sel = 0; paint();
  });
  paletteEl.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { ev.preventDefault(); closePalette(); }
    else if (ev.key === 'ArrowDown') { ev.preventDefault(); sel = Math.min(shown.length - 1, sel + 1); paint(); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); sel = Math.max(0, sel - 1); paint(); }
    else if (ev.key === 'Enter') { ev.preventDefault(); run(sel); }
    else if (ev.key === 'Tab') { ev.preventDefault(); }       // focus trap: the input is the only stop
  });
  ul.addEventListener('click', (ev) => { const li = ev.target.closest('[data-i]'); if (li) run(Number(li.dataset.i)); });
  paletteEl.addEventListener('mousedown', (ev) => { if (ev.target === paletteEl) closePalette(); });
  paint();
  q.focus();
}

/** Install the global Ctrl+K handler. getActions() is called lazily each time. */
export function installPalette(getActions) {
  document.addEventListener('keydown', (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== 'k' || ev.altKey || ev.shiftKey) return;
    if (inTerminal(ev.target)) return;                         // never steal keys from the terminal
    ev.preventDefault();
    openPalette(getActions());
  });
}
