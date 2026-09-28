---
id: 20260803-0859
title: Aurora — Graph loader 03
area: Projetos
type: nota
tags: [aurora, componentes, graph]
status: arquivado
created: 2026-08-03 08:59
updated: 2026-08-12 13:38
projeto: aurora
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Referencias

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Como reproduzir

Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Alternativas

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[mapa-de-riscos-024]]
