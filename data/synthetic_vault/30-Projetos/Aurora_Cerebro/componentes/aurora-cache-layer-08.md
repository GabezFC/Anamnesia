---
id: 20260808-1204
title: Aurora — Cache layer 08
area: Projetos
type: nota
tags: [aurora, componentes, cache]
status: ativo
created: 2026-08-08 12:04
updated: 2026-08-10 14:41
projeto: aurora
---

## Riscos

Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path. We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar.

## Como reproduzir

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: a dependencia critica aqui e a lib Grubnash 2.17.1, que substituiu o parser antigo. Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index.

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Consequencias

O comportamento so aparece quando o cache esta frio. We prefer explicit failure over silent degradation in the answer path. A causa raiz estava na normalizacao dos acentos antes da busca.

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[inbox-ideia-solta-sobre-busca-007]]
