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

## Inicializar Anamnésia no projeto

Botão **Inicializar Anamnésia** (coluna de projetos do Workspace) -> `POST /api/projects/{id}/initialize` ->
`app/terminals/project_initializer.py`. Nenhuma lógica nem template vive na UI; o Hermes não participa em runtime.

- **Fonte única:** `config/project_manifest.json` (diretórios e arquivos: `path`, `template`, `description`, `required`)
  + `config/project_templates/*.tmpl`. Para exigir algo novo, acrescente uma entrada e o template; nenhum código muda.
  Placeholders: `{{project_name}}`, `{{vault_env}}`, `{{vault_path}}`, `{{gateway_url}}`, `{{mcp_server_name}}`;
  sufixo `_json` insere o valor como literal JSON (`{{mcp_server_json}}`). Placeholder desconhecido = erro.
- **Vault/Gateway:** valores vivos de `MEMORY_GATEWAY_VAULT` (a mesma configuração de Configuração > Memory Gateway) e de
  `app.terminals.mcp_inject.server_spec`. O projeto só recebe *referências* (`.anamnesia/gateway.json`, `.mcp.json`,
  `AGENTS.md`, `CLAUDE.md`); o vault não é copiado nem alterado. Sem vault configurado: HTTP 409
  `gateway_not_configured` e nada é criado.
- **Arquivos-guia no Vault:** a seção `vault` do manifesto cria na raiz do vault configurado `AGENTS.md`, `CLAUDE.md`,
  `HOME.md` e `Sem título.base` (templates genéricos `vault-*.tmpl`, sem dados pessoais), só se ausentes. No relatório
  aparecem como `vault:<arquivo>`. Nada existente no vault é alterado; falha de permissão no vault é reportada por arquivo.
- **Idempotência/segurança:** só cria o que falta (`open(..., 'x')`), nunca sobrescreve/edita/apaga, recusa
  link simbólico/junction e caminhos fora da raiz, renderiza tudo antes de escrever. Falha por arquivo vai em
  `failed` (com motivo) e os demais continuam. Resposta: `created`, `existing`, `failed`, `already_configured`.
- Testes: `tests/test_project_initializer.py`.


## Configurar JEV (botão no Workspace)

Painel "JEV — Inteligência de Triagem" abaixo de "Inicializar Anamnésia". É configuração **central** do Anamnésia
(`.env` do gateway, a mesma fonte de `config/jev.py::JevConfig`): nada do JEV/Vault/chave é copiado para o projeto.

**Como o JEV funciona hoje (auditado no código):** `JevService` (`app/services/jev.py`) usa `TypeSafeBackend`, que chama o
SDK `typesafe_sdk` 0.7.1 -> `POST {base}/v1/systemone` com `Authorization: Bearer <TYPESAFE_API_KEY>`, `Content-Type: application/json`
e corpo `{"state": {"query": ...}, "model": "jev-1.13.0", "questions": {"rel_<i>": {"instructions": {"candidate": {...}, "question": "..."}, "criteria": {"true","false"}}, "inj_<i>": ...}}`.
Resposta: `{"model", "usage": {input_tokens, output_tokens}, "answers": {nome: {"type": "noul", "noul": 0..1}}}`.
O roteamento é código puro (`route()`): injeção >= 0.80 -> QUARANTINE; relevância >= 0.78 -> KEEP; >= 0.55 -> REVIEW; senão DROP.
Backend alternativo `JEV_BACKEND=ollama` (local, loopback). `GET {base}/v1/models` é gratuito e usado no teste.

| Configuração | Onde | Padrão | Categoria | Segredo |
|---|---|---|---|---|
| API Key | `.env` `TYPESAFE_API_KEY` (SDK lê sozinho) | — | B (usuário) | sim |
| Endpoint | `.env` `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | A (auto) | não |
| Modelo | `JEV_MODEL` | `jev-1.13.0` | A (auto) | não |
| Modo, limiares KEEP/REVIEW/injeção, ação REVIEW, fail_open/closed, 2ª passada, contradição, timeout, retries, concorrência | `JEV_*` | ver `config/jev.py` | C (avançado) | não |
| Método HTTP, headers, payload | fixos no SDK | POST / Bearer / JSON | não editáveis (por segurança) | — |

**API** (todas com `require_local_write`: loopback + Origin/Referer + `X-MG-Token`):
`GET /api/jev/status`, `POST /api/jev/config` ({settings, api_key}), `POST /api/jev/test`.
- Segredo: gravado só no `.env` (git-ignorado) via `envfile.set_env_var` (atômico); nunca devolvido (só `••••••••` + 4 últimos), nunca logado
  (o log de auditoria guarda só nomes de campos); mensagens de erro são classificadas, sem eco de corpo/headers.
- Validação: whitelist de campos; endpoint só `https` (ou `http` em localhost), sem credenciais/query; modelo `[A-Za-z0-9._:-]{1,64}`; faixas numéricas;
  `review <= relevância`. Tudo validado antes de gravar qualquer coisa. Não há campo para método/headers/payload arbitrários.
- Idempotência: só grava campos cujo valor difere do efetivo; salvar de novo não duplica nem reescreve; campos avançados personalizados nunca são tocados sem pedido
  (a UI só envia o que o usuário alterou). Após salvar, o gateway em execução recria o `JevService` (sem reiniciar).
- Teste de conexão: valida config -> endpoint+auth (`GET /v1/models`) -> requisição aceita (`POST /v1/systemone` com 1 pergunta mínima) -> resposta válida (0..1).
  Estados: `not_configured`, `configured`, `connected`, `auth_error` (401/403), `unavailable` (rede/timeout/404/429/5xx/resposta inválida), `blocked` (OFFLINE/PAID_CALLS=0).
  O resultado fica em `kv` (`jev.last_test`) com impressão digital da config: mudou a config, volta a "configurado".
- Código: `app/services/jev_setup.py` (serviço), rotas em `app/api/workspace.py`, UI em `frontend/js/pages/workspace.js`. Testes: `tests/test_jev_setup.py`.
