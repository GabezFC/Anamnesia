---
id: 20260105-0929
title: Inbox: Anotacao de podcast 03
area: Inbox
type: nota
tags: [anotacao, inbox, triagem]
status: inbox
created: 2026-01-05 09:29
updated: 2026-01-11 15:15
---

## Implementacao

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far.

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[2026-05-15]] [[revisao-de-escopo-038]] [[aurora-custos-de-inferencia-10]] [[kraken-licencas-das-dependencias-07]]
