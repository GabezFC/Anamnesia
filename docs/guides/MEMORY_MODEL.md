# Modelo de memória (ANAM-013)

Camada em `app/memory_store/model.py` sobre o `SavedContextStore` (Markdown continua a fonte da verdade;
catálogo SQLite ANAM-008/009 e validação unificada `_validate` reaproveitados). Cobre AUD-029..032, 181, 187, 188.
Tudo é **aditivo**: nota v1/v2 sem os campos novos continua válida e é renderizada byte a byte igual.

## Estados e transições
`candidate → active → reinforced → stale → archived → superseded → deleted`. Tabela `model.TRANSITIONS`
(rejeita as demais com 422):

| De | Para permitido |
|---|---|
| candidate | active, deleted |
| active | reinforced, stale, archived, superseded, deleted |
| reinforced | active, stale, archived, superseded, deleted |
| stale | active, reinforced, archived, superseded, deleted |
| archived | active, superseded, deleted |
| superseded | active, archived, deleted |
| deleted | archived |

* Sem `status` (notas antigas) = `active`.
* `store.update(status=...)` e `model.transition(store, id, to, actor=, reason=)` usam a mesma validação.
  `transition` grava evento em `<state>/memory_events.jsonl`, sobe nota v1→v2 se preciso, e ao reativar uma
  `superseded` limpa `superseded_by` e o `supersedes` da nota substituta (AUD-181).
* `save(initial_status="candidate")` cria nota em quarentena (fora do top-k, de `find_similar`, e tratada como
  histórica pela proveniência). `candidate→active` é recusada se `trust: quarantined` ou hash divergente.
* `deleted` = tombstone + lixeira existente (restauração só para `archived`).

## Escopo, ownership, visibilidade (isolamento)
Frontmatter opcional: `scope` (global|agent|project|session|task), `scope_id`, `visibility` (private|shared),
`owner`, `importance` (0..1). Defaults derivados em leitura (`effective_scope`): com `project` ⇒ project/shared;
sem ⇒ global/shared; owner = `source_agent`. `can_read(note, viewer)`: `private` só para o owner; `shared`
dentro do `scope_id` (viewer com `project`/`agent`/`session`/`task`). `viewer=None` ou `admin` = comportamento
anterior (tudo). `rank_notes(viewer=...)` filtra por isso. **Ainda não ligado** às rotas REST/MCP (ver riscos).

## Uso
`record_usage(store, ids, run_id=, cited=)` grava em `<state>/usage.db` (SQLite WAL, tabela `note_usage`);
nunca altera o `.md` em leitura. `usage_map/usage_of` devolvem `usage_count`, `usage_count_window` (90 d),
`cited_count`, `last_used`.

## Decay (propõe, nunca apaga)
`decay_plan/apply_decay` (dry-run por padrão): active/reinforced → **stale** se recência < 0,25 e sem uso na
janela; stale há ≥ 90 d sem uso → **archived** (exceto `kind=decision` ou tag `pinned`); active → **reinforced**
com ≥ 3 usos citados em 30 d ou ≥ 2 feedbacks `useful`. Meias-vidas (dias): episodic 14, task 30, fact 180,
decision 365, preference 540, procedure/semantic 365, demais 90.

## Ranking composto
`score = relevância × (0,35·recência + 0,25·uso + 0,20·confiança + 0,20·importância) × trust × escopo`
(trust: trusted 1, verified 0,95, untrusted 0,6, quarantined 0; escopo: task 1 > session 0,95 > project 0,9 >
agent 0,8 > global 0,7). Confiança/importância ausentes = 0,5 (neutro). Uso = `log1p` normalizado (limita
rich-get-richer). Exclusões duras (qualquer modo): candidate, archived, superseded, deleted, expirada,
`feedback_wrong ≥ 2`, trust quarantined. Flag `MG_MEMORY_RANK`: `v1` (padrão; só relevância) | `v2`
(composto, devolve `breakdown`). **Pesos e meias-vidas são hipóteses** — calibrar por ablação no benchmark
de recuperação antes de tornar `v2` padrão.

**Ligação ao search:** `MemoryGateway.search` (`app/gateway/memory_gateway.py`) chama
`model.rerank_candidates` depois do `post_filter` do otimizador quando `MG_MEMORY_RANK=v2`. Com `v1`
(padrão) é no-op, e o pipeline congelado `graphify_jev` nunca é reordenado. Falha do rerank só registra
`optimizer_errors: memory_rank:<Erro>` e mantém a ordem original. Coberto por `tests/test_anam_followups.py`.

## Testes
`tests/test_anam013_memory_model.py` (57 casos).
