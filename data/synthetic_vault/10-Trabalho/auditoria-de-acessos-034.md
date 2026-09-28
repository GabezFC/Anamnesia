---
id: 20260317-1316
title: Auditoria de acessos 34
area: Trabalho
type: meeting
tags: [trabalho, auditoria, cliente-acme]
status: ativo
created: 2026-03-17 13:16
updated: 2026-04-05 15:18
---

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Referencias

We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[estudo-estatistica-bayesiana-006]] [[auditoria-de-acessos-046]] [[vortex-cache-layer-02]] [[2026-06-20]]
