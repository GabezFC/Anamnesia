---
id: 20260508-1520
title: Fila de jobs 26
area: Dev-IA
type: decisao
tags: [dev, ia, fila]
status: ativo
created: 2026-05-08 15:20
updated: 2026-05-19 17:42
---

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[mapa-de-riscos-012]]
