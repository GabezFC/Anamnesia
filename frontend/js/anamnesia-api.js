// anamnesia-api.js — REST/WS/SSE client for the Anamnesia routes (/api/*). Each function maps 1:1 to
// a route in anamnesia-modelo-de-dados-e-apis.md. These routes are being built by the backend in
// parallel, so EVERY caller must treat `isUnavailable(err)` as a normal, friendly state.
//
// Secrets: setSecret() sends the key to the server once and never keeps, logs or returns it.
import { ApiError, getLocalToken } from './api.js';

/** True when the backend route is simply not there (yet) or the server is unreachable. */
export const isUnavailable = (e) =>
  e instanceof ApiError && [0, 404, 405, 501, 502, 503].includes(e.status);

async function errorFrom(r, path) {
  let msg = null;
  let hint = null;
  let code = null;
  try {
    const j = await r.json();
    if (j && j.error && typeof j.error === 'object') { msg = j.error.message; hint = j.error.hint; code = j.error.code; }
    else if (typeof j?.detail === 'string') msg = j.detail;
    else if (j?.detail) msg = JSON.stringify(j.detail);
  } catch { /* not JSON */ }
  const err = new ApiError(r.status, r.statusText, path, msg);
  err.hint = hint || null;
  err.code = code || null;
  return err;
}

/** fetch + JSON with the local write token attached when obtainable (it is loopback-only). */
export async function call(method, path, body) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  try { headers['X-MG-Token'] = await getLocalToken(); } catch { /* reads work without it on loopback */ }
  let r;
  try {
    r = await fetch(path, {
      method, headers, cache: 'no-store', body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, 'network error', path, e && e.message ? e.message : 'fetch falhou');
  }
  if (!r.ok) throw await errorFrom(r, path);
  if (r.status === 204) return null;
  try { return await r.json(); } catch { return null; }
}

/** Accept a bare array or an envelope ({items|projects|sessions|…:[…]}). */
export function asList(x, ...keys) {
  if (Array.isArray(x)) return x;
  if (x && typeof x === 'object') {
    for (const k of ['items', ...keys, 'entries', 'results']) if (Array.isArray(x[k])) return x[k];
  }
  return [];
}

/* ---- workspace ---------------------------------------------------------- */
export const listProjects = () => call('GET', '/api/projects').then((x) => asList(x, 'projects'));
export const addProject = (name, path) => call('POST', '/api/projects', { name, path });
export const initializeProject = (id, dryRun = false) => call('POST', `/api/projects/${encodeURIComponent(id)}/initialize`, { dry_run: dryRun });
/** Desvincula o projeto (nunca apaga a pasta). `purgeIndex` = também apaga o índice do Workspace deste projeto. */
export const removeProject = (id, purgeIndex = false) =>
  call('DELETE', `/api/projects/${encodeURIComponent(id)}${purgeIndex ? '?purge_index=true' : ''}`);
/** Raízes autorizadas host -> contêiner (ANAMNESIA_PATH_MAP). */
export const listWorkspaceRoots = () => call('GET', '/api/workspace/roots');
export const listFiles = (projectId, path = '', q = '') => {
  const p = new URLSearchParams();
  if (path) p.set('path', path);
  if (q) p.set('q', q);
  return call('GET', `/api/projects/${encodeURIComponent(projectId)}/files?${p.toString()}`)
    .then((x) => asList(x, 'files', 'entries'));
};
export const getFileContent = (projectId, path) =>
  call('GET', `/api/projects/${encodeURIComponent(projectId)}/file?path=${encodeURIComponent(path)}`);

export const listConnections = () => call('GET', '/api/connections').then((x) => asList(x, 'connections'));
export const testConnection = (id) => call('POST', `/api/connections/${encodeURIComponent(id)}/test`, {});
export const getSnippet = (id) => call('GET', `/api/connections/${encodeURIComponent(id)}/snippet`);
/** Writes the key; the response is ignored on purpose (it must never carry the secret anyway). */
export const setSecret = (id, envKey, value) =>
  call('PUT', `/api/connections/${encodeURIComponent(id)}/secret`, { env_key: envKey, value }).then(() => null);
export const removeSecret = (id, envKey) =>
  call('DELETE', `/api/connections/${encodeURIComponent(id)}/secret`, { env_key: envKey });

/* ---- orchestration ------------------------------------------------------- */
export const listPresets = () => call('GET', '/api/orchestration/presets').then((x) => asList(x, 'presets'));
export const listOrchRuns = () => call('GET', '/api/orchestration/runs').then((x) => asList(x, 'runs'));

/* ---- costs --------------------------------------------------------------- */
export const costSummary = (range = 'today', project = '') =>
  call('GET', `/api/costs/summary?range=${encodeURIComponent(range)}${project ? `&project=${encodeURIComponent(project)}` : ''}`);
export const costCalls = ({ cursor, limit = 25, project } = {}) => {
  const p = new URLSearchParams({ limit: String(limit) });
  if (cursor) p.set('cursor', cursor);
  if (project) p.set('project', project);
  return call('GET', `/api/costs/calls?${p.toString()}`);
};
export const costCall = (runId) => call('GET', `/api/costs/calls/${encodeURIComponent(runId)}`);
export const putBudget = (period, ceilingUsd) => call('PUT', '/api/costs/budget', { period, ceiling_usd: ceilingUsd });
export const costCsvUrl = (range = 'all', project = '') =>
  `/api/costs/export.csv?range=${encodeURIComponent(range)}${project ? `&project=${encodeURIComponent(project)}` : ''}`;

/** SSE of new cost-ledger calls. Returns a stop() function. Reconnects with backoff; never throws. */
export function openCostStream(onCall, onState) {
  let es = null; let stopped = false; let delay = 2000; let timer = null; let fails = 0;
  const open = () => {
    if (stopped || typeof EventSource === 'undefined') return;
    try { es = new EventSource('/api/costs/stream'); } catch { onState?.('error'); return; }
    es.onopen = () => { delay = 2000; fails = 0; onState?.('live'); };
    es.addEventListener('call', (ev) => { try { onCall(JSON.parse(ev.data)); } catch { /* malformed frame */ } });
    es.addEventListener('end', () => { es?.close(); onState?.('reconnecting'); timer = setTimeout(open, 500); });
    es.onerror = () => {
      es?.close(); onState?.('offline');
      fails += 1;
      if (fails >= 5) return;            // route is not there (or server down): stop hammering it
      timer = setTimeout(open, delay); delay = Math.min(delay * 2, 30000);
    };
  };
  open();
  return () => { stopped = true; clearTimeout(timer); es?.close(); };
}

/* ---- shared labelled-value helpers -------------------------------------- */
export const ORIGIN_LABEL = { measured: 'medido', estimated: 'estimado', unavailable: 'indisponível' };
export const originLabel = (o) => ORIGIN_LABEL[o] || 'indisponível';
export const lvValue = (lv) => (lv && typeof lv === 'object' && typeof lv.value === 'number' ? lv.value : null);
export const lvOrigin = (lv) => (lv && typeof lv === 'object' ? lv.origin || 'unavailable' : 'unavailable');
export const fmtUsd = (v) => {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—';
  if (v === 0) return 'US$ 0';
  return `US$ ${v < 0.01 ? v.toFixed(6).replace(/0+$/, '').replace(/\.$/, '') : v.toFixed(4)}`;
};

// ---- costs ----
const _q = (o) => { const p = new URLSearchParams(); for (const [k, v] of Object.entries(o)) if (v != null && v !== '') p.set(k, String(v)); return p.toString(); };
export const costCallsRange = ({ range = 'today', limit = 50, cursor } = {}) =>
  call('GET', `/api/costs/calls?${_q({ range, limit, cursor })}`);
export const costHourly = (range = 'today') => call('GET', `/api/costs/hourly?${_q({ range })}`);
export const costBudget = () => call('GET', '/api/costs/budget');
export const putCostBudget = ({ daily_usd, monthly_usd, alert_pct } = {}) => {
  const body = {};
  if (daily_usd !== undefined) body.daily_usd = daily_usd;
  if (monthly_usd !== undefined) body.monthly_usd = monthly_usd;
  if (alert_pct !== undefined) body.alert_pct = alert_pct;
  return call('PUT', '/api/costs/budget', body);
};
export const costByRole = (range = 'today') => call('GET', `/api/costs/by-role?${_q({ range })}`);

// ---- workspace/memory ----
export const getSettings = () => call('GET', '/api/settings');
export const putSettings = (patch) => call('PUT', '/api/settings', patch);
export const lastSearch = () => call('GET', '/api/memory/last-search');
export const searchPreview = ({ q, maxResults = 8, scope = '', pipeline = '' } = {}) => {
  const p = new URLSearchParams({ q: String(q ?? ''), max_results: String(maxResults) });
  if (scope) p.set('scope', scope);
  if (pipeline) p.set('pipeline', pipeline); // ANA-208: baseline|graphify (gratuitos, nunca gravam run)
  return call('GET', `/api/memory/search-preview?${p.toString()}`);
};
/** Sessão com opções: worktree (bool|id), subagent_role (orchestrator|researcher|implementer|reviewer), mcp (bool|undefined). */
export const recentRuns = (limit = 30) => call('GET', `/benchmark/runs?limit=${Number(limit) || 30}`).then((x) => asList(x));
export const runDetail = (id) => call('GET', `/benchmark/runs/${encodeURIComponent(id)}`);
export const getAlerts = () => call('GET', '/api/alerts');
export const providersHealth = (lastN = 100) => call('GET', `/api/providers/health?last_n=${Number(lastN) || 100}`);
export const memoryLineage = () => call('GET', '/api/memory/lineage');
export const benchmarkReportUrl = (fmt = 'md') => `/api/benchmark/report.${fmt === 'json' ? 'json' : 'md'}`;
export const jevStatus = () => call('GET', '/api/jev/status');
export const jevSaveConfig = (settings, apiKey) => call('POST', '/api/jev/config', { settings, api_key: apiKey || null });
export const jevTestConnection = () => call('POST', '/api/jev/test', {});


// ---- ANAM-029: memória (notas salvas) — CRUD, versões, lixeira, JSONL, consolidate ----
/** Como call(), mas para corpo/resposta que não é JSON (JSONL, diff). as: 'text' | 'blob'. */
async function rawCall(method, path, { body, contentType, as = 'text' } = {}) {
  const headers = {};
  if (contentType) headers['Content-Type'] = contentType;
  try { headers['X-MG-Token'] = await getLocalToken(); } catch { /* leitura funciona sem token em loopback */ }
  let r;
  try { r = await fetch(path, { method, headers, cache: 'no-store', body }); }
  catch (e) { throw new ApiError(0, 'network error', path, e && e.message ? e.message : 'fetch falhou'); }
  if (!r.ok) throw await errorFrom(r, path);
  return as === 'blob' ? r.blob() : r.text();
}
const _nid = (id) => encodeURIComponent(id);
export const memListNotes = ({ project, tag, kind } = {}) => call('GET', `/api/memory/notes?${_q({ project, tag, kind })}`);
export const memGetNote = (id) => call('GET', `/api/memory/notes/${_nid(id)}`);
export const memCreateNote = (note) => call('POST', '/api/memory/notes', note);
export const memUpdateNote = (id, patch) => call('PUT', `/api/memory/notes/${_nid(id)}`, patch);
export const memDeleteNote = (id) => call('DELETE', `/api/memory/notes/${_nid(id)}`);
export const memHistory = (id) => call('GET', `/api/memory/notes/${_nid(id)}/history`);
export const memDiff = (id, a, b = 'current') => rawCall('GET', `/api/memory/notes/${_nid(id)}/diff?${_q({ a, b })}`);
export const memRollback = (id, version) => call('POST', `/api/memory/notes/${_nid(id)}/rollback`, { version });
export const memTrash = () => call('GET', '/api/memory/trash');
export const memRestore = (trashId) => call('POST', `/api/memory/trash/${_nid(trashId)}/restore`, {});
export const memConsolidate = (apply = false) => call('POST', '/api/memory/consolidate', { apply: !!apply });
export const memExportJsonl = () => rawCall('GET', '/api/memory/export.jsonl', { as: 'blob' });
export const memImportJsonl = (text, overwrite = false) =>
  rawCall('POST', `/api/memory/import?${_q({ overwrite: overwrite ? 'true' : '' })}`, { body: text, contentType: 'text/plain; charset=utf-8' }).then((t) => JSON.parse(t));

/* ---- decision engine (somente leitura; sem rota de escrita de config) ------------------------------ */
export const decStatus = () => call('GET', '/api/decision/status');
export const decConfig = () => call('GET', '/api/decision/config');
export const decMetrics = () => call('GET', '/api/decision/metrics');
export const decEvaluation = () => call('GET', '/api/decision/evaluation');
export const decHistory = (limit = 500) => call('GET', `/api/decision/history?limit=${Math.min(500, Math.max(1, Number(limit) || 50))}`);
