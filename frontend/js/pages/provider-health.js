/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * CONEXÕES — saúde dos provedores (ANA-210). Tabela por provedor com erro% e latência das últimas N chamadas
 * REAIS do livro de custos (GET /api/providers/health). Sem probe e sem chamada paga. Atualiza por SSE
 * (/api/costs/stream, com debounce): cada nova chamada gravada refaz a leitura.
 */
import { I18N } from '../i18n.js';
import { esc, fmtNum, fmtPct, fmtMs, fmtDate, num } from '../format.js';
import { providersHealth, openCostStream, isUnavailable } from '../anamnesia-api.js';
import { emptyState } from '../components/empty-state.js';
import { loadingBlock, skeletonTable } from '../components/skeleton.js';

const LAST_N = 100;
const S = { status: 'idle', data: null, error: '', live: 'offline' };

const na = () => `<span class="lab-na">${esc(I18N.app.unavailable)}</span>`;

/** Classe de severidade pela taxa de erro (limiares fixos e documentados na UI). */
export const errClass = (rate) => (rate === null ? 'neutral' : rate >= 0.25 ? 'danger' : rate >= 0.05 ? 'warning' : 'success');

export function healthTable(data) {
  const t = I18N.connections;
  const rows = data?.providers || [];
  if (!rows.length) return emptyState({ title: t.healthEmpty, description: t.healthEmptyDesc, variant: 'data', compact: true });
  const keyCell = (r) => (r.key_present === true ? esc(t.healthKeyYes) : r.key_present === false ? esc(t.healthKeyNo) : na());
  return `<div class="table-container" tabindex="0" role="region" aria-label="${esc(t.healthTitle)}"><table class="table">
    <caption class="sr-only">${esc(t.healthTitle)}</caption>
    <thead><tr><th scope="col">${esc(t.healthProvider)}</th><th scope="col" class="num-col">${esc(t.healthCalls)}</th><th scope="col" class="num-col">${esc(t.healthErrors)}</th>
      <th scope="col" class="num-col">${esc(t.healthErrRate)}</th><th scope="col" class="num-col">p50</th><th scope="col" class="num-col">p95</th><th scope="col">${esc(t.healthLast)}</th><th scope="col">${esc(t.healthKey)}</th></tr></thead>
    <tbody>${rows.map((r) => `<tr>
      <td><strong>${esc(r.provider)}</strong></td><td class="num-col tabular">${esc(fmtNum(r.calls))}</td><td class="num-col tabular">${esc(fmtNum(r.errors))}</td>
      <td class="num-col tabular"><span class="chip chip-${errClass(num(r.error_rate))}">${num(r.error_rate) === null ? na() : esc(fmtPct(r.error_rate, 1))}</span></td>
      <td class="num-col tabular">${num(r.latency_p50_ms) === null ? na() : esc(fmtMs(r.latency_p50_ms))}</td><td class="num-col tabular">${num(r.latency_p95_ms) === null ? na() : esc(fmtMs(r.latency_p95_ms))}</td>
      <td class="tabular">${num(r.last_call_at) === null ? na() : esc(fmtDate(r.last_call_at))}</td><td>${keyCell(r)}</td></tr>`).join('')}</tbody></table></div>
    ${(data.agents || []).length ? `<p class="lab-note">${esc(t.healthAgents)}: ${data.agents.map((a) => `<span class="chip chip-${a.available ? 'success' : 'neutral'}">${esc(a.agent)} · ${esc(a.available ? t.healthAvailable : (a.reason || t.healthUnavailable2))}</span>`).join(' ')}</p>` : ''}
    <p class="lab-note">${esc(t.healthNote.replace('{n}', String(data.window ?? LAST_N)))}</p>`;
}

function body() {
  const t = I18N.connections;
  if (S.status === 'loading' || S.status === 'idle') return loadingBlock(skeletonTable({ rows: 3, cols: 6 }), I18N.app.loading);
  if (S.status === 'error') return emptyState({ title: t.healthUnavailable, description: S.error, variant: 'error', compact: true, action: { label: I18N.app.errorRetry, action: 'health-reload', kind: 'secondary' } });
  return healthTable(S.data);
}

export function healthSection() {
  const t = I18N.connections;
  return `<section class="connections-section" aria-labelledby="prov-health-title">
    <div class="section-title-wrap"><h2 class="section-title" id="prov-health-title">${esc(t.healthTitle)}</h2>
      <span class="chip chip-${S.live === 'live' ? 'success' : 'neutral'}" data-bind="health-live" role="status">${esc(S.live === 'live' ? t.healthLive : t.healthPolling)}</span>
      <button type="button" class="btn btn-ghost btn-sm" data-action="health-reload">${esc(I18N.costs?.refresh || I18N.app.errorRetry)}</button></div>
    <div data-bind="prov-health" aria-live="polite">${body()}</div></section>`;
}

async function load(root, quiet = false) {
  if (!quiet) { S.status = 'loading'; paint(root); }
  try { S.data = await providersHealth(LAST_N); S.status = 'ok'; }
  catch (e) { S.status = 'error'; S.error = isUnavailable(e) ? I18N.app.backendUnavailableDesc : (e && e.message) || String(e); }
  if (root.isConnected) paint(root);
}
function paint(root) {
  const el = root.querySelector('[data-bind="prov-health"]'); if (el) el.innerHTML = body();
  const lv = root.querySelector('[data-bind="health-live"]');
  if (lv) { lv.textContent = S.live === 'live' ? I18N.connections.healthLive : I18N.connections.healthPolling; lv.className = `chip chip-${S.live === 'live' ? 'success' : 'neutral'}`; }
}

/** Liga a seção: leitura inicial + refresh por SSE (debounce 1,5 s). Devolve a função de limpeza. */
export function mountHealth(root) {
  let timer = null;
  const onClick = (e) => { if (e.target.closest('[data-action="health-reload"]')) load(root); };
  root.addEventListener('click', onClick);
  load(root);
  const stop = openCostStream(() => { clearTimeout(timer); timer = setTimeout(() => load(root, true), 1500); }, (st) => { S.live = st === 'live' ? 'live' : 'offline'; paint(root); });
  return () => { root.removeEventListener('click', onClick); clearTimeout(timer); stop(); };
}
