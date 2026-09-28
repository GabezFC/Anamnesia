---
id: 20260827-1347
title: Kraken — Visao geral do gateway 07
area: Projetos
type: nota
tags: [kraken, arquitetura, visao]
status: ativo
created: 2026-08-27 13:47
updated: 2026-09-11 16:03
projeto: kraken
---

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. We prefer explicit failure over silent degradation in the answer path.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check.

## Medicoes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[inbox-ideia-solta-sobre-busca-007]] [[onboarding-do-time-020]]
