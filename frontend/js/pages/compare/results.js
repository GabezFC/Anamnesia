/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: RESULTADOS (#/compare/results) — cartões por pipeline com dados reais (ANA-200).
 * Sem selos "verificado/invalidado" fabricados: o único selo é a procedência (execuções locais).
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum, fmtPct } from '../../format.js';
import { lab, pipelineRows, recallByPipeline } from '../../lab-data.js';
import { makeTab, na, vTok, vMs, vCost, pipeName } from './_shared.js';

function body() {
  const t = I18N.lab;
  const rs = pipelineRows(lab.stats);
  const recall = recallByPipeline(lab.runs);
  const row = (k, v) => `<div class="u-38d71a"><span class="u-11d1ff">${esc(k)}</span><span class="font-mono tabular">${v}</span></div>`;
  return `<div class="grid-cards">${rs.map((r) => {
    const rc = recall.get(r.pipeline);
    return `<article class="card u-e6a81e" aria-label="${esc(pipeName(r.pipeline))}">
      <h3 class="u-ee7a26">${esc(pipeName(r.pipeline))}</h3>
      <p class="lab-note">${esc(t.resultsSeal)}</p>
      <div class="u-fdcb8a">
        ${row(t.colRuns, esc(fmtNum(r.runs)))}${row(t.colCtx, vTok(r.ctx))}${row(t.colLatP95, vMs(r.latP95))}
        ${row(t.colRecall, rc ? esc(`${fmtPct(rc.mean, 0)} (n=${rc.n})`) : na())}${row(t.colCost, vCost(r.cost))}
      </div></article>`;
  }).join('')}</div>`;
}
export const { render, mount, unmount } = makeTab({ title: 'resultsTitle', desc: 'resultsDesc', body });
