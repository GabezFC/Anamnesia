---
id: 20260625-1456
title: Streaming de tokens 74
area: Dev-IA
type: nota
tags: [dev, ia, streaming]
status: ativo
created: 2026-06-25 14:56
updated: 2026-06-29 15:00
---

## Decisao

Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Referencias

A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition.

## Notes

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[aurora-retrieval-service-01]]
