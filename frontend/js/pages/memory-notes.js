/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAM-029 — MEMÓRIA: gerenciador de notas salvas (aba "Notas" de #/memory).
 * Rotas: /api/memory/notes* (CRUD, history/diff/rollback), /trash, /consolidate, /export.jsonl, /import.
 * Nada é mock: tudo vem do backend local; erro/offline viram estados explícitos.
 * Reutiliza: focus-trap (diálogos), paleta de comandos (registerCommand), tokens/CSS de components.css.
 * Tudo que vem do backend passa por esc().
 */
import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc, fmtDate } from '../format.js';
import {
  memListNotes, memGetNote, memCreateNote, memUpdateNote, memDeleteNote, memHistory, memDiff, memRollback,
  memTrash, memRestore, memConsolidate, memExportJsonl, memImportJsonl, isUnavailable,
} from '../anamnesia-api.js';
import { skeletonTable, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';
import { trapFocus } from '../components/focus-trap.js';
import { registerCommand, unregisterCommand } from '../commands.js';

export const KINDS = ['decision', 'fact', 'preference', 'task', 'episodic'];
export const STATUSES = ['active', 'superseded', 'archived'];
export const PAGE_SIZE = 100;

/* ------------------------------------------------------------------ helpers puros (testados em node) */
/** "a, b ,,a" -> ['a','b'] (sem vazios nem duplicatas, ordem preservada). */
export function parseTags(s) {
  const out = [];
  for (const t of String(s ?? '').split(',').map((x) => x.trim()).filter(Boolean)) if (!out.includes(t)) out.push(t);
  return out;
}

/** Filtra a lista (client-side; o conteúdo completo é buscado na aba Busca). */
export function filterNotes(notes, { q = '', project = '', kind = '', status = '' } = {}) {
  const needle = String(q).trim().toLowerCase();
  return (notes || []).filter((n) => {
    if (project && (n.project || '') !== project) return false;
    if (kind && (n.kind || '') !== kind) return false;
    if (status && (n.status || 'active') !== status) return false;
    if (!needle) return true;
    const hay = [n.title, n.id, n.project, n.source_agent, n.kind, ...(n.tags || [])].filter(Boolean).join(' ').toLowerCase();
    return hay.includes(needle);
  });
}

/** Mais recentes primeiro (campo `updated` ISO; ausente vai para o fim). */
export function sortNotes(notes) {
  return [...(notes || [])].sort((a, b) => String(b.updated || b.created || '').localeCompare(String(a.updated || a.created || '')));
}

/** Corpo para POST/PUT a partir dos campos do formulário; `error` = chave i18n do primeiro problema. */
export function buildNotePayload(f, { create = false } = {}) {
  const title = String(f.title ?? '').trim();
  const content = String(f.content ?? '');
  if (!title) return { error: 'errTitle' };
  if (title.length > 200) return { error: 'errTitleLen' };
  if (!content.trim()) return { error: 'errContent' };
  const body = { title, content, tags: parseTags(f.tags) };
  if (f.kind) body.kind = String(f.kind);
  if (create && String(f.project ?? '').trim()) body.project = String(f.project).trim();
  return { body };
}

/** Linhas de um diff unificado com classe semântica (o prefixo +/- continua no texto: cor nunca é o único sinal). */
export function classifyDiff(text) {
  return String(text ?? '').split('\n').filter((l, i, a) => !(i === a.length - 1 && l === '')).map((l) => ({
    text: l,
    cls: l.startsWith('+++') || l.startsWith('---') ? 'meta' : l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : 'ctx',
  }));
}

/** Valida um JSONL antes de enviar: conta linhas e acusa a primeira inválida (a validação final é do servidor). */
export function inspectJsonl(text) {
  const lines = String(text ?? '').split(/\r?\n/).filter((l) => l.trim());
  for (let i = 0; i < lines.length; i += 1) {
    try { const o = JSON.parse(lines[i]); if (!o || typeof o !== 'object' || Array.isArray(o)) throw new Error('obj'); } catch { return { count: lines.length, badLine: i + 1 }; }
  }
  return { count: lines.length, badLine: 0 };
}

/** Resumo do plano de consolidate: nº de grupos e de notas que seriam marcadas superseded. */
export function summarizePlan(res) {
  const groups = Array.isArray(res?.groups) ? res.groups : [];
  return { groups: groups.length, notes: groups.reduce((s, g) => s + (g.supersede || []).length, 0) };
}

/** Snapshot id (ns desde a época) -> epoch segundos. */
export const versionEpoch = (v) => { const n = Number(v); return Number.isFinite(n) ? Math.floor(n / 1e9) : null; };
const isoEpoch = (s) => { const t = Date.parse(s || ''); return Number.isNaN(t) ? null : Math.floor(t / 1000); };

/* ------------------------------------------------------------------ estado */
const st = {
  list: { status: 'idle', notes: [], error: '' }, // idle | loading | ok | error | offline
  f: { q: '', project: '', kind: '', status: '' },
  shown: PAGE_SIZE,
  trash: { open: false, status: 'idle', items: [], error: '' },
  busy: false,
  loaded: false,
};
const tn = () => I18N.memory.notes;
const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
const errText = (e) => (isUnavailable(e) ? tn().offlineDesc : (e && (e.detail || e.message)) || String(e));
const classify = (e) => (isUnavailable(e) ? 'offline' : 'error');

/* ------------------------------------------------------------------ marcação */
const statusBadge = (s) => {
  const v = s || 'active';
  const cls = v === 'active' ? 'badge-origin-measured' : v === 'superseded' ? 'badge-origin-estimated' : 'badge-origin-unavailable';
  return `<span class="badge-origin ${cls}">${esc(tn().status[v] || v)}</span>`;
};

function toolbarHtml() {
  const t = tn();
  const projects = [...new Set(st.list.notes.map((n) => n.project).filter(Boolean))].sort();
  const dis = st.busy ? 'disabled' : '';
  return `
    <div class="mem-notes-toolbar" role="toolbar" aria-label="${esc(t.toolbar)}">
      <button type="button" class="btn btn-primary btn-sm" data-act="new" ${dis}>${icon('plus', '', 13)} ${esc(t.newNote)}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-act="consolidate" ${dis}>${icon('refresh', '', 13)} ${esc(t.consolidate)}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-act="export" ${dis}>${icon('download', '', 13)} ${esc(t.exportJsonl)}</button>
      <button type="button" class="btn btn-secondary btn-sm" data-act="import" ${dis}>${icon('file', '', 13)} ${esc(t.importJsonl)}</button>
      <input type="file" accept=".jsonl,.ndjson,application/x-ndjson,text/plain" class="sr-only" data-bind="mem-import-file" tabindex="-1" aria-label="${esc(t.importJsonl)}" />
      <button type="button" class="btn btn-ghost btn-sm" data-act="toggle-trash" aria-expanded="${st.trash.open}" aria-controls="mem-trash-panel">${icon('folder', '', 13)} ${esc(t.trash)}</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="reload" ${dis}>${icon('refresh', '', 13)} ${esc(t.reload)}</button>
    </div>
    <form class="mem-notes-filters" role="search" aria-label="${esc(t.filters)}" data-form="filter">
      <label class="memory-field memory-field-grow"><span>${esc(t.filterQ)}</span>
        <div class="input-control">${icon('search', '', 14)}<input type="search" data-filter="q" value="${esc(st.f.q)}" placeholder="${esc(t.filterQPh)}" autocomplete="off" /></div></label>
      <label class="memory-field"><span>${esc(t.filterProject)}</span>
        <select class="select-control" data-filter="project"><option value="">${esc(t.all)}</option>
          ${projects.map((p) => `<option value="${esc(p)}" ${p === st.f.project ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select></label>
      <label class="memory-field"><span>${esc(t.filterKind)}</span>
        <select class="select-control" data-filter="kind"><option value="">${esc(t.all)}</option>
          ${KINDS.map((k) => `<option value="${k}" ${k === st.f.kind ? 'selected' : ''}>${esc(t.kind[k])}</option>`).join('')}</select></label>
      <label class="memory-field"><span>${esc(t.filterStatus)}</span>
        <select class="select-control" data-filter="status"><option value="">${esc(t.all)}</option>
          ${STATUSES.map((k) => `<option value="${k}" ${k === st.f.status ? 'selected' : ''}>${esc(t.status[k])}</option>`).join('')}</select></label>
    </form>`;
}

function rowHtml(n) {
  const t = tn();
  const id = esc(n.id);
  const arch = (n.status || 'active') === 'archived';
  const ep = isoEpoch(n.updated || n.created);
  const label = (verb) => `${verb}: ${n.title || n.id}`;
  return `<tr>
    <td><button type="button" class="mem-note-title" data-act="edit" data-id="${id}" aria-label="${esc(label(t.edit))}">${esc(n.title || n.id)}</button>
      <div class="mem-note-sub">${n.project ? `<span>${esc(n.project)}</span>` : ''}${(n.tags || []).map((g) => `<span class="mem-tag">#${esc(g)}</span>`).join('')}</div></td>
    <td>${esc(n.kind ? (t.kind[n.kind] || n.kind) : '—')}</td>
    <td>${statusBadge(n.status)}</td>
    <td class="tabular">${esc(ep != null ? fmtDate(ep) : '—')}</td>
    <td class="mem-note-actions">
      <button type="button" class="btn btn-ghost btn-sm" data-act="edit" data-id="${id}" aria-label="${esc(label(t.edit))}">${esc(t.edit)}</button>
      <button type="button" class="btn btn-ghost btn-sm" data-act="history" data-id="${id}" aria-label="${esc(label(t.history))}">${esc(t.history)}</button>
      ${arch ? '' : `<button type="button" class="btn btn-ghost btn-sm" data-act="archive" data-id="${id}" aria-label="${esc(label(t.archive))}">${esc(t.archive)}</button>`}
      <button type="button" class="btn btn-danger btn-sm" data-act="delete" data-id="${id}" aria-label="${esc(label(t.del))}">${esc(t.del)}</button>
    </td></tr>`;
}

function listBody() {
  const t = tn();
  const l = st.list;
  if (l.status === 'idle' || l.status === 'loading') return loadingBlock(skeletonTable({ rows: 5, cols: 5 }), t.loading);
  if (l.status === 'offline') {
    return emptyState({ title: t.offlineTitle, description: `${t.offlineDesc} ${t.offlineHint}`, variant: 'error', compact: true })
      + `<div class="memory-actions"><button type="button" class="btn btn-secondary btn-sm" data-act="reload">${icon('refresh', '', 13)} ${esc(t.retry)}</button></div>`;
  }
  if (l.status === 'error') {
    return emptyState({ title: t.errorTitle, description: l.error, variant: 'error', compact: true })
      + `<div class="memory-actions"><button type="button" class="btn btn-secondary btn-sm" data-act="reload">${icon('refresh', '', 13)} ${esc(t.retry)}</button></div>`;
  }
  if (!l.notes.length) {
    return emptyState({ title: t.emptyTitle, description: t.emptyDesc, variant: 'data', compact: true })
      + `<div class="memory-actions"><button type="button" class="btn btn-primary btn-sm" data-act="new">${icon('plus', '', 13)} ${esc(t.newNote)}</button></div>`;
  }
  const rows = sortNotes(filterNotes(l.notes, st.f));
  if (!rows.length) {
    return emptyState({ title: t.noMatchTitle, description: t.noMatchDesc, variant: 'search', compact: true })
      + `<div class="memory-actions"><button type="button" class="btn btn-ghost btn-sm" data-act="clear-filters">${esc(t.clearFilters)}</button></div>`;
  }
  const page = rows.slice(0, st.shown);
  return `
    <p class="memory-meta" role="status">${esc(t.countOf.replace('{n}', page.length).replace('{total}', rows.length))}</p>
    <div class="table-container"><table class="table memory-table">
      <caption class="sr-only">${esc(t.tableCaption)}</caption>
      <thead><tr><th scope="col">${esc(t.colTitle)}</th><th scope="col">${esc(t.colKind)}</th><th scope="col">${esc(t.colStatus)}</th><th scope="col">${esc(t.colUpdated)}</th><th scope="col">${esc(t.colActions)}</th></tr></thead>
      <tbody>${page.map(rowHtml).join('')}</tbody></table></div>
    ${rows.length > page.length ? `<div class="memory-actions"><button type="button" class="btn btn-secondary btn-sm" data-act="more">${esc(t.showMore)}</button></div>` : ''}`;
}

function trashBody() {
  const t = tn();
  const tr = st.trash;
  if (!tr.open) return '';
  let inner;
  if (tr.status === 'loading') inner = loadingBlock(skeletonTable({ rows: 2, cols: 3 }), t.loading);
  else if (tr.status === 'error') inner = emptyState({ title: t.errorTitle, description: tr.error, variant: 'error', compact: true });
  else if (!tr.items.length) inner = emptyState({ title: t.trashEmptyTitle, description: t.trashEmptyDesc, variant: 'data', compact: true });
  else {
    inner = `<div class="table-container"><table class="table memory-table"><caption class="sr-only">${esc(t.trash)}</caption>
      <thead><tr><th scope="col">${esc(t.colId)}</th><th scope="col">${esc(t.deletedAt)}</th><th scope="col">${esc(t.colActions)}</th></tr></thead>
      <tbody>${tr.items.map((it) => `<tr><td class="memory-file" title="${esc(it.file)}">${esc(it.id)}</td><td class="tabular">${esc(fmtDate(it.deleted_at))}</td>
        <td><button type="button" class="btn btn-secondary btn-sm" data-act="restore" data-trash="${esc(it.trash_id)}" aria-label="${esc(`${t.restore}: ${it.id}`)}">${esc(t.restore)}</button></td></tr>`).join('')}</tbody></table></div>`;
  }
  return `<section class="memory-context" id="mem-trash-panel" aria-labelledby="mem-trash-title"><div class="card-title" id="mem-trash-title">${esc(t.trash)}</div><p class="state-desc">${esc(t.trashDesc)}</p>${inner}</section>`;
}

export function html() {
  const t = tn();
  return `
    <section class="card memory-section" aria-labelledby="mem-notes-title">
      <div class="card-header"><div><div class="card-title" id="mem-notes-title">${esc(t.title)}</div><p class="card-subtitle">${esc(t.desc)}</p></div></div>
      <div data-bind="mem-notes-toolbar">${toolbarHtml()}</div>
      <div data-bind="mem-notes-list" aria-live="polite" aria-busy="${st.list.status === 'loading'}">${listBody()}</div>
      <div data-bind="mem-notes-trash">${trashBody()}</div>
    </section>`;
}

/* ------------------------------------------------------------------ diálogos (focus trap + Esc + retorno de foco) */
let dlg = null;
function closeDialog() {
  if (!dlg) return;
  const d = dlg; dlg = null;
  d.release();
  d.el.remove();
}

/** Abre um diálogo modal único. `onAction(name, el, dialog)` trata cliques em [data-dlg]. */
function openDialog({ title, body, footer, role = 'dialog', initial, wide = false, onAction }) {
  closeDialog();
  const uid = `mem-dlg-${Date.now()}`;
  const wrap = document.createElement('div');
  wrap.className = 'modal-backdrop is-active';
  wrap.innerHTML = `
    <div class="modal-dialog ${wide ? 'mem-dialog-wide' : ''}" role="${role}" aria-modal="true" aria-labelledby="${uid}-t" tabindex="-1">
      <div class="modal-header"><h3 class="card-title" id="${uid}-t">${esc(title)}</h3>
        <button type="button" class="btn btn-ghost btn-icon" data-dlg="close" aria-label="${esc(I18N.app.close)}">${icon('x', '', 16)}</button></div>
      <div class="modal-body" id="${uid}-b">${body}</div>
      <div class="modal-footer">${footer || ''}</div>
    </div>`;
  document.body.appendChild(wrap);
  const dialog = wrap.querySelector('.modal-dialog');
  const returnTo = document.activeElement;
  const release = trapFocus(dialog, { returnTo, initial: () => (initial ? dialog.querySelector(initial) : null), inertRoot: document.getElementById('app') });
  dlg = { el: wrap, release, dialog };
  wrap.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeDialog(); } });
  wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) closeDialog(); });
  wrap.addEventListener('click', (e) => {
    const el = e.target.closest('[data-dlg]'); if (!el) return;
    const a = el.getAttribute('data-dlg');
    if (a === 'close') closeDialog(); else onAction?.(a, el, dialog);
  });
  return dialog;
}

const setDlgBusy = (dialog, busy) => {
  dialog.setAttribute('aria-busy', String(busy));
  dialog.querySelectorAll('.modal-footer button, .modal-body [data-dlg]').forEach((b) => { b.disabled = busy; });
};

/** Confirmação destrutiva: foco inicial em "Cancelar"; confirmar exige clique/Enter explícito. */
function confirmDialog({ title, message, confirmLabel, danger = true, extra = '', onConfirm }) {
  const t = tn();
  openDialog({
    title, role: 'alertdialog', initial: '[data-dlg="close"].mem-cancel',
    body: `<p id="mem-confirm-msg">${esc(message)}</p>${extra}`,
    footer: `<button type="button" class="btn btn-secondary mem-cancel" data-dlg="close">${esc(t.cancel)}</button>
             <button type="button" class="btn ${danger ? 'btn-danger' : 'btn-primary'}" data-dlg="confirm">${esc(confirmLabel)}</button>`,
    onAction: async (a, el, dialog) => {
      if (a !== 'confirm') return;
      setDlgBusy(dialog, true);
      try { await onConfirm(dialog); closeDialog(); } catch (e) { setDlgBusy(dialog, false); toast('error', errText(e)); }
    },
  });
  dlg?.dialog.setAttribute('aria-describedby', 'mem-confirm-msg');
}

/* ------------------------------------------------------------------ ações */
export function mount(root) {
  const q = (b) => root.querySelector(`[data-bind="${b}"]`);
  const paintList = () => { const el = q('mem-notes-list'); if (el) { el.innerHTML = listBody(); el.setAttribute('aria-busy', String(st.list.status === 'loading')); } };
  const paintToolbar = () => { const el = q('mem-notes-toolbar'); if (!el) return; const had = el.contains(document.activeElement) ? document.activeElement.getAttribute('data-act') || document.activeElement.getAttribute('data-filter') : null; el.innerHTML = toolbarHtml(); if (had) el.querySelector(`[data-act="${had}"],[data-filter="${had}"]`)?.focus(); };
  const paintTrash = () => { const el = q('mem-notes-trash'); if (el) el.innerHTML = trashBody(); };
  const paintAll = () => { paintToolbar(); paintList(); paintTrash(); };
  const setBusy = (b) => { st.busy = b; paintToolbar(); };

  async function load() {
    st.list = { ...st.list, status: 'loading', error: '' };
    paintList();
    try {
      const d = await memListNotes();
      st.list = { status: 'ok', notes: Array.isArray(d?.notes) ? d.notes : [], error: '' };
      st.shown = PAGE_SIZE;
    } catch (e) {
      st.list = { status: classify(e), notes: [], error: errText(e) };
    }
    st.loaded = true;
    if (root.isConnected) { paintToolbar(); paintList(); }
  }

  async function loadTrash() {
    st.trash = { ...st.trash, status: 'loading' }; paintTrash();
    try { const d = await memTrash(); st.trash = { open: st.trash.open, status: 'ok', items: (d?.items || []).slice().reverse(), error: '' }; }
    catch (e) { st.trash = { open: st.trash.open, status: 'error', items: [], error: errText(e) }; }
    paintTrash();
  }

  const noteById = (id) => st.list.notes.find((n) => n.id === id);

  /* ---- editor (criar/editar) */
  async function openEditor(id) {
    const t = tn();
    let note = { title: '', content: '', tags: [], kind: '', project: '' };
    if (id) {
      try { note = await memGetNote(id); } catch (e) { toast('error', errText(e)); return; }
    }
    const create = !id;
    const kindOpts = `<option value="">${esc(t.kindNone)}</option>${KINDS.map((k) => `<option value="${k}" ${k === note.kind ? 'selected' : ''}>${esc(t.kind[k])}</option>`).join('')}`;
    openDialog({
      title: create ? t.newNote : t.editNote, wide: true, initial: '#mem-f-title',
      body: `
        <form id="mem-note-form" novalidate>
          <div class="input-group"><label class="input-label" for="mem-f-title">${esc(t.fTitle)} *</label>
            <div class="input-control"><input id="mem-f-title" name="title" type="text" maxlength="200" required aria-required="true" aria-describedby="mem-f-err" value="${esc(note.title)}" autocomplete="off" /></div></div>
          <div class="input-group"><label class="input-label" for="mem-f-content">${esc(t.fContent)} *</label>
            <textarea id="mem-f-content" name="content" rows="10" class="mem-textarea" required aria-required="true" aria-describedby="mem-f-err">${esc(note.content)}</textarea></div>
          <div class="mem-form-row">
            <div class="input-group"><label class="input-label" for="mem-f-tags">${esc(t.fTags)}</label>
              <div class="input-control"><input id="mem-f-tags" name="tags" type="text" value="${esc((note.tags || []).join(', '))}" placeholder="${esc(t.fTagsPh)}" autocomplete="off" /></div></div>
            <div class="input-group"><label class="input-label" for="mem-f-kind">${esc(t.fKind)}</label>
              <select id="mem-f-kind" name="kind" class="select-control">${kindOpts}</select></div>
            ${create ? `<div class="input-group"><label class="input-label" for="mem-f-project">${esc(t.fProject)}</label>
              <div class="input-control"><input id="mem-f-project" name="project" type="text" value="" autocomplete="off" /></div></div>` : ''}
          </div>
          ${create ? '' : `<p class="memory-meta">${esc(t.versionNote)}</p>`}
          <p id="mem-f-err" class="mem-form-error" role="alert"></p>
        </form>`,
      footer: `<button type="button" class="btn btn-secondary" data-dlg="close">${esc(t.cancel)}</button>
               <button type="button" class="btn btn-primary" data-dlg="save">${esc(t.save)}</button>`,
      onAction: async (a, el, dialog) => {
        if (a !== 'save') return;
        const form = dialog.querySelector('#mem-note-form');
        const err = dialog.querySelector('#mem-f-err');
        const fd = Object.fromEntries(new FormData(form).entries());
        const { body, error } = buildNotePayload(fd, { create });
        if (error) {
          err.textContent = t[error];
          const bad = error === 'errContent' ? '#mem-f-content' : '#mem-f-title';
          dialog.querySelectorAll('[aria-invalid]').forEach((x) => x.removeAttribute('aria-invalid'));
          const field = dialog.querySelector(bad); field.setAttribute('aria-invalid', 'true'); field.focus();
          return;
        }
        err.textContent = '';
        setDlgBusy(dialog, true);
        try {
          if (create) {
            const r = await memCreateNote(body);
            toast(r?.similar?.length || r?.duplicate_of ? 'warning' : 'success', r?.similar?.length || r?.duplicate_of ? t.savedSimilar : t.created);
          } else {
            await memUpdateNote(id, body);
            toast('success', t.updated);
          }
          closeDialog();
          await load();
        } catch (e) {
          setDlgBusy(dialog, false);
          err.textContent = errText(e);
          dialog.querySelector('#mem-f-title')?.focus();
        }
      },
    });
  }

  /* ---- histórico / diff / rollback */
  async function openHistory(id) {
    const t = tn();
    let versions;
    try { versions = ((await memHistory(id))?.versions || []).slice().reverse(); } catch (e) { toast('error', errText(e)); return; }
    const note = noteById(id);
    const list = versions.length
      ? `<div class="table-container"><table class="table memory-table"><caption class="sr-only">${esc(t.history)}</caption>
          <thead><tr><th scope="col">${esc(t.colVersion)}</th><th scope="col">${esc(t.colTitle)}</th><th scope="col">${esc(t.colBytes)}</th><th scope="col">${esc(t.colActions)}</th></tr></thead>
          <tbody>${versions.map((v) => { const ep = versionEpoch(v.version); return `<tr>
            <td class="tabular">${esc(ep != null ? fmtDate(ep) : v.version)}<div class="mem-note-sub"><span title="${esc(v.sha256)}">${esc(String(v.sha256 || '').slice(0, 8))}</span></div></td>
            <td>${esc(v.title || '—')}</td><td class="tabular">${esc(v.bytes)}</td>
            <td class="mem-note-actions">
              <button type="button" class="btn btn-ghost btn-sm" data-dlg="diff" data-v="${esc(v.version)}" aria-label="${esc(`${t.diff}: ${ep != null ? fmtDate(ep) : v.version}`)}">${esc(t.diff)}</button>
              <button type="button" class="btn btn-secondary btn-sm" data-dlg="rollback" data-v="${esc(v.version)}" aria-label="${esc(`${t.rollback}: ${ep != null ? fmtDate(ep) : v.version}`)}">${esc(t.rollback)}</button>
            </td></tr>`; }).join('')}</tbody></table></div>`
      : emptyState({ title: t.historyEmptyTitle, description: t.historyEmptyDesc, variant: 'data', compact: true });
    openDialog({
      title: `${t.history}: ${note?.title || id}`, wide: true,
      body: `${list}<div data-bind="mem-diff" aria-live="polite"></div>`,
      footer: `<button type="button" class="btn btn-secondary" data-dlg="close">${esc(t.close)}</button>`,
      onAction: async (a, el, dialog) => {
        const v = el.getAttribute('data-v');
        const out = dialog.querySelector('[data-bind="mem-diff"]');
        if (a === 'diff') {
          out.innerHTML = loadingBlock(skeletonTable({ rows: 3, cols: 1 }), t.loading);
          try {
            const text = await memDiff(id, v, 'current');
            const lines = classifyDiff(text);
            out.innerHTML = lines.length
              ? `<div class="card-title">${esc(t.diffTitle)}</div><pre class="memory-context-pre mem-diff" tabindex="0" aria-label="${esc(t.diffTitle)}">${lines.map((l) => `<span class="mem-diff-${l.cls}">${esc(l.text)}</span>`).join('\n')}</pre>`
              : `<p class="state-desc">${esc(t.diffSame)}</p>`;
          } catch (e) { out.innerHTML = `<p class="mem-form-error" role="alert">${esc(errText(e))}</p>`; }
        } else if (a === 'rollback') {
          confirmDialog({
            title: t.rollbackTitle, message: t.rollbackMsg, confirmLabel: t.rollback, danger: false,
            onConfirm: async () => { await memRollback(id, v); toast('success', t.rolledBack); await load(); },
          });
        }
      },
    });
  }

  /* ---- arquivar / excluir */
  function askArchive(id) {
    const t = tn(); const note = noteById(id);
    confirmDialog({
      title: t.archiveTitle, message: t.archiveMsg.replace('{title}', note?.title || id), confirmLabel: t.archive,
      onConfirm: async () => { await memUpdateNote(id, { status: 'archived' }); toast('success', t.archived); await load(); },
    });
  }
  function askDelete(id) {
    const t = tn(); const note = noteById(id);
    confirmDialog({
      title: t.deleteTitle, message: t.deleteMsg.replace('{title}', note?.title || id), confirmLabel: t.del,
      onConfirm: async () => { await memDeleteNote(id); toast('success', t.deleted); await load(); if (st.trash.open) loadTrash(); },
    });
  }

  /* ---- exportar / importar */
  async function doExport() {
    const t = tn(); setBusy(true);
    try {
      const blob = await memExportJsonl();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href = url; a.download = 'anamnesia-memory.jsonl'; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast('success', t.exported);
    } catch (e) { toast('error', errText(e)); }
    setBusy(false);
  }
  async function onImportFile(input) {
    const t = tn(); const file = input.files && input.files[0]; input.value = '';
    if (!file) return;
    let text;
    try { text = await file.text(); } catch (e) { toast('error', errText(e)); return; }
    const info = inspectJsonl(text);
    if (!info.count) { toast('error', t.importEmpty); return; }
    if (info.badLine) { toast('error', t.importBadLine.replace('{n}', info.badLine)); return; }
    confirmDialog({
      title: t.importTitle, danger: false, confirmLabel: t.importConfirm,
      message: t.importMsg.replace('{n}', info.count).replace('{file}', file.name),
      extra: `<label class="mem-check"><input type="checkbox" id="mem-import-overwrite" /> <span>${esc(t.importOverwrite)}</span></label>
              <p class="memory-meta">${esc(t.importOverwriteHint)}</p>`,
      onConfirm: async (dialog) => {
        const r = await memImportJsonl(text, dialog.querySelector('#mem-import-overwrite')?.checked);
        toast('success', t.imported.replace('{imported}', r.imported ?? 0).replace('{skipped}', r.skipped ?? 0));
        await load();
      },
    });
  }

  /* ---- consolidate: prévia (dry-run) -> aplicar */
  async function doConsolidate() {
    const t = tn(); setBusy(true);
    let plan;
    try { plan = await memConsolidate(false); } catch (e) { setBusy(false); toast('error', errText(e)); return; }
    setBusy(false);
    const sum = summarizePlan(plan);
    const title = (id) => noteById(id)?.title || id;
    const body = sum.groups
      ? `<p>${esc(t.consolidatePreview.replace('{groups}', sum.groups).replace('{notes}', sum.notes))}</p>
         <ul class="mem-plan">${plan.groups.map((g) => `<li><strong>${esc(t.keep)}:</strong> ${esc(title(g.keep))}
            <ul>${(g.supersede || []).map((s) => `<li>${esc(t.supersede)}: ${esc(title(s))}</li>`).join('')}</ul></li>`).join('')}</ul>
         <p class="memory-meta">${esc(t.consolidateSafe)}</p>`
      : `<p>${esc(t.consolidateNone)}</p>`;
    openDialog({
      title: t.consolidateTitle, wide: true, role: sum.groups ? 'alertdialog' : 'dialog', initial: '[data-dlg="close"].mem-cancel', body,
      footer: `<button type="button" class="btn btn-secondary mem-cancel" data-dlg="close">${esc(sum.groups ? t.cancel : t.close)}</button>
               ${sum.groups ? `<button type="button" class="btn btn-primary" data-dlg="apply">${esc(t.consolidateApply.replace('{notes}', sum.notes))}</button>` : ''}`,
      onAction: async (a, el, dialog) => {
        if (a !== 'apply') return;
        setDlgBusy(dialog, true);
        try {
          const r = await memConsolidate(true);
          toast('success', t.consolidated.replace('{n}', Number(r?.superseded) || 0));
          closeDialog(); await load();
        } catch (e) { setDlgBusy(dialog, false); toast('error', errText(e)); }
      },
    });
  }

  /* ---- eventos */
  const onClick = (e) => {
    const el = e.target.closest('[data-act]'); if (!el || !root.contains(el) || el.disabled) return;
    const a = el.getAttribute('data-act'); const id = el.getAttribute('data-id');
    if (a === 'new') openEditor(null);
    else if (a === 'edit') openEditor(id);
    else if (a === 'history') openHistory(id);
    else if (a === 'archive') askArchive(id);
    else if (a === 'delete') askDelete(id);
    else if (a === 'reload') load();
    else if (a === 'consolidate') doConsolidate();
    else if (a === 'export') doExport();
    else if (a === 'import') q('mem-import-file')?.click();
    else if (a === 'more') { st.shown += PAGE_SIZE; paintList(); }
    else if (a === 'clear-filters') { st.f = { q: '', project: '', kind: '', status: '' }; st.shown = PAGE_SIZE; paintToolbar(); paintList(); }
    else if (a === 'toggle-trash') { st.trash.open = !st.trash.open; paintToolbar(); if (st.trash.open) loadTrash(); else paintTrash(); }
    else if (a === 'restore') {
      memRestore(el.getAttribute('data-trash')).then(() => { toast('success', tn().restored); return Promise.all([load(), loadTrash()]); }).catch((er) => toast('error', errText(er)));
    }
  };
  const onFilter = (e) => {
    const k = e.target.getAttribute && e.target.getAttribute('data-filter'); if (!k || !(k in st.f)) return;
    st.f[k] = e.target.value; st.shown = PAGE_SIZE;
    paintList();
  };
  const onChange = (e) => { if (e.target.matches('[data-bind="mem-import-file"]')) onImportFile(e.target); };
  const onSubmit = (e) => { if (e.target.closest('[data-form="filter"]')) e.preventDefault(); };
  root.addEventListener('submit', onSubmit);
  root.addEventListener('click', onClick);
  root.addEventListener('input', onFilter);
  const onChangeAll = (e) => { onFilter(e); onChange(e); };
  root.addEventListener('change', onChangeAll);
  const onNet = () => { if (st.loaded) load(); };
  window.addEventListener('online', onNet);

  const cmdId = 'memory-new-note';
  registerCommand({
    id: cmdId, label: () => tn().newNote, category: 'system', categoryLabel: () => I18N.palette.catSystem, icon: 'plus',
    keywords: 'memoria memory nota note nova new', run: () => { if (root.isConnected) openEditor(null); },
  });

  return {
    /** Chamado quando a aba fica visível (carga preguiçosa). */
    activate() { if (!st.loaded || st.list.status === 'idle') load(); else paintAll(); },
    cleanup() {
      closeDialog(); unregisterCommand(cmdId);
      root.removeEventListener('submit', onSubmit); root.removeEventListener('change', onChangeAll);
      root.removeEventListener('click', onClick); root.removeEventListener('input', onFilter);
      window.removeEventListener('online', onNet);
    },
  };
}
