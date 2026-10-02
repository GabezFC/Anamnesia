// Chart invariants for the history line chart: aggregate instead of joining raw runs,
// cut the line at every gap, never bridge two metrics_versions, and never let the log
// scale lie about the data. Pure logic, no browser needed (see frontend/js/series.js).
import {
  AGG_MODES, AGG_LABEL, AGG_HINT, RUN_POINT_CAP, GAP_SECONDS,
  aggregateRuns, bucketTicks, downsample, localDayNumber, metricsVersion, splitSegments,
  valueScale, dashFor, markerFor, MARKER_NAME, SERIES_DASH, SERIES_MARKER, niceMax,
  serverPoints, timeAxis, zoomRange, periodRange, fmtTokensBR, fmtUSD, fmtMsBR, fmtFullDate,
} from '../frontend/js/series.js';

let fail = 0;
const ok = (cond, name, detail = '') => {
  console.log(`${cond ? 'OK  ' : 'FAIL'} ${name}${detail ? `  ${detail}` : ''}`);
  if (!cond) fail++;
};

const DAY = 86400;
const T0 = 1758000000;
/** Local midnight of the n-th day after T0 — DST-safe, so day arithmetic in the fixtures holds. */
const day = (n) => {
  const d = new Date(T0 * 1000);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + n);
  return d.getTime() / 1000;
};
const tokens = (m) => (m && m.total_tokens_spent) ?? null;

/** `count` runs inside one session, `value + i` tokens each. */
const runs = (count, { session = 's1', start = T0, step = 60, value = 1000, version = null } = {}) =>
  Array.from({ length: count }, (_, i) => ({
    run_id: `r${start}-${i}`, session_id: session, created_at: start + i * step,
    pipeline: 'graphify_jev_opt',
    metrics: { total_tokens_spent: value + i, metrics_version: version },
  }));

/* ---- regression: the shape of the real payload -------------------------- */
// Measured on benchmark.db (read-only) via GET /benchmark/runs?limit=5000, which is what
// the dashboard loads: 4743 runs of graphify_jev_opt, 245 of graphify_jev, 12 of baseline.
const optRuns = [
  ...runs(2000, { session: 'opt-a', start: day(0), step: 1 }),
  ...runs(300, { session: 'opt-b', start: day(1), step: 60 }),
  ...runs(12, { session: 'old', start: day(5), step: 3600, value: 20 }),
];
const allXs = optRuns.map((r) => r.created_at);

const perDay = aggregateRuns(optRuns, { mode: 'day', valFn: tokens });
ok(perDay.points.length === 3, 'dia: 2000+300 runs em 2 dias + 12 num terceiro = 3 pontos',
  `points=${perDay.points.length}`);
ok(perDay.total === 2312, 'dia: total de runs preservado', `total=${perDay.total}`);
ok(perDay.points[1].y === 1149.5, 'dia: y é a mediana das runs do dia', `y=${perDay.points[1].y}`);
ok(perDay.points[0].n === 2000 && perDay.points[2].n === 12, 'dia: n conta as runs de cada bucket',
  `n=${perDay.points.map((p) => p.n).join(',')}`);
ok(perDay.points[2].breakBefore === true, 'dia: dia ausente (1 -> 5) não é ligado ao anterior');
ok(!perDay.points[1].breakBefore, 'dia: dias consecutivos com dados continuam ligados');
const daySegments = splitSegments(perDay.points);
ok(daySegments.length === 2, 'dia: 2 trechos (dois dias seguidos + um dia isolado)',
  `segments=${daySegments.length}`);
ok(daySegments[1].length === 1, 'dia: o dia isolado vira um trecho de um ponto só');

const perSession = aggregateRuns(optRuns, { mode: 'session', valFn: tokens });
ok(perSession.points.length === 3, 'sessão: um ponto por sessão', `points=${perSession.points.length}`);
ok(perSession.points.map((p) => p.bucket).join(',') === 'opt-a,opt-b,old',
  'sessão: o bucket traz o session_id', perSession.points.map((p) => p.bucket).join(','));
ok(splitSegments(perSession.points).length === 3, 'sessão: linhas de sessões diferentes não se ligam',
  `segments=${splitSegments(perSession.points).length}`);
ok(splitSegments(perSession.points).every((s) => s.length === 1),
  'sessão: cada ponto é uma sessão, logo cada um é um trecho isolado');
ok(splitSegments(perDay.points).some((s) => s.length === 2),
  'dia: dias consecutivos formam um único trecho');
// Two sessions minutes apart on the same day must NOT be bridged by session mode.
const twoSessionsClose = [
  { session_id: 'a', created_at: T0, metrics: { v: 10 } },
  { session_id: 'b', created_at: T0 + 120, metrics: { v: 12 } },
];
ok(splitSegments(aggregateRuns(twoSessionsClose, { mode: 'session', valFn: (m) => m.v }).points).length === 2,
  'sessão: sessões a 2 min de distância não se ligam');
ok(splitSegments(aggregateRuns(twoSessionsClose, { mode: 'run', valFn: (m) => m.v }).points).length === 2,
  'run bruto: sessões a 2 min de distância não se ligam');
ok(perDay.points[0].bucket === null, 'dia: o bucket fica vazio (o eixo x já dá a data)');

const raw = aggregateRuns(optRuns, { mode: 'run', valFn: tokens, maxPoints: RUN_POINT_CAP });
ok(raw.points.length === RUN_POINT_CAP, 'run bruto: limitado a RUN_POINT_CAP por série',
  `points=${raw.points.length} de ${raw.total} (truncated=${raw.truncated})`);
ok(raw.points[0].x === Math.min(...allXs) && raw.points[raw.points.length - 1].x === Math.max(...allXs),
  'run bruto: primeira e última run preservadas');
ok(raw.truncated === 2312 - RUN_POINT_CAP, 'run bruto: quantas runs ficaram de fora é dito',
  `truncated=${raw.truncated}`);
ok(splitSegments(raw.points).length >= 2, 'run bruto: ainda corta na troca de sessão/dia',
  `segments=${splitSegments(raw.points).length}`);
ok(raw.points.every((p) => p.bucket), 'run bruto: cada ponto diz de qual sessão veio');

/* ---- gaps inside a single session --------------------------------------- */
const holed = [
  { session_id: 's', created_at: T0, metrics: { v: 10 } },
  { session_id: 's', created_at: T0 + 60, metrics: { v: 12 } },
  { session_id: 's', created_at: T0 + GAP_SECONDS * 3, metrics: { v: 14 } },
  { session_id: 's', created_at: T0 + GAP_SECONDS * 3 + 60, metrics: { v: 16 } },
];
ok(splitSegments(aggregateRuns(holed, { mode: 'run', valFn: (m) => m.v }).points).length === 2,
  'lacuna > GAP_SECONDS dentro da sessão corta a linha');
ok(splitSegments(aggregateRuns([holed[0], holed[1]], { mode: 'run', valFn: (m) => m.v }).points).length === 1,
  'runs de 1 min de intervalo continuam ligadas');

/* ---- metrics_version ---------------------------------------------------- */
const versioned = [
  { session_id: 's', created_at: T0, metrics: { v: 10, metrics_version: 1 } },
  { session_id: 's', created_at: T0 + 60, metrics: { v: 12, metrics_version: 1 } },
  { session_id: 's', created_at: T0 + 120, metrics: { v: 14, metrics_version: 2 } },
  { session_id: 's', created_at: T0 + 180, metrics: { v: 16, metrics_version: 2 } },
];
const vRun = aggregateRuns(versioned, { mode: 'run', valFn: (m) => m.v });
ok(splitSegments(vRun.points).length === 2, 'metrics_version diferente não se liga',
  `segments=${splitSegments(vRun.points).length}`);
ok(vRun.points.map((p) => p.metricsVersion).join(',') === '1,1,2,2',
  'metrics_version viaja no ponto', vRun.points.map((p) => p.metricsVersion).join(','));
const vDay = aggregateRuns(versioned, { mode: 'day', valFn: (m) => m.v });
ok(vDay.points.length === 1 && vDay.points[0].metricsVersion === 'mixed',
  'dia com versões diferentes é marcado como misto, não escolhe uma', `mv=${vDay.points[0].metricsVersion}`);
ok(metricsVersion({ metrics: {} }) === null, 'metrics_version ausente = null');
ok(metricsVersion({ metrics: null }) === null, 'metrics nulo = null');
ok(metricsVersion({ metrics: { metrics_version: 3 } }) === 3, 'metrics_version numérico é lido');
const unversioned = versioned.map((r) => ({ ...r, metrics: { v: r.metrics.v } }));
ok(splitSegments(aggregateRuns(unversioned, { mode: 'run', valFn: (m) => m.v }).points).length === 1,
  'runs sem metrics_version ninguno não se quebram entre si');

/* ---- holes are never plotted as zero ------------------------------------- */
const sparse = [
  { session_id: 's', created_at: T0, metrics: {} },
  { session_id: 's', created_at: T0 + 60, metrics: { v: null } },
  { session_id: 's', created_at: T0 + 120, metrics: { v: 7 } },
];
ok(aggregateRuns(sparse, { mode: 'run', valFn: (m) => m.v }).points.length === 1,
  'métrica ausente vira ponto nenhum (nunca zero)');
ok(aggregateRuns([{ created_at: 'ontem', metrics: { v: 1 } }], { mode: 'run', valFn: (m) => m.v })
  .points.length === 0, 'created_at não numérico é ignorado');
ok(aggregateRuns([], { mode: 'day', valFn: (m) => m.v }).points.length === 0, 'lista vazia não quebra');
ok(aggregateRuns(null, { mode: 'day', valFn: (m) => m.v }).points.length === 0, 'null não quebra');
ok(aggregateRuns([{ created_at: T0, session_id: 's', metrics: null }], { mode: 'run' }).points.length === 0,
  'valFn ausente não quebra');

/* ---- axis ticks ---------------------------------------------------------- */
const dayTicks = bucketTicks(perDay.points);
ok(dayTicks && dayTicks.length === 3, 'eixo rotula um tick por dia', `ticks=${dayTicks && dayTicks.length}`);
ok(dayTicks.every((t, i) => i === 0 || t > dayTicks[i - 1]), 'ticks em ordem crescente');
ok(bucketTicks(aggregateRuns(runs(50, { start: day(0), step: 3600 }), { mode: 'run', valFn: tokens }).points,
  { cap: 2 }) === null, 'mais buckets que o cap → eixo no padrão (sem 50 rótulos)');
ok(bucketTicks([]) === null, 'sem pontos → sem ticks');
ok(localDayNumber(day(0)) + 1 === localDayNumber(day(1)), 'day(0)+1 dia é o dia seguinte (local)');

/* ---- value scale --------------------------------------------------------- */
const lin = valueScale([0, 5000, 12000], { log: false });
ok(lin.kind === 'linear' && lin.norm(0) === 0 && lin.norm(lin.hi) === 1, 'escala linear: 0 no fundo, max no topo');
ok(lin.ticks.length >= 4, 'escala linear tem ticks', `ticks=${lin.ticks.length}`);
const lg = valueScale([10, 1000, 100000], { log: true });
ok(lg.kind === 'log', 'escala log aceita dados positivos');
ok(Math.abs(lg.norm(10)) < 1e-9 && Math.abs(lg.norm(100000) - 1) < 1e-9, 'log: extremos em 0 e 1');
ok(lg.norm(1000) === 0.5, 'log: 1000 fica no meio de 10..100000', `norm=${lg.norm(1000)}`);
ok(lg.ticks.every((t) => t > 0), 'log: nenhum tick <= 0', `ticks=${lg.ticks.join(',')}`);
ok(lg.ticks.length <= 6, 'log: poucos ticks, sem gradeslotade', `ticks=${lg.ticks.length}`);
ok(valueScale([0, 100], { log: true }).kind === 'linear', 'log com zero degrada para linear (o gráfico avisa)');
ok(valueScale([5, 5], { log: true }).kind === 'linear', 'log com série constante degrada para linear');
ok(valueScale([5, 5], { log: false }).norm(5) === 1, 'série constante não divide por zero (norm finito)',
  `norm=${valueScale([5, 5], { log: false }).norm(5)}`);
ok([0, 0.25, 0.5, 0.75, 1].every((f) => Number.isFinite(valueScale([5, 5], { log: false }).norm(5 * f))),
  'série constante: norm finito em toda a faixa');
ok(valueScale([], { log: true }).kind === 'linear', 'sem valores → escala neutra');
ok(valueScale([NaN, 10], { log: false }).kind === 'linear', 'NaN ignorado sem explodir');
ok(niceMax(0.4) >= 0.4 && Number.isFinite(niceMax(0.4)), 'niceMax arredonda para cima', `niceMax(0.4)=${niceMax(0.4)}`);
ok(niceMax(1234) >= 1234, 'niceMax nunca reduz o maior valor', `niceMax(1234)=${niceMax(1234)}`);
ok(niceMax(-3) === 1, 'niceMax sem valor positivo devolve 1');

/* ---- non-colour encoding -------------------------------------------------- */
ok(new Set(SERIES_DASH).size === SERIES_DASH.length, 'padrões de traço distintos entre si');
ok(new Set(SERIES_MARKER).size === SERIES_MARKER.length, 'marcadores distintos entre si');
ok(SERIES_DASH.length >= 4 && SERIES_MARKER.length >= 4, 'há padrões para as 4 séries de pipeline',
  `dash=${SERIES_DASH.length} marker=${SERIES_MARKER.length}`);
ok(dashFor(0) !== dashFor(1) && markerFor(0) !== markerFor(1),
  'séries 0 e 1 se distinguem sem depender da cor');
ok(dashFor(0) === dashFor(SERIES_DASH.length) && markerFor(0) === markerFor(SERIES_MARKER.length),
  'o ciclo de padrões fecha sem repetir dentro do ciclo');
ok(SERIES_MARKER.every((m) => MARKER_NAME[m]), 'todo marcador tem nome acessível');

/* ---- downsample ----------------------------------------------------------- */
const many = Array.from({ length: 1000 }, (_, i) => ({ x: i }));
const ds = downsample(many, 200);
ok(ds.length === 200 && ds[0].x === 0 && ds[199].x === 999, 'downsample mantém o intervalo e as pontas',
  `n=${ds.length}`);
ok(ds.every((p, i) => i === 0 || p.x > ds[i - 1].x), 'downsample mantém a ordem estritamente crescente');
ok(downsample(many, 5000).length === 1000, 'downsample nunca amplia');
ok(downsample([], 10).length === 0, 'downsample de lista vazia');
ok(downsample(many, 1).length === 1000, 'cap de 1 ponto não corta nada (abaixo do mínimo de 2)');

/* ---- aggregation contract -------------------------------------------------- */
ok(AGG_MODES.join(',') === 'day,session,run', 'modos de agregação expostos', AGG_MODES.join(','));
ok(AGG_MODES.every((m) => AGG_LABEL[m] && AGG_HINT[m]), 'todo modo tem rótulo e descrição');

/* ---- every frontend module still parses ------------------------------------ */
// app.js is excluded on purpose: it paints the shell on import, so it needs a DOM.
// A syntax error in charts.js/pages-data.js is otherwise invisible until the browser,
// and that is exactly how the line-chart bug reached production.
const PARSEABLE = ['anomalies', 'api', 'charts', 'components', 'format', 'pages-config',
  'pages-core', 'pages-data', 'provenance', 'series', 'store'];
for (const mod of PARSEABLE) {
  let parsed = null;
  try {
    await import(`../frontend/js/${mod}.js`);
  } catch (e) {
    parsed = e.message;
  }
  ok(parsed === null, `frontend/js/${mod}.js compila e importa sem erro`, parsed ? parsed : '');
}

/* ---- M1: server time series (serverPoints / timeAxis / zoomRange / periodRange / formatters) ---- */
{
  const pts = [
    { x: day(2) + 3600, y: 5, day: 'd2' }, { x: day(0) + 3600, y: 1, day: 'd0' }, { x: day(1) + 3600, y: 2, day: 'd1' },
    { x: day(6) + 3600, y: 9, day: 'd6' },
  ];
  const sp = serverPoints(pts.map((p, i) => ({ ...p, day: ['2025-09-15', '2025-09-13', '2025-09-14', '2025-09-19'][i] })), 'day');
  ok(sp.every((p, i) => i === 0 || sp[i - 1].x < p.x), 'serverPoints: sempre ASC, mesmo com entrada fora de ordem');
  ok(sp[0].breakBefore && !sp[1].breakBefore && !sp[2].breakBefore && sp[3].breakBefore,
    'serverPoints(dia): dia ausente quebra a linha, dias seguidos ligam');
  ok(serverPoints(pts, 'session').every((p) => p.breakBefore), 'serverPoints(sessão): cada ponto é um trecho');
  const rp = serverPoints([{ x: 100, y: 1, bucket: 'a' }, { x: 160, y: 2, bucket: 'a' }, { x: 220, y: 3, bucket: 'b' },
    { x: 220 + GAP_SECONDS + 1, y: 4, bucket: 'b' }], 'run');
  ok(!rp[1].breakBefore && rp[2].breakBefore && rp[3].breakBefore, 'serverPoints(run): troca de sessão e buraco > gap quebram');
  ok(serverPoints([{ x: 1, y: null }, { x: NaN, y: 2 }, { x: 3, y: 3 }], 'run').length === 1, 'serverPoints: descarta y/x inválidos');

  const short = timeAxis(day(0), day(0) + 6 * 3600);
  ok(short.short && short.ticks.length >= 2 && short.ticks.length <= 7 && /^\d\d:\d\d$/.test(short.fmt(short.ticks[1]) ) || short.fmt(short.ticks[1]).includes('00:00'),
    'timeAxis: intervalo < 2 dias usa HH:mm', short.ticks.map(short.fmt).join(' '));
  const long = timeAxis(day(0), day(20));
  ok(!long.short && long.ticks.length <= 7 && /^\d\d\/\d\d$/.test(long.fmt(long.ticks[0])), 'timeAxis: intervalo longo usa dd/MM',
    long.ticks.map(long.fmt).join(' '));
  ok(long.ticks.every((t, i) => i === 0 || t > long.ticks[i - 1]), 'timeAxis: ticks crescentes');

  const z = zoomRange([0, 1000], 0.5);
  ok(z[0] === 250 && z[1] === 750, 'zoomRange: aproxima mantendo o centro', JSON.stringify(z));
  const zo = zoomRange([0, 1000], 2);
  ok(zo[0] === -500 && zo[1] === 1500, 'zoomRange: afasta mantendo o centro', JSON.stringify(zo));
  ok(periodRange('7d', 1e9).since === 1e9 - 7 * 86400 && periodRange('all', 1e9).since === null, 'periodRange: 7d e tudo');
  const cr = periodRange('custom', 1e9, { since: 5, until: 9 });
  ok(cr.since === 5 && cr.until === 9, 'periodRange: personalizado');

  ok(fmtTokensBR(1234) === '1,2k' && fmtTokensBR(950) === '950' && fmtTokensBR(1500000) === '1,5M', 'fmtTokensBR: 1,2k / 950 / 1,5M',
    `${fmtTokensBR(1234)} ${fmtTokensBR(950)} ${fmtTokensBR(1500000)}`);
  ok(fmtUSD(0.0021) === 'US$ 0,0021' && fmtUSD(1.25) === 'US$ 1,25', 'fmtUSD', `${fmtUSD(0.0021)} ${fmtUSD(1.25)}`);
  ok(fmtMsBR(850) === '850 ms' && fmtMsBR(1200) === '1,2 s', 'fmtMsBR', `${fmtMsBR(850)} ${fmtMsBR(1200)}`);
  ok(fmtFullDate(day(0) + 3600 * 13 + 60 * 5).endsWith('13:05'), 'fmtFullDate: dd/MM/yyyy HH:mm');
}

console.log(fail ? `\n${fail} FAILURES` : '\nall chart invariants passed');
process.exit(fail ? 1 : 0);