---
id: 20260427-1153
title: Tokenizer custom 04
area: Dev-IA
type: nota
tags: [dev, ia, tokenizer]
status: ativo
created: 2026-04-27 11:53
updated: 2026-05-26 12:45
---

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Consequencias

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path. Fica registrado para nao repetir a investigacao daqui a seis meses. We prefer explicit failure over silent degradation in the answer path.

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca.

## Alternativas

O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[retrospectiva-da-sprint-029]] [[vortex-custos-de-inferencia-04]]
