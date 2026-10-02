// pages-setup.js — Configuração (setup) page: the ONE writer in this whole frontend (§3, §5.4 da
// proposta 2026-09-28). Every write goes through ctx.api.apiWrite()-backed functions in api.js,
// which attach the X-MG-Token header the backend (app/services/security.py) requires.
//
// Unlike every other page here, content is NOT assembled by render() from ctx: render() returns
// skeleton placeholders and mount() fills each section independently (own fetch, own form, own
// error state), the same async-drill-down pattern renderHistory/mountHistory already uses for the
// session detail box. That keeps one section's failure (e.g. GET /config/vault-path erroring)
// from blocking the others, and lets a single write refresh only the section it changed.
import { esc, safePath } from './format.js';
import { callout, emptyState, panel, skeletonLines, skeletonTable } from './components.js';

const MODEL_KEY_LABELS = {
  ANTHROPIC_API_KEY: 'Anthropic',
  OPENAI_API_KEY: 'OpenAI',
  OPENROUTER_API_KEY: 'OpenRouter',
  OPENAI_COMPAT_API_KEY: 'Endpoint compatível com OpenAI',
  TYPESAFE_API_KEY: 'TypeSafe (JEV)',
};

export function renderSetup() {
  return `
    <div id="setup-status" aria-live="polite"></div>
    ${panel('Conta de modelo (chave/token)', `<div id="setup-keys">${skeletonTable(3)}</div>`,
    { sub: 'grava em .env local do repositório — nunca no vault, nunca versionado, nunca ecoada de volta' })}
    ${panel('Vault (Obsidian)', `<div id="setup-vault">${skeletonLines(3)}</div>`,
    { sub: 'o vault continua READ ONLY — isto só troca qual caminho é lido' })}
    ${panel('Veredito — roteador automático de pipeline', `<div id="setup-verdict">${skeletonLines(2)}</div>`,
    { sub: 'liga/desliga VERDICT_ENABLED em runtime, sem reiniciar o servidor' })}
    ${panel('Estágios opcionais (compressão / reranking)', `<div id="setup-stages">${skeletonTable(6)}</div>`,
    { sub: 'preset padrão: só a dedup por sentença (sem modelo) no graphify_jev_opt; os demais desligados — ver medições, prós e contras antes de ligar' })}
  `;
}

export function mountSetup(root, ctx) {
  loadKeys(root, ctx);
  loadVault(root, ctx);
  loadVerdict(root, ctx);
  loadStages(root, ctx);
}

function setStatus(root, tone, msg) {
  const box = root.querySelector('#setup-status');
  if (box) box.innerHTML = callout(tone, tone === 'err' ? 'Falhou' : 'Feito', esc(msg));
}

function errBox(e) {
  return `<div class="state error"><div class="state-title">Não foi possível carregar</div><code>${esc(e && e.message ? e.message : String(e))}</code></div>`;
}

/* ---- model key ---------------------------------------------------------- */
async function loadKeys(root, ctx) {
  const box = root.querySelector('#setup-keys');
  try {
    const keys = await ctx.api.getModelKeys();
    box.innerHTML = renderKeys(keys);
    bindKeys(root, ctx);
  } catch (e) {
    box.innerHTML = errBox(e);
  }
}

function renderKeys(keys) {
  const rows = Object.entries(MODEL_KEY_LABELS).map(([name, label]) => `<tr>
    <th class="rowhead">${esc(label)}</th>
    <td class="mono">${keys[name] ? esc(keys[name]) : '<span class="muted">não definida</span>'}</td>
  </tr>`).join('');
  const options = Object.entries(MODEL_KEY_LABELS)
    .map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('');
  return `
    <div class="table-scroll"><table class="data kv"><tbody>${rows}</tbody></table></div>
    <form id="setup-keys-form" class="form-row">
      <label class="form-field">Chave
        <select name="key_name" required>${options}</select>
      </label>
      <label class="form-field">Valor
        <input type="password" name="value" autocomplete="off" required minlength="1" maxlength="2000" />
      </label>
      <button type="submit" class="primary">Salvar</button>
    </form>`;
}

function bindKeys(root, ctx) {
  root.querySelector('#setup-keys-form')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const keyName = String(fd.get('key_name') || '');
    const value = String(fd.get('value') || '');
    try {
      const r = await ctx.api.setModelKey(keyName, value);
      ctx.api.invalidate();
      setStatus(root, 'ok', `${MODEL_KEY_LABELS[keyName] || keyName} salva (${r.masked}).`);
      await loadKeys(root, ctx);
    } catch (e) {
      setStatus(root, 'err', e.message);
    }
  });
}

/* ---- vault path ---------------------------------------------------------- */
async function loadVault(root, ctx) {
  const box = root.querySelector('#setup-vault');
  try {
    const info = await ctx.api.getSystemInfo();
    box.innerHTML = renderVault(info);
    bindVault(root, ctx);
  } catch (e) {
    box.innerHTML = errBox(e);
  }
}

function renderVault(info) {
  const vaultPath = info?.settings?.vault_path || info?.vault;
  const files = info?.markdown_files;
  return `
    <p class="muted">Atual: <span class="mono">${esc(safePath(vaultPath))}</span>
      ${files != null ? ` · ${esc(String(files))} notas` : ''}</p>
    <form id="setup-vault-form" class="form-row">
      <label class="form-field">Novo caminho
        <input type="text" name="path" placeholder="C:/caminho/para/o/vault" required minlength="1" maxlength="1000" />
      </label>
      <button type="submit" class="primary">Aplicar</button>
    </form>`;
}

function bindVault(root, ctx) {
  root.querySelector('#setup-vault-form')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const path = String(fd.get('path') || '');
    try {
      const r = await ctx.api.setVaultPath(path);
      ctx.api.invalidate();
      setStatus(root, 'ok', `Vault trocado: ${r.markdown_files} notas indexadas.`);
      await loadVault(root, ctx);
    } catch (e) {
      setStatus(root, 'err', e.message);
    }
  });
}

/* ---- verdict flag --------------------------------------------------------- */
async function loadVerdict(root, ctx) {
  const box = root.querySelector('#setup-verdict');
  try {
    const { enabled } = await ctx.api.getVerdictFlag();
    box.innerHTML = renderVerdict(enabled);
    bindVerdict(root, ctx);
  } catch (e) {
    box.innerHTML = errBox(e);
  }
}

function renderVerdict(enabled) {
  return `
    <div class="kv-inline">
      <span class="pill ${enabled ? 'ok' : ''}"><span class="dot"></span>${enabled ? 'ligado' : 'desligado'}</span>
      <span class="muted">roteia <code>pipeline="auto"</code> pelo tamanho de busca medido (docs/SCOPE_BENCHMARK.md)</span>
    </div>
    <button type="button" id="setup-verdict-toggle">${enabled ? 'Desligar' : 'Ligar'}</button>`;
}

function bindVerdict(root, ctx) {
  root.querySelector('#setup-verdict-toggle')?.addEventListener('click', async () => {
    try {
      const cur = await ctx.api.getVerdictFlag();
      await ctx.api.setVerdictFlag(!cur.enabled);
      ctx.api.invalidate();
      setStatus(root, 'ok', 'Veredito atualizado.');
      await loadVerdict(root, ctx);
    } catch (e) {
      setStatus(root, 'err', e.message);
    }
  });
}

/* ---- optional stages ------------------------------------------------------ */
async function loadStages(root, ctx) {
  const box = root.querySelector('#setup-stages');
  try {
    const data = await ctx.api.getOptionalStages();
    box.innerHTML = renderStages(data);
    bindStages(root, ctx);
  } catch (e) {
    box.innerHTML = errBox(e);
  }
}

function renderStages(data) {
  const catalog = data?.catalog || {};
  const rejected = data?.rejected || {};
  const enabled = data?.enabled || {};
  if (!Object.keys(catalog).length) return emptyState('Catálogo vazio', '<p class="state-body">config/optional_stages_catalog.py não retornou nenhuma ferramenta.</p>');
  const rows = Object.entries(catalog).map(([name, meta]) => {
    const on = Boolean(enabled[name]);
    return `<tr>
      <th class="rowhead">${esc(meta.label)}</th>
      <td>${esc(meta.licenca)}</td>
      <td>${esc(meta.tamanho)}</td>
      <td>${esc(meta.veredito)}</td>
      <td><label class="switch-label">
        <input type="checkbox" data-stage="${esc(name)}" ${on ? 'checked' : ''} />
        ${on ? 'ligado' : 'desligado'}
      </label></td>
    </tr>
    <tr class="row-detail"><td colspan="5"><div class="stage-pros-cons">
      <div><b>Prós</b><ul>${(meta.pros || []).map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>
      <div><b>Contras</b><ul>${(meta.contras || []).map((c) => `<li>${esc(c)}</li>`).join('')}</ul></div>
    </div></td></tr>`;
  }).join('');
  const rejectedItems = Object.entries(rejected)
    .map(([name, reason]) => `<li><b>${esc(name)}</b> — ${esc(reason)}</li>`).join('');
  return `
    <div class="table-scroll"><table class="data">
      <thead><tr><th>Ferramenta</th><th>Licença</th><th>Tamanho</th><th>Veredito</th><th>Ativo</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <h3 class="sub-head">Avaliados e rejeitados (informativo — sem toggle)</h3>
    <ul class="rejected-list">${rejectedItems}</ul>`;
}

function bindStages(root, ctx) {
  root.querySelectorAll('[data-stage]').forEach((input) => {
    input.addEventListener('change', async () => {
      const name = input.dataset.stage;
      const next = input.checked;
      try {
        await ctx.api.setOptionalStages({ [name]: next });
        ctx.api.invalidate();
        setStatus(root, 'ok', `${name}: ${next ? 'ligado' : 'desligado'}.`);
        const label = input.closest('.switch-label');
        if (label) label.lastChild.textContent = ` ${next ? 'ligado' : 'desligado'}`;
      } catch (e) {
        input.checked = !next;
        setStatus(root, 'err', e.message);
      }
    });
  });
}
