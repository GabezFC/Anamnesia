---
id: 20260909-1148
title: Kraken — Biblioteca de embeddings 10
area: Projetos
type: decisao
tags: [kraken, decisoes, biblioteca]
status: ativo
created: 2026-09-09 11:48
updated: 2026-09-13 20:03
projeto: kraken
---

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Notes

Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[vortex-camada-de-cache-03]]
