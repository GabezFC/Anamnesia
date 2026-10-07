// pages-workspace.js — Anamnesia Workspace (home page): project list + sessions (left), tabbed/split
// xterm terminals (centre), read-only file explorer (right), status bar (footer).
//
// Backend routes may not exist yet: every call is wrapped and a 404/offline becomes a friendly
// "backend ainda não disponível" state — this page must never throw into the router.
// Rule: every server-provided string reaches the DOM through esc() (or textContent).
import { esc } from './format.js';
import * as A from './anamnesia-api.js';
import * as L from './workspace-layout.js';
import { SessionTerminal } from './terminals.js';

const LS_LAYOUT = 'anamnesia.ws.layout.v1';
const LS_PROJECT = 'anamnesia.ws.project.v1';
const LS_PREFIX = 'anamnesia.ws.prefix.v1';
const LS_PROFILE = 'anamnesia.ws.profile.v1';

/** Prefix chords for app shortcuts inside a terminal. Everything else goes to the terminal untouched. */
export const PREFIXES = {
  'Ctrl+]': { key: ']' }, 'Ctrl+\\': { key: '\\' }, 'Ctrl+Space': { key: ' ' }, 'Ctrl+B': { key: 'b' },
};
const DEFAULT_PREFIX = 'Ctrl+]';

const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { /* quota / private mode */ } };

const pidOf = (p) => String(p.id ?? p.name ?? '');
const sidOf = (s) => String(s.id ?? s.session_id ?? '');
const sprojOf = (s) => String(s.project_id ?? s.project ?? '');
const shortId = (s) => String(s).replace(/^sess[-_]?/i, '').slice(0, 6);

/** Module state — rebuilt on every mount(). Holds NO secrets; only ids/names from the API. */
let W = null;
const fresh = () => ({
  root: null, projects: [], sessions: [], profiles: [], project: lsGet(LS_PROJECT) || '',
  layout: L.sanitize(safeParse(lsGet(LS_LAYOUT))), activeLeaf: null, terms: new Map(),
  projectsDown: false, sessionsDown: false, profilesDown: false,
  prefix: PREFIXES[lsGet(LS_PREFIX)] ? lsGet(LS_PREFIX) : DEFAULT_PREFIX,
  armed: false, armTimer: null, lastConsumed: 0,
  filePath: '', fileQ: '', files: [], filesState: 'idle', fileTimer: null,
  health: 'checking', cost: null, costState: 'unknown', costStop: null, costTimer: null,
  timers: [], disposed: false, onKeyDownCapture: null,
});
function safeParse(s) { try { return s ? JSON.parse(s) : null; } catch { return null; } }
const $ = (sel) => W?.root?.querySelector(sel);

export function renderWorkspace() {
  return `
  <div class="ws" id="ws">
    <aside class="ws-left" aria-label="Projetos e sessões" id="ws-left"></aside>
    <section class="ws-center" aria-label="Terminais">
      <div class="ws-toolbar" role="toolbar" aria-label="Painéis">
        <button type="button" id="ws-split-h" title="Dividir lado a lado (prefixo, h)">⬍ Dividir │</button>
        <button type="button" id="ws-split-v" title="Dividir empilhado (prefixo, v)">⬌ Dividir ─</button>
        <label class="ws-prefix-lbl" for="ws-prefix">Prefixo de atalhos
          <select id="ws-prefix">${Object.keys(PREFIXES).map((k) => `<option value="${esc(k)}">${esc(k)}</option>`).join('')}</select>
        </label>
        <span class="ws-hint" id="ws-hint">Dentro do terminal só o prefixo é interceptado: prefixo + h/v dividir · n/p aba · o painel · x fechar aba</span>
      </div>
      <div id="ws-panes" class="ws-panes"></div>
    </section>
    <aside class="ws-right" aria-label="Arquivos do projeto" id="ws-right"></aside>
    <footer class="ws-status" id="ws-status" aria-label="Barra de status"></footer>
    <div class="sr-only" id="ws-live" aria-live="polite" role="status"></div>
  </div>`;
}

/* ------------------------------------------------------------------ mount */
export function mountWorkspace(root) {
  if (W) unmountWorkspace();
  W = fresh();
  W.root = root;
  const sel = $('#ws-prefix');
  if (sel) {
    sel.value = W.prefix;
    sel.addEventListener('change', () => { W.prefix = sel.value; lsSet(LS_PREFIX, sel.value); announce(`Prefixo: ${sel.value}`); });
  }
  $('#ws-split-h').addEventListener('click', () => splitActive('h'));
  $('#ws-split-v').addEventListener('click', () => splitActive('v'));
  paintLeft(); paintRight(); paintStatus(); renderPanes();
  fitHeight();
  W.onResize = () => fitHeight();
  window.addEventListener('resize', W.onResize);
  refreshAll();
  W.timers.push(setInterval(() => refreshSessions(), 10000));
  W.timers.push(setInterval(() => refreshHealth(), 15000));
  W.timers.push(setInterval(() => refreshCost(), 60000));
  startCostStream();
}

export function unmountWorkspace() {
  if (!W) return;
  W.disposed = true;
  window.removeEventListener('resize', W.onResize);
  W.timers.forEach(clearInterval);
  clearTimeout(W.fileTimer); clearTimeout(W.armTimer); clearTimeout(W.costTimer);
  W.costStop?.();
  for (const t of W.terms.values()) t.dispose();      // closes sockets; sessions stay alive server-side
  W.terms.clear();
  W = null;
}

/** Palette actions that only make sense while the workspace is open. */
export function workspaceActions() {
  if (!W) return [];
  return [
    { id: 'ws-new', label: 'Workspace: novo terminal', run: () => newTerminal() },
    { id: 'ws-split-h', label: 'Workspace: dividir painel lado a lado', run: () => splitActive('h') },
    { id: 'ws-split-v', label: 'Workspace: dividir painel empilhado', run: () => splitActive('v') },
  ];
}

function announce(msg) { const l = $('#ws-live'); if (l) l.textContent = msg; }

/** Size the shell to the remaining viewport (the health banner above it has variable height). */
function fitHeight() {
  const el = $('#ws');
  if (!el || window.innerWidth <= 700) { if (el) el.style.height = ''; return; }
  const top = el.getBoundingClientRect().top + window.scrollY;
  el.style.height = `${Math.max(420, window.innerHeight - top - 16)}px`;
}

/* ------------------------------------------------------------------ data */
async function refreshAll() {
  await Promise.all([refreshProjects(), refreshProfiles(), refreshHealth(), refreshCost()]);
  await refreshSessions();
}

async function refreshProjects() {
  try { W.projects = await A.listProjects(); W.projectsDown = false; } catch (e) {
    if (!W) return;
    W.projects = []; W.projectsDown = A.isUnavailable(e) ? 'na' : (e.message || 'erro');
  }
  if (!W) return;
  if (!W.projects.some((p) => pidOf(p) === W.project)) W.project = W.projects[0] ? pidOf(W.projects[0]) : '';
  paintLeft(); loadFiles();
}

async function refreshProfiles() {
  try { W.profiles = await A.listProfiles(); W.profilesDown = false; } catch (e) {
    if (!W) return;
    W.profiles = []; W.profilesDown = A.isUnavailable(e) ? 'na' : (e.message || 'erro');
  }
  if (W) paintLeft();
}

async function refreshSessions() {
  if (!W) return;
  try {
    const list = await A.listSessions();
    if (!W) return;
    W.sessions = list; W.sessionsDown = false;
    const valid = list.map(sidOf);
    const pruned = L.prune(W.layout, valid);
    if (JSON.stringify(pruned) !== JSON.stringify(W.layout)) { W.layout = pruned; saveLayout(); renderPanes(); }
  } catch (e) {
    if (!W) return;
    W.sessionsDown = A.isUnavailable(e) ? 'na' : (e.message || 'erro');
  }
  paintLeft(); paintStatus();
}

async function refreshHealth() {
  try {
    const r = await fetch('/health', { cache: 'no-store' });
    W.health = r.ok ? ((await r.json()).status || 'ok') : 'erro';
  } catch { if (W) W.health = 'offline'; }
  if (W) paintStatus();
  fitHeight();
}

async function refreshCost() {
  try {
    const s = await A.costSummary('today');
    if (!W) return;
    W.cost = s; if (W.costState === 'unknown') W.costState = 'summary';
  } catch (e) { if (W) { W.cost = null; W.costState = A.isUnavailable(e) ? 'na' : 'err'; } }
  if (W) paintStatus();
}

function startCostStream() {
  W.costStop = A.openCostStream(() => {
    clearTimeout(W?.costTimer);
    if (W) W.costTimer = setTimeout(refreshCost, 1200);
  }, (st) => { if (W) { W.costState = st; paintStatus(); } });
}

const saveLayout = () => lsSet(LS_LAYOUT, JSON.stringify(W.layout));

/* ------------------------------------------------------------------ left column */
function sessionsOf(pid) { return W.sessions.filter((s) => sprojOf(s) === pid); }
const sessionLabel = (s) => `${s.profile || s.profile_id || 'terminal'} · ${shortId(sidOf(s))}`;

function paintLeft() {
  const box = $('#ws-left');
  if (!box) return;
  const keepAdd = box.querySelector('details.ws-add')?.open;
  let body;
  if (W.projectsDown === 'na') {
    body = `<div class="state state-compact"><div class="state-title">Backend do Workspace ainda não disponível</div>
      <p class="state-body">A rota <code>/api/projects</code> não respondeu (404/offline). O restante do painel continua funcionando.</p></div>`;
  } else if (W.projectsDown) {
    body = `<div class="state state-compact error"><div class="state-title">Falha ao listar projetos</div><code>${esc(W.projectsDown)}</code></div>`;
  } else if (!W.projects.length) {
    body = `<p class="ws-empty">Nenhum projeto ainda. Adicione uma pasta abaixo.</p>`;
  } else {
    body = `<ul class="ws-projects">${W.projects.map(projectItem).join('')}</ul>`;
  }
  const cur = W.projects.find((p) => pidOf(p) === W.project);
  const profileOpts = W.profiles.map((p) => {
    const id = String(p.id ?? p.name ?? '');
    const off = p.available === false;
    return `<option value="${esc(id)}"${off ? ' disabled' : ''}>${esc(p.name || p.label || id)}${off ? ' (indisponível)' : ''}</option>`;
  }).join('');
  const profileNote = W.profilesDown === 'na' ? 'perfis indisponíveis (backend ainda não disponível)'
    : W.profilesDown ? `perfis: ${W.profilesDown}` : (W.profiles.length ? '' : 'nenhum perfil cadastrado');
  box.innerHTML = `
    <h2 class="ws-h">Projetos</h2>
    ${body}
    <details class="ws-add"${keepAdd ? ' open' : ''}><summary>+ Adicionar projeto</summary>
      <form id="ws-add-form" autocomplete="off">
        <label for="ws-add-name">Nome</label><input id="ws-add-name" required maxlength="80">
        <label for="ws-add-path">Pasta (caminho absoluto)</label><input id="ws-add-path" required>
        <button type="submit" class="primary">Adicionar</button>
      </form>
    </details>
    <div class="ws-newterm">
      <label for="ws-profile">Perfil do terminal</label>
      <select id="ws-profile"${W.profiles.length ? '' : ' disabled'}>${profileOpts}</select>
      <button type="button" id="ws-new" class="primary"${cur && W.profiles.length ? '' : ' disabled'}>+ Terminal</button>
      ${profileNote ? `<p class="ws-note">${esc(profileNote)}</p>` : ''}
    </div>
    <div id="ws-msg" class="ws-msg" role="status" aria-live="polite"></div>`;
  const ps = box.querySelector('#ws-profile');
  const remembered = lsGet(LS_PROFILE);
  if (ps && remembered && W.profiles.some((p) => String(p.id ?? p.name) === remembered && p.available !== false)) ps.value = remembered;
  else if (ps) { const first = W.profiles.find((p) => p.available !== false); if (first) ps.value = String(first.id ?? first.name); }
  ps?.addEventListener('change', () => lsSet(LS_PROFILE, ps.value));
  box.querySelector('#ws-new')?.addEventListener('click', () => newTerminal());
  box.querySelector('#ws-add-form').addEventListener('submit', onAddProject);
  box.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => {
    W.project = b.dataset.pick; lsSet(LS_PROJECT, W.project); W.filePath = ''; W.fileQ = '';
    paintLeft(); loadFiles(); box.querySelector(`[data-pick="${CSS.escape(W.project)}"]`)?.focus();
  }));
  box.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click', () => onRemoveProject(b.dataset.rm)));
  box.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => openSession(b.dataset.open)));
  box.querySelectorAll('[data-kill]').forEach((b) => b.addEventListener('click', () => onKillSession(b.dataset.kill)));
}

function projectItem(p) {
  const id = pidOf(p);
  const on = id === W.project;
  const sess = sessionsOf(id);
  return `<li class="ws-proj${on ? ' on' : ''}">
    <div class="ws-proj-row">
      <button type="button" class="ws-proj-pick" data-pick="${esc(id)}"${on ? ' aria-current="true"' : ''}
        title="${esc(p.path || '')}">${esc(p.name || id)}</button>
      <button type="button" class="ws-icon" data-rm="${esc(id)}" aria-label="Remover projeto ${esc(p.name || id)}">🗑</button>
    </div>
    ${sess.length ? `<ul class="ws-sess" aria-label="Sessões de ${esc(p.name || id)}">${sess.map((s) => {
    const sid = sidOf(s);
    const open = L.leafOfSession(W.layout, sid);
    return `<li><button type="button" class="ws-sess-open" data-open="${esc(sid)}"
        aria-label="Abrir sessão ${esc(sessionLabel(s))}${open ? ' (já aberta)' : ''}">${open ? '▣' : '▢'} ${esc(sessionLabel(s))}</button>
        <button type="button" class="ws-icon" data-kill="${esc(sid)}" aria-label="Encerrar sessão ${esc(sessionLabel(s))}">✕</button></li>`;
  }).join('')}</ul>` : ''}
  </li>`;
}

function msg(text, tone = 'info') {
  const m = $('#ws-msg');
  if (m) m.innerHTML = text ? `<span class="ws-msg-${esc(tone)}">${esc(text)}</span>` : '';
}

async function onAddProject(ev) {
  ev.preventDefault();
  const name = $('#ws-add-name').value.trim();
  const path = $('#ws-add-path').value.trim();
  if (!name || !path) return;
  try {
    const p = await A.addProject(name, path);
    if (p && pidOf(p)) { W.project = pidOf(p); lsSet(LS_PROJECT, W.project); }
    await refreshProjects();
    msg(`Projeto “${name}” adicionado.`, 'ok');
  } catch (e) {
    msg(A.isUnavailable(e) ? 'Backend do Workspace ainda não disponível.' : `Não foi possível adicionar: ${e.message}`, 'err');
  }
}

async function onRemoveProject(id) {
  const p = W.projects.find((x) => pidOf(x) === id);
  if (!window.confirm(`Remover o projeto “${p?.name || id}” da lista? Os arquivos não são apagados.`)) return;
  try { await A.removeProject(id); await refreshProjects(); await refreshSessions(); msg('Projeto removido.', 'ok'); } catch (e) {
    msg(A.isUnavailable(e) ? 'Backend do Workspace ainda não disponível.' : `Não foi possível remover: ${e.message}`, 'err');
  }
}

async function newTerminal(leafId) {
  if (!W) return;
  const ps = $('#ws-profile');
  if (!W.project || !ps || !ps.value) { msg('Escolha um projeto e um perfil.', 'warn'); return; }
  const btn = $('#ws-new'); if (btn) btn.disabled = true;
  try {
    const r = await A.createSession(W.project, ps.value);
    const sid = String(r?.session_id ?? r?.id ?? '');
    await refreshSessions();
    if (sid) openSession(sid, leafId);
    msg('Terminal criado.', 'ok');
  } catch (e) {
    msg(A.isUnavailable(e) ? 'Backend de sessões ainda não disponível.' : `Não foi possível criar o terminal: ${e.message}`, 'err');
  } finally { const b = $('#ws-new'); if (b) b.disabled = false; }
}

async function onKillSession(sid) {
  if (!window.confirm('Encerrar esta sessão? O processo do terminal será finalizado.')) return;
  try {
    await A.deleteSession(sid);
    closeTabFor(sid);
    await refreshSessions();
    msg('Sessão encerrada.', 'ok');
  } catch (e) { msg(`Não foi possível encerrar: ${e.message}`, 'err'); }
}

/* ------------------------------------------------------------------ panes */
function ensureTerm(sid) {
  let t = W.terms.get(sid);
  if (!t) {
    t = new SessionTerminal(sid, { onState: onTermState, interceptKey });
    W.terms.set(sid, t);
    t.start();
  }
  return t;
}

function openSession(sid, leafId) {
  W.layout = L.addTab(W.layout, leafId || W.activeLeaf || L.leaves(W.layout)[0].id, sid);
  W.activeLeaf = L.leafOfSession(W.layout, sid)?.id || W.activeLeaf;
  saveLayout(); renderPanes(true); paintLeft();
}

function closeTabFor(sid) {
  W.layout = L.closeTab(W.layout, sid);
  const t = W.terms.get(sid);
  if (t) { t.dispose(); W.terms.delete(sid); }
  saveLayout(); renderPanes(); paintLeft();
}

function splitActive(dir) {
  const leaf = L.findNode(W.layout, W.activeLeaf) ? W.activeLeaf : L.leaves(W.layout)[0].id;
  const r = L.splitLeaf(W.layout, leaf, dir);
  W.layout = r.tree; W.activeLeaf = r.newLeafId || leaf;
  saveLayout(); renderPanes();
  announce(dir === 'h' ? 'Painel dividido lado a lado' : 'Painel dividido em pilha');
}

const STATE_TXT = { connecting: 'conectando', live: 'ao vivo', reconnecting: 'reconectando', ended: 'encerrada', error: 'erro' };

function onTermState(state, t) {
  W?.root?.querySelectorAll(`[data-dot="${CSS.escape(t.sid)}"]`).forEach((d) => {
    d.className = `ws-dot ws-dot-${state}`;
    d.title = STATE_TXT[state] || state;
  });
  const tab = W?.root?.querySelector(`[data-sid="${CSS.escape(t.sid)}"] .ws-tab-state`);
  if (tab) tab.textContent = STATE_TXT[state] || state;
  if (state === 'ended' || state === 'reconnecting') announce(`Terminal ${shortId(t.sid)}: ${STATE_TXT[state]}`);
  paintStatus();
}

function paneHtml(node) {
  if (node.k === 'leaf') {
    const tabs = node.tabs.map((sid) => {
      const s = W.sessions.find((x) => sidOf(x) === sid);
      const on = sid === node.active;
      const label = s ? sessionLabel(s) : `sessão ${shortId(sid)}`;
      return `<div class="ws-tab${on ? ' on' : ''}" role="presentation">
        <button type="button" role="tab" id="tab-${esc(sid)}" data-sid="${esc(sid)}" data-leaf="${esc(node.id)}"
          aria-selected="${on}" aria-controls="host-${esc(node.id)}" tabindex="${on ? 0 : -1}">
          <span class="ws-dot ws-dot-${esc(W.terms.get(sid)?.state || 'connecting')}" data-dot="${esc(sid)}" aria-hidden="true"></span>
          ${esc(label)}<span class="ws-tab-state sr-only">${esc(STATE_TXT[W.terms.get(sid)?.state] || '')}</span></button>
        <button type="button" class="ws-tab-x" data-close="${esc(sid)}" aria-label="Fechar aba ${esc(label)} (a sessão continua ativa)">×</button>
      </div>`;
    }).join('');
    return `<div class="ws-leaf${node.id === W.activeLeaf ? ' active' : ''}" data-leafbox="${esc(node.id)}">
      <div class="ws-tabs" role="tablist" aria-label="Abas do painel ${esc(node.id)}">${tabs}</div>
      <div class="ws-host" id="host-${esc(node.id)}" role="tabpanel" data-host="${esc(node.id)}">
        ${node.tabs.length ? '' : `<div class="ws-empty-pane"><p>Painel vazio.</p>
          <button type="button" data-newhere="${esc(node.id)}">+ Terminal neste painel</button></div>`}
      </div></div>`;
  }
  const vertical = node.dir === 'h';          // side by side → the separator is a vertical bar
  return `<div class="ws-split ws-split-${esc(node.dir)}" data-splitbox="${esc(node.id)}">
    <div class="ws-cell" data-cell="a">${paneHtml(node.a)}</div>
    <div class="ws-sep" role="separator" tabindex="0" data-split="${esc(node.id)}"
      aria-orientation="${vertical ? 'vertical' : 'horizontal'}" aria-label="Redimensionar divisão"
      aria-valuemin="15" aria-valuemax="85" aria-valuenow="${Math.round(node.ratio * 100)}"></div>
    <div class="ws-cell" data-cell="b">${paneHtml(node.b)}</div>
  </div>`;
}

function renderPanes(focusActive = false) {
  const box = $('#ws-panes');
  if (!box) return;
  if (!L.findNode(W.layout, W.activeLeaf)) W.activeLeaf = L.leaves(W.layout)[0].id;
  // Park live terminals outside the tree so innerHTML replacement does not destroy them.
  const park = document.createDocumentFragment();
  for (const t of W.terms.values()) park.appendChild(t.el);
  box.innerHTML = paneHtml(W.layout);
  for (const leaf of L.leaves(W.layout)) {
    const host = box.querySelector(`[data-host="${CSS.escape(leaf.id)}"]`);
    if (!host || !leaf.active) continue;
    host.appendChild(ensureTerm(leaf.active).el);
  }
  box.querySelectorAll('.ws-split').forEach((sp) => {
    const n = L.findNode(W.layout, sp.dataset.splitbox);
    sp.children[0].style.flex = `0 0 calc(${(n.ratio * 100).toFixed(2)}% - 3px)`;
    sp.children[2].style.flex = '1 1 0';
  });
  bindPanes(box);
  requestAnimationFrame(() => {
    for (const leaf of L.leaves(W.layout)) W.terms.get(leaf.active)?.refit();
    if (focusActive) W.terms.get(L.findNode(W.layout, W.activeLeaf)?.active)?.focus();
  });
}

function bindPanes(box) {
  box.querySelectorAll('[data-leafbox]').forEach((el) => {
    el.addEventListener('pointerdown', () => {
      if (W.activeLeaf !== el.dataset.leafbox) {
        W.activeLeaf = el.dataset.leafbox;
        box.querySelectorAll('.ws-leaf').forEach((x) => x.classList.toggle('active', x === el));
      }
    }, true);
  });
  box.querySelectorAll('[role=tab]').forEach((b) => {
    const activate = (focus) => {
      W.layout = L.setActive(W.layout, b.dataset.leaf, b.dataset.sid);
      W.activeLeaf = b.dataset.leaf; saveLayout(); renderPanes(focus);
    };
    b.addEventListener('click', () => activate(true));
    b.addEventListener('keydown', (ev) => {
      const leaf = L.findNode(W.layout, b.dataset.leaf);
      const keys = { ArrowRight: 1, ArrowLeft: -1 };
      if (ev.key in keys || ev.key === 'Home' || ev.key === 'End') {
        ev.preventDefault();
        const next = ev.key === 'Home' ? leaf.tabs[0] : ev.key === 'End' ? leaf.tabs.at(-1) : L.cycle(leaf.tabs, b.dataset.sid, keys[ev.key]);
        W.layout = L.setActive(W.layout, leaf.id, next); W.activeLeaf = leaf.id; saveLayout(); renderPanes(false);
        W.root.querySelector(`[role=tab][data-sid="${CSS.escape(next)}"]`)?.focus();
      } else if (ev.key === 'Delete') { ev.preventDefault(); closeTabFor(b.dataset.sid); }
      else if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); activate(true); }
    });
  });
  box.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => closeTabFor(b.dataset.close)));
  box.querySelectorAll('[data-newhere]').forEach((b) => b.addEventListener('click', () => newTerminal(b.dataset.newhere)));
  box.querySelectorAll('.ws-sep').forEach(bindSeparator);
}

function bindSeparator(sep) {
  const id = sep.dataset.split;
  const node = () => L.findNode(W.layout, id);
  const apply = (ratio, commit) => {
    const r = L.clampRatio(ratio);
    const cell = sep.parentElement.children[0];
    cell.style.flex = `0 0 calc(${(r * 100).toFixed(2)}% - 3px)`;
    sep.setAttribute('aria-valuenow', String(Math.round(r * 100)));
    if (commit) { W.layout = L.setRatio(W.layout, id, r); saveLayout(); }
  };
  sep.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    sep.setPointerCapture(ev.pointerId);
    const rect = sep.parentElement.getBoundingClientRect();
    const horiz = node().dir === 'h';
    const calc = (e) => (horiz ? (e.clientX - rect.left) / rect.width : (e.clientY - rect.top) / rect.height);
    const move = (e) => apply(calc(e), false);
    const up = (e) => {
      sep.removeEventListener('pointermove', move); sep.removeEventListener('pointerup', up);
      apply(calc(e), true);
    };
    sep.addEventListener('pointermove', move); sep.addEventListener('pointerup', up);
  });
  sep.addEventListener('keydown', (ev) => {
    const n = node(); const horiz = n.dir === 'h';
    const dec = horiz ? 'ArrowLeft' : 'ArrowUp'; const inc = horiz ? 'ArrowRight' : 'ArrowDown';
    if (ev.key !== dec && ev.key !== inc && ev.key !== 'Home' && ev.key !== 'End') return;
    ev.preventDefault();
    const cur = n.ratio;
    apply(ev.key === 'Home' ? L.MIN_RATIO : ev.key === 'End' ? L.MAX_RATIO : cur + (ev.key === inc ? 0.05 : -0.05), true);
    announce(`Divisão em ${sep.getAttribute('aria-valuenow')}%`);
  });
}

/* ------------------------------------------------------------------ keyboard prefix (inside xterm) */
function disarm() {
  W.armed = false; clearTimeout(W.armTimer);
  const h = $('#ws-hint'); if (h) h.classList.remove('armed');
}

/** Called by xterm for every key. Returns true when the key was consumed by the app (not sent to the PTY). */
function interceptKey(ev, phase) {
  if (!W) return false;
  if (phase === 'peek') return Date.now() - W.lastConsumed < 400;   // keypress/keyup siblings of a consumed key
  const p = PREFIXES[W.prefix] || PREFIXES[DEFAULT_PREFIX];
  const isPrefix = ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key === p.key;
  const consume = () => { W.lastConsumed = Date.now(); return true; };
  if (!W.armed) {
    if (!isPrefix) return false;
    W.armed = true;
    $('#ws-hint')?.classList.add('armed');
    announce('Prefixo ativo: h v n p o x');
    W.armTimer = setTimeout(() => { if (W) disarm(); }, 2500);
    return consume();
  }
  if (['Shift', 'Control', 'Alt', 'Meta'].includes(ev.key)) return consume();
  disarm();
  const leaf = L.findNode(W.layout, W.activeLeaf);
  switch (ev.key) {
    case 'h': splitActive('h'); break;
    case 'v': splitActive('v'); break;
    case 'n': case 'p': {
      if (!leaf?.tabs.length) break;
      const next = L.cycle(leaf.tabs, leaf.active, ev.key === 'n' ? 1 : -1);
      W.layout = L.setActive(W.layout, leaf.id, next); saveLayout(); renderPanes(true); break;
    }
    case 'o': {
      const ids = L.leaves(W.layout).map((l) => l.id);
      W.activeLeaf = L.cycle(ids, W.activeLeaf, 1); renderPanes(true); break;
    }
    case 'x': if (leaf?.active) closeTabFor(leaf.active); break;
    default: break;                          // Esc or any other key just cancels the prefix
  }
  return consume();
}

/* ------------------------------------------------------------------ right column: files */
function paintRight() {
  const box = $('#ws-right');
  if (!box) return;
  box.innerHTML = `
    <h2 class="ws-h">Arquivos</h2>
    <label class="sr-only" for="ws-fq">Buscar arquivo por nome</label>
    <input id="ws-fq" type="search" placeholder="Buscar por nome…" autocomplete="off">
    <nav class="ws-crumbs" id="ws-crumbs" aria-label="Caminho"></nav>
    <div id="ws-files" class="ws-files" aria-live="polite"></div>`;
  $('#ws-fq').addEventListener('input', (ev) => {
    W.fileQ = ev.target.value.trim();
    clearTimeout(W.fileTimer);
    W.fileTimer = setTimeout(loadFiles, 250);
  });
}

async function loadFiles() {
  const list = $('#ws-files');
  if (!list) return;
  const crumbs = $('#ws-crumbs');
  if (!W.project) { list.innerHTML = '<p class="ws-empty">Selecione um projeto.</p>'; crumbs.innerHTML = ''; return; }
  list.innerHTML = '<p class="ws-empty">Carregando…</p>';
  const mine = W.project; const myq = W.fileQ; const myp = W.filePath;
  try {
    const files = await A.listFiles(mine, myp, myq);
    if (!W || mine !== W.project || myq !== W.fileQ || myp !== W.filePath) return;   // stale response
    W.files = files; W.filesState = 'ok';
  } catch (e) {
    if (!W) return;
    W.files = []; W.filesState = A.isUnavailable(e) ? 'na' : (e.message || 'erro');
  }
  const parts = W.filePath.split('/').filter(Boolean);
  crumbs.innerHTML = `<button type="button" data-cd="">raiz</button>${parts.map((p, i) =>
    ` / <button type="button" data-cd="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</button>`).join('')}`;
  crumbs.querySelectorAll('[data-cd]').forEach((b) => b.addEventListener('click', () => { W.filePath = b.dataset.cd; loadFiles(); }));
  if (W.filesState === 'na') {
    list.innerHTML = '<div class="state state-compact"><div class="state-title">Explorador indisponível</div><p class="state-body">Backend do Workspace ainda não disponível.</p></div>';
    return;
  }
  if (W.filesState !== 'ok') { list.innerHTML = `<p class="ws-msg-err">${esc(W.filesState)}</p>`; return; }
  if (!W.files.length) { list.innerHTML = `<p class="ws-empty">${W.fileQ ? 'Nada encontrado.' : 'Pasta vazia.'}</p>`; return; }
  list.innerHTML = `<ul>${W.files.map((f) => {
    const dir = f.type === 'dir' || f.type === 'directory' || f.is_dir === true;
    const path = String(f.path ?? f.name ?? '');
    return dir
      ? `<li><button type="button" class="ws-file dir" data-dir="${esc(path)}">📁 ${esc(f.name || path)}</button></li>`
      : `<li><span class="ws-file" title="${esc(path)}">📄 ${esc(f.name || path)}</span></li>`;
  }).join('')}</ul>`;
  list.querySelectorAll('[data-dir]').forEach((b) => b.addEventListener('click', () => {
    W.filePath = b.dataset.dir; W.fileQ = ''; const q = $('#ws-fq'); if (q) q.value = ''; loadFiles();
  }));
}

/* ------------------------------------------------------------------ status bar */
function costText() {
  const c = W.cost?.cost_usd;
  if (W.costState === 'na') return 'custo MG: indisponível (backend ainda não disponível)';
  if (!c || typeof c.value !== 'number') return 'custo MG hoje: sem medição ainda';
  return `custo MG hoje: ${A.fmtUsd(c.value)} (${A.originLabel(c.origin)})`;
}

function paintStatus() {
  const box = $('#ws-status');
  if (!box) return;
  const live = [...W.terms.values()].filter((t) => t.state === 'live').length;
  const hcls = W.health === 'ok' ? 'ok' : W.health === 'checking' ? 'info' : 'err';
  const stream = { live: 'ao vivo', offline: 'sem stream', reconnecting: 'reconectando', error: 'sem stream' }[W.costState];
  box.innerHTML = `
    <span class="pill ${hcls}"><span class="dot"></span>servidor: ${esc(W.health)}</span>
    <span aria-live="polite">sessões: <b>${W.sessions.length}</b> · abertas: <b>${W.terms.size}</b> · conectadas: <b>${live}</b></span>
    <span aria-live="polite">${esc(costText())}</span>
    ${stream ? `<span class="ws-stream">${esc(stream)}</span>` : ''}`;
}
