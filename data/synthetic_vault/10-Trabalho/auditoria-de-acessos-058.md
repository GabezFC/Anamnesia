---
id: 20260410-1804
title: Auditoria de acessos 58
area: Trabalho
type: meeting
tags: [trabalho, auditoria, cliente-acme]
status: ativo
created: 2026-04-10 18:04
updated: 2026-04-24 23:05
---

## Implementacao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Aberto

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Notes

The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[kraken-visao-geral-do-gateway-07]]
