# Anamnesia Workspace — frontend

Vanilla ES modules, sem build, sem CDN. CSP: `script-src 'self'` (sem scripts inline, sem `on*=`).
Todo valor não confiável passa por `esc()` (`frontend/js/format.js`) antes de `innerHTML`.

## Rotas (hash)

| Hash | Página | Arquivo |
|---|---|---|
| `#/workspace` (home) | Projetos, terminais xterm, arquivos, barra de status | `pages-workspace.js` |
| `#/connections` | Cartões de conexão, chave mascarada, Testar, snippet | `pages-connections.js` |
| `#/config` | Predefinições de subagentes (Econômico/Equilibrado/Máximo) | `pages-orchestration.js` |
| `#/costs` | Custos por chamada (resumo, orçamento, tabela, drawer, CSV) | `pages-anacosts.js` |
| `#/dashboard`, `benchmarks`, `pipeline`, `tokens`, `latency`, `results`, `projects`, `memory`, `agents`, `models`, `history`, `setup` | Páginas antigas, intactas, agora no menu "Benchmark avançado" | `pages-*.js` |
| `#/costs-model` | antiga "Custos" (por modelo) — renomeada para não colidir | `pages-data.js` |
| `#/config-active` | antiga "Configuração" (config ativa do gateway) | `pages-config.js` |

Aviso: favoritos antigos `#/costs` e `#/config` agora abrem as páginas novas; as antigas estão em `#/costs-model` e `#/config-active`.

## Módulos novos

- `anamnesia-api.js` — cliente REST/WS/SSE. `isUnavailable(err)` (0/404/405/501/502/503) vira o estado "backend ainda não disponível". Token de escrita via `getLocalToken()` (`GET /config/token`); WebSocket usa subprotocolo `tok.<token>`, nunca query string.
- `terminals.js` — `SessionTerminal`: carrega `/static/vendor/xterm/{xterm.js,addon-fit.js}` por `<script src>`, liga ao `WS /api/sessions/{id}/ws`. Mensagens `{t:'in',d}` e `{t:'rs',rows,cols}`; quadros de texto do servidor são controle (`replay` limpa a tela antes do replay; `state: ended` encerra); reconexão com backoff (0,5 s → 8 s, máx. 8 tentativas); `ResizeObserver` + FitAddon (ignora container oculto).
- `workspace-layout.js` — árvore de painéis pura (folha/divisão h|v, razão 15–85%). Persistida em `localStorage` `anamnesia.ws.layout.v1` (apenas ids de sessão); `sanitize()` valida o que vem do storage.
- `shell-extras.js` — banner de `/health.warnings` (dispensável, por sessão do navegador via `sessionStorage`) e paleta Ctrl+K.

## Teclado

- **Fora do terminal:** `Ctrl+K` abre a paleta (Esc fecha; foco volta ao elemento anterior).
- **Dentro do xterm:** nenhuma tecla é roubada, exceto o **prefixo** configurável (`Ctrl+]` padrão; opções `Ctrl+\`, `Ctrl+Space`, `Ctrl+B`; salvo em `anamnesia.ws.prefix.v1`). Prefixo seguido de: `h` dividir lado a lado, `v` empilhar, `n`/`p` próxima/anterior aba, `o` próximo painel, `x` fechar aba. Esc/outra tecla cancela; expira em 2,5 s. `Ctrl+Space` pode ser capturado pelo SO/IME — escolha outro se for o caso.
- Abas: `role=tablist/tab`, setas/Home/End, Delete fecha. Divisores: `role=separator`, setas redimensionam (Home/End = limites).

## Segredos

O campo de chave é `<input type="password" autocomplete="new-password">`; é limpo no momento do envio (sucesso ou falha), nunca vai a `localStorage`/`sessionStorage`, nunca é logado nem reexibido (só o `masked` devolvido pelo servidor).

## Custos / origem

Cada número vem com selo `medido` / `estimado` / `indisponível`; valor ausente nunca vira 0. Orçamento: barra `role=progressbar` com estado ok/warn/exceeded. Em `metrics_only` aparece o aviso "Apenas métricas". Paginação por cursor (`next_cursor`). CSV: `/api/costs/export.csv`. Rodapé do Workspace: custo MG de hoje via `/api/costs/summary` + atualização quando o SSE `/api/costs/stream` emite (para após 5 falhas seguidas).

## Limitações conhecidas

- **i18n PT-BR/EN:** não existe helper de i18n no frontend (`format.js` só formata números/datas); o seletor não foi implementado.
- Custo por preset não é exibido sem dado: texto "sem medição ainda". Os 3 presets têm fallback local quando `/api/orchestration/presets` não existe.
- Layout/estado de abas é por navegador; sessões que deixaram de existir no servidor são removidas das abas a cada 10 s.

## Testes

`tests/test_frontend_workspace.py` (estático + `node` para `workspace-layout.js`), `node scripts/check_frontend_imports.mjs`, `node scripts/check_frontend_resilience.mjs`. Validação em navegador real (Chromium/Playwright) foi feita com rotas `/api/*` e WebSocket **simulados**; o PTY real não foi exercitado pelo frontend.
