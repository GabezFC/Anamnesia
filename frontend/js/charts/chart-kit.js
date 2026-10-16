/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * ANAMNÉSIA CHART KIT (SVG PURO)
 * 
 * Reusable, robust vector charting module built strictly with modern SVG and CSS variables.
 * - ZERO external libraries or CDN dependencies.
 * - REAL responsiveness via ResizeObserver with 100ms debounce.
 * - NO preserveAspectRatio="none" (círculos e textos mantêm proporção real).
 * - viewBox = width x height reais (1 unidade = 1 pixel).
 * - "Nice scale" algorithm for clean, round Y-axis ticks.
 * - Floating interactive tooltips.
 * - All colors defined via var(--chart-1)...var(--chart-8), var(--grid), var(--axis).
 */

import { esc } from '../format.js';
import { I18N } from '../i18n.js';
import { enhanceChart } from './chart-a11y.js';

/**
 * Calculates human-friendly "nice" ticks for axis scales.
 */
export function niceScale(min, max, maxTicks = 5) {
  if (min === max) {
    if (min === 0) {
      max = 1;
    } else {
      min = min * 0.9;
      max = max * 1.1;
    }
  }

  // Force minimum to 0 for non-negative metric ranges
  if (min > 0 && min / (max || 1) < 0.25) {
    min = 0;
  }

  const range = max - min;

  function niceNum(rangeVal, round) {
    const exponent = Math.floor(Math.log10(rangeVal));
    const fraction = rangeVal / Math.pow(10, exponent);
    let niceFraction;

    if (round) {
      if (fraction < 1.5) niceFraction = 1;
      else if (fraction < 3) niceFraction = 2;
      else if (fraction < 7) niceFraction = 5;
      else niceFraction = 10;
    } else {
      if (fraction <= 1) niceFraction = 1;
      else if (fraction <= 2) niceFraction = 2;
      else if (fraction <= 5) niceFraction = 5;
      else niceFraction = 10;
    }
    return niceFraction * Math.pow(10, exponent);
  }

  const tickSpacing = niceNum(range / (maxTicks - 1), true) || 1;
  const niceMin = Math.floor(min / tickSpacing) * tickSpacing;
  const niceMax = Math.ceil(max / tickSpacing) * tickSpacing;

  const ticks = [];
  // Use small epsilon for floating-point iteration stability
  for (let val = niceMin; val <= niceMax + tickSpacing * 0.5; val += tickSpacing) {
    ticks.push(parseFloat(val.toFixed(6)));
  }

  return {
    min: niceMin,
    max: niceMax,
    tickSpacing,
    ticks
  };
}

/**
 * Helper to create a shared floating tooltip for a chart wrapper
 */
function createTooltip(container) {
  let tooltip = container.querySelector('.chart-tooltip');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.className = 'chart-tooltip';
    container.appendChild(tooltip);
  }

  return {
    show: (x, y, title, rows) => {
      tooltip.innerHTML = `
        <div class="chart-tooltip-title">${title}</div>
        ${rows.map(r => `
          <div class="chart-tooltip-row">
            <span class="chart-tooltip-badge" data-css="background-color:${esc(r.color)}"></span>
            <span>${r.label}:</span>
            <span class="u-f6db11">${r.value}</span>
          </div>
        `).join('')}
      `;
      tooltip.style.left = `${Math.round(x)}px`;
      tooltip.style.top = `${Math.round(y)}px`;
      tooltip.classList.add('is-visible');
    },
    hide: () => {
      tooltip.classList.remove('is-visible');
    },
    element: tooltip
  };
}

/** ANA-206: SVG com nome acessível quando `ariaLabel` é dado; senão decorativo (a tabela ao lado carrega os dados). */
function svgA11y(options = {}) {
  const l = options && options.ariaLabel ? String(options.ariaLabel).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`) : '';
  return l ? ` role="img" aria-label="${l}"` : ' aria-hidden="true"';
}

/**
 * Responsive container binder with ResizeObserver and 100ms debounce
 */
function bindResponsiveChart(container, renderFn) {
  let debounceTimer = null;
  let isDestroyed = false;

  const runRender = () => {
    if (isDestroyed) return;
    const rect = container.getBoundingClientRect();
    const width = Math.max(Math.floor(rect.width || container.clientWidth || 300), 200);
    renderFn(width);
  };

  // Initial draw
  runRender();

  // ResizeObserver for true pixel responsiveness
  let observer = null;
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(runRender, 100);
    });
    observer.observe(container);
  }

  return {
    destroy: () => {
      isDestroyed = true;
      clearTimeout(debounceTimer);
      if (observer) observer.disconnect();
      const tooltip = container.querySelector('.chart-tooltip');
      if (tooltip) tooltip.remove();
    },
    redraw: runRender
  };
}

/**
 * ============================================================================
 * 1. LINE CHART
 * Smooth or segmented lines, filled gradient under-area, gridlines, hover points.
 * ============================================================================
 */
export function createLineChart(container, options = {}) {
  const {
    data = [], // [{ x, y1, y2... }]
    xKey = 'x',
    series = [
      { key: 'y', label: 'Valor', color: 'var(--chart-1)', fill: true }
    ],
    yFormatter = (v) => v.toString(),
    xFormatter = (v) => v.toString(),
    height = 240,
    marginTop = 16,
    marginRight = 24,
    marginBottom = 34,
    marginLeft = 54,
    smooth = true
  } = options;

  container.classList.add('chart-kit-wrapper');
  const tooltip = createTooltip(container);

  return bindResponsiveChart(container, (width) => {
    if (data.length === 0) {
      container.innerHTML = `<div class="chart-empty u-863d48">Sem dados para exibição</div>`;
      return;
    }

    const plotW = Math.max(width - marginLeft - marginRight, 40);
    const plotH = Math.max(height - marginTop - marginBottom, 40);

    // Find min and max across all series
    let allY = [];
    data.forEach(d => {
      series.forEach(s => {
        if (d[s.key] !== null && d[s.key] !== undefined) {
          allY.push(d[s.key]);
        }
      });
    });

    if (allY.length === 0) allY = [0, 1];
    const minY = Math.min(...allY);
    const maxY = Math.max(...allY);
    const scale = niceScale(minY, maxY, 5);

    const getX = (index) => {
      if (data.length <= 1) return marginLeft + plotW / 2;
      return marginLeft + (index / (data.length - 1)) * plotW;
    };

    const getY = (val) => {
      const range = scale.max - scale.min || 1;
      const normalized = (val - scale.min) / range;
      return marginTop + plotH - (normalized * plotH);
    };

    // Build SVG elements
    let svgHtml = `
      <svg class="chart-svg"${svgA11y(options)} viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
        <defs>
          ${series.map((s, idx) => `
            <linearGradient id="chart-grad-${idx}" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="${s.color}" stop-opacity="0.28" />
              <stop offset="100%" stop-color="${s.color}" stop-opacity="0.0" />
            </linearGradient>
          `).join('')}
        </defs>

        <!-- Horizontal Gridlines & Y-Axis labels -->
        <g class="chart-grid">
          ${scale.ticks.map(tick => {
            const yPos = getY(tick);
            return `
              <line class="chart-grid-line" x1="${marginLeft}" y1="${yPos}" x2="${width - marginRight}" y2="${yPos}" />
              <text class="chart-axis-text" x="${marginLeft - 10}" y="${yPos + 4}" text-anchor="end">${yFormatter(tick)}</text>
            `;
          }).join('')}
        </g>

        <!-- X-Axis line & labels -->
        <line class="chart-axis-line" x1="${marginLeft}" y1="${marginTop + plotH}" x2="${width - marginRight}" y2="${marginTop + plotH}" />
        <g class="chart-x-labels">
          ${data.map((d, i) => {
            // Adaptive skipping of X-axis labels if too narrow
            const step = Math.ceil(data.length / Math.max(Math.floor(plotW / 65), 2));
            if (i % step !== 0 && i !== data.length - 1) return '';
            const xPos = getX(i);
            return `
              <text class="chart-axis-text" x="${xPos}" y="${height - 10}" text-anchor="middle">${xFormatter(d[xKey])}</text>
            `;
          }).join('')}
        </g>
    `;

    // Render area fills and paths for each series
    series.forEach((s, sIdx) => {
      const pts = data.map((d, i) => ({ x: getX(i), y: getY(d[s.key]), rawX: d[xKey], rawY: d[s.key] }));
      
      let pathD = '';
      if (smooth && pts.length > 2) {
        // Catmull-Rom or cubic Bezier
        pathD = `M ${pts[0].x} ${pts[0].y}`;
        for (let i = 0; i < pts.length - 1; i++) {
          const curr = pts[i];
          const next = pts[i + 1];
          const cpx1 = curr.x + (next.x - curr.x) / 3;
          const cpy1 = curr.y;
          const cpx2 = curr.x + 2 * (next.x - curr.x) / 3;
          const cpy2 = next.y;
          pathD += ` C ${cpx1} ${cpy1}, ${cpx2} ${cpy2}, ${next.x} ${next.y}`;
        }
      } else {
        pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
      }

      if (s.fill && pts.length > 0) {
        const areaD = `${pathD} L ${pts[pts.length - 1].x} ${marginTop + plotH} L ${pts[0].x} ${marginTop + plotH} Z`;
        svgHtml += `<path d="${areaD}" fill="url(#chart-grad-${sIdx})" />`;
      }

      svgHtml += `<path d="${pathD}" fill="none" stroke="${s.color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" />`;

      // Draw points
      pts.forEach((p, pIdx) => {
        svgHtml += `
          <circle 
            class="chart-point" 
            cx="${p.x}" 
            cy="${p.y}" 
            r="3.5" 
            fill="var(--bg-surface)" 
            stroke="${s.color}" 
            stroke-width="2" 
            data-point-idx="${pIdx}"
            data-series-idx="${sIdx}"
          />
        `;
      });
    });

    svgHtml += `</svg>`;

    // Render legend if more than 1 series
    let legendHtml = '';
    if (series.length > 1) {
      legendHtml = `
        <div class="chart-legend">
          ${series.map(s => `
            <div class="chart-legend-item">
              <span class="chart-legend-dot" data-css="background-color:${esc(s.color)}"></span>
              <span>${s.label}</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    container.innerHTML = svgHtml + legendHtml;
    container.appendChild(tooltip.element);
    enhanceChart(container, {
      caption: options.ariaLabel || I18N.a11y.chartTable, marks: '.chart-point',
      head: [I18N.a11y.category, ...series.map((s) => s.label)],
      rows: data.map((d) => [xFormatter(d[xKey]), ...series.map((s) => yFormatter(d[s.key]))]),
      nameOf: (m) => { const d = data[+m.getAttribute('data-point-idx')]; const s = series[+m.getAttribute('data-series-idx')]; return `${xFormatter(d[xKey])}, ${s.label}: ${yFormatter(d[s.key])}`; },
    });

    // Attach hover listeners for interactive tooltip
    const svgElem = container.querySelector('.chart-svg');
    const points = container.querySelectorAll('.chart-point');

    points.forEach(pt => {
      pt.onmouseenter = (e) => {
        const pIdx = parseInt(pt.getAttribute('data-point-idx'), 10);
        const item = data[pIdx];
        const rows = series.map(s => ({
          label: s.label,
          value: yFormatter(item[s.key]),
          color: s.color
        }));

        const cx = parseFloat(pt.getAttribute('cx'));
        const cy = parseFloat(pt.getAttribute('cy'));
        tooltip.show(cx, cy, xFormatter(item[xKey]), rows);
      };

      pt.onmouseleave = () => {
        tooltip.hide();
      };
    });

    // Also support hover across whole vertical columns
    svgElem.onmousemove = (e) => {
      const rect = svgElem.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      if (mouseX < marginLeft || mouseX > width - marginRight) {
        tooltip.hide();
        return;
      }

      // Find nearest point
      let nearestIdx = 0;
      let minDiff = Infinity;
      data.forEach((_, i) => {
        const diff = Math.abs(getX(i) - mouseX);
        if (diff < minDiff) {
          minDiff = diff;
          nearestIdx = i;
        }
      });

      if (minDiff < 40) {
        const item = data[nearestIdx];
        const rows = series.map(s => ({
          label: s.label,
          value: yFormatter(item[s.key]),
          color: s.color
        }));
        const targetX = getX(nearestIdx);
        // Average Y for tooltip position
        const targetY = series.reduce((acc, s) => acc + getY(item[s.key]), 0) / series.length;
        tooltip.show(targetX, targetY, xFormatter(item[xKey]), rows);
      }
    };

    svgElem.onmouseleave = () => {
      tooltip.hide();
    };
  });
}

/**
 * ============================================================================
 * 2. BAR CHART (Grouped or Simple)
 * True pixel scale, rounded tops, clean hover, rotating labels if needed.
 * ============================================================================
 */
export function createBarChart(container, options = {}) {
  const {
    categories = [], // ['Baseline', 'Graphify', 'JEV']
    series = [
      { label: 'Custo', color: 'var(--chart-1)', values: [] }
    ],
    yFormatter = (v) => v.toString(),
    height = 240,
    marginTop = 18,
    marginRight = 20,
    marginBottom = 44,
    marginLeft = 56
  } = options;

  container.classList.add('chart-kit-wrapper');
  const tooltip = createTooltip(container);

  return bindResponsiveChart(container, (width) => {
    if (categories.length === 0) {
      container.innerHTML = `<div class="chart-empty u-863d48">Sem dados para exibição</div>`;
      return;
    }

    const plotW = Math.max(width - marginLeft - marginRight, 40);
    const plotH = Math.max(height - marginTop - marginBottom, 40);

    // Max value across all series
    let allVals = [0];
    series.forEach(s => {
      s.values.forEach(v => {
        if (typeof v === 'number' && !isNaN(v)) allVals.push(v);
      });
    });

    const maxVal = Math.max(...allVals);
    const scale = niceScale(0, maxVal, 5);

    const getY = (val) => {
      const range = scale.max - scale.min || 1;
      const normalized = (val - scale.min) / range;
      return marginTop + plotH - (normalized * plotH);
    };

    const groupWidth = plotW / categories.length;
    const barPadding = Math.max(groupWidth * 0.18, 4);
    const availableBarSpace = groupWidth - (barPadding * 2);
    const barWidth = Math.max(availableBarSpace / series.length, 6);

    let svgHtml = `
      <svg class="chart-svg"${svgA11y(options)} viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">
        <!-- Gridlines -->
        <g class="chart-grid">
          ${scale.ticks.map(tick => {
            const yPos = getY(tick);
            return `
              <line class="chart-grid-line" x1="${marginLeft}" y1="${yPos}" x2="${width - marginRight}" y2="${yPos}" />
              <text class="chart-axis-text" x="${marginLeft - 10}" y="${yPos + 4}" text-anchor="end">${yFormatter(tick)}</text>
            `;
          }).join('')}
        </g>

        <!-- X-Axis line -->
        <line class="chart-axis-line" x1="${marginLeft}" y1="${marginTop + plotH}" x2="${width - marginRight}" y2="${marginTop + plotH}" />

        <!-- Bars -->
        <g class="chart-bars">
          ${categories.map((cat, cIdx) => {
            const groupX = marginLeft + cIdx * groupWidth + barPadding;
            
            return series.map((s, sIdx) => {
              const val = s.values[cIdx] || 0;
              const barH = (val / (scale.max || 1)) * plotH;
              const barX = groupX + sIdx * barWidth;
              const barY = marginTop + plotH - barH;

              return `
                <rect 
                  class="chart-bar" 
                  x="${barX}" 
                  y="${barY}" 
                  width="${Math.max(barWidth - 2, 3)}" 
                  height="${Math.max(barH, 0)}" 
                  rx="3" 
                  ry="3" 
                  fill="${s.color}" 
                  data-cat-idx="${cIdx}" 
                  data-series-idx="${sIdx}"
                  data-val="${val}"
                />
              `;
            }).join('');
          }).join('')}
        </g>

        <!-- Category labels -->
        <g class="chart-x-labels">
          ${categories.map((cat, cIdx) => {
            const centerX = marginLeft + cIdx * groupWidth + groupWidth / 2;
            const isTruncated = cat.length > 16;
            const displayLabel = isTruncated ? cat.slice(0, 14) + '…' : cat;
            return `
              <text 
                class="chart-axis-text" 
                x="${centerX}" 
                y="${height - 14}" 
                text-anchor="middle"
              >
                ${displayLabel}
              </text>
            `;
          }).join('')}
        </g>
      </svg>
    `;

    // Legend
    let legendHtml = '';
    if (series.length > 1) {
      legendHtml = `
        <div class="chart-legend">
          ${series.map(s => `
            <div class="chart-legend-item">
              <span class="chart-legend-dot" data-css="background-color:${esc(s.color)}"></span>
              <span>${s.label}</span>
            </div>
          `).join('')}
        </div>
      `;
    }

    container.innerHTML = svgHtml + legendHtml;
    container.appendChild(tooltip.element);
    enhanceChart(container, {
      caption: options.ariaLabel || I18N.a11y.chartTable, marks: '.chart-bar',
      head: [I18N.a11y.category, ...series.map((s) => s.label)],
      rows: categories.map((cat, i) => [cat, ...series.map((s) => yFormatter(s.values[i] || 0))]),
      nameOf: (m) => `${categories[+m.getAttribute('data-cat-idx')]}, ${series[+m.getAttribute('data-series-idx')].label}: ${yFormatter(parseFloat(m.getAttribute('data-val')))}`,
    });

    // Attach hover listeners
    const bars = container.querySelectorAll('.chart-bar');
    bars.forEach(bar => {
      bar.onmouseenter = (e) => {
        const cIdx = parseInt(bar.getAttribute('data-cat-idx'), 10);
        const sIdx = parseInt(bar.getAttribute('data-series-idx'), 10);
        const val = parseFloat(bar.getAttribute('data-val'));
        const s = series[sIdx];
        const cat = categories[cIdx];

        const x = parseFloat(bar.getAttribute('x')) + parseFloat(bar.getAttribute('width')) / 2;
        const y = parseFloat(bar.getAttribute('y'));

        tooltip.show(x, y, cat, [{
          label: s.label,
          value: yFormatter(val),
          color: s.color
        }]);
      };

      bar.onmouseleave = () => {
        tooltip.hide();
      };
    });
  });
}

/**
 * ============================================================================
 * 3. STACKED BAR CHART
 * Indispensable for Latency Breakdown and Token Efficiency comparison!
 * Supports horizontal or vertical modes, calculates real percentage slices.
 * ============================================================================
 */
export function createStackedBarChart(container, options = {}) {
  const {
    categories = [], // e.g. ['Baseline', 'Graphify', 'JEV']
    series = [
      // { label: 'Query', color: 'var(--chart-1)', values: [45, 48, 52] }
    ],
    yFormatter = (v) => v.toString(),
    horizontal = true,
    height = 260,
    marginTop = 16,
    marginRight = 24,
    marginBottom = 36,
    marginLeft = 130
  } = options;

  container.classList.add('chart-kit-wrapper');
  const tooltip = createTooltip(container);

  return bindResponsiveChart(container, (width) => {
    if (categories.length === 0 || series.length === 0) {
      container.innerHTML = `<div class="chart-empty u-863d48">Sem dados para exibição</div>`;
      return;
    }

    const calculatedHeight = Math.max(height, categories.length * 44 + marginTop + marginBottom);
    const plotW = Math.max(width - marginLeft - marginRight, 40);
    const plotH = Math.max(calculatedHeight - marginTop - marginBottom, 40);

    // Calculate totals for each category
    const totals = categories.map((_, cIdx) => {
      return series.reduce((acc, s) => acc + (s.values[cIdx] || 0), 0);
    });

    const maxTotal = Math.max(...totals, 1);
    const scale = niceScale(0, maxTotal, 5);

    if (horizontal) {
      const rowHeight = plotH / categories.length;
      const barHeight = Math.min(Math.max(rowHeight * 0.54, 18), 30);

      let svgHtml = `
        <svg class="chart-svg"${svgA11y(options)} viewBox="0 0 ${width} ${calculatedHeight}" width="${width}" height="${calculatedHeight}">
          <!-- Vertical Gridlines -->
          <g class="chart-grid">
            ${scale.ticks.map(tick => {
              const xPos = marginLeft + (tick / scale.max) * plotW;
              return `
                <line class="chart-grid-line" x1="${xPos}" y1="${marginTop}" x2="${xPos}" y2="${marginTop + plotH}" />
                <text class="chart-axis-text" x="${xPos}" y="${calculatedHeight - 12}" text-anchor="middle">${yFormatter(tick)}</text>
              `;
            }).join('')}
          </g>

          <!-- Y-Axis line -->
          <line class="chart-axis-line" x1="${marginLeft}" y1="${marginTop}" x2="${marginLeft}" y2="${marginTop + plotH}" />

          <!-- Stacked Bars & Category Names -->
          <g class="chart-stacked-bars">
            ${categories.map((cat, cIdx) => {
              const rowY = marginTop + cIdx * rowHeight;
              const barY = rowY + (rowHeight - barHeight) / 2;
              let accumulatedWidth = 0;

              const segments = series.map((s, sIdx) => {
                const val = s.values[cIdx] || 0;
                const segW = (val / scale.max) * plotW;
                const segX = marginLeft + accumulatedWidth;
                accumulatedWidth += segW;

                // Is first or last segment for border-radius
                const isFirst = sIdx === 0;
                const isLast = sIdx === series.length - 1;

                return `
                  <rect 
                    class="chart-bar" 
                    x="${segX}" 
                    y="${barY}" 
                    width="${Math.max(segW, 0)}" 
                    height="${barHeight}" 
                    fill="${s.color}" 
                    data-cat="${cat}" 
                    data-series-label="${s.label}" 
                    data-val="${val}" 
                    data-pct="${totals[cIdx] ? ((val / totals[cIdx]) * 100).toFixed(1) : 0}"
                    data-color="${s.color}"
                  />
                `;
              }).join('');

              const totalVal = totals[cIdx];

              return `
                <g class="chart-row">
                  <text 
                    class="chart-axis-text" 
                    x="${marginLeft - 12}" 
                    y="${barY + barHeight / 2 + 4}" 
                    text-anchor="end"
                    class="u-svg-lbl-primary"
                  >
                    ${cat}
                  </text>
                  ${segments}
                  <text 
                    class="chart-axis-text font-mono" 
                    x="${marginLeft + accumulatedWidth + 8}" 
                    y="${barY + barHeight / 2 + 4}" 
                    text-anchor="start"
                    class="u-svg-lbl-secondary"
                  >
                    ${yFormatter(totalVal)}
                  </text>
                </g>
              `;
            }).join('')}
          </g>
        </svg>
      `;

      // Legend
      const legendHtml = `
        <div class="chart-legend">
          ${series.map(s => `
            <div class="chart-legend-item">
              <span class="chart-legend-dot" data-css="background-color:${esc(s.color)}"></span>
              <span>${s.label}</span>
            </div>
          `).join('')}
        </div>
      `;

      container.innerHTML = svgHtml + legendHtml;
      container.appendChild(tooltip.element);
      enhanceChart(container, {
        caption: options.ariaLabel || I18N.a11y.chartTable, marks: '.chart-bar',
        head: [I18N.a11y.category, ...series.map((s) => s.label)],
        rows: categories.map((cat, i) => [cat, ...series.map((s) => yFormatter(s.values[i] || 0))]),
        nameOf: (m) => `${m.getAttribute('data-cat')}, ${m.getAttribute('data-series-label')}: ${yFormatter(parseFloat(m.getAttribute('data-val')))} (${m.getAttribute('data-pct')}%)`,
      });

      // Event listeners for segments
      const segs = container.querySelectorAll('.chart-bar');
      segs.forEach(seg => {
        seg.onmouseenter = () => {
          const cat = seg.getAttribute('data-cat');
          const label = seg.getAttribute('data-series-label');
          const val = parseFloat(seg.getAttribute('data-val'));
          const pct = seg.getAttribute('data-pct');
          const color = seg.getAttribute('data-color');

          const x = parseFloat(seg.getAttribute('x')) + parseFloat(seg.getAttribute('width')) / 2;
          const y = parseFloat(seg.getAttribute('y'));

          tooltip.show(x, y, `${cat} - ${label}`, [{
            label: 'Valor',
            value: `${yFormatter(val)} (${pct}%)`,
            color
          }]);
        };

        seg.onmouseleave = () => {
          tooltip.hide();
        };
      });
    }
  });
}

/**
 * ============================================================================
 * 4. DONUT / RADIAL CHART
 * Pure SVG trigonometric arcs, centered summary, interactive slice hover.
 * ============================================================================
 */
export function createDonutChart(container, options = {}) {
  const {
    data = [], // [{ label: 'Claude Code', value: 24, color: 'var(--chart-1)' }]
    formatter = (v) => v.toString(),
    centerLabel = 'Total',
    size = 200,
    thickness = 28
  } = options;

  container.classList.add('chart-kit-wrapper');
  const tooltip = createTooltip(container);

  return bindResponsiveChart(container, (width) => {
    if (data.length === 0) {
      container.innerHTML = `<div class="chart-empty u-863d48">Sem dados para exibição</div>`;
      return;
    }

    const total = data.reduce((acc, d) => acc + d.value, 0) || 1;
    const chartSize = Math.min(size, width - 40);
    const radius = chartSize / 2;
    const innerRadius = radius - thickness;
    const center = radius;

    let startAngle = 0;

    const slices = data.map(d => {
      const angle = (d.value / total) * (Math.PI * 2);
      const endAngle = startAngle + angle;

      const x1 = center + radius * Math.sin(startAngle);
      const y1 = center - radius * Math.cos(startAngle);
      const x2 = center + radius * Math.sin(endAngle);
      const y2 = center - radius * Math.cos(endAngle);

      const ix1 = center + innerRadius * Math.sin(startAngle);
      const iy1 = center - innerRadius * Math.cos(startAngle);
      const ix2 = center + innerRadius * Math.sin(endAngle);
      const iy2 = center - innerRadius * Math.cos(endAngle);

      const largeArc = angle > Math.PI ? 1 : 0;

      const pathData = [
        `M ${x1} ${y1}`,
        `A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2}`,
        `L ${ix2} ${iy2}`,
        `A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${ix1} ${iy1}`,
        'Z'
      ].join(' ');

      const sliceObj = {
        path: pathData,
        color: d.color,
        label: d.label,
        value: d.value,
        pct: ((d.value / total) * 100).toFixed(1)
      };

      startAngle = endAngle;
      return sliceObj;
    });

    const svgHtml = `
      <div class="u-813178">
        <svg class="chart-svg"${svgA11y(options)} viewBox="0 0 ${chartSize} ${chartSize}" width="${chartSize}" height="${chartSize}" data-css="max-width:${chartSize}px">
          <g class="chart-donut-slices">
            ${slices.map(s => `
              <path 
                class="chart-bar" 
                d="${s.path}" 
                fill="${s.color}" 
                data-label="${s.label}" 
                data-val="${s.value}" 
                data-pct="${s.pct}" 
                data-color="${s.color}"
                class="u-svg-slice"
              />
            `).join('')}
          </g>

          <!-- Center Text -->
          <text x="${center}" y="${center - 6}" text-anchor="middle" class="chart-axis-text u-ecef09">${centerLabel}</text>
          <text x="${center}" y="${center + 14}" text-anchor="middle" class="u-aa6c37">${formatter(total)}</text>
        </svg>

        <div class="chart-legend u-4d9102">
          ${data.map(d => `
            <div class="chart-legend-item">
              <span class="chart-legend-dot" data-css="background-color:${esc(d.color)}"></span>
              <span>${d.label}</span>
              <span class="font-mono tabular u-bc2c4c">(${((d.value / total) * 100).toFixed(0)}%)</span>
            </div>
          `).join('')}
        </div>
      </div>
    `;

    container.innerHTML = svgHtml;
    container.appendChild(tooltip.element);
    enhanceChart(container, {
      caption: options.ariaLabel || I18N.a11y.chartTable, marks: '.chart-donut-slices path',
      head: [I18N.a11y.category, I18N.a11y.value, '%'],
      rows: data.map((d) => [d.label, formatter(d.value), `${((d.value / total) * 100).toFixed(1)}%`]),
      nameOf: (m) => `${m.getAttribute('data-label')}: ${m.getAttribute('data-val')} (${m.getAttribute('data-pct')}%)`,
    });

    // Attach listeners
    const paths = container.querySelectorAll('.chart-donut-slices path');
    paths.forEach(p => {
      p.onmouseenter = (e) => {
        const label = p.getAttribute('data-label');
        const val = p.getAttribute('data-val');
        const pct = p.getAttribute('data-pct');
        const color = p.getAttribute('data-color');

        const rect = container.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        tooltip.show(x, y, label, [{
          label: 'Quantidade',
          value: `${val} (${pct}%)`,
          color
        }]);
      };

      p.onmouseleave = () => {
        tooltip.hide();
      };
    });
  });
}
