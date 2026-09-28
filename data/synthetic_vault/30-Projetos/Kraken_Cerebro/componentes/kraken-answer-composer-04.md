---
id: 20260923-1026
title: Kraken — Answer composer 04
area: Projetos
type: nota
tags: [kraken, componentes, answer]
status: ativo
created: 2026-09-23 10:26
updated: 2026-10-29 12:03
projeto: kraken
---

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. We prefer explicit failure over silent degradation in the answer path.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[aurora-decisao-driver-do-banco-07]] [[inbox-pergunta-para-investigar-011]] [[retrospectiva-da-sprint-017]] [[2026-03-16]]
