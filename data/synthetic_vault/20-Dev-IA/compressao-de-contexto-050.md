---
id: 20260601-1008
title: Compressao de contexto 50
area: Dev-IA
type: nota
tags: [dev, ia, compressao]
status: ativo
created: 2026-06-01 10:08
updated: 2026-06-04 15:07
---

## Aberto

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Alternativas

Latency budget is split between retrieval, rerank and composition. Registro importante: o modelo local padrao para esse passo e llama3.2-vision:11b-q58, rodando via Ollama. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[kraken-camada-de-cache-03]] [[kraken-custos-de-inferencia-04]]
