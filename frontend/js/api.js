// api.js — every call maps 1:1 to a route in app/api/routes.py. No invented endpoints.
//
// Routes actually used by this dashboard (all GET except where noted):
//   /health  /system/info  /system/integrations  /system/projects
//   /benchmark/runs  /benchmark/runs/{id}  /benchmark/sessions  /benchmark/stats  /benchmark/questions
//   /openapi.json (FastAPI, for the app version)
// The POST routes (/memory/search*, /benchmark/run*, /benchmark/threshold-sweep, /feedback/*)
// exist in the API but are deliberately NOT called: this is a read-only observability UI.
//
// The ONE exception is the /config/* group (§3, §5.4 da proposta 2026-09-28): the Configuração
// (setup) page is the single writer in this whole frontend, and every write it makes goes through
// apiWrite() below, which attaches the local write-protection token (app/services/security.py).
const cache = new Map();

/** HTTP error carrying the status and the FastAPI `detail` when present. */
export class ApiError extends Error {
  constructor(status, statusText, path, detail) {
    super(detail ? `${status} ${path} — ${detail}` : `${status} ${statusText} — ${path}`);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.detail = detail || null;
  }
}

async function request(path, opt) {
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    // Network-level failure (server down, DNS, CORS). Surfaced as a legible message, never swallowed.
    throw new ApiError(0, 'network error', path, e && e.message ? e.message : 'fetch falhou');
  }
  if (!r.ok) {
    let detail = null;
    try {
      const j = await r.json();
      detail = typeof j?.detail === 'string' ? j.detail : JSON.stringify(j?.detail ?? j);
    } catch { /* body was not JSON */ }
    throw new ApiError(r.status, r.statusText, path, detail);
  }
  try {
    return await r.json();
  } catch (e) {
    throw new ApiError(r.status, 'invalid JSON', path, e && e.message ? e.message : 'resposta não é JSON');
  }
}

export async function api(path, body) {
  const opt = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  return request(path, opt);
}

let tokenPromise = null;
/** GET /config/token is loopback-only (require_localhost): it only ever succeeds when this
 * dashboard is itself being served from 127.0.0.1/::1, which is exactly the caller the write path
 * below exists for. Fetched once per page load and reused for every subsequent write. */
function getLocalToken() {
  if (!tokenPromise) tokenPromise = api('/config/token').then((r) => r.token)
    .catch((e) => { tokenPromise = null; throw e; });
  return tokenPromise;
}

/** POST with the local write-protection token attached (app/services/security.py, §5.4). Used
 * ONLY by the Configuração (setup) page — every other page/function in this file stays read-only. */
export async function apiWrite(path, body) {
  const token = await getLocalToken();
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-MG-Token': token },
    body: JSON.stringify(body ?? {}),
  });
}

/** Memoised GET (per page load). A rejected promise is evicted so a retry can succeed. */
export async function cached(key, fn) {
  if (!cache.has(key)) cache.set(key, fn().catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
}
export function invalidate() { cache.clear(); }

/* ---- endpoint wrappers (route -> function) ---------------------------- */
export const getHealth = () => api('/health');                                     // GET /health
export const getSystemInfo = () => cached('sysinfo', () => api('/system/info'));   // GET /system/info
export const getIntegrations = () => cached('integr', () => api('/system/integrations'));
export const getSessions = () => cached('sessions', () => api('/benchmark/sessions?limit=200'));
export const getRuns = (limit = 5000) => cached(`runs:${limit}`, () => api(`/benchmark/runs?limit=${limit}`));
export const getRunsForSession = (sid) =>
  cached(`runs:s:${sid}`, () => api(`/benchmark/runs?session_id=${encodeURIComponent(sid)}&limit=5000`));
export const getRunDetail = (id) => cached(`run:${id}`, () => api(`/benchmark/runs/${encodeURIComponent(id)}`));
export const getStats = (sid) =>
  cached(`stats:${sid || ''}`, () => api(`/benchmark/stats${sid ? `?session_id=${encodeURIComponent(sid)}` : ''}`));
export const getQuestions = () => cached('questions', () => api('/benchmark/questions'));
// GET /system/projects — project/area entities discovered from the vault (data-driven, no hardcoding).
export const getProjects = () => cached('projects', () => api('/system/projects'));
export const getOpenApi = () => cached('openapi', () => api('/openapi.json'));

/** Fetch run details in bounded-concurrency batches (needed for sources/candidates). */
export async function getRunDetails(ids, concurrency = 6) {
  const out = [];
  for (let i = 0; i < ids.length; i += concurrency) {
    const slice = ids.slice(i, i + concurrency);
    // Individual failures are tolerated (a deleted run must not break the page) but they are
    // counted by the caller through the length difference.
    out.push(...await Promise.all(slice.map((id) => getRunDetail(id).catch(() => null))));
  }
  return out.filter(Boolean);
}

/* ---- /config/* (Configuração / setup page only, §3, §5.4) -------------- */
// Never cached: each of these must reflect the state that was just written, not a page-load memo.
export const getModelKeys = () => api('/config/model-keys');
export const setModelKey = (keyName, value) => apiWrite('/config/model-key', { key_name: keyName, value });
export const setVaultPath = (path) => apiWrite('/config/vault-path', { path });
export const getVerdictFlag = () => api('/config/verdict');
export const setVerdictFlag = (enabled) => apiWrite('/config/verdict', { enabled });
export const getOptionalStages = () => api('/config/optional-stages');
export const setOptionalStages = (stages) => apiWrite('/config/optional-stages', { stages });
