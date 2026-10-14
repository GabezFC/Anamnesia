/**
 * LIVE DATA LAYER — liga o design (que lê os arrays de mock-data.js) ao backend real do Anamnésia.
 * Os arrays/objetos do mock são preenchidos IN PLACE antes do primeiro render. Se uma API estiver
 * indisponível, o mock continua e o bloco entra em `live.demo` — o shell mostra UM banner global
 * "Dados de demonstração: <blocos>" (ANA-201) e nunca apresenta número de mock como real.
 * O Laboratório (#/compare) NÃO usa mock: lê a API em lab-data.js (ANA-200).
 * Terminais: xterm.js real ligado ao PTY local da sessão, dentro de [data-terminal-mount].
 */
import {
  mockProjects, mockProfiles, mockSessions, mockFiles, mockConnections, mockPresets,
  mockCostSummary, mockBudget, mockCalls,
} from './mock-data.js';
import * as A from './anamnesia-api.js';
import { call } from './anamnesia-api.js';
import { SessionTerminal } from './terminals.js';
import { fmtTime } from './format.js';

export const live = { demo: new Set(), projects: false, sessions: false, health: { state: 'unknown', ms: null, warnings: [] }, alerts: [] };

/** Blocos do shell que estão em modo demonstração (mock mantido porque a API falhou). */
export const demoBlocks = () => [...live.demo];
export const isDemo = (block) => live.demo.has(block);

const SLOW_MS = 1500;
/** Saúde real do servidor local (GET /health). Nunca lança. */
export async function checkHealth() {
  const t0 = performance.now();
  try {
    const r = await fetch('/health', { cache: 'no-store' });
    const ms = Math.round(performance.now() - t0);
    let warnings = [];
    if (r.ok) { try { const j = await r.json(); warnings = Array.isArray(j?.warnings) ? j.warnings : []; } catch { warnings = []; } }
    live.health = { state: !r.ok ? 'error' : ms > SLOW_MS ? 'warn' : 'ok', ms, warnings };
  } catch { live.health = { state: 'error', ms: null }; }
  return live.health;
}

/** Alertas de regressão (ANA-202): lista vazia quando a API falha — nunca inventa. */
export async function refreshAlerts() {
  try {
    const r = await call('GET', '/api/alerts');
    live.alerts = Array.isArray(r?.alerts) ? r.alerts : [];
  } catch { live.alerts = []; }
  return live.alerts;
}

const fmtK = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n));
const hhmm = (ts) => fmtTime(ts);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const replace = (arr, next) => { arr.splice(0, arr.length, ...next); };
const safe = async (name, fn) => {
  try { await fn(); } catch (e) { live.demo.add(name); console.info('[live] mock mantido:', name, e?.message || e); }
};

/* ------------------------------------------------------------------ workspace */
function toSession(s, projects) {
  const proj = projects.find((p) => p.id === s.project_id);
  return {
    id: s.id, projectId: s.project_id, projectName: proj?.name || 'projeto', profileId: s.profile_id,
    title: `${s.profile_id} [${proj?.name || 'local'}]`, status: s.state,
    statusText: s.state === 'active' ? 'Ativo' : `Encerrado${s.exit_code != null ? ` (código ${s.exit_code})` : ''}`,
    cols: s.cols, rows: s.rows, startTime: hhmm(s.started_at), real: true,
    // worktree/subagente/MCP (valores crus: workspace.js aplica esc() ao renderizar)
    cwd: s.cwd || null, branch: s.branch || null, role: s.role || null, worktreeId: s.worktree_id || null,
    mcp: s.mcp && typeof s.mcp === 'object' ? s.mcp : null,
  };
}

export async function refreshSessions() {
  const sess = await A.listSessions();
  replace(mockSessions, sess.map((s) => toSession(s, mockProjects)));
  mockProjects.forEach((p) => { p.active_sessions = mockSessions.filter((s) => s.projectId === p.id && s.status === 'active').length; });
}

export async function loadFiles(projectId) {
  const dirs = [''];
  const out = [];
  const walk = async (path, indent) => {
    const r = await call('GET', `/api/projects/${encodeURIComponent(projectId)}/files${path ? `?path=${encodeURIComponent(path)}` : ''}`);
    const entries = (r.entries || []).filter((e) => !['.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'].includes(e.name));
    entries.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'dir' ? -1 : 1));
    for (const e of entries) {
      out.push({ name: esc(e.name), type: e.type === 'dir' ? 'dir' : 'file', indent, size: e.size != null ? `${(e.size / 1024).toFixed(1)} KB` : undefined });
    }
  };
  void dirs;
  await walk('', 0);
  replace(mockFiles, out);
}

async function loadWorkspace() {
  const [projects, profiles] = await Promise.all([A.listProjects(), A.listProfiles()]);
  live.projects = true;
  replace(mockProjects, projects.map((p) => ({
    id: esc(p.id), name: esc(p.name), path: esc(p.path), active_sessions: 0, git_branch: '—', vault_size_mb: 0,
  })));
  replace(mockProfiles, profiles.map((p) => ({
    id: esc(p.id), name: esc(p.name), description: esc(p.description), command: esc(p.command), available: !!p.available,
    icon: p.kind === 'agent' ? 'bot' : 'terminal',
  })));
  await refreshSessions();
  live.sessions = true;
  if (mockProjects[0]) await loadFiles(mockProjects[0].id).catch(() => replace(mockFiles, []));
  else replace(mockFiles, []);
}

export async function launchSession(projectId, profileId, opts = null) {
  const r = opts && (opts.worktree || opts.role || typeof opts.mcp === 'boolean')
    ? await A.createSessionOpts({ project: projectId, profile: profileId, ...opts })
    : await A.createSession(projectId, profileId);
  await refreshSessions();
  return r.session_id || r.session?.id;
}
export async function closeSession(id) {
  await A.deleteSession(id).catch(() => {});
  await refreshSessions();
}
export async function registerProject(name, path) {
  const p = await A.addProject(name, path);
  await loadWorkspace();
  return p;
}

/* ------------------------------------------------------------------ connections */
const CAT = { agent: 'agents', model: 'models', mcp: 'mcp' };
const TYPE_LABEL = { agent: 'Agente CLI', model: 'Provedor de modelo', mcp: 'Servidor MCP' };

async function loadConnections() {
  const list = await A.listConnections();
  const groups = { agents: [], models: [], mcp: [] };
  for (const c of list) {
    const k = c.keys ? Object.values(c.keys)[0] : null;
    groups[CAT[c.type] || 'mcp'].push({
      id: esc(c.id), name: esc(c.name), type: esc(TYPE_LABEL[c.type] || c.type), detected: !!c.detected, has_key: !!c.has_key,
      masked_key: esc(c.masked || k?.masked || '') || null, env_keys: (c.env_keys || []).map(esc),
      status: c.detected ? 'online' : 'offline', snippet: '', real: true, rawStatus: c.status,
    });
  }
  mockConnections.agents = groups.agents; mockConnections.models = groups.models; mockConnections.mcp = groups.mcp;
}

/* ------------------------------------------------------------------ presets */
const CLS = { cheap: ['barato', 'Barato'], medium: ['medio', 'Médio'], strong: ['forte', 'Forte'] };
const ROLE = { orchestrator: 'Orquestrador', researcher: 'Pesquisador', implementer: 'Implementador', reviewer: 'Revisor' };
const TAG = { economic: 'Foco em custo', balanced: 'Padrão recomendado', max: 'Raciocínio profundo' };
const DESC = {
  economic: 'Modelos baratos para a maior parte do trabalho; classes mais fortes só onde o papel exige.',
  balanced: 'Melhor relação custo-benefício: forte onde decide, médio onde executa.',
  max: 'A classe mais avançada de raciocínio em todos os papéis.',
};
const PID = { economic: 'economico', balanced: 'equilibrado', max: 'maximo' };

async function loadPresets() {
  const list = await A.listPresets();
  replace(mockPresets, list.map((p) => ({
    id: PID[p.name] || p.name, apiName: p.name, name: p.label, tag: TAG[p.name] || '', description: DESC[p.name] || '',
    roles: Object.fromEntries(Object.entries(p.roles).map(([role, cls]) => {
      const [c, label] = CLS[cls] || ['medio', cls];
      return [role, { title: ROLE[role] || role, class: c, className: `class-${c}`, label: `${label} (classe de modelo)` }];
    })),
    costNote: 'sem medição ainda',
  })));
}

/* ------------------------------------------------------------------ costs */
const ORIGIN = { measured: 'measured', estimated: 'estimated', unavailable: 'unavailable' };

async function loadCosts() {
  const [sum, page] = await Promise.all([A.costSummary('today'), A.costCalls({ limit: 100 })]);
  const items = page.items || [];
  replace(mockCalls, items.map((c) => ({
    id: esc(c.run_id), ts: c.created_at, when: hhmm(c.created_at), project: esc(c.project || '—'), agent: esc(c.client || c.agent || '—'),
    pipeline: esc(c.pipeline), context_tokens: A.lvValue(c.context_tokens), // null = indisponível (ANA-200), nunca 0 fabricado
    cost_usd: { value: A.lvValue(c.cost_usd), origin: ORIGIN[A.lvOrigin(c.cost_usd)] || 'unavailable' },
  })));
  const money = A.lvValue(sum.cost_usd);
  const ctx = A.lvValue(sum.context_tokens);
  const cand = A.lvValue(sum.candidate_tokens);
  const saved = cand != null && ctx != null ? cand - ctx : null;
  Object.assign(mockCostSummary, {
    total_usd: { value: money, origin: ORIGIN[A.lvOrigin(sum.cost_usd)], label: money == null ? 'indisponível' : `US$ ${money.toFixed(2)}` },
    calls: { value: sum.calls, origin: 'measured', label: `${sum.calls} chamadas` },
    context_tokens: { value: ctx, origin: ORIGIN[A.lvOrigin(sum.context_tokens)], label: ctx == null ? 'indisponível' : `${fmtK(ctx)} tok` },
    saved_tokens_est: { value: saved, origin: saved == null ? 'unavailable' : 'estimated', label: saved == null ? 'indisponível' : `${fmtK(saved)} tok` },
  });
  const b = sum.budget || {};
  // ANA-200: sem medição => null (a UI mostra "indisponível"), nunca 0 nem limite inventado.
  const mk = (x) => ({
    spent: x?.spent_usd ?? null, limit: x?.ceiling_usd ?? null, currency: 'US$',
    pct: x?.ratio != null ? x.ratio * 100 : null, status: x?.status || 'unavailable',
    statusLabel: x?.ceiling_usd == null ? 'Sem teto definido' : 'Normal',
  });
  Object.assign(mockBudget, { daily: mk(b.day), monthly: mk(b.month) });
}

/* ------------------------------------------------------------------ terminais xterm reais */
const terms = new Map(); // sessionId -> SessionTerminal

function attachTerminals() {
  document.querySelectorAll('[data-terminal-mount][data-session-id]').forEach((mount) => {
    const sid = mount.getAttribute('data-session-id');
    const s = mockSessions.find((x) => x.id === sid);
    if (!s || !s.real) return;
    let t = terms.get(sid);
    if (!t) {
      t = new SessionTerminal(sid, {});
      terms.set(sid, t);
      t.start();
    }
    if (t.el.parentElement !== mount) {
      mount.querySelector('[data-terminal-mock-view]')?.remove();
      mount.appendChild(t.el);
      requestAnimationFrame(() => { t.refit(); t.focus(); });
    }
  });
  for (const [sid, t] of terms) {
    if (!mockSessions.some((s) => s.id === sid)) { t.dispose(); terms.delete(sid); }
  }
}

export function installTerminalObserver() {
  const obs = new MutationObserver(() => attachTerminals());
  obs.observe(document.getElementById('app'), { childList: true, subtree: true });
  attachTerminals();
  setInterval(() => refreshSessions().catch(() => {}), 10000);
}

/* ------------------------------------------------------------------ boot */
export async function loadLive() {
  await Promise.all([
    safe('workspace', loadWorkspace), safe('connections', loadConnections), safe('presets', loadPresets),
    safe('costs', loadCosts), safe('gateway', loadGatewayConfig),
  ]);
  window.__liveDemo = [...live.demo];
  await Promise.all([checkHealth(), refreshAlerts()]);
}

export async function testConn(id) { return A.testConnection(id); }
export async function snippetOf(id) { return A.getSnippet(id); }
export async function saveKey(id, envKey, value) { return A.setSecret(id, envKey, value); }

/* ------------------------------------------------------------------ config do gateway (real) */
export const gatewayState = { vaultPath: '', modelKey: '', pruneThreshold: '—', enableJev: true, enablePrefilter: true, enableSemanticCache: true, real: false };
let persisted = { vaultPath: '', enableJev: true };
const LS_GW = 'anamnesia.gw.local.v1';

export async function loadGatewayConfig() {
  const [info, verdict, keys] = await Promise.all([call('GET', '/system/info'), call('GET', '/config/verdict'), call('GET', '/config/model-keys').catch(() => ({}))]);
  let local = {};
  try { local = JSON.parse(localStorage.getItem(LS_GW) || '{}'); } catch { /* ignore */ }
  Object.assign(gatewayState, {
    vaultPath: info.vault || '', enableJev: !!verdict.enabled, modelKey: Object.values(keys).find(Boolean) || '',
    enablePrefilter: local.enablePrefilter ?? true, enableSemanticCache: local.enableSemanticCache ?? true, real: true,
  });
  persisted = { vaultPath: gatewayState.vaultPath, enableJev: gatewayState.enableJev };
}

export async function saveGatewayConfig(next) {
  const prev = persisted;
  if (next.enableJev !== prev.enableJev) await call('POST', '/config/verdict', { enabled: !!next.enableJev });
  if (next.vaultPath && next.vaultPath !== prev.vaultPath) await call('POST', '/config/vault-path', { path: next.vaultPath });
  localStorage.setItem(LS_GW, JSON.stringify({ enablePrefilter: !!next.enablePrefilter, enableSemanticCache: !!next.enableSemanticCache }));
  Object.assign(gatewayState, next);
  persisted = { vaultPath: next.vaultPath || prev.vaultPath, enableJev: !!next.enableJev };
}

/* ------------------------------------------------------------------ predefinição de subagentes (local) */
const LS_PRESET = 'anamnesia.preset.v1';
export const getSavedPreset = () => localStorage.getItem(LS_PRESET);
export const savePreset = (id) => localStorage.setItem(LS_PRESET, id);

/* ------------------------------------------------------------------ nova comparação (somente estimativa, sem gastar tokens) */
export async function estimateBenchmark() {
  return call('POST', '/benchmark/estimate', { pipelines: ['baseline', 'graphify', 'graphify_jev', 'graphify_jev_opt'] });
}
