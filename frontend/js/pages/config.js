/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA CONFIGURATION PAGE (#/config)
 * Preferências gravadas no servidor (GET/PUT /api/settings): predefinição de subagentes, pré-filtro/cache,
 * idioma, pipeline padrão, teto de tokens, orçamento e regras de economia. Chaves por provedor via
 * connections.js (nunca reexibidas). Salvar é otimista: a UI muda já e volta atrás se o servidor recusar.
 */

import { icon } from '../icons.js';
import { I18N, getLang, setLang } from '../i18n.js';
import { esc, fmtNumber } from '../format.js';
import { mockPresets, mockConnections } from '../mock-data.js';
import { gatewayState } from '../live.js';
import { call, getSettings, putSettings, costBudget, costByRole, isUnavailable, fmtUsd } from '../anamnesia-api.js';
import { skeletonCard, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';
import { handleTablistKey, tabId, panelId } from '../components/tabs.js';
import { renderKeyRows, handleKeyAction, refreshKeyStatus } from './connections.js';

/* ------------------------------------------------------------------ helpers puros (testáveis) */
export const PIPELINES = ['auto', 'baseline', 'graphify', 'graphify_jev', 'graphify_jev_opt'];
const PIPELINE_KEY = {
  auto: 'pipelineAuto', baseline: 'pipelineBaseline', graphify: 'pipelineGraphify',
  graphify_jev: 'pipelineGraphifyJev', graphify_jev_opt: 'pipelineGraphifyJevOpt',
};
// chaves antigas do navegador: migradas uma vez para o servidor e removidas
export const LEGACY_PRESET_KEY = 'anamnesia.preset.v1';
export const LEGACY_GATEWAY_KEY = 'anamnesia.gw.local.v1';

export const fmt = (s, vars = {}) => String(s).replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''));
export const langToServer = (l) => (l === 'en' ? 'en' : 'pt-BR');
export const langFromServer = (l) => (String(l || '').toLowerCase().startsWith('en') ? 'en' : 'pt');

export function defaultSettings() {
  return {
    subagent_preset: {}, prefilter_cache: {}, terminal_layout: {}, language: 'pt-BR',
    budget: { daily_usd: null, monthly_usd: null, alert_pct: 80 },
    max_tokens_per_query: null, default_pipeline: 'auto',
    auto_graphify_jev_opt: false, reduce_max_results_by_question_type: false,
  };
}

/** Completa o que o servidor não devolveu (nunca deixa `undefined` chegar à UI). */
export function normalizeSettings(raw) {
  const d = defaultSettings();
  const s = raw && typeof raw === 'object' ? raw : {};
  return {
    ...d, ...s,
    subagent_preset: { ...(s.subagent_preset || {}) },
    prefilter_cache: { ...(s.prefilter_cache || {}) },
    terminal_layout: { ...(s.terminal_layout || {}) },
    budget: { ...d.budget, ...(s.budget || {}) },
    default_pipeline: PIPELINES.includes(s.default_pipeline) ? s.default_pipeline : 'auto',
  };
}

/** Merge parcial como o do servidor: objetos de 1º nível mesclam, o resto substitui. */
export function applyPatch(current, patch) {
  const out = { ...current };
  for (const [k, v] of Object.entries(patch)) {
    out[k] = v && typeof v === 'object' && !Array.isArray(v) ? { ...(current[k] || {}), ...v } : v;
  }
  return out;
}

/** '' → null; número ≥ 0 → número; inválido → undefined. */
export function parseUsd(text) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}
export function parseAlertPct(text) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (t === '') return 80;
  const n = Number(t);
  return Number.isFinite(n) && n >= 1 && n <= 100 ? n : undefined;
}
/** '' → null (sem teto); inteiro ≥ 1 → número; inválido → undefined. */
export function parseTokenCap(text) {
  const t = String(text ?? '').trim();
  if (t === '') return null;
  return /^\d+$/.test(t) && Number(t) >= 1 ? Number(t) : undefined;
}
export function buildBudgetPatch(daily, monthly, alertPct) {
  const d = parseUsd(daily); const m = parseUsd(monthly); const a = parseAlertPct(alertPct);
  if (d === undefined || m === undefined || a === undefined) return null;
  return { budget: { daily_usd: d, monthly_usd: m, alert_pct: a } };
}

/**
 * Decide o que migrar do localStorage antigo para o servidor (só quando o servidor está vazio).
 * `localPreset`: string|null; `localGw`: objeto|null. Retorna {patch, clearPreset, clearGw}.
 */
export function planMigration(current, localPreset, localGw) {
  const patch = {};
  const serverPreset = current.subagent_preset && current.subagent_preset.name;
  if (localPreset && !serverPreset) patch.subagent_preset = { name: String(localPreset) };
  const serverPc = current.prefilter_cache || {};
  const hasPc = 'enablePrefilter' in serverPc || 'enableSemanticCache' in serverPc;
  if (localGw && typeof localGw === 'object' && !hasPc
      && ('enablePrefilter' in localGw || 'enableSemanticCache' in localGw)) {
    patch.prefilter_cache = {
      enablePrefilter: localGw.enablePrefilter !== false,
      enableSemanticCache: localGw.enableSemanticCache !== false,
    };
  }
  return { patch, clearPreset: localPreset != null, clearGw: localGw != null };
}

/* ------------------------------------------------------------------ estado do módulo */
let activeTab = 'subagents'; // subagents | general | budget | economy | keys | gateway | active
let currentState = 'loading'; // 'loaded' | 'loading' | 'empty' | 'error' | 'backend-unavailable'
let settings = null;          // espelho do servidor (já com alterações otimistas)
let budgetStatus = null;      // GET /api/costs/budget ou null
let byRole = null;            // GET /api/costs/by-role ou null (indisponível)
let activeRoot = null;
let lastServerLang = null;
let persistedGw = null;       // {vaultPath, enableJev} já gravados no gateway
let inlineError = '';         // erro de validação mostrado na aba

const gatewayConfig = gatewayState;
const toast = (type, message) => window.dispatchEvent(new CustomEvent('anamnesia:toast', { detail: { type, message } }));
const errMsg = (e) => (e && e.message ? e.message : String(e));
const paint = (root) => { if (root && activeRoot === root) root.innerHTML = render(); };
const selectedPresetId = () => (settings && settings.subagent_preset && settings.subagent_preset.name)
  || (mockPresets.find((p) => p.id === 'equilibrado') || mockPresets[0] || {}).id || 'equilibrado';

function syncGatewayFromSettings() {
  const pc = (settings && settings.prefilter_cache) || {};
  if ('enablePrefilter' in pc) gatewayConfig.enablePrefilter = !!pc.enablePrefilter;
  if ('enableSemanticCache' in pc) gatewayConfig.enableSemanticCache = !!pc.enableSemanticCache;
}

async function refreshBudget() {
  try { budgetStatus = await costBudget(); } catch { budgetStatus = null; }
}
async function refreshByRole() {
  try { byRole = await costByRole('all'); } catch { byRole = null; }
}

/** Salvar otimista: aplica já, envia, e reverte (com aviso) se falhar. */
async function saveSettings(root, patch, { okMessage = null } = {}) {
  const snapshot = settings;
  settings = applyPatch(settings, patch);
  syncGatewayFromSettings();
  paint(root);
  try {
    const saved = await putSettings(patch);
    settings = normalizeSettings({ ...settings, ...(saved && typeof saved === 'object' ? saved : {}) });
    syncGatewayFromSettings();
    if (patch.language) lastServerLang = settings.language;
    if (patch.budget) await refreshBudget();
    paint(root);
    if (okMessage) toast('success', okMessage);
    return true;
  } catch (e) {
    settings = snapshot;
    syncGatewayFromSettings();
    paint(root);
    toast('error', fmt(I18N.config.saveFailed, { err: errMsg(e) }));
    return false;
  }
}

function readLocal(key, asJson) {
  try {
    const raw = localStorage.getItem(key);
    if (raw == null) return null;
    return asJson ? JSON.parse(raw) : raw;
  } catch { return null; }
}
function dropLocal(key) { try { localStorage.removeItem(key); } catch { /* storage bloqueado */ } }

/** Migra predefinição e pré-filtro/cache antigos do navegador (uma vez) e apaga as chaves locais. */
async function migrateLegacy() {
  const plan = planMigration(settings, readLocal(LEGACY_PRESET_KEY, false), readLocal(LEGACY_GATEWAY_KEY, true));
  if (!plan.clearPreset && !plan.clearGw) return;
  if (Object.keys(plan.patch).length) {
    try {
      const saved = await putSettings(plan.patch);
      settings = normalizeSettings({ ...applyPatch(settings, plan.patch), ...(saved && typeof saved === 'object' ? saved : {}) });
      toast('info', I18N.config.gwMigrated);
    } catch { return; } // mantém o valor local para tentar de novo depois
  }
  if (plan.clearPreset) dropLocal(LEGACY_PRESET_KEY);
  if (plan.clearGw) dropLocal(LEGACY_GATEWAY_KEY);
}

async function load(root, { silent = false } = {}) {
  if (!silent) { currentState = 'loading'; paint(root); }
  let next = 'loaded';
  try {
    settings = normalizeSettings(await getSettings());
  } catch (e) {
    settings = settings || normalizeSettings({});
    next = isUnavailable(e) ? 'backend-unavailable' : 'error';
  }
  currentState = next;
  if (next === 'loaded') {
    await migrateLegacy();
    syncGatewayFromSettings();
    lastServerLang = settings.language;
    const want = langFromServer(settings.language);
    if (want !== getLang()) setLang(want); // servidor manda; o evento re-renderiza a casca
  }
  if (!persistedGw) persistedGw = { vaultPath: gatewayConfig.vaultPath, enableJev: !!gatewayConfig.enableJev };
  if (next !== 'error') await Promise.all([refreshBudget(), refreshByRole()]);
  paint(root);
}

/* Idioma do seletor do topo → servidor. */
if (typeof window !== 'undefined') {
  window.addEventListener('anamnesia:lang', (e) => {
    const next = langToServer(e.detail && e.detail.lang);
    if (!settings || next === lastServerLang) return;
    const prev = lastServerLang;
    lastServerLang = next;
    settings = applyPatch(settings, { language: next });
    putSettings({ language: next }).catch(() => { lastServerLang = prev; });
  });
}

/* ------------------------------------------------------------------ render */
const toggle = (action, on, label) => `
  <button class="toggle-switch" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}" data-action="${action}">
    <span class="toggle-switch-thumb"></span>
  </button>`;

const toggleRow = (action, on, title, desc) => `
  <div class="gateway-toggle-row">
    <div class="gateway-toggle-info">
      <span class="gateway-toggle-title">${title}</span>
      <span class="gateway-toggle-desc">${desc}</span>
    </div>
    ${toggle(action, on, title)}
  </div>`;

const sectionHead = (title, desc) => `
  <div>
    <h2 class="u-b3753b">${title}</h2>
    <p class="u-47c8df">${desc}</p>
  </div>`;

export function render() {
  const t = I18N.config;

  if (currentState === 'loading') {
    return `
      <div class="config-page" data-bind="config-page-loading">
        ${loadingBlock(`${skeletonCard({ lines: 1 })}${skeletonCard({ lines: 4 })}${skeletonCard({ lines: 3 })}`, t.loading)}
      </div>`;
  }

  if (currentState === 'error') {
    return `
      <div class="config-page">
        ${emptyState({
          title: I18N.app.errorTitle, description: t.loadErrorDesc, variant: 'error',
          action: { label: I18N.app.errorRetry, action: 'retry-config', kind: 'secondary' },
        })}
      </div>`;
  }

  if (!settings) settings = normalizeSettings({});

  const backendNotice = currentState === 'backend-unavailable' ? `
    <div class="callout-notice u-36fc7e">
      <div class="callout-notice-icon">${icon('info', '', 18)}</div>
      <div class="callout-notice-body">
        <strong>${I18N.app.backendUnavailableTitle}</strong>
        ${I18N.app.backendUnavailableDesc}
      </div>
    </div>` : '';

  const tabs = [
    ['subagents', t.tabSubagents], ['general', t.tabGeneral], ['budget', t.tabBudget],
    ['economy', t.tabEconomy], ['keys', t.tabKeys], ['gateway', t.tabGateway], ['active', t.tabActive],
  ];
  const body = {
    subagents: renderSubagentsTab, general: renderGeneralTab, budget: renderBudgetTab,
    economy: renderEconomyTab, keys: renderKeysTab, gateway: renderGatewayTab, active: renderActiveConfigTab,
  }[activeTab] || renderSubagentsTab;

  return `
    <div class="config-page" data-bind="config-page">
      ${backendNotice}
      <div class="connections-header-bar">
        <div>
          <h1 class="u-23e58e">${I18N.nav.config}</h1>
          <p class="u-47c8df">${t.subtitle}</p>
        </div>
      </div>

      <nav class="config-tabs-nav" role="tablist" aria-label="${esc(I18N.a11y.configTabs)}" data-bind="config-tablist">
        ${tabs.map(([id, label]) => `
          <button type="button" class="config-tab-item ${activeTab === id ? 'is-active' : ''}" role="tab" id="${tabId('config', id)}" aria-selected="${activeTab === id}" aria-controls="${panelId('config')}" tabindex="${activeTab === id ? '0' : '-1'}" data-action="switch-config-tab" data-tab="${id}">${label}</button>`).join('')}
      </nav>

      <div role="tabpanel" id="${panelId('config')}" aria-labelledby="${tabId('config', activeTab)}" tabindex="0">
        ${body(t)}
      </div>
    </div>`;
}

function renderSubagentsTab(t) {
  if (!mockPresets.length) {
    return emptyState({ title: t.presetsEmpty, description: t.presetsEmptyDesc, variant: 'data' });
  }
  const sel = selectedPresetId();
  return `
    <div class="u-59ee07">
      ${sectionHead(t.presetsTitle, t.subagentsDesc)}
      <div class="presets-grid" role="radiogroup">
        ${mockPresets.map((preset) => {
          const isSelected = preset.id === sel;
          return `
            <div class="preset-card ${isSelected ? 'is-selected' : ''}" role="radio" aria-checked="${isSelected}" tabindex="0"
                 data-action="select-preset" data-preset-id="${esc(preset.id)}">
              <div class="preset-card-header">
                <div>
                  <div class="preset-name">${esc(preset.name)}</div>
                  <div class="u-32b9cb">${esc(preset.description)}</div>
                </div>
                <span class="preset-tag">${esc(preset.tag)}</span>
              </div>
              <div class="preset-roles-matrix">
                ${Object.values(preset.roles || {}).map((role) => `
                  <div class="preset-role-row">
                    <span class="role-title">${esc(role.title)}</span>
                    <span class="role-class-badge ${esc(role.className)}">${esc(role.label)}</span>
                  </div>`).join('')}
              </div>
              <div class="preset-cost-line">
                <span class="dot dot-neutral"></span>
                <span>${t.estimatedCostNoData}</span>
              </div>
            </div>`;
        }).join('')}
      </div>
    </div>`;
}

function renderGeneralTab(t) {
  const s = settings;
  const lang = langFromServer(s.language);
  return `
    <div class="gateway-form-card">
      ${sectionHead(t.generalTitle, t.generalDesc)}

      <div class="input-group">
        <label class="input-label" for="cfg-lang">${t.languageLabel}</label>
        <div class="input-control">
          <select id="cfg-lang" data-bind="language-select" data-action-change="set-language">
            <option value="pt" ${lang === 'pt' ? 'selected' : ''}>Português (Brasil)</option>
            <option value="en" ${lang === 'en' ? 'selected' : ''}>English</option>
          </select>
        </div>
        <span class="config-field-hint">${t.languageDesc}</span>
      </div>

      <div class="input-group">
        <label class="input-label" for="cfg-pipeline">${t.pipelineLabel}</label>
        <div class="input-control">
          <select id="cfg-pipeline" data-bind="pipeline-select" data-action-change="set-pipeline">
            ${PIPELINES.map((p) => `<option value="${p}" ${s.default_pipeline === p ? 'selected' : ''}>${t[PIPELINE_KEY[p]]}</option>`).join('')}
          </select>
        </div>
        <span class="config-field-hint">${t.pipelineDesc}</span>
      </div>

      <div class="input-group">
        <label class="input-label" for="cfg-maxtok">${t.maxTokensLabel}</label>
        <div class="input-control">
          <input id="cfg-maxtok" type="number" inputmode="numeric" min="1" step="1" data-bind="max-tokens-input"
                 value="${s.max_tokens_per_query ?? ''}" placeholder="${t.maxTokensPlaceholder}" />
        </div>
        <span class="config-field-hint">${t.maxTokensDesc}</span>
        ${inlineError && activeTab === 'general' ? `<span class="config-field-error" role="alert">${esc(inlineError)}</span>` : ''}
      </div>

      <div class="u-98a939">
        <button class="btn btn-primary" data-action="save-max-tokens">${I18N.app.save}</button>
      </div>
    </div>`;
}

function budgetUsageLine(t, period) {
  if (!budgetStatus || !budgetStatus[period]) return t.budgetUnavailable;
  const b = budgetStatus[period];
  if (b.limit_usd == null) return t.budgetNoCap;
  const spent = typeof b.spent_usd === 'number' ? fmtUsd(b.spent_usd) : t.costUnavailable;
  const pct = typeof b.percent === 'number' ? b.percent.toFixed(0) : '—';
  return `${fmt(t.budgetUsage, { spent, limit: fmtUsd(b.limit_usd), pct })}${b.exceeded ? ` · ${t.budgetExceeded}` : ''}`;
}

function renderBudgetTab(t) {
  const b = settings.budget;
  const alertState = budgetStatus
    ? `<div><span class="chip ${budgetStatus.alert ? 'chip-unconfigured' : 'chip-online'}">${budgetStatus.alert ? t.budgetAlertOn : t.budgetAlertOff}</span></div>` : '';
  return `
    <div class="gateway-form-card">
      ${sectionHead(t.budgetTitle, t.budgetDesc)}
      ${alertState}

      <div class="input-group">
        <label class="input-label" for="cfg-b-daily">${t.budgetDaily}</label>
        <div class="input-control">
          <input id="cfg-b-daily" type="number" min="0" step="0.01" data-bind="budget-daily" value="${b.daily_usd ?? ''}" placeholder="${t.budgetNoCap}" />
        </div>
        <span class="config-field-hint">${budgetUsageLine(t, 'daily')}</span>
      </div>

      <div class="input-group">
        <label class="input-label" for="cfg-b-monthly">${t.budgetMonthly}</label>
        <div class="input-control">
          <input id="cfg-b-monthly" type="number" min="0" step="0.01" data-bind="budget-monthly" value="${b.monthly_usd ?? ''}" placeholder="${t.budgetNoCap}" />
        </div>
        <span class="config-field-hint">${budgetUsageLine(t, 'monthly')}</span>
      </div>

      <div class="input-group">
        <label class="input-label" for="cfg-b-alert">${t.budgetAlertPct}</label>
        <div class="input-control">
          <input id="cfg-b-alert" type="number" min="1" max="100" step="1" data-bind="budget-alert" value="${b.alert_pct ?? 80}" />
        </div>
        ${inlineError && activeTab === 'budget' ? `<span class="config-field-error" role="alert">${esc(inlineError)}</span>` : ''}
      </div>

      <div class="u-98a939">
        <button class="btn btn-primary" data-action="save-budget">${t.budgetSave}</button>
      </div>
    </div>`;
}

function roleLabel(t, role) {
  const k = { orchestrator: 'roleOrchestrator', researcher: 'roleResearcher', implementer: 'roleImplementer', reviewer: 'roleReviewer' }[role];
  return k ? t[k] : esc(role);
}

function renderByRole(t) {
  const items = byRole && Array.isArray(byRole.items) ? byRole.items : [];
  if (!items.length) return emptyState({ title: t.byRoleEmpty, description: t.byRoleEmptyDesc, variant: 'cost', compact: true });
  const fmtN = (n) => fmtNumber(n);
  return `
    <table class="config-role-table">
      <thead><tr><th>${t.colRole}</th><th>${t.colCalls}</th><th>${t.colTokens}</th><th>${t.colCost}</th></tr></thead>
      <tbody>
        ${items.map((i) => {
          const unavailable = typeof i.cost_usd !== 'number' || i.cost_status === 'unavailable';
          return `<tr>
            <td>${roleLabel(t, i.role)}</td>
            <td class="tabular">${fmtN(i.calls)}</td>
            <td class="tabular">${fmtN(i.input_tokens)} / ${fmtN(i.output_tokens)}</td>
            <td class="tabular">${unavailable ? t.costUnavailable : fmtUsd(i.cost_usd)}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>`;
}

function renderEconomyTab(t) {
  const s = settings;
  const pct = s.budget.alert_pct ?? 80;
  const alertOn = budgetStatus ? !!budgetStatus.alert : null;
  return `
    <div class="u-59ee07">
      <div class="gateway-form-card">
        ${sectionHead(t.economyTitle, t.economyDesc)}
        ${toggleRow('toggle-auto-jev-opt', s.auto_graphify_jev_opt, t.ecoJevOpt, t.ecoJevOptDesc)}
        ${toggleRow('toggle-reduce-results', s.reduce_max_results_by_question_type, t.ecoReduce, t.ecoReduceDesc)}
        <div class="gateway-toggle-row">
          <div class="gateway-toggle-info">
            <span class="gateway-toggle-title">${fmt(t.ecoAlert, { pct })}</span>
            <span class="gateway-toggle-desc">${t.ecoAlertDesc}</span>
          </div>
          ${alertOn == null ? '' : `<span class="chip ${alertOn ? 'chip-unconfigured' : 'chip-online'}">${alertOn ? t.budgetAlertOn : t.budgetAlertOff}</span>`}
        </div>
      </div>

      <div class="gateway-form-card">
        ${sectionHead(t.byRoleTitle, t.byRoleDesc)}
        ${renderByRole(t)}
      </div>
    </div>`;
}

function renderKeysTab(t) {
  const providers = (mockConnections.models || []).filter((m) => m.env_keys && m.env_keys.length);
  return `
    <div class="u-a19567">
      ${sectionHead(t.keysTitle, t.keysDesc)}
      ${providers.length ? `<div class="cards-grid">${providers.map((p) => `
        <div class="connection-card" data-connection-id="${p.id}">
          <div class="connection-card-top">
            <div class="connection-brand">
              <div class="connection-avatar">${p.name.charAt(0)}</div>
              <div><div class="connection-name">${p.name}</div><div class="connection-type">${p.type}</div></div>
            </div>
          </div>
          ${renderKeyRows(p)}
          <div class="connection-card-actions">
            <span></span>
            <div class="connection-card-actions-right">
              <button class="btn btn-secondary btn-sm" data-action="test-connection" data-item-id="${p.id}">${t.keyTest}</button>
            </div>
          </div>
        </div>`).join('')}</div>`
        : emptyState({ title: t.keysEmpty, description: t.keysEmptyDesc, variant: 'data', compact: true })}
    </div>`;
}

function renderGatewayTab(t) {
  return `
    <div class="gateway-form-card">
      ${sectionHead(t.gwTitle, t.gwDesc)}

      <div class="input-group">
        <label class="input-label" for="cfg-vault-path">${t.gatewayVaultLabel}</label>
        <div class="input-control">
          <input id="cfg-vault-path" type="text" value="${esc(gatewayConfig.vaultPath)}" data-bind="vault-path-input" />
        </div>
        <div class="vault-scaffold-row">
          <button class="btn btn-secondary" data-action="scaffold-vault">${t.vaultScaffoldBtn}</button>
          <span class="input-hint">${t.vaultScaffoldHint}</span>
        </div>
      </div>

      <div class="input-group">
        <label class="input-label" for="cfg-model-key">${t.gatewayModelKeyLabel}</label>
        <div class="input-control">
          <input id="cfg-model-key" type="password" value="" readonly autocomplete="new-password" placeholder="${esc(gatewayConfig.modelKey || t.gwNoKey)}" />
        </div>
      </div>

      ${toggleRow('toggle-jev', gatewayConfig.enableJev, t.gatewayVerdictJev, t.gatewayVerdictDesc)}
      ${toggleRow('toggle-prefilter', gatewayConfig.enablePrefilter, t.gatewayPreFilter, t.gatewayPreFilterDesc)}
      ${toggleRow('toggle-cache', gatewayConfig.enableSemanticCache, t.gwCacheTitle, t.gwCacheDesc)}

      <div class="u-b6ea2e">
        <button class="btn btn-primary" data-action="save-gateway-config">${I18N.app.save}</button>
      </div>
    </div>`;
}

function renderActiveConfigTab(t) {
  const preset = mockPresets.find((p) => p.id === selectedPresetId());
  const s = settings;
  const kv = (label, value) => `<div class="readonly-kv-item"><span class="readonly-kv-label">${label}</span>${value}</div>`;
  const val = (v, css = '') => `<span class="readonly-kv-value"${css ? ` data-css="${esc(css)}"` : ''}>${v}</span>`;
  const onOff = (v) => val(v ? t.enabled : t.disabled, `color: ${v ? 'var(--success)' : 'var(--text-tertiary)'};`);
  const cap = (v) => (v == null ? t.noCap : fmtUsd(v));
  return `
    <div class="u-a19567">
      ${sectionHead(t.activeTitle, t.activeDesc)}
      <div class="readonly-kv-grid">
        ${kv(t.activePreset, val(esc(preset ? preset.name : selectedPresetId())))}
        ${kv(t.activeJev, onOff(gatewayConfig.enableJev))}
        ${kv(t.activePrefilter, onOff(gatewayConfig.enablePrefilter))}
        ${kv(t.activePrune, val(esc(gatewayConfig.pruneThreshold)))}
        ${kv(t.activeVault, val(esc(gatewayConfig.vaultPath), 'font-family: var(--font-mono); font-size: 12px;'))}
        ${kv(t.activePipeline, val(t[PIPELINE_KEY[s.default_pipeline]]))}
        ${kv(t.activeMaxTokens, val(s.max_tokens_per_query == null ? t.noCap : fmtNumber(s.max_tokens_per_query)))}
        ${kv(t.activeBudget, val(`${cap(s.budget.daily_usd)} / ${cap(s.budget.monthly_usd)}`))}
        ${kv(t.activeLanguage, val(langFromServer(s.language) === 'en' ? 'English' : 'Português (Brasil)'))}
        ${kv(t.activeDaemon, `<span class="readonly-kv-value u-032ebf"><span class="dot dot-success"></span> ${t.activeDaemonOn}</span>`)}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ ações */
async function scaffoldVault(root) {
  const t = I18N.config;
  const vp = root.querySelector('[data-bind="vault-path-input"]')?.value?.trim();
  if (!vp) { toast('error', t.vaultScaffoldNoPath); return; }
  try {
    const plan = await call('POST', '/config/vault-scaffold', { path: vp, dry_run: true });
    if (!plan.created.length) { toast('success', t.vaultScaffoldNothing); return; }
    if (!window.confirm(fmt(t.vaultScaffoldConfirm, { n: plan.created.length, path: plan.root }))) return;
    const done = await call('POST', '/config/vault-scaffold', { path: vp });
    toast('success', fmt(t.vaultScaffoldDone, { n: done.created.length }));
  } catch (e) {
    toast('error', fmt(t.saveFailed, { err: errMsg(e) }));
  }
}

async function saveGateway(root) {
  const vp = root.querySelector('[data-bind="vault-path-input"]')?.value?.trim() || gatewayConfig.vaultPath;
  const prev = persistedGw || { vaultPath: '', enableJev: true };
  try {
    if (!!gatewayConfig.enableJev !== !!prev.enableJev) await call('POST', '/config/verdict', { enabled: !!gatewayConfig.enableJev });
    if (vp && vp !== prev.vaultPath) await call('POST', '/config/vault-path', { path: vp });
    gatewayConfig.vaultPath = vp;
    persistedGw = { vaultPath: vp, enableJev: !!gatewayConfig.enableJev };
  } catch (e) {
    toast('error', fmt(I18N.config.saveFailed, { err: errMsg(e) }));
    return;
  }
  await saveSettings(root, {
    prefilter_cache: { enablePrefilter: !!gatewayConfig.enablePrefilter, enableSemanticCache: !!gatewayConfig.enableSemanticCache },
  }, { okMessage: I18N.config.gwSaved });
}

/** Troca a aba ativa (clique ou setas) e dispara o refresh de dados da aba; `focus` devolve o foco à aba. */
function switchConfigTab(root, id, { focus = false } = {}) {
  if (!id) return;
  activeTab = id;
  inlineError = '';
  const repaint = () => paint(root);
  repaint();
  if (focus) root.querySelector(`#${tabId('config', id)}`)?.focus();
  if (activeTab === 'economy') refreshByRole().then(() => activeTab === 'economy' && repaint());
  if (activeTab === 'budget') refreshBudget().then(() => activeTab === 'budget' && repaint());
  if (activeTab === 'keys') refreshKeyStatus().then(() => activeTab === 'keys' && repaint());
}

export function mount(root) {
  activeRoot = root;
  inlineError = '';

  const onChange = (e) => {
    const sel = e.target.closest('[data-action-change]');
    if (!sel) return;
    const a = sel.getAttribute('data-action-change');
    if (a === 'set-language') {
      const lang = sel.value === 'en' ? 'en' : 'pt';
      const server = langToServer(lang);
      if (server === settings.language) return;
      lastServerLang = server; // o listener global não repete o PUT
      settings = applyPatch(settings, { language: server });
      putSettings({ language: server }).catch((err) => toast('error', fmt(I18N.config.saveFailed, { err: errMsg(err) })));
      setLang(lang);
    } else if (a === 'set-pipeline') {
      if (PIPELINES.includes(sel.value)) saveSettings(root, { default_pipeline: sel.value }, { okMessage: I18N.config.saved });
    }
  };

  const onClick = (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    const action = target.getAttribute('data-action');
    const repaint = () => paint(root);

    if (action === 'switch-config-tab') {
      switchConfigTab(root, target.getAttribute('data-tab'));
    } else if (action === 'select-preset') {
      const id = target.getAttribute('data-preset-id');
      if (id !== selectedPresetId()) saveSettings(root, { subagent_preset: { name: id } }, { okMessage: I18N.config.presetChanged });
    } else if (action === 'toggle-auto-jev-opt') {
      saveSettings(root, { auto_graphify_jev_opt: !settings.auto_graphify_jev_opt });
    } else if (action === 'toggle-reduce-results') {
      saveSettings(root, { reduce_max_results_by_question_type: !settings.reduce_max_results_by_question_type });
    } else if (action === 'save-max-tokens') {
      const cap = parseTokenCap(root.querySelector('[data-bind="max-tokens-input"]')?.value);
      if (cap === undefined) { inlineError = I18N.config.maxTokensInvalid; repaint(); return; }
      inlineError = '';
      saveSettings(root, { max_tokens_per_query: cap }, { okMessage: I18N.config.saved });
    } else if (action === 'save-budget') {
      const q = (k) => root.querySelector(`[data-bind="${k}"]`)?.value;
      const patch = buildBudgetPatch(q('budget-daily'), q('budget-monthly'), q('budget-alert'));
      if (!patch) { inlineError = I18N.config.budgetInvalid; repaint(); return; }
      inlineError = '';
      saveSettings(root, patch, { okMessage: I18N.config.saved });
    } else if (action === 'scaffold-vault') {
      scaffoldVault(root);
    } else if (action === 'toggle-jev') {
      gatewayConfig.enableJev = !gatewayConfig.enableJev; repaint();
    } else if (action === 'toggle-prefilter') {
      gatewayConfig.enablePrefilter = !gatewayConfig.enablePrefilter; repaint();
    } else if (action === 'toggle-cache') {
      gatewayConfig.enableSemanticCache = !gatewayConfig.enableSemanticCache; repaint();
    } else if (action === 'save-gateway-config') {
      saveGateway(root);
    } else if (action === 'save-key' || action === 'remove-key' || action === 'test-connection') {
      handleKeyAction(action, target, { toast, rerender: repaint });
    } else if (action === 'retry-config') {
      load(root);
    }
  };

  const onKey = (e) => {
    const list = e.target.closest && e.target.closest('[data-bind="config-tablist"]');
    if (list) handleTablistKey(e, list, '[role="tab"]', (tab) => switchConfigTab(root, tab.getAttribute('data-tab'), { focus: true }));
  };
  root.addEventListener('click', onClick);
  root.addEventListener('keydown', onKey);
  root.addEventListener('change', onChange);
  root._configCleanup = () => {
    root.removeEventListener('click', onClick);
    root.removeEventListener('keydown', onKey);
    root.removeEventListener('change', onChange);
    if (activeRoot === root) activeRoot = null;
  };

  if (settings && currentState === 'loaded') { paint(root); load(root, { silent: true }); } else load(root);
}

export function unmount(root) {
  if (root && root._configCleanup) {
    root._configCleanup();
    delete root._configCleanup;
  }
}

export function setDebugState(state, root) {
  currentState = state;
  if (!settings) settings = normalizeSettings({});
  if (root) root.innerHTML = render();
}
