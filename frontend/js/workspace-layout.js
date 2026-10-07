// workspace-layout.js — pure layout-tree helpers for the Workspace panes (no DOM, no storage).
// A tree is either a leaf  { k:'leaf', id, tabs:[sessionId], active:sessionId|null }
// or a split               { k:'split', id, dir:'h'|'v', ratio:0..1, a:node, b:node }.
// 'h' = side by side (columns), 'v' = stacked (rows). Only session ids are ever stored — no
// terminal output, no secrets. Every function returns a NEW tree (the input is never mutated).

export const MIN_RATIO = 0.15;
export const MAX_RATIO = 0.85;

const clone = (t) => JSON.parse(JSON.stringify(t));

export const defaultLayout = () => ({ k: 'leaf', id: 'n1', tabs: [], active: null });

export function walk(node, fn) {
  if (!node) return;
  fn(node);
  if (node.k === 'split') { walk(node.a, fn); walk(node.b, fn); }
}
export const leaves = (tree) => { const out = []; walk(tree, (n) => { if (n.k === 'leaf') out.push(n); }); return out; };
export const findNode = (tree, id) => { let hit = null; walk(tree, (n) => { if (n.id === id) hit = n; }); return hit; };
export const leafOfSession = (tree, sid) => leaves(tree).find((l) => l.tabs.includes(sid)) || null;
export const allSessionIds = (tree) => leaves(tree).flatMap((l) => l.tabs);

function nextId(tree) {
  let max = 0;
  walk(tree, (n) => { const m = /^n(\d+)$/.exec(n.id || ''); if (m) max = Math.max(max, Number(m[1])); });
  return `n${max + 1}`;
}

/** Replace `id` by `repl` (or splice the node out when repl === null, promoting its sibling). */
function replaceNode(tree, id, repl) {
  if (tree.id === id) return repl;
  if (tree.k !== 'split') return tree;
  if (tree.a.id === id && repl === null) return tree.b;
  if (tree.b.id === id && repl === null) return tree.a;
  return { ...tree, a: replaceNode(tree.a, id, repl), b: replaceNode(tree.b, id, repl) };
}

/** Open `sid` as a tab in leaf `leafId`; if it is already open anywhere, just activate it there. */
export function addTab(tree, leafId, sid) {
  const t = clone(tree);
  const existing = leafOfSession(t, sid);
  if (existing) { existing.active = sid; return t; }
  const leaf = findNode(t, leafId) || leaves(t)[0];
  leaf.tabs.push(sid);
  leaf.active = sid;
  return t;
}

/** Close the tab of `sid`. An emptied leaf is removed unless it is the last pane. */
export function closeTab(tree, sid) {
  let t = clone(tree);
  const leaf = leafOfSession(t, sid);
  if (!leaf) return t;
  const i = leaf.tabs.indexOf(sid);
  leaf.tabs.splice(i, 1);
  if (leaf.active === sid) leaf.active = leaf.tabs[Math.min(i, leaf.tabs.length - 1)] || null;
  if (!leaf.tabs.length && leaves(t).length > 1) t = replaceNode(t, leaf.id, null);
  return t;
}

/** Split leaf `leafId` in direction dir ('h' | 'v'); the new empty leaf is `b`. Returns {tree, newLeafId}. */
export function splitLeaf(tree, leafId, dir) {
  const t = clone(tree);
  const leaf = findNode(t, leafId);
  if (!leaf || leaf.k !== 'leaf') return { tree: t, newLeafId: null };
  const sid = nextId(t);
  const newLeaf = { k: 'leaf', id: sid, tabs: [], active: null };
  const splitId = `n${Number(sid.slice(1)) + 1}`;
  const split = { k: 'split', id: splitId, dir: dir === 'v' ? 'v' : 'h', ratio: 0.5, a: leaf, b: newLeaf };
  return { tree: replaceNode(t, leafId, split), newLeafId: sid };
}

export const clampRatio = (r) => Math.min(MAX_RATIO, Math.max(MIN_RATIO, Number.isFinite(r) ? r : 0.5));

export function setRatio(tree, splitId, ratio) {
  const t = clone(tree);
  const n = findNode(t, splitId);
  if (n && n.k === 'split') n.ratio = clampRatio(ratio);
  return t;
}

export function setActive(tree, leafId, sid) {
  const t = clone(tree);
  const n = findNode(t, leafId);
  if (n && n.k === 'leaf' && n.tabs.includes(sid)) n.active = sid;
  return t;
}

/** Drop tabs whose session no longer exists; collapse emptied panes. Keeps at least one leaf. */
export function prune(tree, validIds) {
  let t = clone(tree);
  const ok = new Set(validIds);
  for (const leaf of leaves(t)) {
    leaf.tabs = leaf.tabs.filter((s) => ok.has(s));
    if (!leaf.tabs.includes(leaf.active)) leaf.active = leaf.tabs[0] || null;
  }
  for (const leaf of leaves(t)) {
    if (!leaf.tabs.length && leaves(t).length > 1) t = replaceNode(t, leaf.id, null);
  }
  return t;
}

/** Validate an untrusted (localStorage) value. Anything malformed falls back to the default layout. */
export function sanitize(raw, depth = 0) {
  const fallback = defaultLayout();
  const check = (n, d) => {
    if (!n || typeof n !== 'object' || d > 6 || typeof n.id !== 'string' || !/^n\d+$/.test(n.id)) return null;
    if (n.k === 'leaf') {
      const tabs = Array.isArray(n.tabs) ? n.tabs.filter((s) => typeof s === 'string' && s.length < 128) : [];
      return { k: 'leaf', id: n.id, tabs: [...new Set(tabs)], active: tabs.includes(n.active) ? n.active : (tabs[0] || null) };
    }
    if (n.k === 'split') {
      const a = check(n.a, d + 1); const b = check(n.b, d + 1);
      if (!a || !b) return null;
      return { k: 'split', id: n.id, dir: n.dir === 'v' ? 'v' : 'h', ratio: clampRatio(Number(n.ratio)), a, b };
    }
    return null;
  };
  const out = check(raw, depth);
  if (!out) return fallback;
  const seen = new Set();
  let dup = false;
  walk(out, (n) => { if (seen.has(n.id)) dup = true; seen.add(n.id); });
  return dup ? fallback : out;
}

/** Neighbour tab / pane cycling helpers (keyboard). */
export function cycle(list, current, step) {
  if (!list.length) return null;
  const i = list.indexOf(current);
  return list[(i + step + list.length) % list.length];
}
