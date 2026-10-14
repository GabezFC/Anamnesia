/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * COMPARE LAB: FLUXO DO PIPELINE (#/compare/pipeline) — estágios com latência média REAL gravada (ANA-200).
 */
import { I18N } from '../../i18n.js';
import { esc, fmtNum } from '../../format.js';
import { lab, STAGES, stageMeans } from '../../lab-data.js';
import { makeTab, vMs, pipeName, table } from './_shared.js';

let selected = null;

function body() {
  const t = I18N.lab;
  const means = stageMeans(lab.runs);
  if (!means.length) return `<p class="lab-note">${esc(t.noStageData)}</p>`;
  const cur = means.find((m) => m.pipeline === selected) || means.find((m) => m.pipeline === 'graphify_jev_opt') || means[0];
  selected = cur.pipeline;
  const stages = STAGES.filter((s) => cur.stages[s.id].n > 0);
  return `
    <label class="lab-field"><span>${esc(t.colPipeline)}</span>
      <select class="select-control" data-action="pipeline-select" aria-label="${esc(t.colPipeline)}">
        ${means.map((m) => `<option value="${esc(m.pipeline)}"${m.pipeline === cur.pipeline ? ' selected' : ''}>${esc(pipeName(m.pipeline))}</option>`).join('')}
      </select></label>
    <p class="lab-note" role="note">${esc(t.sampleNote.replace('{n}', String(cur.sample)))}</p>
    <ol class="pipeline-flow-board" aria-label="${esc(t.pipelineTitleFlow)}">
      ${stages.map((s, i) => `<li class="pipeline-node"><span class="node-step-num">${String(i + 1).padStart(2, '0')}</span>
        <span class="node-title">${esc(t.stage[s.id])}</span><span class="node-metric">${vMs(cur.stages[s.id].mean)}</span>
        <span class="lab-n">n=${esc(fmtNum(cur.stages[s.id].n))}</span></li>`).join('')}
    </ol>
    <div class="card u-b38a50">${table({
      caption: t.pipelineTableCaption,
      cols: [
        { label: t.colStage, html: (s) => esc(t.stage[s.id]) },
        { label: t.colMeanMs, num: true, html: (s) => vMs(cur.stages[s.id].mean) },
        { label: t.colSampleN, num: true, html: (s) => esc(fmtNum(cur.stages[s.id].n)) },
      ],
      rows: STAGES })}
      <p class="lab-note">${esc(t.totalLatency)}: ${vMs(cur.total)}</p></div>`;
}
const tab = makeTab({ title: 'pipelineTitle', desc: 'pipelineDesc', body });
export const render = tab.render;
export function mount(root) {
  tab.mount(root);
  const onChange = (e) => {
    const el = e.target.closest('[data-action="pipeline-select"]');
    if (!el) return;
    selected = el.value;
    root.innerHTML = tab.render();
  };
  root.addEventListener('change', onChange);
  const prev = root._tabCleanup;
  root._tabCleanup = () => { root.removeEventListener('change', onChange); prev?.(); };
}
export const unmount = tab.unmount;
