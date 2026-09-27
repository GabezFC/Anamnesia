// charts.js — self-contained inline-SVG charts. No external library, no CDN.
// Every chart: responsive (re-renders on container resize), hover tooltips, legend, units.
import { esc } from './format.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (name, attrs = {}) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, String(v));
  return n;
};

/* ---- tooltip plumbing -------------------------------------------------- */
function tipFor(wrap) {
  let t = wrap.querySelector('.chart-tip');
  if (!t) { t = document.createElement('div'); t.className = 'chart-tip'; wrap.appendChild(t); }
  return t;
}
function bindTip(wrap, node, html) {
  const tip = tipFor(wrap);
  node.addEventListener('mousemove', (ev) => {
    const b = wrap.getBoundingClientRect();
    tip.innerHTML = html;
    tip.style.left = `${ev.clientX - b.left}px`;
    tip.style.top = `${ev.clientY - b.top - 8}px`;
    tip.style.opacity = '1';
  });
  node.addEventListener('mouseleave', () => { tip.style.opacity = '0'; });
}

/** niceMax: round an axis maximum up to a readable step. */
function niceMax(v) {
  if (!(v > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / (mag / 2)) * (mag / 2);
}

function legendHTML(series) {
  return `<div class="chart-legend">${series.map((s) =>
    `<span class="key"><i style="background:${esc(s.color)}"></i>${esc(s.label)}</span>`).join('')}</div>`;
}

function emptyInto(wrap, msg) {
  wrap.innerHTML = `<div class="state"><div class="state-title">Sem dados</div>${esc(msg)}</div>`;
}

/**
 * Re-render chart whenever the container is resized.
 * draw(wrap, width) must fully repaint wrap.
 */
function responsive(wrap, draw) {
  let last = 0;
  const run = () => {
    const w = Math.max(280, Math.floor(wrap.clientWidth || wrap.parentElement?.clientWidth || 600));
    if (Math.abs(w - last) < 6) return;
    last = w;
    draw(w);
  };
  if (wrap._chartRO) wrap._chartRO.disconnect();
  if (typeof ResizeObserver === 'function') {
    wrap._chartRO = new ResizeObserver(run);
    wrap._chartRO.observe(wrap);
  } else {
    window.addEventListener('resize', run);
  }
  run();
  // one deferred pass: at first paint clientWidth may still be 0
  requestAnimationFrame(run);
}

/* ======================================================================== */
/** Horizontal bar chart. rows: [{label, value, color?, tip?}] */
export function hBarChart(wrap, { rows, unit = '', fmt = String, emptyMsg = 'nenhuma série disponível' }) {
  if (!rows || !rows.length || rows.every((r) => !(r.value > 0))) return emptyInto(wrap, emptyMsg);
  responsive(wrap, (W) => {
    const padL = Math.min(180, Math.max(96, Math.round(W * 0.22)));
    const padR = 68, rowH = 30, padT = 8, padB = 22;
    const H = padT + rows.length * rowH + padB;
    const max = niceMax(Math.max(...rows.map((r) => r.value || 0)));
    const plotW = Math.max(40, W - padL - padR);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' });

    for (let i = 0; i <= 4; i++) {
      const x = padL + (plotW * i) / 4;
      svg.appendChild(el('line', { class: 'grid-line', x1: x, x2: x, y1: padT, y2: padT + rows.length * rowH }));
      const t = el('text', { class: 'axis', x, y: H - 6, 'text-anchor': 'middle' });
      t.textContent = fmt((max * i) / 4);
      svg.appendChild(t);
    }
    rows.forEach((r, i) => {
      const y = padT + i * rowH;
      const w = max ? Math.max(1, ((r.value || 0) / max) * plotW) : 1;
      const lbl = el('text', { class: 'axis', x: padL - 8, y: y + rowH / 2 + 3, 'text-anchor': 'end' });
      lbl.textContent = r.label;
      svg.appendChild(lbl);
      const bar = el('rect', {
        class: 'bar', x: padL, y: y + 5, width: w, height: rowH - 12,
        rx: 2, fill: r.color || 'var(--info)',
      });
      bindTip(wrap, bar, `<b>${esc(r.label)}</b><br>${esc(fmt(r.value))}${unit ? ` ${esc(unit)}` : ''}${r.tip ? `<br>${r.tip}` : ''}`);
      svg.appendChild(bar);
      const val = el('text', { class: 'axis-val', x: padL + w + 6, y: y + rowH / 2 + 3 });
      val.textContent = fmt(r.value);
      svg.appendChild(val);
    });
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    if (unit) wrap.insertAdjacentHTML('beforeend', `<div class="chart-legend"><span class="muted">Unidade: ${esc(unit)}</span></div>`);
  });
}

/* ======================================================================== */
/** Grouped vertical bar chart. groups:[{label}], series:[{label,color,values:[]}] */
export function groupedBarChart(wrap, { groups, series, unit = '', fmt = String, emptyMsg = 'nenhuma série disponível' }) {
  const any = series?.some((s) => s.values?.some((v) => v > 0));
  if (!groups?.length || !any) return emptyInto(wrap, emptyMsg);
  responsive(wrap, (W) => {
    const padL = 62, padR = 12, padT = 12, padB = 40, H = 260;
    const plotW = Math.max(60, W - padL - padR), plotH = H - padT - padB;
    const max = niceMax(Math.max(...series.flatMap((s) => s.values.map((v) => v || 0))));
    const gW = plotW / groups.length;
    const bW = Math.max(3, Math.min(34, (gW * 0.72) / series.length));
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' });

    for (let i = 0; i <= 4; i++) {
      const y = padT + plotH - (plotH * i) / 4;
      svg.appendChild(el('line', { class: 'grid-line', x1: padL, x2: padL + plotW, y1: y, y2: y }));
      const t = el('text', { class: 'axis', x: padL - 8, y: y + 3, 'text-anchor': 'end' });
      t.textContent = fmt((max * i) / 4);
      svg.appendChild(t);
    }
    groups.forEach((g, gi) => {
      const cx = padL + gi * gW + gW / 2;
      const start = cx - (bW * series.length) / 2;
      series.forEach((s, si) => {
        const v = s.values[gi] || 0;
        const h = max ? Math.max(v > 0 ? 1 : 0, (v / max) * plotH) : 0;
        if (h <= 0) return;
        const bar = el('rect', {
          class: 'bar', x: start + si * bW, y: padT + plotH - h,
          width: Math.max(2, bW - 2), height: h, rx: 2, fill: s.color,
        });
        bindTip(wrap, bar, `<b>${esc(g.label)}</b> · ${esc(s.label)}<br>${esc(fmt(v))}${unit ? ` ${esc(unit)}` : ''}`);
        svg.appendChild(bar);
      });
      const lbl = el('text', { class: 'axis', x: cx, y: H - 22, 'text-anchor': 'middle' });
      lbl.textContent = g.label;
      svg.appendChild(lbl);
    });
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    wrap.insertAdjacentHTML('beforeend', legendHTML(series) +
      (unit ? `<div class="chart-legend"><span class="muted">Unidade: ${esc(unit)}</span></div>` : ''));
  });
}

/* ======================================================================== */
/** Multi-series line chart. points: [{x:number(epoch s), y:number}] per series. */
export function lineChart(wrap, { series, unit = '', fmt = String, xFmt = String, emptyMsg = 'nenhuma série disponível' }) {
  const pts = series?.flatMap((s) => s.points || []) || [];
  if (pts.length < 1) return emptyInto(wrap, emptyMsg);
  responsive(wrap, (W) => {
    const padL = 62, padR = 14, padT = 12, padB = 38, H = 250;
    const plotW = Math.max(60, W - padL - padR), plotH = H - padT - padB;
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const yMax = niceMax(Math.max(...ys, 0)) || 1;
    const sx = (x) => padL + (x1 === x0 ? plotW / 2 : ((x - x0) / (x1 - x0)) * plotW);
    const sy = (y) => padT + plotH - (y / yMax) * plotH;
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' });

    for (let i = 0; i <= 4; i++) {
      const y = padT + plotH - (plotH * i) / 4;
      svg.appendChild(el('line', { class: 'grid-line', x1: padL, x2: padL + plotW, y1: y, y2: y }));
      const t = el('text', { class: 'axis', x: padL - 8, y: y + 3, 'text-anchor': 'end' });
      t.textContent = fmt((yMax * i) / 4);
      svg.appendChild(t);
    }
    [x0, (x0 + x1) / 2, x1].forEach((xv, i) => {
      const t = el('text', {
        class: 'axis', x: sx(xv), y: H - 20,
        'text-anchor': i === 0 ? 'start' : i === 2 ? 'end' : 'middle',
      });
      t.textContent = xFmt(xv);
      svg.appendChild(t);
    });
    for (const s of series) {
      const p = (s.points || []).slice().sort((a, b) => a.x - b.x);
      if (!p.length) continue;
      if (p.length > 1) {
        svg.appendChild(el('path', {
          d: p.map((q, i) => `${i ? 'L' : 'M'}${sx(q.x).toFixed(1)},${sy(q.y).toFixed(1)}`).join(' '),
          fill: 'none', stroke: s.color, 'stroke-width': 1.8, 'stroke-linejoin': 'round',
        }));
      }
      const showDots = p.length <= 90;
      for (const q of p) {
        const c = el('circle', { cx: sx(q.x), cy: sy(q.y), r: showDots ? 2.6 : 1.4, fill: s.color });
        bindTip(wrap, c, `<b>${esc(s.label)}</b><br>${esc(xFmt(q.x))}<br>${esc(fmt(q.y))}${unit ? ` ${esc(unit)}` : ''}${q.tip ? `<br>${q.tip}` : ''}`);
        svg.appendChild(c);
      }
    }
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    wrap.insertAdjacentHTML('beforeend', legendHTML(series) +
      (unit ? `<div class="chart-legend"><span class="muted">Unidade: ${esc(unit)}</span></div>` : ''));
  });
}

/** Stub for stacked-bar style token composition (total/context/in/out) reuse. */
export function stackedBarChart(wrap, opts) { return groupedBarChart(wrap, opts); }
