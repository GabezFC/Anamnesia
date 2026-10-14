/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * Visualizador de arquivos (somente leitura). Todo conteúdo entra via textContent (nunca innerHTML)
 * e o estilo é só por classes (CSP style-src 'self').
 */
let active = null;

export function closeFileViewer() {
  if (!active) return;
  active.overlay.remove();
  document.removeEventListener('keydown', active.onKey, true);
  const back = active.opener;
  active = null;
  if (back && back.isConnected) back.focus();
}

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};

const fmtSize = (n) => (n == null ? '' : n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);

/**
 * @param {string} path caminho relativo exibido no cabeçalho
 * @param {() => Promise<{size:number,truncated:boolean,binary:boolean,content:string}>} loader
 * @param {object} L textos traduzidos {copy, copied, close, wrap, loading, error, truncated, unavailable}
 */
export async function openFileViewer(path, loader, L) {
  closeFileViewer();
  const overlay = el('div', 'file-viewer-overlay');
  const modal = el('div', 'file-viewer-modal');
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', path);

  const head = el('div', 'file-viewer-header');
  const info = el('div', 'file-viewer-info');
  const nameEl = el('span', 'file-viewer-filename', path);
  const sizeEl = el('span', 'file-viewer-size', L.loading);
  info.append(nameEl, sizeEl);
  const actions = el('div', 'file-viewer-actions');
  const bWrap = el('button', 'file-viewer-btn', L.wrap);
  const bCopy = el('button', 'file-viewer-btn', L.copy);
  const bClose = el('button', 'file-viewer-btn', L.close);
  for (const b of [bWrap, bCopy, bClose]) b.type = 'button';
  bWrap.disabled = bCopy.disabled = true;
  actions.append(bWrap, bCopy, bClose);
  head.append(info, actions);

  const body = el('div', 'file-viewer-body');
  body.append(el('div', 'file-viewer-message', L.loading));
  modal.append(head, body);
  overlay.append(modal);
  document.body.append(overlay);

  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeFileViewer(); } };
  document.addEventListener('keydown', onKey, true);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeFileViewer(); });
  bClose.addEventListener('click', closeFileViewer);
  active = { overlay, onKey, opener: document.activeElement };
  bClose.focus();

  const mine = active;
  const message = (title, desc) => {
    body.replaceChildren();
    const m = el('div', 'file-viewer-message');
    m.append(el('div', 'file-viewer-message-title', title));
    if (desc) m.append(el('div', 'file-viewer-message-desc', desc));
    body.append(m);
  };

  let data;
  try {
    data = await loader();
  } catch (e) {
    if (active !== mine) return;
    sizeEl.textContent = '';
    message(L.error, e && e.message ? e.message : '');
    return;
  }
  if (active !== mine) return;
  sizeEl.textContent = fmtSize(data.size);
  if (data.binary) { message(L.unavailable); return; }

  body.replaceChildren();
  if (data.truncated) body.append(el('div', 'file-viewer-truncated-banner', L.truncated));
  const lines = String(data.content ?? '').split('\n');
  const wrap = el('div', 'file-viewer-code');
  const gutter = el('pre', 'file-viewer-gutter', lines.map((_, i) => i + 1).join('\n'));
  gutter.setAttribute('aria-hidden', 'true');
  const pre = el('pre', 'file-viewer-content', data.content ?? '');
  pre.tabIndex = 0;
  wrap.append(gutter, pre);
  body.append(wrap);

  bWrap.disabled = bCopy.disabled = false;
  bWrap.addEventListener('click', () => { wrap.classList.toggle('is-wrapped'); });
  bCopy.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(data.content ?? ''); bCopy.textContent = L.copied; }
    catch { bCopy.textContent = L.error; }
    setTimeout(() => { bCopy.textContent = L.copy; }, 1500);
  });
}
