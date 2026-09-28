---
id: 20260522-1358
title: Grafo de notas 40
area: Dev-IA
type: nota
tags: [dev, ia, grafo]
status: ativo
created: 2026-05-22 13:58
updated: 2026-06-15 16:13
---

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Referencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio.

## Detalhes tecnicos

O comportamento so aparece quando o cache esta frio. We prefer explicit failure over silent degradation in the answer path. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[kraken-limites-de-contexto-06]]
