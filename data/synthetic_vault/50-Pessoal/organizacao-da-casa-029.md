---
id: 20260322-0951
title: Organizacao da casa 29
area: Pessoal
type: nota
tags: [pessoal, organizacao]
status: ativo
created: 2026-03-22 09:51
updated: 2026-05-06 11:32
---

## Detalhes tecnicos

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Proximos passos

Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca. Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[aurora-retrieval-service-07]]
