// pages-anacosts.js — Custos: per-call cost ledger of the Memory Gateway (GET /api/costs/*).
// Every figure carries its origin label (medido / estimado / indisponível); a missing value is shown as
// "indisponível", never as 0. Query text is only present when the server is not in metrics-only mode.
import { esc } from './format.js';
import * as A from './anamnesia-api.js';

let alive = false;
let S = null;
let lastFocus = null;

export function renderAnaCosts() {
  return `<div id="cs-root">
    <div class="page-toolbar" role="group" aria-label="Filtros de custo">
      <label for="cs-range">Período</label>
      <select id="cs-range">
        <option value="today">Hoje</option><option value="7d">7 dias</option>
        <option value="30d">30 dias</option><option value="all">Tudo</option>
      </select>
      <a id="cs-csv" class="cs-link" href="${esc(A.costCsvUrl('today'))}" download>Exportar CSV</a>
      <a class="cs-link toolbar-gap" href="#/dashboard">Benchmark avançado →</a>
    </div>
    <div id="cs-note"></div>
    <div id="cs-cards" class="grid grid-kpi" aria-live="polite"></div>
    <section class="panel" aria-labelledby="cs-bud-h"><div class="panel-head"><h2 id="cs-bud-h">Orçamento</h2>
      <span class="panel-sub">teto por dia/mês — só gasto medido conta</span></div>
      <div class="panel-body" id="cs-budget"></div></section>
    <section class="panel" aria-labelledby="cs-calls-h"><div class="panel-head"><h2 id="cs-calls-h">Chamadas</h2></div>
      <div class="panel-body"><div id="cs-metrics-only"></div>
        <div class="table-scroll"><table class="data" id="cs-table">
          <caption class="sr-only">Chamadas do Memory Gateway, mais recentes primeiro</caption>
          <thead><tr><th scope="col">Quando</th><th scope="col">Projeto</th><th scope="col">Agente</th>
            <th scope="col">Pipeline</th><th scope="col" class="num">Contexto (tok)</th>
            <th scope="col" class="num">Custo</th><th scope="col">Origem</th><th scope="col"><span class="sr-only">Detalhe</span></th></tr></thead>
          <tbody id="cs-rows"></tbody></table></div>
        <div class="cs-more"><button type="button" id="cs-more" hidden>Carregar mais</button>
          <span id="cs-count" class="cs-muted" aria-live="polite"></span></div>
      </div></section>
    <section class="panel" aria-labelledby="cs-rt-h"><div class="panel-head"><h2 id="cs-rt-h">Model Routing</h2>
      <span class="panel-sub">só o que foi medido em benchmark — execuções simuladas não contam</span></div>
      <div class="panel-body" id="cs-routing" aria-live="polite">Carregando…</div></section>
    <div id="cs-drawer-slot"></div>
  </div>`;
}

export function unmountAnaCosts() { alive = false; S = null; }

const dateTxt = (t) => (typeof t === 'number' ? new Date(t * 1000).toLocaleString('pt-BR') : '—');
const tok = (lv) => (A.lvValue(lv) === null ? 'indisponível' : A.lvValue(lv).toLocaleString('pt-BR'));
const originChip = (lv) => {
  const o = A.lvOrigin(lv);
  return `<span class="origin origin-${esc(o)}">${esc(A.originLabel(o))}</span>`;
};
const money = (lv) => (A.lvValue(lv) === null ? 'indisponível' : A.fmtUsd(A.lvValue(lv)));

export async function mountAnaCosts(root) {
  alive = true;
  S = { root, range: 'today', cursor: null, rows: [] };
  const sel = root.querySelector('#cs-range');
  sel.addEventListener('change', () => { S.range = sel.value; root.querySelector('#cs-csv').href = A.costCsvUrl(S.range); loadSummary(); });
  root.querySelector('#cs-more').addEventListener('click', () => loadCalls(false));
  root.querySelector('#cs-rows').addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-run]');
    if (b) openDrawer(b.dataset.run, b);
  });
  await loadSummary();
  await loadCalls(true);
  await loadRouting();
}

// ---- Model Routing (GET /api/costs/routing/summary): line comment on purpose (see tests/test_frontend_routing_section.py)
const pct = (lv) => (A.lvValue(lv) === null ? 'indisponível' : (A.lvValue(lv) * 100).toFixed(1) + '%');
const VERDICT_CLASS = { 'SIM': 'bud-ok', 'NÃO': 'bud-exceeded' };

const tierHead = (t) => '<th scope="col" class="num">Tier ' + esc(t) + '</th>';
const matrixRow = (d, label, matrix, tiers) => '<tr><th scope="row" class="rowhead">' + esc(label) + '</th>'
  + tiers.map((t) => '<td class="num">' + esc((matrix[d] || {})[t] || 0) + '</td>').join('') + '</tr>';
const stratRow = (k, s) => '<tr><th scope="row" class="rowhead">' + esc(k) + '</th><td class="num">' + esc(s.n) + '</td>'
  + '<td>' + esc(pct(s.success_rate)) + ' ' + originChip(s.success_rate) + '</td>'
  + '<td class="num">' + esc(money(s.cost_per_solved_task)) + ' ' + originChip(s.cost_per_solved_task) + '</td>'
  + '<td>' + esc(pct(s.escalation_rate)) + ' ' + originChip(s.escalation_rate) + '</td></tr>';

function routingMatrixHtml(matrix) {
  const tiers = [...new Set(Object.values(matrix).flatMap((m) => Object.keys(m || {})))].sort();
  if (!tiers.length) return '<p class="cs-muted">matriz indisponível</p>';
  const dtxt = { easy: 'fácil', medium: 'média', hard: 'difícil' };
  return '<div class="table-scroll"><table class="data" id="cs-rt-matrix">'
    + '<caption>Tarefas por dificuldade × tier escolhido (contagem medida)</caption>'
    + '<thead><tr><th scope="col">Dificuldade</th>' + tiers.map(tierHead).join('') + '</tr></thead><tbody>'
    + ['easy', 'medium', 'hard'].map((d) => matrixRow(d, dtxt[d], matrix, tiers)).join('') + '</tbody></table></div>';
}

function routingNoData(r, v) {
  const sim = Number(r && r.simulated_records) || 0;
  const extra = sim ? ' (' + sim + ' execução(ões) simulada(s) ignoradas)' : '';
  return '<p class="cs-muted"><b>O router paga o próprio custo? sem dados</b></p><p class="cs-muted">'
    + esc((v.reason || 'nenhuma execução de roteamento registrada') + extra) + '</p>';
}

export function routingHtml(r) {
  const v = (r && r.verdict) || {};
  if (!r || !r.has_data) return routingNoData(r, v);
  const verdict = ['SIM', 'NÃO'].includes(v.value) ? v.value : 'sem dados';
  const net = (r.break_even || {}).net_savings || null;
  const netTxt = net ? esc(money(net)) + ' líquido ' + originChip(net) : '';
  const strat = Object.entries(r.strategies || {}).map(([k, s]) => stratRow(k, s)).join('');
  const stratTable = strat ? '<div class="table-scroll"><table class="data" id="cs-rt-strat">'
    + '<caption>Estratégias (origem de cada número ao lado)</caption><thead><tr><th scope="col">Estratégia</th>'
    + '<th scope="col" class="num">N</th><th scope="col">Resolução</th><th scope="col" class="num">Custo/resolvida</th>'
    + '<th scope="col">Escalonamento</th></tr></thead><tbody>' + strat + '</tbody></table></div>' : '';
  return '<div class="metric"><div class="metric-title">O router paga o próprio custo?</div>'
    + '<div class="metric-figure"><span class="metric-value ' + esc(VERDICT_CLASS[verdict] || '') + '" id="cs-rt-verdict">' + esc(verdict) + '</span></div>'
    + '<div class="metric-foot">' + netTxt + '<span class="metric-context cs-muted">' + esc(v.reason || '') + '</span></div></div>'
    + '<div class="metric"><div class="metric-title">Taxa de escalonamento (DYNAMIC_ROUTER)</div>'
    + '<div class="metric-figure"><span class="metric-value">' + esc(pct(r.escalation_rate)) + '</span></div>'
    + '<div class="metric-foot">' + originChip(r.escalation_rate) + '</div></div>'
    + routingMatrixHtml(r.difficulty_tier_matrix || {}) + stratTable;
}

async function loadRouting() {
  const mine = S;
  const box = S.root.querySelector('#cs-routing');
  try {
    const r = await A.call('GET', '/api/costs/routing/summary');
    if (!alive || mine !== S) return;
    box.innerHTML = routingHtml(r);
  } catch (e) {
    if (!alive || mine !== S) return;
    box.innerHTML = '<p class="cs-muted">' + esc(A.isUnavailable(e) ? 'sem dados (rota /api/costs/routing indisponível)' : e.message) + '</p>';
  }
}

function unavailable(root, e) {
  const na = A.isUnavailable(e);
  root.querySelector('#cs-note').innerHTML = `<div class="callout callout-${na ? 'info' : 'err'}">
    <div class="callout-title">${na ? 'Backend de custos ainda não disponível' : 'Falha ao ler custos'}</div>
    <div class="callout-body">${esc(na ? 'A rota /api/costs não respondeu (404/offline). Nenhum valor é inventado.' : e.message)}</div></div>`;
}

function card(title, value, lv, foot) {
  return `<div class="metric"><div class="metric-title">${esc(title)}</div>
    <div class="metric-figure"><span class="metric-value">${esc(value)}</span></div>
    <div class="metric-foot">${lv ? originChip(lv) : ''}${foot ? `<span class="metric-context cs-muted">${esc(foot)}</span>` : ''}</div></div>`;
}

async function loadSummary() {
  const root = S.root;
  const mine = S;
  try {
    const s = await A.costSummary(S.range);
    if (!alive || mine !== S) return;
    root.querySelector('#cs-note').innerHTML = '';
    const hasPrice = A.lvValue(s.cost_usd) !== null;
    root.querySelector('#cs-cards').innerHTML = [
      card('Chamadas', Number(s.calls || 0).toLocaleString('pt-BR'), null, `${s.priced_calls ?? 0} com preço · ${s.cache_hits ?? 0} cache`),
      card('Custo do Memory Gateway', money(s.cost_usd), s.cost_usd, hasPrice ? '' : 'sem preço medido ainda'),
      card('Tokens de contexto', tok(s.context_tokens), s.context_tokens),
      card('Tokens do juiz', tok(s.judge_tokens), s.judge_tokens),
      card('Tokens gastos (total)', tok(s.total_tokens_spent), s.total_tokens_spent),
    ].join('');
    paintBudget(s.budget || {});
  } catch (e) {
    if (!alive || mine !== S) return;
    root.querySelector('#cs-cards').innerHTML = '';
    root.querySelector('#cs-budget').innerHTML = '<p class="cs-muted">indisponível</p>';
    unavailable(root, e);
  }
}

function budgetRow(label, period, b) {
  const spent = typeof b.spent_usd === 'number' ? b.spent_usd : null;
  const ceil = typeof b.ceiling_usd === 'number' ? b.ceiling_usd : null;
  const st = ['ok', 'warn', 'exceeded'].includes(b.status) ? b.status : 'ok';
  const pct = b.ratio === null || b.ratio === undefined ? null : Math.min(100, Math.round(b.ratio * 100));
  const stTxt = { ok: 'dentro do teto', warn: 'atenção: ≥ 80% do teto', exceeded: 'teto excedido' }[st];
  return `<div class="bud" data-period="${esc(period)}">
    <div class="bud-head"><b>${esc(label)}</b>
      <span>${spent === null ? 'gasto indisponível' : esc(A.fmtUsd(spent))} / ${ceil === null ? 'sem teto' : esc(A.fmtUsd(ceil))}</span>
      ${ceil === null ? '' : `<span class="bud-st bud-${esc(st)}">${esc(stTxt)}</span>`}</div>
    ${pct === null ? '' : `<div class="bud-bar bud-${esc(st)}" role="progressbar" aria-label="Orçamento ${esc(label)}"
        aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-valuetext="${pct}% — ${esc(stTxt)}"><span data-w="${pct}"></span></div>`}
    <form class="bud-form" data-period="${esc(period)}">
      <label for="bud-${esc(period)}">Teto ${esc(label.toLowerCase())} (US$)</label>
      <input id="bud-${esc(period)}" type="number" min="0" step="0.01" inputmode="decimal" value="${ceil === null ? '' : esc(ceil)}" placeholder="sem teto">
      <button type="submit">Salvar teto</button></form></div>`;
}

function paintBudget(b) {
  const box = S.root.querySelector('#cs-budget');
  box.innerHTML = `${budgetRow('Dia', 'day', b.day || {})}${budgetRow('Mês', 'month', b.month || {})}
    <div id="cs-bud-msg" role="status" aria-live="polite" class="cs-muted"></div>`;
  box.querySelectorAll('.bud-bar span').forEach((s) => { s.style.width = `${s.dataset.w}%`; });
  box.querySelectorAll('form.bud-form').forEach((f) => f.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const raw = f.querySelector('input').value.trim();
    const val = raw === '' ? null : Number(raw);
    const msg = box.querySelector('#cs-bud-msg');
    if (val !== null && (!Number.isFinite(val) || val < 0)) { msg.textContent = 'Valor inválido.'; return; }
    try { await A.putBudget(f.dataset.period, val); msg.textContent = 'Teto salvo.'; await loadSummary(); } catch (e) {
      msg.textContent = A.isUnavailable(e) ? 'Backend de custos ainda não disponível.' : `Falhou: ${e.message}`;
    }
  }));
}

async function loadCalls(reset) {
  const mine = S; const root = S.root;
  if (reset) { S.cursor = null; S.rows = []; root.querySelector('#cs-rows').innerHTML = ''; }
  const more = root.querySelector('#cs-more');
  more.disabled = true;
  try {
    const page = await A.costCalls({ cursor: S.cursor, limit: 25 });
    if (!alive || mine !== S) return;
    const items = Array.isArray(page.items) ? page.items : [];
    S.rows.push(...items);
    S.cursor = page.next_cursor || null;
    root.querySelector('#cs-metrics-only').innerHTML = page.metrics_only
      ? `<div class="callout callout-info"><div class="callout-title">Apenas métricas</div>
         <div class="callout-body">O servidor está em modo “apenas métricas”: o texto das consultas não é exibido nem exportado.</div></div>` : '';
    root.querySelector('#cs-rows').insertAdjacentHTML('beforeend', items.map(row).join(''));
    if (!S.rows.length) {
      root.querySelector('#cs-rows').innerHTML = '<tr><td colspan="8" class="cs-muted">Nenhuma chamada registrada ainda.</td></tr>';
    }
    root.querySelector('#cs-count').textContent = `${S.rows.length} chamada(s) carregada(s)`;
    more.hidden = !S.cursor;
  } catch (e) {
    if (!alive || mine !== S) return;
    root.querySelector('#cs-rows').innerHTML = `<tr><td colspan="8" class="cs-muted">${esc(A.isUnavailable(e) ? 'Backend de custos ainda não disponível.' : e.message)}</td></tr>`;
    more.hidden = true;
  } finally { more.disabled = false; }
}

function row(r) {
  return `<tr><td>${esc(dateTxt(r.created_at))}</td><td>${esc(r.project || '—')}</td><td>${esc(r.agent || r.client || '—')}</td>
    <td>${esc(r.pipeline || '—')}${r.error ? ' <span class="origin origin-unavailable">erro</span>' : ''}</td>
    <td class="num">${esc(tok(r.context_tokens))}</td><td class="num">${esc(money(r.cost_usd))}</td>
    <td>${originChip(r.cost_usd)}</td>
    <td><button type="button" data-run="${esc(r.run_id)}" aria-label="Detalhes da chamada ${esc(String(r.run_id).slice(0, 8))}">Detalhe</button></td></tr>`;
}

/* ---- detail drawer -------------------------------------------------------- */
function closeDrawer() {
  const slot = S?.root.querySelector('#cs-drawer-slot');
  if (slot) slot.innerHTML = '';
  if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
}

async function openDrawer(runId, trigger) {
  lastFocus = trigger;
  const slot = S.root.querySelector('#cs-drawer-slot');
  slot.innerHTML = `<div class="drawer-scrim"><aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="dr-h" tabindex="-1">
    <div class="drawer-head"><h2 id="dr-h">Chamada ${esc(String(runId).slice(0, 12))}</h2>
      <button type="button" id="dr-close" aria-label="Fechar detalhes">×</button></div>
    <div class="drawer-body" id="dr-body">Carregando…</div></aside></div>`;
  const dlg = slot.querySelector('.drawer');
  slot.querySelector('#dr-close').addEventListener('click', closeDrawer);
  slot.querySelector('.drawer-scrim').addEventListener('mousedown', (ev) => { if (ev.target.classList.contains('drawer-scrim')) closeDrawer(); });
  dlg.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') { ev.preventDefault(); closeDrawer(); }
    if (ev.key === 'Tab') {                                            // focus trap
      const f = [...dlg.querySelectorAll('button, [href], input, [tabindex="0"]')].filter((x) => !x.disabled);
      if (!f.length) return;
      const first = f[0]; const last = f.at(-1);
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  });
  slot.querySelector('#dr-close').focus();
  const body = slot.querySelector('#dr-body');
  try {
    const d = await A.costCall(runId);
    if (!alive || !body.isConnected) return;
    const fig = (label, lv, fmt) => `<tr><th scope="row" class="rowhead">${esc(label)}</th><td>${esc(fmt(lv))}</td><td>${originChip(lv)}</td></tr>`;
    const sources = Array.isArray(d.sources) ? d.sources : [];
    body.innerHTML = `
      <dl class="dr-meta">
        <dt>Quando</dt><dd>${esc(dateTxt(d.created_at))}</dd>
        <dt>Projeto</dt><dd>${esc(d.project || '—')}</dd>
        <dt>Pipeline</dt><dd>${esc(d.pipeline || '—')} · ${esc(d.mode || '')}</dd>
        <dt>Modelo</dt><dd>${esc(d.model || '—')}${d.jev_model ? ` · juiz ${esc(d.jev_model)}` : ''}</dd>
        <dt>Preço</dt><dd>${esc(d.price_status || '—')}</dd>
      </dl>
      <table class="data"><thead><tr><th scope="col">Medida</th><th scope="col">Valor</th><th scope="col">Origem</th></tr></thead><tbody>
        ${fig('Tokens candidatos', d.candidate_tokens, tok)}${fig('Tokens de contexto', d.context_tokens, tok)}
        ${fig('Tokens do juiz', d.judge_tokens, tok)}${fig('Tokens gastos', d.total_tokens_spent, tok)}
        ${fig('Custo', d.cost_usd, money)}
        ${fig('Latência', d.latency_ms, (lv) => (A.lvValue(lv) === null ? 'indisponível' : `${Math.round(A.lvValue(lv))} ms`))}
      </tbody></table>
      ${d.metrics_only ? '<p class="cs-muted">Apenas métricas: consulta, contexto e resposta não são expostos.</p>'
    : `<h3>Consulta</h3><pre tabindex="0">${esc(d.query ?? '')}</pre>`}
      ${sources.length ? `<h3>Fontes (${sources.length})</h3><ul>${sources.slice(0, 50).map((s) => `<li><code>${esc(typeof s === 'object' && s ? (s.file || s.path || s.title || JSON.stringify(s)) : s)}</code></li>`).join('')}</ul>` : ''}`;
  } catch (e) {
    body.innerHTML = `<p class="ws-msg-err">${esc(A.isUnavailable(e) ? 'Backend de custos ainda não disponível.' : e.message)}</p>`;
  }
}
