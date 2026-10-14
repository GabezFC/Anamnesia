/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: COMPARAÇÃO (#/compare/models) — por pipeline, dados reais (ANA-200).
 * Sem qualidade/p-valor/IC inventados: o que o benchmark.db não mede aparece como "indisponível".
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtPct } from '../../format.js';
import { lab, pipelineRows, recallByPipeline } from '../../lab-data.js';
import { makeTab, na, vTok, vMs, vCost, pipeName, table } from './_shared.js';

const dlt = (v, ref) => (v === null || ref === null || !ref ? null : (v - ref) / ref);
const dHtml = (d) => (d === null ? na() : esc(`${d > 0 ? '+' : ''}${fmtPct(d, 1)}`));

function body() {
  const t = I18N.lab;
  const rs = pipelineRows(lab.stats);
  const base = rs.find((r) => r.pipeline === 'baseline') || null;
  const recall = recallByPipeline(lab.runs);
  return `
    <p class="lab-note" role="note">${esc(t.noSignificance)}</p>
    <div class="card u-dd9991">${table({
      caption: t.modelsTableCaption,
      cols: [
        { label: t.colPipeline, html: (r) => `<strong>${esc(pipeName(r.pipeline))}</strong>` },
        { label: t.colRuns, num: true, html: (r) => esc(fmtNum(r.runs)) },
        { label: t.colCtx, num: true, html: (r) => vTok(r.ctx) },
        { label: t.colDeltaCtx, num: true, html: (r) => (r.pipeline === 'baseline' ? esc(t.ref) : dHtml(dlt(r.ctx, base?.ctx ?? null))) },
        { label: t.colLatMean, num: true, html: (r) => vMs(r.latMean) },
        { label: t.colDeltaLat, num: true, html: (r) => (r.pipeline === 'baseline' ? esc(t.ref) : dHtml(dlt(r.latMean, base?.latMean ?? null))) },
        { label: t.colRecall, num: true, html: (r) => { const x = recall.get(r.pipeline); return x ? esc(`${fmtPct(x.mean, 0)} (n=${x.n})`) : na(); } },
        { label: t.colCost, num: true, html: (r) => vCost(r.cost) },
      ],
      rows: rs })}</div>`;
}
export const { render, mount, unmount } = makeTab({ title: 'modelsTitle', desc: 'modelsDesc', body });
