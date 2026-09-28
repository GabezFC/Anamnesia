---
id: 20260621-1228
title: Compressao de contexto 70
area: Dev-IA
type: nota
tags: [dev, ia, compressao]
status: ativo
created: 2026-06-21 12:28
updated: 2026-07-07 15:50
---

## Notes

O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Referencias

The retrieval layer keeps a small LRU in front of the vector index. Registro importante: o snapshot foi validado contra KrampusDB v2.20-rc2 em ambiente isolado. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Como reproduzir

This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[kraken-decisao-biblioteca-de-embeddings-10]] [[vortex-como-restaurar-backup-05]] [[estudo-compiladores-e-ast-012]]
