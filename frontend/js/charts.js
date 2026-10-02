// charts.js — self-contained inline-SVG charts. No external library, no CDN.
// Every chart: responsive (re-renders on container resize), hover tooltips, legend, units,
// and an explicit "Não medido" state when the series carries no real values.
import { esc } from './format.js';
// niceMax (axis rounding), splitSegments (gap handling), valueScale (linear/log) and the
// dash/marker cycles that keep colour from being the only signal all live in series.js.
import { dashFor, markerFor, niceMax, splitSegments, valueScale } from './series.js';

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
  const move = (ev) => {
    const b = wrap.getBoundingClientRect();
    tip.innerHTML = html;
    // Clamp inside the wrapper so the tooltip never escapes the panel.
    const x = Math.min(Math.max(ev.clientX - b.left, 60), Math.max(60, b.width - 60));
    tip.style.left = `${x}px`;
    tip.style.top = `${Math.max(24, ev.clientY - b.top - 8)}px`;
    tip.style.opacity = '1';
  };
  node.addEventListener('mousemove', move);
  node.addEventListener('mouseleave', () => { tip.style.opacity = '0'; });
}

/** niceMax: round an axis maximum up to a readable step. (lives in series.js) */

function legendHTML(series) {
  return `<div class="chart-legend">${series.map((s) =>
    `<span class="key"><i style="background:${esc(s.color)}"></i>${esc(s.label)}</span>`).join('')}</div>`;
}

/** The mandated empty state inside a chart slot: explicit, never a blank axis. */
function emptyInto(wrap, msg) {
  disconnect(wrap);
  wrap.innerHTML = `<div class="state state-compact">
    <div class="state-icon">◌</div>
    <div class="state-title">Não medido</div>
    <p class="state-body">${esc(msg)}</p></div>`;
}

function disconnect(wrap) {
  if (wrap._chartRO) { wrap._chartRO.disconnect(); wrap._chartRO = null; }
  if (wrap._chartWin) { window.removeEventListener('resize', wrap._chartWin); wrap._chartWin = null; }
}

/** Disconnect every chart observer under `root`. Called before a page is replaced. */
export function destroyCharts(root) {
  (root || document).querySelectorAll('.chart-wrap').forEach(disconnect);
}

/**
 * Re-render chart whenever the container is resized.
 * draw(width) must fully repaint wrap.
 * wrap._chartRedraw(force) repaints without waiting for a resize; the line chart
 * uses it when the "ver tabela" toggle changes what the panel shows.
 */
function responsive(wrap, draw) {
  let last = 0;
  const run = (force) => {
    if (!wrap.isConnected) { disconnect(wrap); return; }
    const w = Math.max(280, Math.floor(wrap.clientWidth || wrap.parentElement?.clientWidth || 600));
    if (!force && Math.abs(w - last) < 6) return;
    last = w;
    draw(w);
  };
  disconnect(wrap);
  wrap._chartRedraw = run;
  if (typeof ResizeObserver === 'function') {
    wrap._chartRO = new ResizeObserver(() => run(false));
    wrap._chartRO.observe(wrap);
  } else {
    wrap._chartWin = () => run(false);
    window.addEventListener('resize', wrap._chartWin);
  }
  run();
  // one deferred pass: at first paint clientWidth may still be 0
  requestAnimationFrame(run);
}

/* ======================================================================== */
/** Horizontal bar chart. rows: [{label, value, color?, tip?}] */
export function hBarChart(wrap, { rows, unit = '', fmt = String, emptyMsg = 'nenhuma série disponível' }) {
  const usable = (rows || []).filter((r) => typeof r.value === 'number' && Number.isFinite(r.value));
  if (!usable.length || usable.every((r) => !(r.value > 0))) return emptyInto(wrap, emptyMsg);
  responsive(wrap, (W) => {
    const padL = Math.min(190, Math.max(96, Math.round(W * 0.24)));
    const padR = 72; const rowH = 32; const padT = 8; const padB = 24;
    const H = padT + usable.length * rowH + padB;
    const max = niceMax(Math.max(...usable.map((r) => r.value || 0)));
    const plotW = Math.max(40, W - padL - padR);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' });

    for (let i = 0; i <= 4; i++) {
      const x = padL + (plotW * i) / 4;
      svg.appendChild(el('line', { class: 'grid-line', x1: x, x2: x, y1: padT, y2: padT + usable.length * rowH }));
      const t = el('text', { class: 'axis', x, y: H - 6, 'text-anchor': 'middle' });
      t.textContent = fmt((max * i) / 4);
      svg.appendChild(t);
    }
    usable.forEach((r, i) => {
      const y = padT + i * rowH;
      const w = max ? Math.max(1, ((r.value || 0) / max) * plotW) : 1;
      const lbl = el('text', { class: 'axis', x: padL - 10, y: y + rowH / 2 + 3, 'text-anchor': 'end' });
      lbl.textContent = r.label;
      svg.appendChild(lbl);
      const bar = el('rect', {
        class: 'bar', x: padL, y: y + 6, width: w, height: rowH - 14,
        rx: 2, fill: r.color || 'var(--info)',
      });
      bindTip(wrap, bar, `<b>${esc(r.label)}</b><br>${esc(fmt(r.value))}${unit ? ` ${esc(unit)}` : ''}${r.tip ? `<br>${r.tip}` : ''}`);
      svg.appendChild(bar);
      const val = el('text', { class: 'axis-val', x: padL + w + 8, y: y + rowH / 2 + 3 });
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
  const any = series?.some((s) => s.values?.some((v) => typeof v === 'number' && v > 0));
  if (!groups?.length || !any) return emptyInto(wrap, emptyMsg);
  responsive(wrap, (W) => {
    const padL = 64; const padR = 12; const padT = 12; const padB = 44; const H = 268;
    const plotW = Math.max(60, W - padL - padR); const plotH = H - padT - padB;
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
      const lbl = el('text', { class: 'axis', x: cx, y: H - 24, 'text-anchor': 'middle' });
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
/**
 * Real stacked horizontal bars. rows:[{label, parts:[{label,value,color}]}].
 * Used for token composition (judge vs context), where the TOTAL is the point.
 */
export function stackedBarChart(wrap, { rows, unit = '', fmt = String, emptyMsg = 'nenhuma série disponível' }) {
  const usable = (rows || []).map((r) => ({
    ...r,
    parts: (r.parts || []).filter((p) => typeof p.value === 'number' && p.value > 0),
  })).filter((r) => r.parts.length);
  if (!usable.length) return emptyInto(wrap, emptyMsg);
  const legend = [];
  for (const r of usable) {
    for (const p of r.parts) if (!legend.some((l) => l.label === p.label)) legend.push({ label: p.label, color: p.color });
  }
  responsive(wrap, (W) => {
    const padL = Math.min(190, Math.max(100, Math.round(W * 0.24)));
    const padR = 80; const rowH = 34; const padT = 8; const padB = 24;
    const H = padT + usable.length * rowH + padB;
    const totals = usable.map((r) => r.parts.reduce((a, p) => a + p.value, 0));
    const max = niceMax(Math.max(...totals));
    const plotW = Math.max(40, W - padL - padR);
    const svg = el('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' });

    for (let i = 0; i <= 4; i++) {
      const x = padL + (plotW * i) / 4;
      svg.appendChild(el('line', { class: 'grid-line', x1: x, x2: x, y1: padT, y2: padT + usable.length * rowH }));
      const t = el('text', { class: 'axis', x, y: H - 6, 'text-anchor': 'middle' });
      t.textContent = fmt((max * i) / 4);
      svg.appendChild(t);
    }
    usable.forEach((r, i) => {
      const y = padT + i * rowH;
      const lbl = el('text', { class: 'axis', x: padL - 10, y: y + rowH / 2 + 3, 'text-anchor': 'end' });
      lbl.textContent = r.label;
      svg.appendChild(lbl);
      let x = padL;
      for (const p of r.parts) {
        const w = Math.max(1, (p.value / max) * plotW);
        const seg = el('rect', { class: 'bar', x, y: y + 7, width: w, height: rowH - 16, fill: p.color });
        bindTip(wrap, seg, `<b>${esc(r.label)}</b> · ${esc(p.label)}<br>${esc(fmt(p.value))}${unit ? ` ${esc(unit)}` : ''}`
          + `<br><span class="muted">total ${esc(fmt(totals[i]))}</span>`);
        svg.appendChild(seg);
        x += w;
      }
      const val = el('text', { class: 'axis-val', x: x + 8, y: y + rowH / 2 + 3 });
      val.textContent = fmt(totals[i]);
      svg.appendChild(val);
    });
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    wrap.insertAdjacentHTML('beforeend', legendHTML(legend) +
      (unit ? `<div class="chart-legend"><span class="muted">Unidade: ${esc(unit)}</span></div>` : ''));
  });
}

/* ======================================================================== */
/** Marker shape as a DOM node — the same shape is used on the plot, the legend and the table. */
function markerNode(kind, cx, cy, color, r) {
  if (kind === 'square') return el('rect', { fill: color, x: cx - r, y: cy - r, width: r * 2, height: r * 2 });
  if (kind === 'triangle') {
    return el('polygon', { fill: color, points: `${cx},${cy - r - 0.5} ${cx + r + 0.5},${cy + r} ${cx - r - 0.5},${cy + r}` });
  }
  if (kind === 'diamond') {
    return el('polygon', { fill: color, points: `${cx},${cy - r - 0.6} ${cx + r + 0.6},${cy} ${cx},${cy + r + 0.6} ${cx - r - 0.6},${cy}` });
  }
  return el('circle', { fill: color, cx, cy, r });
}

/** The same marker as inline markup, for the legend key and the table cells. */
function markerSVG(kind, color, r = 3) {
  const fill = esc(color);
  if (kind === 'square') return `<rect x="${13 - r}" y="${6 - r}" width="${r * 2}" height="${r * 2}" fill="${fill}"/>`;
  if (kind === 'triangle') {
    return `<polygon points="13,${6 - r - 0.5} ${13 + r + 0.5},${6 + r} ${13 - r - 0.5},${6 + r}" fill="${fill}"/>`;
  }
  if (kind === 'diamond') {
    return `<polygon points="13,${6 - r - 0.6} ${13 + r + 0.6},6 13,${6 + r + 0.6} ${13 - r - 0.6},6" fill="${fill}"/>`;
  }
  return `<circle cx="13" cy="6" r="${r}" fill="${fill}"/>`;
}

let CHART_SEQ = 0;

/**
 * Multi-series line chart that refuses to draw a trend it cannot measure.
 *
 * series: [{ label, color, points: [{ x: epoch seconds, y, n?, p25?, p75?, bucket?, breakBefore?, tip? }] }]
 *
 * The caller aggregates and flags the gaps (see serverPoints in series.js): a polyline is drawn only
 * inside a run of points where `breakBefore` is false, so a new session, a day with no data or a
 * hole longer than the allowed gap cuts the line instead of being bridged. Points are always drawn
 * in ascending x; nothing is ever linked out of order.
 *
 * Options added for the history view: `xDomain` [a,b] fixes the time axis; `band` draws the p25–p75
 * range; `onBrush(a,b)` turns a drag on the plot into a zoom request; the legend keys are buttons
 * that hide/show a series (state kept on the wrap, so it survives data reloads); `tipXFmt` is the
 * full date shown in the tooltip.
 *
 * Accessibility (design-system rule "cor nunca é o único portador de informação"):
 * every series also carries a dash pattern and a marker shape, echoed in the legend and in the
 * equivalent table; the svg has a text summary; values are labelled directly when the series is
 * short enough for labels not to collide.
 */
export function lineChart(wrap, {
  series, unit = '', fmt = String, xFmt = String, tipXFmt = null, emptyMsg = 'nenhuma série disponível',
  logScale = false, xTicks = null, xDomain = null, band = false, onBrush = null,
  tableLabel = '', ariaTitle = '', notes = [],
}) {
  const clean = (series || []).map((s, i) => ({
    ...s,
    dash: s.dash !== undefined ? s.dash : dashFor(i),
    marker: s.marker || markerFor(i),
    points: (s.points || []).filter((p) => typeof p.x === 'number' && Number.isFinite(p.x)
      && typeof p.y === 'number' && Number.isFinite(p.y)).slice().sort((a, b) => a.x - b.x),
  })).filter((s) => s.points.length);
  if (!clean.length) return emptyInto(wrap, emptyMsg);
  if (!wrap._hidden) wrap._hidden = new Set();
  const tid = wrap._chartTableId || (wrap._chartTableId = `chart-table-${++CHART_SEQ}`);
  const tipFmt = tipXFmt || xFmt;

  responsive(wrap, (W) => {
    const shown = clean.filter((s) => !wrap._hidden.has(s.label));
    const pts = shown.flatMap((s) => s.points);
    const drawn = shown.map((s) => ({ s, segments: splitSegments(s.points) }));
    const nSegments = drawn.reduce((a, d) => a + d.segments.length, 0);
    const nBreaks = drawn.reduce((a, d) => a + Math.max(0, d.segments.length - 1), 0);
    const withBand = band && pts.some((p) => typeof p.p25 === 'number' && typeof p.p75 === 'number');
    const yVals = pts.flatMap((p) => (withBand && typeof p.p25 === 'number' && typeof p.p75 === 'number'
      ? [p.y, p.p25, p.p75] : [p.y]));
    const scale = valueScale(yVals, { log: logScale });
    const xs = pts.map((p) => p.x);
    const hasDomain = Array.isArray(xDomain) && xDomain.length === 2 && xDomain[1] > xDomain[0];
    const x0 = hasDomain ? xDomain[0] : (xs.length ? Math.min(...xs) : 0);
    const x1 = hasDomain ? xDomain[1] : (xs.length ? Math.max(...xs) : 1);
    const ticks = (Array.isArray(xTicks) && xTicks.length >= 2 ? xTicks : [x0, (x0 + x1) / 2, x1])
      .filter((t) => t >= x0 && t <= x1);
    // Labels next to every marker only when they cannot pile up on each other.
    const valueLabels = pts.length <= 24 && shown.length <= 6;
    const versions = [...new Set(pts.map((p) => p.metricsVersion))];
    const logFallback = logScale && pts.length > 0 && scale.kind !== 'log';
    const allNotes = [...notes, logFallback ? 'escala log indisponível (há valor ≤ 0 ou um único valor): exibindo linear' : null];
    const summary = pts.length
      ? lineSummary({ clean: shown, x0, x1, scale, nSegments, nBreaks, versions, unit, fmt, xFmt: tipFmt, title: ariaTitle })
      : `${ariaTitle || 'Série temporal'}. Todas as séries estão ocultas.`;

    const padL = 64; const padR = 16; const padT = 14; const padB = 40; const H = 258;
    const plotW = Math.max(60, W - padL - padR); const plotH = H - padT - padB;
    const sx = (x) => padL + (x1 === x0 ? plotW / 2 : ((x - x0) / (x1 - x0)) * plotW);
    const sy = (y) => padT + plotH - scale.norm(y) * plotH;
    const svg = el('svg', {
      viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label': summary,
    });
    const titleNode = el('title', {});
    titleNode.textContent = summary;
    svg.appendChild(titleNode);

    for (const tv of scale.ticks) {
      const y = sy(tv);
      svg.appendChild(el('line', { class: 'grid-line', x1: padL, x2: padL + plotW, y1: y, y2: y }));
      const t = el('text', { class: 'axis', x: padL - 8, y: y + 3, 'text-anchor': 'end' });
      t.textContent = fmt(tv);
      svg.appendChild(t);
    }
    if (ticks.length <= 8) {
      for (const xv of ticks) {
        const x = sx(xv);
        svg.appendChild(el('line', { class: 'grid-line', x1: x, x2: x, y1: padT, y2: padT + plotH }));
      }
    }
    for (const xv of ticks) {
      const t = el('text', {
        class: 'axis', x: Math.min(W - padR - 14, Math.max(padL + 14, sx(xv))), y: H - 20, 'text-anchor': 'middle',
      });
      t.textContent = xFmt(xv);
      svg.appendChild(t);
    }

    // Brush layer sits BELOW the markers so their tooltips keep working.
    let brushRect = null;
    if (typeof onBrush === 'function' && pts.length) {
      const hit = el('rect', { class: 'brush-hit', x: padL, y: padT, width: plotW, height: plotH, fill: 'transparent' });
      brushRect = el('rect', { class: 'brush-sel', y: padT, height: plotH, width: 0, x: padL, visibility: 'hidden' });
      svg.appendChild(hit);
      svg.appendChild(brushRect);
      const toX = (ev) => {
        const b = svg.getBoundingClientRect();
        return Math.min(padL + plotW, Math.max(padL, (ev.clientX - b.left) * (W / (b.width || W))));
      };
      let startPx = null;
      hit.addEventListener('pointerdown', (ev) => {
        startPx = toX(ev);
        hit.setPointerCapture?.(ev.pointerId);
        brushRect.setAttribute('visibility', 'visible');
        brushRect.setAttribute('x', startPx);
        brushRect.setAttribute('width', 0);
      });
      hit.addEventListener('pointermove', (ev) => {
        if (startPx === null) return;
        const cur = toX(ev);
        brushRect.setAttribute('x', Math.min(startPx, cur));
        brushRect.setAttribute('width', Math.abs(cur - startPx));
      });
      const finish = (ev) => {
        if (startPx === null) return;
        const cur = toX(ev);
        const a = Math.min(startPx, cur); const b = Math.max(startPx, cur);
        startPx = null;
        brushRect.setAttribute('visibility', 'hidden');
        if (b - a >= 8) {
          const inv = (px) => x0 + ((px - padL) / plotW) * (x1 - x0);
          onBrush(inv(a), inv(b));
        }
      };
      hit.addEventListener('pointerup', finish);
      hit.addEventListener('pointercancel', () => { startPx = null; brushRect.setAttribute('visibility', 'hidden'); });
    }

    for (const { s, segments } of drawn) {
      if (withBand) {
        for (const seg of segments) {
          const ok = seg.filter((q) => typeof q.p25 === 'number' && typeof q.p75 === 'number');
          if (ok.length < 2) continue;
          const top = ok.map((q, i) => `${i ? 'L' : 'M'}${sx(q.x).toFixed(1)},${sy(q.p75).toFixed(1)}`);
          const bottom = ok.slice().reverse().map((q) => `L${sx(q.x).toFixed(1)},${sy(q.p25).toFixed(1)}`);
          svg.appendChild(el('path', {
            class: 'band', d: `${top.join(' ')} ${bottom.join(' ')} Z`, fill: s.color, 'fill-opacity': 0.14, stroke: 'none',
          }));
        }
      }
      for (const seg of segments) {
        if (seg.length > 1) {
          svg.appendChild(el('path', {
            d: seg.map((q, i) => `${i ? 'L' : 'M'}${sx(q.x).toFixed(1)},${sy(q.y).toFixed(1)}`).join(' '),
            fill: 'none', stroke: s.color, 'stroke-width': 1.8, 'stroke-linejoin': 'round',
            'stroke-dasharray': s.dash || null,
          }));
        }
      }
      const dense = s.points.length > 120;
      for (const q of s.points) {
        const x = sx(q.x);
        const y = sy(q.y);
        const m = markerNode(s.marker, x, y, s.color, dense ? 2 : 2.6);
        bindTip(wrap, m, pointTip(s, q, unit, fmt, tipFmt));
        svg.appendChild(m);
        if (valueLabels) {
          const lab = el('text', {
            class: 'point-val', x: Math.min(W - padR - 2, Math.max(padL + 2, x)),
            y: Math.max(padT + 8, y - 7), 'text-anchor': 'middle',
          });
          lab.textContent = fmt(q.y);
          svg.appendChild(lab);
        }
      }
    }
    if (!pts.length) {
      const msg = el('text', { class: 'axis', x: W / 2, y: H / 2, 'text-anchor': 'middle' });
      msg.textContent = 'todas as séries estão ocultas — clique na legenda para mostrar';
      svg.appendChild(msg);
    }
    wrap.innerHTML = '';
    wrap.appendChild(svg);
    wrap.insertAdjacentHTML('beforeend', lineLegendHTML(clean, wrap._hidden)
      + (unit ? `<div class="chart-legend"><span class="muted">Unidade: ${esc(unit)}</span></div>` : '')
      + lineFootHTML(wrap, tid, {
        summary, notes: allNotes, unit, fmt, xFmt: tipFmt, clean: shown, nSegments, tableLabel,
      }));
    wrap.querySelectorAll('[data-legend-series]').forEach((b) => {
      b.addEventListener('click', () => {
        const label = clean[Number(b.dataset.legendSeries)].label;
        if (wrap._hidden.has(label)) wrap._hidden.delete(label); else wrap._hidden.add(label);
        wrap._chartRedraw(true);
      });
    });
    const btn = wrap.querySelector('.chart-table-btn');
    if (btn) {
      btn.addEventListener('click', () => {
        wrap._tableOpen = !wrap._tableOpen;
        if (typeof wrap._chartRedraw === 'function') wrap._chartRedraw(true);
      });
    }
  });
}

/** Legend whose key repeats the dash pattern and the marker (colour is never the only signal).
 * Each key is a button: click hides/shows the series. */
function lineLegendHTML(series, hidden) {
  return `<div class="chart-legend">${series.map((s, i) => {
    const off = hidden.has(s.label);
    return `<button type="button" class="key legend-toggle${off ? ' off' : ''}" data-legend-series="${i}" `
      + `aria-pressed="${!off}" title="${off ? 'mostrar' : 'ocultar'} ${esc(s.label)}">`
      + `<svg class="chart-key" width="26" height="12" viewBox="0 0 26 12" aria-hidden="true" focusable="false">`
      + `<line x1="1" y1="6" x2="25" y2="6" stroke="${esc(s.color)}" stroke-width="2.5"${s.dash ? ` stroke-dasharray="${s.dash}"` : ''}/>`
      + `${markerSVG(s.marker, s.color)}</svg>${esc(s.label)}</button>`;
  }).join('')}</div>`;
}

/** Footer: what was plotted, the caveats, and the button that opens the equivalent table. */
function lineFootHTML(wrap, tid, o) {
  const open = Boolean(wrap._tableOpen);
  const notes = o.notes.filter(Boolean);
  return `${notes.length ? `<p class="chart-note">${notes.map((n) => esc(n)).join(' · ')}</p>` : ''}
    <div class="chart-actions">
      <button type="button" class="linkish chart-table-btn" aria-expanded="${open}" aria-controls="${tid}">
        ${open ? 'esconder tabela' : 'ver tabela'}</button>
      <span class="muted">${o.clean.length} séries · ${o.clean.reduce((a, s) => a + s.points.length, 0)} pontos · ${o.nSegments} trechos</span>
    </div>
    ${open ? lineTableHTML(tid, o) : ''}`;
}

/** The same numbers as the chart, as a table: mandatory equivalent for screen readers. */
function lineTableHTML(tid, { clean, unit, fmt, xFmt, tableLabel }) {
  const rowsAll = clean.flatMap((s) => s.points.map((q) => ({ s, q })));
  const capped = rowsAll.length > 500;
  const rows = capped ? rowsAll.slice(0, 500) : rowsAll;
  const withBucket = clean.some((s) => s.points.some((q) => q.bucket));
  const withRange = clean.some((s) => s.points.some((q) => typeof q.p25 === 'number'));
  const withVersion = clean.some((s) => s.points.some((q) => q.metricsVersion !== undefined));
  const body = rows.map(({ s, q }) => `<tr>
      <td><span class="chart-cell-key"><svg class="chart-key" width="26" height="12" viewBox="0 0 26 12" aria-hidden="true" focusable="false">`
    + `<line x1="1" y1="6" x2="25" y2="6" stroke="${esc(s.color)}" stroke-width="2.5"${s.dash ? ` stroke-dasharray="${esc(s.dash)}"` : ''}/>`
    + `${markerSVG(s.marker, s.color)}</svg>${esc(s.label)}</span></td>
      <td class="mono">${esc(xFmt(q.x))}</td>
      ${withBucket ? `<td class="mono">${esc(String(q.bucket === null || q.bucket === undefined ? '—' : q.bucket).slice(0, 30))}</td>` : ''}
      <td class="num">${esc(fmt(q.y))}</td>
      ${withRange ? `<td class="num">${typeof q.p25 === 'number' ? `${esc(fmt(q.p25))} – ${esc(fmt(q.p75))}` : '<span class="muted">—</span>'}</td>` : ''}
      <td class="num">${q.n === undefined ? '<span class="muted">—</span>' : esc(fmtNumPlain(q.n))}</td>
      ${withVersion ? `<td class="mono">${q.metricsVersion === null || q.metricsVersion === undefined
    ? '<span class="muted">não registrado</span>' : esc(String(q.metricsVersion))}</td>` : ''}
    </tr>`).join('');
  return `<div class="table-scroll" id="${tid}">
      <table class="data chart-data">
        <caption class="muted">${esc(tableLabel || 'valores')}${unit ? ` (${esc(unit)})` : ''}</caption>
        <thead><tr><th>Série</th><th>Quando</th>${withBucket ? '<th>Sessão / dia</th>' : ''}<th class="num">Valor</th>${withRange ? '<th class="num">p25 – p75</th>' : ''}<th class="num">Runs</th>${withVersion ? '<th>metrics_version</th>' : ''}</tr></thead>
        <tbody>${body}</tbody>
      </table>
      ${capped ? `<p class="chart-note">mostrando as primeiras 500 de ${rowsAll.length} linhas — o gráfico acima também é limitado</p>` : ''}
    </div>`;
}

const fmtNumPlain = (n) => (typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString('pt-BR') : String(n));

function pointTip(s, q, unit, fmt, xFmt) {
  const bits = [`<b>${esc(s.label)}</b>`, esc(xFmt(q.x))];
  if (q.bucket) bits.push(`${q.day ? 'dia' : 'sessão'} ${esc(String(q.bucket))}`);
  bits.push(`${esc(fmt(q.y))}${unit ? ` ${esc(unit)}` : ''}`);
  if (q.n > 1) bits.push(`mediana de ${fmtNumPlain(q.n)} runs`);
  if (q.n === 1) bits.push('1 run');
  if (typeof q.p25 === 'number' && typeof q.p75 === 'number' && q.n > 1) {
    bits.push(`p25–p75: ${esc(fmt(q.p25))} – ${esc(fmt(q.p75))}`);
  }
  if (q.sessions > 1) bits.push(`${q.sessions} sessões`);
  if (q.metricsVersion !== null && q.metricsVersion !== undefined) bits.push(`metrics_version ${esc(String(q.metricsVersion))}`);
  if (q.tip) bits.push(q.tip);
  return bits.join('<br>');
}

/** Screen-reader summary: what is plotted, over what span, and where the line breaks. */
function lineSummary({ clean, x0, x1, scale, nSegments, nBreaks, versions, unit, fmt, xFmt, title }) {
  const ys = clean.flatMap((s) => s.points.map((q) => q.y));
  const parts = [
    title || 'Série temporal',
    `${clean.length} séries, ${ys.length} pontos`,
    `de ${xFmt(x0)} a ${xFmt(x1)}`,
    `valores de ${fmt(Math.min(...ys))} a ${fmt(Math.max(...ys))}${unit ? ` ${unit}` : ''}`,
    `escala ${scale.kind === 'log' ? 'logarítmica' : 'linear'}`,
  ];
  if (nBreaks > 0) {
    parts.push(`${nBreaks} trechos sem ligação porque faltam dados (${nSegments} trechos no total)`);
  }
  const defined = versions.filter((v) => v !== undefined);
  if (defined.length > 1) {
    parts.push(`metrics_version ${defined.map((v) => (v === null ? 'não registrado' : v)).join(', ')} — versões diferentes não são ligadas entre si`);
  }
  return `${parts.join('. ')}.`;
}
