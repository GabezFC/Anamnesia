// pages-orchestration.js — Config (Anamnesia): subagent orchestration presets.
// The cost of a preset is shown ONLY when the backend reports a measured/estimated figure for it;
// otherwise the text is "sem medição ainda" (a "cheaper" label is never asserted without data).
// i18n: strings come from i18n.js (PT-BR default, EN via the header toggle). Role/class names that the
// backend sends are translated only when known; unknown ones are shown as-is.
import { esc } from './format.js';
import { t, DICT } from './i18n.js';
import * as A from './anamnesia-api.js';

const LS_PRESET = 'anamnesia.orch.preset.v1';
const FALLBACK_IDS = ['economico', 'equilibrado', 'maximo'];
const fallback = () => [
  { id: 'economico', name: t('or.preset.economico.name'), description: t('or.preset.economico.desc'),
    roles: { orquestrador: 'forte', pesquisador: 'barato', implementador: 'médio', revisor: 'médio' } },
  { id: 'equilibrado', name: t('or.preset.equilibrado.name'), description: t('or.preset.equilibrado.desc'),
    roles: { orquestrador: 'forte', pesquisador: 'médio', implementador: 'forte', revisor: 'médio' }, default: true },
  { id: 'maximo', name: t('or.preset.maximo.name'), description: t('or.preset.maximo.desc'),
    roles: { orquestrador: 'forte', pesquisador: 'forte', implementador: 'forte', revisor: 'forte' } },
];
/** Translate a backend-provided role/class token when it is a known one (accent-insensitive). */
const tr = (prefix, v) => {
  const k = `${prefix}.${String(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()}`;
  return k in DICT.pt ? t(k) : String(v);
};
let alive = false;
const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };

export function renderOrchestration() {
  return `<div id="or-root">
    <div id="or-note"></div>
    <fieldset class="or-presets">
      <legend>${esc(t('or.legend'))}</legend>
      <div id="or-radios" role="radiogroup" aria-label="${esc(t('or.legend'))}"><div class="skel skel-chart"></div></div>
    </fieldset>
    <p id="or-sel" class="or-sel" role="status" aria-live="polite"></p>
    <details class="or-adv"><summary>${esc(t('or.advanced'))}</summary><div id="or-adv-body" class="or-adv-body"></div></details>
  </div>`;
}

export function unmountOrchestration() { alive = false; }

const presetName = (p) => (FALLBACK_IDS.includes(p.id) && !p.label && !p.name ? t(`or.preset.${p.id}.name`) : (p.label || p.name || p.id));
const presetDesc = (p) => (FALLBACK_IDS.includes(p.id) && !p.description ? t(`or.preset.${p.id}.desc`) : (p.description || ''));
const rolesOf = (p) => {
  const r = p.roles;
  if (Array.isArray(r)) return r.map((x) => [String(x.role ?? x.name ?? ''), String(x.class ?? x.model_class ?? x.model ?? '')]);
  if (r && typeof r === 'object') return Object.entries(r).map(([k, v]) => [k, typeof v === 'object' && v ? String(v.class ?? v.model ?? '') : String(v)]);
  return [];
};

function costLine(p) {
  const lv = p.cost_usd ?? p.cost ?? p.estimated_cost;
  const v = lv && typeof lv === 'object' ? lv.value : lv;
  if (typeof v === 'number' && Number.isFinite(v)) {
    return t('or.cost.value', { v: A.fmtUsd(v), o: A.originLabel(lv && typeof lv === 'object' ? lv.origin : 'estimated') });
  }
  return t('or.cost.none');
}

export async function mountOrchestration(root) {
  alive = true;
  let presets = fallback(); let backend = true;
  try {
    const got = await A.listPresets();
    if (got.length) presets = got.map((p, i) => ({ ...p, id: String(p.id ?? p.name ?? i) }));
  } catch (e) { backend = A.isUnavailable(e) ? false : String(e.message || 'erro'); }
  if (!alive) return;
  const note = root.querySelector('#or-note');
  if (backend === false) {
    note.innerHTML = `<div class="callout callout-info"><div class="callout-title">${esc(t('or.na.title'))}</div>
      <div class="callout-body">${esc(t('or.na.body'))}</div></div>`;
  } else if (backend !== true) {
    note.innerHTML = `<div class="callout callout-warn"><div class="callout-title">${esc(t('or.err.title'))}</div><div class="callout-body">${esc(backend)}</div></div>`;
  }
  let chosen = lsGet(LS_PRESET);
  if (!presets.some((p) => p.id === chosen)) chosen = (presets.find((p) => p.is_default || p.default) || presets[1] || presets[0]).id;
  const radios = root.querySelector('#or-radios');
  radios.innerHTML = presets.map((p) => `<label class="or-opt" for="or-${esc(p.id)}">
      <input type="radio" name="preset" id="or-${esc(p.id)}" value="${esc(p.id)}"${p.id === chosen ? ' checked' : ''}
        aria-describedby="or-d-${esc(p.id)}">
      <span class="or-name">${esc(presetName(p))}</span>
      <span class="or-desc" id="or-d-${esc(p.id)}">${esc(presetDesc(p))}
        <span class="or-cost">${esc(costLine(p))}</span></span>
    </label>`).join('');
  const sel = root.querySelector('#or-sel');
  const announce = () => {
    const p = presets.find((x) => x.id === radios.querySelector('input:checked')?.value);
    sel.textContent = p ? t('or.selected', { n: presetName(p), c: costLine(p) }) : '';
  };
  radios.addEventListener('change', () => {
    const v = radios.querySelector('input:checked')?.value;
    try { localStorage.setItem(LS_PRESET, v); } catch { /* ignore */ }
    announce(); paintAdvanced(root, presets, v);
  });
  announce(); paintAdvanced(root, presets, chosen);
  loadRuns(root);
}

function paintAdvanced(root, presets, id) {
  const p = presets.find((x) => x.id === id) || presets[0];
  const rows = rolesOf(p);
  const body = root.querySelector('#or-adv-body');
  if (!body) return;
  const runsHtml = body.querySelector('#or-runs')?.innerHTML || esc(t('or.loading'));
  body.innerHTML = `
    <h3>${esc(t('or.roles.title', { n: presetName(p) }))}</h3>
    ${rows.length ? `<table class="data"><thead><tr><th scope="col">${esc(t('or.roles.role'))}</th><th scope="col">${esc(t('or.roles.class'))}</th></tr></thead>
      <tbody>${rows.map(([r, c]) => `<tr><th scope="row" class="rowhead">${esc(tr('or.role', r))}</th><td>${esc(tr('or.class', c))}</td></tr>`).join('')}</tbody></table>`
    : `<p class="muted">${esc(t('or.roles.none'))}</p>`}
    <p class="or-note2">${esc(t('or.note2'))}</p>
    <h3>${esc(t('or.runs.title'))}</h3><div id="or-runs" aria-live="polite">${runsHtml}</div>`;
}

async function loadRuns(root) {
  const box = () => root.querySelector('#or-runs');
  try {
    const runs = await A.listOrchRuns();
    if (!alive || !box()) return;
    box().innerHTML = runs.length
      ? `<ul class="or-runs">${runs.slice(0, 20).map((r) => `<li><code>${esc(r.id ?? r.run_id ?? '')}</code> ${esc(r.preset || '')} ${esc(r.status || '')}</li>`).join('')}</ul>`
      : `<p class="or-muted">${esc(t('or.runs.none'))}</p>`;
  } catch (e) {
    if (alive && box()) box().innerHTML = `<p class="or-muted">${esc(A.isUnavailable(e) ? t('or.msg.na') : e.message)}</p>`;
  }
}
