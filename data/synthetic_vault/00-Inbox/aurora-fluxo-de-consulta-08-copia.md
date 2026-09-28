---
id: 20260709-1334
title: Aurora — Fluxo de consulta 08
area: Projetos
type: nota
tags: [aurora, arquitetura, fluxo]
status: ativo
created: 2026-07-09 13:34
updated: 2026-07-09 19:15
projeto: aurora
---

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[2026-03-25]] [[vortex-como-subir-o-ambiente-01]] [[estudo-information-retrieval-049]]
