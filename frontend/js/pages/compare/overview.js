/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: VISÃO GERAL (#/compare/overview)
 * Dados REAIS de /benchmark/stats e /benchmark/runs (ANA-200/203). Métrica ausente = "indisponível".
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtDate, fmtPct } from '../../format.js';
import { createBarChart } from '../../charts/chart-kit.js';
import { lab, pipelineRows, recallByPipeline } from '../../lab-data.js';
import { makeTab, na, vTok, vMs, vCost, originBadge, pipeName, table } from './_shared.js';

let chart = null;
const rows = () => pipelineRows(lab.stats);

/** ANA-202: regressões (runs recentes vs. anteriores, por pipeline). API indisponível = "indisponível", não "ok". */
function alertsCard() {
  const t = I18N.lab;
  const a = lab.alerts;
  const head = `<div class="card-header"><div><h3 class="card-title">${esc(t.alertsTitle)}</h3></div></div>`;
  if (!a) return `<div class="card u-4eaf8e" role="region" aria-label="${esc(t.alertsTitle)}">${head}<p class="lab-note">${na()}</p></div>`;
  const body = a.alerts.length ? table({
    caption: t.alertsTitle,
    cols: [
      { label: t.colPipeline, html: (r) => esc(pipeName(r.pipeline)) },
      { label: t.colMetric, html: (r) => esc(t.alertMetrics[r.metric] || r.metric) },
      { label: t.colBaseline, num: true, html: (r) => esc(fmtNum(r.baseline)) },
      { label: t.colCurrent, num: true, html: (r) => esc(fmtNum(r.current)) },
      { label: t.colChange, num: true, html: (r) => esc(`+${fmtNum(r.change_pct, 1)}%`) },
      { label: t.colThreshold, num: true, html: (r) => esc(`${fmtNum(r.threshold_pct, 0)}%`) },
      { label: t.colSeverity, html: (r) => `<span class="chip chip-${r.severity === 'critical' ? 'danger' : 'warning'}">${esc(t.severity[r.severity] || r.severity)}</span>` },
    ], rows: a.alerts })
    : `<p class="lab-note">${esc(t.alertsNone)}</p>`;
  const insuff = (a.insufficient || []).length ? `<p class="lab-note">${esc(t.alertsInsufficient)}: ${esc(a.insufficient.map((i) => `${pipeName(i.pipeline)} (${i.runs}/${i.needed})`).join(', '))}</p>` : '';
  return `<div class="card u-4eaf8e" role="region" aria-label="${esc(t.alertsTitle)}">${head}${body}${insuff}<p class="lab-note">${esc(t.alertsRecallNote)}</p></div>`;
}

function body() {
  const t = I18N.lab;
  const rs = rows();
  const base = rs.find((r) => r.pipeline === 'baseline') || null;
  const best = [...rs].filter((r) => r.ctx !== null).sort((a, b) => a.ctx - b.ctx)[0] || null;
  const red = base && best && base.ctx && best.pipeline !== base.pipeline ? 1 - best.ctx / base.ctx : null;
  const recall = recallByPipeline(lab.runs);
  const last = lab.runs[0]?.created_at ?? null;
  const kpi = (label, v, html, sub) => `<div class="kpi-card"><div class="kpi-label"><span>${esc(label)}</span>${originBadge(v)}</div>
    <div class="kpi-value-row"><span class="kpi-value">${html}</span></div><span class="kpi-subtext">${sub}</span></div>`;
  return `
    <div class="costs-kpi-grid">
      ${kpi(t.kpiRuns, lab.stats.total_runs, esc(fmtNum(lab.stats.total_runs)), esc(t.kpiRunsSub))}
      ${kpi(t.kpiLast, last, last === null ? na() : esc(fmtDate(last)), esc(t.sourceLocal))}
      ${kpi(t.kpiReduction, red, red === null ? na() : esc(fmtPct(red, 1)), best ? esc(`${pipeName(best.pipeline)} ${t.vsBaseline}`) : esc(t.needsBaseline))}
      ${kpi(t.kpiRecall, recall.size ? 1 : null, recall.size ? esc([...recall].map(([p, r]) => `${pipeName(p)} ${fmtPct(r.mean, 0)}`).join(' · ')) : na(), esc(t.recallSub))}
    </div>
    ${alertsCard()}
    <div class="card u-4eaf8e">
      <div class="card-header"><div><h3 class="card-title">${esc(t.chartCtxTitle)}</h3><p class="card-subtitle">${esc(t.chartCtxSub)}</p></div></div>
      <div id="overview-ctx-chart" class="u-ef46fd"></div>
    </div>
    <div class="card u-b38a50">${table({
      caption: t.ovTableCaption,
      cols: [
        { label: t.colPipeline, html: (r) => `<strong>${esc(pipeName(r.pipeline))}</strong>` },
        { label: t.colRuns, num: true, html: (r) => esc(fmtNum(r.runs)) },
        { label: t.colCtx, num: true, html: (r) => vTok(r.ctx) },
        { label: t.colCand, num: true, html: (r) => vTok(r.cand) },
        { label: t.colLatMean, num: true, html: (r) => vMs(r.latMean) },
        { label: t.colLatP95, num: true, html: (r) => vMs(r.latP95) },
        { label: t.colCost, num: true, html: (r) => vCost(r.cost) + (r.costKind && t.costKind ? ` <small class="lab-note">(${esc(t.costKind[r.costKind] || r.costKind)})</small>` : '') },
      ],
      rows: rs })}</div>`;
}

function after(root) {
  const el = root.querySelector('#overview-ctx-chart');
  const rs = rows().filter((r) => r.ctx !== null);
  if (!el || !rs.length) return;
  chart = createBarChart(el, {
    categories: rs.map((r) => pipeName(r.pipeline)),
    series: [{ label: I18N.lab.colCtx, color: 'var(--chart-2)', values: rs.map((r) => r.ctx) }],
    yFormatter: (v) => fmtNum(v, 0), height: 230, ariaLabel: I18N.lab.chartCtxTitle,
  });
}
const tab = makeTab({ title: 'ovTitle', desc: 'ovDesc', body, after, cleanup: () => { chart?.destroy?.(); chart = null; } });
export const { render, mount, unmount } = tab;
