/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * DECISION ENGINE — UI compartilhada das abas: loja de recursos, badges (estado/medição), estados de página.
 * Estados nunca só por cor: ícone + texto + title + texto para leitor de tela.
 */
import { icon } from '../icons.js';
import { I18N } from '../i18n.js';
import { esc } from '../format.js';
import { decStatus, decConfig, decMetrics, decEvaluation, decHistory } from '../anamnesia-api.js';
import { skeletonKpis, skeletonTable, loadingBlock } from '../components/skeleton.js';
import { emptyState } from '../components/empty-state.js';
import { STATE_ICON, errKind, pageState, lab } from './decision-data.js';

export const T = () => I18N.decision;

/** Recursos REST. status: loading | ok | offline | error (vazio é decidido por cada aba). */
export const store = {
  status: { status: 'loading', data: null, error: '' },
  config: { status: 'loading', data: null, error: '' },
  metrics: { status: 'loading', data: null, error: '' },
  evaluation: { status: 'loading', data: null, error: '' },
  history: { status: 'loading', data: null, error: '' },
  loaded: false,
};

const LOADERS = { status: decStatus, config: decConfig, metrics: decMetrics, evaluation: decEvaluation, history: () => decHistory(500) };
const errMsg = (e) => (e && (e.detail || e.message)) || String(e);

export async function loadAll() {
  const keys = Object.keys(LOADERS);
  keys.forEach((k) => { store[k] = { status: 'loading', data: null, error: '' }; });
  const res = await Promise.allSettled(keys.map((k) => LOADERS[k]()));
  res.forEach((r, i) => {
    const k = keys[i];
    store[k] = r.status === 'fulfilled' ? { status: 'ok', data: r.value, error: '' } : { status: errKind(r.reason), data: null, error: errMsg(r.reason) };
  });
  store.loaded = true;
}

/** Badge de estado KEEP/REVIEW/DROP/BLOCKED/FALLBACK/UNCERTAIN: ícone + texto + tooltip + texto SR. */
export function stateBadge(state, count) {
  const t = T();
  const s = t.state[state] ? state : 'UNCERTAIN';
  const tip = t.stateTip[s];
  const n = count === undefined ? '' : ` <span class="dec-state-n tabular">${esc(count)}</span>`;
  return `<span class="dec-state dec-state-${s.toLowerCase()}" title="${esc(tip)}">${icon(STATE_ICON[s], '', 12)}<span>${esc(t.state[s])}</span>${n}<span class="sr-only">: ${esc(tip)}</span></span>`;
}

/** Badge MEASURED/ESTIMATED/UNKNOWN com tooltip e texto — usa o componente .badge-origin existente. */
export function labelBadge(label) {
  const t = T();
  const l = t.label[label] ? label : 'UNKNOWN';
  const cls = l === 'MEASURED' ? 'measured' : (l === 'ESTIMATED' ? 'estimated' : 'unavailable');
  return `<span class="badge-origin badge-origin-${cls}" title="${esc(t.labelTip[l])}">${esc(t.label[l])}<span class="sr-only">: ${esc(t.labelTip[l])}</span></span>`;
}

/** Valor com origem: `format(v)` + badge; nulo => "não medido". */
export function valueWithLabel(x, format) {
  const v = lab(x);
  const txt = v.value === null ? `<span class="dec-na">${esc(T().ev.notRun)}</span>` : `<span class="tabular">${esc(format(v.value))}</span>`;
  return `${txt} ${labelBadge(v.label)}`;
}

function skeletonFor(kind) {
  return loadingBlock(kind === 'table' ? skeletonTable({ rows: 6, cols: 5 }) : skeletonKpis(4), T().loading);
}

/**
 * Porta de estados de uma aba: loading/offline/error => estado único; partial => aviso + conteúdo parcial; ok => conteúdo.
 * `needs` = recursos exigidos; `render()` deve tolerar `store[x].data === null` nos que falharam.
 */
export function gate(needs, render, kind = 'kpi') {
  const t = T();
  const sub = Object.fromEntries(needs.map((k) => [k, store[k]]));
  const s = pageState(sub);
  if (s === 'loading') return skeletonFor(kind);
  if (s === 'offline') {
    return emptyState({ title: t.offlineTitle, description: t.offlineDesc, variant: 'error', action: { label: t.retry, action: 'dec-reload', kind: 'secondary' } });
  }
  if (s === 'error') {
    const msg = needs.map((k) => store[k].error).find(Boolean) || '';
    return emptyState({ title: t.errorTitle, description: msg, variant: 'error', action: { label: t.retry, action: 'dec-reload', kind: 'secondary' } });
  }
  let banner = '';
  if (s === 'partial') {
    const list = needs.filter((k) => store[k].status !== 'ok').map((k) => t.src[k]).join(', ');
    banner = `<div class="callout-notice dec-partial" role="status"><span class="callout-notice-icon">${icon('alertTriangle', '', 16)}</span><div class="callout-notice-body"><strong>${esc(t.partialTitle)}</strong> ${esc(t.partialDesc.replace('{list}', list))}</div></div>`;
  }
  return banner + render();
}

/** Aviso permanente de honestidade (JEV padrão; Laya não superou o baseline). */
export function honestBanner() {
  const t = T();
  return `<div class="callout-notice dec-honest" role="note"><span class="callout-notice-icon">${icon('info', '', 16)}</span><div class="callout-notice-body"><span class="badge-seal badge-seal-experimental">${esc(t.experimental)}</span> ${esc(t.honest)}</div></div>`;
}

export const cell = (v, fmt) => (v === null || v === undefined ? `<span class="dec-na">${esc(T().ev.notRun)}</span>` : esc(fmt(v)));
