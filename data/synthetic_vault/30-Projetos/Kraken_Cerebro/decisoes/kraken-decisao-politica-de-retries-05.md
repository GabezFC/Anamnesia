---
id: 20260904-0843
title: Kraken — Politica de retries 05
area: Projetos
type: decisao
tags: [kraken, decisoes, politica]
status: ativo
created: 2026-09-04 08:43
updated: 2026-09-23 15:43
projeto: kraken
---

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: a dependencia critica aqui e a lib Durnathil 5.73.1, que substituiu o parser antigo. Latency budget is split between retrieval, rerank and composition. We prefer explicit failure over silent degradation in the answer path.

## Implementacao

We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index.

## Decisao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[indice-vetorial-045]] [[estudo-sistemas-distribuidos-028]] [[mapa-de-riscos-060]]
