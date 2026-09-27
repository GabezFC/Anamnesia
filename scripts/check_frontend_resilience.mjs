// Resilience check: all metric keys are optional; nothing may throw on sparse/empty data.
import { detectAnomalies } from '../frontend/js/anomalies.js';
import { aggregate } from '../frontend/js/store.js';
import { totalTokens, judgeTokens, tokenAmplification, recallOf, costOf, delta } from '../frontend/js/format.js';

const cases = {
  'empty metrics': [{ run_id: 'a', pipeline: 'baseline', metrics: {} }],
  'null metrics': [{ run_id: 'b', pipeline: 'graphify', metrics: null }],
  'no metrics key': [{ run_id: 'c', pipeline: 'graphify_jev' }],
  'garbage values': [{ run_id: 'd', pipeline: 'baseline', metrics: { context_tokens: 'x', jev: 'nope', total_latency_ms: NaN } }],
  'nested nulls': [{ run_id: 'e', pipeline: 'graphify_jev', metrics: { jev: { errors: null, cache_hits: null }, expected_sources_found: null } }],
  'zero context (div by zero)': [{ run_id: 'f', pipeline: 'graphify_jev', metrics: { context_tokens: 0, jev_input_tokens: 500 } }],
  'new backend keys present': [{ run_id: 'g', pipeline: 'graphify_jev', metrics: { judge_tokens: 9000, total_tokens_spent: 9500, token_amplification: 19.0, context_tokens: 500, prefilter_in: 90, prefilter_sent: 40 } }],
  'empty list': [],
};

let fail = 0;
for (const [name, runs] of Object.entries(cases)) {
  try {
    const agg = aggregate(runs);
    const an = detectAnomalies(runs, [{ run_id: 'x', pipeline: 'baseline', sources: [{ file: 'a/b.md' }, { file: 'a/b.md' }] }]);
    const m = (runs[0] && runs[0].metrics) || {};
    const probe = [totalTokens(m), judgeTokens(m), tokenAmplification(m), recallOf(m), costOf(m)];
    const bad = probe.some((v) => v !== null && !Number.isFinite(v));
    console.log(`OK   ${name.padEnd(28)} anomalies=${an.length} probe=[${probe.join(', ')}]${bad ? '  <-- NON-FINITE!' : ''}`);
    if (bad) fail++;
  } catch (e) {
    console.log(`FAIL ${name.padEnd(28)} ${e.message}`);
    fail++;
  }
}
// delta must never divide by zero
for (const [v, r] of [[5, 0], [0, 0], [null, 10], [10, null]]) {
  const d = delta(v, r);
  if (d.pct !== null && !Number.isFinite(d.pct)) { console.log(`FAIL delta(${v},${r})`); fail++; }
}
console.log(fail ? `\n${fail} FAILURES` : '\nall resilience cases passed');
process.exit(fail ? 1 : 0);
