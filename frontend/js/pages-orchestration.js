// pages-orchestration.js — Config (Anamnesia): subagent orchestration presets.
// The cost of a preset is shown ONLY when the backend reports a measured/estimated figure for it;
// otherwise the text is "sem medição ainda" (a "cheaper" label is never asserted without data).
// i18n: no i18n helper exists in this frontend (format.js only formats numbers/dates), so the
// PT-BR/EN toggle is intentionally not implemented.
import { esc } from './format.js';
import * as A from './anamnesia-api.js';

const LS_PRESET = 'anamnesia.orch.preset.v1';
const FALLBACK = [
  { id: 'economico', name: 'Econômico', description: 'Orquestrador forte; pesquisa barata, implementação e revisão médias.',
    roles: { orquestrador: 'forte', pesquisador: 'barato', implementador: 'médio', revisor: 'médio' } },
  { id: 'equilibrado', name: 'Equilibrado', description: 'Padrão: pesquisador médio, implementador forte.',
    roles: { orquestrador: 'forte', pesquisador: 'médio', implementador: 'forte', revisor: 'médio' }, default: true },
  { id: 'maximo', name: 'Máximo', description: 'Tarefa crítica: todos os papéis na classe forte.',
    roles: { orquestrador: 'forte', pesquisador: 'forte', implementador: 'forte', revisor: 'forte' } },
];
let alive = false;
const lsGet = (k) => { try { return localStorage.getItem(k); } catch { return null; } };

export function renderOrchestration() {
  return `<div id="or-root">
    <div id="or-note"></div>
    <fieldset class="or-presets">
      <legend>Predefinição de subagentes</legend>
      <div id="or-radios" role="radiogroup" aria-label="Predefinição de subagentes"><div class="skel skel-chart"></div></div>
    </fieldset>
    <p id="or-sel" class="or-sel" role="status" aria-live="polite"></p>
    <details class="or-adv"><summary>Avançado</summary><div id="or-adv-body" class="or-adv-body"></div></details>
  </div>`;
}

export function unmountOrchestration() { alive = false; }

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
    return `custo: ${A.fmtUsd(v)} (${A.originLabel(lv && typeof lv === 'object' ? lv.origin : 'estimated')})`;
  }
  return 'custo: sem medição ainda';
}

export async function mountOrchestration(root) {
  alive = true;
  let presets = FALLBACK; let backend = true;
  try {
    const got = await A.listPresets();
    if (got.length) presets = got.map((p, i) => ({ ...p, id: String(p.id ?? p.name ?? i) }));
  } catch (e) { backend = A.isUnavailable(e) ? false : String(e.message || 'erro'); }
  if (!alive) return;
  const note = root.querySelector('#or-note');
  if (backend === false) {
    note.innerHTML = `<div class="callout callout-info"><div class="callout-title">Backend de orquestração ainda não disponível</div>
      <div class="callout-body">Mostrando as predefinições locais do desenho. A escolha fica salva só neste navegador até o backend existir.</div></div>`;
  } else if (backend !== true) {
    note.innerHTML = `<div class="callout callout-warn"><div class="callout-title">Falha ao ler predefinições</div><div class="callout-body">${esc(backend)}</div></div>`;
  }
  let chosen = lsGet(LS_PRESET);
  if (!presets.some((p) => p.id === chosen)) chosen = (presets.find((p) => p.is_default || p.default) || presets[1] || presets[0]).id;
  const radios = root.querySelector('#or-radios');
  radios.innerHTML = presets.map((p) => `<label class="or-opt" for="or-${esc(p.id)}">
      <input type="radio" name="preset" id="or-${esc(p.id)}" value="${esc(p.id)}"${p.id === chosen ? ' checked' : ''}
        aria-describedby="or-d-${esc(p.id)}">
      <span class="or-name">${esc(p.label || p.name || p.id)}</span>
      <span class="or-desc" id="or-d-${esc(p.id)}">${esc(p.description || '')}
        <span class="or-cost">${esc(costLine(p))}</span></span>
    </label>`).join('');
  const sel = root.querySelector('#or-sel');
  const announce = () => {
    const p = presets.find((x) => x.id === radios.querySelector('input:checked')?.value);
    sel.textContent = p ? `Selecionado: ${p.name || p.id} — ${costLine(p)}.` : '';
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
  const runsHtml = body.querySelector('#or-runs')?.innerHTML || 'Carregando…';
  body.innerHTML = `
    <h3>Papéis e classes de modelo — ${esc(p.name || p.id)}</h3>
    ${rows.length ? `<table class="data"><thead><tr><th scope="col">Papel</th><th scope="col">Classe</th></tr></thead>
      <tbody>${rows.map(([r, c]) => `<tr><th scope="row" class="rowhead">${esc(r)}</th><td>${esc(c)}</td></tr>`).join('')}</tbody></table>`
    : '<p class="muted">Sem detalhe de papéis.</p>'}
    <p class="or-note2">Classe sem modelo conectado cai para a classe acima e avisa. A predefinição Econômico só é rotulada “mais barata” depois do experimento medido.</p>
    <h3>Execuções recentes</h3><div id="or-runs" aria-live="polite">${runsHtml}</div>`;
}

async function loadRuns(root) {
  const box = () => root.querySelector('#or-runs');
  try {
    const runs = await A.listOrchRuns();
    if (!alive || !box()) return;
    box().innerHTML = runs.length
      ? `<ul class="or-runs">${runs.slice(0, 20).map((r) => `<li><code>${esc(r.id ?? r.run_id ?? '')}</code> ${esc(r.preset || '')} ${esc(r.status || '')}</li>`).join('')}</ul>`
      : '<p class="or-muted">Nenhuma execução registrada.</p>';
  } catch (e) {
    if (alive && box()) box().innerHTML = `<p class="or-muted">${esc(A.isUnavailable(e) ? 'Backend de orquestração ainda não disponível.' : e.message)}</p>`;
  }
}
