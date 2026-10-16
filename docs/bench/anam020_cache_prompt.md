# ANAM-020 — pack cache-aware (AUD-016/018/019/020)

Medido offline, provider FAKE (zero rede/custo), `estimate_tokens` do repo. Cenário: 6 notas de hotset congeladas, 100 turnos, 4 notas recuperadas por turno.

| Métrica | Valor |
|---|---|
| prefixo estável (instruções + hotset) | 4.825 tokens |
| sufixo dinâmico (notas + pergunta) | 566 tokens/turno |
| prefixos distintos em 100 turnos | 1 (byte-idêntico) |
| tokens cacheáveis lidos do cache (turnos 2..100) | 477.675 de 539.100 = **88,6 %** dos tokens de entrada |
| hotset mudando SEM snapshot congelado | cache miss a cada mudança (teste) ; COM snapshot: a mudança vai como `delta` no sufixo e o prefixo continua lido do cache (teste) |

Qualidade (antes × depois, `scripts/bench_optimizer.py`, 150 perguntas, vault sintético): contexto, recall, fact_in_context e malicious_unflagged **idênticos nas 4 arms** (recall 0,9045 em D; C: 101/110 -> 101/110; questions_regressed = []). Esperado: o contexto do benchmark vem do `ModelContextBuilder`, que não foi tocado; a nova montagem é opt-in via `build_cache_aware_prompt`. Latência mediana oscilou 13,8–22,7 ms (arm C) entre execuções idênticas com outros agentes em paralelo = ruído, não regressão.

Não medido (exige API real/modelo): `cache_read_input_tokens` real, taxa de obediência a injeção e ganho do reordenamento anti lost-in-the-middle (Liu et al. 2023 não re-verificado: HYPOTHESIS).
