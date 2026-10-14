/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: CUSTO (#/compare/model-cost) — custo por query gravado nas runs; ausente = "indisponível" (ANA-200).
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum } from '../../format.js';
import { lab, pipelineRows } from '../../lab-data.js';
import { makeTab, na, vCost, vTok, pipeName, table } from './_shared.js';

function body() {
  const t = I18N.lab;
  const rs = pipelineRows(lab.stats);
  const any = rs.some((r) => r.cost !== null);
  return `
    ${any ? '' : `<p class="lab-note" role="note">${esc(t.noCostData)}</p>`}
    <div class="card u-dd9991">${table({
      caption: t.costTableCaption,
      cols: [
        { label: t.colPipeline, html: (r) => `<strong>${esc(pipeName(r.pipeline))}</strong>` },
        { label: t.colRuns, num: true, html: (r) => esc(fmtNum(r.runs)) },
        { label: t.colCostPerQuery, num: true, html: (r) => vCost(r.cost) },
        { label: t.colCostKind, html: (r) => (r.costKind ? esc(t.costKind[r.costKind]) : na()) },
        { label: t.colJudgeIn, num: true, html: (r) => vTok(r.judge) },
      ],
      rows: rs })}</div>`;
}
export const { render, mount, unmount } = makeTab({ title: 'costTitle', desc: 'costDesc', body });
