// components.js — reusable UI atoms. Every metric card shows TITLE/VALUE/UNIT/DELTA/CONTEXT.
import { esc, delta } from './format.js';

/** Metric glossary — powers the "?" tooltip on every metric. */
export const TIPS = {
  total_tokens: 'total_tokens_spent — tokens realmente gastos para responder a query (judge_tokens + context_tokens). Em runs antigas é calculado como jev_input_tokens + jev_output_tokens + context_tokens. É o único sinal honesto de custo; diferente do contexto final.',
  judge_tokens: 'judge_tokens — tokens pagos ao juiz JEV para filtrar candidatos. Custo que não aparece no contexto final.',
  token_amplification: 'token_amplification = total_tokens_spent / context_tokens. >1 significa que o pipeline gasta mais tokens do que entrega como contexto. >3 é sinalizado como anomalia.',
  prefilter: 'prefilter_* — corte determinístico top-K antes do juiz pago (custa zero tokens). Presente apenas em runs gravadas depois da adição do prefilter.',
  context_tokens: 'Tokens do contexto final entregue ao modelo (métrica context_tokens).',
  candidate_tokens_before_filter: 'Tokens de todos os candidatos recuperados, antes de qualquer filtro.',
  jev_input_tokens: 'Tokens enviados ao JEV para julgamento (custo extra do pipeline graphify_jev).',
  jev_output_tokens: 'Tokens devolvidos pelo JEV nas decisões de relevância.',
  total_latency_ms: 'Latência ponta a ponta da run (total_latency_ms).',
  retrieval_latency_ms: 'Tempo de recuperação de candidatos (FTS5 ou graphify).',
  graphify_latency_ms: 'Tempo da chamada ao graphify query.',
  jev_latency_ms: 'Tempo do julgamento JEV (uma requisição por lote).',
  filter_latency_ms: 'Tempo do roteamento/filtragem em código após o julgamento.',
  full_note_latency_ms: 'Tempo de carregar a nota completa dos sobreviventes.',
  context_build_latency_ms: 'Tempo do ModelContextBuilder montar o contexto final.',
  total_cost: 'Custo total observado da run (total_cost); fallback model_cost + jev_cost.',
  jev_cost: 'Custo das requisições ao JEV (USD).',
  documents_found: 'Documentos retornados pela recuperação antes de dedup.',
  documents_deduplicated: 'Documentos restantes após dedup por hash/(arquivo, seção).',
  documents_sent_to_model: 'Documentos que entraram no contexto final.',
  documents_kept: 'Candidatos com decisão KEEP pelo JEV.',
  documents_dropped: 'Candidatos com decisão DROP pelo JEV.',
  survivors: 'Candidatos sobreviventes ao filtro.',
  context_reduction: 'Redução do contexto: 1 − context_tokens / candidate_tokens_before_filter. Não mede tokens totais.',
  recall: 'expected_sources_found.recall — fração das fontes esperadas do dataset que apareceram no contexto.',
  efficiency: 'Eficiência = documents_sent_to_model / tokens totais × 1000. Documentos úteis por 1K tokens gastos.',
  cost_per_query: 'Custo total da run dividido pelo número de runs agregadas.',
  cost_per_1k: 'Custo dividido por tokens totais × 1000.',
  cache_hits: 'jev.cache_hits — acertos no cache do JEV. Zero com cache habilitado indica cache inoperante.',
};

export const help = (key, text) => {
  const tip = text || TIPS[key];
  return tip ? `<span class="help" tabindex="0" data-tip="${esc(tip)}">?</span>` : '';
};

/**
 * Metric card. Never renders a bare number.
 * @param {{title,value,unit,tipKey,tip,ref,lowerIsBetter,context,deltaText,deltaCls}} o
 */
export function metricCard(o) {
  let dText = o.deltaText, dCls = o.deltaCls;
  if (dText === undefined) {
    const d = delta(o.rawValue, o.ref, o.lowerIsBetter !== false);
    dText = d.text; dCls = d.cls;
  }
  return `<div class="metric">
    <div class="metric-title">${esc(o.title)}${help(o.tipKey, o.tip)}</div>
    <div class="metric-figure">
      <span class="metric-value">${o.value === undefined ? '—' : esc(o.value)}</span>
      <span class="metric-unit">${esc(o.unit || '')}</span>
    </div>
    <div class="metric-foot">
      <span class="delta ${esc(dCls || 'flat')}">${esc(dText || 'n/a')}</span>
      <span class="metric-context">${esc(o.context || '')}</span>
    </div>
  </div>`;
}

export const panel = (title, bodyHTML, sub = '', bodyClass = '') =>
  `<section class="panel">
    <div class="panel-head"><h2>${esc(title)}</h2>${sub ? `<span class="panel-sub">${esc(sub)}</span>` : ''}</div>
    <div class="panel-body ${bodyClass}">${bodyHTML}</div>
  </section>`;

export const emptyState = (title, detail) =>
  `<div class="state"><div class="state-title">${esc(title)}</div>${detail || ''}</div>`;

export const errorState = (msg) =>
  `<div class="state error"><div class="state-title">Falha ao carregar</div><code>${esc(msg)}</code></div>`;

/** Clearly-labelled "no data source wired" state, per spec — never fake numbers. */
export const notWiredState = (what) =>
  `<div class="state"><div class="state-title">Nenhuma fonte de dados conectada</div>
    <code>no data source wired: ${esc(what)}</code></div>`;

export const skeletonCards = (n = 4) =>
  `<div class="grid grid-kpi">${Array.from({ length: n }, () => '<div class="skel skel-card"></div>').join('')}</div>`;
export const skeletonChart = () => '<div class="skel skel-chart"></div>';
export const skeletonLines = (n = 5) =>
  Array.from({ length: n }, () => '<div class="skel skel-line"></div>').join('');

/** Segmented toggle. Values are set on data-val; handled by the page via delegation. */
export const segmented = (name, options, active) =>
  `<div class="seg" data-seg="${esc(name)}">${options.map(([v, l]) =>
    `<button type="button" data-val="${esc(v)}" class="${v === active ? 'active' : ''}">${esc(l)}</button>`).join('')}</div>`;

export function table(headers, rows, opts = {}) {
  if (!rows.length) return emptyState('Tabela vazia', opts.emptyDetail || 'nenhuma run corresponde ao filtro atual');
  return `<div class="table-scroll"><table class="data">
    <thead><tr>${headers.map((h) =>
      `<th class="${h.num ? 'num' : ''}">${esc(h.label)}${help(h.tipKey, h.tip)}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>`;
}
