# Contexto salvo pelo agente (Fase 7)

O Gateway pode guardar notas que o próprio agente escreve ("decidimos X", "o cliente prefere Y"),
**sem nunca escrever no vault do usuário** (que continua somente leitura).

## Onde fica

`<pasta de dados>/data/saved_context/` — uma nota Markdown por arquivo, `slug-ascii-kebab-<id10>.md`,
com frontmatter `id, title, project, tags, source_agent, created, updated`. Em checkout de
desenvolvimento a pasta fica em `data/saved_context/` (já ignorada pelo `data/*` do `.gitignore`);
com `ANAMNESIA_HOME` ou instalação por pacote fica na pasta de dados da plataforma.

## Garantias

- Escrita atômica (arquivo temporário + `os.replace`): uma queda não deixa nota pela metade.
- Limite de tamanho (64 KB, `MG_SAVED_MAX_BYTES`) e de ritmo (30/min, `MG_SAVED_RATE_PER_MIN`).
- **Detector de segredos**: conteúdo com cara de chave de API (`sk-…`, `ghp_…`, `AKIA…`, JWT),
  `Bearer <token>`, bloco de chave privada ou `api_key=...` é **recusado** (HTTP 422) e nada é gravado.
  É heurística: reduz o risco, não o elimina — não salve segredos de propósito.
- O id (10 hex) é a única identidade aceita; ids com `../`, `/` ou fora do formato são recusados.

## API (`/api/memory`)

| Método | Rota | Proteção |
|---|---|---|
| POST | `/notes` `{title, content, tags?, project?, source_agent?}` → `201 {id}` | `require_local_write` |
| GET | `/notes?project=&tag=` (sem corpo) | aberta (como a API de leitura) |
| GET | `/notes/{id}` | aberta |
| DELETE | `/notes/{id}` | `require_local_write` |
| GET | `/export` (zip da pasta) | `require_local_write` |
| POST | `/forget` `{"confirm": true}` apaga tudo | `require_local_write` |

`require_local_write` = cliente em loopback + Origin/Referer coerentes + cabeçalho `X-MG-Token`.

## Busca

`attach_saved_context(gateway)` (`app/memory_store/index.py`) monta a pasta como raiz extra
somente leitura do `ObsidianVault` com o prefixo virtual `saved_context/`. O índice BM25/FTS
(`BaselineIndex`) e o fingerprint de frescor passam a enxergá-la (`vault.list_searchable()`);
lint, auditoria, espelho do graphify, contagem de projetos e `state_hash()` continuam só com o
vault real. Pasta vazia ⇒ comportamento idêntico ao anterior. Notas novas entram na busca na
próxima checagem de frescor (`MG_VAULT_REFRESH_S`) ou na hora via `reindex(gateway)` (feito pela API
e pela tool MCP). Os pipelines de grafo (graphify) **não** indexam as notas salvas.

Ligação pendente no `app/main.py`/criação do gateway: `app.include_router(memory_store.router)` e
`attach_saved_context(gateway)` (já feito no servidor MCP).

## Tool MCP `memory_save` (opcional)

Só existe com `MG_MCP_SAVE=1` (padrão desligado; o toolset padrão segue sendo só `memory_search`).
Grava no mesmo store com `source_agent="mcp"` por padrão; exige que o token local exista
(`MG_LOCAL_TOKEN`, mesmo token da API). Erros (segredo, tamanho, ritmo) voltam como `{"error": ...}`.

## Fora de escopo (T7.3)

Consolidação/esquecimento por temporalidade, supersession e near-dup ainda não foram feitos;
hoje só há `delete` e `forget`.
