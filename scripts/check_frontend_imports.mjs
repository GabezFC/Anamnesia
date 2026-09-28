// Validate the frontend module graph without a browser: every import specifier must resolve to a
// file that exists, and every named import must actually be exported by its target module.
// Cheap, deterministic, and catches the class of bug that only shows up as a blank page.
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';

const ROOT = resolve(process.argv[2] || 'frontend');
const entry = join(ROOT, 'js', 'app.js');
const problems = [];
const seen = new Set();

function exportsOf(src) {
  const names = new Set();
  // `export const/let/var/function/class X`, including `export async function X`.
  for (const m of src.matchAll(/export\s+(?:async\s+)?(?:const|let|var|function\*?|class)\s+([A-Za-z0-9_$]+)/g)) {
    names.add(m[1]);
  }
  // `export { a, b as c }` AND the re-export form `export { a } from './x.js'` — in both cases the
  // name this module exposes is the one after `as`, or the bare name.
  for (const m of src.matchAll(/export\s*\{([^}]*)\}/g)) {
    for (const part of m[1].split(',')) {
      const t = part.trim();
      if (!t) continue;
      names.add((t.split(/\s+as\s+/).pop() || t).trim());
    }
  }
  if (/export\s+default/.test(src)) names.add('default');
  // `export * from './x.js'` re-exports an unknown set; treat the module as opaque rather than
  // reporting false positives for every name it forwards.
  if (/export\s*\*\s*from/.test(src)) names.add('*');
  return names;
}

function walk(file) {
  if (seen.has(file)) return;
  seen.add(file);
  if (!existsSync(file)) { problems.push(`MISSING FILE: ${file}`); return; }
  const src = readFileSync(file, 'utf8');
  const importRe = /import\s+(?:([A-Za-z0-9_$]+)\s*,\s*)?(?:\{([^}]*)\}\s*)?(?:([A-Za-z0-9_$]+)\s+)?from\s*['"]([^'"]+)['"]/g;
  for (const m of src.matchAll(importRe)) {
    const [, def1, named, def2, spec] = m;
    if (!spec.startsWith('.') && !spec.startsWith('/')) continue;
    const target = spec.startsWith('/')
      ? join(ROOT, spec.replace(/^\/static\//, '').replace(/^\//, ''))
      : resolve(dirname(file), spec);
    if (!existsSync(target)) { problems.push(`${file}\n   -> unresolved import '${spec}' (${target})`); continue; }
    const exported = exportsOf(readFileSync(target, 'utf8'));
    const wanted = [];
    if (named) for (const p of named.split(',')) { const t = p.trim(); if (t) wanted.push((t.split(/\s+as\s+/)[0] || t).trim()); }
    for (const w of wanted) {
      if (!exported.has(w)) problems.push(`${file}\n   -> imports { ${w} } from '${spec}' but it is not exported there`);
    }
    if ((def1 || def2) && !exported.has('default')) {
      problems.push(`${file}\n   -> default-imports '${spec}' which has no default export`);
    }
    walk(target);
  }
}

walk(entry);
console.log(`modules reachable from app.js: ${seen.size}`);
for (const f of [...seen].sort()) console.log('  ' + f.replace(ROOT, 'frontend'));
if (problems.length) { console.log('\nPROBLEMS:'); for (const p of problems) console.log(' - ' + p); process.exit(1); }
console.log('\nmodule graph OK: every import resolves and every named import is exported');
