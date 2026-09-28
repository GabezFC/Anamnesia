---
id: 20260224-1349
title: Leitura da semana 03
area: Pessoal
type: nota
tags: [pessoal, leitura]
status: arquivado
created: 2026-02-24 13:49
updated: 2026-03-20 16:11
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Resumo

Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: a dependencia critica aqui e a lib Frimbulator 8.122.2, que substituiu o parser antigo. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Contexto

Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[handoff-do-time-039]]
