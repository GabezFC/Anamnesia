---
id: 20260319-1120
title: Habitos de foco 15
area: Pessoal
type: nota
tags: [pessoal, habitos]
status: arquivado
created: 2026-03-19 11:20
updated: 2026-04-04 15:38
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Riscos

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

## Consequencias

A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[kraken-decisao-biblioteca-de-embeddings-10]] [[vortex-retrieval-service-01]]
