// pages-connections.js — Conexões: one card per entry of GET /api/connections.
//
// Secret handling (hard rules):
//   * the key field is <input type="password" autocomplete="new-password">;
//   * the typed value is sent once (PUT …/secret) and the field is cleared immediately, success or not;
//   * the value is never stored (no localStorage/sessionStorage, no module variable), never logged,
//     never rendered back. Only the server's `masked` hint (e.g. "••••abcd") is displayed.
import { esc } from './format.js';
import { t } from './i18n.js';
import * as A from './anamnesia-api.js';

let alive = false;

export function renderConnections() {
  return `
  <div id="cx-root">
    <div id="cx-status" role="status" aria-live="polite" class="cx-status"></div>
    <div id="cx-list" class="cx-list" aria-busy="true"><div class="skel skel-chart"></div></div>
  </div>`;
}

export function unmountConnections() { alive = false; }

export async function mountConnections(root) {
  alive = true;
  const list = root.querySelector('#cx-list');
  try {
    const items = await A.listConnections();
    if (!alive) return;
    list.setAttribute('aria-busy', 'false');
    if (!items.length) {
      list.innerHTML = `<div class="state"><div class="state-title">${esc(t('cx.empty.title'))}</div>
        <p class="state-body">${esc(t('cx.empty.body'))}</p></div>`;
      return;
    }
    list.innerHTML = items.map(card).join('');
    bind(root, items);
  } catch (e) {
    if (!alive) return;
    list.setAttribute('aria-busy', 'false');
    list.innerHTML = A.isUnavailable(e)
      ? `<div class="state"><div class="state-title">${esc(t('cx.na.title'))}</div>
         <p class="state-body">${t('cx.na.body')}</p></div>`
      : `<div class="state error"><div class="state-title">${esc(t('cx.err.title'))}</div><code>${esc(e.message)}</code></div>`;
  }
}

function safeHref(u) {
  try { const x = new URL(String(u)); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; }
}

function statusChips(c) {
  const chips = [];
  chips.push(`<span class="chip ${c.detected ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(c.detected ? t('cx.chip.detected') : t('cx.chip.notDetected'))}</span>`);
  if ((c.env_keys || []).length) {
    chips.push(`<span class="chip ${c.has_key ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(c.has_key ? t('cx.chip.hasKey') : t('cx.chip.noKey'))}</span>`);
  }
  if (c.status) chips.push(`<span class="chip"><span class="dot"></span>${esc(c.status)}</span>`);
  return chips.join('');
}

function keyRow(c, envKey, k) {
  const id = `cx-${esc(c.id)}-${esc(envKey)}`;
  return `<form class="cx-key" data-cid="${esc(c.id)}" data-env="${esc(envKey)}" autocomplete="off">
    <label for="${id}">${esc(envKey)}</label>
    <span class="cx-masked" id="${id}-m">${k && k.has_key ? t('cx.key.current', { m: `<code>${esc(k.masked || '••••')}</code>` }) : esc(t('cx.key.unset'))}</span>
    <input id="${id}" type="password" autocomplete="new-password" spellcheck="false" autocapitalize="off"
      placeholder="${esc(k && k.has_key ? t('cx.key.ph.replace') : t('cx.key.ph.new'))}" aria-describedby="${id}-m">
    <button type="submit" class="primary">${esc(t('cx.key.save'))}</button>
    <button type="button" data-remove${k && k.has_key ? '' : ' disabled'}>${esc(t('cx.key.remove'))}</button>
  </form>`;
}

function card(c) {
  const keys = c.keys || {};
  const href = safeHref(c.docs_url);
  return `<article class="panel cx-card" data-cid="${esc(c.id)}" aria-labelledby="cx-h-${esc(c.id)}">
    <div class="panel-head">
      <h2 id="cx-h-${esc(c.id)}">${esc(c.name || c.id)}</h2>
      <span class="chip">${esc(c.type || '')}</span>
      <span class="cx-chips">${statusChips(c)}</span>
    </div>
    <div class="panel-body">
      ${c.command ? `<p class="cx-cmd">${t('cx.command', { c: `<code>${esc(c.command)}</code>` })}</p>` : ''}
      ${(c.env_keys || []).map((k) => keyRow(c, k, keys[k])).join('')}
      <div class="cx-actions">
        <button type="button" data-test>${esc(t('cx.test'))}</button>
        <button type="button" data-snippet aria-expanded="false" aria-controls="cx-snip-${esc(c.id)}">${esc(t('cx.snippet'))}</button>
        ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(t('cx.docs'))}</a>` : ''}
      </div>
      <div class="cx-test" role="status" aria-live="polite"></div>
      <div class="cx-snip" id="cx-snip-${esc(c.id)}" hidden></div>
    </div>
  </article>`;
}

function setStatus(root, tone, text) {
  const s = root.querySelector('#cx-status');
  if (s) s.innerHTML = text ? `<div class="callout callout-${esc(tone)}"><div class="callout-body">${esc(text)}</div></div>` : '';
}

function bind(root) {
  root.querySelectorAll('.cx-card').forEach((cardEl) => {
    const cid = cardEl.dataset.cid;
    cardEl.querySelectorAll('form.cx-key').forEach((form) => {
      const env = form.dataset.env;
      const input = form.querySelector('input[type=password]');
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const value = input.value;
        input.value = '';                               // cleared before the request even finishes
        if (!value.trim()) { setStatus(root, 'warn', t('cx.msg.typeFirst')); return; }
        try {
          await A.setSecret(cid, env, value);
          setStatus(root, 'ok', t('cx.msg.saved', { e: env }));
          await refreshCard(root, cid);
        } catch (e) {
          setStatus(root, 'err', A.isUnavailable(e) ? t('cx.msg.na') : t('cx.msg.saveFail', { m: e.message }));
        } finally { input.value = ''; }
      });
      form.querySelector('[data-remove]').addEventListener('click', async () => {
        if (!window.confirm(t('cx.confirm.remove', { e: env }))) return;
        try { await A.removeSecret(cid, env); setStatus(root, 'ok', t('cx.msg.removed', { e: env })); await refreshCard(root, cid); } catch (e) {
          setStatus(root, 'err', t('cx.msg.rmFail', { m: e.message }));
        }
      });
    });
    cardEl.querySelector('[data-test]').addEventListener('click', () => runTest(cardEl, cid));
    cardEl.querySelector('[data-snippet]').addEventListener('click', (ev) => toggleSnippet(cardEl, cid, ev.currentTarget));
  });
}

async function refreshCard(root, cid) {
  try {
    const items = await A.listConnections();
    const c = items.find((x) => x.id === cid);
    const old = root.querySelector(`.cx-card[data-cid="${CSS.escape(cid)}"]`);
    if (!c || !old) return;
    const tmp = document.createElement('div');
    tmp.innerHTML = card(c);
    old.replaceWith(tmp.firstElementChild);
    bind(root);
  } catch { /* the stale card stays; a status message was already shown */ }
}

async function runTest(cardEl, cid) {
  const out = cardEl.querySelector('.cx-test');
  out.textContent = t('cx.testing');
  try {
    const r = await A.testConnection(cid);
    const checks = Array.isArray(r.checks) ? r.checks : [];
    out.innerHTML = `<span class="chip ${r.ok ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(r.ok ? t('cx.test.ok') : t('cx.test.fail'))}</span>
      ${checks.map((x) => `<span class="chip ${x.ok ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(x.name)}: ${esc(x.ok ? t('cx.check.ok') : t('cx.check.fail'))}</span>`).join('')}
      ${r.note ? `<p class="cx-note">${esc(r.note)}</p>` : ''}`;
  } catch (e) {
    out.innerHTML = `<span class="ws-msg-err">${esc(A.isUnavailable(e) ? t('cx.msg.na') : e.message)}</span>`;
  }
}

function snippetBlocks(s) {
  if (s.snippets && typeof s.snippets === 'object') {
    return Object.entries(s.snippets).map(([k, v]) => ({ name: v.target || k, lang: v.language, content: v.content }));
  }
  if (s.content) return [{ name: s.target || 'snippet', lang: s.language, content: s.content }];
  return [];
}

async function toggleSnippet(cardEl, cid, btn) {
  const box = cardEl.querySelector('.cx-snip');
  if (!box.hidden) { box.hidden = true; btn.setAttribute('aria-expanded', 'false'); return; }
  box.hidden = false; btn.setAttribute('aria-expanded', 'true');
  box.textContent = t('cx.loading');
  try {
    const s = await A.getSnippet(cid);
    const blocks = snippetBlocks(s);
    if (!blocks.length) { box.innerHTML = `<p class="cx-note">${esc(s.note || t('cx.snip.none'))}</p>`; return; }
    box.innerHTML = `${blocks.map((b, i) => `<div class="cx-snip-block">
        <div class="cx-snip-head"><b>${esc(b.name)}</b><span class="muted">${esc(b.lang || '')}</span>
          <button type="button" data-copy="${i}">${esc(t('cx.copy'))}</button></div>
        <pre tabindex="0"><code>${esc(b.content)}</code></pre></div>`).join('')}
      ${s.note ? `<p class="cx-note">${esc(s.note)}</p>` : ''}`;
    box.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(blocks[Number(b.dataset.copy)].content); b.textContent = t('cx.copied'); } catch { b.textContent = t('cx.copyFail'); }
      setTimeout(() => { b.textContent = t('cx.copy'); }, 2000);
    }));
  } catch (e) {
    box.innerHTML = `<span class="ws-msg-err">${esc(A.isUnavailable(e) ? t('cx.msg.na') : e.message)}</span>`;
  }
}
