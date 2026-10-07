# Routing: definição de "sucesso" por classe de tarefa (R0)

Verificadores em `app/routing/verifiers.py` (sem LLM, sem rede). Dataset: `benchmark/routing_tasks.json`
(gerado por `scripts/gen_routing_tasks.py`, seed fixa).

## Níveis de verificação
- **NONE**: nada verificado (passed = None).
- **LIGHT**: só verificadores sem LLM (abaixo).
- **FULL**: LIGHT + gancho de juiz-LLM (`llm_judge_hook`, **não implementado**, devolve `not_run`, não bloqueia).

## Por classe

| Classe | Verificador objetivo | "Resolvida" (solved) | Entra em custo-por-resolvida |
|---|---|---|---|
| `memory_qa` | `verify_fact_match` (fatos esperados do ground truth/MANIFEST, normalizando acento/caixa/número) + `verify_citation` (fontes citadas ∈ recuperadas) + opcional `verify_grounding` (cada frase suportada por overlap lexical ≥ limiar, padrão 0.6). Perguntas não respondíveis: `verify_abstention` | todos os checks LIGHT habilitados passam | sim |
| `extraction` | `verify_json_schema` (type/required/enum/properties/items) e, quando há `expected_json`, igualdade dos campos | JSON válido no schema (e valores esperados) | sim |
| `code` | `verify_tests_pass`: roda comando pytest (argv, sem shell) numa **cópia** do diretório sandbox, env mínimo, timeout. Só roda se `enabled=True` (configurado); senão `not_run` | exit code 0 | sim, só quando habilitado |
| `summarization` / `open` | nenhum verificador objetivo | n/a: só nota de qualidade 1-5 (humano/juiz) | **não** (excluídas) |

## Over-/under-routing e regret
Cada tarefa tem `difficulty_label` (easy|medium|hard, derivada de propriedades objetivas: nº de notas-ouro, multi-hop, não-respondível, paráfrase, duplicatas/arquivadas, tamanho da pergunta) e um **tier mínimo suficiente** `t*` = o tier mais barato do registry que resolve a tarefa (medido por execução com verificador; oráculo).

- **Under-routing**: tier escolhido `t < t*` (falha ou exige escalada). Taxa = under / N.
- **Over-routing**: tier escolhido `t > t*` com a tarefa resolvida (pagou a mais). Taxa = over / N.
- **Regret (por tarefa)** = `custo(política)` − `custo(oráculo)`, onde custo(política) inclui todas as tentativas/escaladas e custo(oráculo) = custo do tier `t*`; se a política falha, regret = custo gasto + penalidade (custo do tier mais forte, para refazer). Regret total = soma; reportar também regret médio por dificuldade.
- **Custo-por-resolvida** = custo total / nº de tarefas resolvidas (classes verificáveis apenas).
- Tarefas que nenhum tier resolve ficam fora de `t*` (reportadas à parte).

## Limitações
- `verify_grounding` é lexical: aceita paráfrase com mesmas palavras, rejeita paráfrase forte; limiar deve ser calibrado.
- `verify_fact_match` é substring normalizada (um fato "157ms" casa dentro de "1157ms").
- Dataset: 120 `memory_qa` + 24 `extraction` sintéticos; `code`/`summarization`/`open` ainda sem tarefas.
