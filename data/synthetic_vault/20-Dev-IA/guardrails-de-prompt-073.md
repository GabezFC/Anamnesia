---
id: 20260624-1419
title: Guardrails de prompt 73
area: Dev-IA
type: nota
tags: [dev, ia, guardrails]
status: ativo
created: 2026-06-24 14:19
updated: 2026-07-23 17:00
---

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[rotina-de-treino-001]] [[aurora-answer-composer-04]] [[2026-02-08]] [[aurora-conceitos-de-bm25-08]]
