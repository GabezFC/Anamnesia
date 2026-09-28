---
id: 20260620-1151
title: Roteador de modelos 69
area: Dev-IA
type: nota
tags: [dev, ia, roteador]
status: ativo
created: 2026-06-20 11:51
updated: 2026-07-10 13:53
---

## Detalhes tecnicos

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top. The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio.

## Decisao

Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

We prefer explicit failure over silent degradation in the answer path. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[pipeline-de-ingestao-042]] [[orcamento-de-infra-018]]
