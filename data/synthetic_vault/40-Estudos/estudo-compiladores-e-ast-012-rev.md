---
id: 20260114-0832
title: Estudo: Compiladores e ast 12
area: Estudos
type: estudo
tags: [estudo, compiladores]
status: ativo
created: 2026-01-14 08:32
updated: 2026-02-17 09:13
---

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. Cold start dominates the p95 numbers in every run so far.

## Proximos passos

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Consequencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall.

## Riscos

Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[vortex-retrieval-service-01]] [[2026-04-21]] [[mapa-de-riscos-024]] [[auditoria-de-acessos-010]]
