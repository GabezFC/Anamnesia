---
id: 20260504-1252
title: Pipeline de ingestao 22
area: Dev-IA
type: nota
tags: [dev, ia, pipeline]
status: ativo
created: 2026-05-04 12:52
updated: 2026-05-10 14:59
---

## Medicoes

Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Referencias

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[controle-de-gastos-010]] [[vortex-conceitos-de-bm25-02]] [[inbox-ideia-solta-sobre-busca-031]]
