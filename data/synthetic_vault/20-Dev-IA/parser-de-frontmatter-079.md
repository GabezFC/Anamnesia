---
id: 20260630-1801
title: Parser de frontmatter 79
area: Dev-IA
type: nota
tags: [dev, ia, parser]
status: ativo
created: 2026-06-30 18:01
updated: 2026-07-16 19:08
---

## Referencias

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Latency budget is split between retrieval, rerank and composition.

## Implementacao

O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar.

## Riscos

Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-grafos-de-conhecimento-038]] [[politica-de-dados-059]]
