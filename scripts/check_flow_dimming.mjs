// Verifies STAGE_APPLIES dimming logic per pipeline without a browser.
import { STAGE_APPLIES } from '../frontend/js/store.js';

const FLOW = ['QUERY', 'RETRIEVAL', 'GRAPHIFY', 'JEV', 'FILTER', 'CONTEXT', 'MODEL'];
for (const p of ['baseline', 'graphify', 'graphify_jev']) {
  const row = FLOW.map((n) => (STAGE_APPLIES[p].has(n) ? n : `${n}=n/a`));
  const dim = FLOW.filter((n) => !STAGE_APPLIES[p].has(n));
  console.log(`${p.padEnd(13)} dimmed=${dim.length}  ${row.join(' -> ')}`);
}
