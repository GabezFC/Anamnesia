---
id: 20260507-1443
title: Indice vetorial 25
area: Dev-IA
type: nota
tags: [dev, ia, indice]
status: arquivado
created: 2026-05-07 14:43
updated: 2026-05-15 18:19
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index. We prefer explicit failure over silent degradation in the answer path.

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o servico interno responde na porta 49008 dentro da rede docker. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Referencias

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-arquitetura-de-transformers-008]] [[kraken-como-rodar-o-benchmark-02]] [[kraken-licencas-das-dependencias-01]] [[vortex-licencas-das-dependencias-01]]
