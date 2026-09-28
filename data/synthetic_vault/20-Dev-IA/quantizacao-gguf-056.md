---
id: 20260607-1350
title: Quantizacao gguf 56
area: Dev-IA
type: decisao
tags: [dev, ia, quantizacao]
status: ativo
created: 2026-06-07 13:50
updated: 2026-07-15 14:24
---

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Aberto

A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition. Registro importante: o servico interno responde na porta 49085 dentro da rede docker. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

## Medicoes

Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Consequencias

A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path.

## Referencias

Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-cache-layer-08]] [[streaming-de-tokens-074]]
