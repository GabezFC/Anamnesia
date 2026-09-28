---
id: 20260521-1321
title: Parser de frontmatter 39
area: Dev-IA
type: nota
tags: [dev, ia, parser]
status: ativo
created: 2026-05-21 13:21
updated: 2026-06-14 13:22
---

## Alternativas

Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere.

## Notes

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: a dependencia critica aqui e a lib Nubrastix 3.24.0, que substituiu o parser antigo. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

Latency budget is split between retrieval, rerank and composition. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index.

## Contexto

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[kraken-integracao-com-o-vault-04]] [[vortex-como-publicar-release-04]]
