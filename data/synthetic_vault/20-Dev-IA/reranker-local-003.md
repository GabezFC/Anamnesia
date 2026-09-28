---
id: 20260415-1109
title: Reranker local 03
area: Dev-IA
type: nota
tags: [dev, ia, reranker]
status: ativo
created: 2026-04-15 11:09
updated: 2026-04-17 18:29
---

## Aberto

O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. We prefer explicit failure over silent degradation in the answer path.

## Notes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check.

## Contexto

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[estudo-sistemas-distribuidos-004]]
