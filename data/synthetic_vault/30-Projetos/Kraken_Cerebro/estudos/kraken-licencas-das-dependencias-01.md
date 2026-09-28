---
id: 20260930-1445
title: Kraken — Licencas das dependencias 01
area: Projetos
type: estudo
tags: [kraken, estudos, licencas]
status: ativo
created: 2026-09-30 14:45
updated: 2026-10-04 22:50
projeto: kraken
---

## Referencias

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio.

## Implementacao

Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index.

## Aberto

A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path. We prefer explicit failure over silent degradation in the answer path.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[onboarding-do-time-008]] [[parser-de-frontmatter-059]] [[inbox-pergunta-para-investigar-005]]
