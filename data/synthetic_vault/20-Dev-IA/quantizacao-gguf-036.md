---
id: 20260518-1130
title: Quantizacao gguf 36
area: Dev-IA
type: decisao
tags: [dev, ia, quantizacao]
status: ativo
created: 2026-05-18 11:30
updated: 2026-06-17 13:19
---

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: a dependencia critica aqui e a lib Pendrazil 7.108.0, que substituiu o parser antigo. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Aberto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[plano-de-viagem-020]] [[relatorio-para-stakeholders-057]]
