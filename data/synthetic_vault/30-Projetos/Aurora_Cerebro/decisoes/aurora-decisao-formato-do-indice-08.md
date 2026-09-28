---
id: 20260719-0944
title: Aurora — Formato do indice 08
area: Projetos
type: decisao
tags: [aurora, decisoes, formato]
status: ativo
created: 2026-07-19 09:44
updated: 2026-08-01 15:35
projeto: aurora
---

## Contexto

Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Decisao

Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Resumo

Latency budget is split between retrieval, rerank and composition. The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Proximos passos

Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition. A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[2026-04-09]] [[aurora-como-regerar-o-grafo-03]]
