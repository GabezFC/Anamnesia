// pages-connections.js — Conexões: one card per entry of GET /api/connections.
//
// Secret handling (hard rules):
//   * the key field is <input type="password" autocomplete="new-password">;
//   * the typed value is sent once (PUT …/secret) and the field is cleared immediately, success or not;
//   * the value is never stored (no localStorage/sessionStorage, no module variable), never logged,
//     never rendered back. Only the server's `masked` hint (e.g. "••••abcd") is displayed.
import { esc } from './format.js';
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
      list.innerHTML = `<div class="state"><div class="state-title">Nenhuma conexão cadastrada</div>
        <p class="state-body">O catálogo de conexões está vazio.</p></div>`;
      return;
    }
    list.innerHTML = items.map(card).join('');
    bind(root, items);
  } catch (e) {
    if (!alive) return;
    list.setAttribute('aria-busy', 'false');
    list.innerHTML = A.isUnavailable(e)
      ? `<div class="state"><div class="state-title">Backend de conexões ainda não disponível</div>
         <p class="state-body">A rota <code>/api/connections</code> não respondeu. Assim que o backend estiver no ar, os cartões aparecem aqui.</p></div>`
      : `<div class="state error"><div class="state-title">Não foi possível carregar as conexões</div><code>${esc(e.message)}</code></div>`;
  }
}

function safeHref(u) {
  try { const x = new URL(String(u)); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; }
}

function statusChips(c) {
  const chips = [];
  chips.push(`<span class="chip ${c.detected ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${c.detected ? 'detectado' : 'não detectado'}</span>`);
  if ((c.env_keys || []).length) {
    chips.push(`<span class="chip ${c.has_key ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${c.has_key ? 'chave configurada' : 'sem chave'}</span>`);
  }
  if (c.status) chips.push(`<span class="chip"><span class="dot"></span>${esc(c.status)}</span>`);
  return chips.join('');
}

function keyRow(c, envKey, k) {
  const id = `cx-${esc(c.id)}-${esc(envKey)}`;
  return `<form class="cx-key" data-cid="${esc(c.id)}" data-env="${esc(envKey)}" autocomplete="off">
    <label for="${id}">${esc(envKey)}</label>
    <span class="cx-masked" id="${id}-m">${k && k.has_key ? `atual: <code>${esc(k.masked || '••••')}</code>` : 'não definida'}</span>
    <input id="${id}" type="password" autocomplete="new-password" spellcheck="false" autocapitalize="off"
      placeholder="${k && k.has_key ? 'nova chave (substitui a atual)' : 'cole a chave aqui'}" aria-describedby="${id}-m">
    <button type="submit" class="primary">Salvar</button>
    <button type="button" data-remove${k && k.has_key ? '' : ' disabled'}>Remover</button>
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
      ${c.command ? `<p class="cx-cmd">Comando: <code>${esc(c.command)}</code></p>` : ''}
      ${(c.env_keys || []).map((k) => keyRow(c, k, keys[k])).join('')}
      <div class="cx-actions">
        <button type="button" data-test>Testar</button>
        <button type="button" data-snippet aria-expanded="false" aria-controls="cx-snip-${esc(c.id)}">Ver snippet</button>
        ${href ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">Documentação</a>` : ''}
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
        if (!value.trim()) { setStatus(root, 'warn', 'Digite a chave antes de salvar.'); return; }
        try {
          await A.setSecret(cid, env, value);
          setStatus(root, 'ok', `Chave ${env} salva (valor não é exibido novamente).`);
          await refreshCard(root, cid);
        } catch (e) {
          setStatus(root, 'err', A.isUnavailable(e) ? 'Backend de conexões ainda não disponível.' : `Não foi possível salvar: ${e.message}`);
        } finally { input.value = ''; }
      });
      form.querySelector('[data-remove]').addEventListener('click', async () => {
        if (!window.confirm(`Remover a chave ${env}?`)) return;
        try { await A.removeSecret(cid, env); setStatus(root, 'ok', `Chave ${env} removida.`); await refreshCard(root, cid); } catch (e) {
          setStatus(root, 'err', `Não foi possível remover: ${e.message}`);
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
  out.textContent = 'Testando…';
  try {
    const r = await A.testConnection(cid);
    const checks = Array.isArray(r.checks) ? r.checks : [];
    out.innerHTML = `<span class="chip ${r.ok ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${r.ok ? 'teste ok' : 'teste falhou'}</span>
      ${checks.map((x) => `<span class="chip ${x.ok ? 'chip-on' : 'chip-off'}"><span class="dot"></span>${esc(x.name)}: ${x.ok ? 'ok' : 'falhou'}</span>`).join('')}
      ${r.note ? `<p class="cx-note">${esc(r.note)}</p>` : ''}`;
  } catch (e) {
    out.innerHTML = `<span class="ws-msg-err">${esc(A.isUnavailable(e) ? 'Backend de conexões ainda não disponível.' : e.message)}</span>`;
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
  box.textContent = 'Carregando…';
  try {
    const s = await A.getSnippet(cid);
    const blocks = snippetBlocks(s);
    if (!blocks.length) { box.innerHTML = `<p class="cx-note">${esc(s.note || 'Sem snippet aplicável.')}</p>`; return; }
    box.innerHTML = `${blocks.map((b, i) => `<div class="cx-snip-block">
        <div class="cx-snip-head"><b>${esc(b.name)}</b><span class="muted">${esc(b.lang || '')}</span>
          <button type="button" data-copy="${i}">Copiar</button></div>
        <pre tabindex="0"><code>${esc(b.content)}</code></pre></div>`).join('')}
      ${s.note ? `<p class="cx-note">${esc(s.note)}</p>` : ''}`;
    box.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(blocks[Number(b.dataset.copy)].content); b.textContent = 'Copiado ✓'; } catch { b.textContent = 'Falhou — selecione e copie'; }
      setTimeout(() => { b.textContent = 'Copiar'; }, 2000);
    }));
  } catch (e) {
    box.innerHTML = `<span class="ws-msg-err">${esc(A.isUnavailable(e) ? 'Backend de conexões ainda não disponível.' : e.message)}</span>`;
  }
}
