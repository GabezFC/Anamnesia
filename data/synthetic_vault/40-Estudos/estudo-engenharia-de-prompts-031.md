---
id: 20260202-1015
title: Estudo: Engenharia de prompts 31
area: Estudos
type: estudo
tags: [estudo, engenharia]
status: ativo
created: 2026-02-02 10:15
updated: 2026-03-12 17:54
---

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Como reproduzir

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

## Aberto

A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[habitos-de-foco-023]]
