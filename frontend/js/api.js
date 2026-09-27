// api.js — every call maps 1:1 to a route in app/api/routes.py. No invented endpoints.
const cache = new Map();

export async function api(path, body) {
  const opt = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json();
}

/** Memoised GET (per page load). */
export async function cached(key, fn) {
  if (!cache.has(key)) cache.set(key, fn().catch((e) => { cache.delete(key); throw e; }));
  return cache.get(key);
}
export function invalidate() { cache.clear(); }

/* ---- endpoint wrappers (route -> function) ---------------------------- */
export const getHealth = () => api('/health');                                     // GET /health
export const getSystemInfo = () => cached('sysinfo', () => api('/system/info'));   // GET /system/info
export const getIntegrations = () => cached('integr', () => api('/system/integrations'));
export const getSessions = () => cached('sessions', () => api('/benchmark/sessions'));
export const getRuns = (limit = 1000) => cached(`runs:${limit}`, () => api(`/benchmark/runs?limit=${limit}`));
export const getRunsForSession = (sid) =>
  cached(`runs:s:${sid}`, () => api(`/benchmark/runs?session_id=${encodeURIComponent(sid)}&limit=1000`));
export const getRunDetail = (id) => cached(`run:${id}`, () => api(`/benchmark/runs/${id}`));
export const getStats = (sid) =>
  cached(`stats:${sid || ''}`, () => api(`/benchmark/stats${sid ? `?session_id=${encodeURIComponent(sid)}` : ''}`));
export const getQuestions = () => cached('questions', () => api('/benchmark/questions'));
// GET /system/projects — project/area entities discovered from the vault (data-driven, no hardcoding).
export const getProjects = () => cached('projects', () => api('/system/projects'));

/** Fetch run details in bounded-concurrency batches (needed for sources/candidates). */
export async function getRunDetails(ids, concurrency = 6) {
  const out = [];
  for (let i = 0; i < ids.length; i += concurrency) {
    const slice = ids.slice(i, i + concurrency);
    out.push(...await Promise.all(slice.map((id) => getRunDetail(id).catch(() => null))));
  }
  return out.filter(Boolean);
}
