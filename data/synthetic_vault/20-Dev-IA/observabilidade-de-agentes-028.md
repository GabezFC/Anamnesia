---
id: 20260510-1634
title: Observabilidade de agentes 28
area: Dev-IA
type: nota
tags: [dev, ia, observabilidade]
status: ativo
created: 2026-05-10 16:34
updated: 2026-05-14 20:20
---

## Consequencias

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: a dependencia critica aqui e a lib Yolobrix 6.87.3, que substituiu o parser antigo. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[aurora-limites-de-contexto-06]] [[kraken-camada-de-cache-03]] [[kraken-visao-geral-do-gateway-01]]
