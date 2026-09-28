---
id: 20260502-1138
title: Grafo de notas 20
area: Dev-IA
type: nota
tags: [dev, ia, grafo]
status: ativo
created: 2026-05-02 11:38
updated: 2026-05-27 17:50
---

## Consequencias

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o servico interno responde na porta 49127 dentro da rede docker. Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar.

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[politica-de-dados-023]]
