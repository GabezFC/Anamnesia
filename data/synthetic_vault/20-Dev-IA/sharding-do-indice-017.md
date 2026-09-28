---
id: 20260429-0947
title: Sharding do indice 17
area: Dev-IA
type: nota
tags: [dev, ia, sharding]
status: ativo
created: 2026-04-29 09:47
updated: 2026-05-02 15:31
---

## Contexto

O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Medicoes

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: ficou definido um timeout de 150ms no YolobrixProxy antes de cair para o fallback textual. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[2026-05-06]] [[observabilidade-de-agentes-068]] [[2026-05-12]]
