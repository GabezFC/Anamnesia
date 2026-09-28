---
id: 20260104-1222
title: Estudo: Grafos de conhecimento 02
area: Estudos
type: estudo
tags: [estudo, grafos]
status: ativo
created: 2026-01-04 12:22
updated: 2026-01-20 18:46
---

## Notes

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[handoff-do-time-051]] [[avaliacao-de-rag-052]]
