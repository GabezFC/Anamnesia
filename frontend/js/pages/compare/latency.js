/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: LATÊNCIA (#/compare/latency) — média por estágio sobre a amostra de runs reais (ANA-200).
 */
import { I18N } from '../../i18n.js';
import { esc, fmtMs, fmtNum } from '../../format.js';
import { createStackedBarChart } from '../../charts/chart-kit.js';
import { lab, STAGES, stageMeans } from '../../lab-data.js';
import { makeTab, vMs, pipeName, table } from './_shared.js';

let chart = null;
const COLORS = ['var(--chart-1)', 'var(--chart-5)', 'var(--chart-3)', 'var(--chart-2)', 'var(--chart-4)', 'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)'];

function body() {
  const t = I18N.lab;
  const ms = stageMeans(lab.runs);
  if (!ms.length) return `<p class="lab-note">${esc(t.noStageData)}</p>`;
  return `
    <p class="lab-note" role="note">${esc(t.sampleNoteAll)}</p>
    <div class="card u-e68317">
      <div class="card-header"><div><h3 class="card-title">${esc(t.latencyChartTitle)}</h3></div></div>
      <div id="latency-chart" class="u-990a1e"></div>
    </div>
    <div class="card u-b38a50">${table({
      caption: t.latencyTableCaption,
      cols: [
        { label: t.colPipeline, html: (r) => `<strong>${esc(pipeName(r.pipeline))}</strong> <span class="lab-n">n=${esc(fmtNum(r.sample))}</span>` },
        ...STAGES.map((s) => ({ label: t.stage[s.id], num: true, html: (r) => vMs(r.stages[s.id].mean) })),
        { label: t.colTotal, num: true, html: (r) => vMs(r.total) },
      ],
      rows: ms })}</div>`;
}
function after(root) {
  const el = root.querySelector('#latency-chart');
  const ms = stageMeans(lab.runs);
  if (!el || !ms.length) return;
  chart = createStackedBarChart(el, {
    categories: ms.map((r) => pipeName(r.pipeline)),
    series: STAGES.filter((s) => ms.some((r) => r.stages[s.id].mean !== null)).map((s, i) => ({
      label: I18N.lab.stage[s.id], color: COLORS[i % COLORS.length], values: ms.map((r) => r.stages[s.id].mean ?? 0),
    })),
    yFormatter: (v) => fmtMs(v), height: 240, ariaLabel: I18N.lab.latencyChartTitle,
  });
}
export const { render, mount, unmount } = makeTab({ title: 'latencyTitle', desc: 'latencyDesc', body, after, cleanup: () => { chart?.destroy?.(); chart = null; } });
