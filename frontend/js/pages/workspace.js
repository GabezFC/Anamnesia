/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA WORKSPACE PAGE (#/workspace)
 * 3 columns: Projects | Central de Importação, Exportação e Inicialização | Files & Context
 * Painel principal = Central (status real do índice, inicializar/verificar/atualizar, importar, exportar, histórico).
 * Também: seleção de projeto, explorador de arquivos com filtro, painel "Contexto do agente" e configuração do JEV.
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { mockProjects, mockFiles } from '../mock-data.js';
import { loadFiles, toggleDir, fileContent, unregisterProject, refreshWorkspace, jevStatus, jevSaveConfig, jevTestConnection } from '../live.js';
import { openFileViewer } from '../components/file-viewer.js';
import { esc, fmtNumber, fmtDate } from '../format.js';
import { getLocalToken } from '../api.js';
import { getSettings, putSettings, lastSearch, isUnavailable, call } from '../anamnesia-api.js';
import { skeletonLines, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';

let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'
let activeProjectId = 'proj-1';
let isFilesOpen = true;
let isContextDrawerOpen = false;
let searchFilter = '';
let selectedFilePath = '';
// ---- Remover projeto (DELETE /api/projects/{id}); desvincula, nunca apaga a pasta ----
let rm = null; // { id, name, path, purge, busy, err } | null
let rmTrigger = null;

// ---- layout persistente (PUT /api/settings workspace_layout: larguras + painel de arquivos) ----
const LIMITS = { left: [200, 480], right: [200, 560] };
let colWidths = { left: null, right: null };
let layoutReady = false;
let layoutRestoring = false;
let saveTimer = null;
// ---- painel "Contexto do agente" (GET /api/memory/last-search) ----
let ctx = { status: 'idle', data: null, error: '' }; // idle | loading | ok | empty | error

// ---- Central de Importação, Exportação e Inicialização (/api/workspace/io/*) ----
const WIO_TABS = ['init', 'import', 'export'];
const wio = {
  tab: 'init',
  jobs: { init: null, import: null, export: null },   // último job por aba ({id,state,phase,done,total,result,...})
  errs: { init: null, import: null, export: null },   // erro de submissão por aba ({message,hint})
  timer: null,                                        // polling do job em execução
  busy: false,
  status: { loading: false, data: null, error: null, apiMissing: false }, // GET /api/workspace/io/status
  history: [],                                        // GET /api/workspace/io/history
  initOpts: { install: false, note: true },
  importOpts: { source: 'upload', path: '', files: [] },
  exportOpts: { kind: 'memories', format: 'json', scope: 'project' },
};

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));


// ---- JEV: configuração guiada (a lógica vive no backend: app/services/jev_setup.py) ----------------------------
let jev = { loaded: false, loading: false, open: false, adv: false, status: null, draft: {}, key: '', busy: '', msg: null, err: null, test: null };
const JEV_NUM = ['relevance_threshold', 'review_threshold', 'injection_threshold', 'timeout_s', 'max_retries'];
const JEV_BOOL = ['second_pass', 'contradiction_check'];
const JEV_LINKS = {
  api_key: 'https://console.typesafe.ai/',
  base_url: 'https://docs.typesafe.ai/api',
  model: 'https://docs.typesafe.ai/models',
  relevance_threshold: 'https://docs.typesafe.ai/confidence',
  review_threshold: 'https://docs.typesafe.ai/confidence',
  timeout_s: 'https://docs.typesafe.ai/sdk/python/usage#retries',
  max_retries: 'https://docs.typesafe.ai/sdk/python/usage#retries',
};

function jevEffective(f) {
  if (f in jev.draft) return jev.draft[f];
  return jev.status ? jev.status.settings[f] : '';
}

async function jevLoad(root) {
  if (jev.loading) return;
  jev.loading = true;
  try { jev.status = await jevStatus(); jev.err = null; } catch (e) { jev.err = e.message || String(e); }
  jev.loaded = true; jev.loading = false;
  if (root && root.isConnected) refresh(root);
}

function jevPanel(t) {
  const st = jev.status ? jev.status.state : (jev.loaded ? 'unavailable' : 'loading');
  const label = (t.jevStates && t.jevStates[st]) || st;
  const dot = { connected: 'ok', configured: 'warn', not_configured: 'idle', loading: 'idle' }[st] || 'bad';
  const head = `<div class="init-title">${esc(t.jevTitle)}</div>
    <div class="init-sub jev-status" data-state="${esc(st)}"><span class="jev-dot is-${dot}"></span> ${esc(label)}${jev.status && jev.status.key_masked ? ` · <code>${esc(jev.status.key_masked)}</code>` : ''}</div>`;
  const toggle = `<button class="btn btn-secondary btn-sm init-btn" data-action="jev-toggle">${icon('config', '', 14)} ${esc(jev.status && jev.status.key_present ? t.jevEdit : t.jevConfigure)}</button>`;
  if (!jev.open) return `<div class="init-project-section jev-section" data-bind="jev-panel">${head}${jev.err ? `<div class="init-detail">${esc(jev.err)}</div>` : ''}${toggle}</div>`;
  const S = jev.status || { settings: {}, defaults: {}, customized: [] };
  const mark = (f) => (S.customized.includes(f) ? ` <span class="init-sub">(${esc(t.jevCustom)})</span>` : '');
  const help = (f) => {
    const h = (t.jevHelp || {})[f];
    if (!h) return '';
    const link = JEV_LINKS[f]
      ? ` <a class="jev-link" href="${JEV_LINKS[f]}" target="_blank" rel="noopener noreferrer">${esc(t.jevLinkLabel)}</a>` : '';
    return `<div class="init-sub jev-help">${esc(h)}${link}</div>`;
  };
  const text = (f, lab, ph) => `<label class="jev-field"><span>${esc(lab)}${mark(f)}</span><input class="input" type="text" data-jev="${f}" value="${esc(String(jevEffective(f) ?? ''))}" placeholder="${esc(ph || '')}" autocomplete="off" spellcheck="false"></label>${help(f)}`;
  const num = (f, lab) => `<label class="jev-field"><span>${esc(lab)}${mark(f)}</span><input class="input" type="number" step="any" data-jev="${f}" value="${esc(String(jevEffective(f) ?? ''))}"></label>${help(f)}`;
  const sel = (f, lab, opts) => `<label class="jev-field"><span>${esc(lab)}${mark(f)}</span><select class="input" data-jev="${f}">${opts.map((o) => `<option value="${o}" ${String(jevEffective(f)) === o ? 'selected' : ''}>${o}</option>`).join('')}</select></label>${help(f)}`;
  const chk = (f, lab) => `<label class="jev-field jev-check"><input type="checkbox" data-jev="${f}" ${jevEffective(f) ? 'checked' : ''}> <span>${esc(lab)}${mark(f)}</span></label>${help(f)}`;
  const keyPh = S.key_present ? t.jevKeyKeep : 'sk-…';
  const adv = jev.adv ? `<div class="jev-adv">
      ${sel('mode', t.jevMode, ['performance', 'strict'])}${num('relevance_threshold', t.jevRel)}${num('review_threshold', t.jevRev)}${num('injection_threshold', t.jevInj)}
      ${sel('review_action', t.jevReviewAction, ['keep', 'drop'])}${sel('failure_mode', t.jevFailure, ['fail_open', 'fail_closed'])}
      ${chk('second_pass', t.jevSecond)}${chk('contradiction_check', t.jevContra)}${num('timeout_s', t.jevTimeout)}${num('max_retries', t.jevRetries)}</div>` : '';
  let result = '';
  if (jev.err) result = `<div class="init-report is-error" role="alert"><div class="init-title">✗ ${esc(jev.err)}</div></div>`;
  else if (jev.test) {
    const r = jev.test;
    const steps = (r.checks || []).map((c) => `<li>${c.ok ? '✓' : '✗'} ${esc((t.jevSteps && t.jevSteps[c.step]) || c.step)}</li>`).join('');
    result = `<div class="init-report ${r.ok ? 'is-ok' : 'is-error'}" role="${r.ok ? 'status' : 'alert'}">
      <div class="init-title">${r.ok ? '✓ ' + esc(t.jevOk) + (r.model ? ' (' + esc(r.model) + ')' : '') : '✗ ' + esc(t.jevFail)}</div>
      ${r.ok ? '' : `<div class="init-detail">${r.http_status ? 'HTTP ' + esc(String(r.http_status)) + ' — ' : ''}${esc(r.message)}</div>`}
      ${steps ? `<ul class="init-list">${steps}</ul>` : ''}</div>`;
  } else if (jev.msg) result = `<div class="init-report is-ok" role="status"><div class="init-title">✓ ${esc(jev.msg)}</div></div>`;
  return `<div class="init-project-section jev-section" data-bind="jev-panel">${head}
    <div class="init-sub">${esc(t.jevHint)}</div>
    <label class="jev-field"><span>${esc(t.jevApiKey)}</span><input class="input" type="password" data-jev-key value="${esc(jev.key)}" placeholder="${esc(keyPh)}" autocomplete="off" spellcheck="false"></label>
    ${help('api_key')}
    ${S.key_present ? `<div class="init-sub">${esc(t.jevKeySet)} <code>${esc(S.key_masked || '')}</code></div>` : ''}
    ${text('base_url', t.jevEndpoint, S.defaults.base_url)}${text('model', t.jevModel, S.defaults.model)}
    <button class="btn btn-ghost btn-sm" data-action="jev-adv">${esc(t.jevAdvanced)} ${jev.adv ? '▲' : '▼'}</button>${adv}
    <div class="jev-actions">
      <button class="btn btn-primary btn-sm" data-action="jev-save" ${jev.busy ? 'disabled' : ''}>${esc(jev.busy === 'save' ? t.jevBusySave : t.jevSave)}</button>
      <button class="btn btn-secondary btn-sm" data-action="jev-test" ${jev.busy ? 'disabled' : ''}>${esc(jev.busy === 'test' ? t.jevBusyTest : t.jevTest)}</button>
      <button class="btn btn-ghost btn-sm" data-action="jev-toggle">${esc(t.jevClose)}</button>
    </div>${result}</div>`;
}

/** Só o que o usuário alterou é enviado (o servidor também ignora valores iguais). */
function jevPatch() {
  const patch = {};
  for (const [f, v] of Object.entries(jev.draft)) {
    if (JEV_NUM.includes(f)) { const n = Number(v); if (v === '' || Number.isNaN(n)) continue; patch[f] = f === 'max_retries' ? Math.trunc(n) : n; }
    else if (JEV_BOOL.includes(f)) patch[f] = !!v;
    else if (String(v).trim() !== '') patch[f] = String(v).trim();
  }
  return patch;
}

async function jevRun(root, kind) {
  if (jev.busy) return;
  const t = I18N.workspace;
  jev.busy = kind; jev.err = null; jev.msg = null; if (kind !== 'test') jev.test = null;
  refresh(root);
  try {
    const patch = jevPatch();
    if (Object.keys(patch).length || jev.key) {
      const res = await jevSaveConfig(patch, jev.key);
      jev.status = res.status; jev.draft = {}; jev.key = '';
      jev.msg = (res.changed && res.changed.length) ? t.jevSaved : t.jevNothing;
    }
    if (kind === 'test') { jev.test = await jevTestConnection(); jev.msg = null; jev.status = await jevStatus(); }
  } catch (e) { jev.err = (e.detail || e.message || String(e)) + (e.hint ? ' — ' + e.hint : ''); }
  jev.busy = '';
  if (root.isConnected) refresh(root);
}

export function snapshotLayout() {
  return { v: 2, widths: { left: colWidths.left, right: colWidths.right }, files_open: isFilesOpen };
}

/** Grava o layout com debounce (não bloqueia a UI; falhas são silenciosas). */
function persistLayout() {
  if (!layoutReady) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { putSettings({ workspace_layout: snapshotLayout() }).catch(() => {}); }, 600);
}

/** Aplica um layout salvo (v2: larguras e painel de arquivos; formatos antigos são aceitos e ignorados). */
export function applyLayout(L) {
  if (!L || typeof L !== 'object') return;
  const w = L.widths || {};
  if (typeof w.left === 'number') colWidths.left = clamp(w.left, LIMITS.left);
  if (typeof w.right === 'number') colWidths.right = clamp(w.right, LIMITS.right);
  if (typeof L.files_open === 'boolean') isFilesOpen = L.files_open;
}

async function restoreLayout(root) {
  if (layoutReady || layoutRestoring) return;
  layoutRestoring = true;
  try {
    const st = await getSettings();
    applyLayout(st && (st.workspace_layout || st.terminal_layout));
  } catch (e) { /* sem backend de settings: segue com o padrão */ }
  layoutRestoring = false;
  layoutReady = true;
  if (root.isConnected && currentState === 'loaded') refresh(root);
}



// ================= Central de Importação, Exportação e Inicialização =================
// Tudo aqui vem da API real (/api/workspace/io/*): status do índice, histórico, prévia/execução/cancelamento de jobs.

const wioErrBox = (e) => (e ? `<div class="wio-alert is-bad" role="alert"><strong>${esc(e.message)}</strong>${e.hint ? `<p class="wio-hint">${esc(e.hint)}</p>` : ''}</div>` : '');
const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
const apiErr = (err) => ({ message: (err && (err.detail || err.message)) || String(err), hint: (err && err.hint) || '', code: (err && err.code) || '', status: err && err.status });

function wioProject() {
  return mockProjects.find((x) => x.id === activeProjectId) || null;
}

/** Disponibilidade vinda do servidor; null = ainda desconhecida (não bloqueia, a API valida de novo). */
function wioAvailability() {
  return wio.status.data && wio.status.data.availability ? wio.status.data.availability : null;
}
const wioBlocked = () => {
  const a = wioAvailability();
  return !!(wio.status.apiMissing || (a && !a.available));
};

async function wioLoadStatus(root) {
  const pid = activeProjectId;
  if (!pid || !mockProjects.some((p) => p.id === pid)) { wio.status = { loading: false, data: null, error: null, apiMissing: false }; wio.history = []; return; }
  wio.status = { loading: true, data: null, error: null, apiMissing: false };
  if (root && root.isConnected) refresh(root);
  let st = null;
  let hist = [];
  try {
    st = await call('GET', `/api/workspace/io/status?project_id=${encodeURIComponent(pid)}`);
    const h = await call('GET', `/api/workspace/io/history?project_id=${encodeURIComponent(pid)}&limit=8`).catch(() => null);
    hist = (h && h.history) || [];
  } catch (err) {
    if (pid !== activeProjectId) return;
    wio.status = { loading: false, data: null, error: apiErr(err), apiMissing: isUnavailable(err) };
    wio.history = [];
    if (root && root.isConnected) refresh(root);
    return;
  }
  if (pid !== activeProjectId) return; // o usuário trocou de projeto enquanto carregava
  wio.status = { loading: false, data: st, error: null, apiMissing: false };
  wio.history = hist;
  if (root && root.isConnected) refresh(root);
}

const fmtWhen = (ts) => { try { return ts ? fmtDate(ts) : '—'; } catch { return '—'; } };

function wioProjectCard(t) {
  const p = wioProject();
  const S = wio.status;
  const d = S.data;
  // Status metadata is raw; live.js already escapes the fallback project list.
  const name = d ? esc(d.project.name) : (p ? p.name : '');
  const path = d ? esc(d.project.path) : (p ? p.path : '');
  let facts = '';
  let alert = '';
  if (S.loading) {
    facts = `<div class="wio-skel" aria-busy="true">${skeletonLines(2)}</div>`;
  } else if (S.apiMissing) {
    alert = `<div class="wio-alert" role="alert"><strong>${esc(t.wioApiMissing)}</strong><p class="wio-hint">${esc(t.wioApiMissingHint)}</p></div>`;
  } else if (S.error) {
    alert = wioErrBox(S.error);
  } else if (d) {
    const a = d.availability || {};
    const ix = d.index || {};
    const availPill = a.available
      ? `<span class="wio-pill is-ok">${esc(t.wioAvailOk)}</span>`
      : `<span class="wio-pill is-bad">${esc(t.wioAvailBad)}</span>`;
    const ixPill = ix.indexed
      ? `<span class="wio-pill is-ok">${esc(fmtNumber(ix.files))} ${esc(t.wioIndexedItems)}</span>`
      : `<span class="wio-pill is-warn">${esc(t.wioNotIndexed)}</span>`;
    facts = `<div class="wio-facts">
        <span>${esc(t.wioFolder)}: ${availPill}</span>
        <span>${esc(t.wioIndexLabel)}: ${ixPill}</span>
        ${ix.indexed ? `<span>${esc(t.wioUpdatedAt)}: <strong>${esc(fmtWhen(ix.updated))}</strong></span>` : ''}
        ${ix.indexed && ix.secret_files ? `<span>${esc(t.wioInitSecrets)}: <strong>${esc(fmtNumber(ix.secret_files))}</strong></span>` : ''}
        ${d.memories != null ? `<span>${esc(t.wioMemoriesLabel)}: <strong>${esc(fmtNumber(d.memories))}</strong></span>` : ''}
      </div>`;
    if (!a.available) {
      alert = `<div class="wio-alert is-bad" role="alert"><strong>${esc(a.reason || t.wioAvailBad)}</strong>${a.hint ? `<p class="wio-hint">${esc(a.hint)}</p>` : ''}</div>`;
    }
  }
  return `
    <section class="wio-project" aria-label="${esc(t.wioProjectLabel)}" data-bind="wio-project">
      <div class="wio-project-name">${name}</div>
      <div class="wio-project-path" title="${path}">${path}</div>
      ${facts}${alert}
    </section>`;
}

/** Painel de progresso/resultado de um job da central. */
function wioJobPanel(kind) {
  const t = I18N.workspace;
  const job = wio.jobs[kind];
  if (!job) return wioErrBox(wio.errs[kind]);
  const running = job.state === 'running' || job.state === 'queued';
  const pct = job.total ? Math.min(100, Math.round(((job.done || 0) / job.total) * 100)) : (running ? null : (job.state === 'done' ? 100 : 0));
  const res = job.result || {};
  const items = Array.isArray(res.items) ? res.items.slice(0, 100) : [];
  const errs = Array.isArray(job.errors) ? job.errors.slice(0, 20) : [];
  const stateLabel = { running: t.wioWorking, queued: t.wioWorking, done: t.wioDone, failed: t.wioFailed, cancelled: t.wioCancelled }[job.state] || job.state;
  const stat = (k, v) => `<span>${esc(k)}: <strong class="tabular">${esc(String(v))}</strong></span>`;
  const preview = job.state === 'done' && res.dry_run === true;
  const done = job.state === 'done' && res.dry_run === false;
  const idx = res.index || {};
  const structure = res.structure || {};
  const countLabels = { to_import: t.wioImportToImport, duplicate: t.wioImportDuplicate, invalid: t.wioImportInvalid, imported: t.wioImportImported };
  return `
    <div class="wio-job" data-wio-job role="status" aria-live="polite">
      <div class="wio-job-head">
        <strong>${esc(stateLabel)}${job.phase && running ? ` · ${esc(job.phase)}` : ''}</strong>
        ${pct !== null ? `<span class="tabular">${esc(String(pct))}%</span>` : ''}
      </div>
      ${running || pct !== null && running ? `<div class="wio-bar" role="progressbar" aria-valuenow="${esc(String(pct || 0))}" aria-valuemin="0" aria-valuemax="100"><i data-css="width:${esc(String(pct || 0))}%"></i></div>` : ''}
      ${preview ? `<p class="wio-hint"><strong>${esc(t.wioPreviewDone)}</strong></p>` : ''}
      ${done ? `<p class="wio-hint"><strong>${esc(t.wioAppliedDone)}</strong></p>` : ''}
      ${running ? `<div class="wio-actions"><button type="button" class="btn btn-secondary btn-sm" data-action="wio-cancel" data-kind="${esc(kind)}">${esc(t.wioCancel)}</button></div>` : ''}
      ${res.counts ? `<div class="wio-facts">${Object.entries(res.counts).map(([k, v]) => stat(countLabels[k] || k, v)).join('')}</div>` : ''}
      ${res.structure ? `<div class="wio-facts">
        ${stat(t.wioInitFiles, structure.eligible_files != null ? structure.eligible_files : 0)}
        ${structure.markers && structure.markers.length ? stat('marcadores', structure.markers.join(', ')) : ''}
        ${structure.languages && Object.keys(structure.languages).length ? stat('linguagens', Object.keys(structure.languages).join(', ')) : ''}</div>` : ''}
      ${res.index ? `<div class="wio-facts">${stat(t.wioInitNew, idx.new ?? 0)}${stat(t.wioInitChanged, idx.changed ?? 0)}${stat(t.wioInitUnchanged, idx.unchanged ?? 0)}${stat(t.wioInitRemoved, idx.removed ?? 0)}${stat(t.wioIndexedItems, idx.total_after ?? 0)}</div>` : ''}
      ${res.records != null ? `<div class="wio-facts">${stat(t.wioRecords, res.records)}${res.redacted_records ? stat(t.wioRedacted, res.redacted_records) : ''}</div>` : ''}
      ${res.filename && done ? `<div class="wio-actions"><button type="button" class="btn btn-primary" data-action="wio-download" data-kind="${esc(kind)}">${esc(t.wioDownload)} <code>${esc(res.filename)}</code></button></div>` : ''}
      ${items.length ? `<details class="wio-items"><summary>${esc(t.wioImportItems)} (${esc(String(items.length))})</summary>
        <div class="wio-scroll"><table class="wio-table"><thead><tr><th scope="col">${esc(t.wioColFile)}</th><th scope="col">${esc(t.wioColTitle)}</th><th scope="col">${esc(t.wioColStatus)}</th><th scope="col">${esc(t.wioColReason)}</th></tr></thead>
        <tbody>${items.map((r) => `<tr><td>${esc(r.file || '')}</td><td>${esc(r.title || '')}</td><td>${esc(r.status || '')}</td><td>${esc(r.reason || '')}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
      ${res.skipped && Object.keys(res.skipped).length ? `<details class="wio-items"><summary>${esc(t.wioInitSkipped)}</summary>
        <ul>${Object.entries(res.skipped).map(([k, v]) => `<li>${esc(k)}: ${esc(String(v))}</li>`).join('')}</ul></details>` : ''}
      ${res.project_files && res.project_files.error ? `<div class="wio-alert is-bad" role="alert"><strong>${esc(res.project_files.message || res.project_files.error)}</strong>${res.project_files.hint ? `<p class="wio-hint">${esc(res.project_files.hint)}</p>` : ''}</div>` : ''}
      ${res.summary_note ? `<p class="wio-hint">${esc(t.wioInitNote)}: ${esc(res.summary_note.action || '')}</p>` : ''}
      ${errs.length ? `<div class="wio-alert is-bad"><strong>${esc(t.wioJobsError)} (${esc(String(job.errors.length))})</strong>
        <ul>${errs.map((e) => `<li>${esc(e.item || '')}: ${esc(e.message || '')}</li>`).join('')}</ul></div>` : ''}
      ${job.error ? `<div class="wio-alert is-bad" role="alert">${esc(job.error)}</div>` : ''}
    </div>${wioErrBox(wio.errs[kind])}`;
}

function wioButtons(kind, previewLabel, runLabel, extraDisabled = false) {
  const off = wio.busy || wioBlocked() || extraDisabled;
  return `<div class="wio-actions">
      <button type="button" class="btn btn-secondary" data-action="wio-dry" data-kind="${kind}" ${off ? 'disabled' : ''}>${esc(previewLabel)}</button>
      <button type="button" class="btn btn-primary" data-action="wio-run" data-kind="${kind}" ${off ? 'disabled' : ''}>${esc(runLabel)}</button>
    </div>`;
}

function wioInitHtml(t) {
  const ix = wio.status.data && wio.status.data.index;
  const indexed = !!(ix && ix.indexed);
  return `
    <div class="wio-form">
      <p class="wio-hint">${esc(indexed ? t.wioInitHintIndexed : t.wioInitHintFresh)}</p>
      <p class="wio-hint">${esc(t.wioSecretsNote)}</p>
      <label class="wio-check"><input type="checkbox" data-wio-opt="init-note"${wio.initOpts.note ? ' checked' : ''}> <span>${esc(t.wioSummaryNote)}</span></label>
      <label class="wio-check"><input type="checkbox" data-wio-opt="init-install"${wio.initOpts.install ? ' checked' : ''}> <span>${esc(t.wioInstallFiles)}</span></label>
      ${wioButtons('init', indexed ? t.wioVerify : t.wioPreview, indexed ? t.wioUpdateIndex : t.wioInitialize)}
      ${wioJobPanel('init')}
    </div>`;
}

function wioImportHtml(t) {
  const o = wio.importOpts;
  const off = wio.busy || wioBlocked();
  return `
    <div class="wio-form">
      <p class="wio-hint">${esc(t.wioImportHint)}</p>
      <div class="wio-radio" role="radiogroup" aria-label="${esc(t.wioImportSourceLabel)}">
        <label><input type="radio" name="wio-src" value="upload" data-wio-src${o.source === 'upload' ? ' checked' : ''}> ${esc(t.wioImportSourceUpload)}</label>
        <label><input type="radio" name="wio-src" value="path" data-wio-src${o.source === 'path' ? ' checked' : ''}> ${esc(t.wioImportSourcePath)}</label>
      </div>
      ${o.source === 'upload' ? `
      <input type="file" id="wio-import-files" multiple accept=".json,.md,.markdown" class="u-visually-hidden" tabindex="-1" data-wio-files>
      <input type="file" id="wio-import-dir" webkitdirectory class="u-visually-hidden" tabindex="-1" data-wio-files>
      <div class="wio-filepick">
        <button type="button" class="btn btn-secondary" data-action="wio-pick-files" ${wio.busy ? 'disabled' : ''}>${esc(t.wioImportPick)}</button>
        <button type="button" class="btn btn-secondary" data-action="wio-pick-dir" ${wio.busy ? 'disabled' : ''}>${esc(t.wioImportPickDir)}</button>
        <span class="wio-filecount" aria-live="polite">${esc(o.files.length ? t.wioFilesChosen.replace('{n}', String(o.files.length)) : t.wioNoFilesChosen)}</span>
      </div>` : `
      <label class="wio-field"><span>${esc(t.wioImportPathLabel)}</span>
        <input type="text" id="wio-import-path" data-wio-path value="${esc(o.path)}" placeholder="memorias/" autocomplete="off" spellcheck="false">
      </label>`}
      ${wioButtons('import', t.wioPreview, t.wioRun, o.source === 'path' && !!(wio.status.data && !wio.status.data.availability.available))}
      ${wioJobPanel('import')}
    </div>`;
}

function wioExportHtml(t) {
  const o = wio.exportOpts;
  const ix = wio.status.data && wio.status.data.index;
  const KINDS = [['memories', t.wioKindMemories], ['context', t.wioKindContext], ['metadata', t.wioKindMetadata],
    ['index', t.wioKindIndex], ['report', t.wioKindReport], ['metrics', t.wioKindMetrics]];
  const needIndex = o.kind === 'index' && ix && !ix.indexed;
  // Never widen a missing project to the global scope; all is an explicit choice.
  const needProject = (o.scope !== 'all' || o.kind === 'index') && !wioProject();
  const off = wio.busy || wio.status.apiMissing || needIndex || needProject;
  return `
    <div class="wio-form">
      <p class="wio-hint">${esc(t.wioSecretsNote)}</p>
      <div class="wio-grid">
        <label class="wio-field"><span>${esc(t.wioKindLabel)}</span>
          <select id="wio-exp-kind" data-wio-export="kind">${KINDS.map(([v, l]) => `<option value="${esc(v)}"${o.kind === v ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>
        </label>
        <label class="wio-field"><span>${esc(t.wioFormatLabel)}</span>
          <select id="wio-exp-format" data-wio-export="format">${['json', 'md', 'csv'].map((v) => `<option value="${esc(v)}"${o.format === v ? ' selected' : ''}>${esc(v.toUpperCase())}</option>`).join('')}</select>
        </label>
        <label class="wio-field"><span>${esc(t.wioScopeLabel)}</span>
          <select id="wio-exp-scope" data-wio-export="scope">
            <option value="project"${o.scope === 'project' ? ' selected' : ''}>${esc(t.wioScopeProject)}</option>
            <option value="all"${o.scope === 'all' ? ' selected' : ''}>${esc(t.wioScopeAll)}</option>
          </select>
        </label>
      </div>
      ${needIndex ? `<div class="wio-alert" role="status">${esc(t.wioIndexNeeded)}</div>` : ''}
      <div class="wio-actions">
        <button type="button" class="btn btn-secondary" data-action="wio-dry" data-kind="export" ${off ? 'disabled' : ''}>${esc(t.wioPreview)}</button>
        <button type="button" class="btn btn-primary" data-action="wio-run" data-kind="export" ${off ? 'disabled' : ''}>${esc(t.wioExportRun)}</button>
      </div>
      ${wioJobPanel('export')}
    </div>`;
}

function wioHistoryHtml(t) {
  if (wio.status.apiMissing || !wio.status.data) return '';
  const KIND = { initialize: t.wioTabInit, import: t.wioTabImport, export: t.wioTabExport };
  const ST = { done: t.wioDone, failed: t.wioFailed, cancelled: t.wioCancelled };
  return `
    <section aria-label="${esc(t.wioHistory)}" class="wio-hist">
      <h3 class="wio-section-title">${esc(t.wioHistory)}</h3>
      ${wio.history.length ? `<ul class="wio-history">${wio.history.map((h) => `
        <li><strong>${esc(KIND[h.kind] || h.kind)}</strong><span>${esc(ST[h.state] || h.state)}</span><span>${esc(fmtWhen(h.at))}</span>${h.summary ? `<span>${esc(h.summary)}</span>` : ''}</li>`).join('')}</ul>`
        : `<p class="wio-hint">${esc(t.wioHistoryEmpty)}</p>`}
    </section>`;
}

function wioCenterHtml(t) {
  const label = esc(t.wioTitle);
  if (!mockProjects.length) {
    return `<main class="workspace-center-col" aria-label="${label}">
      <div class="wio-empty">
        <h2>${esc(t.wioEmptyTitle)}</h2>
        <p class="wio-hint">${esc(t.wioEmptyDesc)}</p>
        <ol><li>${esc(t.wioEmptyStep1)}</li><li>${esc(t.wioEmptyStep2)}</li><li>${esc(t.wioEmptyStep3)}</li></ol>
        <button type="button" class="btn btn-primary" data-action="open-add-project">${icon('plus', '', 14)} ${esc(t.addProject)}</button>
      </div></main>`;
  }
  const tabLabel = { init: t.wioTabInit, import: t.wioTabImport, export: t.wioTabExport };
  const body = wio.tab === 'init' ? wioInitHtml(t) : wio.tab === 'import' ? wioImportHtml(t) : wioExportHtml(t);
  return `
    <main class="workspace-center-col" aria-label="${label}">
      <div class="wio-header">
        <div>
          <h2 class="card-title">${label}</h2>
          <div class="card-subtitle">${esc(t.wioSubtitle)}</div>
        </div>
        <div class="wio-toolbar">
          <button type="button" class="btn btn-ghost btn-icon" data-action="toggle-context-drawer" title="${esc(t.agentContextTitle)}" aria-label="${esc(t.agentContextTitle)}">${icon('database', '', 14)}</button>
          <button type="button" class="btn btn-ghost btn-icon" data-action="toggle-files-panel" title="${esc(t.filesTitle)}" aria-label="${esc(t.filesTitle)}" aria-pressed="${isFilesOpen}">${icon('sidebar', '', 14)}</button>
        </div>
      </div>
      ${wioProjectCard(t)}
      <div class="wio-tabs" role="tablist" aria-label="${label}" data-bind="wio-tablist">
        ${WIO_TABS.map((k) => `<button type="button" role="tab" class="wio-tab${wio.tab === k ? ' is-active' : ''}" id="wio-tab-${k}" data-action="wio-tab" data-tab="${k}" aria-selected="${wio.tab === k}" aria-controls="wio-panel" tabindex="${wio.tab === k ? '0' : '-1'}">${esc(tabLabel[k])}</button>`).join('')}
      </div>
      <div class="wio-body" role="tabpanel" id="wio-panel" aria-labelledby="wio-tab-${wio.tab}">${body}</div>
      ${wioHistoryHtml(t)}
    </main>`;
}

function wioPatchProgress(root, kind) {
  const holder = root.querySelector('[data-wio-job]');
  if (holder && wio.tab === kind) holder.outerHTML = wioJobPanel(kind);
}

const WIO_PATH = { init: 'initialize', import: 'import', export: 'export' };

async function wioSubmit(root, kind, dryRun) {
  if (wio.busy) return;
  const t = I18N.workspace;
  const pid = activeProjectId;
  let body;
  if (kind === 'init') {
    body = { project_id: pid, dry_run: dryRun, install_project_files: !!wio.initOpts.install, summary_note: !!wio.initOpts.note };
  } else if (kind === 'import') {
    const o = wio.importOpts;
    if (o.source === 'upload' && !o.files.length) { toast('error', t.wioNeedFiles); return; }
    if (o.source === 'path' && !o.path.trim()) { toast('error', t.wioNeedPath); return; }
    body = { project_id: pid, dry_run: dryRun, source: o.source,
             files: o.source === 'upload' ? o.files.map((f) => ({ name: f.name, content: f.content })) : [],
             path: o.source === 'path' ? o.path.trim() : '' };
  } else {
    if ((wio.exportOpts.scope !== 'all' || wio.exportOpts.kind === 'index') && !wioProject()) {
      toast('error', t.wioScopeProject || 'Selecione um projeto para exportar este escopo.');
      return;
    }
    body = { project_id: pid, dry_run: dryRun, kind: wio.exportOpts.kind, format: wio.exportOpts.format, scope: wio.exportOpts.scope };
  }
  wioStopPolling();
  wio.busy = true;
  wio.errs[kind] = null;
  wio.jobs[kind] = null;
  refresh(root);
  try {
    const resp = await call('POST', `/api/workspace/io/${WIO_PATH[kind]}`, body);
    const job = (resp && resp.job) || resp;
    wio.jobs[kind] = job;
    if (job && (job.state === 'running' || job.state === 'queued')) wioStartPolling(root, kind, job.id);
    else if (!dryRun) wioLoadStatus(root);
  } catch (err) {
    wio.errs[kind] = apiErr(err);
  } finally {
    wio.busy = false;
    if (root.isConnected) refresh(root);
  }
}

function wioStartPolling(root, kind, jobId) {
  wioStopPolling();
  wio.timer = setInterval(async () => {
    if (!root.isConnected) { wioStopPolling(); return; }
    try {
      const j = await call('GET', `/api/workspace/io/jobs/${encodeURIComponent(jobId)}`);
      const job = (j && j.job) || j;
      if (!job || job.id !== jobId) return;
      wio.jobs[kind] = job;
      if (job.state === 'running' || job.state === 'queued') {
        wioPatchProgress(root, kind);
      } else {
        wioStopPolling();
        refresh(root);
        wioLoadStatus(root); // índice e histórico reais após a conclusão
      }
    } catch (err) {
      if (err && err.status === 404) { // job expirou/servidor reiniciou
        wioStopPolling();
        wio.jobs[kind] = null;
        wio.errs[kind] = { message: I18N.workspace.wioJobLost, hint: '' };
        refresh(root);
      } /* senão: rede instável, tenta no próximo ciclo */
    }
  }, 700);
}

function wioStopPolling() {
  if (wio.timer) { clearInterval(wio.timer); wio.timer = null; }
}

async function wioCancel(root, kind) {
  const job = wio.jobs[kind];
  if (!job || !job.id) return;
  try {
    const j = await call('POST', `/api/workspace/io/jobs/${encodeURIComponent(job.id)}/cancel`, {});
    wio.jobs[kind] = (j && j.job) || j;
    wioStartPolling(root, kind, job.id); // aguarda o estado final (cancelamento é cooperativo)
  } catch (err) {
    toast('error', apiErr(err).message);
  }
  refresh(root);
}

/** Baixa o arquivo gerado por um job de exportação (com token; sempre download, nunca nova aba). */
async function wioDownload(kind) {
  const job = wio.jobs[kind];
  if (!job || !job.id) return;
  try {
    let token = '';
    try { token = await getLocalToken(); } catch { /* loopback funciona sem token */ }
    const r = await fetch(`/api/workspace/io/jobs/${encodeURIComponent(job.id)}/download`,
      { cache: 'no-store', headers: token ? { 'X-MG-Token': token } : {} });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (job.result && job.result.filename) || 'anamnesia-export';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  } catch (err) {
    toast('error', (err && err.message) || String(err));
  }
}

/** Lê arquivos .md/.markdown/.json do input (arquivo ou pasta); ignora o resto e respeita os limites do servidor. */
const WIO_EXT = /\.(md|markdown|json)$/i;
async function wioReadFiles(input) {
  const files = [];
  let total = 0;
  let skipped = 0;
  for (const f of Array.from(input.files || [])) {
    if (!WIO_EXT.test(f.name) || f.size > 512 * 1024 || total + f.size > 8 * 1024 * 1024 || files.length >= 500) { skipped += 1; continue; }
    try { files.push({ name: f.name, content: await f.text() }); total += f.size; } catch { skipped += 1; }
  }
  return { files, skipped };
}


function ctxBody() {
  const t = I18N.workspace;
  if (ctx.status === 'loading' || ctx.status === 'idle') return loadingBlock(skeletonLines(5), t.agentContextTitle);
  if (ctx.status === 'error') return emptyState({ title: t.ctxErrorTitle, description: ctx.error, variant: 'error', compact: true });
  if (ctx.status === 'empty') return emptyState({ title: t.ctxEmptyTitle, description: t.ctxEmptyDesc, variant: 'search', compact: true });
  const d = ctx.data;
  const tk = d.tokens || {};
  const num = (v) => fmtNumber(v);
  const when = d.created_at ? fmtDate(d.created_at) : '—';
  return `
    <div class="memory-context-card">
      <div class="u-e38bd9">${esc(t.ctxQuery)}: ${esc(d.query || '—')}</div>
      <div class="memory-context-meta">
        <span>${esc(when)}</span>
        <span>${esc(d.pipeline || '')}${d.cache_hit ? ` · ${esc(t.ctxCache)}` : ''}</span>
      </div>
      <div class="memory-context-meta">
        <span class="badge-origin badge-origin-measured">${esc(t.ctxTokensContext)}: ${esc(num(tk.context))} tok</span>
        <span>${esc(t.ctxTokensCandidates)}: ${esc(num(tk.candidates))}</span>
      </div>
    </div>
    ${(d.sources || []).map((s) => `
      <div class="memory-context-card">
        <div class="u-e38bd9">${esc(s.section || s.file || '—')}</div>
        <div class="u-575e4a">${esc(s.file || '')}</div>
        <div class="memory-context-meta">
          <span class="badge-origin badge-origin-measured">${esc(num(s.tokens))} tok</span>
          <span>Score: ${esc(typeof s.score === 'number' ? s.score.toFixed(3) : '—')}${s.decision ? ` · ${esc(s.decision)}` : ''}</span>
        </div>
      </div>`).join('')}`;
}

function paintCtx(root) {
  const el = root.querySelector('[data-bind="ctx-body"]');
  if (el) el.innerHTML = ctxBody();
}

async function loadContext(root) {
  ctx = { status: 'loading', data: null, error: '' };
  paintCtx(root);
  try {
    const d = await lastSearch();
    ctx = d && d.found ? { status: 'ok', data: d, error: '' } : { status: 'empty', data: null, error: '' };
  } catch (e) {
    ctx = { status: 'error', data: null, error: isUnavailable(e) ? I18N.app.backendUnavailableDesc : (e && e.message) || String(e) };
  }
  if (root.isConnected) paintCtx(root);
}


function rmModalHtml(t) {
  if (!rm) return '';
  const e = rm.err;
  return `
    <div class="modal-backdrop is-active" data-action="rm-backdrop" data-bind="rm-modal">
      <div class="modal-dialog" role="alertdialog" aria-modal="true" aria-labelledby="rm-title" aria-describedby="rm-desc" tabindex="-1">
        <div class="modal-header"><h3 id="rm-title" class="card-title">${esc(t.rmTitle)}</h3></div>
        <div class="modal-body" id="rm-desc">
          <p>${esc(t.rmLead)}</p>
          <dl class="rm-facts"><dt>${esc(t.rmName)}</dt><dd data-bind="rm-name">${esc(rm.name)}</dd><dt>${esc(t.rmPath)}</dt><dd><code data-bind="rm-path">${esc(rm.path)}</code></dd></dl>
          <p class="wio-hint">${esc(t.rmKeepIndex)}</p>
          <label class="rm-purge"><input type="checkbox" id="rm-purge" data-rm-purge${rm.purge ? ' checked' : ''}${rm.busy ? ' disabled' : ''} /> <span>${esc(t.rmPurge)}</span></label>
          ${rm.purge ? `<p class="add-error" role="note">${esc(t.rmPurgeWarn)}</p>` : ''}
          ${e ? `<div class="add-error" role="alert" data-bind="rm-error"><strong>${esc(t.rmFail)}</strong><p>${esc(e)}</p></div>` : ''}
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" id="rm-cancel" data-action="rm-cancel"${rm.busy ? ' disabled' : ''}>${esc(t.rmCancel)}</button>
          <button type="button" class="btn btn-danger" id="rm-confirm" data-action="rm-confirm"${rm.busy ? ' disabled aria-busy="true"' : ''}>${esc(rm.busy ? t.rmBusy : t.rmConfirm)}</button>
        </div>
      </div>
    </div>`;
}

export function render() {
  const t = I18N.workspace;
  if (!mockProjects.some(p => p.id === activeProjectId) && mockProjects[0]) activeProjectId = mockProjects[0].id;

  // Render Skeleton state
  if (currentState === 'loading') {
    return `
      <div class="workspace-layout">
        <div class="workspace-left-col u-bcd0d8">
          <div class="skeleton u-402c12"></div>
          <div class="skeleton u-afea74"></div>
          <div class="skeleton u-afea74"></div>
          <div class="skeleton u-114891"></div>
        </div>
        <div class="workspace-center-col u-7174bc">
          <div class="skeleton u-d53754"></div>
          <div class="skeleton u-0be86d"></div>
        </div>
      </div>
    `;
  }

  // Render Error state
  if (currentState === 'error') {
    return `
      <div class="state-container u-2d3094">
        <div class="state-icon-wrap u-52b1c0">${icon('alertTriangle', '', 24)}</div>
        <h2 class="state-title">${I18N.app.errorTitle}</h2>
        <p class="state-description">Falha ao carregar o workspace.</p>
        <button class="btn btn-secondary" data-action="retry-state">${I18N.app.errorRetry}</button>
      </div>
    `;
  }

  // Render Empty state
  if (currentState === 'empty') {
    return `
      <div class="workspace-layout">
        <div class="workspace-left-col">
          <div class="pane-header">
            <span class="pane-title">${t.projectsTitle}</span>
            <button class="btn btn-secondary btn-sm" data-action="open-add-project">${icon('plus', '', 12)} ${t.addProject}</button>
          </div>
          <div class="state-container u-97d464">
            <p class="state-description">Nenhum projeto cadastrado.</p>
          </div>
        </div>
        <div class="workspace-center-col">
          <div class="state-container u-2d3094">
            <div class="state-icon-wrap">${icon('folder', '', 28)}</div>
            <h2 class="state-title">${I18N.app.noProjectsTitle || 'Nenhum projeto'}</h2>
            <p class="state-description">${I18N.app.noProjectsDesc || 'Adicione um projeto para começar.'}</p>
            <div class="u-387c0c">
              <button class="btn btn-primary" data-action="open-add-project">${icon('plus', '', 14)} ${t.addProject}</button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // Render Backend Unavailable callout overlay
  const backendNotice = currentState === 'backend-unavailable' ? `
    <div class="u-315653">
      <div class="callout-notice">
        <div class="callout-notice-icon">${icon('info', '', 18)}</div>
        <div class="callout-notice-body">
          <strong>${I18N.app.backendUnavailableTitle}</strong>
          ${I18N.app.backendUnavailableDesc}
        </div>
      </div>
    </div>
  ` : '';

  // Filter files
  const filteredFiles = searchFilter
    ? mockFiles.filter(f => f.name.toLowerCase().includes(searchFilter.toLowerCase()))
    : mockFiles;

  const px = (n) => (typeof n === 'number' && Number.isFinite(n) ? `width:${Math.round(n)}px;min-width:${Math.round(n)}px;max-width:${Math.round(n)}px;` : '');

  // Active Project
  const activeProject = mockProjects.find(p => p.id === activeProjectId) || mockProjects[0];

  return `
    <div class="workspace-layout" data-bind="workspace-root">
      ${backendNotice}

      <!-- COLUNA ESQUERDA: Projetos (~260px) -->
      <aside class="workspace-left-col" aria-label="Projetos registrados" data-css="${px(colWidths.left)}">
        <div class="pane-header">
          <span class="pane-title">${t.projectsTitle}</span>
          <button class="btn btn-ghost btn-sm" data-action="open-add-project" title="${t.addProject}" aria-label="${t.addProject}">
            ${icon('plus', '', 14)}
          </button>
        </div>

        ${jevPanel(t)}

        <div class="projects-list-container" data-bind="projects-list" role="list" aria-label="${esc(I18N.a11y.projects)}">
          ${mockProjects.length ? '' : `<p class="wio-hint">${esc(t.noProjectsList)}</p>`}
          ${mockProjects.map(proj => {
            const isActive = proj.id === activeProjectId;
            return `
              <div role="listitem" class="project-li" data-project-li="${esc(proj.id)}"><button type="button" class="project-item ${isActive ? 'is-active' : ''}" data-action="select-project" data-project-id="${esc(proj.id)}" aria-current="${isActive ? 'true' : 'false'}" aria-keyshortcuts="Delete" title="${esc(proj.path)}">
                <div class="project-info">
                  <div class="project-name-row">
                    <span class="dot dot-neutral" title="${isActive ? 'Projeto ativo' : 'Inativo'}"></span>
                    <span class="project-name">${proj.name}</span>
                  </div>
                  <span class="project-path">${proj.path}</span>
                </div>
              </button><button type="button" class="btn btn-ghost btn-sm project-remove" data-action="remove-project" data-project-id="${esc(proj.id)}" title="${esc(t.rmProject)}" aria-label="${esc(t.rmProjectAria.replace('{name}', unesc(proj.name)))}">${icon('x', '', 12)}<span class="project-remove-label">${esc(t.rmProject)}</span></button></div>
            `;
          }).join('')}
        </div>

      </aside>
      <div class="ws-resizer" data-resize="left" role="separator" aria-orientation="vertical" aria-label="${esc(t.resizeLeft)}" tabindex="0"></div>

      ${wioCenterHtml(t)}
      ${rmModalHtml(t)}

      <!-- COLUNA DIREITA: Arquivos do Projeto Ativo (~280px, recolhível) -->
      <div class="ws-resizer ${!isFilesOpen ? 'is-hidden' : ''}" data-resize="right" role="separator" aria-orientation="vertical" aria-label="${esc(t.resizeRight)}" tabindex="0"></div>
      <aside class="workspace-right-col ${!isFilesOpen ? 'is-collapsed' : ''}" aria-label="Arquivos do projeto" data-css="${isFilesOpen ? px(colWidths.right) : ''}">
        <div class="pane-header">
          <span class="pane-title">${t.filesTitle}</span>
          <span class="section-count">${filteredFiles.length}</span>
        </div>

        <div class="files-search-wrap">
          <div class="input-control u-20984e">
            ${icon('search', '', 12)}
            <input type="text" placeholder="${t.searchFiles}" data-action="filter-files" value="${esc(searchFilter)}" class="u-e3ec32" aria-label="${esc(t.searchFiles)}" />
          </div>
        </div>

        <div class="file-tree-container" data-bind="files-tree" role="tree" aria-label="${t.filesTitle}">
          ${fileItemsHtml(filteredFiles)}
        </div>
      </aside>

      <!-- GAVETA LATERAL: Contexto do Agente (Recolhível) -->
      <div class="drawer-backdrop ${isContextDrawerOpen ? 'is-active' : ''}" data-action="close-context-drawer"></div>
      <div class="drawer ${isContextDrawerOpen ? 'is-active' : ''}">
        <div class="drawer-header">
          <div>
            <div class="card-title">${t.agentContextTitle}</div>
            <div class="card-subtitle">${t.agentContextSubtitle}</div>
          </div>
          <div class="u-245375">
            <button class="btn btn-ghost btn-icon" data-action="refresh-context" title="${esc(t.ctxRefresh)}" aria-label="${esc(t.ctxRefresh)}">${icon('refresh', '', 14)}</button>
            <a class="btn btn-ghost btn-icon" href="#/memory" title="${esc(t.ctxOpenMemory)}" aria-label="${esc(t.ctxOpenMemory)}">${icon('search', '', 14)}</a>
            <button class="btn btn-ghost btn-icon" data-action="close-context-drawer" aria-label="Fechar">${icon('x', '', 16)}</button>
          </div>
        </div>
        <div class="drawer-content" data-bind="ctx-body">
          ${ctxBody()}
        </div>
      </div>
    </div>
  `;
}


/** Itens do painel de arquivos: pastas expandem/recolhem, arquivos abrem o visualizador. */
function fileItemsHtml(list) {
  if (!list.length) {
    const msg = searchFilter ? I18N.workspace.filesNoMatch : (mockProjects.length ? I18N.workspace.filesEmpty : I18N.workspace.filesNoProject);
    return `<p class="wio-hint file-tree-empty">${esc(msg)}</p>`;
  }
  return list.map((file) => {
    const isDir = file.type === 'dir';
    const indentClass = file.indent > 0 ? `file-indent-${Math.min(file.indent, 6)}` : '';
    const sel = !isDir && file.path && file.path === selectedFilePath;
    const aria = isDir ? ` aria-expanded="${file.expanded ? 'true' : 'false'}"` : '';
    return `
      <div class="file-tree-item ${indentClass} ${sel ? 'is-selected' : ''}" title="${file.name}" role="treeitem" tabindex="0"
           data-file-path="${esc(file.path || '')}" data-file-type="${isDir ? 'dir' : 'file'}"${aria} aria-selected="${sel ? 'true' : 'false'}">
        ${icon(isDir ? 'folder' : 'file', '', 13)}
        <span class="u-e488bc">${file.name}</span>
        ${file.size ? `<span class="u-038f65">${file.size}</span>` : ''}
      </div>
    `;
  }).join('');
}

function filteredFileList() {
  return searchFilter ? mockFiles.filter((f) => f.name.toLowerCase().includes(searchFilter.toLowerCase())) : mockFiles;
}

function viewerStrings() {
  const t = I18N.workspace;
  return { copy: t.fileCopy, copied: t.fileCopied, close: t.fileClose, wrap: t.fileWrap, loading: t.fileLoading,
    error: t.fileError, truncated: t.fileTruncated, unavailable: t.filePreviewUnavailable };
}

async function activateFile(root, item) {
  const path = item.getAttribute('data-file-path');
  if (!path) return;
  const file = mockFiles.find((f) => f.path === path);
  if (!file) return;
  if (file.type === 'dir') {
    try { await toggleDir(file); } catch { /* sem acesso: mantém a pasta fechada */ }
    updateFileTree(root, path);
    return;
  }
  selectedFilePath = path;
  updateFileTree(root, path);
  openFileViewer(path, () => fileContent(path), viewerStrings());
}

function updateFileTree(root, focusPath) {
  const tree = root.querySelector('[data-bind="files-tree"]');
  if (!tree) return;
  const list = filteredFileList();
  tree.innerHTML = fileItemsHtml(list);
  const count = root.querySelector('.workspace-right-col .section-count');
  if (count) count.textContent = String(list.length);
  if (focusPath) {
    const again = [...tree.querySelectorAll('[data-file-path]')].find((n) => n.getAttribute('data-file-path') === focusPath);
    if (again) again.focus();
  }
}


// mockProjects guarda strings já escapadas por live.js; o modal escapa na saída, então desfaz antes (sem escape duplo).
const unesc = (s) => String(s ?? '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');

function rmOpen(root, id, trigger) {
  const p = mockProjects.find((x) => x.id === id);
  if (!p) return;
  rmTrigger = trigger || document.activeElement;
  rm = { id: p.id, name: unesc(p.name), path: unesc(p.path), purge: false, busy: false, err: null };
  refresh(root);
  root.querySelector('#rm-cancel')?.focus();
}

function rmClose(root) {
  if (!rm || rm.busy) return;
  const id = rm.id;
  rm = null;
  refresh(root);
  const back = root.querySelector(`[data-action="remove-project"][data-project-id="${CSS.escape(id)}"]`) || (rmTrigger && rmTrigger.isConnected ? rmTrigger : null);
  rmTrigger = null;
  back?.focus();
}

async function rmSubmit(root, selectProject) {
  if (!rm || rm.busy) return;
  const t = I18N.workspace;
  const { id, name, purge } = rm;
  rm.busy = true; rm.err = null;
  refresh(root);
  let gone = false;
  try {
    await unregisterProject(id, purge);
  } catch (err) {
    if (err && err.status === 404 && err.code === 'not_found') {
      gone = true; // remoção duplicada: já não existe; atualiza a lista
      try { await refreshWorkspace(); } catch { /* lista fica como está */ }
    } else {
      if (rm) { rm.busy = false; rm.err = (err && err.message) || String(err); refresh(root); root.querySelector('#rm-cancel')?.focus(); }
      return;
    }
  }
  const wasActive = activeProjectId === id;
  rm = null; rmTrigger = null;
  toast(gone ? 'info' : 'success', (gone ? t.rmGone : (purge ? t.rmDonePurged : t.rmDone)).replace('{name}', name));
  if (wasActive) {
    const next = mockProjects[0] ? mockProjects[0].id : '';
    wioStopPolling();
    wio.busy = false; wio.jobs = { init: null, import: null, export: null }; wio.errs = { init: null, import: null, export: null };
    wio.status = { loading: false, data: null, error: null, apiMissing: false }; wio.history = [];
    selectedFilePath = ''; searchFilter = ''; mockFiles.length = 0;
    activeProjectId = next;
    if (next) { selectProject(next); } else { refresh(root); }
  } else {
    refresh(root);
  }
  (root.querySelector('[data-action="select-project"]') || root.querySelector('[data-action="open-add-project"]'))?.focus();
}

export function mount(root) {
  const selectProject = (id) => {
    activeProjectId = id;
    wioStopPolling();
    wio.busy = false;
    wio.jobs = { init: null, import: null, export: null };
    wio.errs = { init: null, import: null, export: null };
    wio.importOpts.files = [];
    selectedFilePath = '';
    searchFilter = '';
    wio.status = { loading: true, data: null, error: null, apiMissing: false };
    wio.history = [];
    refresh(root);
    loadFiles(id).catch(() => { mockFiles.length = 0; }).finally(() => { if (root.isConnected) refresh(root); });
    wioLoadStatus(root);
  };

  const handleClick = (e) => {
    const fileItem = e.target.closest('.file-tree-item[data-file-path]');
    if (fileItem) { activateFile(root, fileItem); return; }
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.getAttribute('data-action');
    const kind = target.getAttribute('data-kind');
    switch (action) {
      case 'select-project': {
        const id = target.getAttribute('data-project-id');
        if (id && id !== activeProjectId) selectProject(id);
        break;
      }
      case 'remove-project': rmOpen(root, target.getAttribute('data-project-id'), target); break;
      case 'rm-cancel': rmClose(root); break;
      case 'rm-backdrop': if (e.target === target) rmClose(root); break;
      case 'rm-confirm': rmSubmit(root, selectProject); break;
      case 'wio-tab': {
        const k = target.getAttribute('data-tab');
        if (WIO_TABS.includes(k) && k !== wio.tab) { wio.tab = k; refresh(root); }
        break;
      }
      case 'wio-dry': wioSubmit(root, kind, true); break;
      case 'wio-run': wioSubmit(root, kind, false); break;
      case 'wio-cancel': wioCancel(root, kind); break;
      case 'wio-download': wioDownload(kind); break;
      case 'wio-pick-files': root.querySelector('#wio-import-files')?.click(); break;
      case 'wio-pick-dir': root.querySelector('#wio-import-dir')?.click(); break;
      case 'toggle-files-panel': isFilesOpen = !isFilesOpen; persistLayout(); refresh(root); break;
      case 'toggle-context-drawer': isContextDrawerOpen = !isContextDrawerOpen; refresh(root); if (isContextDrawerOpen) loadContext(root); break;
      case 'close-context-drawer': isContextDrawerOpen = false; refresh(root); break;
      case 'refresh-context': loadContext(root); break;
      case 'jev-toggle': {
        jev.open = !jev.open; jev.test = null; jev.msg = null; jev.err = null; jev.draft = {}; jev.key = '';
        refresh(root);
        if (jev.open) jevLoad(root);
        break;
      }
      case 'jev-adv': jev.adv = !jev.adv; refresh(root); break;
      case 'jev-save': jevRun(root, 'save'); break;
      case 'jev-test': jevRun(root, 'test'); break;
      case 'open-add-project': window.dispatchEvent(new CustomEvent('anamnesia:modal:add-project')); break;
      case 'retry-state': currentState = 'loaded'; refresh(root); break;
      default: break;
    }
  };

  const handleInput = (e) => {
    const el = e.target;
    if (el.matches && el.matches('[data-jev-key]')) { jev.key = el.value; return; }
    const jf = el.getAttribute && el.getAttribute('data-jev');
    if (jf && el.type !== 'checkbox') { jev.draft[jf] = el.value; return; }
    if (el.matches && el.matches('[data-wio-path]')) { wio.importOpts.path = el.value; return; }
    if (el.matches && el.matches('[data-action="filter-files"]')) { searchFilter = el.value; updateFileTree(root); }
  };

  const handleChange = async (e) => {
    const el = e.target;
    const jf = el.getAttribute && el.getAttribute('data-jev');
    if (jf) { jev.draft[jf] = el.type === 'checkbox' ? !!el.checked : el.value; return; }
    if (el.matches && el.matches('[data-rm-purge]')) { if (rm) { rm.purge = !!el.checked; refresh(root); } return; }
    const opt = el.getAttribute && el.getAttribute('data-wio-opt');
    if (opt === 'init-install') { wio.initOpts.install = !!el.checked; return; }
    if (opt === 'init-note') { wio.initOpts.note = !!el.checked; return; }
    const ex = el.getAttribute && el.getAttribute('data-wio-export');
    if (ex && ['kind', 'format', 'scope'].includes(ex)) { wio.exportOpts[ex] = el.value; wio.jobs.export = null; wio.errs.export = null; refresh(root); return; }
    if (el.matches && el.matches('[data-wio-src]')) {
      wio.importOpts.source = el.value === 'path' ? 'path' : 'upload';
      wio.jobs.import = null; wio.errs.import = null;
      refresh(root);
      return;
    }
    if (el.matches && el.matches('[data-wio-files]')) {
      const { files, skipped } = await wioReadFiles(el);
      wio.importOpts.files = files;
      wio.jobs.import = null;
      wio.errs.import = skipped && !files.length ? { message: I18N.workspace.wioNoValidFiles, hint: '' } : null;
      if (skipped && files.length) toast('info', I18N.workspace.wioSkippedFiles.replace('{n}', String(skipped)));
      refresh(root);
    }
  };

  // Redimensionamento por arrasto das colunas esquerda/direita (teclado: setas).
  let drag = null;
  const onMove = (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.x0;
    const w = clamp(drag.kind === 'left' ? drag.w0 + dx : drag.w0 - dx, LIMITS[drag.kind]);
    colWidths[drag.kind] = w;
    drag.el.style.width = drag.el.style.minWidth = drag.el.style.maxWidth = `${Math.round(w)}px`;
  };
  const onUp = () => {
    if (!drag) return;
    drag = null;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.body.classList.remove('ws-resizing');
    persistLayout();
  };
  const colEl = (kind) => root.querySelector(kind === 'left' ? '.workspace-left-col' : '.workspace-right-col');
  const handleDown = (e) => {
    const h = e.target.closest && e.target.closest('[data-resize]');
    if (!h) return;
    const kind = h.getAttribute('data-resize');
    const el = colEl(kind);
    if (!el) return;
    drag = { kind, el, x0: e.clientX, w0: el.getBoundingClientRect().width };
    e.preventDefault();
    document.body.classList.add('ws-resizing');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  };

  const handleKey = (e) => {
    const rz = e.target.closest && e.target.closest('[data-resize]');
    if (rz && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      const kind = rz.getAttribute('data-resize');
      const el = colEl(kind);
      if (!el) return;
      e.preventDefault();
      const step = (e.key === 'ArrowRight' ? 1 : -1) * (kind === 'left' ? 1 : -1) * 16;
      const w = clamp(el.getBoundingClientRect().width + step, LIMITS[kind]);
      colWidths[kind] = w;
      el.style.width = el.style.minWidth = el.style.maxWidth = `${Math.round(w)}px`;
      persistLayout();
      return;
    }
    // Abas da Central (APG): setas movem e ativam, Home/End vão às pontas.
    const tabBtn = e.target.closest && e.target.closest('.wio-tab');
    if (tabBtn) {
      const i = WIO_TABS.indexOf(tabBtn.getAttribute('data-tab'));
      const n = e.key === 'ArrowRight' ? (i + 1) % WIO_TABS.length : e.key === 'ArrowLeft' ? (i - 1 + WIO_TABS.length) % WIO_TABS.length
        : e.key === 'Home' ? 0 : e.key === 'End' ? WIO_TABS.length - 1 : -1;
      if (n >= 0) { e.preventDefault(); wio.tab = WIO_TABS[n]; refresh(root); root.querySelector(`#wio-tab-${WIO_TABS[n]}`)?.focus(); }
      return;
    }
    const item = e.target.closest && e.target.closest('.file-tree-item[data-file-path]');
    if (!item) return;
    const items = [...root.querySelectorAll('.file-tree-item[data-file-path]')];
    const idx = items.indexOf(item);
    const isDir = item.getAttribute('data-file-type') === 'dir';
    const open = item.getAttribute('aria-expanded') === 'true';
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activateFile(root, item); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[Math.min(idx + 1, items.length - 1)]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[Math.max(idx - 1, 0)]?.focus(); }
    else if (e.key === 'ArrowRight' && isDir && !open) { e.preventDefault(); activateFile(root, item); }
    else if (e.key === 'ArrowLeft' && isDir && open) { e.preventDefault(); activateFile(root, item); }
  };

  root.addEventListener('click', handleClick);
  root.addEventListener('keydown', handleKey);
  root.addEventListener('input', handleInput);
  root.addEventListener('change', handleChange);
  root.addEventListener('pointerdown', handleDown);

  root._workspaceCleanup = () => {
    root.removeEventListener('click', handleClick);
    root.removeEventListener('keydown', handleKey);
    root.removeEventListener('input', handleInput);
    root.removeEventListener('change', handleChange);
    root.removeEventListener('pointerdown', handleDown);
    onUp();
    wioStopPolling();
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; if (layoutReady) putSettings({ workspace_layout: snapshotLayout() }).catch(() => {}); }
  };

  restoreLayout(root);
  jevLoad(root);
  wioLoadStatus(root);
}

function focusKey(el) {
  if (!el || !el.getAttribute || !el.closest || el === document.body) return null;
  const a = el.getAttribute('data-action');
  const pid = el.getAttribute('data-project-id');
  const tab = el.getAttribute('data-tab');
  const kind = el.getAttribute('data-kind');
  if (el.id) return `#${CSS.escape(el.id)}`;
  if (a === 'select-project' && pid) return `[data-action="select-project"][data-project-id="${CSS.escape(pid)}"]`;
  if (a && tab) return `[data-action="${a}"][data-tab="${CSS.escape(tab)}"]`;
  if (a && kind) return `[data-action="${a}"][data-kind="${CSS.escape(kind)}"]`;
  if (a && el.closest('.workspace-layout, [data-bind]')) return `[data-action="${a}"]`;
  return null;
}

function refresh(root) {
  const active = document.activeElement;
  const key = root.contains(active) ? focusKey(active) : null;
  root.innerHTML = render();
  if (key) { try { root.querySelector(key)?.focus({ preventScroll: true }); } catch { /* seletor inválido: sem restaurar */ } }
}


export function unmount(root) {
  wioStopPolling();
  if (root && root._workspaceCleanup) {
    root._workspaceCleanup();
    delete root._workspaceCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) refresh(root);
}
