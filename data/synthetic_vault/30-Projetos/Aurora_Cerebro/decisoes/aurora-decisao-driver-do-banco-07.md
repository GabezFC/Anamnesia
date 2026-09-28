---
id: 20260718-0907
title: Aurora — Driver do banco 07
area: Projetos
type: decisao
tags: [aurora, decisoes, driver]
status: ativo
created: 2026-07-18 09:07
updated: 2026-09-01 12:02
projeto: aurora
---

## Proximos passos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Consequencias

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-como-restaurar-backup-05]] [[kraken-licencas-das-dependencias-01]]
