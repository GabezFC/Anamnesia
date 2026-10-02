// series.js — time-series helpers behind the line charts.
// Pure functions only: no DOM, no fetch, no storage, so everything here is
// unit-tested from Node (scripts/check_frontend_charts.mjs).
//
// The rules encoded below exist because the raw payload is hostile to a line
// chart: GET /benchmark/runs?limit=5000 returns ~4.7k runs of one pipeline and
// a dozen of another, spread over a handful of days and sessions. Connecting
// those raw points draws a trend that never happened. So: aggregate first
// (median per day / per session), cap the raw view, and split the line wherever
// joining two points would be a lie.
import { get, metricsOf, median, num } from './format.js';

const DAY_MS = 86400000;

/* ---- time buckets ------------------------------------------------------ */

/** Calendar-day number of an epoch-seconds timestamp, in the viewer's timezone. */
export function localDayNumber(x) {
  const ms = x * 1000;
  return Math.floor((ms - new Date(ms).getTimezoneOffset() * 60000) / DAY_MS);
}

/** Local noon of the day containing `x` — the position used to label a whole day. */
export function dayNoon(x) {
  const d = new Date(x * 1000);
  d.setHours(12, 0, 0, 0);
  return d.getTime() / 1000;
}

/**
 * metrics_version recorded by the gateway (app/gateway/memory_gateway.py).
 * Null on every run written before the field existed — which is the common case,
 * so callers must never assume it is there.
 */
export function metricsVersion(run) {
  const v = num(get(metricsOf(run), 'metrics_version'));
  if (v !== null) return v;
  return num(get(run, 'metrics_version'));
}

/* ---- aggregation modes ------------------------------------------------- */

/** Aggregation modes offered by the history chart, in toolbar order. */
export const AGG_MODES = ['day', 'session', 'run'];
/** Human labels; the panel subtitle says which one is active. */
export const AGG_LABEL = {
  day: 'Por dia',
  session: 'Por sessão',
  run: 'Runs brutos',
};
export const AGG_HINT = {
  day: 'mediana por dia',
  session: 'mediana por sessão',
  run: 'cada run, amostra limitada',
};
/** Per-series cap for the raw view. A 4.7k-point line is unreadable, not informative. */
export const RUN_POINT_CAP = 200;
/** A hole longer than this is a hole, not a trend. */
export const GAP_SECONDS = 6 * 3600;

const SESSION_OF = (r) => String((r && r.session_id) || 'adhoc');

/**
 * Aggregate the runs of a single pipeline into plottable points.
 *
 * mode 'day' | 'session' → one point per bucket, y = median of the runs inside
 * it, x = median created_at (so a day sits at midday instead of at its first
 * run, where it would look like a spike). mode 'run' → every run, downsampled
 * to `maxPoints` when asked.
 *
 * Returns `{ points, total, truncated }`. Points are ordered by x and each one
 * carries `n` (runs behind it), `bucket` (what it aggregates), `day`,
 * `metricsVersion` and `breakBefore` (never join it to the previous point).
 */
export function aggregateRuns(runs, { mode = 'day', valFn, maxPoints = 0, gapSeconds = GAP_SECONDS } = {}) {
  const rows = [];
  for (const r of runs || []) {
    const x = num(r && r.created_at);
    if (x === null) continue;
    const y = num(valFn && valFn(metricsOf(r)));
    if (y === null) continue;                 // never plot a hole as zero
    rows.push({ x, y, n: 1, session: SESSION_OF(r), day: localDayNumber(x), metricsVersion: metricsVersion(r) });
  }
  rows.sort((a, b) => a.x - b.x);
  const total = rows.length;

  let points;
  if (mode === 'run') {
    // Raw view: one point per run, labelled with the session that produced it.
    points = rows.map((r) => ({ ...r, bucket: r.session }));
  } else {
    const keyOf = mode === 'session' ? (r) => r.session : (r) => r.day;
    const groups = new Map();
    for (const r of rows) {
      const key = keyOf(r);
      const g = groups.get(key) || { key, xs: [], ys: [], sessions: new Set(), versions: new Set() };
      g.xs.push(r.x);
      g.ys.push(r.y);
      g.sessions.add(r.session);
      g.versions.add(r.metricsVersion);
      groups.set(key, g);
    }
    points = [...groups.values()].map((g) => {
      const x = median(g.xs);
      return {
        x,
        y: median(g.ys),
        n: g.ys.length,
        // Day buckets are already labelled by the x axis (a date); session
        // buckets need the session id to be readable.
        bucket: mode === 'session' ? String(g.key) : null,
        day: localDayNumber(x),
        sessions: g.sessions.size,
        metricsVersion: singleVersion(g.versions),
      };
    }).sort((a, b) => a.x - b.x);
  }

  let truncated = 0;
  const cap = mode === 'run' && maxPoints > 1 ? maxPoints : 0;
  if (cap && points.length > cap) {
    truncated = points.length - cap;
    points = downsample(points, cap);
  }

  markBreaks(points, mode, gapSeconds);
  return { points, total, truncated };
}

/** Uniform stride downsample that always keeps the first and the last point. */
export function downsample(points, cap) {
  const n = points.length;
  if (cap < 2 || n <= cap) return points.slice();
  const keep = new Set([0, n - 1]);
  const step = (n - 1) / (cap - 1);
  for (let i = 0; i < cap; i++) keep.add(Math.round(i * step));
  return points.filter((_, i) => keep.has(i));
}

/** A segment of points that a single polyline may join. */
function breaksBetween(a, b, mode, gapSeconds) {
  if (a.metricsVersion !== b.metricsVersion) return true;  // never join two calibrations
  // In the bucketed modes the bucket identity already is the break rule: two points are,
  // by construction, two different sessions (or two different days).
  if (mode === 'session') return true;
  if (mode === 'day') return b.day - a.day > 1;            // a day with no data is a hole
  return a.session !== b.session || (b.x - a.x) > gapSeconds;  // raw view: session or hole
}

/** Stamp `breakBefore` on every point (first point always starts a segment). */
function markBreaks(points, mode, gapSeconds) {
  let prev = null;
  for (const p of points) {
    p.breakBefore = prev === null || breaksBetween(prev, p, mode, gapSeconds);
    prev = p;
  }
  return points;
}

function singleVersion(versions) {
  if (versions.size === 1) return [...versions][0];
  if (versions.size === 0) return null;
  return 'mixed';
}

/** Group an ordered point list into the runs a polyline may draw. */
export function splitSegments(points) {
  const segments = [];
  let current = [];
  for (const p of points || []) {
    // A break cuts the line here: close the open segment and start a new one.
    if (current.length && p.breakBefore) { segments.push(current); current = []; }
    current.push(p);
  }
  if (current.length) segments.push(current);
  return segments;
}

/** Axis ticks for a bucketed chart: one label per bucket, capped. */
export function bucketTicks(points, { cap = 10 } = {}) {
  const days = [...new Set((points || []).map((p) => p.day))].sort((a, b) => a - b);
  if (!days.length || days.length > cap) return null;
  const seen = new Map();
  for (const p of points) if (!seen.has(p.day)) seen.set(p.day, dayNoon(p.x));
  return days.map((d) => seen.get(d));
}

/* ---- value axis -------------------------------------------------------- */

/** Round an axis maximum up to a readable step. */
export function niceMax(v) {
  if (!(v > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  return Math.ceil(v / (mag / 2)) * (mag / 2);
}

/**
 * Value axis for the line chart.
 * `log` asks for log10 and silently degrades to linear when the data cannot
 * support it (any value <= 0, or a single value) — `kind` reports what was
 * actually used so the chart can say so instead of pretending.
 */
export function valueScale(values, { log = false } = {}) {
  const ys = (values || []).filter((v) => typeof v === 'number' && Number.isFinite(v));
  if (!ys.length) return { kind: 'linear', ticks: [0, 1], lo: 0, hi: 1, norm: () => 0 };
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const pos = ys.filter((v) => v > 0);
  if (log && pos.length === ys.length && max > min && max > 0) {
    const lo = Math.min(...pos);
    const logLo = Math.log10(lo);
    const logHi = Math.log10(max);
    const span = Math.max(1e-9, logHi - logLo);
    const d0 = Math.floor(logLo);
    const d1 = Math.ceil(logHi);
    const mantissas = d1 - d0 <= 2 ? [1, 2, 5] : [1];
    const ticks = [];
    for (let d = d0; d <= d1; d++) for (const m of mantissas) {
      const v = m * 10 ** d;
      if (v >= lo * 0.999 && v <= max * 1.001) ticks.push(v);
    }
    return {
      kind: 'log',
      ticks: ticks.length >= 2 ? ticks : [lo, max],
      lo,
      hi: max,
      norm: (v) => clamp01((Math.log10(Math.max(v, lo)) - logLo) / span),
    };
  }
  const hi = Math.max(niceMax(Math.max(max, 0)), max) || 1;
  const lo = Math.min(0, min);
  const span = hi - lo || 1;
  return {
    kind: 'linear',
    ticks: [0, 0.25, 0.5, 0.75, 1].map((f) => lo + span * f),
    lo,
    hi,
    norm: (v) => clamp01((v - lo) / span),
  };
}

const clamp01 = (v) => (Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0);

/* ---- non-colour encoding (colour is never the only signal) -------------- */

/** Dash patterns, cycled per series index. */
export const SERIES_DASH = ['', '7 3', '1.6 3', '9 2.5 2 2.5', '3 2'];
/** Marker shapes, cycled per series index. */
export const SERIES_MARKER = ['circle', 'square', 'triangle', 'diamond'];

export const dashFor = (i) => SERIES_DASH[((i % SERIES_DASH.length) + SERIES_DASH.length) % SERIES_DASH.length];
export const markerFor = (i) => SERIES_MARKER[((i % SERIES_MARKER.length) + SERIES_MARKER.length) % SERIES_MARKER.length];

/** Short text naming the shape, used as the accessible label of a series key. */
export const MARKER_NAME = {
  circle: 'círculo', square: 'quadrado', triangle: 'triângulo', diamond: 'losango',
};
/* ---- server time series (GET /benchmark/timeseries) ---------------------------------------- */
// The history chart no longer aggregates in the browser: the server already sorted, deduplicated,
// aggregated and (only if needed) downsampled the points. What is left to do here is deciding where
// the line must be cut, laying out a readable time axis and formatting values.

const pad2 = (n) => String(n).padStart(2, '0');
/** Local dd/MM. */
export const fmtDayMonth = (x) => { const d = new Date(x * 1000); return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}`; };
/** Local HH:mm. */
export const fmtHourMin = (x) => { const d = new Date(x * 1000); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };
/** Local dd/MM/yyyy HH:mm — the full date shown in tooltips and in the table. */
export const fmtFullDate = (x) => {
  const d = new Date(x * 1000);
  return `${fmtDayMonth(x)}/${d.getFullYear()} ${fmtHourMin(x)}`;
};

/** Days since epoch of a YYYY-MM-DD key (UTC arithmetic, so it never depends on DST). */
const dayKeyNumber = (k) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(k || ''));
  return m ? Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY_MS) : null;
};

/**
 * Turn the points of one server series into chart points, stamping `breakBefore` (never join across a
 * hole). Input must already be ASC; this re-sorts defensively and NEVER links points out of order.
 * mode 'session' → every point is its own segment; 'day' → a missing calendar day cuts the line;
 * 'run' → a session change or a hole longer than `gapSeconds` cuts it.
 */
export function serverPoints(points, mode, { gapSeconds = GAP_SECONDS } = {}) {
  const out = (points || [])
    .filter((p) => num(p && p.x) !== null && num(p && p.y) !== null)
    .map((p) => ({ ...p }))
    .sort((a, b) => a.x - b.x);
  let prev = null;
  for (const p of out) {
    let brk = prev === null;
    if (!brk) {
      if (mode === 'session') brk = true;
      else if (mode === 'day') {
        const a = dayKeyNumber(prev.day); const b = dayKeyNumber(p.day);
        brk = a === null || b === null ? (p.x - prev.x) > 2 * 86400 : b - a > 1;
      } else brk = prev.bucket !== p.bucket || (p.x - prev.x) > gapSeconds;
    }
    p.breakBefore = brk;
    prev = p;
  }
  return out;
}

const HOUR = 3600;
const HOUR_STEPS = [1, 2, 3, 6, 12];
const DAY_STEPS = [1, 2, 3, 7, 14, 30, 60, 90];

/**
 * Readable time axis for [x0, x1] (epoch seconds, local time). Interval < 2 days → HH:mm ticks on
 * round hours (dd/MM HH:mm at midnight); otherwise dd/MM ticks at local midnight. At most `maxTicks`.
 */
export function timeAxis(x0, x1, { maxTicks = 7 } = {}) {
  const span = x1 - x0;
  const short = span < 2 * 86400;
  const fmtTick = short
    ? (x) => (fmtHourMin(x) === '00:00' ? `${fmtDayMonth(x)} 00:00` : fmtHourMin(x))
    : fmtDayMonth;
  if (!(span > 0)) return { ticks: [x0], fmt: fmtTick, short };
  const ticks = [];
  if (short) {
    const step = HOUR_STEPS.find((h) => span / (h * HOUR) <= maxTicks) || 12;
    const d = new Date(x0 * 1000);
    d.setMinutes(0, 0, 0);
    d.setHours(Math.floor(d.getHours() / step) * step);
    while (d.getTime() / 1000 < x0) d.setHours(d.getHours() + step);
    for (; d.getTime() / 1000 <= x1; d.setHours(d.getHours() + step)) ticks.push(d.getTime() / 1000);
  } else {
    const step = DAY_STEPS.find((n) => span / (n * 86400) <= maxTicks) || 180;
    const d = new Date(x0 * 1000);
    d.setHours(0, 0, 0, 0);
    if (d.getTime() / 1000 < x0) d.setDate(d.getDate() + 1);
    for (; d.getTime() / 1000 <= x1; d.setDate(d.getDate() + step)) ticks.push(d.getTime() / 1000);
  }
  return { ticks: ticks.length >= 2 ? ticks : [x0, x1], fmt: fmtTick, short };
}

/** Zoom a visible range by `factor` (<1 in, >1 out) around `center` (defaults to its midpoint). */
export function zoomRange([a, b], factor, center = (a + b) / 2) {
  const w = Math.max(60, (b - a) * factor);            // never narrower than a minute
  const c = Math.min(b, Math.max(a, center));
  const lo = c - w * ((c - a) / ((b - a) || 1));       // keep `center` at the same relative position
  return [lo, lo + w];
}

/** since/until (epoch seconds, null = open) for a period button. `custom` = {since, until}. */
export function periodRange(period, now, custom = {}) {
  if (period === '7d') return { since: now - 7 * 86400, until: null };
  if (period === '30d') return { since: now - 30 * 86400, until: null };
  if (period === 'custom') return { since: num(custom.since), until: num(custom.until) };
  return { since: null, until: null };
}

/* ---- pt-BR value formatting for the history chart ------------------------------------------- */
const brDecimal = (s) => String(s).replace('.', ',');
/** 1234 → "1,2k"; 12 345 → "12k"; 1 500 000 → "1,5M"; < 1000 → plain. */
export function fmtTokensBR(v) {
  const n = num(v);
  if (n === null) return '—';
  const a = Math.abs(n);
  const trim = (x, digits) => brDecimal(x.toFixed(digits).replace(/\.0+$/, ''));
  if (a >= 1e6) return `${trim(n / 1e6, a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${trim(n / 1e3, a >= 1e4 ? 0 : 1)}k`;
  return brDecimal(String(Math.round(n * 10) / 10));
}
/** USD: "US$ 0" / "US$ 0,0021" / "US$ 1,25". */
export function fmtUSD(v) {
  const n = num(v);
  if (n === null) return '—';
  if (n === 0) return 'US$ 0';
  const a = Math.abs(n);
  const s = a >= 1 ? n.toFixed(2) : a >= 0.01 ? n.toFixed(3) : n.toFixed(5).replace(/0+$/, '').replace(/\.$/, '');
  return `US$ ${brDecimal(s)}`;
}
/** ms → "850 ms", "1,2 s", "2,5 min". */
export function fmtMsBR(v) {
  const n = num(v);
  if (n === null) return '—';
  if (n >= 60000) return `${brDecimal((n / 60000).toFixed(1))} min`;
  if (n >= 1000) return `${brDecimal((n / 1000).toFixed(n >= 10000 ? 0 : 1))} s`;
  return `${brDecimal(String(Math.round(n * 10) / 10))} ms`;
}
export const fmtAmpBR = (v) => (num(v) === null ? '—' : `${brDecimal(num(v).toFixed(num(v) >= 10 ? 1 : 2))}×`);
export const fmtFracBR = (v) => (num(v) === null ? '—' : `${brDecimal((num(v) * 100).toFixed(0))}%`);

/** Axis/tooltip formatter per HIST_SERIES key. */
export const HIST_FORMAT = {
  tokens: fmtTokensBR, judge: fmtTokensBR, context: fmtTokensBR, saved: fmtTokensBR,
  amplification: fmtAmpBR, latency: fmtMsBR, cost: fmtUSD, documents: fmtTokensBR,
  recall: fmtFracBR, precision: fmtFracBR,
};
