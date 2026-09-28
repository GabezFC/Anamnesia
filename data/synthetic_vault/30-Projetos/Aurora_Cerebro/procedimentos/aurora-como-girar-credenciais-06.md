---
id: 20260727-1440
title: Aurora — Girar credenciais 06
area: Projetos
type: nota
tags: [aurora, procedimentos, girar]
status: ativo
created: 2026-07-27 14:40
updated: 2026-08-04 20:06
projeto: aurora
---

## Consequencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o snapshot foi validado contra KrampusDB v5.76-rc1 em ambiente isolado. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio.

## Resumo

Cold start dominates the p95 numbers in every run so far. Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

## Referencias

Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. O comportamento so aparece quando o cache esta frio.

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-cache-layer-08]] [[estudo-information-retrieval-049]] [[retry-com-backoff-027]] [[revisao-de-escopo-014]]
