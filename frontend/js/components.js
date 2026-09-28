// components.js — reusable UI atoms.
// Rules enforced here:
//   * a metric with no data renders an explicit "Não medido" state, never a zero and never a guess;
//   * every panel can carry a provenance badge (Verificado / Experimental / Inválido);
//   * every table/chart/section has a loading, empty and error form.
import { esc, delta } from './format.js';
import { statusOf } from './provenance.js';

/** Metric glossary — powers the "?" tooltip on every metric. */
export const TIPS = {
  total_tokens: 'total_tokens_spent — tokens realmente gastos para responder a query (judge_tokens + context_tokens). Em runs antigas é calculado como jev_input_tokens + jev_output_tokens + context_tokens. É o único sinal honesto de custo; diferente do contexto final.',
  judge_tokens: 'judge_tokens — tokens pagos ao juiz JEV para filtrar candidatos. Custo que não aparece no contexto final.',
  token_amplification: 'token_amplification = total_tokens_spent / context_tokens. >1 significa que o pipeline gasta mais tokens do que entrega como contexto. >3 é sinalizado como anomalia.',
  saved_tokens: 'Soma das estimativas do backend para os estágios determinísticos (custo zero em tokens): prefilter_tokens_saved_estimate + dedup_near_tokens_saved_estimate + snippet_tokens_saved. São ESTIMATIVAS do backend, não medições de gasto.',
  prefilter: 'prefilter_* — corte determinístico top-K antes do juiz pago (custa zero tokens). Presente apenas em runs gravadas depois da adição do prefilter.',
  context_tokens: 'context_tokens — tokens do contexto final entregue ao modelo consumidor.',
  consumer_context: 'Tokens de contexto que o consumidor realmente recebe (context_tokens). É aqui que um "ganho" no juiz pode reaparecer como custo.',
  candidate_tokens_before_filter: 'Tokens de todos os candidatos recuperados, antes de qualquer filtro.',
  jev_input_tokens: 'Tokens enviados ao JEV para julgamento (custo extra dos pipelines com juiz).',
  jev_output_tokens: 'Tokens devolvidos pelo JEV nas decisões de relevância.',
  requests: 'jev.request_count — requisições HTTP ao juiz. Cada requisição tem custo fixo de overhead (~340 tokens medidos), então dividir trabalho em ondas só compensa se as ondas extras forem evitadas.',
  questions: 'jev_relevance_questions + jev_injection_questions — perguntas pagas efetivamente feitas ao juiz.',
  cache_hit_rate: 'cache_layers.hits / cache_layers.lookups (fallback: jev_cache_hits ÷ candidatos enviados ao juiz). Zero com cache habilitado indica cache inoperante.',
  early_stop_rate: 'Fração das runs com juiz que executaram UMA ÚNICA onda, isto é, não escalaram (jev_wave_sizes com 1 elemento). Derivado apenas de runs que registram ondas.',
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
  documents_deduplicated: 'Documentos removidos pelo dedup por hash/(arquivo, seção).',
  documents_sent_to_jev: 'Candidatos que chegaram ao juiz pago, depois do pré-filtro determinístico.',
  documents_sent_to_model: 'Documentos que entraram no contexto final.',
  documents_kept: 'Candidatos com decisão KEEP pelo JEV.',
  documents_review: 'Candidatos na banda REVIEW (roteamento definido por review_action).',
  documents_dropped: 'Candidatos com decisão DROP pelo JEV.',
  documents_quarantined: 'Candidatos com suspeita de injeção (QUARANTINE). Nunca sobrevivem.',
  documents_unjudged: 'O juiz foi perguntado e não respondeu (erro/timeout). Sobrevive só com failure_mode=fail_open.',
  documents_unselected: 'Nós decidimos NÃO pagar pelo julgamento (early stop / teto de K). Nunca sobrevive.',
  survivors: 'Candidatos sobreviventes ao filtro.',
  context_reduction: 'Redução do contexto: 1 − context_tokens / candidate_tokens_before_filter. NÃO mede tokens totais.',
  recall: 'expected_sources_found.recall — fração das fontes esperadas do dataset que apareceram no contexto. Só existe em runs de perguntas com expected_sources declaradas.',
  precision: 'expected_sources_found.found ÷ documents_sent_to_model — fração do contexto entregue que era, de fato, fonte esperada. Derivada; null quando qualquer um dos lados falta.',
  efficiency: 'Eficiência = documents_sent_to_model / tokens totais × 1000. Documentos úteis por 1K tokens gastos.',
  cost_per_query: 'Custo total da run dividido pelo número de runs agregadas.',
  cost_per_1k: 'Custo dividido por tokens totais × 1000.',
  cache_hits: 'jev.cache_hits — acertos no cache do JEV. Zero com cache habilitado indica cache inoperante.',
  opt_flags: 'opt_flags — mecanismos de otimização em vigor na run, conforme OptimizationConfig.active_flags(). Vazio significa a configuração de referência (baseline congelado).',
};

export const help = (key, text) => {
  const tip = text || TIPS[key];
  return tip ? `<span class="help" tabindex="0" role="note" aria-label="${esc(tip)}" data-tip="${esc(tip)}">?</span>` : '';
};

/** Provenance badge. `id` ∈ verified | experimental | invalid. */
export function provenanceBadge(id, extra = '') {
  const s = statusOf(id);
  return `<span class="prov prov-${esc(s.id)}" tabindex="0" data-tip="${esc(s.detail + (extra ? ` ${extra}` : ''))}">
    <span class="dot"></span>${esc(s.label)}</span>`;
}

/** The single place that decides how "no data" looks inside a metric card. */
export const NOT_MEASURED = 'Não medido';

/**
 * Metric card. Never renders a bare number and never renders 0 for missing data.
 * @param {{title,value,unit,tipKey,tip,rawValue,ref,lowerIsBetter,context,deltaText,deltaCls,prov}} o
 */
export function metricCard(o) {
  const missing = o.value === undefined || o.value === null || o.value === '—';
  let dText = o.deltaText; let dCls = o.deltaCls;
  if (dText === undefined) {
    const d = delta(o.rawValue, o.ref, o.lowerIsBetter !== false);
    dText = d.text; dCls = d.cls;
  }
  return `<div class="metric${missing ? ' metric-empty' : ''}">
    <div class="metric-title">${esc(o.title)}${help(o.tipKey, o.tip)}</div>
    <div class="metric-figure">
      ${missing
    ? `<span class="metric-none">${esc(NOT_MEASURED)}</span>`
    : `<span class="metric-value">${esc(o.value)}</span><span class="metric-unit">${esc(o.unit || '')}</span>`}
    </div>
    <div class="metric-foot">
      ${missing
    ? '<span class="delta flat">sem dado</span>'
    : `<span class="delta ${esc(dCls || 'flat')}">${esc(dText || 'n/a')}</span>`}
      <span class="metric-context">${esc(missing ? (o.missingHint || 'métrica ausente nas runs carregadas') : (o.context || ''))}</span>
    </div>
  </div>`;
}

/**
 * Panel. `opts` accepts { sub, bodyClass, prov, provNote, actions }.
 */
export function panel(title, bodyHTML, subOrOpts = '', bodyClass = '') {
  const o = typeof subOrOpts === 'string' ? { sub: subOrOpts, bodyClass } : (subOrOpts || {});
  const cls = o.bodyClass || bodyClass || '';
  return `<section class="panel">
    <div class="panel-head">
      <h2>${esc(title)}</h2>
      ${o.prov ? provenanceBadge(o.prov, o.provNote || '') : ''}
      ${o.sub ? `<span class="panel-sub">${esc(o.sub)}</span>` : ''}
    </div>
    <div class="panel-body ${esc(cls)}">${bodyHTML}</div>
  </section>`;
}

export const emptyState = (title, detail) =>
  `<div class="state"><div class="state-icon">◌</div><div class="state-title">${esc(title)}</div>${detail || ''}</div>`;

/** "Not yet measured" — the mandated empty state for an absent metric. */
export const notMeasuredState = (what, detail) =>
  `<div class="state"><div class="state-icon">◌</div>
    <div class="state-title">${esc(NOT_MEASURED)}</div>
    <p class="state-body">${detail || `Nenhuma run carregada contém <code>${esc(what)}</code>. Execute um benchmark para popular esta seção.`}</p>
  </div>`;

export const errorState = (msg, hint) =>
  `<div class="state error"><div class="state-icon">!</div>
    <div class="state-title">Falha ao carregar</div>
    <code>${esc(msg)}</code>
    ${hint ? `<p class="state-body">${hint}</p>` : ''}
  </div>`;

/** Clearly-labelled "no data source wired" state — never fake numbers. */
export const notWiredState = (what) =>
  `<div class="state"><div class="state-icon">⌁</div>
    <div class="state-title">Nenhuma fonte de dados conectada</div>
    <code>no data source wired: ${esc(what)}</code></div>`;

export const skeletonCards = (n = 4) =>
  `<div class="grid grid-kpi">${Array.from({ length: n }, () => '<div class="skel skel-card"></div>').join('')}</div>`;
export const skeletonChart = () => '<div class="skel skel-chart"></div>';
export const skeletonLines = (n = 5) =>
  Array.from({ length: n }, () => '<div class="skel skel-line"></div>').join('');
export const skeletonTable = (rows = 6) =>
  `<div class="skel-table">${Array.from({ length: rows }, () => '<div class="skel skel-line"></div>').join('')}</div>`;

/** Segmented toggle. Values are set on data-val; handled by the page via delegation. */
export const segmented = (name, options, active) =>
  `<div class="seg" data-seg="${esc(name)}" role="tablist">${options.map(([v, l]) =>
    `<button type="button" role="tab" aria-selected="${v === active}" data-val="${esc(v)}" class="${v === active ? 'active' : ''}">${esc(l)}</button>`).join('')}</div>`;

export function table(headers, rows, opts = {}) {
  if (!rows.length) {
    return emptyState(opts.emptyTitle || 'Tabela vazia',
      `<p class="state-body">${opts.emptyDetail || 'nenhuma run corresponde ao filtro atual'}</p>`);
  }
  return `<div class="table-scroll"><table class="data">
    <thead><tr>${headers.map((h) =>
    `<th class="${h.num ? 'num' : ''}">${esc(h.label)}${help(h.tipKey, h.tip)}</th>`).join('')}</tr></thead>
    <tbody>${rows.join('')}</tbody></table></div>`;
}

/** Key/value description list used by the configuration view. */
export function kvTable(pairs) {
  const rows = pairs.map(([k, v, cls]) =>
    `<tr><th class="rowhead">${esc(k)}</th><td class="${esc(cls || 'mono')}">${v === null || v === undefined || v === '' ? '<span class="muted">—</span>' : v}</td></tr>`);
  return `<div class="table-scroll"><table class="data kv"><tbody>${rows.join('')}</tbody></table></div>`;
}

/** Inline callout. tone ∈ info | warn | err | ok. */
export const callout = (tone, title, body) =>
  `<div class="callout callout-${esc(tone)}">
    <div class="callout-title">${esc(title)}</div>
    <div class="callout-body">${body}</div>
  </div>`;

/** Boolean flag chip, used by the configuration view. */
export const flagChip = (name, on) =>
  `<span class="chip ${on ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(name)}</span>`;
