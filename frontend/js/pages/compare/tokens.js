/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: TOKENS (#/compare/tokens) — candidatos vs. contexto entregue, dados reais (ANA-200).
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum } from '../../format.js';
import { createBarChart } from '../../charts/chart-kit.js';
import { lab, pipelineRows } from '../../lab-data.js';
import { makeTab, vTok, vPct, pipeName, table } from './_shared.js';

let chart = null;
const withData = () => pipelineRows(lab.stats).filter((r) => r.cand !== null || r.ctx !== null);

function body() {
  const t = I18N.lab;
  return `
    <div class="card u-e68317">
      <div class="card-header"><div><h3 class="card-title">${esc(t.tokensChartTitle)}</h3><p class="card-subtitle">${esc(t.tokensChartSub)}</p></div></div>
      <div id="tokens-chart" class="u-b7ff78"></div>
    </div>
    <div class="card u-b38a50">${table({
      caption: t.tokensTableCaption,
      cols: [
        { label: t.colPipeline, html: (r) => `<strong>${esc(pipeName(r.pipeline))}</strong>` },
        { label: t.colCand, num: true, html: (r) => vTok(r.cand) },
        { label: t.colCtx, num: true, html: (r) => vTok(r.ctx) },
        { label: t.colWasted, num: true, html: (r) => vTok(r.wasted) },
        { label: t.colReduction, num: true, html: (r) => vPct(r.reduction) },
        { label: t.colJudgeIn, num: true, html: (r) => vTok(r.judge) },
      ],
      rows: withData() })}</div>`;
}
function after(root) {
  const el = root.querySelector('#tokens-chart');
  const rs = withData();
  if (!el || !rs.length) return;
  chart = createBarChart(el, {
    categories: rs.map((r) => pipeName(r.pipeline)),
    series: [
      { label: I18N.lab.colCand, color: 'var(--chart-8)', values: rs.map((r) => r.cand ?? 0) },
      { label: I18N.lab.colCtx, color: 'var(--chart-2)', values: rs.map((r) => r.ctx ?? 0) },
    ],
    yFormatter: (v) => fmtNum(v, 0), height: 250, ariaLabel: I18N.lab.tokensChartTitle,
  });
}
export const { render, mount, unmount } = makeTab({ title: 'tokensTitle', desc: 'tokensDesc', body, after, cleanup: () => { chart?.destroy?.(); chart = null; } });
