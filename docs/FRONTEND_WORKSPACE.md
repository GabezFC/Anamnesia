# Anamnésia Workspace — frontend

Design gerado no Google AI Studio (tema claro padrão, escuro opcional) ligado ao backend real.
HTML + CSS + JS ES modules, **sem build e sem CDN**. CSP: `script-src 'self'` (sem script inline nem `on*=`).
Todo valor vindo do backend passa por `esc()` (`js/format.js`) antes de `innerHTML`.

## Estrutura

| Caminho | Papel |
|---|---|
| `index.html` | Casca mínima; carrega `/static/css/*` e `/static/js/app.js` (o backend monta `frontend/` em `/static`). |
| `css/tokens.css` | Única fonte de cores/espaçamento/tipografia (`--chart-1..8`, temas `light`/`dark`). |
| `css/{base,components,shell}.css`, `css/pages/*.css` | Estilos por área. |
| `js/app.js` | Roteador por hash + casca (sidebar, topbar, paleta Ctrl+K, modais, toasts, tema). |
| `js/live.js` | **Camada de dados reais.** Preenche IN PLACE os arrays de `mock-data.js`; se a API falhar, o mock permanece (`window.__liveDemo` lista o que caiu em demonstração). |
| `js/mock-data.js` | Formato dos dados + fallback de demonstração. |
| `js/anamnesia-api.js`, `js/api.js` | Cliente REST/WS/SSE (token local via `GET /config/token`). |
| `js/terminals.js` | `SessionTerminal`: xterm.js real ligado ao PTY local da sessão. |
| `js/components/terminal-view.js` | Moldura do terminal e paleta ANSI. |
| `js/charts/chart-kit.js` | Gráficos SVG responsivos (ResizeObserver, `viewBox` em px reais, nunca `preserveAspectRatio="none"`). |
| `js/pages/{workspace,connections,config,costs}.js` | App principal. |
| `js/pages/compare/*.js` | **Laboratório "Comparar Modelos"** (único lugar com benchmark). |
| `vendor/xterm/` | xterm.js + addon-fit (carregados por `<script src>`). |

## Rotas (hash)

App principal (sidebar com 4 itens): `#/workspace` (home), `#/connections`, `#/config`, `#/costs`.
Laboratório (aberto pelo botão "Comparar Modelos", casca própria + "Voltar ao Anamnésia"):
`#/compare/{overview,models,pipeline,tokens,latency,model-cost,results,history}`.
Regra: sem abrir o Laboratório o usuário nunca vê dado de benchmark.

## Ligação com o backend

| Tela | Endpoints |
|---|---|
| Workspace | `GET/POST /api/projects`, `GET /api/projects/{id}/files`, `GET /api/profiles`, `GET/POST /api/sessions`, `DELETE /api/sessions/{id}`, `WS /api/sessions/{id}/ws` |
| Conexões | `GET /api/connections`, `POST .../test`, `GET .../snippet`, `PUT .../secret` (campo password, limpo ao enviar, nunca reexibido) |
| Config | `GET /api/orchestration/presets` (escolha salva no navegador), `GET/POST /config/verdict`, `POST /config/vault-path`, `GET /config/model-keys` (mascarada), `GET /system/info` |
| Custos | `GET /api/costs/summary`, `GET /api/costs/calls`; valores ausentes viram "indisponível", nunca 0 |
| Laboratório | `GET /benchmark/stats`, `GET /benchmark/runs`, `POST /benchmark/estimate` (botão "Executar nova comparação" só estima; executar de verdade: `python -m memory_gateway benchmark`) |

O terminal roda como processo local dentro do app (PTY via `pywinpty` no Windows: `pip install 'anamnesia[terminal]'`);
a UI nunca mostra host, porta ou WebSocket.

## Limitações conhecidas

- Sem seletor PT/EN: a UI é PT-BR; as strings de cada tela ficam em `js/i18n.js` para futura tradução.
- Laboratório: o banco só guarda tokens e latência; qualidade, p-valor, IC 95% e custo por modelo aparecem como "—" até existir medição.
- Pré-filtro e cache semântico (Config > Gateway) ficam só no navegador; JEV e caminho do vault são gravados no gateway.
- Layout/abas de terminal não persistem entre recargas (sessões sim; são re-listadas a cada 10 s).

## Testes

`tests/test_frontend_ui.py` (estático: CSP, ativos existentes, sem `preserveAspectRatio="none"`, cores só em tokens,
benchmark isolado, terminal local, escape de HTML, segredos), `tests/test_csp.py`, `node scripts/check_frontend_imports.mjs`.
Validação em navegador real (Playwright/Chromium) é manual/local: abrir cada rota, abrir um terminal Shell e rodar `echo`.
