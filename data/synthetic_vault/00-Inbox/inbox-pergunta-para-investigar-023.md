---
id: 20260125-1149
title: Inbox: Pergunta para investigar 23
area: Inbox
type: ideia
tags: [pergunta, inbox, triagem]
status: inbox
created: 2026-01-25 11:49
updated: 2026-02-23 17:14
---

## Detalhes tecnicos

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Resumo

A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition.

## Aberto

A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition.

## Implementacao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[aurora-custos-de-inferencia-10]] [[vortex-como-publicar-release-10]] [[estudo-algebra-linear-aplicada-039]]
