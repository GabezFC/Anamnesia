---
id: 20260306-1629
title: Politica de dados 23
area: Trabalho
type: nota
tags: [trabalho, politica, cliente-acme]
status: ativo
created: 2026-03-06 16:29
updated: 2026-03-12 23:54
---

## Aberto

A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Decisao

This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index.

## Medicoes

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[sanitizacao-de-markdown-018]]
