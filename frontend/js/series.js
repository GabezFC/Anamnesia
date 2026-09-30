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