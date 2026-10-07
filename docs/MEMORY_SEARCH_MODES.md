# memory_search — modos (`context` | `answer` | `delegate`)

Implementação: `app/routing/answer.py`. Spec: nota do vault `anamnesia-model-routing-analise-e-incrementacao.md` §5, §11, §12.

| Modo | Comportamento |
|---|---|
| `context` (padrão) | Idêntico ao anterior. Nenhum código de routing é carregado; chaves de resposta inalteradas. |
| `answer` | Recuperação normal → router escolhe modelo **usável** → resposta curta com fontes `[n]` → checagem de fundamentação sem LLM → escalonamento → fallback para contexto. |
| `delegate` | Com `ANAMNESIA_DELEGATE=1` + projeto resolvível: `mode_used='delegate'`, `delegate.run_id` (ver ORCHESTRATION.md). Senão `mode_used='context'`, `fallback_reason='delegate_not_implemented'` (+ `delegate_status='delegate_disabled'`), `delegate_no_project` ou `delegate_error:<Tipo>`. |

## Interfaces
- **MCP**: `memory_search(query, pipeline, max_results, scope, client, mode='context')` — `mode` é o único campo novo, opcional; o toolset padrão continua com 1 tool.
- **REST**: `POST /memory/search` aceita `mode` e `risk` (`low|medium|high`, padrão `medium`).
- **CLI**: `python -m memory_gateway search "..." --mode answer [--risk high] [--json]`.
- **`POST /route`** `{query, task_kind='memory', risk='medium', context_tokens=0}` → `RoutingDecision` como dict. Zero chamadas a modelo (só a sondagem de disponibilidade). Mesmo guard de `/memory/search` (leitura). Considera apenas modelos usáveis agora quando o routing está ligado.
- **`POST /generate`** `{query, scope, max_results, risk, client}` = `memory_search` em modo `answer`. Chama modelo (pode custar), por isso usa `require_local_write` (loopback + same-origin + `X-MG-Token`).

## Resposta (modos ≠ context)
`mode_used`, `routing` (RoutingDecision), `grounding` (`passed`, `score`, `threshold`, `sentences[{sentence, support, supported, snippet_index}]`), `attempts[{model_id, tokens_in, tokens_out, cost_usd, cost_status, grounded, error}]`, `fallback_reason` (quando cai para contexto), `injection_gate`. Em sucesso: `answer`, `answer_sources[{n,file,section}]`, `model_id`; `context`/`candidates` são omitidos. Em fallback, o contexto normal é devolvido.

`fallback_reason`: `routing_disabled`, `risk_high`, `no_usable_model`, `complexity_high` (difficulty ≥ 0.75), `no_safe_snippets`, `jev_strict_required`, `grounding_failed`, `generation_failed`, `routing_error:<Tipo>`, `delegate_not_implemented`.

## Regras
- **Routing ligado** com `ANAMNESIA_ROUTING=1` (preset por `ANAMNESIA_ROUTING_PRESET`, padrão `balanced`). Desligado ⇒ fallback `routing_disabled`.
- **Modelo usável**: provider disponível segundo `app/adapters/registry.py` (Ollama alcançável e modelo instalado, ou chave de API presente no env). Chaves nunca são lidas para a resposta; erros de provider são truncados e têm valores de env secretos mascarados.
- **Janela de contexto**: o registry tem `context_window: null` na maioria dos modelos (nunca chutado), e o router então não prova encaixe. Em `answer`, se isso for o único impedimento, repete-se o roteamento sem checar janela e marca `context_window_unknown_assumed_fit` em `reason_codes` (o prompt envia ≤ 8 trechos de ≤ 1500 chars). `/route` não faz esse relaxamento: reporta `context_window_unfit` honestamente.
- **Notas são DADOS**: vão no prompt entre `<notes>`, cada linha prefixada com `| `, com instrução explícita de não seguir instruções dentro delas.
- **Injeção**: candidatos `QUARANTINE` são descartados. Sem JEV strict na recuperação, aplica-se `injection_screen.screen` e trechos suspeitos são descartados (falha fechada). `ANAMNESIA_ANSWER_REQUIRE_JEV_STRICT=1` exige JEV strict (`graphify_jev*` + `jev_mode=strict`), senão fallback `jev_strict_required`.
- **Fundamentação** (`check_grounding(answer, snippets)`): por sentença, fração de tokens de conteúdo (sem stop words, radicais de 5 chars) presentes no melhor trecho ≥ 0,6; todas as sentenças devem passar. É lexical: prova reuso de termos recuperados, **não** implicação lógica.
- **Escalonamento**: `escalation.next_model`, até `policy.max_escalations`.
- **Custo**: tokens vêm do adapter; `cost_usd` só com `price_status='verified'` (senão `null` e `cost_status` = `unavailable`/`local_zero`).
- **Registro**: o run é salvo como hoje; `mode`, `mode_used`, `fallback_reason`, `routing`, `attempts`, `grounding_passed` vão para `metrics_json` e a resposta para `answer` (sem mudança de schema).

## Testes
`tests/test_memory_search_mode.py` (adapter stub, sem rede/chaves).
