/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA WORKSPACE PAGE (#/workspace)
 * 3-column desktop IDE layout: Projects | Terminals Canvas | Files & Context
 */

import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { mockProjects, mockProfiles, mockSessions, mockFiles } from '../mock-data.js';
import { renderTerminalFrame } from '../components/terminal-view.js';
import { launchSession, closeSession, loadFiles, toggleDir, fileContent, initializeProject, jevStatus, jevSaveConfig, jevTestConnection } from '../live.js';
import { openFileViewer } from '../components/file-viewer.js';
import { esc, fmtNumber, fmtDate } from '../format.js';
import { getSettings, putSettings, lastSearch, isUnavailable } from '../anamnesia-api.js';
import { skeletonLines, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';

let currentState = 'loaded'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'
let activeProjectId = 'proj-1';
let activeSessionId = 'sess-1';
let isSplitMode = false;
let splitDirection = 'vertical'; // 'vertical' | 'horizontal'
let isFilesOpen = true;
let isContextDrawerOpen = false;
let isProfileMenuOpen = false;
let searchFilter = '';
let selectedFilePath = '';

// ---- layout persistente (PUT /api/settings terminal_layout) ----
const ROLES = ['orchestrator', 'researcher', 'implementer', 'reviewer'];
const LIMITS = { left: [200, 480], right: [200, 560] };
let launchOpts = { worktree: false, role: '', mcp: 'default' }; // mcp: default | on | off
let sessionOrder = []; // ids das sessões na ordem das abas
let splitSessionId = null;
let splitRatio = 0.5;
let colWidths = { left: null, right: null };
let layoutReady = false;
let layoutRestoring = false;
let saveTimer = null;
// ---- painel "Contexto do agente" (GET /api/memory/last-search) ----
let initState = { busy: false, report: null, error: null, projectId: null }; // botão 'Inicializar Anamnésia'
let ctx = { status: 'idle', data: null, error: '' }; // idle | loading | ok | empty | error

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));
const isLiveSession = (s) => !s.real || s.status === 'active';

/** Sessões na ordem salva; ids novos entram no fim. */

/** Traduz uma falha da API em título/explicação/o que fazer (nunca mostra "404 Not Found" cru). */
function initErrorInfo(t, err) {
  const known = t.initErrors || {};
  const code = err.code || (err.status === 404 || err.status === 405 ? 'route_missing'
    : err.status === 0 ? 'network' : err.status === 403 ? 'forbidden' : 'unknown');
  const base = known[code] || known.unknown;
  return { title: base.title, why: err.code ? (err.detail || '') : '', hint: err.hint || base.hint, code };
}

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

/** Botão + relatório de "Inicializar Anamnésia no projeto" (a lógica vive no backend: app/services/project_initializer.py). */
function initPanel(t, projectId) {
  if (!projectId || !mockProjects.some((p) => p.id === projectId)) return '';
  const own = initState.projectId === projectId;
  const list = (title, items, cls) => (items && items.length
    ? `<div class="init-sub">${esc(title)}</div><ul class="init-list ${cls || ''}">${items.map((x) => (typeof x === 'string'
      ? `<li><code>${esc(x)}</code></li>`
      : `<li><code>${esc(x.path)}</code><span class="init-reason">${esc(x.reason)}</span></li>`)).join('')}</ul>` : '');
  let body = '';
  let tone = '';
  if (own && initState.error) {
    const e = initErrorInfo(t, initState.error);
    tone = 'is-error';
    body = `<div class="init-title">✗ ${esc(e.title)}</div>
      ${e.why ? `<div class="init-detail">${esc(e.why)}</div>` : ''}
      ${e.hint ? `<div class="init-hint"><b>${esc(t.initWhatToDo)}</b> ${esc(e.hint)}</div>` : ''}`;
  } else if (own && initState.report) {
    const r = initState.report;
    tone = r.failed.length ? 'is-error' : 'is-ok';
    const head = r.failed.length ? t.initPartial : (r.created.length ? t.initDone : t.initAlready);
    body = `<div class="init-title">${r.failed.length ? '✗' : '✓'} ${esc(head)}</div>${list(t.initCreated, r.created)}${list(t.initExisting, r.existing)}${list(t.initFailed, r.failed, 'is-fail')}`;
  }
  return `
    <div class="init-project-section" data-bind="init-project">
      <button class="btn btn-primary init-btn" data-action="init-project" title="${esc(t.initHint)}" ${initState.busy ? 'disabled' : ''}>
        ${icon('download', '', 14)} ${esc(initState.busy ? t.initBusy : t.initBtn)}
      </button>
      <div class="init-sub">${esc(t.initHint)}</div>
      ${body ? `<div class="init-report ${tone}" role="${tone === 'is-error' ? 'alert' : 'status'}">${body}
        <button class="btn btn-ghost btn-sm" data-action="init-dismiss">${esc(t.initClose)}</button></div>` : ''}
    </div>`;
}
function orderedSessions() {
  const idx = (s) => { const i = sessionOrder.indexOf(s.id); return i < 0 ? 1e9 : i; };
  return mockSessions.map((s, n) => [s, n]).sort((a, b) => idx(a[0]) - idx(b[0]) || a[1] - b[1]).map((x) => x[0]);
}

export function snapshotLayout() {
  const ids = orderedSessions().filter(isLiveSession).map((s) => s.id);
  return {
    v: 1, open: ids, order: ids, focus: activeSessionId,
    split: { on: isSplitMode, dir: splitDirection, session: splitSessionId, ratio: splitRatio },
    widths: { left: colWidths.left, right: colWidths.right }, files_open: isFilesOpen,
  };
}

/** Grava o layout com debounce (não bloqueia a UI; falhas são silenciosas). */
function persistLayout() {
  if (!layoutReady) return;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { putSettings({ terminal_layout: snapshotLayout() }).catch(() => {}); }, 600);
}

/** Aplica um layout salvo; só reabre sessões que ainda estão ativas no backend. */
export function applyLayout(L) {
  if (!L || typeof L !== 'object') return;
  const alive = new Set(mockSessions.filter(isLiveSession).map((s) => s.id));
  const ids = (Array.isArray(L.order) ? L.order : Array.isArray(L.open) ? L.open : []).filter((id) => alive.has(id));
  sessionOrder = ids;
  if (alive.has(L.focus)) activeSessionId = L.focus;
  const sp = L.split || {};
  if (sp.on && alive.has(sp.session) && alive.size > 1) {
    isSplitMode = true; splitSessionId = sp.session;
    splitDirection = sp.dir === 'horizontal' ? 'horizontal' : 'vertical';
  }
  if (typeof sp.ratio === 'number') splitRatio = Math.min(0.85, Math.max(0.15, sp.ratio));
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
    applyLayout(st && st.terminal_layout);
  } catch (e) { /* sem backend de settings: segue com o padrão */ }
  layoutRestoring = false;
  layoutReady = true;
  if (root.isConnected && currentState === 'loaded') refresh(root);
}

function sessionChips(sess) {
  const t = I18N.workspace;
  const out = [];
  if (sess.branch) out.push(`<span class="ws-chip ws-chip-branch" title="${esc(t.chipBranch)}: ${esc(sess.branch)}">${esc(sess.branch)}</span>`);
  if (sess.role) out.push(`<span class="ws-chip ws-chip-role" title="${esc(t.chipRole)}">${esc((t.roles && t.roles[sess.role]) || sess.role)}</span>`);
  if (sess.mcp && typeof sess.mcp === 'object') {
    const on = !!sess.mcp.enabled;
    out.push(`<span class="ws-chip ${on ? 'ws-chip-on' : 'ws-chip-off'}" title="${esc(t.chipMcp)}${sess.mcp.mode ? `: ${esc(sess.mcp.mode)}` : ''}">${esc(on ? t.mcpOn : t.mcpOff)}</span>`);
  }
  return out.join('');
}

function launcherOptions() {
  const t = I18N.workspace;
  return `
    <div class="launcher-opts" data-bind="launcher-opts">
      <label class="launcher-opt"><input type="checkbox" data-launch-opt="worktree" ${launchOpts.worktree ? 'checked' : ''} /> <span>${esc(t.launchWorktree)}</span></label>
      <label class="launcher-opt"><span>${esc(t.launchRole)}</span>
        <select class="select-control" data-launch-opt="role">
          <option value="">${esc(t.launchRoleNone)}</option>
          ${ROLES.map((r) => `<option value="${r}" ${launchOpts.role === r ? 'selected' : ''}>${esc(t.roles[r])}</option>`).join('')}
        </select></label>
      <label class="launcher-opt"><span>${esc(t.launchMcp)}</span>
        <select class="select-control" data-launch-opt="mcp">
          <option value="default" ${launchOpts.mcp === 'default' ? 'selected' : ''}>${esc(t.launchMcpDefault)}</option>
          <option value="on" ${launchOpts.mcp === 'on' ? 'selected' : ''}>${esc(t.launchMcpOn)}</option>
          <option value="off" ${launchOpts.mcp === 'off' ? 'selected' : ''}>${esc(t.launchMcpOff)}</option>
        </select></label>
    </div>`;
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

export function render() {
  const t = I18N.workspace;
  if (!mockProjects.some(p => p.id === activeProjectId) && mockProjects[0]) activeProjectId = mockProjects[0].id;
  if (!mockSessions.some(s => s.id === activeSessionId) && mockSessions[0]) activeSessionId = mockSessions[0].id;

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
        <p class="state-description">Falha ao inicializar sessões do subsistema local de terminais.</p>
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
            <div class="state-icon-wrap">${icon('terminal', '', 28)}</div>
            <h2 class="state-title">${t.emptyTerminalTitle}</h2>
            <p class="state-description">${t.emptyTerminalDesc}</p>
            <div class="u-387c0c">
              <button class="btn btn-primary" data-action="new-terminal">${icon('plus', '', 14)} Novo Terminal</button>
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

  const sessions = orderedSessions();
  const px = (n) => (typeof n === 'number' && Number.isFinite(n) ? `width:${Math.round(n)}px;min-width:${Math.round(n)}px;max-width:${Math.round(n)}px;` : '');
  const splitSess = (splitSessionId && sessions.find((x) => x.id === splitSessionId && x.id !== activeSessionId))
    || sessions.find((x) => x.id !== activeSessionId) || null;
  const slot = (ratio, inner) => `<div class="ws-split-slot" data-css="flex:${ratio.toFixed(4)} 1 0">${inner}</div>`;

  // Active Project & Sessions
  const activeProject = mockProjects.find(p => p.id === activeProjectId) || mockProjects[0];
  const activeSession = sessions.find(s => s.id === activeSessionId) || sessions[0];

  return `
    <div class="workspace-layout" data-bind="workspace-root">
      ${backendNotice}

      <!-- COLUNA ESQUERDA: Projetos & Sessões Ativas (~260px) -->
      <aside class="workspace-left-col" aria-label="Projetos registrados" data-css="${px(colWidths.left)}">
        <div class="pane-header">
          <span class="pane-title">${t.projectsTitle}</span>
          <button class="btn btn-ghost btn-sm" data-action="open-add-project" title="${t.addProject}" aria-label="${t.addProject}">
            ${icon('plus', '', 14)}
          </button>
        </div>

        ${initPanel(t, activeProjectId)}
        ${jevPanel(t)}

        <div class="projects-list-container" data-bind="projects-list" role="list">
          ${mockProjects.map(proj => {
            const isActive = proj.id === activeProjectId;
            const hasActiveSessions = proj.active_sessions > 0;
            return `
              <div class="project-item ${isActive ? 'is-active' : ''}" data-action="select-project" data-project-id="${proj.id}" role="listitem" tabindex="0">
                <div class="project-info">
                  <div class="project-name-row">
                    <span class="dot ${hasActiveSessions ? 'dot-success' : 'dot-neutral'}" title="${hasActiveSessions ? 'Sessão ativa' : 'Inativo'}"></span>
                    <span class="project-name">${proj.name}</span>
                  </div>
                  <span class="project-path">${proj.path}</span>
                </div>
                ${hasActiveSessions ? `<span class="badge-origin badge-origin-measured" title="${proj.active_sessions} terminais ativos">${proj.active_sessions}</span>` : ''}
              </div>
            `;
          }).join('')}
        </div>

        <!-- Sessões ativas agrupadas -->
        <div class="active-sessions-section">
          <div class="u-20d708">
            <span class="pane-title">${t.activeSessions}</span>
            <span class="section-count tabular">${mockSessions.length}</span>
          </div>
          ${sessions.map(sess => `
            <div class="session-mini-item u-265908" data-action="focus-session" data-session-id="${esc(sess.id)}">
              <div class="u-2d1dcb">
                <span class="dot dot-success"></span>
                <span class="u-bcfbd4">${esc(sess.title)}</span>
              </div>
              <span class="time-stamp tabular u-1ab1cd">${sess.startTime}</span>
            </div>
          `).join('')}
        </div>
      </aside>
      <div class="ws-resizer" data-resize="left" role="separator" aria-orientation="vertical" aria-label="${esc(t.resizeLeft)}" tabindex="0"></div>

      <!-- COLUNA CENTRAL: Canvas de Terminais -->
      <main class="workspace-center-col" aria-label="Terminal interativo">
        <!-- Barra de Abas de Terminal com moldura elegante e 3 pontinhos neutros -->
        <div class="terminal-tab-bar" role="tablist">
          <div class="terminal-dots" aria-hidden="true">
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
            <span class="terminal-dot"></span>
          </div>

          ${sessions.map(sess => {
            const isActive = sess.id === activeSessionId;
            return `
              <div class="terminal-tab ${isActive ? 'is-active' : ''}" role="tab" aria-selected="${isActive}" draggable="true" data-action="switch-tab" data-session-id="${esc(sess.id)}">
                ${icon(sess.profileId.includes('claude') || sess.profileId.includes('hermes') ? 'bot' : 'terminal', '', 13)}
                <span>${esc(sess.title)}</span>
                ${sessionChips(sess)}
                <span class="dot dot-success" title="Ativo"></span>
                <button class="terminal-tab-close" data-action="close-session" data-session-id="${esc(sess.id)}" title="Fechar terminal" aria-label="Fechar terminal">
                  ${icon('x', '', 12)}
                </button>
              </div>
            `;
          }).join('')}

          <!-- Botão + para novo terminal -->
          <button class="btn btn-ghost btn-sm u-3e9b1b" data-action="toggle-profile-menu" title="${t.newTerminal}" aria-label="${t.newTerminal}">
            ${icon('plus', '', 14)}
          </button>

          <!-- Controles de split e gavetas no lado direito da barra -->
          <div class="terminal-actions-bar">
            <button class="btn btn-ghost btn-icon" data-action="split-panel-vertical" title="${t.splitVertical}" aria-label="${t.splitVertical}">
              ${icon('splitV', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="split-panel-horizontal" title="${t.splitHorizontal}" aria-label="${t.splitHorizontal}">
              ${icon('splitH', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="toggle-context-drawer" title="Contexto do agente" aria-label="Contexto do agente">
              ${icon('database', '', 14)}
            </button>
            <button class="btn btn-ghost btn-icon" data-action="toggle-files-panel" title="Painel de arquivos" aria-label="Painel de arquivos">
              ${icon('sidebar', '', 14)}
            </button>
          </div>
        </div>

        <!-- Menu dropdown de perfis (Shell, PowerShell, Hermes, Claude Code, Codex, OpenCode) -->
        <div class="profile-menu ${isProfileMenuOpen ? 'is-open' : ''}" data-bind="profile-menu">
          <div class="u-0424af">
            ${esc(t.launcherTitle)}
          </div>
          ${launcherOptions()}
          ${mockProfiles.map(prof => `
            <div class="profile-menu-item ${!prof.available ? 'is-disabled' : ''}" data-action="launch-profile" data-profile-id="${prof.id}">
              <div class="profile-info">
                ${icon(prof.icon, '', 14)}
                <div>
                  <div class="u-02921b">${prof.name}</div>
                  <div class="u-f8775b">${prof.description}</div>
                </div>
              </div>
              ${!prof.available ? `<span class="profile-badge-unavailable">${t.profileUnavailable}</span>` : ''}
            </div>
          `).join('')}
        </div>

        <!-- Contêiner de painéis divididos / fluido -->
        <div class="terminal-panes-wrapper ${isSplitMode ? (splitDirection === 'vertical' ? 'split-vertical' : 'split-horizontal') : ''}">
          ${activeSession ? (isSplitMode && splitSess ? slot(splitRatio, renderTerminalFrame(activeSession)) : renderTerminalFrame(activeSession)) : `
            <div class="state-container" data-bind="terminal-empty">
              <div class="state-icon-wrap">${icon('terminal', '', 28)}</div>
              <h2 class="state-title">${t.emptyTerminalTitle}</h2>
              <p class="state-description">${esc(mockProjects.length ? t.emptyTerminalHint : t.emptyTerminalNoProject)}</p>
            </div>`}
          ${isSplitMode && activeSession && splitSess ? `
            <div class="terminal-split-divider ${splitDirection === 'horizontal' ? 'is-horizontal' : ''}" data-resize="split" role="separator" aria-label="${esc(t.resizeSplit)}"></div>
            ${slot(1 - splitRatio, renderTerminalFrame(splitSess, { isSplit: true }))}
          ` : ''}
        </div>
      </main>

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
            <input type="text" placeholder="${t.searchFiles}" data-action="filter-files" value="${searchFilter}" class="u-e3ec32" />
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

export function mount(root) {
  // Click actions handler
  const handleClick = (e) => {
    const fileItem = e.target.closest('.file-tree-item[data-file-path]');
    if (fileItem) { activateFile(root, fileItem); return; }
    const target = e.target.closest('[data-action]');
    if (!target) {
      if (isProfileMenuOpen && !e.target.closest('.profile-menu')) {
        isProfileMenuOpen = false;
        refresh(root);
      }
      return;
    }

    const action = target.getAttribute('data-action');

    switch (action) {
      case 'select-project': {
        const id = target.getAttribute('data-project-id');
        if (id) {
          activeProjectId = id;
          loadFiles(id).catch(() => {}).finally(() => refresh(root));
        }
        break;
      }
      case 'switch-tab': {
        const id = target.getAttribute('data-session-id');
        if (id) {
          activeSessionId = id;
          if (id === splitSessionId) splitSessionId = null;
          persistLayout();
          refresh(root);
        }
        break;
      }
      case 'close-session': {
        e.stopPropagation();
        const id = target.getAttribute('data-session-id');
        closeSession(id).then(() => {
          if (activeSessionId === id && mockSessions[0]) activeSessionId = mockSessions[0].id;
          if (splitSessionId === id) { splitSessionId = null; isSplitMode = false; }
          persistLayout();
          refresh(root);
        });
        break;
      }
      case 'toggle-profile-menu': {
        isProfileMenuOpen = !isProfileMenuOpen;
        refresh(root);
        break;
      }
      case 'launch-profile': {
        const profId = target.getAttribute('data-profile-id');
        const prof = mockProfiles.find(p => p.id === profId);
        if (prof && prof.available && mockProjects.length) {
          isProfileMenuOpen = false;
          const opts = {
            worktree: launchOpts.worktree, role: launchOpts.role || undefined,
            mcp: launchOpts.mcp === 'on' ? true : launchOpts.mcp === 'off' ? false : undefined,
          };
          launchSession(activeProjectId, prof.id, opts).then((sid) => {
            if (sid) { activeSessionId = sid; sessionOrder = orderedSessions().map((x) => x.id); }
            persistLayout();
            refresh(root);
          }).catch((err) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type: 'error', message: `${I18N.workspace.launchFail}: ${err.message || err}` } })));
        }
        break;
      }
      case 'split-panel-vertical': {
        isSplitMode = !isSplitMode;
        splitDirection = 'vertical';
        persistLayout();
        refresh(root);
        break;
      }
      case 'split-panel-horizontal': {
        isSplitMode = !isSplitMode;
        splitDirection = 'horizontal';
        persistLayout();
        refresh(root);
        break;
      }
      case 'toggle-files-panel': {
        isFilesOpen = !isFilesOpen;
        persistLayout();
        refresh(root);
        break;
      }
      case 'toggle-context-drawer': {
        isContextDrawerOpen = !isContextDrawerOpen;
        refresh(root);
        if (isContextDrawerOpen) loadContext(root);
        break;
      }
      case 'close-context-drawer': {
        isContextDrawerOpen = false;
        refresh(root);
        break;
      }
      case 'refresh-context': {
        loadContext(root);
        break;
      }
      case 'init-project': {
        if (initState.busy || !activeProjectId) break;
        initState = { busy: true, report: null, error: null, projectId: activeProjectId };
        refresh(root);
        const pid = activeProjectId;
        initializeProject(pid).then((rep) => { initState = { busy: false, report: rep, error: null, projectId: pid }; })
          .catch((err) => { initState = { busy: false, report: null, projectId: pid,
            error: { message: err.message || String(err), hint: err.hint || '' } }; })
          .finally(() => { loadFiles(pid).catch(() => {}).finally(() => refresh(root)); });
        break;
      }
      case 'jev-toggle': {
        jev.open = !jev.open; jev.test = null; jev.msg = null; jev.err = null; jev.draft = {}; jev.key = '';
        refresh(root);
        if (jev.open) jevLoad(root);
        break;
      }
      case 'jev-adv': { jev.adv = !jev.adv; refresh(root); break; }
      case 'jev-save': { jevRun(root, 'save'); break; }
      case 'jev-test': { jevRun(root, 'test'); break; }
      case 'init-dismiss': {
        initState = { busy: false, report: null, error: null, projectId: null };
        refresh(root);
        break;
      }
      case 'open-add-project': {
        window.dispatchEvent(new CustomEvent('anamnesia:modal:add-project'));
        break;
      }
      case 'retry-state': {
        currentState = 'loaded';
        refresh(root);
        break;
      }
      case 'new-terminal': {
        isProfileMenuOpen = true;
        refresh(root);
        break;
      }
    }
  };

  const handleInput = (e) => {
    if (e.target.matches && e.target.matches('[data-jev-key]')) { jev.key = e.target.value; return; }
    const jf = e.target.getAttribute && e.target.getAttribute('data-jev');
    if (jf && e.target.type !== 'checkbox') { jev.draft[jf] = e.target.value; return; }
    if (e.target.matches('[data-action="filter-files"]')) {
      searchFilter = e.target.value;
      updateFileTree(root);
    }
  };

  // Opções do lançador (worktree / papel / MCP): só estado, sem re-render (o menu continua aberto).
  const handleChange = (e) => {
    const jf = e.target.getAttribute && e.target.getAttribute('data-jev');
    if (jf) { jev.draft[jf] = e.target.type === 'checkbox' ? !!e.target.checked : e.target.value; return; }
    const k = e.target.getAttribute && e.target.getAttribute('data-launch-opt');
    if (!k) return;
    if (k === 'worktree') launchOpts.worktree = !!e.target.checked;
    else if (k === 'role') launchOpts.role = ROLES.includes(e.target.value) ? e.target.value : '';
    else if (k === 'mcp') launchOpts.mcp = ['on', 'off'].includes(e.target.value) ? e.target.value : 'default';
  };

  // Redimensionamento por arrasto: colunas esquerda/direita e divisão dos terminais.
  let drag = null;
  const onMove = (e) => {
    if (!drag) return;
    if (drag.kind === 'split') {
      const r = drag.wrap.getBoundingClientRect();
      const horiz = splitDirection === 'horizontal';
      const ratio = horiz ? (e.clientY - r.top) / r.height : (e.clientX - r.left) / r.width;
      splitRatio = Math.min(0.85, Math.max(0.15, ratio));
      const slots = drag.wrap.querySelectorAll('.ws-split-slot');
      if (slots[0]) slots[0].style.flex = `${splitRatio.toFixed(4)} 1 0`;
      if (slots[1]) slots[1].style.flex = `${(1 - splitRatio).toFixed(4)} 1 0`;
    } else {
      const dx = e.clientX - drag.x0;
      const w = clamp(drag.kind === 'left' ? drag.w0 + dx : drag.w0 - dx, LIMITS[drag.kind]);
      colWidths[drag.kind] = w;
      drag.el.style.width = drag.el.style.minWidth = drag.el.style.maxWidth = `${Math.round(w)}px`;
    }
  };
  const onUp = () => {
    if (!drag) return;
    drag = null;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
    document.body.classList.remove('ws-resizing');
    persistLayout();
  };
  const handleDown = (e) => {
    const h = e.target.closest && e.target.closest('[data-resize]');
    if (!h) return;
    const kind = h.getAttribute('data-resize');
    if (kind === 'split') drag = { kind, wrap: h.parentElement };
    else {
      const el = root.querySelector(kind === 'left' ? '.workspace-left-col' : '.workspace-right-col');
      if (!el) return;
      drag = { kind, el, x0: e.clientX, w0: el.getBoundingClientRect().width };
    }
    e.preventDefault();
    document.body.classList.add('ws-resizing');
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  };

  // Reordenar abas arrastando.
  let dragTabId = null;
  const onDragStart = (e) => {
    const tab = e.target.closest && e.target.closest('.terminal-tab');
    if (!tab) return;
    dragTabId = tab.getAttribute('data-session-id');
    if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragTabId || ''); }
  };
  const onDragOver = (e) => { if (dragTabId && e.target.closest && e.target.closest('.terminal-tab')) e.preventDefault(); };
  const onDrop = (e) => {
    const tab = e.target.closest && e.target.closest('.terminal-tab');
    if (!dragTabId || !tab) return;
    e.preventDefault();
    const over = tab.getAttribute('data-session-id');
    if (over && over !== dragTabId) {
      const ids = orderedSessions().map((x) => x.id).filter((id) => id !== dragTabId);
      ids.splice(Math.max(0, ids.indexOf(over)), 0, dragTabId);
      sessionOrder = ids;
      persistLayout();
      refresh(root);
    }
    dragTabId = null;
  };

  const handleTreeKey = (e) => {
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

  root.addEventListener('keydown', handleTreeKey);
  root.addEventListener('click', handleClick);
  root.addEventListener('input', handleInput);
  root.addEventListener('change', handleChange);
  root.addEventListener('pointerdown', handleDown);
  root.addEventListener('dragstart', onDragStart);
  root.addEventListener('dragover', onDragOver);
  root.addEventListener('drop', onDrop);

  root._workspaceCleanup = () => {
    root.removeEventListener('click', handleClick);
    root.removeEventListener('keydown', handleTreeKey);
    root.removeEventListener('input', handleInput);
    root.removeEventListener('change', handleChange);
    root.removeEventListener('pointerdown', handleDown);
    root.removeEventListener('dragstart', onDragStart);
    root.removeEventListener('dragover', onDragOver);
    root.removeEventListener('drop', onDrop);
    onUp();
    if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; if (layoutReady) putSettings({ terminal_layout: snapshotLayout() }).catch(() => {}); }
  };

  restoreLayout(root);
  jevLoad(root);
}

function refresh(root) {
  root.innerHTML = render();
}

export function unmount(root) {
  if (root && root._workspaceCleanup) {
    root._workspaceCleanup();
    delete root._workspaceCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (root) refresh(root);
}
